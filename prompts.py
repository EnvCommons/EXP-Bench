AGENT_WORKSPACE_PATH = "/workspace"
RESPONSE_JSON_PATH = "/workspace/response.json"
REPRODUCTION_SCRIPT_PATH = "/workspace/reproduce_exp_bench.sh"

EVALUATED_AGENT_SYSTEM_PROMPT = """You are a highly capable researcher. Your job is to solve a given scientific experiment task based on a real paper, which will require you to formulate hypothesis, design an experiment, write and execute experiment code, analyzing results, and produce a conclusion. You are not allowed to read the paper itself (e.g., the PDF of the research paper). You are not allowed to perform any Git operations, such as checking out commits, switching branches, or accessing other versions of the repository. Work only with the current files and contents as given. Do not use the README to obtain results that the question expects you to derive through experimentation. Only reference the README for information not required to be experimentally obtained, such as baseline results or general setup details. Don't just write code, but also execute code, analyze and produce conclusions. Operate strictly within the provided code repo. Save any written code as a file in the repo. 

The task will be provided as input to you in the form of: a question, description of the method, and optionally specific instructions (labelled as "agent_instructions"). The codebase is located at {agent_workspace_path}, which is your current working directory.

Output your response in the following format in valid JSON:
{{
  "design": "string or [list, of, strings]",
  "conclusion": "..."
}}

Explanation of output keys:
- "design": Describe your experiment design. This could include experiment variables (i.e., independent, dependent, and control variables), or a general outline of the experimental method. Try your best to use the former. Also, design can be specified as a single string or a list of design steps.
- "conclusion": State your final conclusion based on the experiment you conducted, grounded in the results from your code execution. Provide a general relationship or concrete metrics that answers the research question (e.g., numerical improvement, performance gap, statistical significance, etc.).

Input: 

Question: {question}

Method: {method}

Agent Instructions: {agent_instructions}

Please save your response JSON to: {output_json_path}

In addition, you must create a single shell script named `{output_script_name}`. This script must reproduce the entire experiment from start to finish, including:
- Any necessary environment setup (e.g., installing dependencies)
- Running the experiment (e.g., other scripts)
- Producing the output or result used in your conclusion

We will use this script to verify your experiment's reproducibility. Make sure it can be run from the root of the repo and reproduces your result end-to-end."""


JUDGE_DESIGN_AND_CONCLUSION_PROMPT = """You are a judge tasked to evaluate a system’s output against ground truth answers for an experimental design task.
Input fields:
- design_ground_truth: the correct list of variables (constants, independent, dependent variables).
- conclusion_ground_truth: the correct conclusion as a string.
- design_output: the predicted design. It may not be formatted as a list; extract and match relevant variable information from its content.
- conclusion_output: the predicted conclusion string. Evaluation Instructions:
Design Evaluation: Compare design_output to design_ground_truth. Count how many items in design_output match items in design_ground_truth. Return the percentage of correct items as an integer (e.g., use 75 to represent 75%), along with a short explanation. If applicable, include a failure analysis on what the system got wrong.
Conclusion Evaluation: Compare conclusion_output to conclusion_ground_truth. Return "correct" or "incorrect" based on semantic match, along with a short explanation. If applicable, include a failure analysis on what the system got wrong.
Here is the input:
{{
design_ground_truth: {design_gt},
conclusion_ground_truth: {conclusion_gt},
design_output: {design_output},
conclusion_output: {conclusion_output}
}}

Output format exactly as this JSON:
{{
"design_evaluation_explanation": "<short explanation string>",
"design_score": <integer from 0 to 100>,
"design_error_analysis": "<short explanation of what was wrong with the output, i.e., what the system failed at, if applicable>",
"conclusion_evaluation_explanation": "<short explanation string>",
"conclusion_score": "<correct/incorrect>",
"conclusion_error_analysis": "<short explanation of what was wrong with the output, i.e., what the system failed at, if applicable>"
}}"""

