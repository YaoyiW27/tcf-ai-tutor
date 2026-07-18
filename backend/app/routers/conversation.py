"""Conversational Speaking path: a multi-turn spoken interview with the examiner.

Turn-based over HTTP, with the persisted ``speaking_sessions`` row as the source
of truth for the dialogue:

- ``POST /speaking/sessions``            — start a session; examiner opens (text + audio)
- ``POST /speaking/sessions/{id}/turn``  — candidate audio → STT → examiner reply (text + audio)
- ``POST /speaking/sessions/{id}/finish``— grade the dialogue, return oral feedback
- ``GET  /speaking/sessions/{id}``       — read the transcript / status back

Examiner speech is synthesised per request and returned as base64 MP3 (small
clips, easy to play + curl-test); no audio is stored. On finish the candidate's
turns are graded by the existing speaking pipeline, which creates the same
``answers`` + ``ai_feedback`` rows as the monologue path — so the conversational
grade reads back through the same shape (`SpeakingFeedbackOut`).
"""

import base64
import uuid

import openai
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from langfuse import get_client
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app import examiner, speaking_grader, transcription, tts
from app.db import get_session
from app.models import (
    AIFeedback,
    Answer,
    AnswerStatus,
    ExamSection,
    Question,
    SpeakingSession,
    SpeakingSessionStatus,
)
from app.routers.answers import _get_or_create_dev_user
from app.routers.speaking import SpeakingFeedbackOut, _serialize
from app.speaking_graph import run_speaking_grader

router = APIRouter(tags=["speaking-conversation"])


class SessionStartIn(BaseModel):
    question_id: uuid.UUID


class ExaminerTurnOut(BaseModel):
    """An examiner utterance (opening or reply) with its synthesised audio."""

    session_id: uuid.UUID
    turn_index: int
    examiner_text: str
    audio_base64: str
    audio_mime: str
    ended: bool
    # Present on /turn: the transcript of the candidate's answer just processed.
    transcript: str | None = None


