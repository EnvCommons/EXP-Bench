# EXP-Bench

[![OpenReward Environment](https://img.shields.io/badge/%E2%AD%90%20OpenReward-Environment-f7e6cc)](https://openreward.ai/GeneralReasoning/EXP-Bench)

## Description

EXP-Bench evaluates whether AI agents can independently conduct complete research experiments from published AI papers. Given a research question, method description, and an incomplete codebase, agents must formulate hypotheses, design experiments, implement code, execute experiments, and produce conclusions. Tasks are sourced from 50 papers across ICLR 2024 and NeurIPS 2024.

## Capabilities

- Designing experiments with correct independent, dependent, and control variables
- Implementing experimental code from method descriptions
- Executing and debugging research code end-to-end
- Analyzing experimental results and drawing conclusions
- Working within existing codebases with masked source files

## Compute Requirements

Agents are given a sandbox with 8GB of memory and up to 4 CPUs. No GPU is required. The sandbox has network access to clone GitHub repositories and install dependencies.

## License

[CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) (Public Domain), following the original paper.

## Tasks

There are 452 tasks across 50 papers from two conferences:

| Conference | Papers | Tasks |
|------------|--------|-------|
| ICLR 2024 | 23 | ~215 |
| NeurIPS 2024 | 27 | ~237 |

Both `train` and `test` splits currently contain the same 452 tasks.

Each task provides:
- A research **question** to answer
- A **method** description outlining the experimental approach
- Optional **agent instructions** with step-by-step guidance
- A GitHub repository with key source files masked (removed)

The agent must reconstruct the masked code, run the experiment, and submit a JSON response with its experiment design and conclusion.

## Reward Structure

EXP-Bench uses a three-component grading system evaluated by an LLM judge (`gpt-5.4` with reasoning). Each component is scored 0-100:

1. **Design score** -- evaluates whether the agent correctly identified constant, independent, and dependent variables
2. **Conclusion score** -- binary (0 or 100) based on semantic correctness of the conclusion
3. **Setup score** -- evaluates the agent's code changes (git diff) against ground-truth implementation requirements

The final reward is the **harmonic mean** of the three scores, normalized to [0, 1]:

$$r = \frac{1}{100} \cdot \frac{3}{\frac{1}{s_{\text{design}}} + \frac{1}{s_{\text{conclusion}}} + \frac{1}{s_{\text{setup}}}}$$

If any component scores 0, the final reward is 0. This prevents agents from gaming a single dimension while neglecting others.

## Data

Tasks are derived from 50 published AI papers at ICLR 2024 and NeurIPS 2024. Each task references a public GitHub repository. During setup, the environment clones the repository, creates a private backup, and masks (removes) specified source files that the agent must re-implement.

Ground-truth data includes experiment variable specifications (`design_complexity`), expected conclusions (`conclusion_gt`), and implementation requirements (`requirements`) used by the LLM judge for grading.

## Tools

Agents have access to 6 tools:

| Tool | Description |
|------|-------------|
| `bash` | Execute bash commands in the sandbox (working directory: `/workspace`) |
| `view` | Read file contents with optional line range |
| `str_replace` | Replace text in a file (shows diff) |
| `insert` | Insert content at a specific line number (shows diff) |
| `create` | Create a new file with given content |
| `answer` | Submit final response for grading (reads `/workspace/response.json`) |

## Time Horizon

EXP-Bench is a long-horizon, multi-turn environment. Agents typically require many tool calls to explore the codebase, implement missing code, install dependencies, run experiments, debug failures, and produce results. The agent must also create a reproducibility script (`reproduce_exp_bench.sh`).

## Environment Difficulty

EXP-Bench is a challenging benchmark. The original paper reports that individual grading components occasionally achieve 20-35% accuracy, but only 0.5% of end-to-end experiments succeed across evaluated models.

## Other Environment Requirements

EXP-Bench requires:
- **OpenReward API key** (`api_key`) -- for sandbox provisioning
- **OpenAI API key** (`openai_api_key`) -- for LLM-based grading

## Safety

Agents operate within a sandboxed environment with network access (required for cloning repositories and installing dependencies). The environment does not expose agents to sensitive data or systems beyond public GitHub repositories. The primary risk is computational resource consumption from arbitrary code execution, which is mitigated by sandbox resource limits.

## Citations

```bibtex
@inproceedings{kon2025expbench,
  title     = {EXP-Bench: Can AI Conduct AI Research Experiments?},
  author    = {Kon, Patrick Tser Jern and Liu, Jiachen and Zhu, Xinyi and Ding, Qiuyi and Peng, Jingjia and Xing, Jiarong and Huang, Yibo and Qiu, Yiming and Srinivasa, Jayanth and Lee, Myungjin and Chowdhury, Mosharaf and Zaharia, Matei and Chen, Ang},
  booktitle = {The Fourteenth International Conference on Learning Representations (ICLR)},
  year      = {2026},
  url       = {https://arxiv.org/abs/2505.24785}
}
```
