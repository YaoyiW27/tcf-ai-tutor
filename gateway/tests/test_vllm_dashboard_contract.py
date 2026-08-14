"""Contract test for the vLLM Grafana dashboard.

Guards that the dashboard is valid JSON and its panels query the vLLM metric
names we rely on — so a rename/typo is caught before it silently blanks the board.
(Mirrors the gateway metric-contract test; no cluster/GPU needed.)
"""

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DASHBOARD = REPO / "infra/observability/grafana/dashboards/vllm.json"

# vLLM metric names the dashboard panels must reference.
EXPECTED_METRICS = [
    "vllm:time_to_first_token_seconds_bucket",
    "vllm:e2e_request_latency_seconds_bucket",
    "vllm:generation_tokens_total",
    "vllm:gpu_cache_usage_perc",
    "vllm:num_requests_running",
    "vllm:num_requests_waiting",
]


def test_vllm_dashboard_is_valid_json_with_panels():
    data = json.loads(DASHBOARD.read_text())
    assert data["title"] == "vLLM Serving"
    assert data["panels"], "dashboard has no panels"


def test_vllm_dashboard_references_expected_metrics():
    text = DASHBOARD.read_text()
    for metric in EXPECTED_METRICS:
        assert metric in text, f"dashboard is missing a query for {metric}"
