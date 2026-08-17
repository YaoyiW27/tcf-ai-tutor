"""Seed the ``rubric_chunks`` table with the CEFR/TCF scoring-reference corpus.

Embeds each descriptor (``app.rubric_corpus.RUBRICS``) through the inference
gateway's ``/v1/embeddings`` passthrough and stores it as a pgvector row, so the
score node can retrieve the nearest bands at grade time.

Idempotent: each chunk is keyed on ``(exam_section, dimension, cefr_level,
source)`` and skipped if already present, so the script is safe to re-run. It is
**not** run from the backend entrypoint (unlike ``seed_questions``) because it
needs the gateway up with an OpenAI key; run it manually once the stack is up:

    .venv/bin/python -m scripts.seed_rubrics

Note: idempotency is by key, not content — editing a descriptor's text will not
re-embed the existing row. Re-seed a changed corpus by clearing the affected rows
first (a content-hash column would remove that caveat; deferred).
"""

import asyncio

from sqlalchemy import select

from app.db import async_session_factory
from app.embeddings import embed_texts
from app.models import RubricChunk
from app.rubric_corpus import RUBRICS, rubric_key


def filter_new(records: list[dict], existing_keys: set[tuple]) -> list[dict]:
    """Return the corpus records whose idempotency key is not already present.

    Pure function (no I/O) so the skip-existing decision is unit-testable.
    """
    return [r for r in records if rubric_key(r) not in existing_keys]


async def _existing_keys(session) -> set[tuple]:
    """The idempotency keys already in ``rubric_chunks``."""
    result = await session.execute(
        select(
            RubricChunk.exam_section,
            RubricChunk.dimension,
            RubricChunk.cefr_level,
            RubricChunk.source,
        )
    )
    return {
        rubric_key(
            {
                "exam_section": exam_section,
                "dimension": dimension,
                "cefr_level": cefr_level,
                "source": source,
            }
        )
        for exam_section, dimension, cefr_level, source in result.all()
    }


async def main() -> None:
    async with async_session_factory() as session:
        existing = await _existing_keys(session)
        new = filter_new(RUBRICS, existing)
        if not new:
            print(f"rubric_chunks already seeded ({len(existing)} present); nothing to do.")
            return

        vectors = await embed_texts([record["text"] for record in new])
        for record, vector in zip(new, vectors, strict=True):
            session.add(
                RubricChunk(
                    exam_section=record["exam_section"],
                    cefr_level=record["cefr_level"],
                    dimension=record["dimension"],
                    text=record["text"],
                    source=record["source"],
                    embedding=vector,
                )
            )
        await session.commit()
        print(f"seeded {len(new)} rubric chunks ({len(existing)} already present).")


if __name__ == "__main__":
    asyncio.run(main())
