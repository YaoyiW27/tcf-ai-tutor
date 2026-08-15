"""The gateway's response_format -> guided_json fallback for vLLM.

Runs against the real (extended) mock upstream in-process via httpx ASGITransport —
no network, no GPU — so it exercises the real reject logic + the real gateway retry.
"""

import sys
from pathlib import Path

import httpx
import pytest

import app.backends as backends

# Import the mock upstream (lives under benchmarks/, a different service dir).
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "benchmarks"))
import mock_upstream  # noqa: E402

_SCHEMA_BODY = {
    "model": "m",
    "messages": [{"role": "user", "content": "hi"}],
    "response_format": {
        "type": "json_schema",
        "json_schema": {
            "name": "S",
            "schema": {
                "type": "object",
                "properties": {"x": {"type": "string"}},
                "required": ["x"],
                "additionalProperties": False,
            },
        },
    },
}


@pytest.fixture
def upstream_is_mock(monkeypatch):
    """Point _forward_backend's httpx client at the in-process mock app."""
    monkeypatch.setattr(backends.settings, "upstream_base_url", "http://mock/v1")
    monkeypatch.setattr(backends.settings, "upstream_api_key", "x")

    real_client = httpx.AsyncClient  # capture before patching (httpx module is shared)

    def make_client(*_args, **_kwargs):
        return real_client(
            transport=httpx.ASGITransport(app=mock_upstream.app), base_url="http://mock"
        )

    monkeypatch.setattr(backends.httpx, "AsyncClient", make_client)
    mock_upstream.last_request = {}
    backends._rejects_response_format.clear()  # per-upstream memo must not leak across tests


async def test_forward_backend_retries_with_guided_json_when_response_format_rejected(
    upstream_is_mock, monkeypatch
):
    monkeypatch.setenv("MOCK_REJECT_RESPONSE_FORMAT", "1")  # upstream rejects response_format
    data, _in, _out, _sec = await backends._forward_backend(dict(_SCHEMA_BODY))
    # The fallback request succeeded and returned a real completion.
    assert data["choices"][0]["message"]["content"]
    # The body the mock ultimately accepted was the translated one.
    assert mock_upstream.last_request.get("guided_json") is not None
    assert "response_format" not in mock_upstream.last_request


async def test_forward_backend_no_retry_when_upstream_accepts_response_format(
    upstream_is_mock, monkeypatch
):
    monkeypatch.delenv("MOCK_REJECT_RESPONSE_FORMAT", raising=False)  # upstream accepts it
    data, _in, _out, _sec = await backends._forward_backend(dict(_SCHEMA_BODY))
    assert data["choices"][0]["message"]["content"]
    # No fallback: response_format kept, guided_json never added.
    assert "response_format" in mock_upstream.last_request
    assert "guided_json" not in mock_upstream.last_request


async def test_forward_backend_no_retry_on_unrelated_400(upstream_is_mock, monkeypatch):
    """A 400 that isn't about response_format (e.g. context-length) must not fall back.

    Regression: the old code retried any 400 carrying a json_schema, so a
    context-length 400 was sent twice (double GPU spend on a metered box) and
    surfaced the retry's error, masking the real cause.
    """
    monkeypatch.setenv("MOCK_REJECT_CONTEXT_LENGTH", "1")
    with pytest.raises(httpx.HTTPStatusError) as exc:
        await backends._forward_backend(dict(_SCHEMA_BODY))
    assert exc.value.response.status_code == 400
    # The upstream saw the original response_format body and was NOT retried with guided_json.
    assert "response_format" in mock_upstream.last_request
    assert "guided_json" not in mock_upstream.last_request
    # The context-length 400 is not a capability signal, so nothing is memoized.
    assert backends._rejects_response_format == {}


async def test_forward_backend_memoizes_reject_so_it_probes_once(
    upstream_is_mock, monkeypatch
):
    """After one probe, a rejecting upstream is sent guided_json up front (no re-probe)."""
    monkeypatch.setenv("MOCK_REJECT_RESPONSE_FORMAT", "1")
    await backends._forward_backend(dict(_SCHEMA_BODY))  # first call probes, learns reject
    assert backends._rejects_response_format.get("http://mock/v1") is True

    # Second call: the mock records the body it received first. If the gateway sent
    # response_format again it would 400 (reject mode) then retry; instead it should
    # send guided_json directly, so the mock never sees response_format.
    mock_upstream.last_request = {}
    data, _in, _out, _sec = await backends._forward_backend(dict(_SCHEMA_BODY))
    assert data["choices"][0]["message"]["content"]
    assert mock_upstream.last_request.get("guided_json") is not None
    assert "response_format" not in mock_upstream.last_request
