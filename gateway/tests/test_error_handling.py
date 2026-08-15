"""The /v1/chat/completions endpoint maps failures to the right HTTP status.

Rate limiting and the backend are mocked so nothing external is called.
"""

import httpx

import app.backends as backends
import app.ratelimit as ratelimit
from app.config import settings

_BODY = {"model": "m", "messages": [{"role": "user", "content": "hi"}]}


def test_missing_key_runtimeerror_returns_503(client, monkeypatch):
    monkeypatch.setattr(ratelimit, "allow", lambda key: True)

    async def boom(body):
        raise RuntimeError("ANTHROPIC_API_KEY is not set")

    monkeypatch.setattr(backends, "handle", boom)
    assert client.post("/v1/chat/completions", json=_BODY).status_code == 503


def test_upstream_error_returns_502(client, monkeypatch):
    monkeypatch.setattr(ratelimit, "allow", lambda key: True)

    async def boom(body):
        raise httpx.HTTPError("upstream down")

    monkeypatch.setattr(backends, "handle", boom)
    assert client.post("/v1/chat/completions", json=_BODY).status_code == 502


def test_rate_limited_returns_429(client, monkeypatch):
    monkeypatch.setattr(ratelimit, "allow", lambda key: False)
    assert client.post("/v1/chat/completions", json=_BODY).status_code == 429


def test_rate_limited_request_is_counted(client, monkeypatch, counter):
    """A throttled request must still show up in the metrics.

    Returning 429 without recording it makes rate limiting invisible: the
    dashboard cannot tell "the limiter is shedding load" from "traffic stopped",
    which is exactly when the difference matters. The model label is "unknown"
    on purpose — the limiter rejects before the body is parsed.
    """
    monkeypatch.setattr(ratelimit, "allow", lambda key: False)
    labels = {"backend": settings.inference_backend, "model": "unknown", "status": "429"}
    before = counter("gateway_requests_total", **labels)

    assert client.post("/v1/chat/completions", json=_BODY).status_code == 429

    assert counter("gateway_requests_total", **labels) == before + 1


def test_success_returns_openai_shape(client, monkeypatch):
    monkeypatch.setattr(ratelimit, "allow", lambda key: True)

    async def ok(body):
        return ({"id": "chatcmpl-x", "object": "chat.completion"}, 40, 64, 0.05)

    monkeypatch.setattr(backends, "handle", ok)
    resp = client.post("/v1/chat/completions", json=_BODY)
    assert resp.status_code == 200
    assert resp.json()["id"] == "chatcmpl-x"
