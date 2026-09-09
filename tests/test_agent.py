"""
Unit tests for agent.py. Covers the pure helpers, plus the
call_get_financial_fact/call_compare_financial_metric dispatch/
boundary-validation logic (via monkeypatched xbrl_facts functions, no
network). run_agent()'s actual model-facing behavior drives a live
tool-calling loop against whichever backend is selected (see
llm_backends.py), so THAT is exercised by manual runs (python agent.py
"..." [--backend ollama|gemini]) documented in PROJECT_CONTEXT.md, not
here -- but run_agent()'s own loop CONTROL FLOW (how it reacts to a
scripted sequence of ModelTurns) is deterministic and doesn't need a
live model, so a few targeted regression tests below drive it through
monkeypatched BACKENDS entries instead.
"""

from agent import (
    COMPARE_TOOL_SCHEMA,
    FACT_TOOL_SCHEMA,
    RATIO_DEFINITIONS,
    SEARCH_TOOL_SCHEMA,
    call_compare_financial_metric,
    call_get_financial_fact,
    _comparison_as_results,
    _dispatch_tool_call,
    _finalize_answer,
    _format_citation_key,
    _format_citation_retry_message,
    _format_fact_value,
    _format_no_comparison_message,
    _format_no_fact_message,
    _format_refusal_message,
    _format_results_block,
    _resolve_search_args,
    _should_retry_for_citations,
    validate_tool_args,
    run_agent,
    value_is_citation_verified,
    verify_citations,
)
from llm_backends import ModelTurn


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
    monkeypatch.setattr("agent.is_metric_tagged", lambda ticker, metric: False)
    message = _format_no_comparison_message({"metric": "inventory", "anchor_ticker": "PLTR", "fiscal_period": "FY", "fiscal_year": 2025})
    assert "does not report" in message.lower() or "not applicable" in message.lower() or "business model" in message.lower()
    assert "fabricate" in message.lower() or "estimate" in message.lower()


def test_format_no_comparison_message_omits_never_tagged_hint_when_concept_is_tagged(monkeypatch):
    monkeypatch.setattr("agent.is_metric_tagged", lambda ticker, metric: True)
    message = _format_no_comparison_message({"metric": "inventory", "anchor_ticker": "NVDA", "fiscal_period": "FY", "fiscal_year": 2020})
    assert "business model" not in message.lower()


def test_format_no_fact_message_includes_never_tagged_hint_when_concept_not_tagged_at_all(monkeypatch):
    # Regression case: pltr-inventory-turnover-fy2025-refusal. Palantir
    # genuinely never tags inventory at all (a real fact about its
    # business model, not a missing period) -- a bare "not found, try
    # search" message left the model treating it as ordinary missing
    # data, so it self-computed a fabricated ratio from an unrelated
    # cost-of-revenue figure instead of explaining why.
    monkeypatch.setattr("agent.is_metric_tagged", lambda ticker, metric: False)
    message = _format_no_fact_message({"metric": "inventory", "ticker": "PLTR", "fiscal_period": "FY", "fiscal_year": 2025})
    assert "does not report" in message.lower() or "not applicable" in message.lower() or "business model" in message.lower()
    assert "fabricate" in message.lower() or "estimate" in message.lower()


def test_format_no_fact_message_omits_never_tagged_hint_when_concept_is_tagged(monkeypatch):
    monkeypatch.setattr("agent.is_metric_tagged", lambda ticker, metric: True)
    message = _format_no_fact_message({"metric": "inventory", "ticker": "NVDA", "fiscal_period": "FY", "fiscal_year": 2020})
    assert "business model" not in message.lower()


def test_format_no_fact_message_skips_never_tagged_check_for_margin_metrics(monkeypatch):
    # is_metric_tagged()/_tag_for() only understand raw DEFAULT_METRIC_TAGS
    # names -- a margin metric name would raise ValueError there, so this
    # must never even be called for one.
    calls = []
    monkeypatch.setattr("agent.is_metric_tagged", lambda ticker, metric: calls.append((ticker, metric)) or False)
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
# _format_fact_value (found in code review, 2026-08-25: "raw" is an
# internal numeric_utils.normalize() category label, not a
# natural-language unit -- get_asset_turnover's citation text shouldn't
# read "1.04 raw")
# ---------------------------------------------------------------------------
def test_format_fact_value_omits_unit_word_for_raw():
    assert _format_fact_value({"value": 1.04, "unit": "raw"}) == "1.04"


def test_format_fact_value_includes_unit_word_for_percent():
    assert _format_fact_value({"value": 31.2, "unit": "percent"}) == "31.2 percent"


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


def test_comparison_as_results_uses_real_form_when_present():
    # Instant metrics (total_assets etc., 2026-09-07 redesign) resolve
    # via independent per-company get_metric() calls, which DO carry a
    # real form (10-K/10-Q) unlike frame-sourced duration-metric facts.
    data = {
        "AAPL": {
            "value": 359241000000,
            "unit": "USD",
            "period_end": "2025-09-27",
            "accession": "a",
            "form": "10-K",
        },
    }
    results = _comparison_as_results(data, "total_assets")
    assert results[0]["metadata"]["form"] == "10-K"


# ---------------------------------------------------------------------------
# validate_tool_args -- the generic jsonschema-driven replacement for the
# hand-rolled per-tool extra-key/type/enum checks that broke three separate
# times across three review dates (2026-09-06, 2026-09-09, 2026-09-10). The
# schema-shape checks below exercise the generic function directly, walking
# each *_TOOL_SCHEMA's declared properties rather than one hand-written test
# per field -- the call_get_financial_fact/call_compare_financial_metric/
# _dispatch_tool_call tests further down still cover the same schema-
# violation cases end-to-end (unrecognized_extra_argument, ticker_not_in_enum,
# etc.), so this section is additive, not a replacement for those.
# ---------------------------------------------------------------------------
def test_validate_tool_args_accepts_valid_args():
    assert validate_tool_args("get_financial_fact", FACT_TOOL_SCHEMA, {"ticker": "AAPL", "metric": "revenue"}) is False


def test_validate_tool_args_rejects_extra_argument(monkeypatch):
    calls = []
    monkeypatch.setattr("agent.log_event", lambda category, **fields: calls.append((category, fields)))

    rejected = validate_tool_args(
        "get_financial_fact", FACT_TOOL_SCHEMA, {"ticker": "AAPL", "metric": "revenue", "segment": "Graphics"}
    )

    assert rejected is True
    assert calls == [("tool_call_rejected", {"tool": "get_financial_fact", "reason": "unrecognized_extra_argument", "args": {"ticker": "AAPL", "metric": "revenue", "segment": "Graphics"}})]


def test_validate_tool_args_rejects_missing_required_property(monkeypatch):
    calls = []
    monkeypatch.setattr("agent.log_event", lambda category, **fields: calls.append((category, fields)))

    rejected = validate_tool_args("get_financial_fact", FACT_TOOL_SCHEMA, {"ticker": "AAPL"})

    assert rejected is True
    assert calls[0][1]["reason"] == "missing_required_argument"


def test_validate_tool_args_reason_names_property_and_violation_kind(monkeypatch):
    calls = []
    monkeypatch.setattr("agent.log_event", lambda category, **fields: calls.append((category, fields)))

    validate_tool_args("get_financial_fact", FACT_TOOL_SCHEMA, {"ticker": 123, "metric": "revenue"})

    assert calls[0][1]["reason"] == "ticker_wrong_type"


def test_validate_tool_args_lets_metric_enum_violation_through():
    # The one deliberate carve-out: a recognized-shape-but-unsupported
    # metric name must NOT be a generic hard rejection -- callers route it
    # to record_unmet_metric_request instead (see call_get_financial_fact).
    rejected = validate_tool_args(
        "get_financial_fact", FACT_TOOL_SCHEMA, {"ticker": "AAPL", "metric": "effective_tax_rate"}
    )
    assert rejected is False


