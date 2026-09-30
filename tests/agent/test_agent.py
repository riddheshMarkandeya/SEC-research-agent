"""
Unit tests for agent.py. Covers the pure helpers, plus the
call_get_financial_fact/call_compare_financial_metric dispatch/
boundary-validation logic (via monkeypatched xbrl_facts functions, no
network). run_agent()'s actual model-facing behavior drives a live
tool-calling loop against the selected backend (see llm_backends.py),
so THAT is exercised by manual runs (python -m sec_agent.agent.agent "...") and
tests/manual/, not here -- but run_agent()'s own loop CONTROL FLOW (how it reacts to a
scripted sequence of ModelTurns) is deterministic and doesn't need a
live model, so a few targeted regression tests below drive it through
monkeypatched BACKENDS entries instead.
"""

from contextlib import contextmanager
from typing import cast

import pytest

from sec_agent.agent.agent import (
    CHUNKS_PER_SEARCH,
    AgentResult,
    call_calculate,
    _calculation_as_result,
    _partition_submit_call,
    _dispatch_tool_call,
    _finalize_answer,
    _format_claim_retry_message,
    _format_refusal_message,
    _resolve_search_args,
    _should_force_final_submit,
    _should_retry_for_citations,
    run_search,
    submission_warnings,
    run_agent,
)
from sec_agent.agent.citations import CitationWarning, _quote_matches, verify_claims
from sec_agent.agent.tool_results import _format_results_block
from sec_agent.llm import llm_backends
from tests.agent.helpers import _fake_result, _valid_calculate_args, _valid_submitted_claim, capture_events
from sec_agent.llm.llm_backends import ModelTurn
from sec_agent.prompts.agent_messages import (
    CITATION_RETRY_GUIDANCE,
    FINAL_TURN_SUBMIT_MESSAGE,
    NO_SUBMISSION_REFUSAL,
    NO_SUBMISSION_WARNING,
    SEARCH_INVALID_ARGS_MESSAGE,
)
from sec_agent.prompts.agent_system import SYSTEM_PROMPT
from sec_agent.prompts.agent_tools import (
    AGENT_TOOL_SCHEMAS,
    CALCULATE_TOOL_SCHEMA,
    COMPARE_TOOL_SCHEMA,
    FACT_TOOL_SCHEMA,
    SEARCH_TOOL_SCHEMA,
    SUBMIT_TOOL_SCHEMA,
)


# ---------------------------------------------------------------------------
# _resolve_search_args
# ---------------------------------------------------------------------------
def test_resolve_search_args_uses_model_query_on_retry_against_same_ticker():
    # "CRM" is already in searched_tickers, so this counts as a retry —
    # the model's own query is trusted.
    query, ticker = _resolve_search_args(
        {"query": "RPO", "ticker": "CRM"}, fallback_query="fallback", searched_tickers={"CRM"}
    )
    assert query == "RPO"
    assert ticker == "CRM"


def test_resolve_search_args_ignores_model_query_on_first_search_against_a_ticker():
    # This is the regression case: testing showed the model's own
    # first-pass query text (too vague or too literal, depending on how
    # that company's filings happen to phrase things) was the direct
    # cause of two eval failures. The first search against a not-yet-
    # searched ticker must use the original question regardless of what
    # query the model supplied, even when it supplied a "reasonable"
    # looking one.
    query, ticker = _resolve_search_args(
        {"query": "effective tax rate Q4 2025", "ticker": "MSFT"},
        fallback_query="original question",
        searched_tickers=set(),
    )
    assert query == "original question"
    assert ticker == "MSFT"


def test_resolve_search_args_falls_back_when_query_missing_even_on_retry():
    # This is the real behavior observed from qwen2.5:7b-instruct: it
    # sometimes calls the tool with only `ticker`, no `query`, despite
    # `query` being schema-required.
    query, ticker = _resolve_search_args(
        {"ticker": "CRM"}, fallback_query="original question", searched_tickers={"CRM"}
    )
    assert query == "original question"
    assert ticker == "CRM"


def test_resolve_search_args_ticker_is_none_when_absent():
    query, ticker = _resolve_search_args(
        {"query": "something"}, fallback_query="fallback", searched_tickers={"something-else"}
    )
    assert ticker is None


def test_resolve_search_args_empty_args_falls_back_entirely():
    query, ticker = _resolve_search_args({}, fallback_query="original question", searched_tickers=set())
    assert query == "original question"
    assert ticker is None


# ---------------------------------------------------------------------------
# call_calculate() (2026-09-11) -- the two guarantees the calculate tool
# provides: operand GROUNDING (each operand must actually appear in its
# cited source, via the same _number_candidates() primitive
# _verify_one_claim already uses) and arithmetic CORRECTNESS (the
# operation runs in real Python, never trusted from the model). Returns
# (result_dict, None) on success, (None, error_message) on failure --
# richer than call_get_financial_fact's bare dict|None because calculate
# has several distinct failure reasons that each need their own specific,
# actionable message.
# ---------------------------------------------------------------------------
def test_call_calculate_percent_of():
    all_results = [
        _fake_result(text="R&D expense was $34,550 million for fiscal year 2025."),
        _fake_result(text="Gross profit was $195,201 million for fiscal year 2025."),
    ]
    result, error = call_calculate(_valid_calculate_args(), all_results)
    assert error is None
    assert result == {"value": 17.7, "unit": "percent"}


def test_call_calculate_percent_change():
    all_results = [
        _fake_result(text="Revenue was $81,615 million for the current quarter."),
        _fake_result(text="Revenue was $44,062 million for the prior-year quarter."),
    ]
    args = _valid_calculate_args(
        operation="percent_change", operand_a=81615.0, unit_a="million", operand_b=44062.0, unit_b="million"
    )
    result, error = call_calculate(args, all_results)
    assert error is None
    assert result == {"value": 85.2, "unit": "percent"}


def test_call_calculate_add():
    all_results = [
        _fake_result(text="Segment A revenue was $100 million."),
        _fake_result(text="Segment B revenue was $50 million."),
    ]
    args = _valid_calculate_args(operation="add", operand_a=100.0, unit_a="million", operand_b=50.0, unit_b="million")
    result, error = call_calculate(args, all_results)
    assert error is None
    assert result == {"value": 150_000_000.0, "unit": "raw"}


def test_call_calculate_subtract():
    all_results = [
        _fake_result(text="Total assets were $694,228 million."),
        _fake_result(text="Total liabilities were $300,000 million."),
    ]
    args = _valid_calculate_args(
        operation="subtract", operand_a=694228.0, unit_a="million", operand_b=300000.0, unit_b="million"
    )
    result, error = call_calculate(args, all_results)
    assert error is None
    assert result == {"value": 394_228_000_000.0, "unit": "raw"}


def test_call_calculate_multiply():
    all_results = [_fake_result(text="1000 shares outstanding."), _fake_result(text="$50 price per share.")]
    args = _valid_calculate_args(
        operation="multiply", operand_a=1000.0, unit_a="raw", operand_b=50.0, unit_b="raw"
    )
    result, error = call_calculate(args, all_results)
    assert error is None
    assert result == {"value": 50_000.0, "unit": "raw"}


def test_call_calculate_divide_rounds_to_two_decimals_like_formulas_py():
    all_results = [_fake_result(text="Current assets were $150 million."), _fake_result(text="Current liabilities were $100 million.")]
    args = _valid_calculate_args(
        operation="divide", operand_a=150.0, unit_a="million", operand_b=100.0, unit_b="million"
    )
    result, error = call_calculate(args, all_results)
    assert error is None
    assert result == {"value": 1.5, "unit": "raw"}


def test_call_calculate_handles_unit_scale_mismatch_via_normalize():
    # 34550 million and 195.201 billion are the same real quantities as
    # the percent_of test above (195201 million == 195.201 billion) --
    # normalize() must reconcile the scale mismatch before dividing.
    all_results = [
        _fake_result(text="R&D expense was $34,550 million."),
        _fake_result(text="Gross profit was $195.201 billion."),
    ]
    args = _valid_calculate_args(operand_b=195.201, unit_b="billion")
    result, error = call_calculate(args, all_results)
    assert error is None
    assert result == {"value": 17.7, "unit": "percent"}


def test_call_calculate_rejects_divide_by_zero():
    all_results = [_fake_result(text="Value was $100 million."), _fake_result(text="Value was $0 million.")]
    args = _valid_calculate_args(operand_a=100.0, unit_a="million", operand_b=0.0)
    result, error = call_calculate(args, all_results)
    assert result is None
    assert error is not None
    assert "zero" in error.lower()


def test_call_calculate_rejects_divide_by_zero_for_plain_divide_too():
    all_results = [_fake_result(text="Value was $100 million."), _fake_result(text="Value was $0 million.")]
    args = _valid_calculate_args(operation="divide", operand_a=100.0, unit_a="million", operand_b=0.0)
    result, error = call_calculate(args, all_results)
    assert result is None
    assert error is not None
    assert "zero" in error.lower()


