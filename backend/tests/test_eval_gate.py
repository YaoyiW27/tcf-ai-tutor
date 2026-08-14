"""Eval gate logic: the per-case predicates and the pass/fail suite exit.

`run_grader` is mocked, so no Claude calls — we only test our gate decisions.
"""

import argparse

import pytest

from app.grader import Correction, EssayGrade
from scripts import eval_grader


def _grade(level="A2", corrections=None):
    return EssayGrade(
        task_fulfillment=4, coherence=4, vocabulary=4, grammar=4,
        estimated_level=level, overall_comment="ok", corrections=corrections or [],
    )


def _corr(original):
    return Correction(original=original, correction="x", explanation="y")


def test_check_polite_imparfait_flags_when_corrected():
    assert eval_grader.check_polite_imparfait(_grade(corrections=[_corr("Je voulais vous demander")]))[0] is False


def test_check_polite_imparfait_passes_when_absent():
    assert eval_grader.check_polite_imparfait(_grade(corrections=[]))[0] is True


def test_check_obvious_plural_error_detects_marker():
    assert eval_grader.check_obvious_plural_error(_grade(corrections=[_corr("des pomme")]))[0] is True


def test_check_weak_short_answer_rejects_overscored():
    assert eval_grader.check_weak_short_answer(_grade(level="C1"))[0] is False
    assert eval_grader.check_weak_short_answer(_grade(level="A2"))[0] is True


def _fixed_args():
    return argparse.Namespace(list=False, case=None)


async def test_eval_suite_exits_zero_when_all_cases_pass(monkeypatch):
    async def fake_run(question, content):
        return _grade(level="A2", corrections=[_corr("des pomme")])

    monkeypatch.setattr(eval_grader, "run_grader", fake_run)
    monkeypatch.setattr(eval_grader, "parse_args", _fixed_args)
    await eval_grader.main()  # all three cases pass -> no SystemExit


async def test_eval_suite_exits_nonzero_when_a_case_fails(monkeypatch):
    async def fake_run(question, content):
        # C1 fails the weak-short-answer gate (over-scored)
        return _grade(level="C1", corrections=[_corr("des pomme")])

    monkeypatch.setattr(eval_grader, "run_grader", fake_run)
    monkeypatch.setattr(eval_grader, "parse_args", _fixed_args)
    with pytest.raises(SystemExit):
        await eval_grader.main()