def test_validate_tool_args_still_rejects_wrong_typed_metric():
    # Contrast with the enum carve-out above: a wrong-TYPE metric (not a
    # string at all) is not the same carve-out and must still hard-fail.
    rejected = validate_tool_args("get_financial_fact", FACT_TOOL_SCHEMA, {"ticker": "AAPL", "metric": ["revenue"]})
    assert rejected is True


def test_validate_tool_args_soft_required_allows_missing_property():
    # search_filings' query: schema-required (encourages the model to
    # include it) but tolerated absent at runtime -- _resolve_search_args
    # substitutes the original question instead of rejecting.
    rejected = validate_tool_args(
        "search_filings", SEARCH_TOOL_SCHEMA, {"ticker": "AAPL"}, soft_required=frozenset({"query"})
    )
    assert rejected is False


def test_validate_tool_args_skip_properties_ignores_malformed_value():
    # get_financial_fact's fiscal_year: the multi-year-average request
    # shape never reads it, so a malformed value must be ignored generically
    # -- _rejects_invalid_fiscal_year only fires on the single-period path.
    rejected = validate_tool_args(
        "get_financial_fact",
        FACT_TOOL_SCHEMA,
        {"ticker": "AAPL", "metric": "revenue", "fiscal_year": "bogus"},
        skip_properties=frozenset({"fiscal_year", "start_fiscal_year", "end_fiscal_year"}),
    )
    assert rejected is False


def test_validate_tool_args_treats_null_optional_property_as_absent():
    # Found in code review: this diff's own period_end_date fix (adding
    # "null" to that one property's declared type after live testing)
    # was the first instance of a general problem, not a one-off -- every
    # other optional property had the same gap. search_filings' ticker is
    # optional (a broad, unsure search is valid) and the old hand-rolled
    # check explicitly tolerated `ticker: None` as "no filter"
    # (`if raw_ticker is not None and (...)`) -- an explicit JSON null
    # must be treated the same way now, not hard-rejected.
    rejected = validate_tool_args(
        "search_filings", SEARCH_TOOL_SCHEMA, {"query": "revenue", "ticker": None}, soft_required=frozenset({"query"})
    )
    assert rejected is False


def test_validate_tool_args_treats_null_required_property_as_missing():
    # The other half of the same fix: for a REQUIRED property, null must
    # still be rejected (as "missing", not "wrong type") -- not silently
    # tolerated just because it's declared.
    rejected = validate_tool_args("get_financial_fact", FACT_TOOL_SCHEMA, {"ticker": None, "metric": "revenue"})
    assert rejected is True


def test_validate_tool_args_still_rejects_null_valued_extra_key(monkeypatch):
    # additionalProperties: false must still catch an unrecognized key
    # even when its value happens to be null -- the key itself is the
    # problem, not its value, so it must not be silently stripped away
    # before validation runs.
    calls = []
    monkeypatch.setattr("agent.log_event", lambda category, **fields: calls.append((category, fields)))

    rejected = validate_tool_args(
        "get_financial_fact", FACT_TOOL_SCHEMA, {"ticker": "AAPL", "metric": "revenue", "segment": None}
    )

    assert rejected is True
    assert calls[0][1]["reason"] == "unrecognized_extra_argument"


def test_call_get_financial_fact_tolerates_null_fiscal_period(monkeypatch):
    # Regression case for the same null-optional-property fix, exercised
    # through the real call site rather than validate_tool_args directly.
    monkeypatch.setattr("agent.get_metric", lambda *a, **k: {"value": 42})
    result = call_get_financial_fact({"ticker": "AAPL", "metric": "revenue", "fiscal_period": None})
    assert result == {"value": 42}


def test_dispatch_tool_call_search_filings_tolerates_null_ticker(monkeypatch):
    monkeypatch.setattr("agent.hybrid_search", lambda query, ticker, top_k: [])
    call = {"name": "search_filings", "args": {"query": "revenue", "ticker": None}}
    content = _dispatch_tool_call(call, "q", [], set(), verbose=False)
    assert "invalid" not in content


def test_validate_tool_args_skip_properties_still_allows_the_property_itself(monkeypatch):
    # additionalProperties: false must not treat a skip_propertied but
    # otherwise-declared property as an unrecognized extra key.
    calls = []
    monkeypatch.setattr("agent.log_event", lambda category, **fields: calls.append((category, fields)))

    rejected = validate_tool_args(
        "get_financial_fact",
        FACT_TOOL_SCHEMA,
        {"ticker": "AAPL", "metric": "revenue", "fiscal_year": 2026},
        skip_properties=frozenset({"fiscal_year", "start_fiscal_year", "end_fiscal_year"}),
    )
    assert rejected is False
    assert calls == []


# ---------------------------------------------------------------------------
# jsonschema's bool-exclusion from "integer" -- the recurring bug this whole
# redesign exists to fix structurally: isinstance(True, int) is True in
# Python, so the old hand-rolled `isinstance(fiscal_year, int)` check
# silently accepted a JSON boolean (2026-09-09 review, left open at the
# time). jsonschema's default type checker already excludes bool from
# "integer", so this is fixed as a side effect of the library switch.
# ---------------------------------------------------------------------------
def test_call_get_financial_fact_rejects_boolean_fiscal_year(monkeypatch):
    calls = []
    monkeypatch.setattr("agent.log_event", lambda category, **fields: calls.append((category, fields)))

    result = call_get_financial_fact({"ticker": "AAPL", "metric": "revenue", "fiscal_year": True})

    assert result is None
    assert calls[-1][1]["reason"] == "invalid_fiscal_year_type"


def test_call_compare_financial_metric_rejects_boolean_fiscal_year(monkeypatch):
    calls = []
    monkeypatch.setattr("agent.log_event", lambda category, **fields: calls.append((category, fields)))

    result = call_compare_financial_metric({"anchor_ticker": "AAPL", "metric": "revenue", "fiscal_year": True})

    assert result == {}
    assert calls[-1][1]["reason"] == "invalid_fiscal_year_type"


# ---------------------------------------------------------------------------
# call_get_financial_fact / call_compare_financial_metric
# (margin dispatch + yoy_growth boundary validation)
# ---------------------------------------------------------------------------
def test_call_get_financial_fact_dispatches_operating_margin(monkeypatch):
    # get_ratio() is the single generic dispatch point for every
    # RATIO_DEFINITIONS entry now -- unlike the old RATIO_METRIC_FUNCTIONS/
    # SINGLE_COMPANY_RATIO_FUNCTIONS dicts (which bound function objects
    # at import time, so a monkeypatch had to target the dict entry
    # itself), get_ratio is looked up fresh by bare name each call, so
    # patching agent.get_ratio directly is the correct seam -- same
    # pattern already used for get_yoy_growth/get_multi_year_average
    # below. Asserting the exact call args, not just the return value,
    # keeps this test meaningfully distinguishing "operating_margin" from
    # any other ratio, since the mock itself no longer does.
    calls = []
    monkeypatch.setattr(
        "agent.get_ratio",
        lambda ticker, ratio_name, fiscal_year, fiscal_period, period_end_date: calls.append(
            (ticker, ratio_name, fiscal_year, fiscal_period, period_end_date)
        )
        or {"value": 60.0, "unit": "percent"},
    )
    result = call_get_financial_fact(
        {"ticker": "NVDA", "metric": "operating_margin", "fiscal_year": 2026, "fiscal_period": "FY"}
    )
    assert result == {"value": 60.0, "unit": "percent"}
    assert calls == [("NVDA", "operating_margin", 2026, "FY", None)]


