"""Unit tests for eval/questions.py: the question-file schema and the
load-time checks that run before any quota is spent."""

import json

import pytest

from sec_agent.config import QUESTIONS_PATH
from sec_agent.eval.questions import question_tickers, single_ticker, validate_questions

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


def test_a_one_item_tickers_list_is_the_default_trap_ticker():
    question = _numeric(forbidden_values=[{"value": 1.0, "unit": "billion"}])
    question["tickers"] = [question.pop("ticker")]
    validate_questions([question])


def test_a_trap_value_whose_match_band_overlaps_the_expected_values_is_rejected():
    # 179.0 is outside 1% of 182.4, but an answer of 180.6 is within 1% of both.
    with pytest.raises(ValueError, match=r"'q1' at \$\.forbidden_values\[0\]: 179\.0 billion overlaps"):
        validate_questions([_numeric(forbidden_values=[{"value": 179.0, "unit": "billion"}])])
    validate_questions([_numeric(forbidden_values=[{"value": 178.0, "unit": "billion"}])])
    with pytest.raises(ValueError, match="overlaps the grading tolerance"):
        validate_questions(
            [_numeric(forbidden_values=[{"value": 178.0, "unit": "billion"}], tolerance=0.02, tolerance_note="n")]
        )


def _bank_comparison(**extra) -> dict:
    question = _numeric(
        type="comparison",
        expected=[
            {"ticker": "JPM", "expected_value": 182.4, "expected_unit": "billion"},
            {"ticker": "BAC-net-revenue", "companies": ["BAC"], "expected_value": 101.9, "expected_unit": "billion"},
        ],
        **extra,
    )
    del question["expected_value"], question["expected_unit"], question["ticker"]
    question["tickers"] = ["JPM", "BAC"]
    return question


def test_a_trap_value_is_checked_against_its_own_companys_entries_only():
    with pytest.raises(ValueError, match="overlaps the grading tolerance of the expected 101.9 billion"):
        validate_questions([_bank_comparison(forbidden_values=[{"value": 101.5, "unit": "billion", "ticker": "BAC"}])])
    # BAC's value claimed for JPM is the swap a trap exists to catch.
    validate_questions([_bank_comparison(forbidden_values=[{"value": 101.9, "unit": "billion", "ticker": "JPM"}])])


def test_an_expected_value_of_unknown_company_is_checked_against_every_trap():
    # Asked about two banks, the expected value could be either one's.
    question = _numeric(forbidden_values=[{"value": 182.0, "unit": "billion", "ticker": "BAC"}])
    question["tickers"] = ["JPM", "BAC"]
    del question["ticker"]
    with pytest.raises(ValueError, match="overlaps the grading tolerance of the expected 182.4 billion"):
        validate_questions([question])


@pytest.mark.parametrize(
    "names, tickers, single",
    [
        ({"ticker": "JPM"}, ["JPM"], "JPM"),
        ({"tickers": ["JPM"]}, ["JPM"], "JPM"),
        ({"tickers": ["JPM", "BAC"]}, ["BAC", "JPM"], None),
        ({"ticker": "JPM", "tickers": ["JPM", "BAC"]}, ["BAC", "JPM"], None),
        ({"ticker": "JPM", "tickers": ["JPM"]}, ["JPM"], "JPM"),
    ],
)
def test_a_questions_companies_are_named_across_both_fields(names, tickers, single):
    assert (question_tickers(names), single_ticker(names)) == (tickers, single)


def test_an_entrys_companies_must_be_known_tickers():
    question = _bank_comparison()
    question["expected"][1]["companies"] = ["BofA"]
    with pytest.raises(ValueError, match=r"at \$\.expected\[1\]\.companies\[0\]: 'BofA'"):
        validate_questions([question])


def test_a_ticker_label_cannot_name_other_companies():
    question = _bank_comparison()
    question["expected"][0]["companies"] = ["JPM"]
    validate_questions([question])
    for other in (["BAC"], ["JPM", "BAC"]):
        question["expected"][0]["companies"] = other
        with pytest.raises(ValueError, match=r"at \$\.expected\[0\]: label 'JPM' is a ticker, but companies names"):
            validate_questions([question])


@pytest.mark.parametrize(
    "entry",
    [
        {"ticker": "TGT", "expected_value": 1.0, "expected_unit": "billion"},
        {"ticker": "TGT-net-revenue", "companies": ["TGT"], "expected_value": 1.0, "expected_unit": "billion"},
    ],
)
def test_an_entrys_companies_must_be_the_questions_own(entry):
    question = _bank_comparison()
    question["expected"].append(entry)
    with pytest.raises(ValueError, match=r"at \$\.expected\[2\]: TGT is not one of the question's companies"):
        validate_questions([question])


