import base64
import json
from shlex import quote
import time
from pathlib import Path
import random
import traceback
from typing import Any, List
from pydantic import BaseModel
from logging import getLogger

from openai import AsyncOpenAI
import requests
import tiktoken

from openreward.environments import Environment, JSONObject, ToolOutput, terminal, tool, TextBlock
from openreward import AsyncOpenReward, SandboxSettings
from prompts import (
    AGENT_WORKSPACE_PATH,
    EVALUATED_AGENT_SYSTEM_PROMPT,
    JUDGE_DESIGN_AND_CONCLUSION_PROMPT,
    JUDGE_IMPLEMENTATION_PROMPT,
    JUDGE_IMPLEMENTATION_PROMPT_PARTIAL,
    REPRODUCTION_SCRIPT_PATH,
    RESPONSE_JSON_PATH,
)

logger = getLogger(__name__)
enc = tiktoken.get_encoding("o200k_base")


def get_file_from_github(repo_url, file_path, branches=("main", "master")):
    # Normalize URL
    repo_url = repo_url.rstrip("/")
    if repo_url.endswith(".git"):
        repo_url = repo_url[:-4]

    parts = repo_url.split("/")
    if len(parts) < 2:
        raise ValueError("Invalid GitHub repo URL")

    # Strip /workspace from file_path:
    if file_path.startswith("/workspace"):
        file_path = file_path[len("/workspace"):]

    user, repo = parts[-2], parts[-1]

    for branch in branches:
        raw_url = f"https://raw.githubusercontent.com/{user}/{repo}/{branch}/{file_path}"
        response = requests.get(raw_url)
        if response.status_code == 200:
            return response.text

    raise Exception(f"File not found in branches {branches} for repo {repo_url}")

def concatenate_setup_scripts(repo_url: str, setup_scripts: list[str]) -> str:
    """
    Concatenate setup scripts from a GitHub repository into a single string.

    Args:
        repo_url (str): The URL of the GitHub repository.
        setup_scripts (List[str]): A list of file paths to the setup scripts.

    Returns:
        str: A single string containing the concatenated setup scripts. It will be formatted like such:
        ```
        name_of_source_file_1:

        #!/bin/bash
        # ...
        # ...
        # ...

        name_of_source_file_2:

        #!/bin/bash
        # ...
        # ...
        # ...
        ```
    """

    concatenated_setup_scripts = ""
    for script in setup_scripts:
        concatenated_setup_scripts += f"{script}:\n\n"
        concatenated_setup_scripts += get_file_from_github(repo_url, script) + "\n\n"
    return concatenated_setup_scripts

def extract_setup_scripts(source: list[str] | None, repo_url: str):
    if source:
        # Concatenate the setup scripts into a single string:
        concatenated_setup_scripts = concatenate_setup_scripts(repo_url, source)
    else:
        concatenated_setup_scripts = ""

    return concatenated_setup_scripts

class TaskSpec(BaseModel):
  id: str
  question: str
  method: str
  agent_instructions: str
  design_complexity: dict[str, Any]
  conclusion_gt: str
  requirements: list[str] | str

  repo_url: str
  max_response_length: int | None = None

  source: list[str]

  execute_in_new_environment: bool = False

class BashParams(BaseModel, extra="forbid"):
    command: str

class ViewParams(BaseModel, extra="forbid"):
    path: str
    start: int | None = None  # 1-indexed inclusive
    end: int | None = None    # 1-indexed inclusive

class StrReplaceParams(BaseModel, extra="forbid"):
    path: str
    old_str: str
    new_str: str

class CreateParams(BaseModel, extra="forbid"):
    path: str
    content: str

class InsertParams(BaseModel, extra="forbid"):
    path: str
    start: int  # 1-indexed line number to insert before
    content: str