def test_call_calculate_rejects_out_of_range_citation_index():
    all_results = [_fake_result(text="R&D expense was $34,550 million.")]
    args = _valid_calculate_args(citation_index_b=5)
    result, error = call_calculate(args, all_results)
    assert result is None
    assert error is not None
    assert "[5]" in error or "5" in error


def test_call_calculate_rejects_operand_not_grounded_in_cited_source():
    all_results = [
        _fake_result(text="R&D expense was $34,550 million."),
        _fake_result(text="Cost of revenue was $60,000 million."),  # doesn't contain 195201
    ]
    result, error = call_calculate(_valid_calculate_args(), all_results)
    assert result is None
    assert error is not None
    assert "operand_b" in error
    assert "[2]" in error


def test_call_calculate_rejects_operand_a_not_grounded_names_it_specifically():
    all_results = [
        _fake_result(text="Cost of revenue was $60,000 million."),  # doesn't contain 34550
        _fake_result(text="Gross profit was $195,201 million."),
    ]
    result, error = call_calculate(_valid_calculate_args(), all_results)
    assert result is None
    assert error is not None
    assert "operand_a" in error
    assert "[1]" in error


def test_call_calculate_operand_wrong_unit_names_the_correct_unit_not_the_value():
    # Regression test for the 2026-09-13 baseline finding (aapl-revenue-
    # growth-q3fy2026): a value mislabeled "billion" that's actually raw
    # got a message blaming the value/citation index, both correct --
    # the model's retry changed neither and failed identically twice.
    # The fixed message must name the UNIT specifically as the problem.
    all_results = [
        _fake_result(text="Revenue was $109,417,000,000."),
        _fake_result(text="Prior-year revenue was $94,036,000,000."),
    ]
    args = _valid_calculate_args(
        operation="percent_change",
        operand_a=109417000000,
        unit_a="billion",
        citation_index_a=1,
        operand_b=94036000000,
        unit_b="raw",
        citation_index_b=2,
    )
    result, error = call_calculate(args, all_results)
    assert result is None
    assert error is not None
    assert "operand_a" in error
    assert "billion" in error.lower()
    assert "raw" in error.lower()
    assert "unit" in error.lower()


def test_call_calculate_operand_wrong_citation_index_names_the_correct_result():
    # Regression guard for a review finding: an earlier version of the
    # terminal message claimed "a different citation index will not
    # help" without ever checking any OTHER already-retrieved result --
    # if the value actually lives in a different result (a plausible
    # citation-index transcription slip), that message would have been
    # false and would have told the model not to bother trying the fix
    # that actually works. operand_a (34550 million) is cited against
    # [1], which doesn't contain it, but genuinely lives in [2].
    all_results = [
        _fake_result(text="Cost of revenue was $60,000 million."),
        _fake_result(text="R&D expense was $34,550 million. Gross profit was $195,201 million."),
    ]
    args = _valid_calculate_args(citation_index_a=1)
    result, error = call_calculate(args, all_results)
    assert result is None
    assert error is not None
    assert "operand_a" in error
    assert "[2]" in error
    assert "citation index" in error.lower()


def test_call_calculate_operand_ungroundable_under_any_unit_says_not_retryable():
    # A literal conversion constant (e.g. 1,000,000,000 to convert to
    # billions) has no citation to ground against at all -- distinct
    # from the mislabeled-unit case above, this is a genuinely terminal
    # failure and the message must say so rather than invite a retry
    # that cannot succeed.
    all_results = [_fake_result(text="Revenue was $4,475,446,000.")]
    args = _valid_calculate_args(
        operation="divide",
        operand_a=4475446000,
        unit_a="raw",
        citation_index_a=1,
        operand_b=1000000000,
        unit_b="raw",
        citation_index_b=1,
    )
    result, error = call_calculate(args, all_results)
    assert result is None
    assert error is not None
    assert "operand_b" in error
    assert "not a retryable mistake" in error.lower() or "not retryable" in error.lower()


def test_call_calculate_rejects_mismatched_categories():
    all_results = [
        _fake_result(text="Growth was 20 percent."),
        _fake_result(text="Revenue was $100 million."),
    ]
    args = _valid_calculate_args(operand_a=20.0, unit_a="percent", operand_b=100.0, unit_b="million")
    result, error = call_calculate(args, all_results)
    assert result is None
    assert error is not None
    assert "percent" in error.lower() and "scale" in error.lower()


def test_call_calculate_rejects_malformed_args_via_schema():
    all_results = [_fake_result(), _fake_result()]
    args = _valid_calculate_args()
    del args["operand_a"]
    result, error = call_calculate(args, all_results)
    assert result is None
    assert error is not None


# ---------------------------------------------------------------------------
# _calculation_as_result() -- wraps a call_calculate() result in the same
# {text, metadata} shape every other all_results entry uses, with `text`
# rendering the full expression so it's directly quotable by
# _quote_matches/_number_candidates (proven end-to-end below, not just
# asserted -- the whole point of this tool is that its output flows
# through verify_claims/_verify_one_claim completely unchanged).
# ---------------------------------------------------------------------------
def test_calculation_as_result_text_is_directly_quotable_end_to_end():
    all_results = [
        _fake_result(text="R&D expense was $34,550 million."),
        _fake_result(text="Gross profit was $195,201 million."),
    ]
    args = _valid_calculate_args()
    calc_result, error = call_calculate(args, all_results)
    assert error is None
    assert calc_result is not None
    entry = _calculation_as_result(calc_result, args)
    assert "17.7" in entry["text"]
    assert "percent" in entry["text"]

    # The whole point: a submit_answer claim citing this new result must
    # pass _verify_one_claim's existing, unchanged pipeline -- no new
    # verification code needed for calculate-sourced claims.
    all_results_with_calc = all_results + [entry]
    claim = {
        "value": 17.7,
        "unit": "percent",
        "citation_index": 3,
        "quote": entry["text"],
    }
    from sec_agent.agent.citations import _verify_one_claim

    assert _verify_one_claim(claim, all_results_with_calc) is None


def test_calculation_as_result_renders_percent_change_as_from_b_to_a():
    # percent_change reads operand_b as the old value and operand_a as the
    # new one, so the expression names them in that order.
    all_results = [
        _fake_result(text="Revenue was $81,615 million for the current quarter."),
        _fake_result(text="Revenue was $44,062 million for the prior-year quarter."),
    ]
    args = _valid_calculate_args(
        operation="percent_change", operand_a=81615.0, unit_a="million", operand_b=44062.0, unit_b="million"
    )
    calc_result, error = call_calculate(args, all_results)
    assert error is None
    assert calc_result is not None

    entry = _calculation_as_result(calc_result, args)

    assert entry["text"] == (
        "percentage change from 44062 million to 81615 million = 85.2 percent "
        "(computed value, not directly stated in any filing; operands from results [1] and [2])"
    )


def test_calculation_as_result_text_avoids_scientific_notation_for_large_values():
    # Found in code review, 2026-09-11: str()'s default formatting
    # switches to scientific notation ("1e+18") outside roughly
    # 1e16..1e-4, but NUMBER_PATTERN (numeric_utils.py) has no exponent
    # support -- a value in that range could never be re-extracted from
    # the very citation text this function generates, so a correct,
    # tool-computed value would be refused as ungrounded by the exact
    # gate this tool exists to satisfy. multiply of two billion-scale
    # operands is a realistic way to reach this range (e.g. a
    # shares-times-price-style question with unusually large operands).
    all_results = [
        _fake_result(text="Value A is 1 billion."),
        _fake_result(text="Value B is 1 billion."),
    ]
    args = _valid_calculate_args(
        operation="multiply", operand_a=1.0, unit_a="billion", operand_b=1.0, unit_b="billion"
    )
    calc_result, error = call_calculate(args, all_results)
    assert error is None
    assert calc_result is not None
    assert calc_result["value"] == 1e18  # sanity check on the premise

    entry = _calculation_as_result(calc_result, args)
    assert "e+" not in entry["text"].lower()
    assert "1000000000000000000" in entry["text"]

    # The real-world consequence: a claim citing this result must still
    # verify, the same end-to-end proof as the percent_of test above.
    all_results_with_calc = all_results + [entry]
    claim = {"value": 1e18, "unit": "raw", "citation_index": 3, "quote": entry["text"]}
    from sec_agent.agent.citations import _verify_one_claim

    assert _verify_one_claim(claim, all_results_with_calc) is None