def test_a_trap_must_name_a_known_ticker():
    question = _bank_comparison(forbidden_values=[{"value": 80.5, "unit": "billion", "ticker": "BofA"}])
    with pytest.raises(ValueError, match=r"at \$\.forbidden_values\[0\]\.ticker: 'BofA'"):
        validate_questions([question])


def test_a_trap_is_not_checked_against_a_cross_company_entry():
    # A correct gap claim cites both banks, so it can never hit a JPM-only trap.
    question = _bank_comparison(**V2_TAGS, forbidden_values=[{"value": 80.5, "unit": "billion", "ticker": "JPM"}])
    question["expected"].append({"ticker": "NII-gap", "expected_value": 80.5, "expected_unit": "billion"})
    validate_questions([question])


def _growth(**extra) -> dict:
    """Year-over-year growth, from two anchored revenue figures."""
    return {
        "operation": "percent_change",
        "a": {"value": 177.6, "unit": "billion", "part": "revenue-2024"},
        "b": {"value": 182.4, "unit": "billion", "part": "revenue-2025"},
        **extra,
    }


def _average_of_two() -> dict:
    """(x + y) / 2: a nested step, then an unanchored constant."""
    return {
        "operation": "divide",
        "a": {"derivation": {"operation": "add",
                             "a": {"value": 177.6, "unit": "billion", "part": "revenue-2024"},
                             "b": {"value": 182.4, "unit": "billion", "part": "revenue-2025"}}},
        "b": {"value": 2, "unit": "raw", "constant": True},
    }


@pytest.mark.parametrize("derivation", [_growth(), _average_of_two()])
def test_a_derivation_validates_on_a_numeric_question_and_on_an_entry(derivation):
    validate_questions([_numeric(derivation=derivation)])
    question = _bank_comparison()
    question["expected"][0]["derivation"] = derivation
    validate_questions([question])


@pytest.mark.parametrize(
    "derivation, fragment",
    [
        (_growth(operation="modulo"), "modulo"),
        ({k: v for k, v in _growth().items() if k != "b"}, "'b' is a required property"),
        (_growth(b={"value": 182.4, "unit": "billion", "part": "p", "constant": True}), "derivation.b"),
        (_growth(b={"value": 182.4, "unit": "billion"}), "derivation.b"),
        (_growth(b={"derivation": _growth(), "value": 1.0}), "derivation.b"),
        (_growth(b={"value": 182.4, "unit": "billion", "constant": False}), "derivation.b"),
    ],
)
def test_a_malformed_derivation_is_rejected(derivation, fragment):
    with pytest.raises(ValueError) as e:
        validate_questions([_numeric(derivation=derivation)])
    assert fragment in str(e.value)


def test_a_unit_typo_is_rejected_wherever_a_unit_appears():
    with pytest.raises(ValueError, match=r"at \$\.expected_unit: 'bilion'"):
        validate_questions([_numeric(expected_unit="bilion")])
    question = _bank_comparison()
    question["expected"][0]["expected_unit"] = "bilion"
    with pytest.raises(ValueError, match=r"at \$\.expected\[0\]\.expected_unit: 'bilion'"):
        validate_questions([question])
    with pytest.raises(ValueError, match=r"at \$\.forbidden_values\[0\]\.unit: 'bilion'"):
        validate_questions([_numeric(forbidden_values=[{"value": 1.0, "unit": "bilion"}])])
    with pytest.raises(ValueError, match=r"at \$\.derivation\.b: .*'bilion'|at \$\.derivation\.b\.unit"):
        validate_questions([_numeric(derivation=_growth(b={"value": 182.4, "unit": "bilion", "part": "p"}))])


def _never_disclosed(**extra) -> dict:
    return {"id": "nd", "ticker": "AAPL", "question": "How many iPhones did Apple sell in fiscal 2025?",
            "type": "refusal", "refusal_kind": "never_disclosed", **extra}


def test_a_never_disclosed_refusal_must_record_its_absence_terms():
    with pytest.raises(ValueError, match="'nd'.*absence_terms"):
        validate_questions([_never_disclosed()])
    with pytest.raises(ValueError, match="absence_terms"):
        validate_questions([_never_disclosed(absence_terms=[])])
    validate_questions([_never_disclosed(absence_terms=["units sold", "iPhone units"])])


def test_absence_terms_belong_to_refusals_only():
    with pytest.raises(ValueError, match=r"'q1' at \$\.absence_terms: only a refusal question"):
        validate_questions([_numeric(absence_terms=["units sold"])])
    validate_questions([{"id": "r", "ticker": "XOM", "question": "q", "type": "refusal",
                         "refusal_kind": "not_yet_filed", "absence_terms": ["2030"]}])


def test_a_top_level_derivation_belongs_to_a_numeric_question_only():
    question = {"id": "t", "ticker": "CAT", "question": "q", "type": "text", "accepted": ["x"], "derivation": _growth()}
    with pytest.raises(ValueError, match=r"'t' at \$\.derivation: only a numeric question"):
        validate_questions([question])
