"""Seed the ``questions`` table with a few sample TCF Writing prompts.

Verifies the full path from DB schema to ORM models with real rows.
Idempotent: each question is keyed by ``(exam_section, task_number,
source)`` and skipped if a matching row already exists, so the script
is safe to run repeatedly.

Run from the ``backend/`` directory:

    .venv/bin/python -m scripts.seed_questions
"""

import asyncio

from sqlalchemy import select

from app.db import async_session_factory
from app.models import DifficultyLevel, ExamSection, Question

# Three sample TCF Canada "Expression écrite" tasks (Tâches 1–3).
SAMPLE_QUESTIONS: list[dict] = [
    {
        "exam_section": ExamSection.writing,
        "task_number": 1,
        "prompt": (
            "Vous venez d'emménager dans un nouvel appartement. Vous écrivez "
            "à un ami francophone pour lui décrire votre nouveau logement et "
            "l'inviter à vous rendre visite."
        ),
        "instructions": (
            "Rédigez un message d'environ 60 à 120 mots. Présentez votre "
            "logement, expliquez pourquoi vous l'aimez et proposez une date "
            "de visite."
        ),
        "time_limit_seconds": 900,
        "word_count_min": 60,
        "word_count_max": 120,
        "difficulty_level": DifficultyLevel.A2,
        "source": "Réussir",
    },
    {
        "exam_section": ExamSection.writing,
        "task_number": 2,
        "prompt": (
            "Le journal de votre ville organise un concours de récits de "
            "voyage. Vous décidez d'y participer en racontant un voyage qui "
            "vous a particulièrement marqué."
        ),
        "instructions": (
            "Rédigez un récit d'environ 120 à 150 mots. Décrivez le lieu, "
            "racontez ce qui s'est passé et expliquez pourquoi ce voyage "
            "vous a marqué."
        ),
        "time_limit_seconds": 1200,
        "word_count_min": 120,
        "word_count_max": 150,
        "difficulty_level": DifficultyLevel.B1,
        "source": "Formation",
    },
    {
        "exam_section": ExamSection.writing,
        "task_number": 3,
        "prompt": (
            "Sur un forum en ligne, deux internautes débattent de la place "
            "du télétravail dans la vie professionnelle. L'un affirme qu'il "
            "améliore la qualité de vie, l'autre qu'il isole les salariés. "
            "Vous réagissez en donnant votre opinion argumentée."
        ),
        "instructions": (
            "Rédigez un texte argumentatif d'environ 120 à 180 mots. "
            "Comparez les deux points de vue, prenez position et justifiez "
            "votre opinion avec des exemples."
        ),
        "time_limit_seconds": 1200,
        "word_count_min": 120,
        "word_count_max": 180,
        "difficulty_level": DifficultyLevel.B2,
        "source": "Opal",
    },
]


async def seed() -> None:
    inserted = 0
    skipped = 0
    async with async_session_factory() as session:
        for data in SAMPLE_QUESTIONS:
            exists = await session.scalar(
                select(Question.id).where(
                    Question.exam_section == data["exam_section"],
                    Question.task_number == data["task_number"],
                    Question.source == data["source"],
                )
            )
            if exists is not None:
                skipped += 1
                continue
            session.add(Question(**data))
            inserted += 1
        await session.commit()

    print(f"Seed complete: {inserted} inserted, {skipped} already present.")


if __name__ == "__main__":
    asyncio.run(seed())
