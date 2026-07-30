"""Compare two gateway benchmark result files side by side.

Reads two JSON files produced by ``bench_gateway.py`` (e.g. a Python run and a
Rust run) and prints a per-concurrency table of QPS and latency percentiles,
plus peak RSS. Used for the Python-vs-Rust gateway comparison
(see ``docs/rust-gateway-benchmark.md``).

    python benchmarks/compare_results.py results/python-*.json results/rust-*.json
"""

import argparse
import json


def load(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def index_by_concurrency(summary: dict) -> dict[int, dict]:
    return {lvl["concurrency"]: lvl for lvl in summary.get("per_concurrency", [])}


def main() -> None:
    p = argparse.ArgumentParser(description="Compare two gateway benchmark runs.")
    p.add_argument("a", help="First result JSON (baseline, e.g. python).")
    p.add_argument("b", help="Second result JSON (e.g. rust).")
    args = p.parse_args()

    a, b = load(args.a), load(args.b)
    la, lb = a.get("label", "A"), b.get("label", "B")
    ia, ib = index_by_concurrency(a), index_by_concurrency(b)
    levels = sorted(set(ia) | set(ib))

    print(f"\n{la}  vs  {lb}")
    print(f"peak RSS (MB):  {la}={a.get('peak_rss_mb')}   {lb}={b.get('peak_rss_mb')}\n")
    header = f"{'conc':>5} | {'metric':>8} | {la:>12} | {lb:>12} | {'Δ (b vs a)':>12}"
    print(header)
    print("-" * len(header))

    def row(conc: int, name: str, va: float | None, vb: float | None) -> None:
        delta = ""
        if isinstance(va, (int, float)) and isinstance(vb, (int, float)) and va:
            delta = f"{(vb - va) / va * 100:+.0f}%"
        sa = "-" if va is None else f"{va}"
        sb = "-" if vb is None else f"{vb}"
        print(f"{conc:>5} | {name:>8} | {sa:>12} | {sb:>12} | {delta:>12}")

    for c in levels:
        ra, rb = ia.get(c, {}), ib.get(c, {})
        lat_a = ra.get("latency_seconds", {})
        lat_b = rb.get("latency_seconds", {})
        row(c, "qps", ra.get("qps"), rb.get("qps"))
        row(c, "p50", lat_a.get("p50"), lat_b.get("p50"))
        row(c, "p95", lat_a.get("p95"), lat_b.get("p95"))
        row(c, "p99", lat_a.get("p99"), lat_b.get("p99"))
        row(c, "errors", ra.get("requests_failed"), rb.get("requests_failed"))
        print("-" * len(header))


if __name__ == "__main__":
    main()
