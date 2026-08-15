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


async def _anthropic_backend(body: dict) -> tuple[dict, int, int, float]:
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

    upstream_start = time.perf_counter()
    resp = await client.messages.create(**kwargs, extra_body=extra_body)
    upstream_seconds = time.perf_counter() - upstream_start
    text = "".join(b.text for b in resp.content if b.type == "text")
    usage = resp.usage
    out = _openai_shape(
        resp.id, body["model"], text, usage.input_tokens, usage.output_tokens
    )
    return out, usage.input_tokens, usage.output_tokens, upstream_seconds


def _has_json_schema(body: dict) -> bool:
    return (body.get("response_format") or {}).get("type") == "json_schema"


def _to_guided_json(body: dict) -> dict:
    """Translate OpenAI ``response_format: json_schema`` → vLLM's ``guided_json``.

    Some (older) vLLM servers reject ``response_format`` and expect the schema as
    the top-level ``guided_json`` param. Symmetric with ``_anthropic_backend``,
    which translates the same schema to Anthropic's ``output_config`` — the app
    never sees the backend's quirks (it always sends OpenAI ``response_format``).
    """
    out = dict(body)
    schema = (out.pop("response_format", {}) or {}).get("json_schema", {}).get("schema")
    if schema is not None:
        out["guided_json"] = schema
    return out


def _is_response_format_error(resp: httpx.Response) -> bool:
    """Whether a 400 specifically means the upstream can't handle ``response_format``.

    A json_schema request can 400 for unrelated reasons — a context-length overflow
    (``prompt + max_completion_tokens > --max-model-len``), a malformed schema, etc.
    Retrying *those* with ``guided_json`` wastes a second (metered) round trip and
    then surfaces the retry's error, masking the real cause. Only the "field not
    supported" case should fall back, so we key on the upstream naming the field.

    Known limitation: this is a substring match on the upstream's error prose, so
    it is coupled to that wording. An upstream that echoed the request body back
    in its 400 detail would trip it (the body contains ``response_format``).
    vLLM does not — its context-length error names only the token counts — but a
    structured error code would be sturdier than string matching.
    """
    if resp.status_code != 400:
        return False
    return "response_format" in resp.text.lower()


# Per-upstream memo: has this base_url been observed to reject ``response_format``?
# Set on the first probe so an older vLLM costs a probe rather than a retry on
# every request. Two boundaries worth naming:
#
# 1. The verdict is never invalidated. If the same URL is later upgraded to a
#    vLLM that has dropped the deprecated ``guided_json``, this keeps sending it
#    and the resulting 400 names ``guided_json`` — not ``response_format`` — so
#    no retry fires and the process cannot recover without a restart. A TTL, or
#    clearing the memo when a guided_json request itself 400s, would close that.
# 2. "One probe" holds per process, per URL, and only under serial load: requests
#    that arrive before the first probe resolves each probe independently, so a
#    burst of N concurrent calls against an old upstream costs up to N probes.
#    Same shape as the per-process rate limiter in ``app.ratelimit`` — correct for
#    one replica, and a shared store is what changes it.
_rejects_response_format: dict[str, bool] = {}


async def _forward_backend(body: dict) -> tuple[dict, int, int, float]:
    if not settings.upstream_base_url:
        raise RuntimeError("UPSTREAM_BASE_URL is not set")
    base = settings.upstream_base_url.rstrip("/")
    headers = {"Authorization": f"Bearer {settings.upstream_api_key or ''}"}
    url = f"{base}/chat/completions"

    has_schema = _has_json_schema(body)
    # If this upstream is already known to reject response_format, translate up
    # front — one round trip, no wasted probe.
    known_reject = _rejects_response_format.get(base)
    send_body = _to_guided_json(body) if (has_schema and known_reject) else body

    async with httpx.AsyncClient(timeout=120) as client:
        upstream_start = time.perf_counter()
        resp = await client.post(url, json=send_body, headers=headers)
        upstream_seconds = time.perf_counter() - upstream_start
        # Fallback: retry with guided_json ONLY when the 400 says response_format is
        # unsupported (not a context-length / bad-schema 400). Remember the verdict so
        # subsequent requests skip the native attempt. upstream_seconds is re-timed on
        # the retry so it reflects the returned call, not the probe + retry sum (which
        # would understate gateway_overhead_seconds).
        if has_schema and not known_reject and _is_response_format_error(resp):
            _rejects_response_format[base] = True
            upstream_start = time.perf_counter()
            resp = await client.post(url, json=_to_guided_json(body), headers=headers)
            upstream_seconds = time.perf_counter() - upstream_start
        resp.raise_for_status()
        data = resp.json()
    usage = data.get("usage") or {}
    return (
        data,
        int(usage.get("prompt_tokens", 0)),
        int(usage.get("completion_tokens", 0)),
        upstream_seconds,
    )


async def handle(body: dict) -> tuple[dict, int, int, float]:
    """Route a chat-completions request to the configured backend.

    Returns ``(response, input_tokens, output_tokens, upstream_seconds)`` — the
    last is the time spent awaiting the backend, so the caller can separate the
    gateway's own overhead from model/upstream time.
    """
    backend = settings.inference_backend
    if backend == "anthropic":
        return await _anthropic_backend(body)
    if backend in ("openai", "vllm"):
        return await _forward_backend(body)
    raise RuntimeError(f"unknown INFERENCE_BACKEND: {backend!r}")
