"""Integrity of the CEFR rubric corpus + the seed script's skip-existing logic.

Pure data/logic checks — no DB, no gateway. Guards the two ways the corpus can
silently break: a duplicate idempotency key (rows would clash on the unique
constraint / be skipped) and incomplete section×level coverage.
"""

from app.models import DifficultyLevel, ExamSection
from app.rubric_corpus import DIMENSION, RUBRICS, SOURCE, rubric_key
from scripts.seed_rubrics import filter_new

_LEVELS = list(DifficultyLevel)  # A1..C2
_SECTIONS = (ExamSection.writing, ExamSection.speaking)


def test_corpus_covers_every_section_and_level_exactly_once():
    assert len(RUBRICS) == len(_SECTIONS) * len(_LEVELS)  # 2 × 6 = 12
    pairs = {(r["exam_section"], r["cefr_level"]) for r in RUBRICS}
    assert pairs == {(s, lv) for s in _SECTIONS for lv in _LEVELS}


def test_idempotency_keys_are_unique():
    keys = [rubric_key(r) for r in RUBRICS]
    assert len(keys) == len(set(keys)), "duplicate rubric idempotency key"


def test_every_descriptor_has_substantive_text_and_shared_metadata():
    for r in RUBRICS:
        assert r["dimension"] == DIMENSION
        assert r["source"] == SOURCE
        # Descriptors are multi-sentence bands, not stubs.
        assert len(r["text"]) > 120, r["cefr_level"]


def test_rubric_key_is_stable_across_enum_and_string_fields():
    # A corpus record (enum fields) and an equivalent DB-row-shaped dict (string
    # fields) must produce the same key, so skip-existing matching is reliable.
    record = RUBRICS[0]
    as_strings = {
        "exam_section": record["exam_section"].value,
        "cefr_level": record["cefr_level"].value,
        "dimension": record["dimension"],
        "source": record["source"],
    }
    assert rubric_key(record) == rubric_key(as_strings)


def test_filter_new_returns_only_absent_records():
    existing = {rubric_key(RUBRICS[0]), rubric_key(RUBRICS[1])}
    new = filter_new(RUBRICS, existing)
    assert len(new) == len(RUBRICS) - 2
    assert all(rubric_key(r) not in existing for r in new)


def test_filter_new_empty_when_all_present():
    all_keys = {rubric_key(r) for r in RUBRICS}
    assert filter_new(RUBRICS, all_keys) == []


def test_filter_new_all_when_none_present():
    assert filter_new(RUBRICS, set()) == RUBRICS
