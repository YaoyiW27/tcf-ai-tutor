# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project intent

A self-hosted LLM inference stack — inference gateway, vLLM model serving,
Prometheus/Grafana observability, Kubernetes deployment, and an Argo model-eval/rollout
pipeline — with a working multi-agent **TCF Canada AI tutor** as the workload that
exercises it. The tutor already works against hosted APIs; the current work is building
the serving stack underneath it.

Full architecture + build order: `docs/architecture-v2-infra.md`; the detailed build plan
is `docs/upgrade-plan.md`. The tutor/workload design lives in `docs/architecture-v1.md`.
Session history is in `docs/dev-log.md`.

## Current state (what exists)

- **backend/** — FastAPI app (Python 3.11), the workload:
  - LangGraph writing grader (`app/graph.py`, `app/grader.py`) and speaking grader
    (`app/speaking_graph.py`, `app/speaking_grader.py`) — structured Claude output via
    `messages.parse`.
  - Speaking: Whisper STT (`app/transcription.py`), OpenAI TTS (`app/tts.py`),
    conversational examiner (`app/examiner.py`, `app/routers/conversation.py`).
  - PostgreSQL via async SQLAlchemy + Alembic; Langfuse tracing.
- **frontend/** — Next.js 16 (App Router) + Tailwind v4 + shadcn/ui. **Read
  `frontend/AGENTS.md` before writing frontend code** (Next 16 has breaking changes; the
  bundled docs under `node_modules/next/dist/docs/` are authoritative).
- **gateway/ · infra/ · benchmarks/ · pipeline/** — skeleton dirs with README stubs for
  the infra layers being built next.

## Commands

Backend (from `backend/`, venv must be active — prompt shows `(.venv)`):
```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head                     # migrations
python -m scripts.seed_questions         # seed sample TCF questions (idempotent)
uvicorn app.main:app --reload --port 8000
python -m scripts.eval_grader            # writing grader regression eval (real Claude calls)
python -m scripts.eval_speaking_grader   # speaking grader eval (transcript-based)
python -m scripts.eval_examiner          # conversational examiner eval (text-only)
python -m compileall app                 # quick syntax check
```
Frontend (from `frontend/`): `npm install`, `npm run dev` (:3000), `npm run lint`, `npm run build`.

`.env` (backend) holds `DATABASE_URL`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` (Whisper/TTS),
and optional `LANGFUSE_*`. The app boots without the API keys; the relevant endpoints return
503 when a key is missing.

## How to work here

- **Confirm the design before writing code** for each new layer/slice (the user plans
  interactively, then approves). Build in small, reviewable slices.
- **Measurement-first:** infra work must produce reproducible data (TTFT, tokens/sec,
  P50/95/99, QPS, cost/req), not just "it runs". Put benchmark scripts + results under
  `benchmarks/`.
- **Code quality:** type hints, docstrings, and at least basic tests/evals — this is a
  real system, keep it clean. Match the existing style in `backend/app/**`.
- **Sequencing — GPU-free first:** build the gateway, observability, K8s (kind), and Argo
  locally with no GPU; vLLM comes **last** on a rented cloud GPU (the dev machine is a Mac,
  no CUDA). Don't try to run vLLM locally.
- **Backend switch:** all text-LLM calls go through an `INFERENCE_BACKEND`
  (`anthropic` | `openai` | `vllm`) abstraction (built in the gateway slice). **Keep Claude
  as the "quality" backend.** **STT/TTS stay on OpenAI** — vLLM is text-only.
- Keep `backend/` in place (it's the workload layer); grow the monorepo by adding to the
  sibling infra dirs rather than restructuring.
- Committed docs are written in **English** even when chatting in another language.
- Update `docs/dev-log.md` (a new dated "Session" entry) and the README roadmap as each
  slice lands. Commit prefixes: `feat:`, `fix:`, `docs:`, `chore:`, `refactor:`.