def test_call_get_financial_fact_dispatches_net_margin(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "agent.get_ratio",
        lambda ticker, ratio_name, fiscal_year, fiscal_period, period_end_date: calls.append(ratio_name)
        or {"value": 45.0, "unit": "percent"},
    )
    result = call_get_financial_fact(
        {"ticker": "NVDA", "metric": "net_margin", "fiscal_year": 2026, "fiscal_period": "FY"}
    )
    assert result == {"value": 45.0, "unit": "percent"}
    assert calls == ["net_margin"]


def test_call_get_financial_fact_dispatches_return_on_assets(monkeypatch):
    # return_on_assets/asset_turnover/cash_to_assets/inventory_turnover/
    # rd_intensity all have supports_cross_company=False in
    # RATIO_DEFINITIONS, but get_financial_fact supports every ratio
    # regardless of that flag -- same generic get_ratio() dispatch as
    # any other ratio, see formulas.get_return_on_assets's own docstring
    # for why there's no cross-company counterpart.
    calls = []
    monkeypatch.setattr(
        "agent.get_ratio",
        lambda ticker, ratio_name, fiscal_year, fiscal_period, period_end_date: calls.append(ratio_name)
        or {"value": 31.2, "unit": "percent"},
    )
    result = call_get_financial_fact(
        {"ticker": "AAPL", "metric": "return_on_assets", "fiscal_year": 2025, "fiscal_period": "FY"}
    )
    assert result == {"value": 31.2, "unit": "percent"}
    assert calls == ["return_on_assets"]


def test_call_get_financial_fact_dispatches_asset_turnover(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "agent.get_ratio",
        lambda ticker, ratio_name, fiscal_year, fiscal_period, period_end_date: calls.append(ratio_name)
        or {"value": 1.04, "unit": "raw"},
    )
    result = call_get_financial_fact(
        {"ticker": "NVDA", "metric": "asset_turnover", "fiscal_year": 2026, "fiscal_period": "FY"}
    )
    assert result == {"value": 1.04, "unit": "raw"}
    assert calls == ["asset_turnover"]


def test_call_get_financial_fact_dispatches_cash_to_assets(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "agent.get_ratio",
        lambda ticker, ratio_name, fiscal_year, fiscal_period, period_end_date: calls.append(ratio_name)
        or {"value": 4.9, "unit": "percent"},
    )
    result = call_get_financial_fact(
        {"ticker": "MSFT", "metric": "cash_to_assets", "fiscal_year": 2025, "fiscal_period": "FY"}
    )
    assert result == {"value": 4.9, "unit": "percent"}
    assert calls == ["cash_to_assets"]


def test_call_get_financial_fact_dispatches_inventory_turnover(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "agent.get_ratio",
        lambda ticker, ratio_name, fiscal_year, fiscal_period, period_end_date: calls.append(ratio_name)
        or {"value": 5.2, "unit": "raw"},
    )
    result = call_get_financial_fact(
        {"ticker": "NVDA", "metric": "inventory_turnover", "fiscal_year": 2026, "fiscal_period": "FY"}
    )
    assert result == {"value": 5.2, "unit": "raw"}
    assert calls == ["inventory_turnover"]


def test_call_get_financial_fact_dispatches_rd_intensity(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "agent.get_ratio",
        lambda ticker, ratio_name, fiscal_year, fiscal_period, period_end_date: calls.append(ratio_name)
        or {"value": 18.3, "unit": "percent"},
    )
    result = call_get_financial_fact(
        {"ticker": "NVDA", "metric": "rd_intensity", "fiscal_year": 2026, "fiscal_period": "FY"}
    )
    assert result == {"value": 18.3, "unit": "percent"}
    assert calls == ["rd_intensity"]


def test_call_get_financial_fact_rejects_yoy_growth_combined_with_single_company_ratio():
    # Same reasoning as the margin+yoy_growth rejection below -- "growth
    # of a ratio" has no current evidence/use case for these three
    # either, so it's rejected the same way rather than silently
    # computed or passed through to get_yoy_growth (which doesn't
    # support ratio metrics at all).
    result = call_get_financial_fact({"ticker": "NVDA", "metric": "asset_turnover", "yoy_growth": True})
    assert result is None


def test_call_get_financial_fact_dispatches_yoy_growth_for_raw_metric(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "agent.get_yoy_growth",
        lambda ticker, metric, fiscal_year, fiscal_period, period_end_date: calls.append((ticker, metric))
        or {"value": 10.0, "unit": "percent"},
    )
    result = call_get_financial_fact(
        {"ticker": "AAPL", "metric": "revenue", "yoy_growth": True, "fiscal_year": 2026, "fiscal_period": "Q3"}
    )
    assert result == {"value": 10.0, "unit": "percent"}
    assert calls == [("AAPL", "revenue")]


def test_call_get_financial_fact_rejects_yoy_growth_combined_with_margin_metric():
    # get_yoy_growth() doesn't support ratio metrics (see its own
    # docstring) -- caught here at the boundary, same reasoning as this
    # function's existing invalid-metric guard, rather than letting
    # xbrl_facts raise or silently compute something nonsensical.
    result = call_get_financial_fact({"ticker": "AAPL", "metric": "gross_margin", "yoy_growth": True})
    assert result is None


def test_call_get_financial_fact_dispatches_multi_year_average(monkeypatch):
    # Regression case: aapl-3yr-avg-operating-margin-fy2023-fy2025. With
    # no deterministic path before this existed, the model self-computed
    # an average from 3 separate calls (a rule-3 violation) or misparsed
    # the whole request as Q4-specific.
    calls = []
    monkeypatch.setattr(
        "agent.get_multi_year_average",
        lambda ticker, metric, start_fiscal_year, end_fiscal_year: calls.append(
            (ticker, metric, start_fiscal_year, end_fiscal_year)
        )
        or {"value": 31.1, "unit": "percent"},
    )
    result = call_get_financial_fact(
        {"ticker": "AAPL", "metric": "operating_margin", "start_fiscal_year": 2023, "end_fiscal_year": 2025}
    )
    assert result == {"value": 31.1, "unit": "percent"}
    assert calls == [("AAPL", "operating_margin", 2023, 2025)]


def test_call_get_financial_fact_ignores_malformed_fiscal_year_in_multi_year_average_request(monkeypatch):
    # Found in code review (round 2, 2026-09-09): the new §8 fiscal_year
    # type guard was placed before this branch even checks whether
    # start_fiscal_year/end_fiscal_year are present -- fiscal_year is
    # never read inside get_multi_year_average()'s call below, so a
    # stray malformed fiscal_year alongside a VALID start/end pair used
    # to wrongly reject the whole request instead of being ignored, the
    # same as it always was pre-fix.
    calls = []
    monkeypatch.setattr(
        "agent.get_multi_year_average",
        lambda ticker, metric, start_fiscal_year, end_fiscal_year: calls.append(
            (ticker, metric, start_fiscal_year, end_fiscal_year)
        )
        or {"value": 31.1, "unit": "percent"},
    )
    result = call_get_financial_fact(
        {
            "ticker": "AAPL",
            "metric": "operating_margin",
            "start_fiscal_year": 2023,
            "end_fiscal_year": 2025,
            "fiscal_year": "bogus",
        }
    )
    assert result == {"value": 31.1, "unit": "percent"}
    assert calls == [("AAPL", "operating_margin", 2023, 2025)]


def test_call_get_financial_fact_rejects_multi_year_average_combined_with_yoy_growth():
    # Nonsensical combination -- caught explicitly rather than silently
    # picking one, same discipline as the yoy_growth+margin rejection.
    result = call_get_financial_fact(
        {"ticker": "AAPL", "metric": "revenue", "start_fiscal_year": 2023, "end_fiscal_year": 2025, "yoy_growth": True}
    )
    assert result is None


