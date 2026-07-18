"""Load benchmark for the inference gateway.

Fires N chat-completion requests at the gateway at a fixed concurrency, using a
common prompt, and reports latency percentiles, throughput (QPS), and output
tokens/sec. Results are printed and written to ``benchmarks/results/``.

Run (either venv that has `openai` works; point at a running gateway):

    python benchmarks/bench_gateway.py --n 20 --concurrency 4
    python benchmarks/bench_gateway.py --url http://localhost:8001/v1 --model claude-sonnet-4-6

This measures the *serving path* (gateway → backend), not grading quality.
"""

import argparse
import asyncio
import json
import os
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


async def run(args: argparse.Namespace) -> dict:
    client = AsyncOpenAI(base_url=args.url, api_key="sk-bench")
    sem = asyncio.Semaphore(args.concurrency)
    results: list[dict] = []
    errors = 0

    async def worker() -> None:
        nonlocal errors
        async with sem:
            try:
                results.append(await one_request(client, args.model, args.max_tokens))
            except Exception as exc:  # noqa: BLE001 - record and continue
                errors += 1
                print(f"  request failed: {exc}")

    wall_start = time.perf_counter()
    await asyncio.gather(*(worker() for _ in range(args.n)))
    wall = time.perf_counter() - wall_start

    latencies = [r["latency"] for r in results]
    total_out = sum(r["output_tokens"] for r in results)
    total_in = sum(r["input_tokens"] for r in results)
    ok = len(results)
    return {
        "config": {
            "url": args.url,
            "model": args.model,
            "n": args.n,
            "concurrency": args.concurrency,
            "max_tokens": args.max_tokens,
        },
        "requests_ok": ok,
        "requests_failed": errors,
        "wall_seconds": round(wall, 2),
        "qps": round(ok / wall, 2) if wall else 0.0,
        "latency_seconds": {
            "p50": round(percentile(latencies, 50), 2),
            "p95": round(percentile(latencies, 95), 2),
            "p99": round(percentile(latencies, 99), 2),
            "mean": round(sum(latencies) / ok, 2) if ok else 0.0,
        },
        "tokens": {"input_total": total_in, "output_total": total_out},
        "output_tokens_per_sec": round(total_out / wall, 1) if wall else 0.0,
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Benchmark the inference gateway.")
    p.add_argument("--url", default="http://localhost:8001/v1", help="Gateway base URL.")
    p.add_argument("--model", default="claude-sonnet-4-6")
    p.add_argument("--n", type=int, default=20, help="Total requests.")
    p.add_argument("--concurrency", type=int, default=4)
    p.add_argument("--max-tokens", type=int, default=256, dest="max_tokens")
    p.add_argument("--ts", default="", help="Timestamp label for the output file.")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    summary = asyncio.run(run(args))
    print(json.dumps(summary, indent=2, ensure_ascii=False))

    results_dir = os.path.join(os.path.dirname(__file__), "results")
    os.makedirs(results_dir, exist_ok=True)
    label = args.ts or str(int(time.time()))
    out_path = os.path.join(results_dir, f"gateway-{args.model}-{label}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"\nsaved: {out_path}")


if __name__ == "__main__":
    main()
