"""Unit tests for eval/grading.py: the text matcher and the judge
criteria for refusal and clarify questions."""

import pytest

from sec_agent.eval import grading
from sec_agent.eval.grading import judge_criteria_for, text_matches


# ---------------------------------------------------------------------------
# text_matches
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "answer",
    [
        "The fiscal year ended on February 1, 2025 [1].",
        "The fiscal year ended on Feb. 1, 2025 [1].",
        "The fiscal year ended on 2/1/2025 [1].",
        "The fiscal year ended on 2025-02-01 [1].",
        "THE FISCAL YEAR ENDED ON FEBRUARY 1 2025 [1].",
        "The fiscal year ended on February 1st, 2025 [1].",
        "The fiscal year ended on 1 February 2025 [1].",
        "The fiscal year ended on 1st Feb. 2025 [1].",
    ],
)
def test_text_matches_normalizes_dates_and_case(answer):
    assert text_matches(answer, ["February 1, 2025"])


def test_text_matches_any_accepted_variant_case_and_punctuation_insensitive():
    accepted = ["PricewaterhouseCoopers LLP", "PwC"]
    assert text_matches("Caterpillar's auditor is PricewaterhouseCoopers, LLP [4].", accepted)
    assert text_matches("Its auditor is pwc [4].", accepted)


def test_a_decimal_before_a_month_is_not_read_as_a_day():
    assert text_matches("A rate of 5.25 June 2024 [1].", ["5.25"])


def test_a_day_first_date_right_after_a_comma_still_normalizes():
    assert text_matches("Paid on Monday,25 June 2024 [1].", ["June 25, 2024"])


def test_text_matches_whole_words_only():
    assert not text_matches("The answer is PwCs [1].", ["PwC"])
    assert not text_matches("The fiscal year ended February 11, 2025 [1].", ["February 1, 2025"])


def test_text_matches_rejects_a_different_value():
    assert not text_matches("The auditor is Deloitte & Touche LLP [2].", ["PricewaterhouseCoopers LLP"])


# ---------------------------------------------------------------------------
# judge_criteria_for
# ---------------------------------------------------------------------------
def test_refusal_criteria_is_its_kinds_template():
    q = {"type": "refusal", "refusal_kind": "never_disclosed"}
    assert judge_criteria_for(q) == grading.REFUSAL_CRITERIA["never_disclosed"]


def test_refusal_criteria_appends_the_questions_own_detail():
    q = {"type": "refusal", "refusal_kind": "false_premise", "criteria": "Revenue rose {not a field}."}
    assert judge_criteria_for(q).endswith(" For this question: Revenue rose {not a field}.")


def test_clarify_criteria_lists_the_readings():
    q = {"type": "clarify", "readings": ["gross margin", "operating margin"]}
    assert "these readings: gross margin; operating margin." in judge_criteria_for(q)