def test_calculation_as_result_has_metadata_required_by_format_results_block():
    all_results = [
        _fake_result(text="R&D expense was $34,550 million."),
        _fake_result(text="Gross profit was $195,201 million."),
    ]
    args = _valid_calculate_args()
    calc_result, _ = call_calculate(args, all_results)
    assert calc_result is not None
    entry = _calculation_as_result(calc_result, args)
    # _format_results_block reads meta['ticker']/['form']/['reportDate'] --
    # a KeyError here would only surface live, the first time a
    # calculate result is ever rendered back to the model.
    block = _format_results_block([entry], 3)
    assert "[3]" in block


def test_dispatch_no_data_reply_names_the_converted_year_and_logs_once(monkeypatch):
    events = []
    capture_events(monkeypatch, events)
    monkeypatch.setattr("sec_agent.agent.fact_tools.get_ratio", lambda *a, **k: None)
    call = {"name": "get_financial_fact", "args": {"ticker": "NVDA", "metric": "gross_margin", "fiscal_year": "2025"}}

    content = _dispatch_tool_call(call, "q", [], set(), verbose=False)

    assert "'FY' FY2025" in content
    assert "FY'2025'" not in content
    assert [c for c, _ in events].count("tool_arg_coerced") == 1
# ---------------------------------------------------------------------------
# _dispatch_tool_call
# ---------------------------------------------------------------------------
def test_dispatch_tool_call_get_financial_fact_appends_result(monkeypatch):
    fact = {
        "value": 71.1,
        "unit": "percent",
        "form": "10-K",
        "filed": "2026-06-20",
        "period_end": "2026-03-31",
        "accession": "0001234567-26-000123",
    }
    monkeypatch.setattr("sec_agent.agent.agent.call_get_financial_fact", lambda args, question=None: fact)
    all_results = []
    call = {"name": "get_financial_fact", "args": {"ticker": "NVDA", "metric": "gross_margin"}}

    content = _dispatch_tool_call(call, "q", all_results, set(), verbose=False)

    assert len(all_results) == 1
    assert all_results[0]["metadata"]["ticker"] == "NVDA"
    assert "[1]" in content


def test_dispatch_tool_call_get_financial_fact_none_uses_no_fact_message(monkeypatch):
    monkeypatch.setattr("sec_agent.agent.agent.call_get_financial_fact", lambda args, question=None: None)
    monkeypatch.setattr("sec_agent.agent.agent._format_no_fact_message", lambda args: "NO FACT MESSAGE")
    all_results = []
    call = {"name": "get_financial_fact", "args": {"ticker": "NVDA", "metric": "gross_margin"}}

    content = _dispatch_tool_call(call, "q", all_results, set(), verbose=False)

    assert all_results == []
    assert content == "NO FACT MESSAGE"


def test_dispatch_tool_call_calculate_appends_result():
    all_results = [
        _fake_result(text="R&D expense was $34,550 million."),
        _fake_result(text="Gross profit was $195,201 million."),
    ]
    call = {"name": "calculate", "args": _valid_calculate_args()}

    content = _dispatch_tool_call(call, "q", all_results, set(), verbose=False)

    assert len(all_results) == 3
    assert all_results[2]["metadata"]["chunk_index"] == "calculated"
    assert "[3]" in content
    assert "17.7" in content


def test_dispatch_tool_call_calculate_failure_uses_error_message_no_mutation():
    all_results = [_fake_result(text="R&D expense was $34,550 million.")]
    # citation_index_b=5 is out of range against a 1-result all_results.
    call = {"name": "calculate", "args": _valid_calculate_args(citation_index_b=5)}

    content = _dispatch_tool_call(call, "q", all_results, set(), verbose=False)

    assert len(all_results) == 1  # unchanged -- no phantom entry on failure
    assert "5" in content


def test_dispatch_tool_call_compare_financial_metric_appends_results(monkeypatch):
    data = {
        "AAPL": {
            "value": 40.0,
            "unit": "percent",
            "form": "10-K",
            "filed": "2026-06-20",
            "period_end": "2026-03-31",
            "accession": "acc-1",
        }
    }
    monkeypatch.setattr("sec_agent.agent.agent.call_compare_financial_metric", lambda args, question=None: data)
    all_results = []
    call = {"name": "compare_financial_metric", "args": {"metric": "gross_margin"}}

    content = _dispatch_tool_call(call, "q", all_results, set(), verbose=False)

    assert len(all_results) == 1
    assert "[1]" in content


def test_dispatch_tool_call_compare_financial_metric_empty_uses_no_comparison_message(monkeypatch):
    monkeypatch.setattr("sec_agent.agent.agent.call_compare_financial_metric", lambda args, question=None: {})
    monkeypatch.setattr("sec_agent.agent.agent._format_no_comparison_message", lambda args: "NO COMPARISON MESSAGE")
    all_results = []
    call = {"name": "compare_financial_metric", "args": {"metric": "gross_margin"}}

    content = _dispatch_tool_call(call, "q", all_results, set(), verbose=False)

    assert content == "NO COMPARISON MESSAGE"


def test_dispatch_tool_call_search_filings_uses_resolved_query_and_tracks_ticker(monkeypatch):
    fake_results = [
        {
            "text": "chunk text",
            "metadata": {
                "ticker": "AAPL",
                "form": "10-K",
                "filingDate": "2026-01-01",
                "reportDate": "2025-12-31",
                "accessionNumber": "acc-1",
                "chunk_index": 0,
            },
        }
    ]
    captured = {}

    def fake_hybrid_search(query, ticker, top_k):
        captured["query"] = query
        captured["ticker"] = ticker
        return fake_results

    monkeypatch.setattr("sec_agent.agent.agent.hybrid_search", fake_hybrid_search)
    all_results = []
    searched_tickers = set()
    # ticker not yet in searched_tickers -> _resolve_search_args ignores
    # the model's own query and uses the fallback question instead
    call = {"name": "search_filings", "args": {"query": "employees", "ticker": "AAPL"}}

    content = _dispatch_tool_call(call, "how many employees", all_results, searched_tickers, verbose=False)

    assert captured["query"] == "how many employees"
    assert captured["ticker"] == "AAPL"
    assert all_results == fake_results
    assert "AAPL" in searched_tickers
    assert "[1]" in content


def test_dispatch_tool_call_search_filings_rejects_unrecognized_ticker(monkeypatch):
    # review §12: unlike call_get_financial_fact/call_compare_financial_metric,
    # search_filings never validated a provided ticker -- a hallucinated
    # ticker silently fell through to hybrid_search with no rejection or
    # telemetry signal, unlike every other schema-violation case in this
    # module.
    monkeypatch.setattr(
        "sec_agent.agent.agent.hybrid_search", lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not be called"))
    )
    calls = []
    capture_events(monkeypatch, calls)
    all_results = []
    call = {"name": "search_filings", "args": {"query": "revenue", "ticker": "NOTREAL"}}

    content = _dispatch_tool_call(call, "q", all_results, set(), verbose=False)

    assert "NOTREAL" in content
    assert all_results == []
    assert len(calls) == 1
    category, fields = calls[0]
    assert category == "tool_call_rejected"
    assert fields["reason"] == "ticker_not_in_enum"


def test_dispatch_tool_call_search_filings_rejects_non_hashable_ticker_without_crashing(monkeypatch):
    # Found in code review (round 2, 2026-09-10): the §12 fix's guard
    # ran AFTER _resolve_search_args(), which already crashes first on
    # `ticker not in searched_tickers` (a set) for a non-hashable ticker
    # like a list -- the exact same unhashable-ticker crash class
    # get_financial_fact/compare_financial_metric were already fixed
    # for on 2026-09-06, just never closed for search_filings.
    monkeypatch.setattr(
        "sec_agent.agent.agent.hybrid_search", lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not be called"))
    )
    calls = []
    capture_events(monkeypatch, calls)
    call = {"name": "search_filings", "args": {"query": "revenue", "ticker": ["AAPL"]}}

    content = _dispatch_tool_call(call, "q", [], set(), verbose=False)

    assert len(calls) == 1
    category, fields = calls[0]
    assert category == "tool_call_rejected"
    assert fields["reason"] == "ticker_wrong_type"
    assert "not a recognized company" in content


def test_dispatch_tool_call_search_filings_rejects_other_invalid_args_generically(monkeypatch):
    # Only a bad ticker gets the tailored message; any other schema
    # violation (here an invented `segment` filter) gets the generic one.
    monkeypatch.setattr(
        "sec_agent.agent.agent.hybrid_search", lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not be called"))
    )
    capture_events(monkeypatch, [])
    call = {"name": "search_filings", "args": {"query": "revenue", "segment": "cloud"}}

    content = _dispatch_tool_call(call, "q", [], set(), verbose=False)

    assert content == SEARCH_INVALID_ARGS_MESSAGE


