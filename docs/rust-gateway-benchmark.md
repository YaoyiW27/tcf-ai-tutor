# Rust gateway benchmark — experiment scope

A future experiment: reimplement the inference gateway in **Rust** and compare it against
the Python (FastAPI) one. This doc scopes it — **the Rust gateway is not built yet.** The
observability + benchmark harness (this repo) was built to make the comparison drop-in:
same mock upstream, same load script, same dashboards, same metric names.

## Hypothesis

The gateway is an **I/O-bound proxy** — most wall-clock time is the upstream/model call, not
CPU in the gateway. So:

- **Single-request latency: ~unchanged.** With one request in flight, total latency is
  dominated by the upstream; the gateway adds a small fixed overhead. Rust shrinks that
  overhead (ms → sub-ms) but it's a small slice of the total, so end-to-end p50 at low
  concurrency should look similar.
- **Rust should win on:**
  - **Throughput ceiling** — max sustained QPS before latency degrades. Python (single
    process, GIL, async event loop, per-request work) plateaus; Rust (no GIL, cheaper
    tasks) should sustain more on the same box.
  - **Tail latency under load (P95/P99)** — Python's tails blow up past its ceiling; Rust
    should hold flatter tails at high concurrency.
  - **Memory** — lower and flatter RSS.

### Python baseline (2026-07-29, forward path → mock upstream @1ms, rate limiting off, 8-core Mac)
| concurrency | QPS | p50 | p95 | p99 |
|---|---|---|---|---|
| 1  | 85  | 9 ms   | 14 ms   | 23 ms   |
| 4  | 169 | 19 ms  | 32 ms   | 53 ms   |
| 16 | 206 | 72 ms  | 118 ms  | 123 ms  |
| 32 | 116 | 206 ms | 594 ms  | 725 ms  |
| 64 | 86  | 502 ms | 1520 ms | 1710 ms |

Gateway **overhead** (total − upstream, from Prometheus): p50 ≈ 4 ms, p99 ≈ 24 ms under the
sweep. Peak RSS ≈ 93 MB. Throughput ceiling ≈ 200 QPS around concurrency 16, then latency
degrades — this is the regime the Rust version aims to improve.

## Method (identical for both implementations)

1. **Same mock upstream** — `benchmarks/mock_upstream.py`, a deterministic OpenAI-compatible
   server (fixed delay + fixed token usage). Removes model variance/cost so the measurement
   is the gateway itself. Two profiles:
   - **fast** (`MOCK_DELAY_MS=1`) — exposes gateway overhead + throughput ceiling.
   - **realistic** (`MOCK_DELAY_MS=100`) — exposes queuing behavior / tail latency under load.
2. **Same load script** — `benchmarks/bench_gateway.py`, run with `--label python` / `--label rust`.
   Sweeps concurrency, records per-level QPS + p50/p95/p99 + errors, and samples peak RSS
   (`--pid`). Results save to `benchmarks/results/<label>-*.json`.
3. **Rate limiting off** for throughput runs (`RATE_LIMIT_PER_MIN`/`BURST` set very high) —
   we're measuring the serving ceiling, not the limiter. (The default 120/min throttles a
   load test to ~2 QPS.)
4. **Same dashboards** — both gateways are scraped by the one Prometheus (`infra/observability/`)
   as separate targets carrying an `impl` label (`python` / `rust`); the Grafana dashboard is
   faceted by `impl`, so the two are overlaid on every panel live.
5. **Same box, one at a time** — run each gateway alone on the host for its load run (so they
   don't contend), on the same hardware, against the same mock profile.

## Metric contract (both gateways MUST expose these at `/metrics`)

Prometheus attaches the `impl` target label; the app exposes the names/labels below.

| metric | type | labels | meaning |
|---|---|---|---|
| `gateway_requests_total` | counter | backend, model, status | requests handled |
| `gateway_request_latency_seconds` | histogram | backend, model | end-to-end latency |
| `gateway_upstream_latency_seconds` | histogram | backend, model | time awaiting upstream |
| `gateway_overhead_seconds` | histogram | backend, model | **total − upstream (gateway-added)** |
| `gateway_tokens_input_total` | counter | backend, model | prompt tokens |
| `gateway_tokens_output_total` | counter | backend, model | completion tokens |
| `gateway_cost_usd_total` | counter | backend, model | estimated cost |
| `gateway_inflight_requests` | gauge | — | in-flight requests |

Histogram bucket boundaries should match (`gateway/app/metrics.py`) so quantiles are
comparable — especially `gateway_overhead_seconds`, whose fine sub-ms buckets are what make
the overhead comparison meaningful.

## Metrics to compare (the scorecard)

- **Gateway overhead** p50/p95/**p99** (`gateway_overhead_seconds`) — the headline: pure
  gateway cost, upstream factored out.
- **Throughput ceiling** — peak sustained QPS across the concurrency sweep, and the
  concurrency at which it peaks before latency degrades.
- **Tail latency under load** — p95/p99 of `gateway_request_latency_seconds` at the highest
  concurrency levels, and error rate under overload.
- **Memory** — peak RSS (`--pid` sampler); optionally CPU% during the run.

## How to run (per implementation)

```bash
# 1) mock upstream (fast profile)
MOCK_DELAY_MS=1 uvicorn benchmarks.mock_upstream:app --port 9000

# 2a) Python gateway (forward path → mock, limiter off)
cd gateway && INFERENCE_BACKEND=openai UPSTREAM_BASE_URL=http://localhost:9000/v1 \
  RATE_LIMIT_PER_MIN=6000000 RATE_LIMIT_BURST=1000000 \
  uvicorn app.main:app --host 0.0.0.0 --port 8001
# 2b) Rust gateway (when it exists) on :8002, same env semantics

# 3) observability (uncomment the rust target in prometheus.yml when running 2b)
docker compose -f infra/observability/docker-compose.yml up -d

# 4) load each, labeled
python benchmarks/bench_gateway.py --label python --url http://localhost:8001/v1 \
  --model mock-model --concurrency 1,4,16,32,64 --n 200 --pid <python_gw_pid>
python benchmarks/bench_gateway.py --label rust   --url http://localhost:8002/v1 \
  --model mock-model --concurrency 1,4,16,32,64 --n 200 --pid <rust_gw_pid>

# 5) compare
python benchmarks/compare_results.py results/python-*.json results/rust-*.json
```

Watch it live in Grafana (**Inference Gateway** dashboard, faceted by `impl`) at
http://localhost:3001.