def test_call_get_financial_fact_rejects_partial_multi_year_average_range(monkeypatch):
    # Only one of start/end given -- malformed, not a valid single-period
    # lookup either (fiscal_year/fiscal_period/period_end_date are all
    # absent), so this must reject rather than silently falling through
    # to a plain get_metric() call with fiscal_year=None.
    monkeypatch.setattr("agent.get_metric", lambda *a, **k: {"value": 999})
    result = call_get_financial_fact({"ticker": "AAPL", "metric": "revenue", "start_fiscal_year": 2023})
    assert result is None


def test_call_get_financial_fact_rejects_unrecognized_extra_argument(monkeypatch):
    # Regression case: nvda-segment-revenue-comparison-q1fy27. The model
    # invented a `segment` filter this tool doesn't support; the old code
    # silently ignored it (only ever read known keys via args.get(...)),
    # so both a "Compute & Networking" and a "Graphics" call silently
    # returned the SAME consolidated total -- a plausible-looking but
    # wrong value, not an error the model could react to. An unrecognized
    # key must reject the call entirely (falls through to the "no
    # structured data found -- try search_filings" message) rather than
    # silently succeeding with a misleading result.
    calls = []
    monkeypatch.setattr("agent.get_metric", lambda *a, **k: calls.append((a, k)) or {"value": 1})
    result = call_get_financial_fact(
        {"ticker": "NVDA", "metric": "revenue", "period_end_date": "2026-04-26", "segment": "Graphics"}
    )
    assert result is None
    assert calls == []  # never even reached the real lookup


def test_call_get_financial_fact_still_works_with_only_known_keys(monkeypatch):
    # Sanity check for the test above: a call using ONLY recognized keys
    # must still reach the real lookup, so the new guard isn't
    # accidentally rejecting legitimate calls too.
    monkeypatch.setattr("agent.get_metric", lambda *a, **k: {"value": 42})
    result = call_get_financial_fact(
        {"ticker": "AAPL", "metric": "revenue", "fiscal_year": 2026, "fiscal_period": "FY", "period_end_date": None}
    )
    assert result == {"value": 42}


# ---------------------------------------------------------------------------
# Unmet-metric-request tracing (Week 7 guardrails, Langfuse): the
# specific "let evidence decide" requirement added 2026-08-28 -- record
# when a metric/ratio request comes back empty for a reason worth
# tracking, distinguishing "we don't know this metric at all" from "we
# know it, but this ticker has no data for it."
# ---------------------------------------------------------------------------
def test_call_get_financial_fact_records_unmet_request_for_unknown_metric(monkeypatch):
    calls = []
    monkeypatch.setattr("agent.record_unmet_metric_request", lambda *a, **k: calls.append((a, k)))

    result = call_get_financial_fact(
        {"ticker": "AAPL", "metric": "effective_tax_rate"}, question="What is AAPL's effective tax rate?"
    )

    assert result is None
    assert calls == [
        (
            ("AAPL", "effective_tax_rate"),
            {"reason": "unknown_metric", "question": "What is AAPL's effective tax rate?"},
        )
    ]


def test_call_get_financial_fact_records_unmet_request_with_no_data_for_ticker(monkeypatch):
    calls = []
    monkeypatch.setattr("agent.get_metric", lambda *a, **k: None)
    monkeypatch.setattr("agent.record_unmet_metric_request", lambda *a, **k: calls.append((a, k)))

    result = call_get_financial_fact({"ticker": "PLTR", "metric": "revenue"})

    assert result is None
    assert calls == [(("PLTR", "revenue"), {"reason": "no_data_for_ticker", "question": None})]


def test_call_get_financial_fact_does_not_record_unmet_request_on_success(monkeypatch):
    calls = []
    monkeypatch.setattr("agent.get_metric", lambda *a, **k: {"value": 42})
    monkeypatch.setattr("agent.record_unmet_metric_request", lambda *a, **k: calls.append((a, k)))

    result = call_get_financial_fact({"ticker": "AAPL", "metric": "revenue"})

    assert result == {"value": 42}
    assert calls == []


def test_call_get_financial_fact_does_not_record_unmet_request_on_boundary_rejection(monkeypatch):
    # Malformed/invented args (an unrecognized extra key here) are a
    # different problem than "this formula doesn't exist" -- they
    # shouldn't pollute the unmet-metric-request signal with noise from
    # the model not following the schema.
    calls = []
    monkeypatch.setattr("agent.record_unmet_metric_request", lambda *a, **k: calls.append((a, k)))

    result = call_get_financial_fact({"ticker": "NVDA", "metric": "revenue", "segment": "Graphics"})

    assert result is None
    assert calls == []


def test_call_get_financial_fact_records_unmet_request_when_yoy_growth_has_no_data(monkeypatch):
    # Found in code review: get_yoy_growth() returning None for a
    # genuine no-prior-period-data reason (not a schema violation, the
    # metric/args are perfectly valid) was silently invisible to the
    # unmet-metric-request signal -- unlike the plain-metric path just
    # above, which already records this.
    calls = []
    monkeypatch.setattr("agent.get_yoy_growth", lambda *a, **k: None)
    monkeypatch.setattr("agent.record_unmet_metric_request", lambda *a, **k: calls.append((a, k)))

    result = call_get_financial_fact({"ticker": "AAPL", "metric": "revenue", "yoy_growth": True})

    assert result is None
    assert calls == [(("AAPL", "revenue"), {"reason": "no_data_for_ticker", "question": None})]


def test_call_get_financial_fact_records_unmet_request_when_multi_year_average_has_no_data(monkeypatch):
    calls = []
    monkeypatch.setattr("agent.get_multi_year_average", lambda *a, **k: None)
    monkeypatch.setattr("agent.record_unmet_metric_request", lambda *a, **k: calls.append((a, k)))

    result = call_get_financial_fact(
        {"ticker": "AAPL", "metric": "operating_margin", "start_fiscal_year": 2023, "end_fiscal_year": 2025}
    )

    assert result is None
    assert calls == [(("AAPL", "operating_margin"), {"reason": "no_data_for_ticker", "question": None})]


def test_call_get_financial_fact_does_not_record_unmet_request_for_yoy_growth_ratio_rejection(monkeypatch):
    calls = []
    monkeypatch.setattr("agent.record_unmet_metric_request", lambda *a, **k: calls.append((a, k)))

    result = call_get_financial_fact({"ticker": "NVDA", "metric": "asset_turnover", "yoy_growth": True})

    assert result is None
    assert calls == []


def test_call_get_financial_fact_does_not_record_unmet_request_for_multi_year_average_yoy_growth_rejection(monkeypatch):
    calls = []
    monkeypatch.setattr("agent.record_unmet_metric_request", lambda *a, **k: calls.append((a, k)))

    result = call_get_financial_fact(
        {"ticker": "AAPL", "metric": "revenue", "start_fiscal_year": 2023, "end_fiscal_year": 2025, "yoy_growth": True}
    )

    assert result is None
    assert calls == []


def test_call_get_financial_fact_does_not_record_unmet_request_when_metric_is_missing(monkeypatch):
    # Found in code review: a missing `metric` key entirely (the model
    # not following the schema, per this function's own docstring) is a
    # boundary violation like the invented-extra-key case, not a "this
    # formula doesn't exist" signal -- metric=None must not pollute the
    # unmet-metric-request signal.
    calls = []
    monkeypatch.setattr("agent.record_unmet_metric_request", lambda *a, **k: calls.append((a, k)))

    result = call_get_financial_fact({"ticker": "AAPL"})

    assert result is None
    assert calls == []


