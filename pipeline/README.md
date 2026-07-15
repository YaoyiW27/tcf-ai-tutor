# pipeline/ — ML Pipeline (Argo Workflows)

**Status: planned.**

Automated model evaluation and deployment on the K8s cluster. Planned contents:

- Argo `Workflow` / `CronWorkflow` YAML: pull model weights → run the evaluation
  benchmark → compare against the current production baseline → on pass, trigger a
  rolling update of the vLLM deployment; on fail, notify (log/Slack webhook).
- An evaluation step that reuses the existing quality evals in `backend/scripts/eval_*`
  (grader/examiner correctness) plus expected-output checks.
- A simple **model registry** (JSON/SQLite): model version, eval scores, deployment timestamp.

See [../docs/architecture-v2-infra.md](../docs/architecture-v2-infra.md).