class ExpBench(Environment):
    def __init__(self, task_spec: JSONObject, secrets: dict[str, str] = {}) -> None:
        super().__init__(task_spec)
        self.spec = TaskSpec.model_validate(task_spec)

        # Validate required secrets
        api_key = secrets.get("api_key")
        if not api_key:
            raise ValueError("OpenReward API key must be provided via secrets parameter")

        openai_api_key = secrets.get("openai_api_key")
        if not openai_api_key:
            raise ValueError("OpenAI API key must be provided via secrets parameter for grading")

        # Initialize grader client
        self.grader_client = AsyncOpenAI(api_key=openai_api_key)

        # Initialize sandbox
        self.sandbox_settings = SandboxSettings(
            environment="GeneralReasoning/EXP-Bench",
            image="generalreasoning/expbench-agent:latest",
            machine_size="2:8",
            block_network=False,
            env={"DEBIAN_FRONTEND": "noninteractive"},
        )
        or_client = AsyncOpenReward(api_key=api_key)
        self.sandbox = or_client.sandbox(self.sandbox_settings)

    async def _check_run(self, cmd: str) -> str:
        """Run command in sandbox and raise on non-zero exit code."""
        output, code = await self.sandbox.run(cmd)
        if code != 0:
            raise RuntimeError(f"Command failed (exit {code}): {cmd}\nOutput: {output}")
        return output

    async def setup(self) -> None:
        """
        1) Start sandbox
        2) Clone repo
        3) Mask repo
        """
        await self.sandbox.start()

        st = time.time()
        # Clone repo
        await self._check_run("mkdir -p /workspace")
        await self._check_run(f"git clone {self.spec.repo_url} /workspace")
        await self._check_run("cd /workspace && git submodule sync")
        await self._check_run("cd /workspace && git submodule update --init --recursive")
        logger.info(f"Cloned repo in {time.time() - st:.2f}s")

        # Create backup in /private/backup_repo/
        await self._check_run("mkdir -p /private/backup_repo")
        await self._check_run("cp -a /workspace/* /private/backup_repo/")

        # Mask repo
        await self._check_run("cd /workspace && git rm --cached README.md -f || true")
        await self._check_run("cd /workspace && rm -f README.md || true")
        for file in self.spec.source:
            file_relative_to_workspace = file.replace("/workspace/", "")
            await self._check_run(f"cd /workspace && git rm --cached {file_relative_to_workspace} -f || true")
            await self._check_run(f"cd /workspace && rm -f {file_relative_to_workspace} || true")
        await self._check_run("cd /workspace && git config --global user.email 'expbench@genrintern.com'")
        await self._check_run("cd /workspace && git config --global user.name 'ExpBench'")
        await self._check_run("cd /workspace && git add . && git commit -m 'Masked repo'")
        logger.info(f"Completed repo setup in {time.time() - st:.2f}s")

    async def get_prompt(self) -> List[TextBlock]:
        return [TextBlock(text=EVALUATED_AGENT_SYSTEM_PROMPT.format(
            question=self.spec.question,
            method=self.spec.method,
            agent_instructions=self.spec.agent_instructions,
            agent_workspace_path=AGENT_WORKSPACE_PATH,
            output_json_path=RESPONSE_JSON_PATH,
            output_script_name=REPRODUCTION_SCRIPT_PATH,
        ))]

    @classmethod
    def list_tasks(cls, split: str) -> list[JSONObject]:
        if split not in {"train", "test"}:
            raise ValueError(f"Unknown split: {split}")

        tasks = []
        dataset_path = Path(__file__).parent / "dataset"
        conferences = [i for i in dataset_path.iterdir() if i.is_dir()]
        for conference in conferences:
            with open(conference / "conference_data.jsonl", "r") as f:
              conference_data = [json.loads(line) for line in f if line.strip()]
            for paper in conference.iterdir():
              if not paper.is_dir():
                  continue

              paper_data = next(i for i in conference_data if i["id"] == paper.name)

              data_files = [i for i in paper.iterdir() if i.is_file()]
              if len(data_files) == 0:
                  logger.warning(f"No data files found for {paper}")
                  continue
              if any("complete_final.json" in i.name for i in data_files):
                data_file = next(i for i in data_files if "complete_final.json" in i.name)
              else:  # pick randomly
                data_file = random.choice(data_files)
              data = json.load(open(data_file))
              for question_idx, question in enumerate(data["questions"]):
                 task_data = TaskSpec(
                    id=f"{paper.name}_{question_idx}",
                    question=question["question"],
                    method=question["method"],
                    agent_instructions=question["agent_instructions"] if "agent_instructions" in question else "",
                    design_complexity=question["design_complexity"],
                    conclusion_gt=question["expected_outcome"],
                    requirements=question["requirements"] if "requirements" in question else question["method"],
                    source=question["masked_source"] if "masked_source" in question else question["source"] if "source" in question else [],
                    repo_url=paper_data["code_url"] if paper_data["code_url"] else paper_data["reproduce_eval"]["code"],
                 )
                 task_data_json = task_data.model_dump()
                 tasks.append(task_data_json)
        return tasks

    @classmethod
    def list_splits(cls) -> list[str]:
        return ["train", "test"]

    @tool
    async def bash(self, params: BashParams) -> ToolOutput:
        """
        Execute a bash command.
        """
        output, code = await self.sandbox.run(f"cd /workspace && {params.command}")
        max_len = self.spec.max_response_length

        if isinstance(max_len, int) and len(output) > max_len:
            output = f"...(truncated)\n{output[-max_len:]}"

        return ToolOutput(
            metadata={"output": output, "exit_code": code},
            blocks=[TextBlock(text=f"{output}\n\n(exit {code})")],
            reward=0.0,
            finished=False,
        )

    @terminal
    @tool
    async def answer(self) -> ToolOutput:
        """
        Compute the final score against the design + conclusion + patch produced
        by the agent.

        Terminal tool: hidden from the agent, which signals it is done by
        replying with an ordinary message instead of calling a tool. The
        message itself is not used — grading reads /workspace/response.json,
        diffs the workspace, and calls the gpt-5.4 judge; this tool takes no
        arguments.
        """
        try:
            # Load agent's response
            response_text, code = await self.sandbox.run(f"cat {RESPONSE_JSON_PATH}")
            if code != 0:
                raise RuntimeError(f"Failed to read {RESPONSE_JSON_PATH}")
            response: dict[str, str] = json.loads(response_text)
            assert response.keys() == {"design", "conclusion"}

            await self._check_run("cd /workspace && git add .")
            await self._check_run(
                "cd /workspace && git diff --binary --no-color HEAD > /tmp/agent.diff"
            )

            patch, code = await self.sandbox.run("cat /tmp/agent.diff")
            if code != 0:
                raise RuntimeError("Failed to read agent.diff")
            assert patch.startswith("diff --git a/")

            prompt = JUDGE_DESIGN_AND_CONCLUSION_PROMPT.format(
                design_gt=self.spec.design_complexity,
                conclusion_gt=self.spec.conclusion_gt,
                design_output=response["design"],
                conclusion_output=response["conclusion"],
            )
            oai_response = await self.grader_client.responses.create(
                model="gpt-5.4",
                reasoning={"effort": "medium"},
                input=[
                    {"role": "user", "content": prompt},
                ],
            )
            design_and_conclusion_completion = oai_response.output_text
            assert design_and_conclusion_completion is not None
            if design_and_conclusion_completion.startswith("```json\n") and design_and_conclusion_completion.endswith("\n```"):
                design_and_conclusion_completion = design_and_conclusion_completion[len("```json\n"):-len("\n```")]
            design_and_conclusion_completion_json: dict[str, str | int] = json.loads(design_and_conclusion_completion)
            assert design_and_conclusion_completion_json.keys() == {"design_evaluation_explanation", "design_score", "design_error_analysis", "conclusion_evaluation_explanation", "conclusion_score", "conclusion_error_analysis"}
            design_score = design_and_conclusion_completion_json["design_score"]
            assert isinstance(design_score, int)
            assert design_score in range(0, 101)
            conclusion_score = design_and_conclusion_completion_json["conclusion_score"]

            setup_scripts = extract_setup_scripts(self.spec.source, self.spec.repo_url)

            num_patch_tokens = len(enc.encode(patch))
            logger.info(f"num_patch_tokens: {num_patch_tokens}")
            if num_patch_tokens > 100000:  # partial evaluation
                patch_chunks = [patch[i:i+100000] for i in range(0, len(patch), 100000)]
                previous_partial_evaluation = ""
                for patch_chunk in patch_chunks:
                    prompt = JUDGE_IMPLEMENTATION_PROMPT_PARTIAL.format(
                        setup_gt=self.spec.requirements,
                        setup_scripts=setup_scripts,
                        setup_output=patch_chunk,
                        previous_partial_evaluation=previous_partial_evaluation,
                    )
                    oai_response = await self.grader_client.responses.create(
                        model="gpt-5.4",
                        reasoning={"effort": "medium"},
                        input=[
                            {"role": "user", "content": prompt},
                        ],
                    )
                    implementation_completion = oai_response.output_text
                    assert implementation_completion is not None
                    if implementation_completion.startswith("```json\n") and implementation_completion.endswith("\n```"):
                        implementation_completion = implementation_completion[len("```json\n"):-len("\n```")]
                    implementation_completion_json: dict[str, str | int] = json.loads(implementation_completion)
                    setup_score = implementation_completion_json["setup_score"]
                    setup_evaluation_explanation = implementation_completion_json["setup_evaluation_explanation"]
                    assert isinstance(setup_evaluation_explanation, str)
                    previous_partial_evaluation = setup_evaluation_explanation
            else:
                prompt = JUDGE_IMPLEMENTATION_PROMPT.format(
                    setup_gt=self.spec.requirements,
                    setup_scripts=setup_scripts,
                    setup_output=patch,
                )
                oai_response = await self.grader_client.responses.create(
                    model="gpt-5.4",
                    reasoning={"effort": "medium"},
                    input=[
                        {"role": "user", "content": prompt},
                    ],
                )
                implementation_completion = oai_response.output_text
                assert implementation_completion is not None
                if implementation_completion.startswith("```json\n") and implementation_completion.endswith("\n```"):
                        implementation_completion = implementation_completion[len("```json\n"):-len("\n```")]
                implementation_completion_json: dict[str, str | int] = json.loads(implementation_completion)
                setup_score = implementation_completion_json["setup_score"]
            assert implementation_completion_json.keys() == {"setup_evaluation_explanation", "setup_score", "setup_error_analysis"}
            assert isinstance(setup_score, int)
            assert setup_score in range(0, 101)

            # reward is harmonic mean of design, conclusion, and setup scores
            # where conclusion_score is 100 if correct, 0 if incorrect
            conclusion_score = 100 if conclusion_score == "correct" else 0
            if min(design_score, conclusion_score, setup_score) == 0:
                reward = 0.0
            else:
                reward = (3 / (1 / design_score + 1 / conclusion_score + 1 / setup_score)) / 100.0

            return ToolOutput(
                metadata={
                  "design_and_conclusion": design_and_conclusion_completion_json,
                  "implementation": implementation_completion_json,
                  "design_score": design_score,
                  "conclusion_score": conclusion_score,
                  "setup_score": setup_score,
                },
                blocks=[TextBlock(text=f"Design and conclusion: {design_and_conclusion_completion}\nImplementation: {implementation_completion}")],
                reward=reward,
                finished=True,
            )

        except Exception:
            logger.error(f"Error grading: {traceback.format_exc()}")
            # Terminal tools always end the episode. finished=False here would
            # leave the rollout in an ambiguous state under the @terminal flow —
            # there is no retry path once the assistant's message has been
            # routed through call_terminal_tool.
            return ToolOutput(
                metadata={"error": f"Error grading: {traceback.format_exc()}"},
                blocks=[TextBlock(text=f"Error grading: {traceback.format_exc()}")],
                reward=0.0,
                finished=True,
            )

    @tool
    async def view(self, params: ViewParams) -> ToolOutput:
        """
        View file contents. Optionally specify a 1-indexed [start, end] line range.
        """
        p = quote(params.path)
        if params.start is not None or params.end is not None:
            start = params.start if params.start is not None else 1
            end = params.end if params.end is not None else '$'
            cmd = f"sed -n '{start},{end}p' {p}"
        else:
            cmd = f"cat {p}"
        output, code = await self.sandbox.run(cmd)
        return ToolOutput(
            metadata={"content": output, "exit_code": code, "path": params.path},
            blocks=[TextBlock(text=output)],
            reward=0.0,
            finished=False,
        )

    @tool
    async def str_replace(self, params: StrReplaceParams) -> ToolOutput:
        """
        Replace all occurrences of old_str with new_str in the given file. Use this tool to edit files.
        """
        path = params.path
        suffix = Path(path).suffix
        backup = f"{path}_old{suffix}"

        py = (
            "from pathlib import Path\n"
            f"p = Path({json.dumps(path)})\n"
            f"old = {json.dumps(params.old_str)}\n"
            f"new = {json.dumps(params.new_str)}\n"
            "text = p.read_text()\n"
            "p.write_text(text.replace(old, new))\n"
        )

        cmd = (
            f"set -e\n"
            f"cp {quote(path)} {quote(backup)}\n"
            f"python3 - << 'PY'\n{py}PY\n"
            f"git diff --no-index {quote(backup)} {quote(path)} || true"
        )

        output, exit_code = await self.sandbox.run(cmd)
        return ToolOutput(
            metadata={"diff": output, "exit_code": exit_code, "backup_path": backup, "path": path},
            blocks=[TextBlock(text=output)],
            reward=0.0,
            finished=False,
        )

    @tool
    async def insert(self, params: InsertParams) -> ToolOutput:
        """
        Insert content at the given 1-indexed line number. Use this tool to edit files.
        """
        path = params.path
        suffix = Path(path).suffix
        backup = f"{path}_old{suffix}"

        py = (
            "from pathlib import Path\n"
            "import sys\n"
            f"p = Path({json.dumps(path)})\n"
            f"start = int({json.dumps(params.start)})\n"
            f"content = {json.dumps(params.content)}\n"
            "if not p.exists():\n"
            "    p.parent.mkdir(parents=True, exist_ok=True)\n"
            "    p.write_text('')\n"
            "text = p.read_text()\n"
            "lines = text.splitlines(keepends=True)\n"
            "idx = max(0, min(start - 1, len(lines)))\n"
            "new_text = ''.join(lines[:idx]) + content + ''.join(lines[idx:])\n"
            "p.write_text(new_text)\n"
        )

        cmd = (
            f"set -e\n"
            f"if [ -f {quote(path)} ]; then cp {quote(path)} {quote(backup)}; "
            f"else mkdir -p $(dirname {quote(path)}); : > {quote(path)}; cp {quote(path)} {quote(backup)}; fi\n"
            f"python3 - << 'PY'\n{py}PY\n"
            f"git diff --no-index {quote(backup)} {quote(path)} || true"
        )

        output, _ = await self.sandbox.run(cmd)
        return ToolOutput(
            metadata={"diff": output, "exit_code": 0, "backup_path": backup, "path": path, "start": params.start},
            blocks=[TextBlock(text=output)],
            reward=0.0,
            finished=False,
        )

    @tool
    async def create(self, params: CreateParams) -> ToolOutput:
        """
        Create a file with the given content.
        """
        path = params.path
        path_q = quote(path)
        b64 = base64.b64encode(params.content.encode()).decode()
        # Use base64 to avoid here-doc delimiter collisions and escaping issues
        cmd = (
            f"set -e; "
            f"mkdir -p $(dirname {path_q}); "
            f"printf '%s' {quote(b64)} | base64 -d > {path_q}; "
            f"printf 'Created {path} (%s bytes)\\n' $(wc -c < {path_q})"
        )
        output, code = await self.sandbox.run(cmd)
        msg = output.strip()
        return ToolOutput(
            metadata={"message": msg, "path": path, "bytes": len(params.content), "exit_code": code},
            blocks=[TextBlock(text=msg)],
            reward=0.0,
            finished=False,
        )

    async def teardown(self) -> None:
        if self.sandbox:
            await self.sandbox.stop()
