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
  --max-model-len 8192
```

**AWQ-4bit** (same command, different checkpoint + quantization):
```bash
docker run --gpus all -p 8000:8000 vllm/vllm-openai:latest \
  --model Qwen/Qwen2.5-7B-Instruct-AWQ --quantization awq \
  --api-key "$VLLM_KEY" --max-model-len 8192
```

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
Save the FP16-vs-AWQ table + observations here and in `docs/dev-log.md`. Then **spin down the GPU**.

## Deferred
In-cluster GPU-aware HPA (our kind cluster runs on the Mac, not the GPU) — a future slice would run
kind on the GPU box and scale on `vllm:num_requests_waiting` / GPU utilization.
