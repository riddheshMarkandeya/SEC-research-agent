"""Unit tests for eval/grading.py: the text matcher and the judge
criteria for refusal and clarify questions."""

import pytest

from sec_agent.eval import grading
from sec_agent.agent.calculate import calculation_as_result
from sec_agent.eval.grading import (
    claim_attributions,
    entry_companies,
    forbidden_hits,
    judge_criteria_for,
    misattributed,
    text_matches,
)


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


# ---------------------------------------------------------------------------
# claim attribution
# ---------------------------------------------------------------------------
def _source(ticker: str, text: str = "chunk text", chunk_index="0") -> dict:
    return {"text": text, "metadata": {"ticker": ticker, "chunk_index": chunk_index}}


def _calculated(idx_a: int, idx_b: int) -> dict:
    result = {"value": 1.5, "unit": "raw"}
    args = {
        "operation": "divide", "operand_a": 3, "unit_a": "billion", "citation_index_a": idx_a,
        "operand_b": 2, "unit_b": "billion", "citation_index_b": idx_b,
    }
    return calculation_as_result(result, args)


def _claim(index, value=182.4, unit="billion") -> dict:
    return {"citation_index": index, "value": value, "unit": unit, "quote": "q"}


@pytest.mark.parametrize(
    "source",
    [
        _source("JPM"),
        _source("JPM", chunk_index="xbrl"),
        {"text": "JPM | 2025 | 182.4", "metadata": {"ticker": "JPM", "form": "XBRL frame data"}},
    ],
    ids=["chunk", "xbrl-fact", "comparison-row"],
)
def test_a_claim_takes_the_ticker_of_the_source_it_cites(source):
    assert claim_attributions([_claim(1)], [source]) == [
        {"citation_index": 1, "value": 182.4, "unit": "billion", "quote": "q", "tickers": ["JPM"]}
    ]


def test_a_calculated_value_from_one_companys_operands_is_attributed_to_it():
    results = [_source("JPM"), _source("JPM"), _calculated(1, 2)]
    assert claim_attributions([_claim(3)], results)[0]["tickers"] == ["JPM"]


def test_a_cross_company_calculation_takes_both_companies():
    results = [_source("JPM"), _source("BAC"), _calculated(1, 2)]
    assert claim_attributions([_claim(3)], results)[0]["tickers"] == ["BAC", "JPM"]


def test_a_chained_calculation_resolves_through_both_levels():
    results = [_source("JPM"), _source("JPM"), _calculated(1, 2), _source("JPM"), _calculated(3, 4)]
    assert claim_attributions([_claim(5)], results)[0]["tickers"] == ["JPM"]
    results[3] = _source("BAC")
    assert claim_attributions([_claim(5)], results)[0]["tickers"] == ["BAC", "JPM"]


@pytest.mark.parametrize("index", [0, -1, 3, True])
def test_an_index_outside_the_results_has_no_company(index):
    # 0 and -1 would otherwise wrap around to the last result, and True
    # pass for 1 (a bool is an int).
    results = [_source("JPM"), _source("JPM")]
    assert claim_attributions([_claim(index)], results)[0]["tickers"] == []


def test_a_calculation_whose_operand_tail_is_unreadable_has_no_company():
    results = [{"text": "edited away", "metadata": {"ticker": "N/A", "chunk_index": "calculated"}}]
    assert claim_attributions([_claim(1)], results)[0]["tickers"] == []


@pytest.mark.parametrize(
    "claim",
    [
        {"citation_index": 1, "quote": "Revenue grew on strong demand."},
        {"citation_index": 1, "value": 182.4, "quote": "182.4"},
        {"citation_index": 1, "unit": "billion", "quote": "182.4"},
    ],
    ids=["qualitative", "value-without-unit", "unit-without-value"],
)
def test_a_claim_without_both_value_and_unit_is_skipped(claim):
    assert claim_attributions([claim], [_source("JPM")]) == []


_BANKS = [
    {"ticker": "JPM", "expected_value": 182.4, "expected_unit": "billion"},
    {"ticker": "BAC", "expected_value": 101.9, "expected_unit": "billion"},
]


def _attr(tickers, value, unit="billion") -> dict:
    """An attribution as claim_attributions returns it; `tickers` is one ticker or a list."""
    tickers = [tickers] if isinstance(tickers, str) else tickers
    return {"citation_index": 1, "value": value, "unit": unit, "quote": "q", "tickers": tickers}


