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

# Sample TCF Canada "Expression écrite" tasks (Tâches 1–3).
# Idempotency is keyed on (exam_section, task_number, source), so every
# question sharing a task_number must use a distinct source.
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
    # --- Tâche 1 (A2, 60–120 mots) : situations du quotidien ---
    {
        "exam_section": ExamSection.writing,
        "task_number": 1,
        "prompt": (
            "Vous organisez une fête pour votre anniversaire samedi prochain. "
            "Vous écrivez un message à un ami francophone pour l'inviter."
        ),
        "instructions": (
            "Rédigez un message d'environ 60 à 120 mots. Indiquez la date, "
            "l'heure et le lieu, expliquez ce que vous allez faire ensemble et "
            "demandez-lui de confirmer sa présence."
        ),
        "time_limit_seconds": 900,
        "word_count_min": 60,
        "word_count_max": 120,
        "difficulty_level": DifficultyLevel.A2,
        "source": "Didier",
    },
    {
        "exam_section": ExamSection.writing,
        "task_number": 1,
        "prompt": (
            "Un ami francophone vous a hébergé pendant vos vacances dans sa "
            "ville. De retour chez vous, vous lui écrivez un message pour le "
            "remercier."
        ),
        "instructions": (
            "Rédigez un message d'environ 60 à 120 mots. Remerciez-le de son "
            "accueil, dites ce que vous avez préféré pendant votre séjour et "
            "proposez de le recevoir à votre tour."
        ),
        "time_limit_seconds": 900,
        "word_count_min": 60,
        "word_count_max": 120,
        "difficulty_level": DifficultyLevel.A2,
        "source": "Hachette",
    },
    {
        "exam_section": ExamSection.writing,
        "task_number": 1,
        "prompt": (
            "Un ami français va bientôt s'installer dans votre quartier. Vous "
            "lui écrivez un message pour lui décrire l'endroit où vous habitez."
        ),
        "instructions": (
            "Rédigez un message d'environ 60 à 120 mots. Décrivez votre "
            "quartier, présentez les commerces et les transports disponibles "
            "et dites ce que vous préférez dans cet endroit."
        ),
        "time_limit_seconds": 900,
        "word_count_min": 60,
        "word_count_max": 120,
        "difficulty_level": DifficultyLevel.A2,
        "source": "CLE",
    },
    {
        "exam_section": ExamSection.writing,
        "task_number": 1,
        "prompt": (
            "Vous souhaitez vous inscrire à un cours de cuisine dans une "
            "association francophone. Vous écrivez un message pour demander "
            "des informations."
        ),
        "instructions": (
            "Rédigez un message d'environ 60 à 120 mots. Présentez-vous, posez "
            "des questions sur les horaires et le tarif et demandez comment "
            "vous inscrire."
        ),
        "time_limit_seconds": 900,
        "word_count_min": 60,
        "word_count_max": 120,
        "difficulty_level": DifficultyLevel.A2,
        "source": "Nathan",
    },
    # --- Tâche 2 (B1, 120–150 mots) : textes d'opinion ---
    {
        "exam_section": ExamSection.writing,
        "task_number": 2,
        "prompt": (
            "Un magazine francophone pour les jeunes publie une rubrique "
            "d'opinion. Cette semaine, la question posée aux lecteurs est : "
            "« Les réseaux sociaux nous rapprochent-ils vraiment des autres ? » "
            "Vous décidez d'y répondre."
        ),
        "instructions": (
            "Rédigez un texte d'environ 120 à 150 mots. Donnez votre opinion "
            "sur les réseaux sociaux, présentez leurs avantages et leurs "
            "inconvénients et illustrez votre point de vue par des exemples."
        ),
        "time_limit_seconds": 1200,
        "word_count_min": 120,
        "word_count_max": 150,
        "difficulty_level": DifficultyLevel.B1,
        "source": "Didier",
    },
    {
        "exam_section": ExamSection.writing,
        "task_number": 2,
        "prompt": (
            "Le site Internet de votre entreprise invite les employés à donner "
            "leur avis sur le télétravail. Vous rédigez un commentaire pour "
            "partager votre point de vue."
        ),
        "instructions": (
            "Rédigez un texte d'environ 120 à 150 mots. Expliquez si vous "
            "préférez travailler à distance ou au bureau, donnez au moins deux "
            "raisons et appuyez-vous sur votre expérience."
        ),
        "time_limit_seconds": 1200,
        "word_count_min": 120,
        "word_count_max": 150,
        "difficulty_level": DifficultyLevel.B1,
        "source": "Hachette",
    },
    {
        "exam_section": ExamSection.writing,
        "task_number": 2,
        "prompt": (
            "La mairie de votre ville mène une enquête auprès des habitants sur "
            "les transports en commun. Vous écrivez un message pour donner "
            "votre avis."
        ),
        "instructions": (
            "Rédigez un texte d'environ 120 à 150 mots. Dites si vous utilisez "
            "souvent les transports en commun, expliquez ce que vous en pensez "
            "et proposez des améliorations."
        ),
        "time_limit_seconds": 1200,
        "word_count_min": 120,
        "word_count_max": 150,
        "difficulty_level": DifficultyLevel.B1,
        "source": "CLE",
    },
    {
        "exam_section": ExamSection.writing,
        "task_number": 2,
        "prompt": (
            "Un forum en ligne pose la question suivante à ses membres : "
            "« Faut-il commencer à apprendre une langue étrangère dès "
            "l'enfance ? » Vous décidez de réagir."
        ),
        "instructions": (
            "Rédigez un texte d'environ 120 à 150 mots. Donnez votre opinion, "
            "expliquez pourquoi il est utile d'apprendre une langue étrangère "
            "et donnez des exemples tirés de votre expérience."
        ),
        "time_limit_seconds": 1200,
        "word_count_min": 120,
        "word_count_max": 150,
        "difficulty_level": DifficultyLevel.B1,
        "source": "Nathan",
    },
    # --- Tâche 3 (B2, 120–180 mots) : textes argumentatifs ---
    {
        "exam_section": ExamSection.writing,
        "task_number": 3,
        "prompt": (
            "Sur un forum consacré à l'éducation, deux internautes s'opposent "
            "sur l'usage des outils numériques à l'école. L'un estime qu'ils "
            "favorisent l'apprentissage, l'autre qu'ils nuisent à la "
            "concentration des élèves. Vous réagissez en donnant votre opinion "
            "argumentée."
        ),
        "instructions": (
            "Rédigez un texte argumentatif d'environ 120 à 180 mots. Comparez "
            "les deux points de vue, prenez position et justifiez votre "
            "opinion avec des exemples."
        ),
        "time_limit_seconds": 1200,
        "word_count_min": 120,
        "word_count_max": 180,
        "difficulty_level": DifficultyLevel.B2,
        "source": "Didier",
    },
    {
        "exam_section": ExamSection.writing,
        "task_number": 3,
        "prompt": (
            "Un article en ligne suscite un débat : faut-il interdire les "
            "voitures dans les centres-villes pour protéger l'environnement ? "
            "Dans les commentaires, les avis sont partagés. Vous réagissez en "
            "donnant votre opinion argumentée."
        ),
        "instructions": (
            "Rédigez un texte argumentatif d'environ 120 à 180 mots. Présentez "
            "les arguments pour et contre, prenez position et appuyez votre "
            "opinion sur des exemples concrets."
        ),
        "time_limit_seconds": 1200,
        "word_count_min": 120,
        "word_count_max": 180,
        "difficulty_level": DifficultyLevel.B2,
        "source": "Hachette",
    },
    {
        "exam_section": ExamSection.writing,
        "task_number": 3,
        "prompt": (
            "Sur un forum professionnel, un débat oppose deux internautes sur "
            "l'équilibre entre vie professionnelle et vie privée. L'un pense "
            "que l'entreprise doit s'en préoccuper, l'autre que cela relève de "
            "chacun. Vous réagissez en donnant votre opinion argumentée."
        ),
        "instructions": (
            "Rédigez un texte argumentatif d'environ 120 à 180 mots. Comparez "
            "les deux points de vue, prenez position et justifiez votre "
            "opinion avec des exemples."
        ),
        "time_limit_seconds": 1200,
        "word_count_min": 120,
        "word_count_max": 180,
        "difficulty_level": DifficultyLevel.B2,
        "source": "CLE",
    },
    {
        "exam_section": ExamSection.writing,
        "task_number": 3,
        "prompt": (
            "Un magazine en ligne publie une tribune sur la diversité "
            "culturelle en milieu de travail. Les lecteurs débattent : "
            "certains y voient une richesse, d'autres une source de "
            "difficultés. Vous réagissez en donnant votre opinion argumentée."
        ),
        "instructions": (
            "Rédigez un texte argumentatif d'environ 120 à 180 mots. Comparez "
            "les deux points de vue, prenez position et justifiez votre "
            "opinion avec des exemples concrets."
        ),
        "time_limit_seconds": 1200,
        "word_count_min": 120,
        "word_count_max": 180,
        "difficulty_level": DifficultyLevel.B2,
        "source": "Nathan",
    },
    # --- Expression orale (Tâches 1–3) ---
    # word_count_min/max don't apply to speech, but the columns are NOT NULL, so
    # they are set to 0 (= N/A). time_limit_seconds holds the approximate speaking
    # duration for each task. exam_section=speaking keeps these from colliding
    # with the writing tasks under the (section, task_number, source) dedup key.
    {
        "exam_section": ExamSection.speaking,
        "task_number": 1,
        "prompt": (
            "L'examinateur souhaite faire connaissance avec vous. Présentez-vous "
            "et parlez de votre vie quotidienne."
        ),
        "instructions": (
            "Répondez à l'oral pendant environ 2 minutes, sans préparation. "
            "Parlez de vous, de votre travail ou de vos études, de vos loisirs "
            "et de vos projets."
        ),
        "time_limit_seconds": 120,
        "word_count_min": 0,
        "word_count_max": 0,
        "difficulty_level": DifficultyLevel.A2,
        "source": "Réussir",
    },
    {
        "exam_section": ExamSection.speaking,
        "task_number": 2,
        "prompt": (
            "Vous venez de vous installer dans une nouvelle ville et vous "
            "souhaitez vous inscrire à la médiathèque municipale. Vous vous "
            "adressez à un employé pour obtenir des renseignements."
        ),
        "instructions": (
            "Après 2 minutes de préparation, jouez la situation pendant environ "
            "3 minutes 30. Posez des questions pour obtenir toutes les "
            "informations utiles : horaires, conditions d'inscription, documents "
            "à fournir et services proposés."
        ),
        "time_limit_seconds": 210,
        "word_count_min": 0,
        "word_count_max": 0,
        "difficulty_level": DifficultyLevel.B1,
        "source": "Réussir",
    },
    {
        "exam_section": ExamSection.speaking,
        "task_number": 3,
        "prompt": (
            "« Les écrans occupent une place de plus en plus importante dans la "
            "vie des enfants. » Donnez votre opinion sur ce sujet et défendez "
            "votre point de vue."
        ),
        "instructions": (
            "Après 2 minutes de préparation, exprimez-vous pendant environ 4 "
            "minutes 30. Présentez votre point de vue de façon structurée, "
            "développez vos arguments et illustrez-les par des exemples concrets."
        ),
        "time_limit_seconds": 270,
        "word_count_min": 0,
        "word_count_max": 0,
        "difficulty_level": DifficultyLevel.B2,
        "source": "Réussir",
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
