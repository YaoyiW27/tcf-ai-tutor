"""Contract tests for the gateway's Prometheus metrics.

These guard against the exposed metric names/labels drifting from what the Grafana
dashboard's PromQL expects (`infra/observability/grafana/dashboards/gateway.json`).
The `impl` label is a Prometheus scrape-time label, not app-emitted — see
test_scrape_config_impl_label.py.
"""

from prometheus_client import Counter, Gauge, Histogram

from app import backends, metrics

# The seven families the dashboard queries, with their type + declared labels.
EXPECTED = {
    "gateway_requests_total": (Counter, ("backend", "model", "status")),
    "gateway_request_latency_seconds": (Histogram, ("backend", "model")),
    "gateway_upstream_latency_seconds": (Histogram, ("backend", "model")),
    "gateway_overhead_seconds": (Histogram, ("backend", "model")),
    "gateway_tokens_output_total": (Counter, ("backend", "model")),
    "gateway_inflight_requests": (Gauge, ()),
    "gateway_cost_usd_total": (Counter, ("backend", "model")),
}

_OBJECTS = {
    "gateway_requests_total": metrics.REQUESTS,
    "gateway_request_latency_seconds": metrics.LATENCY,
    "gateway_upstream_latency_seconds": metrics.UPSTREAM_LATENCY,
    "gateway_overhead_seconds": metrics.OVERHEAD,
    "gateway_tokens_output_total": metrics.TOKENS_OUT,
    "gateway_inflight_requests": metrics.INFLIGHT,
    "gateway_cost_usd_total": metrics.COST_USD,
}


def test_all_seven_metric_families_have_expected_types():
    for name, (expected_type, _labels) in EXPECTED.items():
        assert isinstance(_OBJECTS[name], expected_type), name


def test_each_metric_declares_expected_labels():
    for name, (_type, expected_labels) in EXPECTED.items():
        assert tuple(_OBJECTS[name]._labelnames) == expected_labels, name


def test_metrics_endpoint_exposes_all_names_and_histogram_buckets(client, monkeypatch):
    # Mock the backend so a request succeeds with no real LLM call, which
    # instantiates the labeled series so they appear in the exposition.
    async def fake_handle(body):
        return ({"choices": [{"message": {"content": "ok"}}]}, 40, 64, 0.05)

    monkeypatch.setattr(backends, "handle", fake_handle)

    resp = client.post(
        "/v1/chat/completions",
        json={"model": "m", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 200

    body = client.get("/metrics").text
    for name in EXPECTED:
        assert name in body, f"missing metric {name} in /metrics"
    # Histograms must expose *_bucket (the le dimension) so histogram_quantile works.
    for hist in ("gateway_request_latency_seconds", "gateway_overhead_seconds"):
        assert f"{hist}_bucket" in body, f"missing {hist}_bucket"