def test_dispatch_tool_call_search_filings_allows_no_ticker_filter(monkeypatch):
    # ticker is optional for this tool (a broad, unsure search) -- must
    # NOT be rejected just for being absent.
    monkeypatch.setattr("sec_agent.agent.agent.hybrid_search", lambda query, ticker, top_k: [])
    calls = []
    capture_events(monkeypatch, calls)
    call = {"name": "search_filings", "args": {"query": "revenue"}}

    _dispatch_tool_call(call, "q", [], set(), verbose=False)

    assert calls == []


# ---------------------------------------------------------------------------
# _should_retry_for_citations / _format_claim_retry_message
# (citation-verification retry loop, revisited Week 5j -> 2026-08-24 --
# see PROJECT_CONTEXT.md and docs/plans/2026-08-24-citation-
# retry-loop-design.md)
# ---------------------------------------------------------------------------
def test_should_retry_for_citations_true_with_warnings_and_not_yet_retried():
    assert (
        _should_retry_for_citations(["[1] claims 6478.0 (million) ..."], already_retried=False)
        is True
    )


def test_should_retry_for_citations_false_once_already_retried():
    assert (
        _should_retry_for_citations(["[1] claims 6478.0 (million) ..."], already_retried=True)
        is False
    )


def test_should_retry_for_citations_false_with_no_warnings_regardless_of_retried_flag():
    assert _should_retry_for_citations([], already_retried=False) is False
    assert _should_retry_for_citations([], already_retried=True) is False

# ---------------------------------------------------------------------------
# _should_force_final_submit (final-turn safety net for the
# MAX_TOOL_ITERATIONS zero-slack bug -- BACKLOG.md, docs/decisions/
# 2026-09-16-final-turn-safety-net.md)
# ---------------------------------------------------------------------------
def test_should_force_final_submit_true_when_budget_exhausted_and_not_yet_attempted():
    assert _should_force_final_submit(already_attempted=False, calls_made=6) is True


def test_should_force_final_submit_false_once_already_attempted():
    assert _should_force_final_submit(already_attempted=True, calls_made=6) is False


def test_should_force_final_submit_false_when_budget_not_yet_exhausted():
    assert _should_force_final_submit(already_attempted=False, calls_made=5) is False

def _repeating_backend(fake_start):
    """A BACKENDS entry whose every later turn (tool results, forced
    follow-ups, retries) repeats fake_start's own turn -- for tests that
    only care how the loop finalizes a model that keeps saying the same
    thing."""

    first_turn = []

    def start(question, system_prompt, tool_schemas):
        state, turn = fake_start(question, system_prompt, tool_schemas)
        first_turn.append(turn)
        return state, turn

    def repeat(*_args, **_kwargs):
        return first_turn[0]

    return start, repeat, repeat


# ---------------------------------------------------------------------------
# run_agent() -- loop control flow only, via a fake/scripted backend (see
# module docstring for why this is fair game for a unit test despite
# run_agent() otherwise being live-only)
# ---------------------------------------------------------------------------
def test_run_agent_sends_the_system_prompt_and_tool_schemas_in_order(monkeypatch):
    # Pins what the model is actually given at conversation start --
    # the exact SYSTEM_PROMPT object and the five schemas in the order
    # Gemini receives them -- so a prompt/schema move or reorder can't
    # silently change the model's input without this failing.
    captured = {}

    def fake_start(question, system_prompt, tool_schemas):
        captured["system_prompt"] = system_prompt
        captured["tool_schemas"] = tool_schemas
        return {}, ModelTurn(tool_calls=[], text="done")

    monkeypatch.setattr("sec_agent.agent.agent.BACKENDS", {"gemini": _repeating_backend(fake_start)})

    run_agent("What was Apple's revenue?", backend="gemini")

    assert captured["system_prompt"] is SYSTEM_PROMPT
    assert captured["tool_schemas"] == list(AGENT_TOOL_SCHEMAS)
    assert list(AGENT_TOOL_SCHEMAS) == [
        FACT_TOOL_SCHEMA, COMPARE_TOOL_SCHEMA, SEARCH_TOOL_SCHEMA, CALCULATE_TOOL_SCHEMA, SUBMIT_TOOL_SCHEMA
    ]


# ---------------------------------------------------------------------------
# citation hard-gate (Week 7): run_agent() must refuse, not just warn, when
# citation verification still fails after any applicable retry
# ---------------------------------------------------------------------------
def test_run_agent_refuses_a_text_answer_given_again_after_forcing(monkeypatch):
    # A text reply gets one forced submit_answer turn; text again means
    # there's nothing structured to verify, so the answer is refused with
    # the no-submission wording and the text kept for FP analysis.
    text_turn = ModelTurn(tool_calls=[], text="Apple's revenue was $100 billion [1].")
    followups = []

    def fake_start(question, system_prompt, tool_schemas):
        return {}, text_turn

    def fake_send_followup(state, text, force_tool=None):
        followups.append(force_tool)
        return text_turn

    log_calls = []
    capture_events(monkeypatch, log_calls)
    monkeypatch.setattr("sec_agent.agent.agent.BACKENDS", {"gemini": (fake_start, None, fake_send_followup)})

    answer, all_results, warnings, withheld_answer, details = run_agent("What was Apple's revenue?", backend="gemini")

    assert followups == ["submit_answer"]
    assert answer == NO_SUBMISSION_REFUSAL
    assert warnings == [NO_SUBMISSION_WARNING]
    assert [d["check"] for d in details] == ["no_submission"]
    assert withheld_answer == "Apple's revenue was $100 billion [1]."
    [refused] = [fields for category, fields in log_calls if category == "citation_gate_refused"]
    assert refused["checks"] == {"no_submission": 1}


def test_run_agent_forces_submit_on_a_text_answer_at_the_budget_edge(monkeypatch):
    # The start turn already uses the whole budget, but the one reserved
    # final round trip is unspent, so the text still gets its forced
    # submit_answer turn -- here the model then submits.
    monkeypatch.setattr("sec_agent.agent.agent.MAX_TOOL_ITERATIONS", 1)
    followups = []

    def fake_start(question, system_prompt, tool_schemas):
        return {}, ModelTurn(tool_calls=[], text="Revenue was $100 billion.")

    def fake_send_followup(state, text, force_tool=None):
        followups.append(force_tool)
        return _submit_turn(answer_text="Revenue was $100 billion.")

    log_calls = []
    capture_events(monkeypatch, log_calls)
    monkeypatch.setattr("sec_agent.agent.agent.BACKENDS", {"gemini": (fake_start, None, fake_send_followup)})
    monkeypatch.setattr("sec_agent.agent.agent.verify_claims", lambda *a: [])

    answer, all_results, warnings, withheld_answer, _ = run_agent("What was Apple's revenue?", backend="gemini")

    assert followups == ["submit_answer"]
    assert answer == "Revenue was $100 billion."
    assert withheld_answer is None
    # Spending the reserve is logged like the pending-tool path's, with
    # no pending tools.
    [forced] = [fields for category, fields in log_calls if category == "final_turn_forced"]
    assert forced == {"backend": "gemini", "calls_made": 1, "pending_tools": []}


def test_run_agent_refuses_a_text_answer_once_the_final_turn_is_spent(monkeypatch):
    # Budget exhausted with a tool call pending: the reserved final turn
    # forces submit_answer, the model answers in text anyway, and there's
    # nothing left to force with, so the text is refused straight away.
    monkeypatch.setattr("sec_agent.agent.agent.MAX_TOOL_ITERATIONS", 1)
    text_turn = ModelTurn(tool_calls=[], text="Revenue was $100 billion.")

    def fake_start(question, system_prompt, tool_schemas):
        return {}, ModelTurn(tool_calls=[{"name": "search_filings", "args": {}}], text=None)

    monkeypatch.setattr(
        "sec_agent.agent.agent.BACKENDS", {"gemini": (fake_start, lambda state, results, force_tool=None: text_turn, None)}
    )

    answer, all_results, warnings, withheld_answer, details = run_agent(
        "What was Apple's revenue?", backend="gemini", verbose=True
    )

    assert answer == NO_SUBMISSION_REFUSAL
    assert [d["check"] for d in details] == ["no_submission"]
    assert withheld_answer == "Revenue was $100 billion."


def test_run_agent_text_after_forcing_regates_a_submission_cached_by_the_retry(monkeypatch):
    # submit (claims fail) -> retry -> the model answers in text, is
    # forced, answers in text again. Its earlier submission is still its
    # last verifiable answer, so that is re-gated rather than refusing
    # with no_submission -- here it now passes.
    text_turn = ModelTurn(tool_calls=[], text="Let me restate: the value was 100.")

    def fake_start(question, system_prompt, tool_schemas):
        return {}, _submit_turn(answer_text="The value was 100.")

    monkeypatch.setattr(
        "sec_agent.agent.agent.BACKENDS",
        {"gemini": (fake_start, lambda state, results, force_tool=None: text_turn, lambda *a, **k: text_turn)},
    )
    verify_calls = []

    def fake_verify_claims(claims, all_results, question, answer_text):
        verify_calls.append(answer_text)
        if len(verify_calls) == 1:
            return [CitationWarning(check="quote_not_found", citation_index=1, value=100.0, unit="raw", message="bad", quote=None)]
        return []

    monkeypatch.setattr("sec_agent.agent.agent.verify_claims", fake_verify_claims)

    answer, all_results, warnings, withheld_answer, _ = run_agent("What was the value?", backend="gemini")

    assert verify_calls == ["The value was 100.", "The value was 100."]
    assert answer == "The value was 100."
    assert warnings == []
    assert withheld_answer is None


