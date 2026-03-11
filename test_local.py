import json
import os
from shlex import quote

import pytest

from expbench import ExpBench
from prompts import RESPONSE_JSON_PATH


secrets = {
    "api_key": os.getenv("OPENREWARD_API_KEY", ""),
    "openai_api_key": os.getenv("OPENAI_API_KEY", ""),
}

tasks = ExpBench.list_tasks(split="test")


@pytest.mark.parametrize("task", tasks)
@pytest.mark.asyncio
async def test_expected_files(task):
    """
    Check no README.md and no masked files are present
    """
    env = ExpBench(task_spec=task, secrets=secrets)
    try:
        await env.setup()

        output, code = await env.sandbox.run("test ! -f /workspace/README.md")
        assert code == 0

        for file in env.spec.source:
            output, code = await env.sandbox.run(f"test ! -f /workspace/{file}")
            assert code == 0

        # check /workspace/.git exists
        output, code = await env.sandbox.run("test -d /workspace/.git")
        assert code == 0
    finally:
        await env.teardown()


@pytest.mark.parametrize("task", tasks)
@pytest.mark.asyncio
async def test_gold_grading(task):
    """
    Create perfect submission:
    - Diff on workplace is reverse of masking process
    - response.json contains perfect design and conclusion
    Then grade and check this returns perfect score
    """
    env = ExpBench(task_spec=task, secrets=secrets)
    try:
        await env.setup()

        # create perfect codebase by copying masked files from /private/backup_repo/
        for file in env.spec.source:
            file_relative_to_workspace = file.replace("/workspace/", "")
            await env._check_run(f"cp -p /private/backup_repo/{file_relative_to_workspace} /workspace/{file_relative_to_workspace}")

        # create perfect response.json
        perfect_response = {
            "design": env.spec.design_complexity,
            "conclusion": env.spec.conclusion_gt,
        }
        await env._check_run(f"echo {quote(json.dumps(perfect_response))} > {RESPONSE_JSON_PATH}")

        # grade and check this returns perfect score
        res = await env.answer()
        assert res.metadata["design_score"] == 100, res.metadata
        assert res.metadata["conclusion_score"] == 100, res.metadata
        assert res.metadata["setup_score"] == 100, res.metadata
    finally:
        await env.teardown()
