"""AI grader for TCF Writing essays.

A single Claude call takes the question (prompt + instructions + the
expected word-count band) and the candidate's essay, and returns a
structured rubric: four dimension scores on a 0–6 band, an estimated
CEFR level, a written comment, and concrete corrections.

This module is pure scoring — no database access. The router owns
persistence into the ``ai_feedback`` table. Structured output is enforced
with ``messages.parse(output_format=...)`` so we get a validated
``EssayGrade`` back rather than free-form text we'd have to parse.
"""

from typing import Literal

from anthropic import AsyncAnthropic
from pydantic import BaseModel, Field

from app.config import settings
from app.models import Question

# CEFR scale, matching DifficultyLevel in app.models. Literal → JSON enum,
# which structured outputs enforces.
CEFRLevel = Literal["A1", "A2", "B1", "B2", "C1", "C2"]

MODEL = "claude-sonnet-4-6"

GRADER_SYSTEM = """You are an experienced TCF Canada (Test de connaissance du \
français) examiner grading the "Expression écrite" (Writing) section.

Grade the candidate's essay against the task it was given. Score each of \
the four dimensions on a 0–6 band (0 = not addressed, 6 = excellent), using \
half-points where appropriate:

- task_fulfillment: Does the essay do what the task asked (content, format, \
  register, and the expected length)? Penalise off-topic or under-length work.
- coherence: Organisation, logical flow, paragraphing, and connectors.
- vocabulary: Range, precision, and appropriateness of word choice.
- grammar: Accuracy of syntax, agreement, tense, and spelling.

Then estimate the overall CEFR level (A1–C2) the essay demonstrates, write a \
short overall comment (2–4 sentences, in French, addressed to the learner), \
and list the most important concrete corrections. For each correction quote \
the original French excerpt, give the corrected version, and explain the fix \
briefly in French. Return at most 8 corrections, prioritising the ones that \
matter most. If the essay is strong, it is fine to return few or no \
corrections."""


class Correction(BaseModel):
    """One concrete fix tied to an excerpt of the essay."""

    original: str = Field(description="The original French excerpt from the essay.")
    correction: str = Field(description="The corrected French version.")
    explanation: str = Field(description="Brief explanation of the fix, in French.")


class EssayGrade(BaseModel):
    """Structured grade returned by Claude (one essay)."""

    task_fulfillment: float = Field(description="Task fulfillment score, 0–6.")
    coherence: float = Field(description="Coherence/organisation score, 0–6.")
    vocabulary: float = Field(description="Vocabulary score, 0–6.")
    grammar: float = Field(description="Grammar/accuracy score, 0–6.")
    estimated_level: CEFRLevel
    overall_comment: str
    corrections: list[Correction]


_client: AsyncAnthropic | None = None


def _get_client() -> AsyncAnthropic:
    """Lazily build the Anthropic client; raise if no key is configured."""
    global _client
    if settings.anthropic_api_key is None:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    if _client is None:
        _client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client


def _build_user_message(question: Question, content: str) -> str:
    return (
        f"## Task (Tâche {question.task_number})\n"
        f"{question.prompt}\n\n"
        f"### Instructions\n{question.instructions}\n\n"
        f"### Expected length\n"
        f"{question.word_count_min}–{question.word_count_max} words\n\n"
        f"## Candidate's essay\n{content}"
    )


async def grade_essay(question: Question, content: str) -> EssayGrade:
    """Call Claude once and return a validated :class:`EssayGrade`."""
    response = await _get_client().messages.parse(
        model=MODEL,
        max_tokens=8000,
        thinking={"type": "adaptive"},
        system=GRADER_SYSTEM,
        messages=[{"role": "user", "content": _build_user_message(question, content)}],
        output_format=EssayGrade,
    )
    return response.parsed_output
