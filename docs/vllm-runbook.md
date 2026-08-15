# vLLM serving runbook (Qwen2.5-7B behind the gateway)

Self-host **Qwen2.5-7B-Instruct** on vLLM on a rented GPU, route the gateway to it
(`INFERENCE_BACKEND=vllm`), benchmark **FP16 vs AWQ**, and scrape vLLM's metrics into Grafana.
The gateway's `vllm` backend just forwards to `UPSTREAM_BASE_URL` (already built/tested), so this is
config + operations, not gateway code.

> Cost: the GPU bills by the hour — spin it down when done.

## 1. Launch vLLM on the GPU box (Docker)
A ~24 GB GPU (A10/L4/A100) runs the FP16 model; AWQ-4bit fits ~8–12 GB. Pick a strong `KEY`.

**FP16:**
```bash
docker run --gpus all -p 8000:8000 \
  -e HF_TOKEN=<hf_token_if_needed> \
  vllm/vllm-openai:latest \
  --model Qwen/Qwen2.5-7B-Instruct \
  --api-key "$VLLM_KEY" \
  --max-model-len 16384
```

**AWQ-4bit** (same command, different checkpoint + quantization):
```bash
docker run --gpus all -p 8000:8000 vllm/vllm-openai:latest \
  --model Qwen/Qwen2.5-7B-Instruct-AWQ --quantization awq \
  --api-key "$VLLM_KEY" --max-model-len 16384
```

> **`--max-model-len` must clear the workload's completion cap.** The grader's
> `_structured_call` caps completions at `max_tokens=8000` (tuned for Claude's 200k
> window; the workload stays backend-agnostic). vLLM counts prompt + `max_completion_tokens`
> against `--max-model-len`, so an 8192 window 400s every grader call
> (`8000 + prompt > 8192`). `16384` clears it with headroom (Qwen2.5-7B supports 32768);
> keep the **same value for FP16 and AWQ** so the benchmark is apples-to-apples.

Reach it from the Mac with an SSH tunnel (keeps the key off the public internet and out of chat):
`ssh -L 8000:localhost:8000 <box>` → the endpoint is `http://localhost:8000`. vLLM serves
OpenAI-compatible `/v1/*` and Prometheus `/metrics`.

## 2. Point the gateway at vLLM
Put the config in `gateway/.env` (gitignored — **don't paste the key into chat**):
```
INFERENCE_BACKEND=vllm
UPSTREAM_BASE_URL=http://localhost:8000/v1   # the SSH-tunnelled vLLM
UPSTREAM_API_KEY=<vllm --api-key>
```
then run the gateway (`uvicorn app.main:app --port 8001` from `gateway/`). Structured output works
across vLLM versions: recent vLLM accepts `response_format` json_schema; if it 400s, the gateway
auto-retries with vLLM's top-level `guided_json` (see `_forward_backend`) — no app change.
And the backend/workload requests this model id:
```bash
INFERENCE_MODEL=Qwen/Qwen2.5-7B-Instruct   # gateway forwards the request model to vLLM
```

### Structured output
The graders always send OpenAI `response_format: {type: json_schema, …}`; the gateway handles the
backend's quirks (the app never knows which backend is active). For vLLM the gateway forwards
`response_format`; if the upstream 400s (older vLLM), it retries once with the top-level `guided_json`
param — implemented + tested in `gateway/app/backends.py::_forward_backend`. A 7B model's French-grading
*quality* will trail Claude — that's expected; the goal is that grading runs end-to-end on the
self-hosted model (the Argo eval gate may legitimately reject it as a weaker candidate).

## 3. Benchmark FP16 vs AWQ
Reuse the harness against the gateway → vLLM (raise the gateway rate limit for load):
```bash
python benchmarks/bench_gateway.py --url http://localhost:8001/v1 \
  --model Qwen/Qwen2.5-7B-Instruct --label vllm-fp16 --concurrency 1,4,8,16 --n 200
# switch vLLM to the AWQ checkpoint, then:
python benchmarks/bench_gateway.py --url http://localhost:8001/v1 \
  --model Qwen/Qwen2.5-7B-Instruct --label vllm-awq --concurrency 1,4,8,16 --n 200
python benchmarks/compare_results.py results/vllm-fp16-*.json results/vllm-awq-*.json
```
The client bench measures **end-to-end latency with the network in the path** (Mac → SSH tunnel →
GPU) — use it only for *relative* FP16-vs-AWQ e2e comparison and tokens/sec/QPS, **not** as an absolute
serving latency. **TTFT and true serving latency come from vLLM's own metrics** (step 4:
`vllm:time_to_first_token_seconds`), not the client — the gateway forward path is non-streaming, and
the client number would otherwise be dominated by internet RTT.

