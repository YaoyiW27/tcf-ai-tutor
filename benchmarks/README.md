# benchmarks/ — Serving benchmarks

**Status: planned.**

Reproducible performance measurements for the serving layer. Planned contents:

- A benchmark harness: fixed prompt set → measure **TTFT**, total latency, **tokens/sec**,
  and throughput (QPS) under concurrency.
- Comparison runs across configs — e.g. **FP16 vs AWQ-4bit** — with results saved as
  CSV/JSON and summarized in a table.
- Instructions to reproduce (which GPU, which model, how to run).

Distinct from the *model-quality* evals in `backend/scripts/eval_*` (grader/examiner
correctness); those feed the ML pipeline in `pipeline/`.

See [../docs/architecture-v2-infra.md](../docs/architecture-v2-infra.md).
