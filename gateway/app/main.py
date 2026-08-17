"""Inference gateway — OpenAI-compatible entry point.

Routes ``POST /v1/chat/completions`` to the configured model backend (see
``app.backends``), applies per-key rate limiting, and records Prometheus metrics
(requests, latency, tokens, cost) exposed at ``GET /metrics``. ``POST
/v1/embeddings`` is an OpenAI-compatible passthrough (always routed to OpenAI)
for the RAG workload, metered on its own metric family.
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
        # Count throttled requests too. Returning 429 without recording it makes
        # rate limiting invisible on the dashboard — "the limiter is shedding
        # load" and "traffic stopped" look identical, which is exactly when the
        # difference matters. The model label is "unknown" because we reject
        # before parsing the body, which is the point: do no work for a request
        # that is already over its limit.
        metrics.REQUESTS.labels(settings.inference_backend, "unknown", "429").inc()
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
        resp, input_tokens, output_tokens, upstream_seconds = await backends.handle(body)
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

    # Split total latency into upstream (model) time vs the gateway's own
    # overhead — overhead is the metric the Python-vs-Rust A/B turns on.
    total = time.perf_counter() - started
    metrics.UPSTREAM_LATENCY.labels(backend, model).observe(upstream_seconds)
    metrics.OVERHEAD.labels(backend, model).observe(max(0.0, total - upstream_seconds))

    metrics.REQUESTS.labels(backend, model, "200").inc()
    metrics.TOKENS_IN.labels(backend, model).inc(input_tokens)
    metrics.TOKENS_OUT.labels(backend, model).inc(output_tokens)
    metrics.COST_USD.labels(backend, model).inc(
        cost.cost_usd(model, input_tokens, output_tokens)
    )
    return JSONResponse(content=resp)


@app.post("/v1/embeddings")
async def embeddings(request: Request) -> Response:
    """OpenAI-compatible embeddings passthrough (always routed to OpenAI).

    Metered/rate-limited like chat so RAG embedding calls are visible on the
    dashboard. Kept on its own metric family and deliberately outside the chat
    inflight gauge (which drives the HPA) so the autoscale signal stays chat-only.
    """
    key = request.headers.get("authorization", "anon")
    if not ratelimit.allow(key):
        metrics.EMBED_REQUESTS.labels("unknown", "429").inc()
        return JSONResponse(
            status_code=429,
            content={"error": {"message": "rate limit exceeded", "type": "rate_limit_error"}},
        )

    body = await request.json()
    model = body.get("model", "unknown")

    started = time.perf_counter()
    try:
        resp, input_tokens, _upstream_seconds = await backends.embeddings(body)
    except RuntimeError as exc:  # missing key / misconfiguration
        metrics.EMBED_REQUESTS.labels(model, "503").inc()
        return JSONResponse(
            status_code=503,
            content={"error": {"message": str(exc), "type": "configuration_error"}},
        )
    except (anthropic.APIError, httpx.HTTPError) as exc:  # upstream failure
        metrics.EMBED_REQUESTS.labels(model, "502").inc()
        return JSONResponse(
            status_code=502,
            content={"error": {"message": str(exc), "type": "upstream_error"}},
        )
    finally:
        metrics.EMBED_LATENCY.labels(model).observe(time.perf_counter() - started)

    metrics.EMBED_REQUESTS.labels(model, "200").inc()
    metrics.EMBED_TOKENS.labels(model).inc(input_tokens)
    metrics.EMBED_COST_USD.labels(model).inc(cost.cost_usd(model, input_tokens, 0))
    return JSONResponse(content=resp)
