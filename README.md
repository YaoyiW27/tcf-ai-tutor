# tcf-ai-tutor — Self-hosted LLM inference stack with observability and automated deployment pipeline

An inference gateway — request routing, token and cost accounting, rate limiting, and Prometheus metrics — sits in front of an open-weight LLM served by vLLM. The stack runs on Kubernetes with Prometheus/Grafana monitoring and an Argo Workflows pipeline that evaluates candidate models and rolls them out when they beat the current baseline. The workload it serves is a TCF Canada French-exam tutor: LangGraph writing and speaking graders and a turn-based voice examiner.

Text generation sits behind an `INFERENCE_BACKEND` switch (`anthropic` | `openai` | `vllm`), so the workload runs unchanged against a hosted API or the self-hosted model. Speech-to-text (Whisper) and text-to-speech run on OpenAI. Each serving configuration is benchmarked — TTFT, tokens/sec, P50/95/99 latency, QPS, cost per request.

The tutor workload runs end-to-end today against the Anthropic and OpenAI APIs. The infrastructure layers are being built GPU-independent parts first — gateway, monitoring, Kubernetes (kind), Argo — with vLLM wired in last on a rented GPU, since the development machine is a Mac with no CUDA. Design notes and build order: [docs/architecture-v2-infra.md](docs/architecture-v2-infra.md).

## Architecture

```
Application — TCF tutor (FastAPI + LangGraph graders + Next.js UI)   built
        │
Inference gateway (routing · token/cost accounting ·                 in progress
  rate limiting · /metrics · SSE)
        │
Model serving — vLLM, OpenAI-compatible                              planned
  (continuous batching · KV cache · AWQ/GPTQ)
        │
Observability — Prometheus + Grafana                                 planned
  (QPS · P50/95/99 · TTFT · GPU util · VRAM · KV-cache)
        │
Orchestration — Kubernetes (kind/k3s) · Helm · HPA                   planned
        │
Model pipeline — Argo Workflows · model registry                     planned
```

## Components

- **Inference gateway** *(in progress)* — the app calls the gateway instead of an LLM SDK directly. It validates requests, counts tokens, rate-limits per user, routes to the selected backend, records latency and cost, and exposes Prometheus metrics at `/metrics`.
- **Model serving** *(planned)* — vLLM serving an open-weight model (e.g. Qwen2.5-7B-Instruct) over an OpenAI-compatible API, with continuous batching and AWQ/GPTQ quantization. Runs on a rented GPU.
- **Observability** *(planned)* — Prometheus scrapes the gateway and vLLM; Grafana dashboards for latency, throughput, GPU/VRAM, KV-cache, and cost.
- **Orchestration** *(planned)* — Kubernetes (kind locally), Helm, HPA driven by queue depth / GPU utilization.
- **Model pipeline** *(planned)* — Argo Workflows: pull model weights → run the eval suite → compare against the current baseline → rolling-update the vLLM deployment on pass, else notify.
- **Workload** *(built)* — FastAPI + LangGraph writing/speaking graders and a turn-based voice examiner; PostgreSQL + Alembic; Langfuse tracing; a Next.js UI. Text generation uses Anthropic Claude today; STT/TTS use OpenAI. See [backend/README.md](backend/README.md).

## Stack

**Infrastructure:** vLLM · Prometheus · Grafana · Kubernetes (kind/k3s) · Helm · Argo Workflows · Docker · GitHub Actions
**Workload:** FastAPI · LangGraph · Anthropic Claude · OpenAI Whisper (STT) + TTS · PostgreSQL · SQLAlchemy · Alembic · Langfuse · Next.js · shadcn/ui · Tailwind

---

## Running the project

In development, run **two terminals at once**: one for the backend (`:8000`) and one for the frontend (`:3000`). Once both are up, open **http://localhost:3000** in your browser.

> Prerequisites: Python 3.11, Node.js, and a running PostgreSQL.

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

In progress:
- [~] Monorepo scaffold + this architecture
- [ ] Inference gateway — `INFERENCE_BACKEND` switch, token/cost accounting, rate limiting, Prometheus `/metrics`

Planned:
- [ ] Observability — Prometheus + Grafana dashboards
- [ ] Kubernetes (kind/k3s) — Helm, kube-prometheus-stack, HPA
- [ ] Model pipeline — Argo Workflows eval → gate → rolling update, model registry
- [ ] vLLM serving on GPU — FP16-vs-AWQ benchmarks, GPU metrics, GPU-aware HPA

Sequencing note: only vLLM needs a GPU, so the GPU-independent layers are built and validated on the Mac first; vLLM is added last on a rented GPU. Rationale in [docs/architecture-v2-infra.md](docs/architecture-v2-infra.md).

## Repository layout

```
tcf-ai-tutor/
├── backend/          # Application layer — FastAPI tutor (Python 3.11)
├── frontend/         # Next.js 16 (App Router) + Tailwind v4 + shadcn/ui
├── gateway/          # Inference gateway (in progress)
├── infra/            # Dockerfiles, K8s/Helm, Prometheus/Grafana (planned)
├── benchmarks/       # Serving benchmarks + results (planned)
├── pipeline/         # Argo Workflows eval pipeline + model registry (planned)
├── docs/             # Architecture (v1 workload, v2 infra), build plan, dev log
├── CLAUDE.md         # Guidance for Claude Code
└── README.md
```
