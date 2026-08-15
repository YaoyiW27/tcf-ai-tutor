# pipeline/ — Argo Workflows model-eval → gate → promote

A CI-for-models pipeline: evaluate a **candidate LLM model** with the real writing-grader
regression, **gate** on the result, and **promote** it (record in a registry + roll the backend
to it) only if it passes. Runs on the same kind cluster as the app (`../infra/k8s/`).

The candidate is a hosted Claude model today; this is the same flow that will promote a
**vLLM-served model version** once serving lands.

## Prerequisites
The app deployed by the `tcf` chart (gateway must be Anthropic-backed — the eval makes real
Claude calls). See `../infra/k8s/README.md`.

## Install
```bash
# Argo Workflows (cluster install so Workflows can run in the tcf namespace)
kubectl create namespace argo
kubectl apply -n argo -f https://github.com/argoproj/argo-workflows/releases/download/v3.6.2/install.yaml

# Pipeline: RBAC, the model registry, and the WorkflowTemplate
kubectl apply -f pipeline/rbac.yaml
kubectl apply -f pipeline/model-registry.yaml
kubectl apply -f pipeline/model-eval-workflow.yaml
kubectl apply -f pipeline/model-eval-cronworkflow.yaml   # suspended by default
```

## Run
Submit a Workflow from the template (no argo CLI needed):
```bash
kubectl -n tcf create -f - <<'EOF'
apiVersion: argoproj.io/v1alpha1
kind: Workflow
metadata: { generateName: model-eval- }
spec:
  workflowTemplateRef: { name: model-eval-promote }
  arguments:
    parameters: [ { name: candidate-model, value: claude-sonnet-4-6 } ]
EOF

kubectl -n tcf get wf
# logs for a run:
kubectl -n tcf logs -l workflows.argoproj.io/workflow=<name> --all-containers
```

- **Pass** → the `promote` step appends to the registry and rolls the backend:
  ```bash
  kubectl -n tcf get configmap tcf-model-registry -o jsonpath='{.data.registry}'
  kubectl -n tcf get deploy tcf-backend -o jsonpath='{..containers[?(@.name=="backend")].env}'
  ```
- **Fail** (e.g. `candidate-model=not-a-real-model` → the model call errors) → `report-failure`
  runs, `promote` is skipped, and production is untouched.

## The gate is best-of-N, not a single run
The eval calls a non-deterministic model, so one run is a coin flip — the same candidate can pass
once and fail the next time for reasons that have nothing to do with its quality. The `eval` step
runs `eval-runs` times (default 3) and passes only if at least `eval-required` (default 2) succeed,
so the tolerance is a stated policy rather than an accident of sampling:

```bash
argo submit --from workflowtemplate/model-eval-promote -n tcf \
  -p candidate-model=claude-haiku-4-5 -p eval-runs=5 -p eval-required=4
```

`report-failure` is named for what it does: with `notify-webhook` empty (the default) it writes to
the workflow log and nothing else — nothing reaches a human until you pass one:

```bash
  -p notify-webhook=https://hooks.example.com/...
```

## Notes
- The eval makes real Claude calls (a few cents per run, now ×`eval-runs`). The CronWorkflow stays
  **suspended** so it doesn't run on a schedule; resume it deliberately.
- RBAC (`rbac.yaml`): the workflow ServiceAccount needs `workflowtaskresults` (Argo executor) plus
  `configmaps`/`deployments` patch for the promote step.
