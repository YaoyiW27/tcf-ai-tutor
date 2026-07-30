"""Prometheus metrics for the gateway.

Exposed at ``GET /metrics``. Labels are kept low-cardinality (backend, model,
status) so the series stay cheap to store and query.
"""

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

# Buckets spanning the whole model call (seconds → tens of seconds).
_REQUEST_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60)
# Fine buckets for the gateway's own overhead, which is sub-millisecond → ms
# against a fast upstream. This is the metric the Python-vs-Rust A/B turns on,
# so it must resolve well below the request buckets above.
_OVERHEAD_BUCKETS = (
    0.0001, 0.00025, 0.0005, 0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1,
)

REQUESTS = Counter(
    "gateway_requests_total",
    "Chat-completion requests handled, by backend/model/status.",
    ["backend", "model", "status"],
)
LATENCY = Histogram(
    "gateway_request_latency_seconds",
    "End-to-end request latency (gateway → backend → response).",
    ["backend", "model"],
    buckets=_REQUEST_BUCKETS,
)
UPSTREAM_LATENCY = Histogram(
    "gateway_upstream_latency_seconds",
    "Time spent awaiting the model backend (Anthropic SDK / forwarded upstream).",
    ["backend", "model"],
    buckets=_REQUEST_BUCKETS,
)
OVERHEAD = Histogram(
    "gateway_overhead_seconds",
    "Gateway-added latency per request (total − upstream).",
    ["backend", "model"],
    buckets=_OVERHEAD_BUCKETS,
)
TOKENS_IN = Counter(
    "gateway_tokens_input_total",
    "Input (prompt) tokens, by backend/model.",
    ["backend", "model"],
)
TOKENS_OUT = Counter(
    "gateway_tokens_output_total",
    "Output (completion) tokens, by backend/model.",
    ["backend", "model"],
)
COST_USD = Counter(
    "gateway_cost_usd_total",
    "Estimated request cost in USD, by backend/model.",
    ["backend", "model"],
)
INFLIGHT = Gauge(
    "gateway_inflight_requests",
    "In-flight chat-completion requests.",
)


def render() -> tuple[bytes, str]:
    """Return ``(body, content_type)`` for the /metrics response."""
    return generate_latest(), CONTENT_TYPE_LATEST
