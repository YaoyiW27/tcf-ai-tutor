"""The RAG embedding helper — batching, ordering, and the empty case (mocked).

No real gateway/OpenAI call: the OpenAI-compatible client is replaced with a stub
that records the request and returns a shuffled response, so we prove ordering is
restored by ``index`` rather than trusting upstream order.
"""

from types import SimpleNamespace

import pytest

from app import embeddings


class _StubEmbeddings:
    def __init__(self, recorder: dict, data):
        self._recorder = recorder
        self._data = data

    async def create(self, *, model, input):
        self._recorder["model"] = model
        self._recorder["input"] = input
        return SimpleNamespace(data=self._data)


def _install_stub(monkeypatch, data, recorder: dict | None = None):
    recorder = {} if recorder is None else recorder
    client = SimpleNamespace(embeddings=_StubEmbeddings(recorder, data))
    monkeypatch.setattr(embeddings, "_get_client", lambda: client)
    return recorder


async def test_embed_texts_empty_short_circuits_without_calling_gateway(monkeypatch):
    # If the client is touched at all, this raises — proving no call was made.
    def _boom():
        raise AssertionError("gateway must not be called for empty input")

    monkeypatch.setattr(embeddings, "_get_client", _boom)
    assert await embeddings.embed_texts([]) == []


async def test_embed_texts_returns_vectors_in_input_order(monkeypatch):
    # Upstream returns items out of order; helper must sort by index.
    data = [
        SimpleNamespace(index=1, embedding=[0.2]),
        SimpleNamespace(index=0, embedding=[0.1]),
    ]
    recorder = _install_stub(monkeypatch, data)

    vectors = await embeddings.embed_texts(["first", "second"])

    assert vectors == [[0.1], [0.2]]
    assert recorder["input"] == ["first", "second"]
    assert recorder["model"] == embeddings.settings.embedding_model


async def test_embed_text_returns_single_vector(monkeypatch):
    _install_stub(monkeypatch, [SimpleNamespace(index=0, embedding=[0.9, 0.8])])
    assert await embeddings.embed_text("bonjour") == [0.9, 0.8]


async def test_embed_text_raises_if_upstream_returns_wrong_count(monkeypatch):
    # Defensive: a single-text embed expects exactly one vector back.
    _install_stub(
        monkeypatch,
        [SimpleNamespace(index=0, embedding=[0.1]), SimpleNamespace(index=1, embedding=[0.2])],
    )
    with pytest.raises(ValueError):
        await embeddings.embed_text("x")