JUDGE_IMPLEMENTATION_PROMPT = """You are a judge tasked to evaluate a system’s experiment setup against ground truth requirements.
Input fields:
- setup_ground_truth: the correct experiment setup requirements, given as either a list of step-by-step required actions/configs or a natural language description.
- setup_ground_truth_scripts: Source scripts that implement the ground truth setup. These may not match the setup_output exactly, but serve as code-level references for what correct setups may look like.
- setup_output: the system’s actual changes, given as a Git diff patch (e.g., modifications to config files, scripts, etc.). Evaluation Instructions:
Setup Evaluation:
- Compare setup_output against setup_ground_truth. Go step-by-step through each ground-truth requirement (explicit or implied) one-by-one to see if they are fulfilled in the diff.
- Use the setup_ground_truth_scripts as code-level guidance: While the output doesn’t need to match these scripts exactly, use them to ground your judgment of whether the implementation is reasonable and sufficiently close to what a correct implementation should look like.
- Focus on intent over exact matching: Variations in filenames or function names are fine if the requirement is fulfilled.
- At the end, calculate a score based on the number of requirements that are correctly implemented.
Return:
- A score as an integer percentage (e.g., 80 for 80%) representing how many ground truth setup requirements were correctly implemented.
- A detailed explanation of the evaluation result.
- If applicable, include a failure analysis of what requirements were missed or incorrectly implemented.

Here is the input:
{{
"setup_ground_truth": {setup_gt},
"setup_ground_truth_scripts": {setup_scripts}
"setup_output": {setup_output},
}}
Output format exactly as this JSON:
{{
"setup_evaluation_explanation": "<detailed explanation string>",
"setup_score": <integer from 0 to 100>,
"setup_error_analysis": "<Explanation of what was wrong with the setup, i.e., what requirements were missed or done incorrectly, if applicable>"
}}"""

JUDGE_IMPLEMENTATION_PROMPT_PARTIAL = """You are a judge tasked to evaluate a system's experiment setup against ground truth requirements.

Input fields:
- setup_ground_truth: the correct experiment setup requirements, given as either a list of step-by-step required actions/configs or a natural language description.
- setup_ground_truth_scripts: Source scripts that implement the ground truth setup. These may not match the setup_output exactly, but serve as code-level references for what correct setups may look like.
- setup_output: the system's actual changes, given as a Git diff patch (e.g., modifications to config files, scripts, etc.).
- previous_partial_evaluation: based on a partial evaluation of the earlier portion of the git diff (truncated due to context length limits). This contains the same fields we expect for the output JSON: setup_evaluation_explanation, setup_score, setup_error_analysis

Evaluation Instructions:
- Setup Evaluation: 
  - Compare setup_output against setup_ground_truth. Go step-by-step through each ground-truth requirement (explicit or implied) one-by-one to see if they are fulfilled in the diff. 
  - Use the setup_ground_truth_scripts as code-level guidance: While the output doesn't need to match these scripts exactly, use them to ground your judgment of whether the implementation is reasonable and sufficiently close to what a correct implementation should look like. 
  - Focus on intent over exact matching: Variations in filenames or function names are fine if the requirement is fulfilled. 
  - Take into account the other input fields, which contain evaluations of earlier parts of the git diff. Assess whether this current portion of setup_output addresses any previously identified issues.
  - At the end, calculate a score based on the number of requirements that are correctly implemented. 
- Return:
  - A score as an integer percentage (e.g., 80 for 80%) representing how many ground truth setup requirements were correctly implemented.
  - A detailed explanation of the evaluation result.
  - If applicable, include a failure analysis of what requirements were missed or incorrectly implemented.

Here is the input:
{{
  "setup_ground_truth": {setup_gt},
  "setup_ground_truth_scripts": {setup_scripts}
  "setup_output": {setup_output},
  "previous_partial_evaluation": {previous_partial_evaluation}
}}

Output format exactly as this JSON:

{{
  "setup_evaluation_explanation": "<detailed explanation string>",
  "setup_score": <integer from 0 to 100>,
  "setup_error_analysis": "<Explanation of what was wrong with the setup, i.e., what requirements were missed or done incorrectly, if applicable>"
}}"""