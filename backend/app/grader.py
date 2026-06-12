"""AI grader for TCF Writing essays.

Grading is split into three independent Claude calls so that *finding*
candidate errors and *judging* whether they are real errors are separate
steps. This fixes the classic single-pass failure mode where the model
"corrects" French that was already correct (e.g. a politeness ``imparfait``)
in the same breath as scoring.

The steps (orchestrated by :mod:`app.graph`):

- :func:`score_essay`  — the four rubric dimensions + CEFR level + comment.
- :func:`find_errors`  — over-collect candidate language errors.
- :func:`verify_errors` — keep only the candidates that are genuine errors.

This module is pure scoring — no database access, no graph wiring. Each
call uses ``messages.parse(output_format=...)`` so we get a validated
Pydantic object back rather than free-form text. The router owns
persistence; :mod:`app.graph` owns the pipeline.
"""

from typing import Literal

from anthropic import AsyncAnthropic
from anthropic.types import Usage
from pydantic import BaseModel, Field

from app.config import settings
from app.models import Question

# CEFR scale, matching DifficultyLevel in app.models. Literal → JSON enum,
# which structured outputs enforces.
CEFRLevel = Literal["A1", "A2", "B1", "B2", "C1", "C2"]

# Official TCF Canada "Expression écrite" bands per CEFR level, from the NCLC
# table. This is PURE DATA, never produced by the model: the LLM only judges
# estimated_level, and the band is looked up from it in Python (see the
# `assemble` node in app.graph and `_serialize` in app.routers.feedback). This
# keeps us from ever emitting a fake precise score — we report the level plus
# its official écrite range. Maps level -> (nclc_level, ecrit_band).
NCLC_ECRIT_BANDS: dict[str, tuple[str, str]] = {
    "C2": ("NCLC 10+", "16–20"),
    "C1": ("NCLC 9", "14–15"),
    "B2": ("NCLC 7", "10–11"),
    "B1": ("NCLC 6", "7–9"),
    "A2": ("NCLC 5", "6"),
    "A1": ("NCLC 4", "below 6"),
}


def nclc_band_for(level: str) -> tuple[str | None, str | None]:
    """Return ``(nclc_level, ecrit_band)`` for a CEFR level — pure lookup.

    Falls back to ``(None, None)`` for an unknown level so callers can show
    just the level. No LLM involved.
    """
    return NCLC_ECRIT_BANDS.get(level, (None, None))

MODEL = "claude-sonnet-4-6"

_EXAMINER = """You are an experienced TCF Canada (Test de connaissance du \
français) examiner grading the "Expression écrite" (Writing) section."""

SCORE_SYSTEM = (
    _EXAMINER
    + """

Score the candidate's essay against the task it was given. Rate each of the \
four dimensions on a 0–6 band (0 = not addressed, 6 = excellent), using \
half-points where appropriate:

- task_fulfillment: Does the essay do what the task asked (content, format, \
  register, and the expected length)? Penalise off-topic or under-length work.
- coherence: Organisation, logical flow, paragraphing, and connectors.
- vocabulary: Range, precision, and appropriateness of word choice.
- grammar: Accuracy of syntax, agreement, tense, and spelling.

Then estimate the overall CEFR level (A1–C2) the essay demonstrates and write \
a short overall comment (2–4 sentences, in French, addressed to the learner).

Do NOT list corrections or rewrite the essay here — scoring only."""
)

FIND_ERRORS_SYSTEM = (
    _EXAMINER
    + """

Read the candidate's essay and collect the most likely *candidate* language \
errors: grammar, agreement, tense, spelling, or wrong word choice. For each \
one return:

- original: the exact French excerpt from the essay,
- correction: the corrected French version,
- explanation: ONE short sentence, in French, explaining the fix.

Only flag things that are plausibly actual errors — do NOT report stylistic \
nitpicks or matters of taste (a later reviewer does the final filtering). If \
the essay has no real errors, return an empty list: do not invent or pad \
errors to reach a count. Return at most 6 candidates."""
)

VERIFY_ERRORS_SYSTEM = (
    _EXAMINER
    + """

You are reviewing a list of *candidate* corrections that another examiner \
proposed for a French essay. For each candidate, decide whether it flags a \
genuine error, or whether the original French was actually correct or \
acceptable.

Set is_genuine_error = true ONLY if the original is truly wrong (grammar, \
agreement, tense, spelling, or a real misuse). Set it to false if the \
original is correct or acceptable French, including:

- a politeness or hypothetical imparfait / conditionnel (e.g. "je voulais", \
  "je voudrais"),
- valid register or stylistic variation,
- a "correction" that is merely a stylistic rewrite or a matter of taste.

Do NOT make pure stylistic rewrites. If you are unsure whether something is a \
real error, set is_genuine_error = false. Return one verdict per candidate, \
preserving its original / correction / explanation text."""
)


