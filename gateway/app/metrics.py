"""Prometheus metrics for the gateway.

Exposed at ``GET /metrics``. Labels are kept low-cardinality (backend, model,
status) so the series stay cheap to store and query.
"""

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

REQUESTS = Counter(
    "gateway_requests_total",
    "Chat-completion requests handled, by backend/model/status.",
    ["backend", "model", "status"],
)
LATENCY = Histogram(
    "gateway_request_latency_seconds",
    "End-to-end request latency (gateway → backend → response).",
    ["backend", "model"],
    buckets=(0.1, 0.25, 0.5, 1, 2, 4, 8, 16, 32, 64),
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
