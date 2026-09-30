"""
Unit tests for tool_results.py: the numbered results block, the citation
key, and the no-data messages the fact and compare tools return.
"""

from sec_agent.agent.tool_results import (
    _citation_header,
    _format_citation_key,
    _format_no_comparison_message,
    _format_no_fact_message,
    _format_results_block,
)
from tests.agent.helpers import _fake_result


# ---------------------------------------------------------------------------
# _format_results_block
# ---------------------------------------------------------------------------
def test_format_results_block_numbers_from_start_index():
    results = [_fake_result(text="First."), _fake_result(text="Second.")]
    block = _format_results_block(results, start_index=3)
    assert "[3] CRM 10-K (reportDate=2026-01-31)" in block
    assert "First." in block
    assert "[4] CRM 10-K (reportDate=2026-01-31)" in block
    assert "Second." in block


def test_format_results_block_empty_results_returns_placeholder_text():
    block = _format_results_block([], start_index=1)
    assert "no matching filing excerpts" in block.lower()


def test_citation_header_matches_format_results_block_output():
    # _format_results_block and _strip_citation_header must reconstruct
    # the identical header string, or the strip could never match what
    # was actually shown to the model -- this pins that shared contract.
    result = _fake_result(ticker="NVDA", form="10-Q", reportDate="2026-04-26")
    header = _citation_header(1, result["metadata"])
    assert header == "[1] NVDA 10-Q (reportDate=2026-04-26)"
    assert _format_results_block([result], start_index=1) == f"{header}\n{result['text']}"


# ---------------------------------------------------------------------------
# _format_no_fact_message / _format_no_comparison_message
# ---------------------------------------------------------------------------
def test_format_no_fact_message_includes_q4_hint():
    # Regression case: nvda-rd-expense-q4fy26-refusal. No company files a
    # standalone Q4 report (only Q1-Q3 get a 10-Q; Q4 only exists inside
    # the 10-K), so a bare "not found, try search" message left the model
    # unaware this was a structural gap rather than a retrieval miss --
    # it trusted the noisy search results back and fabricated a number.
    message = _format_no_fact_message({"metric": "rd_expense", "ticker": "NVDA", "fiscal_period": "Q4", "fiscal_year": 2026})
    assert "estimate" in message.lower()
    assert "q4" in message.lower()


def test_format_no_fact_message_omits_q4_hint_for_other_periods():
    message = _format_no_fact_message({"metric": "rd_expense", "ticker": "NVDA", "fiscal_period": "Q2", "fiscal_year": 2026})
    assert "estimate" not in message.lower()


def test_format_no_fact_message_preserves_existing_detail():
    message = _format_no_fact_message({"metric": "rd_expense", "ticker": "NVDA", "fiscal_period": "Q2", "fiscal_year": 2026})
    assert "rd_expense" in message
    assert "NVDA" in message
    assert "Q2" in message
    assert "2026" in message


def _no_fact_for(**period_args) -> str:
    # A ratio metric skips the never-tagged check, so no XBRL cache read.
    return _format_no_fact_message({"metric": "gross_margin", "ticker": "NVDA", **period_args})


def test_format_no_fact_message_year_without_period_names_the_fy_default():
    # The lookup defaults a missing fiscal_period to "FY".
    assert "'FY' FY2025" in _no_fact_for(fiscal_year=2025)


def test_format_no_fact_message_explicit_null_period_renders_none():
    # The lookup reads args.get("fiscal_period", "FY"), so an explicit
    # null reaches it as None; the reply says what was used.
    assert "None FY2025" in _no_fact_for(fiscal_year=2025, fiscal_period=None)


def test_format_no_fact_message_period_end_date_wins_over_fiscal_year():
    message = _no_fact_for(period_end_date="2026-04-26", fiscal_year=2027, fiscal_period="Q1")
    assert "period ending '2026-04-26'" in message
    assert "FY" not in message


def test_format_no_fact_message_keeps_q4_hint_when_date_overrides_period():
    # The hint answers what the user asked for (a Q4 figure), which stays
    # true even though the date lookup ignored fiscal_period.
    message = _no_fact_for(period_end_date="2026-06-30", fiscal_period="Q4")
    assert "period ending '2026-06-30'" in message
    assert "isn't reported as a standalone figure" in message


def test_format_no_fact_message_empty_date_falls_through_to_fiscal_year():
    assert "'Q2' FY2026" in _no_fact_for(period_end_date="", fiscal_year=2026, fiscal_period="Q2")


def test_format_no_fact_message_full_multi_year_range():
    message = _no_fact_for(start_fiscal_year=2023, end_fiscal_year=2025, fiscal_year=2025)
    assert "FY2023–FY2025 average" in message


def test_format_no_fact_message_partial_multi_year_range_shows_what_was_sent():
    assert "FYNone–FY2025 average" in _no_fact_for(end_fiscal_year=2025)


def test_format_no_fact_message_no_period_arguments_names_latest():
    message = _no_fact_for()
    assert "the latest available period" in message
    assert "None" not in message