def test_run_agent_returns_generic_timeout_message_unchanged_when_iterations_exhausted(monkeypatch):
    # The iteration-budget-exhausted fallback (no cached submission to
    # fall back to) always passes warnings=[] into _finalize_answer(), so this
    # locks in that routing it through the same choke point as every
    # other return site (code review, 2026-08-26) is a genuine no-op --
    # the generic message must still come back completely unchanged.
    monkeypatch.setattr("sec_agent.agent.agent.MAX_TOOL_ITERATIONS", 1)

    keeps_calling_tools = ModelTurn(tool_calls=[{"name": "search_filings", "args": {}}], text=None)

    def fake_start(question, system_prompt, tool_schemas):
        return {}, keeps_calling_tools

    monkeypatch.setattr("sec_agent.agent.agent.BACKENDS", {"gemini": _repeating_backend(fake_start)})

    answer, all_results, warnings, withheld_answer, _ = run_agent("What was Apple's revenue?", backend="gemini")

    assert answer == (
        "I wasn't able to finish answering within the allotted number of searches. "
        "Try asking a more specific or narrower question."
    )
    assert warnings == []
    assert withheld_answer is None


# ---------------------------------------------------------------------------
# Final-turn safety net (BACKLOG.md's MAX_TOOL_ITERATIONS zero-slack bug --
# docs/decisions/2026-09-16-final-turn-safety-net.md): when the dispatch budget
# is exhausted but the model is still actively requesting tool calls (not
# yet given up), the loop spends one reserved, submit-only round trip
# instead of immediately falling through to the generic timeout.
# ---------------------------------------------------------------------------
def test_run_agent_final_turn_safety_net_rescues_a_clean_refusal(monkeypatch):
    monkeypatch.setattr("sec_agent.agent.agent.MAX_TOOL_ITERATIONS", 2)

    keeps_calling_tools = ModelTurn(tool_calls=[{"name": "search_filings", "args": {}}], text=None)
    clean_refusal = _submit_turn(answer_text="I don't have enough data to answer.", claims=[])

    def fake_start(question, system_prompt, tool_schemas):
        return {}, keeps_calling_tools

    send_tool_results_calls = []

    def fake_send_tool_results(state, results, force_tool=None):
        send_tool_results_calls.append((results, force_tool))
        return clean_refusal if force_tool == "submit_answer" else keeps_calling_tools

    monkeypatch.setattr("sec_agent.agent.agent.BACKENDS", {"gemini": (fake_start, fake_send_tool_results, None)})
    monkeypatch.setattr(
        "sec_agent.agent.agent._dispatch_tool_call",
        lambda call, question, all_results, searched_tickers, verbose: "search result",
    )
    monkeypatch.setattr("sec_agent.agent.agent.verify_claims", lambda claims, all_results, question, answer_text: [])
    log_calls = []
    capture_events(monkeypatch, log_calls)

    answer, all_results, warnings, withheld_answer, _ = run_agent("What was the value?", backend="gemini")

    # One ordinary dispatch round trip (calls_made 1 -> 2), then exactly
    # one forced final-turn round trip once the budget is exhausted.
    assert len(send_tool_results_calls) == 2
    forced_results, forced_tool = send_tool_results_calls[-1]
    assert forced_tool == "submit_answer"
    assert len(forced_results) == 1  # one synthetic result per pending call in `other`
    assert forced_results[0]["name"] == "search_filings"
    assert answer == "I don't have enough data to answer."
    assert answer != (
        "I wasn't able to finish answering within the allotted number of searches. "
        "Try asking a more specific or narrower question."
    )
    assert warnings == []
    assert withheld_answer is None
    # Local-only debug event: the safety net engaging is now directly
    # queryable instead of only inferable from counting trace spans.
    assert ("final_turn_forced", {"backend": "gemini", "calls_made": 2, "pending_tools": ["search_filings"]}) in (
        log_calls
    )


def test_run_agent_final_turn_safety_net_fires_at_most_once(monkeypatch):
    # An uncooperative model (Gemini ignoring the nudge) keeps requesting
    # tool calls even
    # on the forced final turn -- the safety net must not fire a second
    # time; the loop falls through to the unmodified generic timeout.
    monkeypatch.setattr("sec_agent.agent.agent.MAX_TOOL_ITERATIONS", 2)

    keeps_calling_tools = ModelTurn(tool_calls=[{"name": "search_filings", "args": {}}], text=None)

    def fake_start(question, system_prompt, tool_schemas):
        return {}, keeps_calling_tools

    send_tool_results_calls = []

    def fake_send_tool_results(state, results, force_tool=None):
        send_tool_results_calls.append((results, force_tool))
        return keeps_calling_tools  # never complies, whether forced or not

    monkeypatch.setattr("sec_agent.agent.agent.BACKENDS", {"gemini": (fake_start, fake_send_tool_results, None)})
    monkeypatch.setattr(
        "sec_agent.agent.agent._dispatch_tool_call",
        lambda call, question, all_results, searched_tickers, verbose: "search result",
    )

    answer, all_results, warnings, withheld_answer, _ = run_agent("What was the value?", backend="gemini")

    forced_calls = [c for c in send_tool_results_calls if c[1] == "submit_answer"]
    assert len(forced_calls) == 1  # spent exactly once, never repeated
    assert answer == (
        "I wasn't able to finish answering within the allotted number of searches. "
        "Try asking a more specific or narrower question."
    )
    assert warnings == []
    assert withheld_answer is None

def test_final_turn_submit_message_contains_no_deadline_pressure_language():
    # Regression guard against reintroducing the documented fabrication
    # scar (prompts.agent_messages.CITATION_RETRY_GUIDANCE's comment): a prior
    # "final attempt" framing pushed the model to fabricate an estimate
    # on nvda-rd-expense-q4fy26-refusal instead of refusing honestly.
    lowered = FINAL_TURN_SUBMIT_MESSAGE.lower()
    assert "final attempt" not in lowered
    assert "last chance" not in lowered
    assert "acceptable outcome" in lowered  # mirrors CITATION_RETRY_GUIDANCE's proven phrasing


# ---------------------------------------------------------------------------
# run_agent() -- submit_answer loop control (2026-09-10). See
# docs/plans/2026-09-10-structured-claims-citation-verification.md. All
# via the same scripted fake-backend harness used above (agent.BACKENDS
# monkeypatched) -- run_agent()'s actual model-facing behavior is
# exercised live by tests/manual/verify_submit_answer.py, not here; this
# is deterministic loop CONTROL FLOW given a scripted sequence of turns.
# ---------------------------------------------------------------------------
def _submit_turn(answer_text="The value was 100.", claims=None):
    claims = [{"value": 100.0, "unit": "raw", "citation_index": 1, "quote": "the reported value was 100"}] if claims is None else claims
    return ModelTurn(tool_calls=[{"name": "submit_answer", "args": {"answer_text": answer_text, "claims": claims}}], text=None)


def test_submission_warnings_invalid_args_returns_no_structured_answer():
    answer_text, warnings = submission_warnings({"answer_text": "The value was 100.", "claims": "not-a-list"}, [], "q")

    assert answer_text == "The value was 100."
    assert [w.check for w in warnings] == ["no_structured_answer"]


def test_submission_warnings_invalid_args_without_answer_text_yields_empty_text():
    answer_text, warnings = submission_warnings({}, [], "q")

    assert answer_text == ""
    assert [w.check for w in warnings] == ["no_structured_answer"]


def test_submission_warnings_valid_args_delegates_to_verify_claims(monkeypatch):
    seen = {}

    def fake_verify_claims(claims, all_results, question, answer_text):
        seen.update(claims=claims, all_results=all_results, question=question, answer_text=answer_text)
        return []

    monkeypatch.setattr("sec_agent.agent.agent.verify_claims", fake_verify_claims)
    claims = [{"value": 100.0, "unit": "raw", "citation_index": 1, "quote": "the reported value was 100"}]
    results = [{"text": "x"}]

    answer_text, warnings = submission_warnings({"answer_text": "It was 100 [1].", "claims": claims}, results, "q")

    assert (answer_text, warnings) == ("It was 100 [1].", [])
    assert seen == {"claims": claims, "all_results": results, "question": "q", "answer_text": "It was 100 [1]."}


