# gateway/ — Inference Gateway

**Status: next slice (not yet implemented).**

A backend-agnostic layer between the application and the model backends. Planned
responsibilities:

- Backend routing via an `INFERENCE_BACKEND` switch (`anthropic` | `openai` | `vllm`),
  with Claude kept as the "quality" backend and vLLM as a drop-in OpenAI-compatible URL.
- Request validation + token counting (tiktoken / Anthropic count).
- Per-user rate limiting (token-bucket) and request queuing when the backend is saturated.
- Per-request cost/latency/model tracking.
- Streaming (SSE).
- Prometheus metrics at `/metrics` (QPS, P50/95/99 latency, tokens in/out, cost, error rate).

See [../docs/architecture-v2-infra.md](../docs/architecture-v2-infra.md).
