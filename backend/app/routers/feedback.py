"""Grading path: ``POST /answers/{id}/grade`` and ``GET /answers/{id}/feedback``.

``grade`` runs the AI grader (one Claude call) over a stored essay and
persists the result into ``ai_feedback`` (one row per answer — ``answer_id``
is unique). ``feedback`` reads that row back.

### Mapping the grader output onto schema-v1's ``ai_feedback``

The grader returns four dimension scores, an estimated CEFR level, a
comment, and corrections. schema-v1's ``ai_feedback`` has fixed columns
(no ``estimated_level`` column — adding one would be a schema-v2 change),
so we map as follows:

- ``total_score``      — mean of the four dimensions, rounded to 1 dp
- ``dimension_scores`` — JSON: the four scores **plus** ``estimated_level``
- ``corrections``      — JSON list of {original, correction, explanation}
- ``overall_comment``  — the comment text

On the way out we lift ``estimated_level`` back out of the JSON so the API
response exposes it as a first-class field.
"""

import uuid
from datetime import datetime

import anthropic
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import graph
from app.db import get_session
from app.models import AIFeedback, Answer, Question

router = APIRouter(tags=["feedback"])


class FeedbackOut(BaseModel):
    """Public shape of an ai_feedback row."""

    id: uuid.UUID
    answer_id: uuid.UUID
    total_score: float
    estimated_level: str
    dimension_scores: dict[str, float]
    corrections: list[dict]
    overall_comment: str
    created_at: datetime


def _serialize(fb: AIFeedback) -> FeedbackOut:
    """Build the API response, lifting estimated_level out of the JSON."""
    scores = dict(fb.dimension_scores)
    estimated_level = scores.pop("estimated_level")
    return FeedbackOut(
        id=fb.id,
        answer_id=fb.answer_id,
        total_score=fb.total_score,
        estimated_level=estimated_level,
        dimension_scores=scores,
        corrections=fb.corrections,
        overall_comment=fb.overall_comment,
        created_at=fb.created_at,
    )


@router.post("/answers/{answer_id}/grade", response_model=FeedbackOut, status_code=201)
async def grade_answer(
    answer_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> FeedbackOut:
    answer = await session.get(Answer, answer_id)
    if answer is None:
        raise HTTPException(status_code=404, detail="Answer not found")

    existing = await session.scalar(
        select(AIFeedback).where(AIFeedback.answer_id == answer_id)
    )
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail="Answer already graded; GET /answers/{id}/feedback to read it",
        )

    # Load the question explicitly (the relationship is lazy under async).
    question = await session.get(Question, answer.question_id)

    try:
        grade = await graph.run_grader(question, answer.content)
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Grader not configured (no API key)")
    except anthropic.APIError as exc:
        raise HTTPException(status_code=502, detail=f"Grader call failed: {exc}")

    dimension_scores = {
        "task_fulfillment": grade.task_fulfillment,
        "coherence": grade.coherence,
        "vocabulary": grade.vocabulary,
        "grammar": grade.grammar,
        "estimated_level": grade.estimated_level,
    }
    total_score = round(
        (grade.task_fulfillment + grade.coherence + grade.vocabulary + grade.grammar) / 4,
        1,
    )

    feedback = AIFeedback(
        answer_id=answer_id,
        total_score=total_score,
        dimension_scores=dimension_scores,
        corrections=[c.model_dump() for c in grade.corrections],
        overall_comment=grade.overall_comment,
    )
    session.add(feedback)
    await session.commit()
    await session.refresh(feedback)
    return _serialize(feedback)


@router.get("/answers/{answer_id}/feedback", response_model=FeedbackOut)
async def get_feedback(
    answer_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> FeedbackOut:
    feedback = await session.scalar(
        select(AIFeedback).where(AIFeedback.answer_id == answer_id)
    )
    if feedback is None:
        raise HTTPException(status_code=404, detail="No feedback for this answer")
    return _serialize(feedback)