def test_run_search_appends_results_and_numbers_them_after_existing(monkeypatch):
    fake_results = [
        {
            "text": "chunk text",
            "metadata": {
                "ticker": "AAPL",
                "form": "10-K",
                "filingDate": "2025-01-01",
                "reportDate": "2024-12-31",
                "accessionNumber": "acc-1",
                "chunk_index": 0,
            },
        }
    ]
    captured = {}

    def fake_hybrid_search(query, ticker, top_k):
        captured.update(query=query, ticker=ticker, top_k=top_k)
        return fake_results

    monkeypatch.setattr("sec_agent.agent.agent.hybrid_search", fake_hybrid_search)
    all_results = [{"text": "earlier"}]

    content, count = run_search("employees", None, all_results)

    assert captured == {"query": "employees", "ticker": None, "top_k": CHUNKS_PER_SEARCH}
    assert count == 1
    assert all_results == [{"text": "earlier"}] + fake_results
    assert "[2]" in content and "[1]" not in content


def test_run_agent_spontaneous_submit_answer_with_valid_claims_passes(monkeypatch):
    def fake_start(question, system_prompt, tool_schemas):
        return {}, _submit_turn()

    monkeypatch.setattr("sec_agent.agent.agent.BACKENDS", {"gemini": (fake_start, None, None)})
    monkeypatch.setattr(
        "sec_agent.agent.agent.verify_claims", lambda claims, all_results, question, answer_text: []
    )

    answer, all_results, warnings, withheld_answer, _ = run_agent("What was the value?", backend="gemini")

    assert answer == "The value was 100."
    assert warnings == []
    assert withheld_answer is None


def test_run_agent_submit_answer_bad_claims_retries_on_gemini_then_succeeds(monkeypatch):
    first_submit = _submit_turn(answer_text="The value was 100.")
    corrected_submit = _submit_turn(answer_text="The value was 100, corrected.")

    def fake_start(question, system_prompt, tool_schemas):
        return {}, first_submit

    sent_results = []

    def fake_send_tool_results(state, results):
        sent_results.append(results)
        return corrected_submit

    monkeypatch.setattr("sec_agent.agent.agent.BACKENDS", {"gemini": (fake_start, fake_send_tool_results, None)})

    verify_calls = iter(
        [
            [
                CitationWarning(
                    check="quote_not_found",
                    citation_index=1,
                    value=100.0,
                    unit="raw",
                    message="[1] quote not found",
                    quote=None,
                )
            ],
            [],
        ]
    )
    monkeypatch.setattr("sec_agent.agent.agent.verify_claims", lambda claims, all_results, question, answer_text: next(verify_calls))

    answer, all_results, warnings, withheld_answer, _ = run_agent("What was the value?", backend="gemini")

    assert answer == "The value was 100, corrected."
    assert warnings == []
    # The retry's corrective feedback was delivered as a submit_answer
    # TOOL RESULT (send_tool_results), not a plain follow-up turn -- keeps
    # the chat history well-formed (see the loop's own docstring on this).
    assert sent_results == [[{"name": "submit_answer", "content": sent_results[0][0]["content"]}]]
    assert "[1] quote not found" in sent_results[0][0]["content"]

def test_run_agent_mixed_submit_and_search_turn_requests_resubmission(monkeypatch):
    mixed_turn = ModelTurn(
        tool_calls=[
            {"name": "submit_answer", "args": {"answer_text": "x", "claims": []}},
            {"name": "search_filings", "args": {"query": "revenue"}},
        ],
        text=None,
    )
    final_submit = _submit_turn(answer_text="The value was 100, now grounded.")

    def fake_start(question, system_prompt, tool_schemas):
        return {}, mixed_turn

    sent_results = []

    def fake_send_tool_results(state, results):
        sent_results.append(results)
        return final_submit

    monkeypatch.setattr("sec_agent.agent.agent.BACKENDS", {"gemini": (fake_start, fake_send_tool_results, None)})
    monkeypatch.setattr("sec_agent.agent.agent.verify_claims", lambda claims, all_results, question, answer_text: [])
    monkeypatch.setattr(
        "sec_agent.agent.agent._dispatch_tool_call", lambda call, question, all_results, searched_tickers, verbose: "search results here"
    )

    answer, all_results, warnings, withheld_answer, _ = run_agent("What was the value?", backend="gemini")

    assert answer == "The value was 100, now grounded."
    # Both the search result AND a resubmission request went back in the
    # same turn -- the model can't have grounded claims in results it
    # hasn't read yet.
    names_sent = [r["name"] for r in sent_results[0]]
    assert names_sent == ["search_filings", "submit_answer"]
    assert "resubmit" in sent_results[0][1]["content"].lower() or "again" in sent_results[0][1]["content"].lower()


def test_run_agent_mixed_submit_and_search_on_last_turn_salvages_the_submission(monkeypatch):
    # Regression test for the ordering edge case: a mixed submit+search
    # turn landing on the VERY LAST allowed round trip has no budget left
    # to dispatch the searches and get a clean resubmission back -- the
    # submission must still be verified, not discarded for the generic
    # timeout message.
    monkeypatch.setattr("sec_agent.agent.agent.MAX_TOOL_ITERATIONS", 1)
    mixed_turn = ModelTurn(
        tool_calls=[
            {"name": "submit_answer", "args": {"answer_text": "The value was 100.", "claims": []}},
            {"name": "search_filings", "args": {"query": "revenue"}},
        ],
        text=None,
    )

    def fake_start(question, system_prompt, tool_schemas):
        return {}, mixed_turn

    monkeypatch.setattr("sec_agent.agent.agent.BACKENDS", {"gemini": (fake_start, None, None)})
    monkeypatch.setattr("sec_agent.agent.agent.verify_claims", lambda claims, all_results, question, answer_text: [])

    answer, all_results, warnings, withheld_answer, _ = run_agent("What was the value?", backend="gemini")

    assert answer == "The value was 100."
    assert answer != (
        "I wasn't able to finish answering within the allotted number of searches. "
        "Try asking a more specific or narrower question."
    )


def test_run_agent_text_reply_on_gemini_forces_submit_answer(monkeypatch):
    text_turn = ModelTurn(tool_calls=[], text="Apple's revenue was $100 billion [1].")
    forced_submit = _submit_turn(answer_text="Apple's revenue was $100 billion [1].")

    def fake_start(question, system_prompt, tool_schemas):
        return {}, text_turn

    forced_calls = []

    def fake_send_followup(state, text, force_tool=None):
        forced_calls.append((text, force_tool))
        return forced_submit

    monkeypatch.setattr("sec_agent.agent.agent.BACKENDS", {"gemini": (fake_start, None, fake_send_followup)})
    monkeypatch.setattr("sec_agent.agent.agent.verify_claims", lambda claims, all_results, question, answer_text: [])

    answer, all_results, warnings, withheld_answer, _ = run_agent("What was Apple's revenue?", backend="gemini")

    assert answer == "Apple's revenue was $100 billion [1]."
    assert len(forced_calls) == 1
    assert forced_calls[0][1] == "submit_answer"  # force_tool was actually passed

def test_run_agent_malformed_submit_answer_args_produces_no_structured_answer_warning(monkeypatch):
    # Defensive boundary check (same belt-and-suspenders every other tool
    # gets via validate_tool_args) -- not expected in practice (both
    # backends called this correctly on every live run tried), but a
    # schema-invalid submit_answer call must still be handled, not crash.
    malformed_turn = ModelTurn(
        tool_calls=[{"name": "submit_answer", "args": {"answer_text": "The value was 100.", "claims": "not-a-list"}}],
        text=None,
    )

    def fake_start(question, system_prompt, tool_schemas):
        return {}, malformed_turn

    monkeypatch.setattr("sec_agent.agent.agent.BACKENDS", {"gemini": _repeating_backend(fake_start)})

    answer, all_results, warnings, withheld_answer, _ = run_agent("What was the value?", backend="gemini")

    assert len(warnings) == 1
    assert "schema" in warnings[0].lower()
    assert withheld_answer == "The value was 100."


