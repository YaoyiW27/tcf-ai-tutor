"""Write path: ``POST /answers`` stores a TCF Writing essay.

This is the minimal "save an essay" step — no auth, no grading, no
``ai_feedback``. It accepts a ``question_id`` and the essay ``content``,
inserts one row into the ``answers`` table, and returns it.

### How ``user_id`` is handled (no auth yet)

``answers.user_id`` is a NOT NULL FK to ``users.id``, but there is no
authentication in place. Of the two options — (a) seed a fixed dev user
server-side, or (b) take ``user_id`` in the request body — we use (a).

It's simpler for the caller (the request stays just ``question_id`` +
``content``; the frontend can't invent a valid user UUID anyway) and it
keeps a single, stable owner for every essay during development. When
Google OAuth lands, the dev user is replaced by the authenticated user
and this helper goes away. See docs/schema-v1.md.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import Answer, AnswerStatus, Question, User

router = APIRouter(tags=["answers"])

# Fixed identity used for every essay until real auth exists.
DEV_USER_EMAIL = "dev@tcf-ai-tutor.local"
DEV_USER_NAME = "Dev User"


class AnswerIn(BaseModel):
    """Request body for submitting an essay."""

    question_id: uuid.UUID
    content: str


class AnswerOut(BaseModel):
    """Public shape of an answer row returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    question_id: uuid.UUID
    content: str
    status: AnswerStatus


async def _get_or_create_dev_user(session: AsyncSession) -> User:
    """Return the fixed dev user, creating it on first use."""
    user = await session.scalar(
        select(User).where(User.email == DEV_USER_EMAIL)
    )
    if user is None:
        user = User(email=DEV_USER_EMAIL, name=DEV_USER_NAME)
        session.add(user)
        await session.flush()  # populate user.id without committing yet
    return user


@router.post("/answers", response_model=AnswerOut, status_code=201)
async def create_answer(
    payload: AnswerIn,
    session: AsyncSession = Depends(get_session),
) -> Answer:
    question = await session.get(Question, payload.question_id)
    if question is None:
        raise HTTPException(status_code=404, detail="Question not found")

    user = await _get_or_create_dev_user(session)

    answer = Answer(
        user_id=user.id,
        question_id=payload.question_id,
        content=payload.content,
        status=AnswerStatus.submitted,
    )
    session.add(answer)
    await session.commit()
    await session.refresh(answer)
    return answer
