# infra/observability/ — Prometheus + Grafana

Scrapes the gateway's `/metrics` and visualizes it. Runs via docker-compose;
the gateway itself runs on the host (uvicorn), scraped over `host.docker.internal`.

## Run
```bash
docker compose -f infra/observability/docker-compose.yml up -d
```
- Prometheus → http://localhost:9090 (check targets at `/targets`)
- Grafana → http://localhost:3001 (anonymous; dashboard **Inference Gateway** auto-provisioned)

The gateway must be running and bound so the container can reach it:
```bash
cd gateway && uvicorn app.main:app --host 0.0.0.0 --port 8001
```

## Dashboard
Panels are faceted by an `impl` label so two gateway implementations can be
compared on one board: throughput (QPS), error rate, request-latency
p50/p95/p99, **gateway overhead** p50/p95/p99 (total − upstream), upstream
latency, output tokens/sec, in-flight, and cost/sec.

The `impl` label is attached by Prometheus (a target label in `prometheus.yml`),
not by the app — so any gateway exposing the same metric names slots in.

## Adding a second implementation (e.g. Rust)
Run it on `:8002`, then uncomment the `impl: rust` target in `prometheus.yml`
and `docker compose ... restart prometheus`. See
[../../docs/rust-gateway-benchmark.md](../../docs/rust-gateway-benchmark.md).

## Metric contract
The gateway exposes (all gain the `impl` target label in Prometheus):
`gateway_requests_total{backend,model,status}`,
`gateway_request_latency_seconds` (histogram),
`gateway_upstream_latency_seconds` (histogram),
`gateway_overhead_seconds` (histogram),
`gateway_tokens_input_total`, `gateway_tokens_output_total`,
`gateway_cost_usd_total`, `gateway_inflight_requests`.
