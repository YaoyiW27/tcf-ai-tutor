# Architecture v2 — Self-hosted inference stack

Status: Active (build in progress)
Date: 2026-07-14
Supersedes the *scope* of [architecture-v1.md](architecture-v1.md); the v1
tutor design (writing grader, speaking, conversational examiner) stays valid and
becomes the workload the stack below serves.

Build plan: [upgrade-plan.md](upgrade-plan.md).

## Why

The TCF tutor works end-to-end (writing + speaking grading, a conversational voice
examiner, Langfuse tracing) but calls hosted LLM APIs directly. The goal now is to
put a proper serving stack underneath it — a self-hosted model behind an inference
gateway, with monitoring, Kubernetes deployment, and an automated model-eval/rollout
pipeline. The tutor is the workload that exercises the stack.

## Target architecture

```
┌─────────────────────────────────────────────────────────┐
│  Application Layer — TCF AI Tutor (the workload)          │  built
│  FastAPI + LangGraph graders + Next.js UI                 │
├─────────────────────────────────────────────────────────┤
│  Inference Gateway                                        │  next
│  routing · token counting · cost tracking ·              │
│  rate limiting · queuing · Prometheus /metrics · SSE      │
├─────────────────────────────────────────────────────────┤
│  Model Serving — vLLM (OpenAI-compatible)                 │  last (GPU)
│  self-hosted OSS LLM · continuous batching · KV cache ·   │
│  quantization (AWQ/GPTQ)                                   │
├─────────────────────────────────────────────────────────┤
│  Observability — Prometheus + Grafana                     │  planned
│  QPS · P50/95/99 latency · TTFT · GPU util · VRAM ·       │
│  KV-cache hit rate · tokens/sec · queue depth             │
├─────────────────────────────────────────────────────────┤
│  Orchestration — Kubernetes (kind/k3s local)              │  planned
│  Helm/Kustomize · GPU-aware HPA                           │
├─────────────────────────────────────────────────────────┤
│  ML Pipeline — Argo Workflows                             │  planned
│  eval benchmark → gate → rolling update · model registry  │
└─────────────────────────────────────────────────────────┘
```

## Build order (re-sequenced: GPU-free first, vLLM last)

The upgrade doc lists vLLM (Phase 1) first, but only vLLM needs a GPU. To avoid
burning cloud-GPU money before the surrounding system exists, we build everything
GPU-free first and slot vLLM in last on a rented GPU:

1. **Reposition + scaffold** — this doc, monorepo skeleton, README/CLAUDE.md (done).
2. **Inference Gateway** (GPU-free) — backend-agnostic layer + Prometheus `/metrics`.
3. **Observability stack** (GPU-free) — Prometheus + Grafana dashboards for the gateway.
4. **Containerize + K8s** (kind, GPU-free) — Dockerfiles, Helm, kube-prometheus-stack, HPA on gateway metrics.
5. **Argo Workflows pipeline** (mostly GPU-free) — eval benchmark (reusing `backend/scripts/eval_*`) + model registry + rolling-update trigger.
6. **vLLM serving** (cloud GPU, last) — OpenAI-compatible server, `INFERENCE_BACKEND=vllm`, FP16-vs-AWQ benchmarks, GPU metrics → Grafana, GPU-aware HPA.

## Key decisions

- **Hosting:** the dev machine is a Mac (no CUDA), so vLLM runs on a **rented cloud GPU** (RunPod/Lambda/vast.ai), spun up only for serving/benchmark windows.
- **`INFERENCE_BACKEND` switch** (`anthropic` | `openai` | `vllm`): all text-LLM calls (graders + examiner) go through the gateway's backend abstraction. **Claude stays as the "quality" backend** so either can be demoed; vLLM is a drop-in OpenAI-compatible backend URL.
- **STT/TTS stay on OpenAI.** vLLM serves *text* models only, so Whisper (STT) and OpenAI TTS are unchanged — the pivot moves only the chat/completion calls.
- **Structured output:** the graders currently use Anthropic `messages.parse(output_format=…)`. The vLLM path needs guided-JSON / xgrammar decoding to produce the same validated Pydantic objects — handled when the vLLM backend is wired.
- **Measurable by default:** every serving/infra step produces data (TTFT, tokens/sec, P50/95/99, QPS, cost/req), not just "it runs."

## Repo mapping

`backend/` is the Application/workload layer (kept in place to avoid churn). New
sibling top-level dirs hold the infra layers as they land: `gateway/`, `infra/`,
`benchmarks/`, `pipeline/`.