## 4. Scrape vLLM metrics → Grafana
Add a scrape job for the vLLM `/metrics` target (see the commented block in
`infra/observability/prometheus.yml`), then bring up the observability stack. The **vLLM** dashboard
(`infra/observability/grafana/dashboards/vllm.json`) shows TTFT p50/95/99
(`vllm:time_to_first_token_seconds`), generation throughput, KV-cache usage, and running/waiting requests.

## 5. Record results

### Live run — 2026-08-14 (RunPod, Qwen2.5-7B-Instruct, vLLM 0.27.1, `--max-model-len 16384`)

**Setup:** vLLM on a RunPod pod (public HTTPS proxy) → gateway (`INFERENCE_BACKEND=vllm`) on the
Mac → benchmark. Structured output used vLLM's **native `response_format` json_schema** (200 on the
benchmark + eval runs). The `guided_json` fallback did *not* fire on those successful runs — but note
that the earlier `--max-model-len 8192` 400s (§1) **did** each trip the fallback, because the
then-current gateway retried on *any* json_schema 400. That was a bug: a context-length 400 is not a
"response_format unsupported" signal, so retrying it double-charged the metered GPU and surfaced the
retry's error instead of the real cause. The gateway now retries only when the 400 body names
`response_format`, and memoizes the verdict per upstream (see `backends._forward_backend`).

**Grader eval:** `eval_grader` **3/3 passed end-to-end against the FP16 model** (the eval ran while the
FP16 pod was up, before the AWQ redeploy). This is a *pipeline* check — 3 hand-written assertions against
a non-deterministic model confirm the self-hosted path produces valid structured grades and doesn't
regress on three specific cases; it is **not** a measure of grading quality or adequacy.

Client bench = e2e (Mac → RunPod → GPU), fixed prompt, `max_completion_tokens=256` but the model
**emitted only ~28–42 tokens** (short French answer, `finish_reason=stop`), so these numbers measure
**TTFT + a short decode, not sustained generation** — the FP16-vs-AWQ gap may differ on long outputs.
n=100/level, single run, limiter raised.

**FP16 vs AWQ-4bit** (`benchmarks/results/vllm-fp16-*.json`, `vllm-awq-*.json`):

| concurrency | QPS (fp16→awq) | p50 s (fp16→awq) | p95 s | p99 s | out tok/s (fp16→awq) |
|---|---|---|---|---|---|
| 1  | 0.78 → 0.98  (+26%) | 1.25 → 1.01 (−19%) | 1.61 → 1.28 | 1.68 → 1.43 | 29.8 → 38.0  (+28%) |
| 4  | 2.86 → 3.68  (+29%) | 1.36 → 1.06 (−22%) | 1.61 → 1.33 | 1.68 → 1.64 | 112.5 → 144.0 (+28%) |
| 8  | 5.79 → 7.30  (+26%) | 1.31 → 1.06 (−19%) | 1.62 → 1.31 | 1.70 → 1.44 | 221.3 → 275.0 (+24%) |
| 16 | 10.75 → 12.36 (+15%) | 1.32 → 1.17 (−12%) | 1.65 → 1.45 | 1.75 → 1.56 | 405.6 → 487.5 (+20%) |

**Authoritative serving-side metrics** (from vLLM `/metrics`, AWQ pod, network excluded):
TTFT **p50=0.06s / p95=0.08s / p99=0.10s** (`vllm:time_to_first_token_seconds`); serving e2e
p50≈1.0s ≈ the client p50, so **the RunPod proxy adds negligible network overhead** — the ~1s is real
single-stream decode (~38 tok/s), not RTT. Prometheus scraped the vLLM target live (`scheme: https`,
`/metrics`, unauthenticated); the **vLLM Serving** Grafana dashboard rendered TTFT/throughput from it.

**Observations:** (1) On these short-decode requests AWQ is a straight win — **+15–29% QPS and
−10–22% p50/p95 latency** at every concurrency, 0 errors. The **quality delta was not measured**:
`eval_grader` was only run against FP16 (the AWQ eval was skipped to spin the GPU down), so this
records AWQ's *performance* advantage, not its accuracy relative to FP16. (2) vLLM continuous batching:
**QPS scales ~linearly 1→16 while p50 stays ~flat** — throughput grows at near-constant per-request
latency. (3) FP16's serving-side TTFT was not captured live (its pod was destroyed on the AWQ redeploy);
the client-side FP16-vs-AWQ delta above is the relative record. (4) `--max-model-len` **must exceed the
grader's 8000-token completion cap** or every call 400s (§1) — this was the one live blocker.

> **Precision caveat:** each cell is a **single run of n=100**, so p95/p99 rest on ~5 / ~1 samples
> respectively — treat p99 as indicative, not a stable quantile, and don't over-read the last digits.
> The QPS and p50 numbers are the trustworthy ones; re-run with larger n for publishable tail latencies.

Then **spin down the GPU.**

## Deferred
In-cluster GPU-aware HPA (our kind cluster runs on the Mac, not the GPU) — a future slice would run
kind on the GPU box and scale on `vllm:num_requests_waiting` / GPU utilization.
