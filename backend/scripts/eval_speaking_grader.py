"""Manual regression evals for the LangGraph speaking grader.

Run from backend/:

    .venv/bin/python -m scripts.eval_speaking_grader
    .venv/bin/python -m scripts.eval_speaking_grader --list
    .venv/bin/python -m scripts.eval_speaking_grader --case disfluencies_not_flagged

Like the writing eval, this is a small, human-readable script rather than a
full test suite. It feeds *transcripts* straight into the grader (no audio, no
Whisper), so it only needs ANTHROPIC_API_KEY — not OPENAI_API_KEY. The focus is
the oral-specific behaviour: spontaneous-speech disfluencies (fillers, false
starts, repetitions) must NOT be reported as language errors.
"""

import argparse
import asyncio
from dataclasses import dataclass
from time import perf_counter
from typing import Callable

from app.models import DifficultyLevel, ExamSection, Question
from app.speaking_grader import SpeakingGrade
from app.speaking_graph import run_speaking_grader


@dataclass
class EvalCase:
    name: str
    transcript: str
    check: Callable[[SpeakingGrade], tuple[bool, str]]


def make_question() -> Question:
    """Build a fake TCF speaking question without touching the database."""
    return Question(
        exam_section=ExamSection.speaking,
        task_number=3,
        prompt=(
            "« Les écrans occupent une place de plus en plus importante dans la "
            "vie des enfants. » Donnez votre opinion sur ce sujet et défendez "
            "votre point de vue."
        ),
        instructions=(
            "Exprimez-vous pendant environ 4 minutes 30. Présentez votre point "
            "de vue de façon structurée et développez vos arguments."
        ),
        time_limit_seconds=270,
        word_count_min=0,
        word_count_max=0,
        difficulty_level=DifficultyLevel.B2,
        source="eval",
    )


def correction_text(grade: SpeakingGrade) -> str:
    """Flatten corrections so simple string checks are easy to read."""
    return "\n".join(
        f"{c.original} -> {c.correction}: {c.explanation}"
        for c in grade.corrections
    ).lower()


def check_disfluencies_not_flagged(grade: SpeakingGrade) -> tuple[bool, str]:
    text = correction_text(grade)
    fillers = ["euh", "ben", "bah"]
    hit = next((f for f in fillers if f in text), None)
    if hit is not None:
        return False, f"flagged a spoken filler as an error: {hit!r}"
    return True, "did not flag spoken fillers / disfluencies"


def check_obvious_agreement_error(grade: SpeakingGrade) -> tuple[bool, str]:
    text = correction_text(grade)
    expected_markers = ["enfant", "intéressant"]
    if any(marker in text for marker in expected_markers):
        return True, "found expected correction for the agreement error"
    return False, "did not find correction mentioning enfant/intéressant"


def check_weak_short_answer(grade: SpeakingGrade) -> tuple[bool, str]:
    allowed_levels = {"A1", "A2", "B1"}
    if grade.estimated_level in allowed_levels:
        return True, "weak short answer was not over-scored"
    return False, f"weak short answer was over-scored as {grade.estimated_level}"


CASES = [
    # A fluent, grammatically-fine answer that is FULL of natural spoken
    # features: fillers ("euh", "ben"), a false start, and a repetition. None of
    # these should be reported as language errors.
    EvalCase(
        name="disfluencies_not_flagged",
        transcript=(
            "Euh... alors, moi je pense que, ben, les écrans c'est... c'est "
            "vraiment un sujet important aujourd'hui. Euh, d'un côté, les "
            "enfants ils apprennent beaucoup de choses avec les tablettes, "
            "mais... mais de l'autre côté, je pense qu'il faut, euh, limiter le "
            "temps devant l'écran. Voilà, c'est mon opinion."
        ),
        check=check_disfluencies_not_flagged,
    ),
    # A clear agreement error inside otherwise-normal speech: "les enfant" and
    # "très intéressants" (masc. plural where the noun is feminine singular).
    EvalCase(
        name="obvious_agreement_error",
        transcript=(
            "Je pense que les enfant passent trop de temps devant les écrans. "
            "La télévision est très intéressants mais ce n'est pas bon pour "
            "leur santé."
        ),
        check=check_obvious_agreement_error,
    ),
    # A very short, weak answer that barely addresses the task — must not be
    # over-scored to a high CEFR level.
    EvalCase(
        name="weak_short_answer",
        transcript="Euh... les écrans. C'est bien. Et aussi pas bien. Voilà.",
        check=check_weak_short_answer,
    ),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run manual regression evals for the speaking grader."
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available eval cases without calling the grader.",
    )
    parser.add_argument(
        "--case",
        choices=[case.name for case in CASES],
        help="Run one eval case instead of the full suite.",
    )
    return parser.parse_args()


async def run_case(case: EvalCase) -> tuple[bool, float]:
    print(f"\n=== {case.name} ===")

    question = make_question()
    started_at = perf_counter()
    grade = await run_speaking_grader(question, case.transcript)
    elapsed = perf_counter() - started_at

    passed, reason = case.check(grade)
    status = "PASS" if passed else "FAIL"

    print(f"{status}: {reason} ({elapsed:.1f}s)")
    print(f"estimated_level: {grade.estimated_level}")
    print(f"nclc_level: {grade.nclc_level}")
    print(f"oral_band: {grade.oral_band}")
    print(f"corrections: {len(grade.corrections)}")

    for correction in grade.corrections:
        print(f"  - {correction.original} -> {correction.correction}")
        print(f"    {correction.explanation}")

    return passed, elapsed


async def main() -> None:
    args = parse_args()

    if args.list:
        print("Available eval cases:")
        for case in CASES:
            print(f"  - {case.name}")
        return

    selected_cases = (
        [case for case in CASES if case.name == args.case]
        if args.case
        else CASES
    )

    results = []
    for case in selected_cases:
        results.append(await run_case(case))

    passed = sum(case_passed for case_passed, _ in results)
    total = len(results)
    total_seconds = sum(elapsed for _, elapsed in results)
    failed_names = [
        case.name
        for case, (case_passed, _) in zip(selected_cases, results)
        if not case_passed
    ]

    print(f"\nSummary: {passed}/{total} passed in {total_seconds:.1f}s")
    if failed_names:
        print(f"Failed: {', '.join(failed_names)}")

    if passed != total:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
