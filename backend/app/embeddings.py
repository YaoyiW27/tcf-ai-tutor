"""Embedding helper for the scoring-reference RAG path.

All embedding calls go through the inference gateway's ``/v1/embeddings``
passthrough (``settings.gateway_url``), the same chokepoint the graders use for
chat — so embeddings are metered/observable (cost, latency, tokens) like every
other model call, and the backend never holds a provider key. The gateway always
routes embeddings to OpenAI (Anthropic has no embeddings API), independent of the
chat backend.

Used by ``scripts.seed_rubrics`` (embed the reference corpus at seed time) and,
in the retrieval slice, by the score node (embed the essay/transcript as a query).
"""

from openai import AsyncOpenAI

from app.config import settings

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    """Lazily build the OpenAI-compatible client pointed at the gateway.

    Mirrors ``app.grader._get_client``: the gateway holds the real provider key,
    so this client only needs a non-empty placeholder ``api_key``. A separate
    instance from the grader's keeps the two call sites independent.
    """
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            base_url=f"{settings.gateway_url.rstrip('/')}/v1",
            api_key="sk-gateway",
        )
    return _client


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts, returning one vector per input (order preserved).

    Empty input short-circuits (no gateway call). The response is sorted by the
    per-item ``index`` before extracting vectors, so ordering never depends on the
    upstream returning items in request order.
    """
    if not texts:
        return []
    response = await _get_client().embeddings.create(
        model=settings.embedding_model,
        input=texts,
    )
    items = sorted(response.data, key=lambda item: item.index)
    return [item.embedding for item in items]


async def embed_text(text: str) -> list[float]:
    """Embed a single text — convenience wrapper over :func:`embed_texts`."""
    [vector] = await embed_texts([text])
    return vector
