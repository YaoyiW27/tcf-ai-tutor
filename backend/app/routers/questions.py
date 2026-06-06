"""Read-only ``GET /questions`` endpoint.

Exists to verify the DB → ORM → API path end to end. No pagination,
auth, or write routes by design — those come later.
"""

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import DifficultyLevel, ExamSection, Question

router = APIRouter(tags=["questions"])


class QuestionOut(BaseModel):
    """Public shape of a question row returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    exam_section: ExamSection
    task_number: int
    prompt: str
    instructions: str
    time_limit_seconds: int
    word_count_min: int
    word_count_max: int
    difficulty_level: DifficultyLevel
    source: str | None


@router.get("/questions", response_model=list[QuestionOut])
async def list_questions(
    session: AsyncSession = Depends(get_session),
) -> list[Question]:
    result = await session.scalars(
        select(Question).order_by(Question.exam_section, Question.task_number)
    )
    return list(result.all())
