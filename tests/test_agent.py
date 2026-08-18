"""
Unit tests for agent.py. Covers the pure helpers, plus the
_call_get_financial_fact/_call_compare_financial_metric dispatch/
boundary-validation logic (via monkeypatched xbrl_facts functions, no
network). run_agent()/_call_ollama() drive a live tool-calling loop
against Ollama, so they're exercised by manual runs (python agent.py
"...") documented in PROJECT_CONTEXT.md, not here.
"""

from agent import (
    MARGIN_METRIC_FUNCTIONS,
    _call_compare_financial_metric,
    _call_get_financial_fact,
    _comparison_as_results,
    _format_citation_key,
    _format_results_block,
    _resolve_search_args,
    value_is_citation_verified,
    verify_citations,
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
# _format_results_block
# ---------------------------------------------------------------------------
def _fake_result(ticker="CRM", form="10-K", reportDate="2026-01-31", text="Some chunk text.",
                  filingDate="2026-03-02", accessionNumber="0001108524-26-000060", chunk_index=95):
    return {
        "text": text,
        "metadata": {
            "ticker": ticker,
            "form": form,
            "reportDate": reportDate,
            "filingDate": filingDate,
            "accessionNumber": accessionNumber,
            "chunk_index": chunk_index,
        },
    }


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


# ---------------------------------------------------------------------------
# verify_citations
# ---------------------------------------------------------------------------
def test_verify_citations_flags_computed_ratio_not_in_either_cited_source():
    # Simplified version of the real, observed case (aapl-revenue-growth-
    # q3fy2026, see PROJECT_CONTEXT.md): the model retrieved two raw
    # dollar figures via get_financial_fact, self-computed a percentage
    # from them, and cited both dollar-figure sources for a percentage
    # that appears in neither.
    #
    # Only [1] gets flagged, not [2]: since the two citations are back
    # to back ("...16.27%. [1] [2]"), [2]'s window is just the gap
    # between the two bracket markers (no numbers in it), so the claim
    # text is only associated with the first citation's window. Still
    # catches the misgrounding, which is the actual goal -- it doesn't
    # need to flag every citation attached to a claim to be useful.
    results = [
        _fake_result(text="revenue = 109417000000.0 USD"),
        _fake_result(text="revenue = 94036000000.0 USD"),
    ]
    answer = "The year-over-year revenue growth was approximately 16.27%. [1] [2]"
    warnings = verify_citations(answer, results)
    assert len(warnings) == 1
    assert "[1]" in warnings[0]
    assert "16.27" in warnings[0]


def test_verify_citations_no_warning_when_claim_matches_cited_source():
    results = [_fake_result(text="revenue = 109417000000.0 USD")]
    answer = "Apple's revenue was $109,417 million [1]."
    assert verify_citations(answer, results) == []


def test_verify_citations_windows_reset_per_citation_not_whole_sentence():
    # Two citations in one sentence, each backing a DIFFERENT number
    # stated right before it -- windowing must not let the first
    # citation's number bleed into checking the second (or vice versa).
    results = [
        _fake_result(text="revenue = 109417000000.0 USD"),
        _fake_result(text="tax rate = 20 percent"),
    ]
    answer = "Revenue was $109,417 million [1] and the tax rate was 20% [2]."
    assert verify_citations(answer, results) == []


def test_verify_citations_ignores_citations_with_no_nearby_number():
    # A qualitative claim (no numeric content near the citation) has
    # nothing for this numeric-only check to verify.
    results = [_fake_result(text="We depend on third-party suppliers.")]
    answer = "Apple describes supply chain risk related to suppliers [1]."
    assert verify_citations(answer, results) == []


def test_verify_citations_ignores_out_of_range_citation_index():
    answer = "The rate was 20%. [5]"
    assert verify_citations(answer, [_fake_result()]) == []


def test_verify_citations_ignores_dates_stated_near_a_citation():
    # Found live on the real motivating question: "Revenue for the
    # quarter ending June 27, 2026: $109,417,000,000 USD [1]" was
    # producing spurious warnings for 27 and 2026 (parsed as bare
    # numbers from the date) in addition to the one genuinely useful
    # warning -- dates aren't claims this check should be verifying.
    results = [_fake_result(text="revenue = 109417000000.0 USD")]
    answer = "Revenue for the quarter ending June 27, 2026: $109,417,000,000 USD [1]"
    assert verify_citations(answer, results) == []


def test_verify_citations_ignores_bare_year_stated_near_a_citation():
    # Found live: "Revenue in fiscal Q3 2025: $94,036,000,000 USD [2]"
    # still produced a spurious "2025" warning after the full-date
    # pattern fix, since "Q3 2025" isn't a "Month DD, YYYY" date -- a
    # standalone 1900-2099 number is still a period label, not a claim.
    results = [_fake_result(text="revenue = 94036000000.0 USD")]
    answer = "Revenue in fiscal Q3 2025: $94,036,000,000 USD [2]"
    assert verify_citations(answer, [_fake_result(), results[0]]) == []


def test_verify_citations_ignores_10k_10q_form_type_mentions():
    # Found live: across a real 21-question eval run, the model's own
    # prose routinely says "the 10-Q filing [1]" / "10-K report [1]",
    # and "10" isn't glued to a preceding letter (there's a space), so
    # it wasn't caught by the digit-glued-to-letter fix in
    # numeric_utils.py -- produced a "claims 10.0 (raw)" warning on the
    # majority of that run's answers, the dominant remaining noise
    # source after the date/year fixes.
    results = [_fake_result(text="revenue = 109417000000.0 USD")]
    assert verify_citations("Per the 10-Q filing [1], revenue was $109,417 million.", results) == []


def test_verify_citations_matches_bare_table_cell_under_caption_stated_unit():
    # Real, live case: crm-rpo-fy26 passed with the exact correct answer
    # (72.4 billion) but was still flagged, because the source chunk
    # states the unit once in a table caption ("...consisted of the
    # following (in billions):") and leaves the actual cell value bare
    # ("$72.4"), so a naive per-number extraction reads it as 72.4 raw,
    # not 72.4 billion -- a false positive on a correctly-answered
    # question, not one of the intentionally-hard gap questions.
    source_text = (
        "Remaining performance obligation consisted of the following (in billions):\n"
        "As of January 31, 2026 | $35.1 | $37.3 | $72.4"
    )
    results = [_fake_result(text=source_text)]
    answer = "The total remaining performance obligation was approximately $72.4 billion [1]."
    assert verify_citations(answer, results) == []
    assert verify_citations("Per the 10-K report [1], revenue was $109,417 million.", results) == []


def test_verify_citations_deduplicates_repeated_identical_warnings():
    results = [_fake_result(text="revenue = 109417000000.0 USD")]
    answer = "The rate was 16.28%. [1] It was also stated as 16.28%. [1]"
    warnings = verify_citations(answer, results)
    assert len(warnings) == 1


def test_verify_citations_tolerance_matches_grade_numeric_tolerance():
    # A rounding difference within the same 1%-relative tolerance
    # grade_numeric() uses should not be flagged as unverified.
    results = [_fake_result(text="revenue = 109417000000.0 USD")]
    answer = "Apple's revenue was approximately $109.4 billion [1]."
    assert verify_citations(answer, results) == []


# ---------------------------------------------------------------------------
# value_is_citation_verified (eval_harness.py's numeric/comparison gate)
# ---------------------------------------------------------------------------
def test_value_is_citation_verified_true_when_cited_source_backs_it():
    results = [_fake_result(text="revenue = 109417000000.0 USD")]
    answer = "Apple's revenue was $109,417 million [1]."
    assert value_is_citation_verified(109417000000.0, "raw", answer, results) is True


def test_value_is_citation_verified_false_when_only_citation_is_unrelated():
    # Reproduces the real, live-found aapl-employees-fy25 bug: the answer
    # states the correct headcount, but the cited chunk is actually about
    # debt notes/share repurchases -- grade_numeric() alone can't see
    # this, since it only checks whether the number appears anywhere in
    # the answer text, not whether its own citation supports it.
    results = [_fake_result(text="Future principal payments for the Company's Notes...")]
    answer = "Apple had approximately 166,000 full-time equivalent employees [1]."
    assert value_is_citation_verified(166000.0, "raw", answer, results) is False


def test_value_is_citation_verified_true_when_value_never_cited_at_all():
    # Nothing to contradict a plain-text match if the target value isn't
    # attached to any citation marker in the first place.
    results = [_fake_result(text="Some unrelated source text.")]
    answer = "The company grew steadily over the period. [1]"
    assert value_is_citation_verified(166000.0, "raw", answer, results) is True


def test_value_is_citation_verified_true_when_at_least_one_citation_backs_it():
    # A redundant second (wrong) citation for the same value shouldn't
    # poison an otherwise properly-supported claim -- verified via ANY
    # matching citation, not ALL of them.
    results = [
        _fake_result(text="revenue = 109417000000.0 USD"),
        _fake_result(text="Unrelated debt notes text."),
    ]
    answer = "Apple's revenue was $109,417 million [1] [2]."
    assert value_is_citation_verified(109417000000.0, "raw", answer, results) is True


def test_value_is_citation_verified_respects_grade_numeric_tolerance():
    results = [_fake_result(text="revenue = 109417000000.0 USD")]
    answer = "Apple's revenue was approximately $109.4 billion [1]."
    assert value_is_citation_verified(109417000000.0, "raw", answer, results) is True


# ---------------------------------------------------------------------------
# _comparison_as_results (compare_financial_metric)
# ---------------------------------------------------------------------------
def test_comparison_as_results_one_entry_per_company_sorted_by_ticker():
    data = {
        "NVDA": {"value": 74.9, "unit": "percent", "period_end": "2026-04-26", "accession": "b"},
        "AAPL": {"value": 49.3, "unit": "percent", "period_end": "2026-03-28", "accession": "a"},
    }
    results = _comparison_as_results(data, "gross_margin")
    assert [r["metadata"]["ticker"] for r in results] == ["AAPL", "NVDA"]
    assert "AAPL gross_margin = 49.3 percent" in results[0]["text"]
    assert results[0]["metadata"]["form"] == "XBRL frame data"
    assert results[0]["metadata"]["accessionNumber"] == "a"


def test_comparison_as_results_empty_dict_returns_empty_list():
    assert _comparison_as_results({}, "revenue") == []


# ---------------------------------------------------------------------------
# _call_get_financial_fact / _call_compare_financial_metric
# (margin dispatch + yoy_growth boundary validation)
# ---------------------------------------------------------------------------
def test_call_get_financial_fact_dispatches_operating_margin(monkeypatch):
    # MARGIN_METRIC_FUNCTIONS binds function objects once at import time,
    # so patching agent.get_operating_margin afterward wouldn't reach
    # the dispatch code (which reads from the dict, not the module
    # attribute) -- patch the dict entry itself instead.
    monkeypatch.setitem(
        MARGIN_METRIC_FUNCTIONS,
        "operating_margin",
        (lambda ticker, fiscal_year, fiscal_period, period_end_date: {"value": 60.0, "unit": "percent"}, None),
    )
    result = _call_get_financial_fact(
        {"ticker": "NVDA", "metric": "operating_margin", "fiscal_year": 2026, "fiscal_period": "FY"}
    )
    assert result == {"value": 60.0, "unit": "percent"}


def test_call_get_financial_fact_dispatches_net_margin(monkeypatch):
    monkeypatch.setitem(
        MARGIN_METRIC_FUNCTIONS,
        "net_margin",
        (lambda ticker, fiscal_year, fiscal_period, period_end_date: {"value": 45.0, "unit": "percent"}, None),
    )
    result = _call_get_financial_fact(
        {"ticker": "NVDA", "metric": "net_margin", "fiscal_year": 2026, "fiscal_period": "FY"}
    )
    assert result == {"value": 45.0, "unit": "percent"}


def test_call_get_financial_fact_dispatches_yoy_growth_for_raw_metric(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "agent.get_yoy_growth",
        lambda ticker, metric, fiscal_year, fiscal_period, period_end_date: calls.append((ticker, metric))
        or {"value": 10.0, "unit": "percent"},
    )
    result = _call_get_financial_fact(
        {"ticker": "AAPL", "metric": "revenue", "yoy_growth": True, "fiscal_year": 2026, "fiscal_period": "Q3"}
    )
    assert result == {"value": 10.0, "unit": "percent"}
    assert calls == [("AAPL", "revenue")]


def test_call_get_financial_fact_rejects_yoy_growth_combined_with_margin_metric():
    # get_yoy_growth() doesn't support ratio metrics (see its own
    # docstring) -- caught here at the boundary, same reasoning as this
    # function's existing invalid-metric guard, rather than letting
    # xbrl_facts raise or silently compute something nonsensical.
    result = _call_get_financial_fact({"ticker": "AAPL", "metric": "gross_margin", "yoy_growth": True})
    assert result is None


def test_call_compare_financial_metric_dispatches_operating_margin(monkeypatch):
    monkeypatch.setitem(
        MARGIN_METRIC_FUNCTIONS,
        "operating_margin",
        (None, lambda ticker, fiscal_year, fiscal_period, period_end_date: {"NVDA": {"value": 60.0}}),
    )
    result = _call_compare_financial_metric({"anchor_ticker": "NVDA", "metric": "operating_margin"})
    assert result == {"NVDA": {"value": 60.0}}


def test_call_compare_financial_metric_dispatches_net_margin(monkeypatch):
    monkeypatch.setitem(
        MARGIN_METRIC_FUNCTIONS,
        "net_margin",
        (None, lambda ticker, fiscal_year, fiscal_period, period_end_date: {"NVDA": {"value": 45.0}}),
    )
    result = _call_compare_financial_metric({"anchor_ticker": "NVDA", "metric": "net_margin"})
    assert result == {"NVDA": {"value": 45.0}}
