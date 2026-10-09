"""Unit tests for eval/questions.py: the question-file schema and the
load-time checks that run before any quota is spent."""

import json

import pytest

from sec_agent.config import QUESTIONS_PATH
from sec_agent.eval.questions import validate_questions

V2_TAGS = {
    "category": "cross-company",
    "steps": 2,
    "answer_source": "table",
    "trap": "look-alike",
    "needs_calculate": False,
}


def _numeric(**extra) -> dict:
    return {
        "id": "q1",
        "ticker": "JPM",
        "question": "What was JPMorgan's total net revenue for 2025?",
        "type": "numeric",
        "expected_value": 182.4,
        "expected_unit": "billion",
        **extra,
    }


def test_every_v1_question_validates_unchanged():
    with QUESTIONS_PATH.open(encoding="utf-8") as f:
        questions = [json.loads(line) for line in f if line.strip()]
    validate_questions(questions)


@pytest.mark.parametrize(
    "question",
    [
        _numeric(),
        _numeric(**V2_TAGS),
        _numeric(accepted=["December 31, 2025"], tolerance=0.02, tolerance_note="inputs rounded to 0.1B"),
        _numeric(forbidden_values=[{"value": 177.6, "unit": "billion"}, {"value": 101.9, "unit": "billion", "ticker": "BAC"}]),
        {"id": "t", "ticker": "CAT", "question": "Who audits Caterpillar?", "type": "text", "accepted": ["PricewaterhouseCoopers"]},
        {"id": "r", "ticker": "XOM", "question": "XOM 2030 revenue?", "type": "refusal", "refusal_kind": "not_yet_filed"},
        {"id": "r2", "ticker": "JPM", "question": "Why did JPM's 2025 revenue fall?", "type": "refusal",
         "refusal_kind": "false_premise", "criteria": "It rose, from $177.6 billion to $182.4 billion."},
        {"id": "c", "ticker": "WMT", "question": "What was Walmart's margin?", "type": "clarify",
         "readings": ["gross margin", "operating margin"]},
        {"id": "cmp", "tickers": ["JPM", "BAC"], "question": "q", "type": "comparison",
         "expected": [{"ticker": "JPM", "expected_value": 1, "expected_unit": "billion"},
                      {"ticker": "BAC", "expected_value": 2, "expected_unit": "billion"}]},
    ],
)
def test_valid_questions_pass(question):
    validate_questions([question])


@pytest.mark.parametrize(
    "question, fragment",
    [
        ({k: v for k, v in _numeric().items() if k != "expected_value"}, "expected_value"),
        ({"id": "t", "ticker": "CAT", "question": "q", "type": "text"}, "accepted"),
        ({"id": "t", "ticker": "CAT", "question": "q", "type": "text", "accepted": []}, "accepted"),
        ({"id": "r", "ticker": "XOM", "question": "q", "type": "refusal"}, "refusal_kind"),
        ({"id": "r", "ticker": "XOM", "question": "q", "type": "refusal", "refusal_kind": "dunno"}, "dunno"),
        ({"id": "c", "ticker": "WMT", "question": "q", "type": "clarify", "readings": ["one"]}, "readings"),
        ({"id": "j", "ticker": "WMT", "question": "q", "type": "judged"}, "criteria"),
        ({"id": "x", "ticker": "WMT", "question": "q", "type": "essay"}, "essay"),
        (_numeric(expected_vale=1), "expected_vale"),
        (_numeric(category="extraction"), "steps"),
        (_numeric(**{**V2_TAGS, "category": "trivia"}), "trivia"),
        (_numeric(tolerance=0.02), "tolerance_note"),
        (_numeric(tolerance=0), "tolerance"),
        ({k: v for k, v in _numeric().items() if k != "type"}, "type"),
    ],
)
def test_invalid_question_raises_naming_the_problem_and_the_question(question, fragment):
    with pytest.raises(ValueError) as e:
        validate_questions([question])
    assert fragment in str(e.value)
    assert repr(question.get("id")) in str(e.value)


def test_the_most_relevant_error_is_reported_not_the_first():
    # A missing ticker fails an anyOf too, but the missing value is the
    # error that names what to fix.
    with pytest.raises(ValueError, match="'expected_value' is a required property"):
        validate_questions([{"id": "x", "question": "q", "type": "numeric"}])


def test_question_without_an_id_is_named_by_position():
    with pytest.raises(ValueError, match="question 2"):
        validate_questions([_numeric(), {"question": "q", "type": "judged", "criteria": "c"}])


def test_duplicate_ids_raise():
    with pytest.raises(ValueError, match="duplicate question id 'q1'"):
        validate_questions([_numeric(), _numeric()])


def test_a_trap_value_on_a_multi_ticker_question_must_name_its_ticker():
    question = _numeric(forbidden_values=[{"value": 1.0, "unit": "billion"}])
    del question["ticker"]
    question["tickers"] = ["JPM", "BAC"]
    with pytest.raises(ValueError, match=r"'q1' at \$\.forbidden_values\[0\]: names no ticker"):
        validate_questions([question])
    question["forbidden_values"][0]["ticker"] = "BAC"
    validate_questions([question])
