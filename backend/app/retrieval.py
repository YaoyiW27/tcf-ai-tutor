"""Scoring-reference retrieval for the RAG grading path.

At grade time the candidate's production (essay or transcript) is embedded and
the nearest CEFR band descriptors — filtered to the same ``exam_section`` — are
pulled from ``rubric_chunks`` (pgvector, cosine distance) and formatted into a
block that the score node injects into its prompt, so level placement is anchored
to reference bands.

RAG is **additive**: :func:`build_rubric_context` never raises. An empty table, a
missing embedding key, or any retrieval failure degrades to ``None`` (grade
without context) rather than breaking grading — the pre-RAG behaviour.
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.embeddings import embed_text
from app.models import ExamSection, RubricChunk

logger = logging.getLogger(__name__)

DEFAULT_K = 3


async def retrieve_rubrics(
    session: AsyncSession,
    exam_section: ExamSection,
    query_text: str,
    *,
    k: int = DEFAULT_K,
) -> list[RubricChunk]:
    """Return the ``k`` rubric chunks nearest ``query_text``, within ``exam_section``.

    Embeds the query through the gateway, then orders by pgvector cosine distance.
    Raises on embedding/DB failure — callers that must not break should use
    :func:`build_rubric_context`.
    """
    query_vec = await embed_text(query_text)
    stmt = (
        select(RubricChunk)
        .where(RubricChunk.exam_section == exam_section)
        .order_by(RubricChunk.embedding.cosine_distance(query_vec))
        .limit(k)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


def format_rubric_context(chunks: list[RubricChunk]) -> str | None:
    """Format retrieved chunks into a prompt block, or ``None`` if there are none."""
    if not chunks:
        return None
    lines = "\n".join(f"- [{chunk.cefr_level.value}] {chunk.text}" for chunk in chunks)
    return (
        "## Reference CEFR bands\n"
        "The descriptors below are the reference bands closest to this "
        "production. Use them to anchor your CEFR level estimate and dimension "
        "scores — they are guidance, not a substitute for judging the actual "
        "text.\n"
        f"{lines}"
    )


async def build_rubric_context(
    session: AsyncSession,
    exam_section: ExamSection,
    query_text: str,
    *,
    k: int = DEFAULT_K,
) -> str | None:
    """Retrieve + format reference bands, degrading to ``None`` on any failure.

    This is the single graceful-degradation point: because RAG is additive, no
    retrieval problem should ever surface as a grading error.
    """
    try:
        chunks = await retrieve_rubrics(session, exam_section, query_text, k=k)
    except Exception:  # noqa: BLE001 - retrieval must never break grading
        logger.warning(
            "rubric retrieval failed; grading without RAG context", exc_info=True
        )
        return None
    return format_rubric_context(chunks)