class Correction(BaseModel):
    """One concrete fix tied to an excerpt of the essay."""

    original: str = Field(description="The original French excerpt from the essay.")
    correction: str = Field(description="The corrected French version.")
    explanation: str = Field(description="Brief explanation of the fix, in French.")


class EssayScore(BaseModel):
    """Scoring-only output of the ``score`` step (no corrections)."""

    task_fulfillment: float = Field(description="Task fulfillment score, 0–6.")
    coherence: float = Field(description="Coherence/organisation score, 0–6.")
    vocabulary: float = Field(description="Vocabulary score, 0–6.")
    grammar: float = Field(description="Grammar/accuracy score, 0–6.")
    estimated_level: CEFRLevel
    overall_comment: str


class DraftCorrections(BaseModel):
    """Candidate errors produced by the ``find_errors`` step."""

    corrections: list[Correction]


class CorrectionVerdict(BaseModel):
    """One candidate correction plus the reviewer's verdict on it."""

    original: str
    correction: str
    explanation: str
    is_genuine_error: bool = Field(
        description="True only if the original is genuinely wrong, not "
        "acceptable or stylistic French."
    )


class VerificationResult(BaseModel):
    """The ``verify_errors`` step's per-candidate verdicts."""

    items: list[CorrectionVerdict]


class EssayGrade(BaseModel):
    """Final assembled grade for one essay (what the API returns).

    ``nclc_level`` / ``ecrit_band`` are derived from ``estimated_level`` via the
    pure-Python :data:`NCLC_ECRIT_BANDS` lookup in the ``assemble`` node — not
    produced by the model.
    """

    task_fulfillment: float = Field(description="Task fulfillment score, 0–6.")
    coherence: float = Field(description="Coherence/organisation score, 0–6.")
    vocabulary: float = Field(description="Vocabulary score, 0–6.")
    grammar: float = Field(description="Grammar/accuracy score, 0–6.")
    estimated_level: CEFRLevel
    overall_comment: str
    corrections: list[Correction]
    nclc_level: str | None = None
    ecrit_band: str | None = None


_client: AsyncAnthropic | None = None


def _get_client() -> AsyncAnthropic:
    """Lazily build the Anthropic client; raise if no key is configured."""
    global _client
    if settings.anthropic_api_key is None:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    if _client is None:
        _client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client


async def _structured_call(system: str, user: str, output_format: type[BaseModel]):
    """One structured Claude call.

    Returns ``(validated Pydantic object, token usage)`` so callers can report
    the call as a Langfuse generation (model + input/output tokens). Callers
    that don't need the usage can discard it.
    """
    response = await _get_client().messages.parse(
        model=MODEL,
        max_tokens=8000,
        thinking={"type": "adaptive"},
        system=system,
        messages=[{"role": "user", "content": user}],
        output_format=output_format,
    )
    return response.parsed_output, response.usage


def _build_task_message(question: Question, content: str) -> str:
    return (
        f"## Task (Tâche {question.task_number})\n"
        f"{question.prompt}\n\n"
        f"### Instructions\n{question.instructions}\n\n"
        f"### Expected length\n"
        f"{question.word_count_min}–{question.word_count_max} words\n\n"
        f"## Candidate's essay\n{content}"
    )


async def score_essay(question: Question, content: str) -> tuple[EssayScore, Usage]:
    """Score the four dimensions + CEFR level + comment. No corrections.

    Returns the score plus the Claude call's token usage (for tracing).
    """
    return await _structured_call(
        SCORE_SYSTEM, _build_task_message(question, content), EssayScore
    )


async def find_errors(
    question: Question, content: str
) -> tuple[list[Correction], Usage]:
    """Over-collect candidate language errors (recall over precision).

    Returns the candidates plus the Claude call's token usage (for tracing).
    """
    draft: DraftCorrections
    draft, usage = await _structured_call(
        FIND_ERRORS_SYSTEM, _build_task_message(question, content), DraftCorrections
    )
    return draft.corrections, usage


async def verify_errors(
    content: str, draft: list[Correction]
) -> list[Correction]:
    """Keep only candidates that are genuine errors; drop the rest."""
    if not draft:
        return []

    candidates = "\n".join(
        f"{i}. original: {c.original!r}\n"
        f"   correction: {c.correction!r}\n"
        f"   explanation: {c.explanation!r}"
        for i, c in enumerate(draft, start=1)
    )
    user = (
        f"## Candidate's essay\n{content}\n\n"
        f"## Candidate corrections to review\n{candidates}"
    )
    verdicts: VerificationResult
    verdicts, _usage = await _structured_call(
        VERIFY_ERRORS_SYSTEM, user, VerificationResult
    )
    return [
        Correction(
            original=v.original,
            correction=v.correction,
            explanation=v.explanation,
        )
        for v in verdicts.items
        if v.is_genuine_error
    ]
