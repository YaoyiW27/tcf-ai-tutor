# tcf-ai-tutor — Self-hosted LLM inference stack with observability and automated deployment pipeline

[![CI](https://github.com/YaoyiW27/tcf-ai-tutor/actions/workflows/ci.yml/badge.svg)](https://github.com/YaoyiW27/tcf-ai-tutor/actions/workflows/ci.yml)

An inference gateway — request routing, token and cost accounting, rate limiting, and Prometheus metrics — sits in front of an open-weight LLM served by vLLM. The stack runs on Kubernetes with Prometheus/Grafana monitoring and an Argo Workflows pipeline that evaluates candidate models and rolls them out when they beat the current baseline. The workload it serves is a TCF Canada French-exam tutor: LangGraph writing and speaking graders and a turn-based voice examiner.

Text generation sits behind an `INFERENCE_BACKEND` switch (`anthropic` | `openai` | `vllm`), so the workload runs unchanged against a hosted API or the self-hosted model. Speech-to-text (Whisper) and text-to-speech run on OpenAI. Each serving configuration is benchmarked — TTFT, tokens/sec, P50/95/99 latency, QPS, cost per request.

The tutor workload runs end-to-end today against the Anthropic and OpenAI APIs. The infrastructure layers are being built GPU-independent parts first — gateway, monitoring, Kubernetes (kind), Argo — with vLLM wired in last on a rented GPU, since the development machine is a Mac with no CUDA. Design notes and build order: [docs/architecture-v2-infra.md](docs/architecture-v2-infra.md).

## Architecture

```
Application — TCF tutor (FastAPI + LangGraph graders + Next.js UI)   built
        │
Inference gateway (routing · token/cost accounting ·                 built
  rate limiting · /metrics)
        │
Model serving — vLLM, OpenAI-compatible                              built (rented GPU)
  (continuous batching · KV cache · AWQ/GPTQ)
        │
Observability — Prometheus + Grafana                                 built (gateway)
  (QPS · P50/95/99 · overhead · tokens · cost; GPU panels w/ vLLM)
        │
Orchestration — Kubernetes (kind) · Helm · HPA                       built (kind)
        │
Model pipeline — Argo Workflows · model registry                     built
```

## Components

- **Inference gateway** *(built)* — a standalone OpenAI-compatible service (`gateway/`). The app calls it instead of an LLM SDK directly; it routes to the selected backend (`INFERENCE_BACKEND=anthropic|openai|vllm`), counts tokens, rate-limits per key, records latency/cost, and exposes Prometheus metrics at `/metrics`. Text grading + the examiner run through it today with the anthropic backend. **Scope of the rate limiter:** it is a per-process token bucket, so the configured limit holds at *one* gateway replica and becomes N× the limit across N — a shared store (Redis) is the prerequisite for limiting across replicas. It is also turned effectively off in the Kubernetes values (`rateLimitPerMin: 6000000`) so it can't throttle the autoscaling load test.
- **Model serving** *(built)* — vLLM serving Qwen2.5-7B-Instruct over an OpenAI-compatible API (continuous batching, AWQ/GPTQ) on a rented GPU, behind the gateway's `vllm` backend. Live-validated: grader runs end-to-end on the self-hosted 7B (structured output intact, `eval_grader` 3/3), and **AWQ-4bit benchmarked +15–29% QPS / −10–22% latency vs FP16**; serving TTFT p50≈0.06s from vLLM's own metrics into Grafana. Runbook + results: [docs/vllm-runbook.md](docs/vllm-runbook.md).
- **Observability** *(built for the gateway)* — Prometheus scrapes the gateway (`infra/observability/`); a Grafana dashboard shows QPS, error rate, latency p50/95/99, gateway overhead, tokens/sec, and cost, faceted by an `impl` label for A/B comparison. GPU/VRAM/KV-cache panels come with vLLM.
- **Orchestration** *(built on kind)* — a Helm chart deploys the stack ([infra/k8s/](infra/k8s/)); kube-prometheus-stack scrapes the gateway and an HPA autoscales it on `gateway_inflight_requests` via prometheus-adapter. **What that demo validates:** load ran against the in-cluster mock upstream (fixed 100 ms delay), so it exercises the custom-metric → prometheus-adapter → HPA path end to end and shows replicas scaling on it — not model serving under real load. GPU-aware HPA comes with vLLM.
- **Model pipeline** *(built on kind)* — an Argo Workflows DAG evaluates a candidate model with the real grader regression, gates on it, and on pass records it in a model registry + rolls the backend to it (fail → notify, production untouched). See [pipeline/](pipeline/). Today the candidate is a hosted model; the same flow swaps a vLLM-served version later.
- **Workload** *(built)* — FastAPI + LangGraph writing/speaking graders and a turn-based voice examiner; PostgreSQL + Alembic; Langfuse tracing; a Next.js UI. Text generation uses Anthropic Claude today; STT/TTS use OpenAI. See [backend/README.md](backend/README.md).

## Stack

**Infrastructure:** vLLM · Prometheus · Grafana · Kubernetes (kind/k3s) · Helm · Argo Workflows · Docker · GitHub Actions
**Workload:** FastAPI · LangGraph · Anthropic Claude · OpenAI Whisper (STT) + TTS · PostgreSQL · SQLAlchemy · Alembic · Langfuse · Next.js · shadcn/ui · Tailwind

---

## Running the project

In development, run three processes: the **inference gateway** (`:8001`), the **backend** (`:8000`), and the **frontend** (`:3000`). The backend routes text generation through the gateway, so start the gateway first. Once all are up, open **http://localhost:3000** in your browser.

> Prerequisites: Python 3.11, Node.js, and a running PostgreSQL.
>
> **Prefer containers?** The whole backend stack (Postgres + gateway + backend + Prometheus + Grafana) runs with one command — see [infra/compose/](infra/compose/). The steps below are the host-run dev workflow.

### Start the inference gateway

```bash
cd gateway
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # set INFERENCE_BACKEND=anthropic + ANTHROPIC_API_KEY
uvicorn app.main:app --port 8001
```

Verify: `curl http://localhost:8001/health` → `{"status":"ok","backend":"anthropic"}`. See [gateway/README.md](gateway/README.md) for backends, metrics, and the benchmark.

### Start the backend

In **terminal 1**, copy-paste from the repo root:

```bash
cd backend

# 1) Python virtualenv + dependencies
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2) Create the database role and database (one-time; set a password when prompted)
createuser tcf_app --pwprompt
createdb tcf_ai_tutor -O tcf_app

# 3) Config: copy the template, then edit .env with your DB password and Anthropic key
cp .env.example .env
#    Open .env and replace the placeholders with real values:
#    DATABASE_URL=postgresql+asyncpg://tcf_app:YOUR_PASSWORD@localhost:5432/tcf_ai_tutor
#    ANTHROPIC_API_KEY=sk-ant-YOUR_KEY

# 4) Create tables + seed sample questions
alembic upgrade head
python -m scripts.seed_questions
```

Then **run the API** (:8000) — copy-paste this block every time you start it:

```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

> The venv must be activated (prompt shows `(.venv)`) before running uvicorn, otherwise dependencies like `sqlalchemy` won't be found.

Verify: `curl http://localhost:8000/health` should return `{"status":"ok"}`. Interactive docs live at <http://localhost:8000/docs>.

### Start the frontend

In **terminal 2**, copy-paste from the repo root:

```bash
cd frontend

# 1) Dependencies
npm install

# 2) Config: backend URL (only needed to override the default of localhost:8000)
cp .env.example .env.local

# 3) Run the dev server (:3000)
npm run dev
```

Open **http://localhost:3000** — the home page fetches and renders the question list from the backend's `GET /questions`.

---

## Roadmap

Built:
- [x] Tutor workload — writing grader (LangGraph multi-node), speaking grader, turn-based voice examiner, Langfuse tracing, Next.js UI
- [x] Scoring-reference RAG — CEFR band descriptors embedded through the gateway's `/v1/embeddings` (OpenAI) into pgvector (`rubric_chunks`); the score node retrieves the nearest bands (cosine, `exam_section`-filtered) to ground writing + speaking grading. Additive — grading falls back to the pre-RAG path when the store is empty or embeddings are unavailable
- [x] Inference gateway — `INFERENCE_BACKEND` switch, token/cost accounting, per-process rate limiting (single-replica scope), Prometheus `/metrics`; workload migrated to it (evals green through the gateway)
- [x] Observability — Prometheus + Grafana dashboards scraping the gateway; reusable benchmark harness (mock upstream + concurrency sweep) faceted by `impl` for an A/B (see [docs/rust-gateway-benchmark.md](docs/rust-gateway-benchmark.md))
- [x] Containerized stack — Dockerfiles (gateway + backend) + one-command `docker compose` (Postgres + gateway + backend + Prometheus + Grafana); see [infra/compose/](infra/compose/)

- [x] Kubernetes (kind) — Helm chart deploys gateway + backend + Postgres ([infra/k8s/](infra/k8s/)); kube-prometheus-stack scrapes the gateway and an HPA autoscales it on `gateway_inflight_requests` (prometheus-adapter), verified scaling under load against the in-cluster mock upstream — the metric → adapter → HPA path, not model serving

Planned:
- [x] Model pipeline — Argo Workflows eval → gate → promote (rolling update + model registry), verified pass/fail gates on kind
- [x] vLLM serving on GPU — live-validated on a rented RunPod GPU: grader end-to-end on Qwen2.5-7B (structured output intact, `eval_grader` 3/3), FP16-vs-AWQ benchmarks (AWQ +15–29% QPS / −10–22% latency), vLLM `/metrics` (TTFT p50≈0.06s) into Grafana. Results in [docs/vllm-runbook.md](docs/vllm-runbook.md) §5

Sequencing note: only vLLM needs a GPU, so the GPU-independent layers are built and validated on the Mac first; vLLM is added last on a rented GPU. Rationale in [docs/architecture-v2-infra.md](docs/architecture-v2-infra.md).

## Repository layout

```
tcf-ai-tutor/
├── backend/          # Application layer — FastAPI tutor (Python 3.11)
├── frontend/         # Next.js 16 (App Router) + Tailwind v4 + shadcn/ui
├── gateway/          # Inference gateway (+ Dockerfile)
├── infra/            # compose/ (full stack) · observability/ (Prom+Grafana) · k8s/ (kind + Helm chart)
├── benchmarks/       # Serving benchmarks + results (planned)
├── pipeline/         # Argo Workflows model-eval → gate → promote + model registry
├── docs/             # Architecture (v1 workload, v2 infra), build plan, dev log
├── CLAUDE.md         # Guidance for Claude Code
└── README.md
```
