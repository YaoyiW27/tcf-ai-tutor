"""Embeddings passthrough — routing, metering, and error mapping (no network).

The `/v1/embeddings` endpoint always forwards to OpenAI (Anthropic has no
embeddings API) and records its own metric family, kept separate from the chat
counters so the chat dashboards and the inflight-based HPA signal stay chat-only.
These tests mock the upstream HTTP call — no real OpenAI request is made.
"""

import httpx
import pytest
from prometheus_client import Counter, Histogram

from app import backends, cost, metrics


def _embedding_response(prompt_tokens: int = 7) -> dict:
    """A minimal OpenAI-shaped embeddings response body."""
    return {
        "object": "list",
        "data": [{"object": "embedding", "index": 0, "embedding": [0.1, 0.2, 0.3]}],
        "model": "text-embedding-3-small",
        "usage": {"prompt_tokens": prompt_tokens, "total_tokens": prompt_tokens},
    }


class _StubResponse:
    def __init__(self, status_code: int, json_body: dict):
        self.status_code = status_code
        self._json = json_body
        self.text = str(json_body)

    def json(self) -> dict:
        return self._json

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=None)


def _stub_client(monkeypatch, response: _StubResponse, recorder: dict | None = None):
    """Patch httpx.AsyncClient so backends.embeddings hits our stub, not the network."""

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json, headers):
            if recorder is not None:
                recorder["url"] = url
                recorder["json"] = json
                recorder["headers"] = headers
            return response

    monkeypatch.setattr(backends.httpx, "AsyncClient", _Client)


# ---- metric contract -------------------------------------------------------


def test_embedding_metric_families_types_and_labels():
    # Embeddings have no `backend` label (always OpenAI) — model alone identifies.
    assert isinstance(metrics.EMBED_REQUESTS, Counter)
    assert tuple(metrics.EMBED_REQUESTS._labelnames) == ("model", "status")
    assert isinstance(metrics.EMBED_LATENCY, Histogram)
    assert tuple(metrics.EMBED_LATENCY._labelnames) == ("model",)
    assert isinstance(metrics.EMBED_TOKENS, Counter)
    assert tuple(metrics.EMBED_TOKENS._labelnames) == ("model",)
    assert isinstance(metrics.EMBED_COST_USD, Counter)
    assert tuple(metrics.EMBED_COST_USD._labelnames) == ("model",)


# ---- backends.embeddings ---------------------------------------------------


async def test_embeddings_forwards_to_openai_and_returns_usage(monkeypatch):
    monkeypatch.setattr(backends.settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(backends.settings, "openai_base_url", "https://api.openai.com/v1")
    recorder: dict = {}
    _stub_client(monkeypatch, _StubResponse(200, _embedding_response(7)), recorder)

    body = {"model": "text-embedding-3-small", "input": "bonjour"}
    data, input_tokens, upstream_seconds = await backends.embeddings(body)

    assert data["data"][0]["embedding"] == [0.1, 0.2, 0.3]
    assert input_tokens == 7
    assert upstream_seconds >= 0.0
    # Forwarded verbatim to the OpenAI embeddings URL with the OpenAI key.
    assert recorder["url"] == "https://api.openai.com/v1/embeddings"
    assert recorder["json"] == body
    assert recorder["headers"]["Authorization"] == "Bearer sk-test"


async def test_embeddings_missing_key_raises(monkeypatch):
    monkeypatch.setattr(backends.settings, "openai_api_key", None)
    with pytest.raises(RuntimeError):
        await backends.embeddings({"model": "text-embedding-3-small", "input": "x"})


async def test_embeddings_independent_of_inference_backend(monkeypatch):
    # Chat backend is anthropic, but embeddings must still route to OpenAI.
    monkeypatch.setattr(backends.settings, "inference_backend", "anthropic")
    monkeypatch.setattr(backends.settings, "openai_api_key", "sk-test")
    _stub_client(monkeypatch, _StubResponse(200, _embedding_response()))
    data, _tokens, _secs = await backends.embeddings({"model": "text-embedding-3-small", "input": "x"})
    assert data["object"] == "list"


# ---- endpoint + metrics ----------------------------------------------------


def test_endpoint_success_records_metrics(client, counter, monkeypatch):
    async def fake_embeddings(body):
        return _embedding_response(11), 11, 0.02

    monkeypatch.setattr(backends, "embeddings", fake_embeddings)

    model = "text-embedding-3-small"
    before_req = counter("gateway_embedding_requests_total", model=model, status="200")
    before_tok = counter("gateway_embedding_tokens_input_total", model=model)
    before_cost = counter("gateway_embedding_cost_usd_total", model=model)

    resp = client.post("/v1/embeddings", json={"model": model, "input": "bonjour"})
    assert resp.status_code == 200
    assert resp.json()["data"][0]["embedding"] == [0.1, 0.2, 0.3]

    assert counter("gateway_embedding_requests_total", model=model, status="200") == before_req + 1
    assert counter("gateway_embedding_tokens_input_total", model=model) == before_tok + 11
    # 11 tokens * $0.02 / 1M
    assert counter("gateway_embedding_cost_usd_total", model=model) == pytest.approx(
        before_cost + cost.cost_usd(model, 11, 0)
    )


def test_endpoint_missing_key_returns_503(client, counter, monkeypatch):
    async def fake_embeddings(body):
        raise RuntimeError("OPENAI_API_KEY is not set")

    monkeypatch.setattr(backends, "embeddings", fake_embeddings)

    before = counter("gateway_embedding_requests_total", model="m", status="503")
    resp = client.post("/v1/embeddings", json={"model": "m", "input": "x"})
    assert resp.status_code == 503
    assert counter("gateway_embedding_requests_total", model="m", status="503") == before + 1


def test_endpoint_upstream_error_returns_502(client, counter, monkeypatch):
    async def fake_embeddings(body):
        raise httpx.HTTPError("boom")

    monkeypatch.setattr(backends, "embeddings", fake_embeddings)

    before = counter("gateway_embedding_requests_total", model="m", status="502")
    resp = client.post("/v1/embeddings", json={"model": "m", "input": "x"})
    assert resp.status_code == 502
    assert counter("gateway_embedding_requests_total", model="m", status="502") == before + 1


def test_endpoint_rate_limited_returns_429_and_counts(client, counter, monkeypatch):
    monkeypatch.setattr("app.main.ratelimit.allow", lambda key: False)
    before = counter("gateway_embedding_requests_total", model="unknown", status="429")
    resp = client.post("/v1/embeddings", json={"model": "m", "input": "x"})
    assert resp.status_code == 429
    assert (
        counter("gateway_embedding_requests_total", model="unknown", status="429")
        == before + 1
    )
