"""Manual regression eval for the conversational examiner.

Run from backend/:

    .venv/bin/python -m scripts.eval_examiner

Text-only (no audio, no TTS, no DB): drives the examiner through an opening plus
a series of scripted candidate answers and checks the turn logic. Needs only
ANTHROPIC_API_KEY. Verifies (a) every examiner line is non-empty French, and
(b) the interview terminates by the MAX_CANDIDATE_TURNS cap.
"""

import asyncio

from app import examiner
from app.models import DifficultyLevel, ExamSection, Question


def make_question() -> Question:
    """A fake Tâche 1 (directed interview) speaking question — no DB."""
    return Question(
        exam_section=ExamSection.speaking,
        task_number=1,
        prompt=(
            "L'examinateur souhaite faire connaissance avec vous. Présentez-vous "
            "et parlez de votre vie quotidienne."
        ),
        instructions=(
            "Répondez à l'oral pendant environ 2 minutes. Parlez de vous, de "
            "votre travail ou de vos études, de vos loisirs et de vos projets."
        ),
        time_limit_seconds=120,
        word_count_min=0,
        word_count_max=0,
        difficulty_level=DifficultyLevel.A2,
        source="eval",
    )


# Scripted candidate answers — more than the cap, so the cap must kick in.
CANDIDATE_ANSWERS = [
    "Bonjour ! Je m'appelle Marie, j'ai trente ans et j'habite à Montréal.",
    "Je travaille comme infirmière dans un hôpital, c'est un métier fatigant mais que j'aime beaucoup.",
    "Le week-end, j'aime faire de la randonnée et lire des romans policiers.",
    "Plus tard, j'aimerais voyager au Japon et apprendre un peu de japonais.",
    "Oui, je pense que c'est important de continuer à apprendre tout au long de la vie.",
    "Merci beaucoup, c'était un plaisir de parler avec vous.",
]


async def main() -> None:
    question = make_question()
    problems: list[str] = []

    reply, _ = await examiner.opening(question)
    print(f"Examiner (opening): {reply}")
    if not reply.strip():
        problems.append("opening line was empty")

    history = [{"role": "examiner", "text": reply, "turn_index": 0}]
    ended = False
    candidate_turns = 0

    for answer in CANDIDATE_ANSWERS:
        if ended:
            break
        history.append(
            {"role": "candidate", "text": answer, "turn_index": len(history)}
        )
        candidate_turns += 1
        reply, ended, _ = await examiner.next_turn(question, history)
        history.append(
            {"role": "examiner", "text": reply, "turn_index": len(history)}
        )
        print(f"\nCandidate: {answer}")
        print(f"Examiner: {reply}{'  [ended]' if ended else ''}")
        if not reply.strip():
            problems.append(f"empty examiner reply at candidate turn {candidate_turns}")

    if not ended:
        problems.append(
            f"interview did not end after {candidate_turns} candidate turns"
        )
    if candidate_turns > examiner.MAX_CANDIDATE_TURNS:
        problems.append(
            f"ran {candidate_turns} candidate turns, over cap "
            f"{examiner.MAX_CANDIDATE_TURNS}"
        )

    print(
        f"\nSummary: {candidate_turns} candidate turn(s), "
        f"ended={ended} (cap {examiner.MAX_CANDIDATE_TURNS})"
    )
    if problems:
        print("FAIL:")
        for p in problems:
            print(f"  - {p}")
        raise SystemExit(1)
    print("PASS: examiner conducted and closed the interview within the cap")


if __name__ == "__main__":
    asyncio.run(main())