def test_call_compare_financial_metric_does_not_record_unmet_request_when_metric_is_missing(monkeypatch):
    calls = []
    monkeypatch.setattr("agent.record_unmet_metric_request", lambda *a, **k: calls.append((a, k)))

    result = call_compare_financial_metric({"anchor_ticker": "AAPL"})

    assert result == {}
    assert calls == []


# ---------------------------------------------------------------------------
# tool_call_rejected local-only debug logging: distinct from
# record_unmet_metric_request above -- these are schema-violation
# boundary rejections (the model not following the tool's schema), a
# different debugging need than "this formula doesn't exist yet."
# ---------------------------------------------------------------------------
def test_call_get_financial_fact_logs_rejection_for_unrecognized_extra_argument(monkeypatch):
    calls = []
    monkeypatch.setattr("agent.log_event", lambda category, **fields: calls.append((category, fields)))

    result = call_get_financial_fact({"ticker": "NVDA", "metric": "revenue", "segment": "Graphics"})

    assert result is None
    assert len(calls) == 1
    category, fields = calls[0]
    assert category == "tool_call_rejected"
    assert fields["tool"] == "get_financial_fact"
    assert fields["reason"] == "unrecognized_extra_argument"


def test_call_get_financial_fact_logs_rejection_for_unknown_ticker(monkeypatch):
    calls = []
    monkeypatch.setattr("agent.log_event", lambda category, **fields: calls.append((category, fields)))

    result = call_get_financial_fact({"ticker": "NOT-A-REAL-TICKER", "metric": "revenue"})

    assert result is None
    assert len(calls) == 1
    category, fields = calls[0]
    assert category == "tool_call_rejected"
    assert fields["reason"] == "ticker_not_in_enum"


def test_call_get_financial_fact_logs_rejection_for_invalid_multi_year_average_combo(monkeypatch):
    calls = []
    monkeypatch.setattr("agent.log_event", lambda category, **fields: calls.append((category, fields)))

    result = call_get_financial_fact({"ticker": "AAPL", "metric": "revenue", "start_fiscal_year": 2023})

    assert result is None
    assert len(calls) == 1
    category, fields = calls[0]
    assert category == "tool_call_rejected"
    assert fields["reason"] == "invalid_multi_year_average_combo"


def test_call_get_financial_fact_rejects_non_int_multi_year_average_years(monkeypatch):
    # Found in code review (2026-09-06): a numeric-STRING year (a real
    # shape of LLM tool-call quirk this file already documents elsewhere)
    # used to crash formulas.py's end_fiscal_year - start_fiscal_year
    # with an uncaught TypeError instead of degrading like every other
    # boundary check here.
    calls = []
    monkeypatch.setattr("agent.log_event", lambda category, **fields: calls.append((category, fields)))

    result = call_get_financial_fact(
        {"ticker": "AAPL", "metric": "revenue", "start_fiscal_year": "2023", "end_fiscal_year": "2025"}
    )

    assert result is None
    assert len(calls) == 1
    category, fields = calls[0]
    assert category == "tool_call_rejected"
    assert fields["reason"] == "invalid_multi_year_average_combo"


def test_call_get_financial_fact_rejects_non_int_fiscal_year(monkeypatch):
    # review §8: a non-int fiscal_year (e.g. a numeric string) doesn't
    # crash -- get_metric()/get_ratio() just fail to find a match and
    # return None, which used to record reason="no_data_for_ticker" via
    # record_unmet_metric_request(), polluting that "should we add a
    # formula for this" telemetry with a schema-violation false negative
    # instead of a real data gap.
    calls = []
    monkeypatch.setattr("agent.log_event", lambda category, **fields: calls.append((category, fields)))

    result = call_get_financial_fact({"ticker": "AAPL", "metric": "revenue", "fiscal_year": "2025"})

    assert result is None
    assert len(calls) == 1
    category, fields = calls[0]
    assert category == "tool_call_rejected"
    assert fields["reason"] == "invalid_fiscal_year_type"


def test_call_compare_financial_metric_rejects_non_int_fiscal_year(monkeypatch):
    # Parity with call_get_financial_fact above -- same fiscal_year
    # argument, same unvalidated read, same telemetry-pollution risk.
    calls = []
    monkeypatch.setattr("agent.log_event", lambda category, **fields: calls.append((category, fields)))

    result = call_compare_financial_metric({"anchor_ticker": "AAPL", "metric": "revenue", "fiscal_year": "2025"})

    assert result == {}
    assert len(calls) == 1
    category, fields = calls[0]
    assert category == "tool_call_rejected"
    assert fields["reason"] == "invalid_fiscal_year_type"


def test_call_get_financial_fact_rejects_non_hashable_ticker_without_crashing(monkeypatch):
    # Found in code review (2026-09-06): `ticker not in COMPANIES` raises
    # TypeError for an unhashable value (e.g. a list) instead of the
    # graceful rejection every other malformed-argument case gets.
    calls = []
    monkeypatch.setattr("agent.log_event", lambda category, **fields: calls.append((category, fields)))

    result = call_get_financial_fact({"ticker": ["AAPL"], "metric": "revenue"})

    assert result is None
    assert len(calls) == 1
    category, fields = calls[0]
    assert category == "tool_call_rejected"
    assert fields["reason"] == "ticker_wrong_type"


def test_call_get_financial_fact_rejects_non_hashable_metric_without_crashing(monkeypatch):
    calls = []
    monkeypatch.setattr("agent.log_event", lambda category, **fields: calls.append((category, fields)))

    result = call_get_financial_fact({"ticker": "AAPL", "metric": ["revenue"]})

    assert result is None
    assert len(calls) == 1
    category, fields = calls[0]
    assert category == "tool_call_rejected"
    assert fields["reason"] == "metric_wrong_type"


def test_call_get_financial_fact_logs_rejection_for_yoy_growth_unsupported_for_ratio(monkeypatch):
    calls = []
    monkeypatch.setattr("agent.log_event", lambda category, **fields: calls.append((category, fields)))

    result = call_get_financial_fact({"ticker": "NVDA", "metric": "asset_turnover", "yoy_growth": True})

    assert result is None
    assert len(calls) == 1
    category, fields = calls[0]
    assert category == "tool_call_rejected"
    assert fields["reason"] == "yoy_growth_unsupported_for_ratio"


def test_call_get_financial_fact_logs_rejection_for_missing_metric(monkeypatch):
    calls = []
    monkeypatch.setattr("agent.log_event", lambda category, **fields: calls.append((category, fields)))

    result = call_get_financial_fact({"ticker": "AAPL"})

    assert result is None
    assert len(calls) == 1
    category, fields = calls[0]
    assert category == "tool_call_rejected"
    assert fields["reason"] == "missing_required_argument"


def test_call_compare_financial_metric_logs_rejection_for_missing_metric(monkeypatch):
    calls = []
    monkeypatch.setattr("agent.log_event", lambda category, **fields: calls.append((category, fields)))

    result = call_compare_financial_metric({"anchor_ticker": "AAPL"})

    assert result == {}
    assert len(calls) == 1
    category, fields = calls[0]
    assert category == "tool_call_rejected"
    assert fields["reason"] == "missing_required_argument"


def test_call_get_financial_fact_does_not_log_rejection_on_success(monkeypatch):
    calls = []
    monkeypatch.setattr("agent.get_metric", lambda *a, **k: {"value": 42})
    monkeypatch.setattr("agent.log_event", lambda category, **fields: calls.append((category, fields)))

    result = call_get_financial_fact({"ticker": "AAPL", "metric": "revenue"})

    assert result == {"value": 42}
    assert calls == []


