# infra/k8s/ — Kubernetes (kind + Helm)

Runs the stack on a local Kubernetes cluster: **Postgres + inference gateway + backend**,
deployed by the hand-written Helm chart in `tcf/`. Access is via `kubectl port-forward`
(no Ingress). In-cluster monitoring (kube-prometheus-stack) and an HPA on a gateway metric
are the next sub-slice.

## Prerequisites
`docker`, `kind`, `kubectl`, `helm`.

## Deploy
```bash
# 1) cluster
kind create cluster --name tcf

# 2) images (kind can't pull local images — load them). Reuse the compose-built
#    images, or build fresh:
docker build -t tcf-gateway:dev gateway
docker build -t tcf-backend:dev backend
kind load docker-image tcf-gateway:dev tcf-backend:dev --name tcf

# 3) secrets — copy the example and fill in (gitignored)
cp infra/k8s/tcf/values-secret.example.yaml infra/k8s/tcf/values-secret.yaml
#   set at least secrets.anthropicApiKey

# 4) install
helm install tcf infra/k8s/tcf -n tcf --create-namespace \
  -f infra/k8s/tcf/values-secret.yaml

kubectl -n tcf get pods            # postgres, gateway, backend Running
kubectl -n tcf logs deploy/tcf-backend -c migrate   # migrations + seed ran
```

## Use
```bash
kubectl -n tcf port-forward svc/tcf-backend 8000:8000
curl localhost:8000/health
# submit + grade an answer to exercise backend -> gateway -> Anthropic
```

## Teardown
```bash
helm uninstall tcf -n tcf
kind delete cluster --name tcf
```

## Chart notes (`tcf/`)
- **Migrations run in a backend `initContainer`** (`alembic upgrade head` + seed), not a
  Helm pre-install hook: a pre-install hook would run before Postgres exists, whereas K8s
  retries the initContainer until Postgres is reachable, and both steps are idempotent.
  (A dedicated one-time Job is a future refinement.) The app container overrides the image
  entrypoint to run uvicorn only.
- `DATABASE_URL` is assembled in the Secret (async DSN → the `tcf-postgres` Service);
  `GATEWAY_URL` points at the `tcf-gateway` Service. Images use `IfNotPresent` so pods use
  the `kind load`-ed images.
- Secrets come from a gitignored `tcf/values-secret.yaml`; only `values-secret.example.yaml`
  is committed.
