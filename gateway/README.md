# gateway/ — Inference Gateway

A standalone **OpenAI-compatible** service that sits between the workload and the
model backends. The app talks to it with an OpenAI client; the gateway routes to
the configured backend, and adds token/cost accounting, rate limiting, and
Prometheus metrics. Swapping the model backend (e.g. to vLLM) is a config change,
not an app change.

## Endpoints
- `POST /v1/chat/completions` — OpenAI-compatible chat completions, including
  structured output via `response_format` (JSON schema).
- `GET /metrics` — Prometheus metrics.
- `GET /health` — liveness + the active backend.

## Backends (`INFERENCE_BACKEND`)
- `anthropic` (default) — translates to the Anthropic Messages API. Structured
  output uses Anthropic's native structured outputs (`output_config.format`),
  which is compatible with extended thinking; `reasoning_effort`
  (`low|medium|high`) maps to a thinking budget.
- `openai` / `vllm` — forwards verbatim to an OpenAI-compatible `UPSTREAM_BASE_URL`
  (guided JSON / `response_format` passes straight through).

## Metrics
`gateway_requests_total`, `gateway_request_latency_seconds`,
`gateway_tokens_input_total`, `gateway_tokens_output_total`,
`gateway_cost_usd_total`, `gateway_inflight_requests` — labeled by backend/model
(and status for requests).

## Run
```bash
cd gateway
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env   # set INFERENCE_BACKEND + the relevant key
uvicorn app.main:app --port 8001
```
`.env` keys: `INFERENCE_BACKEND` (anthropic|openai|vllm), `ANTHROPIC_API_KEY`
(anthropic backend), `UPSTREAM_BASE_URL` + `UPSTREAM_API_KEY` (openai/vllm),
`RATE_LIMIT_PER_MIN`, `RATE_LIMIT_BURST`.

The backend (workload) points at the gateway via `GATEWAY_URL` (default
`http://localhost:8001`), so the gateway must be running for text grading /
the examiner to work.

## Benchmark
`python ../benchmarks/bench_gateway.py --n 20 --concurrency 4` → latency
percentiles, QPS, output tokens/sec (saved under `benchmarks/results/`).

See [../docs/architecture-v2-infra.md](../docs/architecture-v2-infra.md).