def test_call_compare_financial_metric_logs_rejection_for_unrecognized_extra_argument(monkeypatch):
    calls = []
    monkeypatch.setattr("agent.log_event", lambda category, **fields: calls.append((category, fields)))

    result = call_compare_financial_metric({"anchor_ticker": "NVDA", "metric": "revenue", "segment": "Graphics"})

    assert result == {}
    assert len(calls) == 1
    category, fields = calls[0]
    assert category == "tool_call_rejected"
    assert fields["tool"] == "compare_financial_metric"
    assert fields["reason"] == "unrecognized_extra_argument"


def test_call_compare_financial_metric_logs_rejection_for_unknown_ticker(monkeypatch):
    calls = []
    monkeypatch.setattr("agent.log_event", lambda category, **fields: calls.append((category, fields)))

    result = call_compare_financial_metric({"anchor_ticker": "NOT-A-REAL-TICKER", "metric": "revenue"})

    assert result == {}
    assert len(calls) == 1
    category, fields = calls[0]
    assert category == "tool_call_rejected"
    assert fields["reason"] == "anchor_ticker_not_in_enum"


def test_call_compare_financial_metric_rejects_non_hashable_ticker_without_crashing(monkeypatch):
    # Mirrors call_get_financial_fact's matching test — found in the same
    # code-review pass (2026-09-06).
    calls = []
    monkeypatch.setattr("agent.log_event", lambda category, **fields: calls.append((category, fields)))

    result = call_compare_financial_metric({"anchor_ticker": ["AAPL"], "metric": "revenue"})

    assert result == {}
    assert len(calls) == 1
    category, fields = calls[0]
    assert category == "tool_call_rejected"
    assert fields["reason"] == "anchor_ticker_wrong_type"


def test_call_compare_financial_metric_rejects_non_hashable_metric_without_crashing(monkeypatch):
    calls = []
    monkeypatch.setattr("agent.log_event", lambda category, **fields: calls.append((category, fields)))

    result = call_compare_financial_metric({"anchor_ticker": "AAPL", "metric": ["revenue"]})

    assert result == {}
    assert len(calls) == 1
    category, fields = calls[0]
    assert category == "tool_call_rejected"
    assert fields["reason"] == "metric_wrong_type"


def test_call_compare_financial_metric_does_not_log_rejection_on_success(monkeypatch):
    calls = []
    monkeypatch.setattr("agent.get_metric_all_companies", lambda *a, **k: {"AAPL": {"value": 1}})
    monkeypatch.setattr("agent.log_event", lambda category, **fields: calls.append((category, fields)))

    result = call_compare_financial_metric({"anchor_ticker": "AAPL", "metric": "revenue"})

    assert result == {"AAPL": {"value": 1}}
    assert calls == []


def test_call_compare_financial_metric_records_unmet_request_for_unknown_metric(monkeypatch):
    calls = []
    monkeypatch.setattr("agent.record_unmet_metric_request", lambda *a, **k: calls.append((a, k)))

    result = call_compare_financial_metric({"anchor_ticker": "AAPL", "metric": "effective_tax_rate"})

    assert result == {}
    assert calls == [(("AAPL", "effective_tax_rate"), {"reason": "unknown_metric", "question": None})]


def test_call_compare_financial_metric_records_unmet_request_with_no_data_for_ticker(monkeypatch):
    calls = []
    monkeypatch.setattr("agent.get_metric_all_companies", lambda *a, **k: {})
    monkeypatch.setattr("agent.record_unmet_metric_request", lambda *a, **k: calls.append((a, k)))

    result = call_compare_financial_metric({"anchor_ticker": "AAPL", "metric": "revenue"})

    assert result == {}
    assert calls == [(("AAPL", "revenue"), {"reason": "no_data_for_ticker", "question": None})]


def test_call_compare_financial_metric_does_not_record_unmet_request_on_success(monkeypatch):
    calls = []
    monkeypatch.setattr("agent.get_metric_all_companies", lambda *a, **k: {"AAPL": {"value": 1}})
    monkeypatch.setattr("agent.record_unmet_metric_request", lambda *a, **k: calls.append((a, k)))

    result = call_compare_financial_metric({"anchor_ticker": "AAPL", "metric": "revenue"})

    assert result == {"AAPL": {"value": 1}}
    assert calls == []


def test_call_compare_financial_metric_records_unmet_request_when_anchor_missing_from_partial_result(monkeypatch):
    # Found in code review (2026-09-07): instant metrics (total_assets
    # etc.) resolve each company independently with no requirement that
    # the requested anchor itself has data -- e.g. PLTR doesn't tag
    # inventory but AAPL/MSFT do. Without this, `if not result:` never
    # fires for a non-empty-but-anchor-missing result, so the caller
    # asked about PLTR specifically and gets a silently PLTR-less
    # comparison with zero signal anywhere that PLTR's own data is
    # missing.
    calls = []
    monkeypatch.setattr("agent.get_metric_all_companies", lambda *a, **k: {"AAPL": {"value": 1}, "MSFT": {"value": 2}})
    monkeypatch.setattr("agent.record_unmet_metric_request", lambda *a, **k: calls.append((a, k)))

    result = call_compare_financial_metric({"anchor_ticker": "PLTR", "metric": "inventory"})

    # Other companies' data is still returned -- genuinely useful partial
    # info -- but the anchor-specific gap is now signaled too.
    assert result == {"AAPL": {"value": 1}, "MSFT": {"value": 2}}
    assert calls == [(("PLTR", "inventory"), {"reason": "no_data_for_ticker", "question": None})]


def test_call_compare_financial_metric_rejects_unrecognized_extra_argument(monkeypatch):
    calls = []
    monkeypatch.setattr("agent.get_metric_all_companies", lambda *a, **k: calls.append((a, k)) or {"NVDA": {}})
    result = call_compare_financial_metric({"anchor_ticker": "NVDA", "metric": "revenue", "segment": "Graphics"})
    assert result == {}
    assert calls == []


def test_call_compare_financial_metric_gracefully_rejects_single_company_only_ratio():
    # return_on_assets/asset_turnover/cash_to_assets/inventory_turnover/
    # rd_intensity all have supports_cross_company=False in
    # RATIO_DEFINITIONS -- "asset_turnover" IS a recognized ratio name so
    # it passes compare_financial_metric's own boundary check (unlike
    # the old design, where it wasn't in RATIO_METRIC_FUNCTIONS at all
    # and was rejected right there), but get_ratio_all_companies() checks
    # the flag internally and returns the same graceful {} any other
    # unsupported metric gets, rather than a crash. This is deliberate
    # scoping (see formulas.get_return_on_assets's docstring for why
    # there's no cross-company version yet), not an oversight -- this
    # test locks in that it stays graceful regardless of which layer
    # does the rejecting.
    result = call_compare_financial_metric({"anchor_ticker": "AAPL", "metric": "asset_turnover"})
    assert result == {}


def test_call_compare_financial_metric_dispatches_operating_margin(monkeypatch):
    # get_ratio_all_companies() is the single generic dispatch point for
    # every cross-company-capable RATIO_DEFINITIONS entry now -- see
    # test_call_get_financial_fact_dispatches_operating_margin above for
    # why agent.get_ratio_all_companies is the correct monkeypatch seam.
    calls = []
    monkeypatch.setattr(
        "agent.get_ratio_all_companies",
        lambda ticker, ratio_name, fiscal_year, fiscal_period, period_end_date: calls.append(ratio_name)
        or {"NVDA": {"value": 60.0}},
    )
    result = call_compare_financial_metric({"anchor_ticker": "NVDA", "metric": "operating_margin"})
    assert result == {"NVDA": {"value": 60.0}}
    assert calls == ["operating_margin"]