_TWO_BANKS = ["JPM", "BAC"]


def test_each_expected_value_must_be_claimed_for_its_company():
    right = [_attr("JPM", 182.4), _attr("BAC", 101.9)]
    assert misattributed(_BANKS, right, None, _TWO_BANKS) == []
    swapped = [_attr("JPM", 101.9), _attr("BAC", 182.4)]
    assert misattributed(_BANKS, swapped, None, _TWO_BANKS) == ["JPM (182.4 billion)", "BAC (101.9 billion)"]


def test_a_value_in_another_unit_category_does_not_match():
    # 182.4 percent is not $182.4 billion, whatever the company.
    assert misattributed(_BANKS[:1], [_attr("JPM", 182.4, "percent")], None, _TWO_BANKS) == ["JPM (182.4 billion)"]


@pytest.mark.parametrize(
    "entry, question_tickers, companies",
    [
        ({"ticker": "JPM"}, _TWO_BANKS, {"JPM"}),
        # A ticker label is that company; the validator rejects one the question doesn't ask about.
        ({"ticker": "BAC"}, ["JPM"], {"BAC"}),
        ({"ticker": "NII-gap", "companies": ["JPM", "BAC"]}, _TWO_BANKS, {"JPM", "BAC"}),
        ({"ticker": "MSFT-Dynamics-CRM", "companies": ["MSFT"]}, ["CRM", "MSFT"], {"MSFT"}),
        # Labels are never parsed: any other label means the question's companies.
        ({"ticker": "JPM-NII"}, _TWO_BANKS, {"JPM", "BAC"}),
        ({"ticker": "FY2025"}, ["NVDA"], {"NVDA"}),
        ({"ticker": "NVDA-Q1FY27"}, ["NVDA"], {"NVDA"}),
        ({"ticker": "APPL"}, ["AAPL", "MSFT"], {"AAPL", "MSFT"}),
    ],
)
def test_an_entrys_companies_are_its_own_list_its_ticker_label_or_the_questions(entry, question_tickers, companies):
    assert entry_companies(entry, question_tickers) == companies


def test_a_cross_company_entry_needs_a_claim_from_exactly_those_companies():
    gap = [{"ticker": "NII-gap", "companies": ["JPM", "BAC"], "expected_value": 35.7, "expected_unit": "billion"}]
    assert misattributed(gap, [_attr(["BAC", "JPM"], 35.7)], None, _TWO_BANKS) == []
    # Two JPM figures, or a JPM figure stated as the gap, aren't the gap.
    assert misattributed(gap, [_attr("JPM", 35.7)], None, _TWO_BANKS) == ["NII-gap (35.7 billion)"]


def test_a_non_ticker_label_on_a_one_company_question_is_that_companys():
    periods = [{"ticker": "FY2025", "expected_value": 182.4, "expected_unit": "billion"}]
    assert misattributed(periods, [_attr("JPM", 182.4)], None, ["JPM"]) == []
    assert misattributed(periods, [_attr("BAC", 182.4)], None, ["JPM"]) == ["FY2025 (182.4 billion)"]


def test_the_question_tolerance_widens_the_attribution_match():
    near = [_attr("JPM", 185.0), _attr("BAC", 101.9)]
    assert misattributed(_BANKS, near, None, _TWO_BANKS) == ["JPM (182.4 billion)"]
    assert misattributed(_BANKS, near, 0.02, _TWO_BANKS) == []


def test_a_trap_value_is_charged_to_the_default_ticker_unless_it_names_one():
    trap = [{"value": 107.4, "unit": "billion"}]
    assert forbidden_hits(trap, [_attr("TGT", 107.4)], "TGT", None) == ["TGT (107.4 billion)"]
    assert forbidden_hits(trap, [_attr("WMT", 107.4)], "TGT", None) == []
    named = [{"value": 107.4, "unit": "billion", "ticker": "WMT"}]
    assert forbidden_hits(named, [_attr("WMT", 107.4)], "TGT", None) == ["WMT (107.4 billion)"]
    assert forbidden_hits(named, [_attr("TGT", 107.4)], "TGT", None) == []


@pytest.mark.parametrize("tickers", [[], ["TGT", "WMT"]], ids=["no-company", "mixed-companies"])
def test_only_a_claim_from_the_charged_company_alone_hits_a_trap(tickers):
    assert forbidden_hits([{"value": 107.4, "unit": "billion"}], [_attr(tickers, 107.4)], "TGT", None) == []