class SessionOut(BaseModel):
    """The stored dialogue, for review."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    question_id: uuid.UUID
    status: SpeakingSessionStatus
    turns: list[dict]
    answer_id: uuid.UUID | None


def _b64(audio: bytes) -> str:
    return base64.b64encode(audio).decode("ascii")


def _append(convo: SpeakingSession, role: str, text: str) -> None:
    """Append a turn, reassigning the list so SQLAlchemy flags the JSONB dirty."""
    turns = list(convo.turns)
    turns.append({"role": role, "text": text, "turn_index": len(turns)})
    convo.turns = turns


def _log_gen(name: str, model: str, usage=None) -> None:
    """Record an STT/TTS/LLM call as a Langfuse generation under the current span."""
    details = (
        {"input": usage.input_tokens, "output": usage.output_tokens}
        if usage is not None
        else None
    )
    get_client().start_observation(
        name=name, as_type="generation", model=model, usage_details=details
    ).end()


@router.post("/speaking/sessions", response_model=ExaminerTurnOut, status_code=201)
async def start_session(
    payload: SessionStartIn,
    session: AsyncSession = Depends(get_session),
) -> ExaminerTurnOut:
    question = await session.get(Question, payload.question_id)
    if question is None:
        raise HTTPException(status_code=404, detail="Question not found")
    if question.exam_section != ExamSection.speaking:
        raise HTTPException(status_code=400, detail="Question is not a speaking task")

    user = await _get_or_create_dev_user(session)

    langfuse = get_client()
    try:
        with langfuse.start_as_current_observation(
            name="speaking_session_start", as_type="span"
        ):
            langfuse.update_current_span(
                metadata={"user_id": str(user.id), "question_id": str(question.id)}
            )
            reply, usage = await examiner.opening(question)
            _log_gen("examiner_opening", examiner.MODEL, usage)
            audio = await tts.synthesize(reply)
            _log_gen("tts", tts.MODEL)
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Examiner not configured (no API key)")
    except openai.APIStatusError as exc:
        raise HTTPException(status_code=exc.status_code, detail=f"Examiner call failed: {exc}")
    except openai.APIError as exc:
        raise HTTPException(status_code=502, detail=f"Examiner call failed: {exc}")
    finally:
        langfuse.flush()

    convo = SpeakingSession(
        user_id=user.id,
        question_id=question.id,
        status=SpeakingSessionStatus.active,
        turns=[],
    )
    _append(convo, "examiner", reply)
    session.add(convo)
    await session.commit()
    await session.refresh(convo)

    return ExaminerTurnOut(
        session_id=convo.id,
        turn_index=0,
        examiner_text=reply,
        audio_base64=_b64(audio),
        audio_mime=tts.AUDIO_MIME,
        ended=False,
    )


@router.post(
    "/speaking/sessions/{session_id}/turn", response_model=ExaminerTurnOut
)
async def take_turn(
    session_id: uuid.UUID,
    audio: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
) -> ExaminerTurnOut:
    convo = await session.get(SpeakingSession, session_id)
    if convo is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if convo.status != SpeakingSessionStatus.active:
        raise HTTPException(status_code=409, detail="Session is already finished")

    question = await session.get(Question, convo.question_id)
    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Empty audio upload")

    langfuse = get_client()
    try:
        with langfuse.start_as_current_observation(
            name="speaking_turn", as_type="span"
        ):
            langfuse.update_current_span(
                metadata={
                    "session_id": str(session_id),
                    "user_id": str(convo.user_id),
                    "question_id": str(convo.question_id),
                }
            )
            with langfuse.start_as_current_observation(
                name="transcribe", as_type="generation", model=transcription.MODEL
            ):
                transcript = await transcription.transcribe(
                    audio_bytes, audio.filename or "audio.webm"
                )
            # Examiner reasons over the dialogue including this new answer.
            history = list(convo.turns) + [
                {"role": "candidate", "text": transcript, "turn_index": len(convo.turns)}
            ]
            reply, ended, usage = await examiner.next_turn(question, history)
            _log_gen("examiner_turn", examiner.MODEL, usage)
            audio_out = await tts.synthesize(reply)
            _log_gen("tts", tts.MODEL)
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Examiner not configured (no API key)")
    except openai.APIStatusError as exc:
        raise HTTPException(status_code=exc.status_code, detail=f"Examiner call failed: {exc}")
    except openai.APIError as exc:
        raise HTTPException(status_code=502, detail=f"Examiner call failed: {exc}")
    finally:
        langfuse.flush()

    _append(convo, "candidate", transcript)
    _append(convo, "examiner", reply)
    await session.commit()
    await session.refresh(convo)

    return ExaminerTurnOut(
        session_id=convo.id,
        turn_index=len(convo.turns) - 1,
        examiner_text=reply,
        audio_base64=_b64(audio_out),
        audio_mime=tts.AUDIO_MIME,
        ended=ended,
        transcript=transcript,
    )


@router.post(
    "/speaking/sessions/{session_id}/finish",
    response_model=SpeakingFeedbackOut,
    status_code=201,
)
async def finish_session(
    session_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> SpeakingFeedbackOut:
    convo = await session.get(SpeakingSession, session_id)
    if convo is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if convo.status == SpeakingSessionStatus.finished:
        raise HTTPException(
            status_code=409,
            detail="Session already finished; GET the session for its answer_id",
        )

    question = await session.get(Question, convo.question_id)
    candidate_text = "\n".join(
        t["text"] for t in convo.turns if t["role"] == "candidate"
    ).strip()
    if not candidate_text:
        raise HTTPException(
            status_code=400, detail="No candidate turns to grade yet"
        )

    # The dialogue converges onto the same answers/ai_feedback rows as monologue.
    answer = Answer(
        user_id=convo.user_id,
        question_id=convo.question_id,
        content=candidate_text,
        status=AnswerStatus.submitted,
    )
    session.add(answer)
    await session.flush()  # populate answer.id without committing yet

    try:
        grade = await run_speaking_grader(
            question,
            candidate_text,
            user_id=str(convo.user_id),
            question_id=str(convo.question_id),
        )
    except openai.APIStatusError as exc:
        raise HTTPException(status_code=exc.status_code, detail=f"Grader call failed: {exc}")
    except openai.APIError as exc:
        raise HTTPException(status_code=502, detail=f"Grader call failed: {exc}")

    dimension_scores, total_score = speaking_grader.feedback_fields(grade)
    feedback = AIFeedback(
        answer_id=answer.id,
        total_score=total_score,
        dimension_scores=dimension_scores,
        corrections=[c.model_dump() for c in grade.corrections],
        overall_comment=grade.overall_comment,
    )
    session.add(feedback)
    convo.status = SpeakingSessionStatus.finished
    convo.answer_id = answer.id
    await session.commit()
    await session.refresh(feedback)
    return _serialize(feedback)


@router.get("/speaking/sessions/{session_id}", response_model=SessionOut)
async def get_session_detail(
    session_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> SpeakingSession:
    convo = await session.get(SpeakingSession, session_id)
    if convo is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return convo
