"""Reusable load benchmark for an inference gateway.

Implementation-agnostic: point it at any gateway that speaks the OpenAI
chat-completions API (the Python gateway today, a Rust one later) and label the
run. Sweeps a list of concurrency levels, and for each records QPS, latency
percentiles, and errors; optionally samples the gateway process RSS. Results are
printed and saved to ``benchmarks/results/<label>-<ts>.json`` for side-by-side
comparison (see ``compare_results.py``).

For a fair gateway-overhead comparison, run the gateway's forward path against
the deterministic ``mock_upstream`` rather than a real model. See
``docs/rust-gateway-benchmark.md``.

Examples:
    python benchmarks/bench_gateway.py --label python --concurrency 1,4,8,16,32 --n 200
    python benchmarks/bench_gateway.py --url http://localhost:8001/v1 --pid 12345
"""

import argparse
import asyncio
import json
import os
import platform
import subprocess
import time

from openai import AsyncOpenAI

PROMPT = "En une phrase, explique pourquoi apprendre une langue étrangère est utile."


def percentile(values: list[float], p: float) -> float:
    """Nearest-rank percentile of a list (p in 0..100)."""
    if not values:
        return 0.0
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, round(p / 100 * len(ordered) + 0.5) - 1))
    return ordered[k]


def _rss_kb(pid: int) -> int:
    """Resident set size of a pid in KB via ``ps`` (macOS/Linux); 0 on failure."""
    try:
        out = subprocess.run(
            ["ps", "-o", "rss=", "-p", str(pid)],
            capture_output=True,
            text=True,
            check=False,
        )
        return int(out.stdout.strip() or 0)
    except (ValueError, OSError):
        return 0


async def _sample_rss(pid: int, peak: list[int], stop: asyncio.Event) -> None:
    while not stop.is_set():
        peak[0] = max(peak[0], _rss_kb(pid))
        try:
            await asyncio.wait_for(stop.wait(), timeout=0.2)
        except asyncio.TimeoutError:
            pass


async def one_request(client: AsyncOpenAI, model: str, max_tokens: int) -> dict:
    start = time.perf_counter()
    resp = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": PROMPT}],
        max_completion_tokens=max_tokens,
    )
    latency = time.perf_counter() - start
    usage = resp.usage
    return {
        "latency": latency,
        "input_tokens": usage.prompt_tokens if usage else 0,
        "output_tokens": usage.completion_tokens if usage else 0,
    }


async def run_level(
    client: AsyncOpenAI, model: str, max_tokens: int, n: int, concurrency: int
) -> dict:
    """Fire ``n`` requests at a fixed ``concurrency`` and summarize."""
    sem = asyncio.Semaphore(concurrency)
    results: list[dict] = []
    errors = 0

    async def worker() -> None:
        nonlocal errors
        async with sem:
            try:
                results.append(await one_request(client, model, max_tokens))
            except Exception as exc:  # noqa: BLE001 - record and continue
                errors += 1
                print(f"  [c={concurrency}] request failed: {exc}")

    wall_start = time.perf_counter()
    await asyncio.gather(*(worker() for _ in range(n)))
    wall = time.perf_counter() - wall_start

    latencies = [r["latency"] for r in results]
    ok = len(results)
    total_out = sum(r["output_tokens"] for r in results)
    return {
        "concurrency": concurrency,
        "requests_ok": ok,
        "requests_failed": errors,
        "wall_seconds": round(wall, 3),
        "qps": round(ok / wall, 2) if wall else 0.0,
        "latency_seconds": {
            "p50": round(percentile(latencies, 50), 4),
            "p95": round(percentile(latencies, 95), 4),
            "p99": round(percentile(latencies, 99), 4),
            "mean": round(sum(latencies) / ok, 4) if ok else 0.0,
        },
        "output_tokens_per_sec": round(total_out / wall, 1) if wall else 0.0,
    }


async def run(args: argparse.Namespace) -> dict:
    client = AsyncOpenAI(base_url=args.url, api_key="sk-bench")
    levels = [int(x) for x in str(args.concurrency).split(",") if x.strip()]

    peak = [0]
    stop = asyncio.Event()
    sampler = (
        asyncio.create_task(_sample_rss(args.pid, peak, stop)) if args.pid else None
    )

    per_concurrency: list[dict] = []
    try:
        for c in levels:
            level = await run_level(client, args.model, args.max_tokens, args.n, c)
            per_concurrency.append(level)
            lat = level["latency_seconds"]
            print(
                f"c={c:>4}  qps={level['qps']:>7}  "
                f"p50={lat['p50']}s p95={lat['p95']}s p99={lat['p99']}s  "
                f"errors={level['requests_failed']}"
            )
    finally:
        if sampler is not None:
            stop.set()
            await sampler

    return {
        "label": args.label,
        "config": {
            "url": args.url,
            "model": args.model,
            "n_per_level": args.n,
            "concurrency_levels": levels,
            "max_tokens": args.max_tokens,
        },
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "cpu_count": os.cpu_count(),
        },
        "peak_rss_mb": round(peak[0] / 1024, 1) if args.pid else None,
        "per_concurrency": per_concurrency,
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Benchmark an inference gateway.")
    p.add_argument("--url", default="http://localhost:8001/v1", help="Gateway base URL.")
    p.add_argument("--model", default="claude-sonnet-4-6")
    p.add_argument("--label", default="python", help="Implementation label (e.g. python|rust).")
    p.add_argument("--n", type=int, default=200, help="Requests per concurrency level.")
    p.add_argument(
        "--concurrency",
        default="1,4,8,16,32",
        help="Comma-separated concurrency levels to sweep (or a single int).",
    )
    p.add_argument("--max-tokens", type=int, default=256, dest="max_tokens")
    p.add_argument("--pid", type=int, default=0, help="Gateway PID to sample RSS (peak).")
    p.add_argument("--ts", default="", help="Timestamp label for the output file.")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    summary = asyncio.run(run(args))
    print("\n" + json.dumps(summary, indent=2, ensure_ascii=False))

    results_dir = os.path.join(os.path.dirname(__file__), "results")
    os.makedirs(results_dir, exist_ok=True)
    label = args.ts or str(int(time.time()))
    out_path = os.path.join(results_dir, f"{args.label}-{label}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"\nsaved: {out_path}")


if __name__ == "__main__":
    main()
