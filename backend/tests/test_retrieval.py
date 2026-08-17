"""Scoring-reference retrieval + score-prompt injection (mocked; no DB/gateway).

Covers the RAG query (embed → cosine-nearest, section-filtered, top-k), the
prompt-block formatting, the additive graceful-degradation contract
(build_rubric_context never raises), and that both graders inject the context
into the score prompt only when present.
"""

from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from app import grader, retrieval, speaking_grader
from app.models import DifficultyLevel, ExamSection


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class _FakeSession:
    """Records the statement handed to execute and returns canned rows."""

    def __init__(self, rows):
        self._rows = rows
        self.stmt = None

    async def execute(self, stmt):
        self.stmt = stmt
        return _FakeResult(self._rows)


def _chunk(level: DifficultyLevel, text: str):
    return SimpleNamespace(cefr_level=level, text=text)


# ---- retrieve_rubrics ------------------------------------------------------


async def test_retrieve_rubrics_embeds_query_and_builds_nearest_neighbour_query(monkeypatch):
    captured = {}

    async def fake_embed(text):
        captured["query"] = text
        return [0.1, 0.2, 0.3]

    monkeypatch.setattr(retrieval, "embed_text", fake_embed)
    rows = [_chunk(DifficultyLevel.B1, "b1 band")]
    session = _FakeSession(rows)

    result = await retrieval.retrieve_rubrics(
        session, ExamSection.writing, "mon essai", k=2
    )

    assert result == rows
    assert captured["query"] == "mon essai"
    sql = str(session.stmt.compile(dialect=postgresql.dialect())).upper()
    assert "RUBRIC_CHUNKS" in sql
    assert "<=>" in sql  # pgvector cosine distance in ORDER BY
    assert "WHERE" in sql and "EXAM_SECTION" in sql
    assert "LIMIT" in sql


# ---- format_rubric_context -------------------------------------------------


def test_format_rubric_context_empty_is_none():
    assert retrieval.format_rubric_context([]) is None


def test_format_rubric_context_lists_each_band_with_level_tag():
    out = retrieval.format_rubric_context(
        [_chunk(DifficultyLevel.B1, "b1 text"), _chunk(DifficultyLevel.B2, "b2 text")]
    )
    assert "Reference CEFR bands" in out
    assert "- [B1] b1 text" in out
    assert "- [B2] b2 text" in out


# ---- build_rubric_context (graceful) ---------------------------------------


async def test_build_rubric_context_returns_formatted_on_success(monkeypatch):
    async def fake_retrieve(session, section, query, *, k=3):
        return [_chunk(DifficultyLevel.A2, "a2 text")]

    monkeypatch.setattr(retrieval, "retrieve_rubrics", fake_retrieve)
    out = await retrieval.build_rubric_context(object(), ExamSection.speaking, "q")
    assert "- [A2] a2 text" in out


async def test_build_rubric_context_none_when_empty(monkeypatch):
    async def fake_retrieve(session, section, query, *, k=3):
        return []

    monkeypatch.setattr(retrieval, "retrieve_rubrics", fake_retrieve)
    assert await retrieval.build_rubric_context(object(), ExamSection.writing, "q") is None


async def test_build_rubric_context_swallows_failure_returns_none(monkeypatch):
    async def boom(session, section, query, *, k=3):
        raise RuntimeError("embeddings gateway 503")

    monkeypatch.setattr(retrieval, "retrieve_rubrics", boom)
    # Additive contract: retrieval failure must never propagate to grading.
    assert await retrieval.build_rubric_context(object(), ExamSection.writing, "q") is None


# ---- prompt injection (writing + speaking) ---------------------------------

_QUESTION = SimpleNamespace(
    task_number=1,
    prompt="Décrivez votre journée.",
    instructions="60–120 mots.",
    word_count_min=60,
    word_count_max=120,
)


async def test_score_essay_appends_context_only_when_present(monkeypatch):
    seen = {}

    async def fake_call(system, user, output_format, **kwargs):
        seen["user"] = user
        return object(), grader.Usage(input_tokens=0, output_tokens=0)

    monkeypatch.setattr(grader, "_structured_call", fake_call)

    await grader.score_essay(_QUESTION, "mon texte")
    assert "Reference CEFR bands" not in seen["user"]
    assert "mon texte" in seen["user"]

    await grader.score_essay(
        _QUESTION, "mon texte", rubric_context="## Reference CEFR bands\n- [B1] x"
    )
    assert "Reference CEFR bands" in seen["user"]
    assert "mon texte" in seen["user"]


async def test_score_speaking_appends_context_only_when_present(monkeypatch):
    seen = {}

    async def fake_call(system, user, output_format, **kwargs):
        seen["user"] = user
        return object(), grader.Usage(input_tokens=0, output_tokens=0)

    # score_speaking calls grader._structured_call.
    monkeypatch.setattr(grader, "_structured_call", fake_call)

    await speaking_grader.score_speaking(_QUESTION, "ma réponse orale")
    assert "Reference CEFR bands" not in seen["user"]

    await speaking_grader.score_speaking(
        _QUESTION, "ma réponse orale", rubric_context="## Reference CEFR bands\n- [A2] y"
    )
    assert "Reference CEFR bands" in seen["user"]
    assert "ma réponse orale" in seen["user"]
