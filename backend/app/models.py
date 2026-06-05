"""ORM models for schema v1 (see docs/schema-v1.md).

Covers a single end-to-end flow: a user submits a TCF Writing answer,
an AI agent grades it, and the user reads the feedback.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Enum as SAEnum,
    Float,
    ForeignKey,
    Integer,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class ExamSection(str, enum.Enum):
    writing = "writing"
    speaking = "speaking"
    listening = "listening"
    reading = "reading"


class DifficultyLevel(str, enum.Enum):
    A1 = "A1"
    A2 = "A2"
    B1 = "B1"
    B2 = "B2"
    C1 = "C1"
    C2 = "C2"


class AnswerStatus(str, enum.Enum):
    draft = "draft"
    submitted = "submitted"


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _uuid_pk()
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    answers: Mapped[list["Answer"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    exam_section: Mapped[ExamSection] = mapped_column(
        SAEnum(ExamSection, name="exam_section"), nullable=False
    )
    task_number: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    instructions: Mapped[str] = mapped_column(Text, nullable=False)
    time_limit_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    word_count_min: Mapped[int] = mapped_column(Integer, nullable=False)
    word_count_max: Mapped[int] = mapped_column(Integer, nullable=False)
    difficulty_level: Mapped[DifficultyLevel] = mapped_column(
        SAEnum(DifficultyLevel, name="difficulty_level"), nullable=False
    )
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    answers: Mapped[list["Answer"]] = relationship(back_populates="question")


class Answer(Base):
    __tablename__ = "answers"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("questions.id"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[AnswerStatus] = mapped_column(
        SAEnum(AnswerStatus, name="answer_status"),
        nullable=False,
        default=AnswerStatus.draft,
    )
    time_spent_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    submitted_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    user: Mapped["User"] = relationship(back_populates="answers")
    question: Mapped["Question"] = relationship(back_populates="answers")
    feedback: Mapped["AIFeedback | None"] = relationship(
        back_populates="answer", cascade="all, delete-orphan", uselist=False
    )


class AIFeedback(Base):
    __tablename__ = "ai_feedback"

    id: Mapped[uuid.UUID] = _uuid_pk()
    answer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("answers.id"),
        nullable=False,
        unique=True,  # one feedback per answer
    )
    total_score: Mapped[float] = mapped_column(Float, nullable=False)
    dimension_scores: Mapped[dict] = mapped_column(JSONB, nullable=False)
    corrections: Mapped[list] = mapped_column(JSONB, nullable=False)
    overall_comment: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    answer: Mapped["Answer"] = relationship(back_populates="feedback")