def test_run_agent_submit_answer_retry_exhausting_budget_reverifies_against_current_all_results(monkeypatch):
    # This is the actual proof that the cached-answer staleness bug
    # is closed structurally for the submit_answer path, not
    # just described as closed: caches the RAW submit_args (not
    # pre-computed warnings) and re-runs verify_claims against whatever
    # all_results actually is by the time the budget runs out -- here,
    # grown by one more search dispatched AFTER the retry fired.
    # MAX_TOOL_ITERATIONS bumped by 1 again (3, was already bumped once
    # for the citation-retry mechanism) to make room for the final-turn
    # safety net's own reserved round trip (2026-09-16) without changing
    # what this test is actually regression-testing -- see the same
    # pattern already noted on the sibling test above (line ~2351).
    monkeypatch.setattr("sec_agent.agent.agent.MAX_TOOL_ITERATIONS", 3)
    first_submit = _submit_turn(answer_text="The value was 100.")
    retry_makes_new_search = ModelTurn(tool_calls=[{"name": "search_filings", "args": {"query": "more"}}], text=None)
    another_search_turn = ModelTurn(tool_calls=[{"name": "search_filings", "args": {"query": "even more"}}], text=None)
    # The model ignores the forced final-turn nudge too (realistic mock
    # scenario -- Gemini's real hard constraint isn't exercised by this
    # fake), so the loop still falls through to the unmodified post-loop
    # fallback this test actually verifies.
    ignores_forced_nudge = ModelTurn(tool_calls=[{"name": "search_filings", "args": {"query": "still"}}], text=None)

    def fake_start(question, system_prompt, tool_schemas):
        return {}, first_submit

    responses = iter([retry_makes_new_search, another_search_turn, ignores_forced_nudge])

    def fake_send_tool_results(state, results, force_tool=None):
        return next(responses)

    monkeypatch.setattr("sec_agent.agent.agent.BACKENDS", {"gemini": (fake_start, fake_send_tool_results, None)})
    monkeypatch.setattr(
        "sec_agent.agent.agent._dispatch_tool_call",
        lambda call, question, all_results, searched_tickers, verbose: all_results.append({"text": "extra"}) or "search result",
    )

    verify_calls = []

    def fake_verify_claims(claims, all_results, question, answer_text):
        verify_calls.append(len(all_results))
        return (
            []
            if len(all_results) > 0
            else [
                CitationWarning(
                    check="quote_not_found", citation_index=1, value=100.0, unit="raw", message="bad", quote=None
                )
            ]
        )

    monkeypatch.setattr("sec_agent.agent.agent.verify_claims", fake_verify_claims)

    answer, all_results, warnings, withheld_answer, _ = run_agent("What was the value?", backend="gemini")

    # Called once at retry-decision time (0 results, fails) and once more
    # at the exhausted-budget fallback (1 result by then, passes) --
    # proving the re-check sees the CURRENT all_results, not a stale
    # snapshot from when the retry fired.
    assert verify_calls == [0, 1]
    assert warnings == []
    assert answer == "The value was 100."


def test_run_agent_invalid_submit_then_exhausted_budget_refuses_instead_of_crashing(monkeypatch):
    # A schema-invalid submit triggers the corrective retry, which caches
    # those invalid args; if the budget then runs out, the post-loop
    # fallback must re-gate them through the same boundary check, not
    # index their missing keys.
    monkeypatch.setattr("sec_agent.agent.agent.MAX_TOOL_ITERATIONS", 3)
    invalid_submit = ModelTurn(tool_calls=[{"name": "submit_answer", "args": {"claims": "not-a-list"}}], text=None)
    search_turn = ModelTurn(tool_calls=[{"name": "search_filings", "args": {"query": "more"}}], text=None)

    def fake_start(question, system_prompt, tool_schemas):
        return {}, invalid_submit

    def fake_send_tool_results(state, results, force_tool=None):
        return search_turn

    monkeypatch.setattr("sec_agent.agent.agent.BACKENDS", {"gemini": (fake_start, fake_send_tool_results, None)})
    monkeypatch.setattr(
        "sec_agent.agent.agent._dispatch_tool_call",
        lambda call, question, all_results, searched_tickers, verbose: all_results.append({"text": "extra"}) or "search result",
    )

    answer, all_results, warnings, withheld_answer, details = run_agent("What was the value?", backend="gemini")

    assert [d["check"] for d in details] == ["no_structured_answer"]
    assert withheld_answer == ""


def test_run_agent_rejects_an_unknown_backend_by_name(monkeypatch):
    # e.g. a leftover DEFAULT_BACKEND=ollama in a local .env after that
    # backend was removed -- the error must say which backends exist,
    # not surface as a bare KeyError.
    monkeypatch.setattr("sec_agent.agent.agent.DEFAULT_BACKEND", "ollama")

    with pytest.raises(ValueError, match="'ollama'.*gemini"):
        run_agent("What was Apple's revenue?")


def test_run_agent_backend_default_follows_config(monkeypatch):
    # A caller that omits `backend` must resolve to whatever
    # config.DEFAULT_BACKEND currently is, not a value bound at
    # function-definition time -- a made-up backend name registered in
    # BACKENDS (the one dict agent.py and llm_backends.py share) proves it.
    def fake_start(question, system_prompt, tool_schemas):
        return {}, _submit_turn(answer_text="The value was 100.")

    monkeypatch.setattr("sec_agent.agent.agent.DEFAULT_BACKEND", "totally-custom-backend")
    monkeypatch.setitem(llm_backends.BACKENDS, "totally-custom-backend", _repeating_backend(fake_start))
    monkeypatch.setattr("sec_agent.agent.agent.verify_claims", lambda claims, all_results, question, answer_text: [])

    answer, all_results, warnings, withheld_answer, _ = run_agent("What was the value?")

    assert answer == "The value was 100."


def test_run_agent_does_not_send_withheld_answer_to_the_span(monkeypatch):
    # traced_span() dual-writes to Langfuse when configured; the withheld
    # answer is exactly the text the hard gate decided NOT to trust, so
    # it must never leave the machine via that path -- log_event() (local
    # JSONL only, see tracing.py) is the only place it's allowed to go
    # (see _finalize_answer's own tests above).
    final_answer_turn = ModelTurn(tool_calls=[], text="Apple's revenue was $100 billion [1].")

    def fake_start(question, system_prompt, tool_schemas):
        return {}, final_answer_turn

    monkeypatch.setattr("sec_agent.agent.agent.BACKENDS", {"gemini": _repeating_backend(fake_start)})

    captured_outputs = []

    class _FakeSpan:
        def update(self, **kwargs):
            captured_outputs.append(kwargs)

    @contextmanager
    def fake_traced_span(as_type, name, input=None):
        yield _FakeSpan()

    monkeypatch.setattr("sec_agent.agent.agent.traced_span", fake_traced_span)

    answer, all_results, warnings, withheld_answer, _ = run_agent("What was Apple's revenue?", backend="gemini")

    assert withheld_answer == "Apple's revenue was $100 billion [1]."
    assert len(captured_outputs) == 1
    output = captured_outputs[0]["output"]
    assert "Apple's revenue was $100 billion [1]." not in str(output)
    assert output["citation_checks"] == {"no_submission": 1}


def test_finalize_answer_passes_through_when_no_warnings():
    result = _finalize_answer("the answer", [], [], backend="gemini", retried=False)
    assert result == AgentResult("the answer", [], [], None, [])


def test_finalize_answer_refuses_when_warnings_present():
    warnings = [
        CitationWarning(
            check="quote_not_found",
            citation_index=1,
            value=100.0,
            unit="raw",
            message="[1] claims 100.0 ... doesn't appear",
            quote=None,
        )
    ]
    result = _finalize_answer("the answer", warnings, cast(list[dict], ["result"]), backend="gemini", retried=False)
    assert result.answer == _format_refusal_message(["[1] claims 100.0 ... doesn't appear"])
    assert result.results == ["result"]
    assert result.citation_warnings == ["[1] claims 100.0 ... doesn't appear"]
    assert result.citation_warning_details == [warnings[0]._asdict()]


# ---------------------------------------------------------------------------
# _finalize_answer -- withheld answer + citation_gate_refused logging
# (2026-09-10, added for the FP/FN gate-measurement work). The withheld
# answer preserves what the model actually said so it can later be
# re-graded against ground truth; nothing before this could recover it
# once the hard gate refused.
# ---------------------------------------------------------------------------
def test_finalize_answer_returns_the_withheld_answer_when_refusing():
    warnings = [
        CitationWarning(
            check="uncovered_number",
            citation_index=None,
            value=4.0,
            unit="percent",
            message="claims 4.0 (percent)...",
            quote=None,
        )
    ]
    result = _finalize_answer("the model's answer", warnings, [], backend="gemini", retried=True)
    assert result.withheld_answer == "the model's answer"
    assert result.answer != "the model's answer"  # the refusal text, not the raw answer


def test_finalize_answer_withheld_answer_is_none_when_passing():
    result = _finalize_answer("the model's answer", [], [], backend="gemini", retried=False)
    assert result.withheld_answer is None
    assert result.answer == "the model's answer"


# ---------------------------------------------------------------------------
# _finalize_answer -- citation_warning_details, AgentResult's 5th field
# (2026-09-10, see
# docs/plans/2026-09-10-structured-claims-citation-verification.md).
# Populated directly from the CitationWarnings _finalize_answer already
# holds, NOT re-derived by a second pass, so it always names the checks
# that actually refused the answer.
# ---------------------------------------------------------------------------
def test_finalize_answer_citation_warning_details_empty_when_passing():
    result = _finalize_answer("the answer", [], [], backend="gemini", retried=False)
    assert result.citation_warning_details == []


