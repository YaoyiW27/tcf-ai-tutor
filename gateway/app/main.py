"""Inference gateway — OpenAI-compatible entry point.

Routes ``POST /v1/chat/completions`` to the configured model backend (see
``app.backends``), applies per-key rate limiting, and records Prometheus metrics
(requests, latency, tokens, cost) exposed at ``GET /metrics``.
"""

import time

import anthropic
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from app import backends, cost, metrics, ratelimit
from app.config import settings

app = FastAPI(title="Inference Gateway")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "backend": settings.inference_backend}


@app.get("/metrics")
def metrics_endpoint() -> Response:
    body, content_type = metrics.render()
    return Response(content=body, media_type=content_type)


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> Response:
    key = request.headers.get("authorization", "anon")
    if not ratelimit.allow(key):
        return JSONResponse(
            status_code=429,
            content={"error": {"message": "rate limit exceeded", "type": "rate_limit_error"}},
        )

    body = await request.json()
    model = body.get("model", "unknown")
    backend = settings.inference_backend

    metrics.INFLIGHT.inc()
    started = time.perf_counter()
    try:
        resp, input_tokens, output_tokens = await backends.handle(body)
    except RuntimeError as exc:  # missing key / misconfiguration
        metrics.REQUESTS.labels(backend, model, "503").inc()
        return JSONResponse(
            status_code=503,
            content={"error": {"message": str(exc), "type": "configuration_error"}},
        )
    except (anthropic.APIError, httpx.HTTPError) as exc:  # upstream failure
        metrics.REQUESTS.labels(backend, model, "502").inc()
        return JSONResponse(
            status_code=502,
            content={"error": {"message": str(exc), "type": "upstream_error"}},
        )
    finally:
        metrics.INFLIGHT.dec()
        metrics.LATENCY.labels(backend, model).observe(time.perf_counter() - started)

    metrics.REQUESTS.labels(backend, model, "200").inc()
    metrics.TOKENS_IN.labels(backend, model).inc(input_tokens)
    metrics.TOKENS_OUT.labels(backend, model).inc(output_tokens)
    metrics.COST_USD.labels(backend, model).inc(
        cost.cost_usd(model, input_tokens, output_tokens)
    )
    return JSONResponse(content=resp)
