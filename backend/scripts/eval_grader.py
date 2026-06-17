"""Manual regression evals for the LangGraph writing grader.

Run from backend/:

    .venv/bin/python -m scripts.eval_grader

This is intentionally a small, human-readable eval script, not a full test
suite. It calls the real grader, so it requires ANTHROPIC_API_KEY in .env.
"""

import asyncio
from dataclasses import dataclass
from typing import Callable

from app.graph import run_grader
from app.grader import EssayGrade
from app.models import DifficultyLevel, ExamSection, Question


@dataclass
class EvalCase:
    name: str
    content: str
    check: Callable[[EssayGrade], tuple[bool, str]]


def make_question() -> Question:
    """Build a fake TCF writing question without touching the database."""
    return Question(
        exam_section=ExamSection.writing,
        task_number=1,
        prompt=(
            "Vous écrivez un message formel pour demander de déplacer un "
            "rendez-vous."
        ),
        instructions=(
            "Rédigez un message clair et poli. Expliquez la situation et "
            "proposez une nouvelle date."
        ),
        time_limit_seconds=900,
        word_count_min=60,
        word_count_max=120,
        difficulty_level=DifficultyLevel.A2,
        source="eval",
    )


def correction_text(grade: EssayGrade) -> str:
    """Flatten corrections so simple string checks are easy to read."""
    return "\n".join(
        f"{c.original} -> {c.correction}: {c.explanation}"
        for c in grade.corrections
    ).lower()


def check_polite_imparfait(grade: EssayGrade) -> tuple[bool, str]:
    text = correction_text(grade)
    if "voulais" in text:
        return False, "flagged polite imparfait: 'je voulais'"
    return True, "did not flag polite imparfait"


def check_obvious_plural_error(grade: EssayGrade) -> tuple[bool, str]:
    text = correction_text(grade)
    expected_markers = ["pomme", "gentils"]

    if any(marker in text for marker in expected_markers):
        return True, "found expected correction for plural/agreement error"

    return False, "did not find correction mentioning pomme or gentils"


def check_weak_short_answer(grade: EssayGrade) -> tuple[bool, str]:
    allowed_levels = {"A1", "A2", "B1"}

    if grade.estimated_level in allowed_levels:
        return True, "weak short answer was not over-scored"

    return False, f"weak short answer was over-scored as {grade.estimated_level}"


CASES = [
    EvalCase(
        name="polite_imparfait",
        content=(
            "Bonjour Madame,\n\n"
            "Je voulais vous demander de déplacer notre rendez-vous à vendredi. "
            "Je vous remercie pour votre compréhension.\n\n"
            "Cordialement,"
        ),
        check=check_polite_imparfait,
    ),
    EvalCase(
        name="obvious_plural_error",
        content=(
            "Bonjour,\n\n"
            "Hier, je suis allé au marché et j'ai acheté des pomme pour ma "
            "famille. Le vendeur était très gentils.\n\n"
            "Merci."
        ),
        check=check_obvious_plural_error,
    ),
    EvalCase(
        name="weak_short_answer",
        content="Bonjour. Je veux travail. Merci.",
        check=check_weak_short_answer,
    ),
]


async def run_case(case: EvalCase) -> bool:
    print(f"\n=== {case.name} ===")

    question = make_question()
    grade = await run_grader(question, case.content)

    passed, reason = case.check(grade)
    status = "PASS" if passed else "FAIL"

    print(f"{status}: {reason}")
    print(f"estimated_level: {grade.estimated_level}")
    print(f"nclc_level: {grade.nclc_level}")
    print(f"ecrit_band: {grade.ecrit_band}")
    print(f"corrections: {len(grade.corrections)}")

    for correction in grade.corrections:
        print(f"  - {correction.original} -> {correction.correction}")
        print(f"    {correction.explanation}")

    return passed


async def main() -> None:
    results = []
    for case in CASES:
        results.append(await run_case(case))

    passed = sum(results)
    total = len(results)

    print(f"\nSummary: {passed}/{total} passed")

    if passed != total:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