def test_call_compare_financial_metric_dispatches_net_margin(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "agent.get_ratio_all_companies",
        lambda ticker, ratio_name, fiscal_year, fiscal_period, period_end_date: calls.append(ratio_name)
        or {"NVDA": {"value": 45.0}},
    )
    result = call_compare_financial_metric({"anchor_ticker": "NVDA", "metric": "net_margin"})
    assert result == {"NVDA": {"value": 45.0}}
    assert calls == ["net_margin"]


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
    monkeypatch.setattr("agent.call_get_financial_fact", lambda args, question=None: fact)
    all_results = []
    call = {"name": "get_financial_fact", "args": {"ticker": "NVDA", "metric": "gross_margin"}}

    content = _dispatch_tool_call(call, "q", all_results, set(), verbose=False)

    assert len(all_results) == 1
    assert all_results[0]["metadata"]["ticker"] == "NVDA"
    assert "[1]" in content


def test_dispatch_tool_call_get_financial_fact_none_uses_no_fact_message(monkeypatch):
    monkeypatch.setattr("agent.call_get_financial_fact", lambda args, question=None: None)
    monkeypatch.setattr("agent._format_no_fact_message", lambda args: "NO FACT MESSAGE")
    all_results = []
    call = {"name": "get_financial_fact", "args": {"ticker": "NVDA", "metric": "gross_margin"}}

    content = _dispatch_tool_call(call, "q", all_results, set(), verbose=False)

    assert all_results == []
    assert content == "NO FACT MESSAGE"


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
    monkeypatch.setattr("agent.call_compare_financial_metric", lambda args, question=None: data)
    all_results = []
    call = {"name": "compare_financial_metric", "args": {"metric": "gross_margin"}}

    content = _dispatch_tool_call(call, "q", all_results, set(), verbose=False)

    assert len(all_results) == 1
    assert "[1]" in content


def test_dispatch_tool_call_compare_financial_metric_empty_uses_no_comparison_message(monkeypatch):
    monkeypatch.setattr("agent.call_compare_financial_metric", lambda args, question=None: {})
    monkeypatch.setattr("agent._format_no_comparison_message", lambda args: "NO COMPARISON MESSAGE")
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

    monkeypatch.setattr("agent.hybrid_search", fake_hybrid_search)
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
        "agent.hybrid_search", lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not be called"))
    )
    calls = []
    monkeypatch.setattr("agent.log_event", lambda category, **fields: calls.append((category, fields)))
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
        "agent.hybrid_search", lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not be called"))
    )
    calls = []
    monkeypatch.setattr("agent.log_event", lambda category, **fields: calls.append((category, fields)))
    call = {"name": "search_filings", "args": {"query": "revenue", "ticker": ["AAPL"]}}

    content = _dispatch_tool_call(call, "q", [], set(), verbose=False)

    assert len(calls) == 1
    category, fields = calls[0]
    assert category == "tool_call_rejected"
    assert fields["reason"] == "ticker_wrong_type"
    assert "not a recognized company" in content


def test_dispatch_tool_call_search_filings_allows_no_ticker_filter(monkeypatch):
    # ticker is optional for this tool (a broad, unsure search) -- must
    # NOT be rejected just for being absent.
    monkeypatch.setattr("agent.hybrid_search", lambda query, ticker, top_k: [])
    calls = []
    monkeypatch.setattr("agent.log_event", lambda category, **fields: calls.append((category, fields)))
    call = {"name": "search_filings", "args": {"query": "revenue"}}

    _dispatch_tool_call(call, "q", [], set(), verbose=False)

    assert calls == []


# ---------------------------------------------------------------------------
# _should_retry_for_citations / _format_citation_retry_message
# (citation-verification retry loop, revisited Week 5j -> 2026-08-24 --
# see PROJECT_CONTEXT.md and docs/plans/2026-08-24-citation-
# retry-loop-design.md)
# ---------------------------------------------------------------------------
def test_should_retry_for_citations_true_with_warnings_and_not_yet_retried():
    assert (
        _should_retry_for_citations(["[1] claims 6478.0 (million) ..."], already_retried=False, backend="gemini")
        is True
    )


def test_should_retry_for_citations_false_once_already_retried():
    assert (
        _should_retry_for_citations(["[1] claims 6478.0 (million) ..."], already_retried=True, backend="gemini")
        is False
    )


def test_should_retry_for_citations_false_with_no_warnings_regardless_of_retried_flag():
    assert _should_retry_for_citations([], already_retried=False, backend="gemini") is False
    assert _should_retry_for_citations([], already_retried=True, backend="gemini") is False


def test_should_retry_for_citations_false_for_ollama_even_with_warnings_and_not_yet_retried():
    # Gated 2026-08-25 per live evidence in PROJECT_CONTEXT.md /
    # docs/plans/2026-08-24-citation-retry-loop-design.md:
    # this exact mechanism was tried and reverted once already (Week 5j)
    # because qwen2.5:7b-instruct couldn't reliably act on the corrective
    # feedback -- gated out for Ollama specifically rather than relying
    # on a single live re-run to prove it's safe now.
    assert (
        _should_retry_for_citations(["[1] claims 6478.0 (million) ..."], already_retried=False, backend="ollama")
        is False
    )


# ---------------------------------------------------------------------------
# run_agent() -- loop control flow only, via a fake/scripted backend (see
# module docstring for why this is fair game for a unit test despite
# run_agent() otherwise being live-only)
# ---------------------------------------------------------------------------
def test_run_agent_citation_retry_exhausting_budget_returns_pre_retry_answer_not_timeout(monkeypatch):
    # Regression test for a real bug found in code review (2026-08-25):
    # if the citation retry fires on the second-to-last iteration and
    # the model's follow-up turn makes a NEW tool call instead of just
    # re-answering, the loop used to hit the iteration cap on that tool
    # call and fall through to the generic "wasn't able to finish"
    # message -- discarding an already-produced, merely-warned answer
    # that was perfectly fine to return as-is. Post-hard-gate (Week 7),
    # "return as-is" now means through _finalize_answer(), which refuses
    # since warnings are still non-empty -- so the assertion checks the
    # pre-retry answer's warning made it into the refusal, not that the
    # raw pre-retry answer text comes back unchanged.
    monkeypatch.setattr("agent.MAX_TOOL_ITERATIONS", 2)

    final_answer_turn = ModelTurn(tool_calls=[], text="Apple's revenue was $100 billion [1].")
    followup_makes_new_tool_call = ModelTurn(tool_calls=[{"name": "search_filings", "args": {}}], text=None)

    def fake_start(question, system_prompt, tool_schemas):
        return {}, final_answer_turn

    def fake_send_followup(state, text):
        return followup_makes_new_tool_call

    monkeypatch.setattr("agent.BACKENDS", {"gemini": (fake_start, None, fake_send_followup)})
    monkeypatch.setattr("agent.verify_citations", lambda answer, all_results: ["[1] claims 100.0 ... doesn't appear"])
    log_calls = []
    monkeypatch.setattr("agent.log_event", lambda category, **fields: log_calls.append((category, fields)))

    answer, all_results, warnings = run_agent("What was Apple's revenue?", backend="gemini")

    assert answer != (
        "I wasn't able to finish answering within the allotted number of searches. "
        "Try asking a more specific or narrower question."
    )
    assert "[1] claims 100.0 ... doesn't appear" in answer
    assert warnings == ["[1] claims 100.0 ... doesn't appear"]
    # Local-only debug event (Week 7 follow-up): the self-correction
    # retry decision is logged, not just printed under --verbose.
    assert log_calls == [("citation_retry", {"backend": "gemini", "warnings": ["[1] claims 100.0 ... doesn't appear"]})]


