"""Deterministic OpenAI-compatible upstream for benchmarking the gateway.

Stands in for a real model server so gateway benchmarks are free, reproducible,
and low-variance — the fixed delay + fixed token usage let us measure the latency
the *gateway* adds rather than model variability. Point the gateway's forward
path at it (`INFERENCE_BACKEND=openai`, `UPSTREAM_BASE_URL=http://localhost:9000/v1`).

Run (reuse the gateway venv — needs only fastapi + uvicorn):

    MOCK_DELAY_MS=1   uvicorn benchmarks.mock_upstream:app --port 9000   # fast profile
    MOCK_DELAY_MS=100 uvicorn benchmarks.mock_upstream:app --port 9000   # realistic profile

`MOCK_DELAY_MS` (env) sets the simulated upstream latency; the per-request
`?delay_ms=` query param overrides it. Token counts are fixed and configurable
via `MOCK_PROMPT_TOKENS` / `MOCK_COMPLETION_TOKENS`.
"""

import asyncio
import os
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="Mock Upstream")

DEFAULT_DELAY_MS = float(os.environ.get("MOCK_DELAY_MS", "1"))
PROMPT_TOKENS = int(os.environ.get("MOCK_PROMPT_TOKENS", "40"))
COMPLETION_TOKENS = int(os.environ.get("MOCK_COMPLETION_TOKENS", "64"))
CONTENT = "Apprendre une langue étrangère ouvre l'esprit et crée des opportunités."


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> JSONResponse:
    body = await request.json()
    delay_ms = float(request.query_params.get("delay_ms", DEFAULT_DELAY_MS))
    if delay_ms > 0:
        await asyncio.sleep(delay_ms / 1000.0)
    return JSONResponse(
        {
            "id": "chatcmpl-mock",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": body.get("model", "mock-model"),
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": CONTENT},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": PROMPT_TOKENS,
                "completion_tokens": COMPLETION_TOKENS,
                "total_tokens": PROMPT_TOKENS + COMPLETION_TOKENS,
            },
        }
    )
