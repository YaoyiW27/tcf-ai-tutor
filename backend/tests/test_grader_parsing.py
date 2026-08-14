"""Grader parsing/derivation logic (Claude fully mocked — no real calls)."""

from app import grader, speaking_grader
from app.grader import Correction, CorrectionVerdict, Usage, VerificationResult
from app.speaking_grader import SpeakingGrade


def test_nclc_band_for_known_levels():
    assert grader.nclc_band_for("B2") == ("NCLC 7", "10–11")
    assert grader.nclc_band_for("A1") == ("NCLC 4", "below 6")


def test_nclc_band_for_unknown_level_returns_none():
    assert grader.nclc_band_for("Z9") == (None, None)


def test_speaking_nclc_oral_band_for_levels():
    assert speaking_grader.nclc_oral_band_for("B2") == ("NCLC 7", "10–11")
    assert speaking_grader.nclc_oral_band_for("Z9") == (None, None)


def _speaking_grade(tf, co, lx, gr, level="B1"):
    return SpeakingGrade(
        task_fulfillment=tf, coherence=co, lexis=lx, grammar=gr,
        estimated_level=level, overall_comment="", corrections=[],
    )


def test_speaking_feedback_fields_dimensions_and_mean_total():
    dims, total = speaking_grader.feedback_fields(_speaking_grade(4, 3, 2, 5, "B2"))
    assert dims == {
        "task_fulfillment": 4, "coherence": 3, "lexis": 2, "grammar": 5,
        "estimated_level": "B2",
    }
    assert total == 3.5  # mean of 4,3,2,5


async def test_verify_errors_keeps_only_genuine(monkeypatch):
    draft = [
        Correction(original="a", correction="A", explanation="x"),
        Correction(original="b", correction="B", explanation="y"),
    ]
    verdicts = VerificationResult(items=[
        CorrectionVerdict(original="a", correction="A", explanation="x", is_genuine_error=True),
        CorrectionVerdict(original="b", correction="B", explanation="y", is_genuine_error=False),
    ])

    async def fake_call(system, user, output_format, **kwargs):
        return verdicts, Usage(0, 0)

    monkeypatch.setattr(grader, "_structured_call", fake_call)
    corrections, _usage = await grader.verify_errors("essay", draft)
    assert [c.original for c in corrections] == ["a"]  # non-genuine dropped


async def test_verify_errors_shortcircuits_on_empty_draft_without_llm_call(monkeypatch):
    async def must_not_call(*args, **kwargs):
        raise AssertionError("_structured_call should not run for an empty draft")

    monkeypatch.setattr(grader, "_structured_call", must_not_call)
    assert await grader.verify_errors("essay", []) == ([], None)