def test_run_agent_citation_retry_not_attempted_for_ollama_backend(monkeypatch):
    # Companion sanity check: the same scripted scenario, but for the
    # gated-out backend, must never call send_followup at all -- if it
    # did, MAX_TOOL_ITERATIONS being hit would trip the same bug this
    # test's sibling guards against, just for the wrong reason (a retry
    # that should never have started). Post-hard-gate (Week 7), the
    # returned answer is now a refusal (no retry chance for ollama at
    # all), not the raw pass-through text.
    monkeypatch.setattr("agent.MAX_TOOL_ITERATIONS", 2)

    final_answer_turn = ModelTurn(tool_calls=[], text="Apple's revenue was $100 billion [1].")

    def fake_start(question, system_prompt, tool_schemas):
        return {}, final_answer_turn

    def fake_send_followup(state, text):
        raise AssertionError("send_followup should never be called for the ollama backend")

    monkeypatch.setattr("agent.BACKENDS", {"ollama": (fake_start, None, fake_send_followup)})
    monkeypatch.setattr("agent.verify_citations", lambda answer, all_results: ["[1] claims 100.0 ... doesn't appear"])

    answer, all_results, warnings = run_agent("What was Apple's revenue?", backend="ollama")

    assert "Apple's revenue was $100 billion [1]." not in answer
    assert "[1] claims 100.0 ... doesn't appear" in answer
    assert warnings == ["[1] claims 100.0 ... doesn't appear"]


# ---------------------------------------------------------------------------
# citation hard-gate (Week 7): run_agent() must refuse, not just warn, when
# citation verification still fails after any applicable retry
# ---------------------------------------------------------------------------
def test_run_agent_refuses_when_ollama_answer_has_unverified_citation(monkeypatch):
    final_answer_turn = ModelTurn(tool_calls=[], text="Apple's revenue was $100 billion [1].")

    def fake_start(question, system_prompt, tool_schemas):
        return {}, final_answer_turn

    monkeypatch.setattr("agent.BACKENDS", {"ollama": (fake_start, None, None)})
    monkeypatch.setattr("agent.verify_citations", lambda answer, all_results: ["[1] claims 100.0 ... doesn't appear"])

    answer, all_results, warnings = run_agent("What was Apple's revenue?", backend="ollama")

    assert answer == _format_refusal_message(["[1] claims 100.0 ... doesn't appear"])
    assert warnings == ["[1] claims 100.0 ... doesn't appear"]


def test_run_agent_returns_generic_timeout_message_unchanged_when_iterations_exhausted(monkeypatch):
    # The iteration-budget-exhausted fallback (no pre_retry_answer to fall
    # back to) always passes warnings=[] into _finalize_answer(), so this
    # locks in that routing it through the same choke point as every
    # other return site (code review, 2026-08-26) is a genuine no-op --
    # the generic message must still come back completely unchanged.
    monkeypatch.setattr("agent.MAX_TOOL_ITERATIONS", 1)

    keeps_calling_tools = ModelTurn(tool_calls=[{"name": "search_filings", "args": {}}], text=None)

    def fake_start(question, system_prompt, tool_schemas):
        return {}, keeps_calling_tools

    monkeypatch.setattr("agent.BACKENDS", {"ollama": (fake_start, None, None)})

    answer, all_results, warnings = run_agent("What was Apple's revenue?", backend="ollama")

    assert answer == (
        "I wasn't able to finish answering within the allotted number of searches. "
        "Try asking a more specific or narrower question."
    )
    assert warnings == []


def test_run_agent_refuses_when_gemini_retry_still_leaves_unverified_citation(monkeypatch):
    # The retry fires once (per _should_retry_for_citations), the model
    # produces a second final answer, but it's still unverified -- since
    # a retry was already spent, the loop must not retry again and must
    # gate on the second answer's warnings instead of returning it.
    first_answer_turn = ModelTurn(tool_calls=[], text="Apple's revenue was $100 billion [1].")
    second_answer_turn = ModelTurn(tool_calls=[], text="Apple's revenue was $105 billion [1].")

    def fake_start(question, system_prompt, tool_schemas):
        return {}, first_answer_turn

    def fake_send_followup(state, text):
        return second_answer_turn

    monkeypatch.setattr("agent.BACKENDS", {"gemini": (fake_start, None, fake_send_followup)})
    monkeypatch.setattr("agent.verify_citations", lambda answer, all_results: [f"[1] claims from: {answer}"])

    answer, all_results, warnings = run_agent("What was Apple's revenue?", backend="gemini")

    assert answer == _format_refusal_message(["[1] claims from: Apple's revenue was $105 billion [1]."])
    assert warnings == ["[1] claims from: Apple's revenue was $105 billion [1]."]


def test_run_agent_returns_answer_unchanged_when_no_citation_warnings(monkeypatch):
    final_answer_turn = ModelTurn(tool_calls=[], text="Apple's revenue was $100 billion [1].")

    def fake_start(question, system_prompt, tool_schemas):
        return {}, final_answer_turn

    monkeypatch.setattr("agent.BACKENDS", {"ollama": (fake_start, None, None)})
    monkeypatch.setattr("agent.verify_citations", lambda answer, all_results: [])

    answer, all_results, warnings = run_agent("What was Apple's revenue?", backend="ollama")

    assert answer == "Apple's revenue was $100 billion [1]."
    assert warnings == []


def test_finalize_answer_passes_through_when_no_warnings():
    assert _finalize_answer("the answer", [], []) == ("the answer", [], [])


def test_finalize_answer_refuses_when_warnings_present():
    warnings = ["[1] claims 100.0 ... doesn't appear"]
    answer, all_results, returned_warnings = _finalize_answer("the answer", warnings, ["result"])
    assert answer == _format_refusal_message(warnings)
    assert all_results == ["result"]
    assert returned_warnings == warnings


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


def test_format_citation_retry_message_includes_each_warning():
    warnings = [
        "[1] claims 6478.0 (million) but that value doesn't appear in the cited source",
        "[2] claims 42.0 (raw) but that value doesn't appear in the cited source",
    ]
    message = _format_citation_retry_message("Apple's tax rate was 17.9% [1].", warnings)
    for w in warnings:
        assert w in message


def test_format_citation_retry_message_includes_the_previous_answer():
    answer = "Apple's tax rate was 17.9% [1]."
    message = _format_citation_retry_message(answer, ["[1] claims ... doesn't appear"])
    assert answer in message


def test_format_citation_retry_message_tells_model_to_recheck_shown_sources_first():
    # Targets the aapl-employees-fy25 failure mode from Week 5j: the
    # retry gave up entirely instead of checking the 4 OTHER
    # already-retrieved chunks for a valid citation.
    message = _format_citation_retry_message("answer", ["[1] claims ... doesn't appear"])
    assert "already" in message.lower()


def test_format_citation_retry_message_permits_an_honest_refusal():
    message = _format_citation_retry_message("answer", ["[1] claims ... doesn't appear"])
    assert "refus" in message.lower() or "acceptable" in message.lower()


def test_format_citation_retry_message_forbids_inventing_or_estimating():
    message = _format_citation_retry_message("answer", ["[1] claims ... doesn't appear"])
    assert "invent" in message.lower() or "estimat" in message.lower()


def test_format_citation_retry_message_never_uses_final_attempt_deadline_pressure():
    # Regression guard for the exact Week 5j-diagnosed cause of a
    # fabrication regression: wording like "this is your final attempt"
    # pushed the model to fabricate an estimate on a previously-reliable
    # refusal question. Must never reappear in this message.
    message = _format_citation_retry_message("answer", ["[1] claims ... doesn't appear"])
    lowered = message.lower()
    assert "final attempt" not in lowered
    assert "last chance" not in lowered
