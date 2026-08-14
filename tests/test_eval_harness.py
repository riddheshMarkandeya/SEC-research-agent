"""
Unit tests for eval_harness.py. Covers the deterministic grading logic
(extract_numbers, _normalize, grade_numeric, load_questions) plus
grade_judged's response-PARSING logic with a mocked Ollama call — the
call itself isn't made, only the "split PASS/FAIL + reason out of the
model's reply" logic is exercised. run_eval()'s end-to-end behavior
(live retrieval + live LLM calls) is exercised by manual runs
(python eval_harness.py) documented in PROJECT_CONTEXT.md, not here.
"""

import json

import pytest

from eval_harness import (
    _normalize,
    extract_numbers,
    grade_judged,
    grade_numeric,
    load_questions,
)


# ---------------------------------------------------------------------------
# extract_numbers
# ---------------------------------------------------------------------------
def test_extract_numbers_dollar_billion():
    assert (72.4, "billion") in extract_numbers("The total was approximately $72.4 billion.")


def test_extract_numbers_comma_grouped_raw_count():
    assert (166000.0, "raw") in extract_numbers("Apple had 166,000 full-time equivalent employees.")


def test_extract_numbers_percent_sign():
    assert (20.0, "percent") in extract_numbers("the effective tax rate was 20%")


def test_extract_numbers_percent_word():
    assert (20.0, "percent") in extract_numbers("a statutory rate of 20 percent")


def test_extract_numbers_no_digits_returns_empty_list():
    assert extract_numbers("no numbers in this sentence at all") == []


# ---------------------------------------------------------------------------
# _normalize — the percent/scale category-safety guarantee
# ---------------------------------------------------------------------------
def test_normalize_percent_stays_raw_value():
    assert _normalize(20, "percent") == ("percent", 20)


def test_normalize_billion_applies_multiplier():
    category, value = _normalize(72.4, "billion")
    assert category == "scale"
    assert value == pytest.approx(72_400_000_000)


def test_normalize_raw_is_unchanged_scale_value():
    assert _normalize(166000, "raw") == ("scale", 166000)


def test_normalize_percent_and_raw_are_different_categories():
    # This is the exact guarantee grade_numeric depends on: a literal "20"
    # must never be treated as satisfying an expected "20 percent".
    percent_category, _ = _normalize(20, "percent")
    scale_category, _ = _normalize(20, "raw")
    assert percent_category != scale_category


# ---------------------------------------------------------------------------
# grade_numeric
# ---------------------------------------------------------------------------
def test_grade_numeric_passes_on_matching_value():
    passed, _ = grade_numeric("Total RPO was approximately $72.4 billion.", 72.4, "billion")
    assert passed is True


def test_grade_numeric_fails_on_wrong_value():
    passed, _ = grade_numeric("Total RPO was approximately $50 billion.", 72.4, "billion")
    assert passed is False


def test_grade_numeric_fails_when_unit_category_differs_even_if_number_matches():
    # 72.4% and $72.4 billion must never be confused just because "72.4"
    # appears in both — this is the regression test for the category-
    # safety design in _normalize().
    passed, _ = grade_numeric("The rate was 72.4%.", 72.4, "billion")
    assert passed is False


def test_grade_numeric_within_tolerance_passes():
    # expected=100 raw -> tolerance = max(1% of 100, 0.05) = 1.0
    passed, _ = grade_numeric("The figure was 100.9.", 100, "raw")
    assert passed is True


def test_grade_numeric_outside_tolerance_fails():
    passed, _ = grade_numeric("The figure was 102.", 100, "raw")
    assert passed is False


# ---------------------------------------------------------------------------
# load_questions
# ---------------------------------------------------------------------------
def test_load_questions_parses_jsonl_and_skips_blank_lines(tmp_path):
    path = tmp_path / "questions.jsonl"
    path.write_text(
        '{"id": "q1", "question": "A?"}\n'
        "\n"
        '{"id": "q2", "question": "B?"}\n',
        encoding="utf-8",
    )
    questions = load_questions(path)
    assert [q["id"] for q in questions] == ["q1", "q2"]


# ---------------------------------------------------------------------------
# grade_judged — mocked Ollama call, testing only the response parsing
# ---------------------------------------------------------------------------
class _FakeResponse:
    def __init__(self, content: str):
        self._content = content

    def raise_for_status(self):
        pass

    def json(self):
        return {"message": {"content": self._content}}


def test_grade_judged_parses_pass(monkeypatch):
    monkeypatch.setattr(
        "eval_harness.requests.post",
        lambda *a, **k: _FakeResponse("PASS\nThe answer clearly satisfies the criteria."),
    )
    passed, reason = grade_judged("Q?", "some answer", "some criteria")
    assert passed is True
    assert reason == "The answer clearly satisfies the criteria."


def test_grade_judged_parses_fail(monkeypatch):
    monkeypatch.setattr(
        "eval_harness.requests.post",
        lambda *a, **k: _FakeResponse("FAIL\nThe answer does not mention the required risk."),
    )
    passed, reason = grade_judged("Q?", "some answer", "some criteria")
    assert passed is False
    assert reason == "The answer does not mention the required risk."


def test_grade_judged_lowercase_pass_still_counts(monkeypatch):
    monkeypatch.setattr(
        "eval_harness.requests.post",
        lambda *a, **k: _FakeResponse("pass\nfine."),
    )
    passed, _ = grade_judged("Q?", "some answer", "some criteria")
    assert passed is True
