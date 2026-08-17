"""Hand-authored CEFR/TCF scoring-reference descriptors (the RAG corpus).

One holistic descriptor per ``(exam_section, cefr_level)`` — what a French
written or spoken production looks like at that level across task fulfilment,
coherence, vocabulary/lexis, and grammatical control. These are original
paraphrases of the public CEFR level definitions (copyright-clean; no official
TCF material is reproduced), written in English because they ground the (English)
grader prompt's judgement of French competence.

Retrieval embeds the candidate's production and returns the nearest descriptors,
so the score node anchors its level placement to reference bands rather than
unaided judgement. ``dimension`` is ``"overall"`` for the whole initial corpus;
the field exists so per-dimension descriptors can be added later without a schema
change. Idempotency (``scripts.seed_rubrics``) is keyed on
``(exam_section, dimension, cefr_level, source)``.

Speaking descriptors describe delivery from a transcript only — pronunciation and
acoustic fluency are out of scope (the transcript loses that signal), matching how
the speaking grader already treats disfluencies.
"""

from app.models import DifficultyLevel, ExamSection

SOURCE = "CEFR"
DIMENSION = "overall"

# (exam_section, cefr_level) -> descriptor text.
_WRITING: dict[DifficultyLevel, str] = {
    DifficultyLevel.A1: (
        "Writes only simple, isolated phrases and sentences — a short note, a "
        "form, a basic message. Vocabulary is limited to concrete personal needs "
        "(name, home, family). Connectors barely go beyond 'et'; frequent errors "
        "in basic verb forms, gender, and agreement, though isolated words remain "
        "recognisable."
    ),
    DifficultyLevel.A2: (
        "Writes short, simple notes, messages, and a very simple personal letter, "
        "linking ideas with 'et', 'mais', and 'parce que'. Vocabulary covers "
        "everyday routines and immediate needs. Recurrent errors in gender, "
        "agreement, and tense choice occur, but the intended meaning generally "
        "comes through."
    ),
    DifficultyLevel.B1: (
        "Writes straightforward connected text on familiar topics, describing "
        "experiences and giving brief reasons and explanations for opinions. "
        "Everyday vocabulary is adequate, with some circumlocution for gaps. "
        "Frequent structures are well controlled; errors appear on more complex "
        "forms (subjunctive, tense sequence) but rarely block understanding."
    ),
    DifficultyLevel.B2: (
        "Writes clear, detailed text on a range of subjects and develops an "
        "argument, weighing advantages and disadvantages. Vocabulary is broad with "
        "some precision, with the occasional awkward collocation. Grammatical "
        "control is good; errors do not lead to misunderstanding and are often "
        "self-corrected."
    ),
    DifficultyLevel.C1: (
        "Writes clear, well-structured text on complex subjects, using cohesive "
        "devices and organisational patterns in a controlled way. Vocabulary is "
        "broad and precise, including some idiomatic and connotative usage. "
        "Grammatical accuracy is consistently high; errors are rare and minor."
    ),
    DifficultyLevel.C2: (
        "Writes clear, smoothly flowing, complex text in an effective, "
        "register-appropriate style, with a logical structure that helps the "
        "reader find salient points. Command of a very broad lexical repertoire is "
        "full and precise, including nuance and idiom. Maintains consistent control "
        "of complex grammar; the text is virtually error-free."
    ),
}

_SPEAKING: dict[DifficultyLevel, str] = {
    DifficultyLevel.A1: (
        "Produces simple, mainly isolated phrases about people and places, from a "
        "very limited stock of words and short formulaic expressions. Turns are "
        "short with frequent pausing. Only a few memorised patterns are used, with "
        "many basic errors. (Delivery is judged from the transcript; pronunciation "
        "is out of scope.)"
    ),
    DifficultyLevel.A2: (
        "Gives a simple description as a short series of points and handles short "
        "social exchanges. Basic lexis covers concrete everyday needs. Frequent "
        "errors occur but the intended meaning is usually clear; turns are short "
        "with visible hesitation and restarts, which are normal for the level."
    ),
    DifficultyLevel.B1: (
        "Connects phrases to describe experiences, plans, and opinions, giving "
        "reasons and explanations. Lexis is sufficient to get by on familiar topics, "
        "with some circumlocution. Accuracy is reasonable in familiar contexts; "
        "errors are more noticeable in less routine language. Delivery is mostly "
        "sustained with some hesitation."
    ),
    DifficultyLevel.B2: (
        "Gives clear, detailed descriptions and viewpoints, developing an argument "
        "with relevant support. Range of lexis is good, and formulation is varied "
        "to avoid repetition. Grammatical control is good, with occasional slips "
        "that are often self-corrected. Interaction is fluent and largely "
        "spontaneous."
    ),
    DifficultyLevel.C1: (
        "Gives clear, detailed accounts of complex subjects fluently and almost "
        "effortlessly. Lexical repertoire is broad, with idiomatic and colloquial "
        "usage handled well. Grammatical accuracy is high; errors are rare and hard "
        "to spot. Ideas are structured and connected smoothly."
    ),
    DifficultyLevel.C2: (
        "Presents a clear, smoothly flowing description or argument in a style "
        "appropriate to the context, with an effective logical structure. Command "
        "of lexis is very broad, precise, and natural, including idiom and register. "
        "Maintains consistent control of complex grammar even under processing "
        "pressure; delivery is essentially native-like."
    ),
}


def _build() -> list[dict]:
    """Flatten the per-section level maps into corpus records."""
    records: list[dict] = []
    for section, level_map in (
        (ExamSection.writing, _WRITING),
        (ExamSection.speaking, _SPEAKING),
    ):
        for level, text in level_map.items():
            records.append(
                {
                    "exam_section": section,
                    "cefr_level": level,
                    "dimension": DIMENSION,
                    "source": SOURCE,
                    "text": text,
                }
            )
    return records


# The full corpus: 2 sections × 6 CEFR levels = 12 holistic descriptors.
RUBRICS: list[dict] = _build()


def rubric_key(record: dict) -> tuple[str, str, str, str]:
    """Idempotency key for a corpus record — matches the DB unique constraint.

    ``(exam_section, dimension, cefr_level, source)`` as plain strings, so it is
    comparable whether the fields are enums (corpus) or column values (DB rows).
    """
    return (
        ExamSection(record["exam_section"]).value,
        str(record["dimension"]),
        DifficultyLevel(record["cefr_level"]).value,
        str(record["source"]),
    )
