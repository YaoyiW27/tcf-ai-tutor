"""Model-backend routing for the gateway.

Takes an OpenAI-compatible chat-completions request body and fulfils it against
the configured backend, always returning an OpenAI-shaped ``chat.completion``
dict plus ``(input_tokens, output_tokens)`` for metrics.

- ``anthropic`` — translate to the Anthropic Messages API. Structured output
  (the request's ``response_format`` JSON schema) is fulfilled with Anthropic's
  native structured outputs (``output_config.format``), which is compatible with
  extended thinking — the same mechanism ``messages.parse`` uses, so grading
  behaviour matches the pre-gateway path. The JSON comes back as the response
  text block.
- ``openai`` / ``vllm`` — forward verbatim to an OpenAI-compatible upstream
  (``UPSTREAM_BASE_URL``); ``response_format`` / guided JSON passes straight
  through.
"""

import time

import httpx
from anthropic import AsyncAnthropic

# Anthropic's own JSON-schema normaliser, so an OpenAI-strict schema is accepted
# by the Messages structured-outputs API. Private path, pinned SDK version.
from anthropic.lib._parse._transform import transform_schema

from app.config import settings

_anthropic: AsyncAnthropic | None = None


def _anthropic_client() -> AsyncAnthropic:
    global _anthropic
    if settings.anthropic_api_key is None:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    if _anthropic is None:
        _anthropic = AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _anthropic


def _thinking(reasoning_effort: str | None, max_tokens: int) -> tuple[dict | None, int]:
    """Map a provider-agnostic reasoning effort to an Anthropic thinking config.

    Returns ``(thinking, max_tokens)``; max_tokens may be bumped so it stays
    above the thinking budget (Anthropic requires ``budget_tokens < max_tokens``).
    """
    effort = (reasoning_effort or "medium").lower()
    if effort == "medium":
        return {"type": "adaptive"}, max_tokens
    budget = 1024 if effort == "low" else 4096  # low | high
    if max_tokens <= budget:
        max_tokens = budget + 512
    return {"type": "enabled", "budget_tokens": budget}, max_tokens


def _openai_shape(
    request_id: str, model: str, content: str, input_tokens: int, output_tokens: int
) -> dict:
    """Wrap a completion string in an OpenAI ``chat.completion`` response."""
    return {
        "id": f"chatcmpl-{request_id}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": input_tokens,
            "completion_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        },
    }


async def _anthropic_backend(body: dict) -> tuple[dict, int, int]:
    client = _anthropic_client()
    messages = body.get("messages", [])
    system = "\n\n".join(
        m["content"] for m in messages if m.get("role") == "system"
    )
    conversation = [
        {"role": m["role"], "content": m["content"]}
        for m in messages
        if m.get("role") in ("user", "assistant")
    ]
    max_tokens = int(body.get("max_completion_tokens") or body.get("max_tokens") or 4096)
    thinking, max_tokens = _thinking(body.get("reasoning_effort"), max_tokens)

    kwargs: dict = {"model": body["model"], "max_tokens": max_tokens, "messages": conversation}
    if system:
        kwargs["system"] = system
    if thinking:
        kwargs["thinking"] = thinking

    schema = (body.get("response_format") or {}).get("json_schema", {}).get("schema")
    extra_body = {}
    if schema is not None:
        extra_body["output_config"] = {
            "format": {"type": "json_schema", "schema": transform_schema(schema)}
        }

    resp = await client.messages.create(**kwargs, extra_body=extra_body)
    text = "".join(b.text for b in resp.content if b.type == "text")
    usage = resp.usage
    out = _openai_shape(
        resp.id, body["model"], text, usage.input_tokens, usage.output_tokens
    )
    return out, usage.input_tokens, usage.output_tokens


async def _forward_backend(body: dict) -> tuple[dict, int, int]:
    if not settings.upstream_base_url:
        raise RuntimeError("UPSTREAM_BASE_URL is not set")
    headers = {"Authorization": f"Bearer {settings.upstream_api_key or ''}"}
    url = f"{settings.upstream_base_url.rstrip('/')}/chat/completions"
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(url, json=body, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    usage = data.get("usage") or {}
    return data, int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))


async def handle(body: dict) -> tuple[dict, int, int]:
    """Route a chat-completions request to the configured backend."""
    backend = settings.inference_backend
    if backend == "anthropic":
        return await _anthropic_backend(body)
    if backend in ("openai", "vllm"):
        return await _forward_backend(body)
    raise RuntimeError(f"unknown INFERENCE_BACKEND: {backend!r}")
