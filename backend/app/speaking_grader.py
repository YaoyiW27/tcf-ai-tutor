"""AI grader for TCF Speaking ("Expression orale") responses.

The Speaking path records a spoken answer, transcribes it with Whisper (see
:mod:`app.transcription`), and grades the resulting *transcript* here. The
structure deliberately mirrors :mod:`app.grader`: three structured Claude calls
— score, find candidate errors, verify — orchestrated by
:mod:`app.speaking_graph`. Shared pieces (``Correction``, ``CEFRLevel``, the
structured-call helper, and the ``verify_errors`` judge) are reused straight
from :mod:`app.grader` rather than duplicated.

### What is (and isn't) graded

Grading works from a text transcript, so it assesses only what text can carry:
task fulfilment, coherence, lexical range, and grammar. **Pronunciation and
accent are explicitly out of scope** — a Whisper transcript discards the
acoustic signal, so any "pronunciation score" would be fabricated. This is
stated in the scoring prompt and reflected in the learner comment.

Spontaneous speech also differs from writing: hesitations, self-corrections,
false starts, and fillers ("euh", "ben", repetitions) are normal oral features,
not language errors. The error-finding prompt is tuned to ignore them.
"""

from pydantic import BaseModel, Field

from app import grader
from app.grader import CEFRLevel, Correction, DraftCorrections, verify_errors
from app.models import Question

# One Claude model for the whole pipeline; reuse the grader's choice so Writing
# and Speaking stay on the same model.
MODEL = grader.MODEL

# Official TCF Canada "Expression orale" bands per CEFR level. Same shape as
# grader.NCLC_ECRIT_BANDS: the CEFR -> NCLC level mapping is skill-agnostic, and
# both expression sections are marked out of 20 with the same level cut-offs, so
# the ranges mirror the écrite table. PURE DATA — never produced by the model,
# which only judges estimated_level. Maps level -> (nclc_level, oral_band).
# TODO: confirm the oral score ranges against the current official grid.
NCLC_ORAL_BANDS: dict[str, tuple[str, str]] = {
    "C2": ("NCLC 10+", "16–20"),
    "C1": ("NCLC 9", "14–15"),
    "B2": ("NCLC 7", "10–11"),
    "B1": ("NCLC 6", "7–9"),
    "A2": ("NCLC 5", "6"),
    "A1": ("NCLC 4", "below 6"),
}


def nclc_oral_band_for(level: str) -> tuple[str | None, str | None]:
    """Return ``(nclc_level, oral_band)`` for a CEFR level — pure lookup."""
    return NCLC_ORAL_BANDS.get(level, (None, None))


_EXAMINER = """You are an experienced TCF Canada (Test de connaissance du \
français) examiner grading the "Expression orale" (Speaking) section. You are \
given a written transcript of the candidate's spoken response."""

SCORE_SYSTEM = (
    _EXAMINER
    + """

Score the candidate's spoken response against the task it was given. Rate each \
of the four dimensions on a 0–6 band (0 = not addressed, 6 = excellent), using \
half-points where appropriate:

- task_fulfillment: Does the response do what the task asked (content, \
  register, and enough development for the task)? Penalise off-topic or \
  far-too-short answers.
- coherence: Organisation, logical flow, and connectors — appropriate to \
  spoken French, not written prose.
- lexis: Range, precision, and appropriateness of vocabulary.
- grammar: Accuracy of syntax, agreement, tense, and word forms.

This is a TRANSCRIPT of speech: treat hesitations, fillers ("euh", "ben"), \
repetitions, and self-corrections as normal features of spontaneous speech, \
NOT as errors, and do not penalise them. Do NOT attempt to judge pronunciation \
or accent — the transcript does not contain that information.

Then estimate the overall CEFR level (A1–C2) the response demonstrates and \
write a short overall comment (2–4 sentences, in French, addressed to the \
learner). If relevant, remind the learner that this assessment is based on a \
transcript and does not cover pronunciation.

Do NOT list corrections here — scoring only."""
)

FIND_ERRORS_SYSTEM = (
    _EXAMINER
    + """

Read the transcript and collect the most likely *candidate* language errors: \
grammar, agreement, tense, wrong word forms, or clearly wrong word choice. For \
each one return:

- original: the exact French excerpt from the transcript,
- correction: the corrected French version,
- explanation: ONE short sentence, in French, explaining the fix.

This is spontaneous speech: do NOT flag hesitations, fillers ("euh", "ben"), \
repetitions, false starts, self-corrections, or normal spoken register as \
errors. Only flag things that are plausibly actual language errors — no \
stylistic nitpicks (a later reviewer does the final filtering). If there are \
no real errors, return an empty list: do not invent or pad errors to reach a \
count. Return at most 6 candidates."""
)


class SpeakingScore(BaseModel):
    """Scoring-only output of the ``score`` step (no corrections)."""

    task_fulfillment: float = Field(description="Task fulfillment score, 0–6.")
    coherence: float = Field(description="Coherence/organisation score, 0–6.")
    lexis: float = Field(description="Lexical range/precision score, 0–6.")
    grammar: float = Field(description="Grammar/accuracy score, 0–6.")
    estimated_level: CEFRLevel
    overall_comment: str


class SpeakingGrade(BaseModel):
    """Final assembled grade for one spoken response (what the API returns).

    ``nclc_level`` / ``oral_band`` are derived from ``estimated_level`` via the
    pure-Python :data:`NCLC_ORAL_BANDS` lookup in the ``assemble`` node — not
    produced by the model.
    """

    task_fulfillment: float = Field(description="Task fulfillment score, 0–6.")
    coherence: float = Field(description="Coherence/organisation score, 0–6.")
    lexis: float = Field(description="Lexical range/precision score, 0–6.")
    grammar: float = Field(description="Grammar/accuracy score, 0–6.")
    estimated_level: CEFRLevel
    overall_comment: str
    corrections: list[Correction]
    nclc_level: str | None = None
    oral_band: str | None = None


def _build_task_message(question: Question, transcript: str) -> str:
    return (
        f"## Task (Tâche {question.task_number})\n"
        f"{question.prompt}\n\n"
        f"### Instructions\n{question.instructions}\n\n"
        f"## Transcript of the candidate's spoken response\n{transcript}"
    )


async def score_speaking(question: Question, transcript: str):
    """Score the four dimensions + CEFR level + comment. No corrections.

    Returns ``(SpeakingScore, token usage)`` — usage for Langfuse tracing.
    """
    return await grader._structured_call(
        SCORE_SYSTEM, _build_task_message(question, transcript), SpeakingScore
    )


async def find_errors(question: Question, transcript: str):
    """Over-collect candidate language errors from the transcript.

    Returns ``(list[Correction], token usage)``. Verification reuses
    :func:`app.grader.verify_errors` unchanged — the judge is skill-agnostic.
    """
    draft: DraftCorrections
    draft, usage = await grader._structured_call(
        FIND_ERRORS_SYSTEM, _build_task_message(question, transcript), DraftCorrections
    )
    return draft.corrections, usage


# Re-export the shared verify step so the graph imports both find and verify
# from one place, mirroring app.grader.
__all__ = [
    "SpeakingScore",
    "SpeakingGrade",
    "score_speaking",
    "find_errors",
    "verify_errors",
    "nclc_oral_band_for",
    "MODEL",
]
