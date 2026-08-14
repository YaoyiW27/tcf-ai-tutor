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
