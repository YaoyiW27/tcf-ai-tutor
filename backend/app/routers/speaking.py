"""Speaking path: upload a spoken answer, grade it, read the feedback.

Mirrors the Writing flow (``answers`` + ``feedback`` routers) but for TCF
"Expression orale", with a speech-to-text step at upload:

- ``POST /speaking/answers``            — multipart audio upload → Whisper STT →
                                          store the transcript as an ``answers`` row
- ``POST /speaking/answers/{id}/grade`` — run the speaking LangGraph grader,
                                          persist to ``ai_feedback``
- ``GET  /speaking/answers/{id}/feedback`` — read that feedback back

### Reusing schema-v1 tables (no migration)

The transcript is stored in ``answers.content`` and the grade in
``ai_feedback`` exactly like Writing — the only structural difference lives in
the JSONB ``dimension_scores`` (oral rubric: ``lexis`` instead of
``vocabulary``, plus ``estimated_level``). ``nclc_level`` / ``oral_band`` are a
pure-Python lookup from ``estimated_level`` and are not stored. A speaking
answer is distinguished from a writing one purely by its question's
``exam_section``; the grade endpoint rejects a non-speaking question.
"""

import uuid
from datetime import datetime

import anthropic
import openai
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from langfuse import get_client
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import speaking_grader, speaking_graph, transcription
from app.db import get_session
from app.models import AIFeedback, Answer, AnswerStatus, ExamSection, Question
from app.routers.answers import _get_or_create_dev_user

router = APIRouter(tags=["speaking"])


class SpeakingAnswerOut(BaseModel):
    """Public shape of a stored speaking answer (with its transcript)."""

    id: uuid.UUID
    question_id: uuid.UUID
    transcript: str


class SpeakingFeedbackOut(BaseModel):
    """Public shape of an ai_feedback row for a speaking answer."""

    id: uuid.UUID
    answer_id: uuid.UUID
    total_score: float
    estimated_level: str
    nclc_level: str | None
    oral_band: str | None
    dimension_scores: dict[str, float]
    corrections: list[dict]
    overall_comment: str
    created_at: datetime


def _serialize(fb: AIFeedback) -> SpeakingFeedbackOut:
    """Build the API response, lifting estimated_level out of the JSON.

    nclc_level / oral_band aren't stored; they're a pure Python lookup from
    estimated_level, so GET feedback reports the same band as the grade.
    """
    scores = dict(fb.dimension_scores)
    estimated_level = scores.pop("estimated_level")
    nclc_level, oral_band = speaking_grader.nclc_oral_band_for(estimated_level)
    return SpeakingFeedbackOut(
        id=fb.id,
        answer_id=fb.answer_id,
        total_score=fb.total_score,
        estimated_level=estimated_level,
        nclc_level=nclc_level,
        oral_band=oral_band,
        dimension_scores=scores,
        corrections=fb.corrections,
        overall_comment=fb.overall_comment,
        created_at=fb.created_at,
    )


@router.post("/speaking/answers", response_model=SpeakingAnswerOut, status_code=201)
async def create_speaking_answer(
    question_id: uuid.UUID = Form(...),
    audio: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
) -> SpeakingAnswerOut:
    question = await session.get(Question, question_id)
    if question is None:
        raise HTTPException(status_code=404, detail="Question not found")
    if question.exam_section != ExamSection.speaking:
        raise HTTPException(
            status_code=400, detail="Question is not a speaking task"
        )

    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Empty audio upload")

    # Transcribe (Whisper). Recorded as its own Langfuse trace since upload and
    # grading are separate requests — this makes STT latency visible on its own.
    langfuse = get_client()
    try:
        with langfuse.start_as_current_observation(
            name="transcribe", as_type="generation", model=transcription.MODEL
        ):
            transcript = await transcription.transcribe(
                audio_bytes, audio.filename or "audio.webm"
            )
    except RuntimeError:
        raise HTTPException(
            status_code=503, detail="Speech-to-text not configured (no API key)"
        )
    except openai.APIError as exc:
        raise HTTPException(status_code=502, detail=f"Transcription failed: {exc}")
    finally:
        langfuse.flush()

    user = await _get_or_create_dev_user(session)
    answer = Answer(
        user_id=user.id,
        question_id=question_id,
        content=transcript,
        status=AnswerStatus.submitted,
    )
    session.add(answer)
    await session.commit()
    await session.refresh(answer)
    return SpeakingAnswerOut(
        id=answer.id, question_id=answer.question_id, transcript=answer.content
    )


@router.post(
    "/speaking/answers/{answer_id}/grade",
    response_model=SpeakingFeedbackOut,
    status_code=201,
)
async def grade_speaking_answer(
    answer_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> SpeakingFeedbackOut:
    answer = await session.get(Answer, answer_id)
    if answer is None:
        raise HTTPException(status_code=404, detail="Answer not found")

    existing = await session.scalar(
        select(AIFeedback).where(AIFeedback.answer_id == answer_id)
    )
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail="Answer already graded; GET /speaking/answers/{id}/feedback to read it",
        )

    question = await session.get(Question, answer.question_id)
    if question.exam_section != ExamSection.speaking:
        raise HTTPException(status_code=400, detail="Answer is not a speaking task")

    try:
        grade = await speaking_graph.run_speaking_grader(
            question,
            answer.content,
            user_id=str(answer.user_id),
            question_id=str(answer.question_id),
        )
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Grader not configured (no API key)")
    except anthropic.APIError as exc:
        raise HTTPException(status_code=502, detail=f"Grader call failed: {exc}")

    dimension_scores = {
        "task_fulfillment": grade.task_fulfillment,
        "coherence": grade.coherence,
        "lexis": grade.lexis,
        "grammar": grade.grammar,
        "estimated_level": grade.estimated_level,
    }
    total_score = round(
        (grade.task_fulfillment + grade.coherence + grade.lexis + grade.grammar) / 4,
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


@router.get(
    "/speaking/answers/{answer_id}/feedback", response_model=SpeakingFeedbackOut
)
async def get_speaking_feedback(
    answer_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> SpeakingFeedbackOut:
    feedback = await session.scalar(
        select(AIFeedback).where(AIFeedback.answer_id == answer_id)
    )
    if feedback is None:
        raise HTTPException(status_code=404, detail="No feedback for this answer")
    return _serialize(feedback)
