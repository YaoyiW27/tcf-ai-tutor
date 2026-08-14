"""Backend routing + pure request/response helpers (no real LLM calls)."""

import pytest

import app.backends as backends


def _stub_backends(monkeypatch):
    async def anthro(body):
        return ("ANTHRO", 1, 2, 0.1)

    async def forward(body):
        return ("FORWARD", 0, 0, 0.0)

    monkeypatch.setattr(backends, "_anthropic_backend", anthro)
    monkeypatch.setattr(backends, "_forward_backend", forward)


async def test_handle_routes_anthropic_backend(monkeypatch):
    _stub_backends(monkeypatch)
    monkeypatch.setattr(backends.settings, "inference_backend", "anthropic")
    result = await backends.handle({})
    assert result[0] == "ANTHRO"


async def test_handle_routes_openai_and_vllm_to_forward(monkeypatch):
    _stub_backends(monkeypatch)
    for backend in ("openai", "vllm"):
        monkeypatch.setattr(backends.settings, "inference_backend", backend)
        result = await backends.handle({})
        assert result[0] == "FORWARD", backend


async def test_handle_unknown_backend_raises(monkeypatch):
    monkeypatch.setattr(backends.settings, "inference_backend", "bogus")
    with pytest.raises(RuntimeError):
        await backends.handle({})


def test_thinking_maps_effort_low_medium_high_and_bumps_max_tokens():
    assert backends._thinking("low", 2000) == ({"type": "enabled", "budget_tokens": 1024}, 2000)
    # max_tokens bumped above the budget when too small
    assert backends._thinking("low", 1000)[1] == 1536
    assert backends._thinking("high", 8000) == ({"type": "enabled", "budget_tokens": 4096}, 8000)
    assert backends._thinking("medium", 8000) == ({"type": "adaptive"}, 8000)
    assert backends._thinking(None, 8000)[0] == {"type": "adaptive"}  # default = medium


def test_openai_shape_maps_usage_and_wraps_content():
    out = backends._openai_shape("abc", "claude-x", "hello", 40, 64)
    assert out["id"] == "chatcmpl-abc"
    assert out["model"] == "claude-x"
    assert out["choices"][0]["message"]["content"] == "hello"
    assert out["usage"] == {"prompt_tokens": 40, "completion_tokens": 64, "total_tokens": 104}