def test_finalize_answer_citation_warning_details_matches_the_actual_warnings():
    # Proves this field comes from the warnings _finalize_answer was
    # actually given, not re-derived. Also the
    # `quote` field's own presence in the resulting dict, proving it
    # survives the CitationWarning -> _asdict() -> report JSON path
    # unmodified (see Fix B's docstring rationale on verify_claims).
    warnings = [
        CitationWarning(
            check="quote_not_found",
            citation_index=2,
            value=42.0,
            unit="million",
            message="[2] quote not found",
            quote="the model's claimed quote text",
        )
    ]
    result = _finalize_answer("the answer", warnings, [], backend="gemini", retried=False)
    assert result.citation_warning_details == [
        {
            "check": "quote_not_found",
            "citation_index": 2,
            "value": 42.0,
            "unit": "million",
            "message": "[2] quote not found",
            "quote": "the model's claimed quote text",
        }
    ]


def test_finalize_answer_logs_citation_gate_refused_with_check_counts(monkeypatch):
    log_calls = []
    capture_events(monkeypatch, log_calls)
    warnings = [
        CitationWarning(
            check="quote_not_found",
            citation_index=1,
            value=100.0,
            unit="raw",
            message="[1] claims 100.0...",
            quote=None,
        ),
        CitationWarning(
            check="uncovered_number",
            citation_index=None,
            value=4.0,
            unit="percent",
            message="claims 4.0 (percent)...",
            quote=None,
        ),
    ]
    _finalize_answer("the model's answer", warnings, cast(list[dict], ["result"]), backend="gemini", retried=True)

    assert len(log_calls) == 1
    category, fields = log_calls[0]
    assert category == "citation_gate_refused"
    assert fields["backend"] == "gemini"
    assert fields["retried"] is True
    assert fields["n_results"] == 1
    assert fields["checks"] == {"quote_not_found": 1, "uncovered_number": 1}
    assert fields["warnings"] == ["[1] claims 100.0...", "claims 4.0 (percent)..."]
    assert fields["withheld_answer"] == "the model's answer"


def test_finalize_answer_does_not_log_when_passing(monkeypatch):
    log_calls = []
    capture_events(monkeypatch, log_calls)
    _finalize_answer("the model's answer", [], [], backend="gemini", retried=False)
    assert log_calls == []


def test_format_refusal_message_includes_each_warning():
    warnings = [
        "[1] claims 6478.0 (million) but that value doesn't appear in the cited source",
        "[2] claims 42.0 (raw) but that value doesn't appear in the cited source",
    ]
    message = _format_refusal_message(warnings)
    for w in warnings:
        assert w in message


def test_format_refusal_message_reads_as_a_refusal():
    message = _format_refusal_message(["[1] claims ... doesn't appear"]).lower()
    assert "refus" in message or "can't confirm" in message or "can't verify" in message


def test_format_claim_retry_message_tells_model_to_recheck_shown_sources_first():
    # Targets the aapl-employees-fy25 failure mode from Week 5j: the
    # retry gave up entirely instead of checking the 4 OTHER
    # already-retrieved chunks for a valid citation.
    message = _format_claim_retry_message("answer", [])
    assert "already" in message.lower()


def test_format_claim_retry_message_permits_an_honest_refusal():
    message = _format_claim_retry_message("answer", [])
    assert "refus" in message.lower() or "acceptable" in message.lower()


def test_format_claim_retry_message_forbids_inventing_or_estimating():
    message = _format_claim_retry_message("answer", [])
    assert "invent" in message.lower() or "estimat" in message.lower()


def test_format_claim_retry_message_never_uses_final_attempt_deadline_pressure():
    # Regression guard for the exact Week 5j-diagnosed cause of a
    # fabrication regression: wording like "this is your final attempt"
    # pushed the model to fabricate an estimate on a previously-reliable
    # refusal question. Must never reappear in this message.
    message = _format_claim_retry_message("answer", [])
    lowered = message.lower()
    assert "final attempt" not in lowered
    assert "last chance" not in lowered


# ---------------------------------------------------------------------------
# _format_claim_retry_message (2026-09-10) -- structured-claims retry
# wording, built around CITATION_RETRY_GUIDANCE.
# ---------------------------------------------------------------------------
def test_format_claim_retry_message_includes_each_warning():
    warnings = [
        CitationWarning(
            check="quote_not_found", citation_index=1, value=100.0, unit="raw", message="[1] quote missing", quote=None
        ),
        CitationWarning(
            check="value_not_in_quote", citation_index=2, value=42.0, unit="raw", message="[2] value missing", quote=None
        ),
    ]
    message = _format_claim_retry_message("the answer", warnings)
    assert "[1] quote missing" in message
    assert "[2] value missing" in message


def test_format_claim_retry_message_includes_the_previous_answer():
    message = _format_claim_retry_message("Apple's revenue was $100 billion.", [])
    assert "Apple's revenue was $100 billion." in message


def test_format_claim_retry_message_includes_the_shared_guidance():
    assert CITATION_RETRY_GUIDANCE in _format_claim_retry_message("answer", [])


def test_format_claim_retry_message_tells_model_to_call_submit_answer_again():
    message = _format_claim_retry_message("answer", [])
    assert "submit_answer" in message


# ---------------------------------------------------------------------------
# _partition_submit_call (2026-09-10) -- splits a turn's tool_calls into
# the submit_answer call (if any) and every other call, so the loop can
# tell a pure submission from a mixed submit+search turn without a
# str|Terminal union return type on _dispatch_tool_call. See
# docs/plans/2026-09-10-structured-claims-citation-verification.md.
# ---------------------------------------------------------------------------
def test_partition_submit_call_pure_submission():
    submit_call = {"name": "submit_answer", "args": {"answer_text": "x", "claims": []}}
    submit, other = _partition_submit_call([submit_call])
    assert submit is submit_call
    assert other == []


def test_partition_submit_call_no_submission():
    search_call = {"name": "search_filings", "args": {"query": "revenue"}}
    submit, other = _partition_submit_call([search_call])
    assert submit is None
    assert other == [search_call]


def test_partition_submit_call_mixed_turn():
    submit_call = {"name": "submit_answer", "args": {"answer_text": "x", "claims": []}}
    search_call = {"name": "search_filings", "args": {"query": "revenue"}}
    submit, other = _partition_submit_call([submit_call, search_call])
    assert submit is submit_call
    assert other == [search_call]


def test_partition_submit_call_empty():
    assert _partition_submit_call([]) == (None, [])


def test_quote_matches_accepts_a_long_bare_xbrl_number_quote():
    # Regression test for a real false-positive refusal found live
    # (2026-09-10, running the newly-wired agent loop end to end): the
    # model quoted JUST an XBRL fact's bare number, with no surrounding
    # "revenue = ... USD" context -- "391035000000" is only 12
    # NORMALIZED CHARACTERS, under _QUOTE_MIN_CHARS (15), so it was
    # wrongly rejected as "too short to verify" despite being an exact,
    # unambiguous match. A quote's DIGIT count, not character count, is
    # what makes a bare number specific enough to trust -- a 12-digit
    # XBRL value is astronomically unlikely to match by coincidence even
    # though it's shorter (as text) than a genuinely vague quote like
    # "$5" needs to be to mean anything.
    source = "revenue = 391035000000 USD (structured XBRL data, not filing prose)"
    assert _quote_matches("391035000000", source) is True


def test_quote_matches_still_rejects_a_short_bare_number():
    # Contrast with the fix above: a SHORT bare number ("$5", 1 digit)
    # must still be rejected -- the digit-count exception is deliberately
    # scoped to numbers long enough to be specific, not every number.
    source = "Total revenue for fiscal year 2025 was $416,161 million according to the filing."
    assert _quote_matches("$5", source) is False


def test_verify_claims_accepts_a_long_bare_xbrl_number_quote_end_to_end():
    # verify_claims()/_verify_one_claim() had their OWN separate
    # too-short pre-check (agent.py, before ever calling _quote_matches)
    # that was never updated when _BARE_NUMBER_MIN_DIGITS was added to
    # _quote_matches -- so the exact live false positive
    # test_quote_matches_accepts_a_long_bare_xbrl_number_quote regression-
    # tests at the _quote_matches level was still reproducible one layer
    # up, through the actual verify_claims() entry point every caller
    # uses. Found in code review 2026-09-10.
    results = [_fake_result(text="revenue = 391035000000 USD (structured XBRL data, not filing prose)")]
    claims = [_valid_submitted_claim(value=391035000000.0, unit="raw", quote="391035000000")]
    answer_text = "The value was 391035000000 [1]."
    assert verify_claims(claims, results, "q", answer_text) == []
