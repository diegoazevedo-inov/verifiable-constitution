# ADR 0002 — Agent evaluation gate keyed to (model, prompt version)

Status: accepted.

Context: model or prompt changes alter behaviour without any code change.
Decision: the agent is called only when the evaluation result whose path is passed to `Workbench` (parameter `eval_file`, a JSON file) records an approved evaluation for the current task, model and prompt version; the prompt version is a hash of the fixed prompt text, so it cannot be forgotten (C8). Without that file the deterministic rule decides (C1). The example ships no evaluation result, so its agent stays off until one is supplied; the checks write one to a temporary directory. Model output is untrusted: only ids in the closed list and contract reason codes are accepted (C2, C9).
Consequences: changing the prompt closes the gate until a new evaluation is approved.
