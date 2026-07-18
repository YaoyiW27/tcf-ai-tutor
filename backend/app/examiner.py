"""The conversational TCF examiner for the Speaking dialogue agent.

Pure turn logic (no DB, no HTTP), mirroring :mod:`app.grader`: each examiner
utterance is one structured Claude call via :func:`app.grader._structured_call`.
The router owns the session/persistence and the STT/TTS around these calls.

The examiner conducts an "Expression orale" interview one turn at a time:

- :func:`opening`   — greet the candidate and ask the first question for the task.
- :func:`next_turn` — react to the candidate's latest answer and ask one natural
  follow-up, or wrap the interview up.

A hard :data:`MAX_CANDIDATE_TURNS` cap forces the interview to end even if the
model would keep going, so a session always terminates.
"""

from pydantic import BaseModel, Field

from app import grader
from app.models import Question

MODEL = grader.MODEL

# Stop after this many candidate answers, regardless of what the model wants —
# a TCF oral task is short, and this guarantees termination.
MAX_CANDIDATE_TURNS = 5

# Short replies; low reasoning effort so each turn stays snappy.
_MAX_TOKENS = 1536
_REASONING_EFFORT = "low"

_PERSONA = """You are a warm, professional TCF Canada (Test de connaissance du \
français) examiner conducting the "Expression orale" (Speaking) section. You \
speak French, in a natural spoken register, and you keep your turns short \
(1–2 sentences)."""

OPENING_SYSTEM = (
    _PERSONA
    + """

Start the interview for the given task: greet the candidate briefly and ask \
your first question to get them talking. Return only your spoken line, in \
French, in `reply`."""
)

FOLLOWUP_SYSTEM = (
    _PERSONA
    + """

You are mid-interview. Given the dialogue so far, respond as the examiner: \
briefly acknowledge the candidate's last answer, then ask ONE natural \
follow-up question that digs deeper or moves to a related aspect of the task. \
Stay on the task and adapt to what they said. Return your spoken line, in \
French, in `reply`, and set should_end=false — unless the conversation has \
clearly run its natural course, in which case give a short closing remark and \
set should_end=true."""
)

# Appended for the forced final exchange (turn cap reached).
_CLOSING_HINT = """

This is the FINAL exchange. Do NOT ask another question. Give a brief, warm \
closing remark in French to end the interview, and set should_end=true."""


class ExaminerLine(BaseModel):
    """The examiner's opening utterance."""

    reply: str = Field(description="The examiner's spoken line, in French.")


class ExaminerTurn(BaseModel):
    """The examiner's follow-up utterance plus whether to end the interview."""

    reply: str = Field(description="The examiner's spoken line, in French.")
    should_end: bool = Field(
        description="True if the interview should end after this line."
    )


def _task_block(question: Question) -> str:
    return (
        f"## Task (Tâche {question.task_number})\n"
        f"{question.prompt}\n\n"
        f"### Instructions\n{question.instructions}"
    )


def _format_dialogue(question: Question, history: list[dict]) -> str:
    lines = [_task_block(question), "", "## Dialogue so far"]
    for turn in history:
        speaker = "Examiner" if turn["role"] == "examiner" else "Candidate"
        lines.append(f"{speaker}: {turn['text']}")
    return "\n".join(lines)


async def opening(question: Question):
    """Produce the examiner's first line for the task.

    Returns ``(reply_text, token usage)`` — usage for Langfuse tracing.
    """
    line: ExaminerLine
    line, usage = await grader._structured_call(
        OPENING_SYSTEM,
        _task_block(question),
        ExaminerLine,
        max_tokens=_MAX_TOKENS,
        reasoning_effort=_REASONING_EFFORT,
    )
    return line.reply, usage


async def next_turn(question: Question, history: list[dict]):
    """Produce the examiner's next line given the dialogue so far.

    ``history`` is the ordered list of ``{role, text, ...}`` turns (including
    the candidate's just-added answer). Returns ``(reply_text, ended, usage)``.
    The turn cap forces ``ended`` once the candidate has answered
    :data:`MAX_CANDIDATE_TURNS` times.
    """
    candidate_turns = sum(1 for t in history if t["role"] == "candidate")
    must_end = candidate_turns >= MAX_CANDIDATE_TURNS
    system = FOLLOWUP_SYSTEM + (_CLOSING_HINT if must_end else "")

    turn: ExaminerTurn
    turn, usage = await grader._structured_call(
        system,
        _format_dialogue(question, history),
        ExaminerTurn,
        max_tokens=_MAX_TOKENS,
        reasoning_effort=_REASONING_EFFORT,
    )
    return turn.reply, (turn.should_end or must_end), usage