def test_format_no_fact_message_string_year_stays_visible():
    # The dispatcher converts a 4-digit year string first; any other string
    # that reaches the formatter is shown as sent.
    assert "'FY' FY'FY2025'" in _no_fact_for(fiscal_year="FY2025")


def test_format_no_fact_message_list_ticker_does_not_raise():
    message = _format_no_fact_message({"metric": "inventory", "ticker": ["NVDA"], "fiscal_year": 2025})
    assert "['NVDA']" in message


def test_format_no_comparison_message_includes_q4_hint():
    # Same structural gap applies to compare_financial_metric -- a user
    # could just as easily ask to compare Q4 figures across companies.
    message = _format_no_comparison_message({"metric": "revenue", "fiscal_period": "Q4", "fiscal_year": 2026})
    assert "estimate" in message.lower()
    assert "q4" in message.lower()


def test_format_no_comparison_message_omits_q4_hint_for_other_periods():
    message = _format_no_comparison_message({"metric": "revenue", "fiscal_period": "FY", "fiscal_year": 2026})
    assert "estimate" not in message.lower()


def test_format_no_comparison_message_includes_never_tagged_hint_when_concept_not_tagged_at_all(monkeypatch):
    # review §12 parity fix: _format_no_fact_message's never-tagged hint
    # (see the PLTR/inventory tests below) applies just as much to a
    # cross-company comparison as to a single-company lookup -- the
    # compare tool's args carry anchor_ticker (not ticker), which
    # _never_tagged_hint() already accepts positionally.
    monkeypatch.setattr("sec_agent.agent.tool_results.is_metric_tagged", lambda ticker, metric: False)
    message = _format_no_comparison_message({"metric": "inventory", "anchor_ticker": "PLTR", "fiscal_period": "FY", "fiscal_year": 2025})
    assert "does not report" in message.lower() or "not applicable" in message.lower() or "business model" in message.lower()
    assert "fabricate" in message.lower() or "estimate" in message.lower()


def test_format_no_comparison_message_omits_never_tagged_hint_when_concept_is_tagged(monkeypatch):
    monkeypatch.setattr("sec_agent.agent.tool_results.is_metric_tagged", lambda ticker, metric: True)
    message = _format_no_comparison_message({"metric": "inventory", "anchor_ticker": "NVDA", "fiscal_period": "FY", "fiscal_year": 2020})
    assert "business model" not in message.lower()


def test_format_no_fact_message_includes_never_tagged_hint_when_concept_not_tagged_at_all(monkeypatch):
    # Regression case: pltr-inventory-turnover-fy2025-refusal. Palantir
    # genuinely never tags inventory at all (a real fact about its
    # business model, not a missing period) -- a bare "not found, try
    # search" message left the model treating it as ordinary missing
    # data, so it self-computed a fabricated ratio from an unrelated
    # cost-of-revenue figure instead of explaining why.
    monkeypatch.setattr("sec_agent.agent.tool_results.is_metric_tagged", lambda ticker, metric: False)
    message = _format_no_fact_message({"metric": "inventory", "ticker": "PLTR", "fiscal_period": "FY", "fiscal_year": 2025})
    assert "does not report" in message.lower() or "not applicable" in message.lower() or "business model" in message.lower()
    assert "fabricate" in message.lower() or "estimate" in message.lower()


def test_format_no_fact_message_omits_never_tagged_hint_when_concept_is_tagged(monkeypatch):
    monkeypatch.setattr("sec_agent.agent.tool_results.is_metric_tagged", lambda ticker, metric: True)
    message = _format_no_fact_message({"metric": "inventory", "ticker": "NVDA", "fiscal_period": "FY", "fiscal_year": 2020})
    assert "business model" not in message.lower()


def test_format_no_fact_message_skips_never_tagged_check_for_margin_metrics(monkeypatch):
    # is_metric_tagged()/_tag_for() only understand raw DEFAULT_METRIC_TAGS
    # names -- a margin metric name would raise ValueError there, so this
    # must never even be called for one.
    calls = []
    monkeypatch.setattr("sec_agent.agent.tool_results.is_metric_tagged", lambda ticker, metric: calls.append((ticker, metric)) or False)
    _format_no_fact_message({"metric": "gross_margin", "ticker": "PLTR", "fiscal_period": "FY", "fiscal_year": 2025})
    assert calls == []


# ---------------------------------------------------------------------------
# _format_citation_key
# ---------------------------------------------------------------------------
def test_format_citation_key_numbering_stays_consistent_across_simulated_tool_calls():
    # Simulates two tool calls' worth of accumulated results, as run_agent
    # would build up all_results across iterations of the loop.
    first_call_results = [_fake_result(ticker="AAPL")]
    second_call_results = [_fake_result(ticker="MSFT"), _fake_result(ticker="MSFT")]
    all_results = first_call_results + second_call_results

    key = _format_citation_key(all_results)
    lines = key.splitlines()

    assert lines[0].strip().startswith("[1] AAPL")
    assert lines[1].strip().startswith("[2] MSFT")
    assert lines[2].strip().startswith("[3] MSFT")
