"""The `impl` half of the metric contract.

`impl` isn't emitted by the gateway app (kept identical for a future Rust
implementation); Prometheus attaches it at scrape time. The dashboard groups
`by (impl)`, so these guard that the scrape configs + ServiceMonitor actually
declare `impl=python`.
"""

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]


def _impl_labels(path: str) -> list[str]:
    cfg = yaml.safe_load((REPO / path).read_text())
    out = []
    for job in cfg.get("scrape_configs", []):
        for static in job.get("static_configs", []):
            labels = static.get("labels") or {}
            if "impl" in labels:
                out.append(labels["impl"])
    return out


def test_compose_prometheus_sets_impl_python():
    assert "python" in _impl_labels("infra/compose/prometheus.yml")


def test_observability_prometheus_sets_impl_python():
    assert "python" in _impl_labels("infra/observability/prometheus.yml")


def test_servicemonitor_relabels_impl_python():
    # Go-templated file — assert as text (not YAML-parseable).
    text = (REPO / "infra/k8s/tcf/templates/servicemonitor.yaml").read_text()
    assert "targetLabel: impl" in text
    assert "replacement: python" in text
