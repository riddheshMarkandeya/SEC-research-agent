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

from contextlib import contextmanager

from agent import (
    CALCULATE_TOOL_SCHEMA,
    FACT_TOOL_SCHEMA,
    SEARCH_TOOL_SCHEMA,
    SUBMIT_TOOL_SCHEMA,
    AgentResult,
    CitationWarning,
    _CITATION_RETRY_GUIDANCE,
    _FINAL_TURN_SUBMIT_MESSAGE,
    call_calculate,
    call_compare_financial_metric,
    call_get_financial_fact,
    collect_citation_warnings,
    _calculation_as_result,
    _comparison_as_results,
    _normalize_for_match,
    _number_candidates,
    _partition_submit_call,
    _quote_matches,
    _dispatch_tool_call,
    _finalize_answer,
    _format_citation_key,
    _format_citation_retry_message,
    _format_claim_retry_message,
    _format_fact_value,
    _format_no_comparison_message,
    _format_no_fact_message,
    _format_refusal_message,
    _format_results_block,
    _resolve_search_args,
    _should_force_final_submit,
    _should_retry_for_citations,
    validate_tool_args,
    run_agent,
    value_is_citation_verified,
    verify_citations,
    verify_claims,
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
# verify_citations -- uncited numeric claims (2026-09-09). The existing
# checks above only ever look at numbers already sitting near a [n]
# marker; a claim with NO marker anywhere near it was previously
# invisible to this function entirely. Found live (PROJECT_CONTEXT.md's
# 2026-08-25 "Formula registry extended" section): asked for
# msft-cash-to-assets-fy2025, the model self-computed the ratio from two
# separately-retrieved raw values and stated the result with zero
# citation marker nearby, in 2 of 4 manual runs.
# ---------------------------------------------------------------------------
def test_verify_citations_flags_a_bare_uncited_claim():
    answer = "Apple's cash to assets ratio was approximately 24.3%."
    warnings = verify_citations(answer, [])
    assert len(warnings) == 1
    assert "24.3" in warnings[0]
    assert "no citation" in warnings[0]


def test_verify_citations_reproduces_the_msft_cash_to_assets_case():
    # The actual observed shape: two properly-cited raw figures, then a
    # self-computed, entirely uncited derived percentage in the same
    # answer.
    results = [
        _fake_result(text="cash_and_equivalents = 20000000000.0 USD"),
        _fake_result(text="total_assets = 500000000000.0 USD"),
    ]
    answer = (
        "Microsoft's cash and cash equivalents were $20.0 billion [1], and its "
        "total assets were $500.0 billion [2]. This means cash made up "
        "approximately 4.0% of total assets."
    )
    warnings = verify_citations(answer, results)
    assert len(warnings) == 1
    assert "4.0" in warnings[0]


def test_verify_citations_flags_a_second_uncited_claim_comma_joined_to_a_real_citation():
    # Found in code review: an earlier version treated ANY claim within
    # window+no-sentence-break as covered by a marker, regardless of how
    # many OTHER claims sat between it and the marker -- a comma-joined
    # second, uncited claim in the SAME sentence as a real citation
    # (rather than msft-cash-to-assets' own separate-sentence phrasing)
    # slipped through completely undetected.
    results = [_fake_result(text="cash_and_equivalents = 20000000000.0 USD")]
    answer = "Microsoft's cash was $20 billion [1], representing approximately 4.0% of total assets."
    warnings = verify_citations(answer, results)
    assert len(warnings) == 1
    assert "4.0" in warnings[0]
    assert "no citation" in warnings[0]


def test_verify_citations_leading_marker_covers_every_reachable_claim_that_follows_it():
    # A leading marker attaches to EVERY reachable claim after it, not
    # just the first -- "Per the 10-Q filing [1], revenue was $X and
    # margin was Y%." is one clause introduced by [1] covering both
    # facts. (An earlier version of this test asserted the opposite --
    # only the first claim covered -- but that was this function's own
    # invented assumption, not an observed bug; the "attach to only the
    # nearest claim" design it was guarding is what code review later
    # found broke the more common multi-claim-per-citation phrasing --
    # see the next test.)
    results = [_fake_result(text="revenue = 109417000000.0 USD")]
    answer = "Per the 10-Q filing [1], revenue was $109,417 million and margin improved to 42%."
    assert verify_citations(answer, results) == []


def test_verify_citations_covers_every_reachable_claim_sharing_one_trailing_citation():
    # Found in code review: an earlier "at most one claim per marker"
    # design (added to fix the comma-joined uncited-claim bug below)
    # broke this common, legitimate phrasing -- three numbers, all
    # genuinely grounded in the one cited source, sharing a single
    # trailing citation. Attaching the marker to only its nearest claim
    # (20%) left the other two (10, 12) unattached to any citation at
    # all, wrongly flagged as uncited even though they're correct.
    results = [_fake_result(text="revenue = 10000000.0 USD, prior_revenue = 12000000.0 USD")]
    answer = "Revenue grew from $10 million to $12 million, a 20% increase [1]."
    warnings = verify_citations(answer, results)
    # The 20% is genuinely NOT in the cited source -- still correctly
    # caught by the existing misattribution check (_iter_citation_claims),
    # unaffected by this function. Only that one warning, not three.
    assert len(warnings) == 1
    assert "20.0" in warnings[0]
    assert "doesn't appear in the cited source" in warnings[0]


def test_verify_citations_does_not_treat_an_abbreviation_period_as_a_sentence_break():
    # Found in code review: an abbreviation period with nothing else
    # after it in the same clause ("U.S.") was registering as a false
    # sentence break, making a correctly-cited claim look unreachable
    # from its own marker and wrongly refusing an otherwise-correct
    # answer. Real financial-prose phrasing, not a contrived edge case.
    results = [_fake_result(text="revenue = 50000000000.0 USD")]
    answer = "Revenue was $50 billion, primarily from U.S. sales [1]."
    assert verify_citations(answer, results) == []


def test_verify_citations_extra_whitespace_before_a_marker_does_not_create_a_false_break():
    # Found in code review: an earlier _SENTENCE_BREAK regex used a
    # greedy `\s+` that could backtrack to a SHORTER whitespace match
    # whenever the maximal one failed the trailing-marker exception, so
    # two spaces before "[1]" (double-spaced LLM output, or markdown
    # normalization) still registered a false break -- the same
    # false-refusal bug the exception exists to prevent, just triggered
    # by extra whitespace instead of an abbreviation.
    results = [_fake_result(text="revenue = 50000000000.0 USD")]
    assert verify_citations("Revenue was $50 billion.  [1].", results) == []


def test_verify_citations_accepts_missing_a_break_for_a_lowercase_starting_sentence():
    # Documents a known, deliberately-accepted limitation (not a bug to
    # fix): the lowercase-letter exception that protects abbreviations
    # like "U.S." also means a genuine new sentence that happens to
    # start with a lowercase word is treated as NOT a break, so "30"
    # here is (wrongly, but harmlessly) considered reachable from [1] --
    # it's still correctly caught by the pre-existing misattribution
    # check (not in the cited source), just not ALSO double-reported as
    # a separate "uncited" claim. Rare in real prose (sentences start
    # capitalized), and a false NEGATIVE (silently missing a break)
    # rather than the false POSITIVE (wrongly refusing an otherwise-
    # correct answer) the exception exists to prevent -- accepted as the
    # safer side to err on. Locks in that choice so a future "fix"
    # doesn't reintroduce the original abbreviation false-positive.
    results = [_fake_result(text="revenue = 50000000000.0 USD")]
    answer = "Total costs were $30 million. revenue was $50 billion [1]."
    warnings = verify_citations(answer, results)
    assert len(warnings) == 1
    assert "doesn't appear in the cited source" in warnings[0]


def test_verify_citations_does_not_double_report_the_same_value_via_both_checks():
    # Found in code review: _iter_citation_claims's flat backward window
    # (character distance only, no sentence-boundary awareness) and
    # _iter_uncited_claims's sentence-aware reachability check define
    # "near a marker" differently -- a value can be misattributed by the
    # first (within its flat window) and simultaneously judged uncited
    # by the second (not reachable across the sentence boundary that
    # actually separates it from the marker). Only one warning should
    # surface, not a redundant restatement of the same problem.
    results = [_fake_result(text="revenue = 50000000000.0 USD")]
    answer = "Total costs were $30 million. Total revenue was $50 billion [1]."
    warnings = verify_citations(answer, results)
    assert len(warnings) == 1
    assert "30" in warnings[0]
    assert "doesn't appear in the cited source" in warnings[0]


def test_verify_citations_reports_two_different_misattributed_citations_with_the_same_value():
    # Found in code review: fixing the cross-loop duplicate above by
    # deduping on value+unit alone ALSO collapsed two genuinely
    # different, independently-broken citations that happen to share a
    # value -- silently dropping the fact that [2] is broken too, not
    # just [1]. Citation index must stay part of citation-claims' own
    # dedup key even though the cross-loop check (above) doesn't use it.
    results = [_fake_result(text="unrelated text one"), _fake_result(text="unrelated text two")]
    answer = "Revenue was $99 million [1]. Margin was $99 million [2]."
    warnings = verify_citations(answer, results)
    assert len(warnings) == 2
    assert any("[1]" in w for w in warnings)
    assert any("[2]" in w for w in warnings)


def test_verify_citations_uncited_claim_does_not_duplicate_windowed_warning():
    # A claim already flagged by the existing near-a-citation check
    # (misattributed, not uncited) must not ALSO get a second, redundant
    # "uncited" warning just because it happens to be counted once by
    # each loop -- it's near a marker, so the new check must skip it.
    results = [_fake_result(text="revenue = 109417000000.0 USD")]
    answer = "The year-over-year revenue growth was approximately 16.27%. [1] [2]"
    warnings = verify_citations(answer, [results[0], results[0]])
    assert len(warnings) == 1


def test_verify_citations_ignores_the_digit_inside_a_trailing_citation_marker():
    # Found while implementing the uncited-claim check: NUMBER_PATTERN
    # (numeric_utils.py) deliberately also matches the bare digit INSIDE
    # a "[n]" marker itself (documented there as harmless noise for
    # extract_numbers()'s other callers). Left unfiltered here, that
    # self-match would itself count as an unverifiable claim whenever
    # it's the LAST marker in the answer (nothing follows it to "cover"
    # it) -- a false positive on the single most common answer shape in
    # this codebase (one citation ending the sentence).
    results = [_fake_result(text="revenue = 109417000000.0 USD")]
    assert verify_citations("Apple's revenue was $109,417 million [1].", results) == []
    assert verify_citations("Revenue was $109,417 million [1] and [2].", results + results) == []


def test_verify_citations_ignores_non_claim_text_with_no_citation_at_all():
    # Dates/years/form-type mentions must stay excluded from the new
    # check the same way they're excluded from the existing one --
    # otherwise a plain, fully-qualitative sentence with a date in it
    # would wrongly refuse.
    answer = "Apple filed its 10-K on June 27, 2026, covering fiscal year 2026."
    assert verify_citations(answer, []) == []


def test_verify_citations_q4_not_disclosed_hint_text_does_not_trip_uncited_check():
    # The Q4-refusal hint text (agent.py's _Q4_NOT_DISCLOSED_HINT) can end
    # up echoed/paraphrased into a final answer -- confirm its own
    # wording contains nothing the new check would misread as an uncited
    # numeric claim.
    from agent import _Q4_NOT_DISCLOSED_HINT

    assert verify_citations(_Q4_NOT_DISCLOSED_HINT, []) == []


def test_format_refusal_message_renders_an_uncited_only_warning_list():
    warnings = verify_citations("The ratio was approximately 24.3%.", [])
    message = _format_refusal_message(warnings)
    assert "24.3" in message
    assert "no citation" in message
    assert "refusing this answer" in message


# ---------------------------------------------------------------------------
# collect_citation_warnings (2026-09-10) -- the structured counterpart to
# verify_citations(), added so callers (the FP/FN gate-measurement work,
# see docs/plans/2026-09-10-citation-gate-measurement-instrumentation.md)
# can tell WHICH of the two independent checks produced a given warning
# without parsing its wording. verify_citations() itself must stay a
# byte-identical string-list wrapper around this -- its warnings are
# interpolated into _format_refusal_message/_format_citation_retry_message
# prompt text, so changing that text would perturb model behavior mid-
# measurement.
# ---------------------------------------------------------------------------
def test_collect_citation_warnings_tags_the_cited_claim_check():
    results = [_fake_result(text="tax rate = 20 percent")]
    answer = "The tax rate was 16.28% [1]."
    warnings = collect_citation_warnings(answer, results)
    assert len(warnings) == 1
    assert warnings[0].check == "cited_claim_unsupported"
    assert warnings[0].citation_index == 1
    assert warnings[0].value == 16.28
    assert warnings[0].unit == "percent"


def test_collect_citation_warnings_tags_the_uncited_claim_check():
    answer = "The ratio was approximately 24.3%."
    warnings = collect_citation_warnings(answer, [])
    assert len(warnings) == 1
    assert warnings[0].check == "uncited_claim"
    assert warnings[0].citation_index is None
    assert warnings[0].value == 24.3
    assert warnings[0].unit == "percent"


def test_collect_citation_warnings_message_matches_verify_citations_string():
    results = [_fake_result(text="tax rate = 20 percent")]
    answer = "The tax rate was 16.28% [1]. The ratio was approximately 24.3%."
    structured = collect_citation_warnings(answer, results)
    assert [w.message for w in structured] == verify_citations(answer, results)


def test_verify_citations_output_is_unchanged_by_the_structured_split():
    # Runs across every existing fixture used above (both checks firing
    # together) to confirm the refactor didn't alter a single warning
    # string, not just the two cases spelled out individually above.
    results = [_fake_result(text="revenue = 109417000000.0 USD")]
    answer = "The year-over-year revenue growth was approximately 16.27%. [1] [2]"
    assert [w.message for w in collect_citation_warnings(answer, [results[0], results[0]])] == verify_citations(
        answer, [results[0], results[0]]
    )


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
# SUBMIT_TOOL_SCHEMA (2026-09-10) -- the structured-claims final-answer
# tool, see docs/plans/2026-09-10-structured-claims-citation-verification.md.
# Same {"type":"function","function":{...}} envelope every existing tool
# uses, so validate_tool_args() (exercised above) is reusable verbatim --
# these tests exercise ITS acceptance/rejection of submit_answer's actual
# shape, not validate_tool_args itself again.
# ---------------------------------------------------------------------------
def _valid_claim(**overrides):
    claim = {"value": 100.0, "unit": "raw", "citation_index": 1, "quote": "the value was 100"}
    claim.update(overrides)
    return claim


def test_submit_tool_schema_accepts_a_valid_payload():
    args = {"answer_text": "The value was 100 [1].", "claims": [_valid_claim()]}
    assert validate_tool_args("submit_answer", SUBMIT_TOOL_SCHEMA, args) is False


def test_submit_tool_schema_accepts_empty_claims():
    # A refusal ("the sources don't support this") is a valid answer with
    # zero numeric claims -- claims: [] must stay legal, no minItems.
    args = {"answer_text": "I can't confirm this from the sources provided.", "claims": []}
    assert validate_tool_args("submit_answer", SUBMIT_TOOL_SCHEMA, args) is False


def test_submit_tool_schema_rejects_missing_answer_text():
    args = {"claims": []}
    assert validate_tool_args("submit_answer", SUBMIT_TOOL_SCHEMA, args) is True


def test_submit_tool_schema_rejects_claim_missing_quote():
    claim = _valid_claim()
    del claim["quote"]
    args = {"answer_text": "text", "claims": [claim]}
    assert validate_tool_args("submit_answer", SUBMIT_TOOL_SCHEMA, args) is True


def test_submit_tool_schema_rejects_claim_missing_citation_index():
    claim = _valid_claim()
    del claim["citation_index"]
    args = {"answer_text": "text", "claims": [claim]}
    assert validate_tool_args("submit_answer", SUBMIT_TOOL_SCHEMA, args) is True


def test_submit_tool_schema_accepts_a_qualitative_claim_with_no_value_or_unit():
    # 2026-09-15: value/unit are no longer required, so a citation marker
    # supporting a purely qualitative fact can validly omit both.
    claim = {"citation_index": 1, "quote": "the value was 100"}
    args = {"answer_text": "text [1].", "claims": [claim]}
    assert validate_tool_args("submit_answer", SUBMIT_TOOL_SCHEMA, args) is False


def test_submit_tool_schema_rejects_invented_claim_key():
    args = {"answer_text": "text", "claims": [_valid_claim(confidence=0.9)]}
    assert validate_tool_args("submit_answer", SUBMIT_TOOL_SCHEMA, args) is True


def test_submit_tool_schema_rejects_unknown_unit():
    args = {"answer_text": "text", "claims": [_valid_claim(unit="dollars")]}
    assert validate_tool_args("submit_answer", SUBMIT_TOOL_SCHEMA, args) is True


def test_submit_tool_schema_rejects_non_integer_citation_index():
    args = {"answer_text": "text", "claims": [_valid_claim(citation_index="1")]}
    assert validate_tool_args("submit_answer", SUBMIT_TOOL_SCHEMA, args) is True


def test_submit_tool_schema_excluded_from_mcp_server_tool_schemas():
    # mcp_server.py exposes the individual tools over MCP, not the LLM
    # agent loop -- submit_answer is a final-answer mechanism internal to
    # agent.py's own loop and must never be offered there.
    import mcp_server

    assert SUBMIT_TOOL_SCHEMA not in mcp_server._TOOL_SCHEMAS


# ---------------------------------------------------------------------------
# CALCULATE_TOOL_SCHEMA (2026-09-11) -- lets the model perform verified
# arithmetic instead of a self-computed value that can never pass
# verify_claims (see docs/plans/2026-09-11-calculate-tool-and-stress-questions.md).
# Same envelope every tool uses, so these tests exercise validate_tool_args'
# acceptance/rejection of calculate's actual shape, same style as
# SUBMIT_TOOL_SCHEMA's tests above.
# ---------------------------------------------------------------------------
def _valid_calculate_args(**overrides):
    args = {
        "operation": "percent_of",
        "operand_a": 34550.0,
        "citation_index_a": 1,
        "unit_a": "million",
        "operand_b": 195201.0,
        "citation_index_b": 2,
        "unit_b": "million",
    }
    args.update(overrides)
    return args


def test_calculate_tool_schema_accepts_a_valid_payload():
    assert validate_tool_args("calculate", CALCULATE_TOOL_SCHEMA, _valid_calculate_args()) is False


def test_calculate_tool_schema_rejects_missing_operand():
    args = _valid_calculate_args()
    del args["operand_b"]
    assert validate_tool_args("calculate", CALCULATE_TOOL_SCHEMA, args) is True


def test_calculate_tool_schema_rejects_unknown_operation():
    assert validate_tool_args("calculate", CALCULATE_TOOL_SCHEMA, _valid_calculate_args(operation="square_root")) is True


def test_calculate_tool_schema_rejects_unknown_unit():
    assert validate_tool_args("calculate", CALCULATE_TOOL_SCHEMA, _valid_calculate_args(unit_a="dollars")) is True


def test_calculate_tool_schema_rejects_non_integer_citation_index():
    assert (
        validate_tool_args("calculate", CALCULATE_TOOL_SCHEMA, _valid_calculate_args(citation_index_a="1")) is True
    )


def test_calculate_tool_schema_rejects_invented_key():
    assert validate_tool_args("calculate", CALCULATE_TOOL_SCHEMA, _valid_calculate_args(confidence=0.9)) is True


def test_calculate_tool_schema_excluded_from_mcp_server_tool_schemas():
    # Same reasoning as submit_answer: citation_index_a/citation_index_b
    # are only meaningful within one _run_agent_impl run's own
    # all_results, not to a standalone MCP caller.
    import mcp_server

    assert CALCULATE_TOOL_SCHEMA not in mcp_server._TOOL_SCHEMAS


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
    assert "zero" in error.lower()


def test_call_calculate_rejects_divide_by_zero_for_plain_divide_too():
    all_results = [_fake_result(text="Value was $100 million."), _fake_result(text="Value was $0 million.")]
    args = _valid_calculate_args(operation="divide", operand_a=100.0, unit_a="million", operand_b=0.0)
    result, error = call_calculate(args, all_results)
    assert result is None
    assert "zero" in error.lower()


def test_call_calculate_rejects_out_of_range_citation_index():
    all_results = [_fake_result(text="R&D expense was $34,550 million.")]
    args = _valid_calculate_args(citation_index_b=5)
    result, error = call_calculate(args, all_results)
    assert result is None
    assert "[5]" in error or "5" in error


def test_call_calculate_rejects_operand_not_grounded_in_cited_source():
    all_results = [
        _fake_result(text="R&D expense was $34,550 million."),
        _fake_result(text="Cost of revenue was $60,000 million."),  # doesn't contain 195201
    ]
    result, error = call_calculate(_valid_calculate_args(), all_results)
    assert result is None
    assert "operand_b" in error
    assert "[2]" in error


def test_call_calculate_rejects_operand_a_not_grounded_names_it_specifically():
    all_results = [
        _fake_result(text="Cost of revenue was $60,000 million."),  # doesn't contain 34550
        _fake_result(text="Gross profit was $195,201 million."),
    ]
    result, error = call_calculate(_valid_calculate_args(), all_results)
    assert result is None
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
    from agent import _verify_one_claim

    assert _verify_one_claim(claim, all_results_with_calc) is None


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
    assert calc_result["value"] == 1e18  # sanity check on the premise

    entry = _calculation_as_result(calc_result, args)
    assert "e+" not in entry["text"].lower()
    assert "1000000000000000000" in entry["text"]

    # The real-world consequence: a claim citing this result must still
    # verify, the same end-to-end proof as the percent_of test above.
    all_results_with_calc = all_results + [entry]
    claim = {"value": 1e18, "unit": "raw", "citation_index": 3, "quote": entry["text"]}
    from agent import _verify_one_claim

    assert _verify_one_claim(claim, all_results_with_calc) is None


def test_calculation_as_result_has_metadata_required_by_format_results_block():
    all_results = [
        _fake_result(text="R&D expense was $34,550 million."),
        _fake_result(text="Gross profit was $195,201 million."),
    ]
    args = _valid_calculate_args()
    calc_result, _ = call_calculate(args, all_results)
    entry = _calculation_as_result(calc_result, args)
    # _format_results_block reads meta['ticker']/['form']/['reportDate'] --
    # a KeyError here would only surface live, the first time a
    # calculate result is ever rendered back to the model.
    block = _format_results_block([entry], 3)
    assert "[3]" in block


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
# _should_force_final_submit (final-turn safety net for the
# MAX_TOOL_ITERATIONS zero-slack bug -- BACKLOG.md, docs/decisions/
# 2026-09-16-final-turn-safety-net.md)
# ---------------------------------------------------------------------------
def test_should_force_final_submit_true_when_budget_exhausted_and_not_yet_attempted():
    assert _should_force_final_submit(already_attempted=False, calls_made=6, backend="gemini") is True


def test_should_force_final_submit_false_once_already_attempted():
    assert _should_force_final_submit(already_attempted=True, calls_made=6, backend="gemini") is False


def test_should_force_final_submit_false_when_budget_not_yet_exhausted():
    assert _should_force_final_submit(already_attempted=False, calls_made=5, backend="gemini") is False


def test_should_force_final_submit_false_for_ollama_even_with_budget_exhausted():
    # Gated like _CITATION_RETRY_BACKENDS/_FORCED_SUBMIT_BACKENDS above --
    # no live evidence yet for how Ollama responds to a directive nudge
    # under budget pressure, so this mechanism stays Gemini-only until
    # proven otherwise (see the decision doc).
    assert _should_force_final_submit(already_attempted=False, calls_made=6, backend="ollama") is False


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
    #
    # Still exercises the UNCHANGED pre_retry_answer/prose-fallback
    # mechanism (2026-09-10): a text reply on Gemini is always given one
    # forced submit_answer attempt first now, simulated here as ALSO
    # returning text (forcing doesn't always produce a clean submission --
    # see the design doc), before the scenario proceeds exactly as it did
    # before that mechanism existed. MAX_TOOL_ITERATIONS bumped by 1 (2 ->
    # 3) to make room for that extra forced round trip without changing
    # what the test is actually regression-testing. Bumped by one more
    # (2026-09-16) for the final-turn safety net's own reserved round
    # trip -- see the sibling test below for the same pattern.
    monkeypatch.setattr("agent.MAX_TOOL_ITERATIONS", 3)

    final_answer_turn = ModelTurn(tool_calls=[], text="Apple's revenue was $100 billion [1].")
    forced_attempt_still_text = ModelTurn(tool_calls=[], text="Apple's revenue was $100 billion [1].")
    followup_makes_new_tool_call = ModelTurn(tool_calls=[{"name": "search_filings", "args": {}}], text=None)
    # The model ignores the final-turn safety net's forced nudge too
    # (mock only -- Gemini's real hard constraint isn't exercised by
    # this fake), so the loop still falls through to the unmodified
    # post-loop pre_retry_answer fallback this test actually verifies.
    ignores_forced_nudge = ModelTurn(tool_calls=[{"name": "search_filings", "args": {}}], text=None)

    def fake_start(question, system_prompt, tool_schemas):
        return {}, final_answer_turn

    followups = iter([forced_attempt_still_text, followup_makes_new_tool_call])

    def fake_send_followup(state, text, force_tool=None):
        return next(followups)

    def fake_send_tool_results(state, results, force_tool=None):
        return ignores_forced_nudge

    monkeypatch.setattr("agent.BACKENDS", {"gemini": (fake_start, fake_send_tool_results, fake_send_followup)})
    monkeypatch.setattr(
        "agent.collect_citation_warnings",
        lambda answer, all_results: [
            CitationWarning(
                check="cited_claim_unsupported",
                citation_index=1,
                value=100.0,
                unit="raw",
                message="[1] claims 100.0 ... doesn't appear",
            )
        ],
    )
    log_calls = []
    monkeypatch.setattr("agent.log_event", lambda category, **fields: log_calls.append((category, fields)))

    answer, all_results, warnings, withheld_answer, _ = run_agent("What was Apple's revenue?", backend="gemini")

    assert answer != (
        "I wasn't able to finish answering within the allotted number of searches. "
        "Try asking a more specific or narrower question."
    )
    assert "[1] claims 100.0 ... doesn't appear" in answer
    assert warnings == ["[1] claims 100.0 ... doesn't appear"]
    # Local-only debug event (Week 7 follow-up): the self-correction
    # retry decision is logged, not just printed under --verbose.
    assert ("citation_retry", {"backend": "gemini", "warnings": ["[1] claims 100.0 ... doesn't appear"]}) in log_calls


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
    monkeypatch.setattr(
        "agent.collect_citation_warnings",
        lambda answer, all_results: [
            CitationWarning(
                check="cited_claim_unsupported",
                citation_index=1,
                value=100.0,
                unit="raw",
                message="[1] claims 100.0 ... doesn't appear",
            )
        ],
    )

    answer, all_results, warnings, withheld_answer, _ = run_agent("What was Apple's revenue?", backend="ollama")

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
    monkeypatch.setattr(
        "agent.collect_citation_warnings",
        lambda answer, all_results: [
            CitationWarning(
                check="cited_claim_unsupported",
                citation_index=1,
                value=100.0,
                unit="raw",
                message="[1] claims 100.0 ... doesn't appear",
            )
        ],
    )

    answer, all_results, warnings, withheld_answer, _ = run_agent("What was Apple's revenue?", backend="ollama")

    assert answer == _format_refusal_message(["[1] claims 100.0 ... doesn't appear"])
    assert warnings == ["[1] claims 100.0 ... doesn't appear"]
    assert withheld_answer == "Apple's revenue was $100 billion [1]."


def test_run_agent_refuses_a_bare_uncited_claim_end_to_end(monkeypatch):
    # Same wiring as the test above, but through the REAL verify_citations()
    # (not mocked) -- proves the uncited-claim check (agent.py's
    # _iter_uncited_claims, 2026-09-09) is actually reached by run_agent()'s
    # own control flow, not just correct in isolation. Reproduces the
    # msft-cash-to-assets-fy2025 shape: a self-computed percentage with no
    # citation marker anywhere near it.
    final_answer_turn = ModelTurn(
        tool_calls=[], text="Microsoft's cash to assets ratio was approximately 4.0%."
    )

    def fake_start(question, system_prompt, tool_schemas):
        return {}, final_answer_turn

    monkeypatch.setattr("agent.BACKENDS", {"ollama": (fake_start, None, None)})

    answer, all_results, warnings, withheld_answer, _ = run_agent(
        "What is Microsoft's cash to assets ratio?", backend="ollama"
    )

    assert "refusing this answer" in answer
    assert len(warnings) == 1
    assert "4.0" in warnings[0]
    assert "no citation" in warnings[0]
    assert withheld_answer == "Microsoft's cash to assets ratio was approximately 4.0%."


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

    answer, all_results, warnings, withheld_answer, _ = run_agent("What was Apple's revenue?", backend="ollama")

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
    monkeypatch.setattr("agent.MAX_TOOL_ITERATIONS", 2)

    keeps_calling_tools = ModelTurn(tool_calls=[{"name": "search_filings", "args": {}}], text=None)
    clean_refusal = _submit_turn(answer_text="I don't have enough data to answer.", claims=[])

    def fake_start(question, system_prompt, tool_schemas):
        return {}, keeps_calling_tools

    send_tool_results_calls = []

    def fake_send_tool_results(state, results, force_tool=None):
        send_tool_results_calls.append((results, force_tool))
        return clean_refusal if force_tool == "submit_answer" else keeps_calling_tools

    monkeypatch.setattr("agent.BACKENDS", {"gemini": (fake_start, fake_send_tool_results, None)})
    monkeypatch.setattr(
        "agent._dispatch_tool_call",
        lambda call, question, all_results, searched_tickers, verbose: "search result",
    )
    monkeypatch.setattr("agent.verify_claims", lambda claims, all_results, question, answer_text: [])

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


def test_run_agent_final_turn_safety_net_fires_at_most_once(monkeypatch):
    # An uncooperative model (realistic for Ollama's no-forcing case, or
    # Gemini simply ignoring the nudge) keeps requesting tool calls even
    # on the forced final turn -- the safety net must not fire a second
    # time; the loop falls through to the unmodified generic timeout.
    monkeypatch.setattr("agent.MAX_TOOL_ITERATIONS", 2)

    keeps_calling_tools = ModelTurn(tool_calls=[{"name": "search_filings", "args": {}}], text=None)

    def fake_start(question, system_prompt, tool_schemas):
        return {}, keeps_calling_tools

    send_tool_results_calls = []

    def fake_send_tool_results(state, results, force_tool=None):
        send_tool_results_calls.append((results, force_tool))
        return keeps_calling_tools  # never complies, whether forced or not

    monkeypatch.setattr("agent.BACKENDS", {"gemini": (fake_start, fake_send_tool_results, None)})
    monkeypatch.setattr(
        "agent._dispatch_tool_call",
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


def test_run_agent_final_turn_safety_net_not_applied_on_ollama(monkeypatch):
    # Gated to _FINAL_TURN_BACKENDS = {"gemini"} -- Ollama's behavior on
    # budget exhaustion must be completely unchanged by this mechanism.
    monkeypatch.setattr("agent.MAX_TOOL_ITERATIONS", 2)

    keeps_calling_tools = ModelTurn(tool_calls=[{"name": "search_filings", "args": {}}], text=None)

    def fake_start(question, system_prompt, tool_schemas):
        return {}, keeps_calling_tools

    def fake_send_tool_results(state, results, force_tool=None):
        assert force_tool is None, "the final-turn safety net must never fire for Ollama"
        return keeps_calling_tools

    monkeypatch.setattr("agent.BACKENDS", {"ollama": (fake_start, fake_send_tool_results, None)})
    monkeypatch.setattr(
        "agent._dispatch_tool_call",
        lambda call, question, all_results, searched_tickers, verbose: "search result",
    )

    answer, all_results, warnings, withheld_answer, _ = run_agent("What was the value?", backend="ollama")

    assert answer == (
        "I wasn't able to finish answering within the allotted number of searches. "
        "Try asking a more specific or narrower question."
    )


def test_final_turn_submit_message_contains_no_deadline_pressure_language():
    # Regression guard against reintroducing the documented fabrication
    # scar (agent.py's _CITATION_RETRY_GUIDANCE docstring): a prior
    # "final attempt" framing pushed the model to fabricate an estimate
    # on nvda-rd-expense-q4fy26-refusal instead of refusing honestly.
    lowered = _FINAL_TURN_SUBMIT_MESSAGE.lower()
    assert "final attempt" not in lowered
    assert "last chance" not in lowered
    assert "acceptable outcome" in lowered  # mirrors _CITATION_RETRY_GUIDANCE's proven phrasing


def test_run_agent_refuses_when_gemini_retry_still_leaves_unverified_citation(monkeypatch):
    # The retry fires once (per _should_retry_for_citations), the model
    # produces a second final answer, but it's still unverified -- since
    # a retry was already spent, the loop must not retry again and must
    # gate on the second answer's warnings instead of returning it.
    #
    # A text reply on Gemini is always given one forced submit_answer
    # attempt first now (2026-09-10) -- simulated here as also returning
    # text, so the scenario proceeds through the prose fallback exactly
    # as before that mechanism existed.
    first_answer_turn = ModelTurn(tool_calls=[], text="Apple's revenue was $100 billion [1].")
    forced_attempt_still_text = ModelTurn(tool_calls=[], text="Apple's revenue was $100 billion [1].")
    second_answer_turn = ModelTurn(tool_calls=[], text="Apple's revenue was $105 billion [1].")

    def fake_start(question, system_prompt, tool_schemas):
        return {}, first_answer_turn

    followups = iter([forced_attempt_still_text, second_answer_turn])

    def fake_send_followup(state, text, force_tool=None):
        return next(followups)

    monkeypatch.setattr(
        "agent.collect_citation_warnings",
        lambda answer, all_results: [
            CitationWarning(
                check="cited_claim_unsupported",
                citation_index=1,
                value=105.0,
                unit="billion",
                message=f"[1] claims from: {answer}",
            )
        ],
    )
    monkeypatch.setattr("agent.BACKENDS", {"gemini": (fake_start, None, fake_send_followup)})

    answer, all_results, warnings, withheld_answer, _ = run_agent("What was Apple's revenue?", backend="gemini")

    assert answer == _format_refusal_message(["[1] claims from: Apple's revenue was $105 billion [1]."])
    assert warnings == ["[1] claims from: Apple's revenue was $105 billion [1]."]
    assert withheld_answer == "Apple's revenue was $105 billion [1]."


def test_run_agent_returns_answer_unchanged_when_no_citation_warnings(monkeypatch):
    final_answer_turn = ModelTurn(tool_calls=[], text="Apple's revenue was $100 billion [1].")

    def fake_start(question, system_prompt, tool_schemas):
        return {}, final_answer_turn

    monkeypatch.setattr("agent.BACKENDS", {"ollama": (fake_start, None, None)})
    monkeypatch.setattr("agent.collect_citation_warnings", lambda answer, all_results: [])

    answer, all_results, warnings, withheld_answer, _ = run_agent("What was Apple's revenue?", backend="ollama")

    assert answer == "Apple's revenue was $100 billion [1]."
    assert warnings == []
    assert withheld_answer is None


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


def test_run_agent_spontaneous_submit_answer_with_valid_claims_passes(monkeypatch):
    def fake_start(question, system_prompt, tool_schemas):
        return {}, _submit_turn()

    monkeypatch.setattr("agent.BACKENDS", {"gemini": (fake_start, None, None)})
    monkeypatch.setattr(
        "agent.verify_claims", lambda claims, all_results, question, answer_text: []
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

    monkeypatch.setattr("agent.BACKENDS", {"gemini": (fake_start, fake_send_tool_results, None)})

    verify_calls = iter(
        [
            [
                CitationWarning(
                    check="quote_not_found", citation_index=1, value=100.0, unit="raw", message="[1] quote not found"
                )
            ],
            [],
        ]
    )
    monkeypatch.setattr("agent.verify_claims", lambda claims, all_results, question, answer_text: next(verify_calls))

    answer, all_results, warnings, withheld_answer, _ = run_agent("What was the value?", backend="gemini")

    assert answer == "The value was 100, corrected."
    assert warnings == []
    # The retry's corrective feedback was delivered as a submit_answer
    # TOOL RESULT (send_tool_results), not a plain follow-up turn -- keeps
    # the chat history well-formed (see the loop's own docstring on this).
    assert sent_results == [[{"name": "submit_answer", "content": sent_results[0][0]["content"]}]]
    assert "[1] quote not found" in sent_results[0][0]["content"]


def test_run_agent_submit_answer_bad_claims_refuses_immediately_on_ollama(monkeypatch):
    # No retry for Ollama (_CITATION_RETRY_BACKENDS is gemini-only,
    # unchanged) -- a bad structured submission refuses on the first try.
    def fake_start(question, system_prompt, tool_schemas):
        return {}, _submit_turn()

    monkeypatch.setattr("agent.BACKENDS", {"ollama": (fake_start, None, None)})
    monkeypatch.setattr(
        "agent.verify_claims",
        lambda claims, all_results, question, answer_text: [
            CitationWarning(check="quote_not_found", citation_index=1, value=100.0, unit="raw", message="[1] quote not found")
        ],
    )

    answer, all_results, warnings, withheld_answer, _ = run_agent("What was the value?", backend="ollama")

    assert "refusing this answer" in answer
    assert warnings == ["[1] quote not found"]
    assert withheld_answer == "The value was 100."


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

    monkeypatch.setattr("agent.BACKENDS", {"gemini": (fake_start, fake_send_tool_results, None)})
    monkeypatch.setattr("agent.verify_claims", lambda claims, all_results, question, answer_text: [])
    monkeypatch.setattr(
        "agent._dispatch_tool_call", lambda call, question, all_results, searched_tickers, verbose: "search results here"
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
    monkeypatch.setattr("agent.MAX_TOOL_ITERATIONS", 1)
    mixed_turn = ModelTurn(
        tool_calls=[
            {"name": "submit_answer", "args": {"answer_text": "The value was 100.", "claims": []}},
            {"name": "search_filings", "args": {"query": "revenue"}},
        ],
        text=None,
    )

    def fake_start(question, system_prompt, tool_schemas):
        return {}, mixed_turn

    monkeypatch.setattr("agent.BACKENDS", {"gemini": (fake_start, None, None)})
    monkeypatch.setattr("agent.verify_claims", lambda claims, all_results, question, answer_text: [])

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

    monkeypatch.setattr("agent.BACKENDS", {"gemini": (fake_start, None, fake_send_followup)})
    monkeypatch.setattr("agent.verify_claims", lambda claims, all_results, question, answer_text: [])

    answer, all_results, warnings, withheld_answer, _ = run_agent("What was Apple's revenue?", backend="gemini")

    assert answer == "Apple's revenue was $100 billion [1]."
    assert len(forced_calls) == 1
    assert forced_calls[0][1] == "submit_answer"  # force_tool was actually passed


def test_run_agent_text_reply_on_ollama_never_attempts_forcing(monkeypatch):
    # Companion sanity check to the forcing test above: Ollama has no
    # forcing mechanism at all (_FORCED_SUBMIT_BACKENDS is gemini-only) --
    # send_followup must never be called; a text reply goes straight to
    # the prose fallback.
    text_turn = ModelTurn(tool_calls=[], text="Apple's revenue was $100 billion [1].")

    def fake_start(question, system_prompt, tool_schemas):
        return {}, text_turn

    def fake_send_followup(state, text, force_tool=None):
        raise AssertionError("send_followup should never be called for the ollama backend")

    monkeypatch.setattr("agent.BACKENDS", {"ollama": (fake_start, None, fake_send_followup)})
    monkeypatch.setattr("agent.collect_citation_warnings", lambda answer, all_results: [])

    answer, all_results, warnings, withheld_answer, _ = run_agent("What was Apple's revenue?", backend="ollama")

    assert answer == "Apple's revenue was $100 billion [1]."


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

    monkeypatch.setattr("agent.BACKENDS", {"ollama": (fake_start, None, None)})

    answer, all_results, warnings, withheld_answer, _ = run_agent("What was the value?", backend="ollama")

    assert len(warnings) == 1
    assert "schema" in warnings[0].lower()
    assert withheld_answer == "The value was 100."


def test_run_agent_submit_answer_retry_exhausting_budget_reverifies_against_current_all_results(monkeypatch):
    # This is the actual proof that the pre_retry_answer staleness bug
    # (BACKLOG.md) is closed structurally for the submit_answer path, not
    # just described as closed: caches the RAW submit_args (not
    # pre-computed warnings) and re-runs verify_claims against whatever
    # all_results actually is by the time the budget runs out -- here,
    # grown by one more search dispatched AFTER the retry fired.
    # MAX_TOOL_ITERATIONS bumped by 1 again (3, was already bumped once
    # for the citation-retry mechanism) to make room for the final-turn
    # safety net's own reserved round trip (2026-09-16) without changing
    # what this test is actually regression-testing -- see the same
    # pattern already noted on the sibling test above (line ~2351).
    monkeypatch.setattr("agent.MAX_TOOL_ITERATIONS", 3)
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

    monkeypatch.setattr("agent.BACKENDS", {"gemini": (fake_start, fake_send_tool_results, None)})
    monkeypatch.setattr(
        "agent._dispatch_tool_call",
        lambda call, question, all_results, searched_tickers, verbose: all_results.append({"text": "extra"}) or "search result",
    )

    verify_calls = []

    def fake_verify_claims(claims, all_results, question, answer_text):
        verify_calls.append(len(all_results))
        return (
            []
            if len(all_results) > 0
            else [CitationWarning(check="quote_not_found", citation_index=1, value=100.0, unit="raw", message="bad")]
        )

    monkeypatch.setattr("agent.verify_claims", fake_verify_claims)

    answer, all_results, warnings, withheld_answer, _ = run_agent("What was the value?", backend="gemini")

    # Called once at retry-decision time (0 results, fails) and once more
    # at the exhausted-budget fallback (1 result by then, passes) --
    # proving the re-check sees the CURRENT all_results, not a stale
    # snapshot from when the retry fired.
    assert verify_calls == [0, 1]
    assert warnings == []
    assert answer == "The value was 100."


def test_run_agent_backend_default_follows_config(monkeypatch):
    # 2026-09-10: run_agent()'s backend default used to be a literal
    # "ollama" bound at function-definition time, ignoring
    # config.DEFAULT_BACKEND entirely. A caller that omits `backend`
    # must resolve to whatever DEFAULT_BACKEND currently is -- a
    # monkeypatched BACKENDS dict keyed only on a made-up backend name
    # proves it: the old hardcoded "ollama" default would KeyError here.
    final_answer_turn = ModelTurn(tool_calls=[], text="Apple's revenue was $100 billion [1].")

    def fake_start(question, system_prompt, tool_schemas):
        return {}, final_answer_turn

    monkeypatch.setattr("agent.DEFAULT_BACKEND", "totally-custom-backend")
    monkeypatch.setattr("agent.BACKENDS", {"totally-custom-backend": (fake_start, None, None)})
    monkeypatch.setattr("agent.collect_citation_warnings", lambda answer, all_results: [])

    answer, all_results, warnings, withheld_answer, _ = run_agent("What was Apple's revenue?")

    assert answer == "Apple's revenue was $100 billion [1]."


def test_run_agent_does_not_send_withheld_answer_to_the_span(monkeypatch):
    # traced_span() dual-writes to Langfuse when configured; the withheld
    # answer is exactly the text the hard gate decided NOT to trust, so
    # it must never leave the machine via that path -- log_event() (local
    # JSONL only, see tracing.py) is the only place it's allowed to go
    # (see _finalize_answer's own tests above).
    final_answer_turn = ModelTurn(tool_calls=[], text="Apple's revenue was $100 billion [1].")

    def fake_start(question, system_prompt, tool_schemas):
        return {}, final_answer_turn

    monkeypatch.setattr("agent.BACKENDS", {"ollama": (fake_start, None, None)})
    monkeypatch.setattr(
        "agent.collect_citation_warnings",
        lambda answer, all_results: [
            CitationWarning(
                check="cited_claim_unsupported",
                citation_index=1,
                value=100.0,
                unit="raw",
                message="[1] claims 100.0 ... doesn't appear",
            )
        ],
    )

    captured_outputs = []

    class _FakeSpan:
        def update(self, **kwargs):
            captured_outputs.append(kwargs)

    @contextmanager
    def fake_traced_span(as_type, name, input=None):
        yield _FakeSpan()

    monkeypatch.setattr("agent.traced_span", fake_traced_span)

    answer, all_results, warnings, withheld_answer, _ = run_agent("What was Apple's revenue?", backend="ollama")

    assert withheld_answer == "Apple's revenue was $100 billion [1]."
    assert len(captured_outputs) == 1
    output = captured_outputs[0]["output"]
    assert "Apple's revenue was $100 billion [1]." not in str(output)
    assert output["citation_checks"] == {"cited_claim_unsupported": 1}


def test_finalize_answer_passes_through_when_no_warnings():
    result = _finalize_answer("the answer", [], [], backend="ollama", retried=False)
    assert result == AgentResult("the answer", [], [], None, [])


def test_finalize_answer_refuses_when_warnings_present():
    warnings = [
        CitationWarning(
            check="cited_claim_unsupported",
            citation_index=1,
            value=100.0,
            unit="raw",
            message="[1] claims 100.0 ... doesn't appear",
        )
    ]
    result = _finalize_answer("the answer", warnings, ["result"], backend="ollama", retried=False)
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
            check="uncited_claim", citation_index=None, value=4.0, unit="percent", message="claims 4.0 (percent)..."
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
# holds, NOT re-derived by a second pass -- this is what lets
# eval_harness._citation_gate_evidence() stop calling
# collect_citation_warnings() (the PROSE checker) on a structured-path
# refusal, which could otherwise silently disagree with what actually
# refused it.
# ---------------------------------------------------------------------------
def test_finalize_answer_citation_warning_details_empty_when_passing():
    result = _finalize_answer("the answer", [], [], backend="ollama", retried=False)
    assert result.citation_warning_details == []


def test_finalize_answer_citation_warning_details_matches_the_actual_warnings():
    # A structured-path check value (quote_not_found) that the OLD prose
    # checker (collect_citation_warnings) could never produce -- proves
    # this field comes from the warnings _finalize_answer was actually
    # given, not from re-deriving via the prose pipeline.
    warnings = [
        CitationWarning(
            check="quote_not_found", citation_index=2, value=42.0, unit="million", message="[2] quote not found"
        )
    ]
    result = _finalize_answer("the answer", warnings, [], backend="gemini", retried=False)
    assert result.citation_warning_details == [
        {"check": "quote_not_found", "citation_index": 2, "value": 42.0, "unit": "million", "message": "[2] quote not found"}
    ]


def test_finalize_answer_logs_citation_gate_refused_with_check_counts(monkeypatch):
    log_calls = []
    monkeypatch.setattr("agent.log_event", lambda category, **fields: log_calls.append((category, fields)))
    warnings = [
        CitationWarning(
            check="cited_claim_unsupported", citation_index=1, value=100.0, unit="raw", message="[1] claims 100.0..."
        ),
        CitationWarning(
            check="uncited_claim", citation_index=None, value=4.0, unit="percent", message="claims 4.0 (percent)..."
        ),
    ]
    _finalize_answer("the model's answer", warnings, ["result"], backend="gemini", retried=True)

    assert len(log_calls) == 1
    category, fields = log_calls[0]
    assert category == "citation_gate_refused"
    assert fields["backend"] == "gemini"
    assert fields["retried"] is True
    assert fields["n_results"] == 1
    assert fields["checks"] == {"cited_claim_unsupported": 1, "uncited_claim": 1}
    assert fields["warnings"] == ["[1] claims 100.0...", "claims 4.0 (percent)..."]
    assert fields["withheld_answer"] == "the model's answer"


def test_finalize_answer_does_not_log_when_passing(monkeypatch):
    log_calls = []
    monkeypatch.setattr("agent.log_event", lambda category, **fields: log_calls.append((category, fields)))
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


# ---------------------------------------------------------------------------
# _normalize_for_match / _quote_matches (2026-09-10) -- fuzzy quote
# grounding for the structured-claims verifier. See
# docs/plans/2026-09-10-structured-claims-citation-verification.md for the
# full design reasoning (coverage vs. ratio, why autojunk=False is
# mandatory, the anchor-block floor).
# ---------------------------------------------------------------------------
def test_quote_matches_exact_modulo_whitespace():
    source = "Total revenue for fiscal year 2025 was  $416,161   million\naccording to the filing."
    quote = "Total revenue for fiscal year 2025 was $416,161 million"
    assert _quote_matches(quote, source) is True


def test_quote_matches_nfkc_curly_quote_and_en_dash_normalization():
    source = "The Company's remaining performance obligation \u2014 approximately $72.4 billion \u2014 is expected to be recognized."
    quote = "The Company's remaining performance obligation - approximately $72.4 billion"
    assert _quote_matches(quote, source) is True


def test_quote_matches_realistic_paraphrase_above_threshold():
    # A near-verbatim quote with one cosmetic word swap someone copying
    # by hand (or a model lightly restating) might introduce -- still
    # ~95% character-coverage against the source.
    source = "Net income for the three months ended June 27, 2026 was $23,434 million, compared to $21,448 million in the prior year period."
    quote = "Net income for the three months ended June 27 2026 was $23434 million"
    assert _quote_matches(quote, source) is True


def test_quote_matches_rejects_unrelated_text():
    source = "The Company's remaining performance obligation was approximately $72.4 billion as of January 31, 2026."
    quote = "Research and development expenses increased due to higher headcount and stock-based compensation."
    assert _quote_matches(quote, source) is False


def test_quote_matches_rejects_short_quotes():
    # A 2-character quote would otherwise match almost any source
    # trivially -- tells the checker nothing.
    source = "Total revenue for fiscal year 2025 was $416,161 million according to the filing."
    assert _quote_matches("$5", source) is False


def test_quote_matches_autojunk_false_regression():
    # SequenceMatcher's autojunk heuristic is keyed off len(b) -- the
    # SECOND positional argument -- not len(a); in _quote_matches's call
    # (SequenceMatcher(None, source_norm, quote_norm, ...)) that means
    # the QUOTE's length is what has to reach 200+ characters to trigger
    # it, not the source's (an earlier version of this test padded the
    # SOURCE to 200+ chars while leaving a ~90-char quote, which never
    # actually exercised autojunk at all -- both settings gave identical
    # results; found in code review 2026-09-10). Once triggered, autojunk
    # marks any character occurring in more than ~1% of the quote as
    # "popular junk" and excludes it from the initial anchor search --
    # devastating for prose, where common letters/short words legitimately
    # repeat many times over 200+ characters. This quote/source pair has
    # several small word-level differences (rose/increased,
    # likewise/also, stayed/remained, business/company) spread across a
    # 280+ character quote built from short repeated clauses ("for the
    # period", "compared to the prior period") -- with autojunk enabled
    # those repeated words become "popular" and get excluded as anchors,
    # collapsing coverage to ~0.65 (below the 0.90 threshold, i.e. a
    # false rejection); with autojunk=False coverage is ~0.93 (correctly
    # accepted). Confirmed by direct calculation before writing this
    # assertion, not by guessing at plausible numbers.
    quote = (
        "The company reported that total revenues for the period increased compared to the prior period "
        "and that total expenses for the period also increased compared to the prior period while total "
        "assets for the period remained roughly flat compared to the prior period overall for the company"
    )
    source = (
        "Filing note: the company reported that total revenues for the period rose compared to the prior period "
        "and that total expenses for the period likewise increased compared to the prior period while total "
        "assets for the period stayed roughly flat compared to the prior period overall for the business"
    )
    assert len(_normalize_for_match(quote)) >= 200
    assert _quote_matches(quote, source) is True


def test_normalize_for_match_collapses_whitespace_and_case():
    assert _normalize_for_match("Total  Revenue\nWas\t$5") == "total revenue was $5"


# ---------------------------------------------------------------------------
# _number_candidates (2026-09-10) -- generalizes what used to be
# _source_number_candidates(source_text) into a two-argument form:
# _number_candidates(text, *, unit_source=None) additionally reinterprets
# bare numbers in `text` under a unit word found in `unit_source` (a
# SEPARATE, typically longer text), defaulting unit_source to `text`
# itself when omitted -- which is exactly the old function's behavior,
# byte-for-byte, so the old prose-verification path (_iter_citation_claims)
# is completely unaffected by this change. See
# docs/plans/2026-09-10-structured-claims-citation-verification.md.
# ---------------------------------------------------------------------------
def test_number_candidates_finds_bare_number_under_its_own_unit():
    candidates = _number_candidates("Revenue was $5 billion.")
    assert ("scale", 5e9) in candidates


def test_number_candidates_unit_source_defaults_to_text_itself():
    # Byte-identical to the old _source_number_candidates(text) behavior
    # this generalizes -- found live on crm-rpo-fy26 (BACKLOG history):
    # a table states its unit once in a caption ("...consisted of the
    # following (in billions):") and leaves cell values bare ("$72.4").
    text = (
        "Remaining performance obligation consisted of the following (in billions):\n"
        "As of January 31, 2026 | $35.1 | $37.3 | $72.4"
    )
    candidates = _number_candidates(text)
    assert ("scale", 72.4e9) in candidates  # bare $72.4 reinterpreted under the "(in billions)" caption
    assert ("scale", 72.4) in candidates  # still also present as its own literal raw value


def test_number_candidates_reinterprets_under_a_separate_unit_source():
    # New capability: a claim's QUOTE ("$72.4") often won't itself carry
    # the unit word -- that's stated once in the chunk's caption, not
    # repeated per cell. Passing the whole chunk as unit_source lets a
    # short quote still resolve under it -- this is what lets Check C
    # (value attribution) verify a claim's quote against its cited
    # chunk's caption without requiring the quote to restate the unit.
    quote = "$72.4"
    chunk = "Remaining performance obligation consisted of the following (in billions): $35.1, $37.3, $72.4"
    candidates = _number_candidates(quote, unit_source=chunk)
    assert ("scale", 72.4e9) in candidates


def test_number_candidates_does_not_reinterpret_without_a_matching_caption_word():
    candidates = _number_candidates("$5", unit_source="no unit words here at all")
    assert candidates == [("scale", 5.0)]


# ---------------------------------------------------------------------------
# verify_claims (2026-09-10) -- the structured-claims counterpart to
# verify_citations()/collect_citation_warnings() above, used for a
# submit_answer tool call instead of prose. Combines three checks (quote
# grounding via _quote_matches, value attribution via _number_candidates,
# and a coverage cross-check against answer_text) into the same
# CitationWarning vocabulary, with 5 new `check` values:
# citation_out_of_range, quote_too_short, quote_not_found,
# value_not_in_quote, uncovered_number. See
# docs/plans/2026-09-10-structured-claims-citation-verification.md.
# ---------------------------------------------------------------------------
def _valid_submitted_claim(**overrides):
    claim = {
        "value": 100.0,
        "unit": "raw",
        "citation_index": 1,
        "quote": "the reported value for the period was exactly 100",
    }
    claim.update(overrides)
    return claim


def test_verify_claims_empty_claims_and_answer_passes():
    assert verify_claims([], [], "What was the value?", "I can't confirm this from the sources.") == []


def test_verify_claims_valid_claim_passes():
    results = [_fake_result(text="the reported value for the period was exactly 100 raw units")]
    claims = [_valid_submitted_claim()]
    answer_text = "The value was 100 [1]."
    assert verify_claims(claims, results, "What was the value?", answer_text) == []


def test_verify_claims_out_of_range_citation_index():
    claims = [_valid_submitted_claim(citation_index=5)]
    warnings = verify_claims(claims, [_fake_result()], "q", "The value was 100 [5].")
    assert len(warnings) == 1
    assert warnings[0].check == "citation_out_of_range"
    assert warnings[0].citation_index == 5


def test_verify_claims_quote_too_short():
    results = [_fake_result(text="the reported value for the period was exactly 100")]
    claims = [_valid_submitted_claim(quote="100")]
    warnings = verify_claims(claims, results, "q", "The value was 100 [1].")
    assert len(warnings) == 1
    assert warnings[0].check == "quote_too_short"


def test_verify_claims_quote_not_found():
    results = [_fake_result(text="Research and development expenses increased due to higher headcount.")]
    claims = [_valid_submitted_claim(quote="the reported value for the period was exactly 100")]
    warnings = verify_claims(claims, results, "q", "The value was 100 [1].")
    assert len(warnings) == 1
    assert warnings[0].check == "quote_not_found"


def test_verify_claims_value_not_in_quote():
    # Reproduces the same-sentence wrong-period substitution system-prompt
    # rule 5 exists to prevent: the quote genuinely appears in the source
    # (so quote_not_found doesn't fire), but the CLAIMED value belongs to
    # a different number stated elsewhere in that same source chunk.
    results = [_fake_result(text="Revenue was $100 million in Q1 and $200 million in Q2.")]
    claims = [_valid_submitted_claim(value=200.0, unit="million", quote="Revenue was $100 million in Q1")]
    warnings = verify_claims(claims, results, "q", "Revenue was $200 million [1].")
    assert len(warnings) == 1
    assert warnings[0].check == "value_not_in_quote"


# ---------------------------------------------------------------------------
# Qualitative claims (2026-09-15) -- a claims entry with no value/unit,
# used for a citation marker supporting a purely qualitative fact (e.g.
# a risk-factor bullet with no number in it). Previously value/unit were
# both required, so the model would invent a placeholder value (1) to
# satisfy the schema, which then always failed the value-in-quote check
# and refused an otherwise-correct qualitative answer.
# ---------------------------------------------------------------------------
def _qualitative_claim(**overrides):
    claim = {"citation_index": 1, "quote": "the reported value for the period was exactly 100"}
    claim.update(overrides)
    return claim


def test_verify_claims_qualitative_claim_with_real_quote_passes():
    results = [_fake_result(text="the reported value for the period was exactly 100 raw units")]
    claims = [_qualitative_claim()]
    answer_text = "The value was reported as significant [1]."
    assert verify_claims(claims, results, "q", answer_text) == []


def test_verify_claims_qualitative_claim_with_fabricated_quote_is_caught():
    # The closed-gap case: a fabricated qualitative citation would have
    # been silently trusted under the old claims: [] fallback for a
    # fully qualitative answer -- it's now actually grounded-checked.
    results = [_fake_result(text="Research and development expenses increased due to higher headcount.")]
    claims = [_qualitative_claim(quote="the reported value for the period was exactly 100")]
    warnings = verify_claims(claims, results, "q", "Something happened [1].")
    assert len(warnings) == 1
    assert warnings[0].check == "qualitative_quote_not_found"
    assert warnings[0].value is None
    assert warnings[0].unit is None


def test_verify_claims_qualitative_claim_quote_too_short():
    results = [_fake_result(text="the reported value for the period was exactly 100")]
    claims = [_qualitative_claim(quote="100")]
    warnings = verify_claims(claims, results, "q", "Something [1].")
    assert len(warnings) == 1
    assert warnings[0].check == "quote_too_short"
    assert "None" not in warnings[0].message


def test_verify_claims_malformed_claim_value_without_unit_does_not_crash():
    # A malformed claim doesn't count as covering its number either, so
    # this correctly produces BOTH warnings, not just one: malformed_claim
    # from _verify_one_claim, and uncovered_number from the coverage
    # cross-check (claimed_normalized skips the malformed claim, same as
    # it skips a qualitative one). The point of this test is that it
    # doesn't crash, not that there's exactly one warning.
    results = [_fake_result(text="the reported value for the period was exactly 100")]
    claims = [_qualitative_claim(value=100.0)]  # value with no unit -- malformed, not qualitative
    warnings = verify_claims(claims, results, "q", "The value was 100 [1].")
    checks = {w.check for w in warnings}
    assert checks == {"malformed_claim", "uncovered_number"}


def test_verify_claims_malformed_claim_unit_without_value_does_not_crash():
    results = [_fake_result(text="the reported value for the period was exactly 100")]
    claims = [_qualitative_claim(unit="million")]  # unit with no value -- malformed, not qualitative
    warnings = verify_claims(claims, results, "q", "Something [1].")
    assert len(warnings) == 1
    assert warnings[0].check == "malformed_claim"


def test_verify_claims_mix_of_qualitative_and_numeric_claims_grades_each_correctly():
    results = [
        _fake_result(text="the reported value for the period was exactly 100 raw units"),
        _fake_result(text="Research and development expenses increased due to higher headcount."),
    ]
    claims = [
        _valid_submitted_claim(citation_index=1),
        _qualitative_claim(citation_index=2, quote="Research and development expenses increased due to higher"),
    ]
    answer_text = "The value was 100 [1], driven by higher R&D spending [2]."
    assert verify_claims(claims, results, "q", answer_text) == []


def test_verify_one_claim_qualitative_claim_passes():
    from agent import _verify_one_claim

    results = [_fake_result(text="the reported value for the period was exactly 100 raw units")]
    assert _verify_one_claim(_qualitative_claim(), results) is None


def test_verify_claims_caption_unit_case_still_passes():
    # The documented live crm-rpo-fy26 fix must keep working under the
    # new checker: a bare "$72.4" quote, with the unit stated only in the
    # chunk's own caption, not repeated in the quote itself.
    source_text = (
        "Remaining performance obligation consisted of the following (in billions):\n"
        "As of January 31, 2026 | $35.1 | $37.3 | $72.4"
    )
    results = [_fake_result(text=source_text)]
    claims = [_valid_submitted_claim(value=72.4, unit="billion", quote="As of January 31, 2026 | $35.1 | $37.3 | $72.4")]
    answer_text = "The total remaining performance obligation was approximately $72.4 billion [1]."
    assert verify_claims(claims, results, "q", answer_text) == []


def test_verify_claims_accepts_a_parenthesized_negative_source_value():
    # End-to-end proof that numeric_utils.py's negative-number fix
    # (2026-09-11, found during a hand-rolled-complexity review) actually
    # closes the citation-verification gap, not just that extract_numbers()
    # in isolation returns the right sign: a claim of a NEGATIVE value,
    # citing a source that states it in the real accounting-parens
    # convention ("(1,234)"), must now verify cleanly -- this used to be
    # impossible (the claimed -1234.0 could never match the +1234.0
    # NUMBER_PATTERN incorrectly extracted from "(1,234)").
    results = [_fake_result(text="Net loss | (1,234) |")]
    claims = [_valid_submitted_claim(value=-1234.0, unit="raw", quote="Net loss | (1,234) |")]
    answer_text = "The company reported a net loss of $(1,234) [1]."
    assert verify_claims(claims, results, "q", answer_text) == []


def test_verify_claims_uncovered_number_in_answer_text():
    results = [_fake_result(text="the reported value for the period was exactly 100 raw units")]
    claims = [_valid_submitted_claim()]
    answer_text = "The value was 100 [1], roughly double last year's 50."
    warnings = verify_claims(claims, results, "q", answer_text)
    assert len(warnings) == 1
    assert warnings[0].check == "uncovered_number"
    assert warnings[0].value == 50.0


def test_verify_claims_multi_index_citation_bracket_digits_not_treated_as_uncovered_numbers():
    # Real false positive found live 2026-09-11 (41-question baseline
    # re-run after the structured-claims redesign): _CITATION_MARKER
    # (r"\[(\d+)\]") only strips a SINGLE-index bracket like "[1]" before
    # the coverage check runs extract_numbers() on answer_text -- a
    # multi-source bracket like "[1, 3, 5]" (crm-revenue-q1fy27's real
    # answer) or "[1, 17]" (msft-net-income-fy2025-indirect's) survives
    # untouched, so the bare digits 1/3/5 (or 1/17) inside it get
    # extracted as their own spurious uncovered-number claims and refuse
    # an otherwise fully-grounded answer. This is the SAME marker-format
    # gap BACKLOG.md already tracks for the old prose fallback path
    # (_CITATION_MARKER doesn't recognize "[1, 5]" as a marker at all)
    # -- it turns out to also hit the NEW structured-claims coverage
    # check, not just the fallback path as originally expected.
    results = [_fake_result(text="Revenue was $11,133 million, up 13 percent year-over-year.")]
    claims = [
        _valid_submitted_claim(value=11133.0, unit="million", quote="Revenue was $11,133 million"),
        _valid_submitted_claim(value=13.0, unit="percent", quote="up 13 percent year-over-year"),
    ]
    answer_text = "Revenue was $11,133 million, an increase of 13 percent year-over-year [1, 3, 5]."
    warnings = verify_claims(claims, results, "q", answer_text)
    uncovered = [w for w in warnings if w.check == "uncovered_number"]
    assert uncovered == [], uncovered


def test_verify_claims_question_echo_exempts_a_number_from_coverage():
    # A number the model is merely repeating from the user's OWN question
    # is not a claim it's asserting -- kills "3-year"-shaped noise (and
    # date/fiscal-year echoes) at the source, without a claims entry.
    results = [_fake_result(text="operating margin data")]
    claims = []
    question = "What was Apple's 3-year average operating margin from fiscal year 2023 through fiscal year 2025?"
    answer_text = "I can't confirm a 3-year average from the sources provided."
    assert verify_claims(claims, results, question, answer_text) == []


def test_verify_claims_non_claim_noise_in_answer_text_is_not_flagged():
    results = [_fake_result(text="Apple filed its 10-K covering the period.")]
    claims = []
    answer_text = "Apple filed its 10-K on June 27, 2026, covering fiscal year 2026, as discussed in Note 1."
    assert verify_claims(claims, results, "q", answer_text) == []


def test_verify_claims_does_not_duplicate_the_same_uncovered_number_twice():
    results = [_fake_result()]
    claims = []
    answer_text = "Total costs were $30 million. Total costs were $30 million again."
    warnings = verify_claims(claims, results, "q", answer_text)
    assert len(warnings) == 1


# ---------------------------------------------------------------------------
# table_grounding.py integration (2026-09-12) -- _verify_one_claim now
# checks a claim's value/quote against parsed table structure (row
# group/row label/column) whenever the value can be located in a table
# cell, instead of _quote_matches's flat coverage/anchor-floor check.
# See docs/plans/2026-09-12-structure-aware-table-quote-grounding.md for
# the full investigation: that flat check's 30-char contiguous-block
# floor rejected a genuine, correctly-reformatted quote purely because a
# segment label was short ("Intelligent Cloud", 18 normalized chars,
# under the floor; "Productivity and Business Processes", 36 chars,
# wasn't) -- and, worse, the SAME flat check already accepted real
# misattributions (wrong fiscal period, an inflated value) whenever the
# label happened to be long enough to clear the anchor on its own.
# Fixture is the real MSFT segment table (0001193125-26-191507, Q3
# FY2026 10-Q), reproduced verbatim, not paraphrased -- also used in
# tests/test_table_grounding.py.
# ---------------------------------------------------------------------------
_MSFT_SEGMENT_TABLE_TEXT = """Segment revenue, cost of revenue, operating expenses, and operating income were as follows during the periods presented:

<TABLE>
| (In millions) | Three Months EndedMarch 31, | Nine Months EndedMarch 31, |  |  |
| --- | --- | --- | --- | --- |
| 2026 | 2025 | 2026 | 2025 |  |
| Productivity and Business Processes |  |  |  |  |
| Revenue | $35,013 | $29,944 | $102,149 | $87,698 |
| Cost of revenue | 6,197 | 5,517 | 18,028 | 16,380 |
| Operating expenses | 7,843 | 7,048 | 22,142 | 20,538 |
| Operating income | $20,973 | $17,379 | $61,979 | $50,780 |
| Intelligent Cloud |  |  |  |  |
| Revenue | $34,681 | $26,751 | $98,485 | $76,387 |
| Cost of revenue | 15,120 | 10,307 | 41,000 | 28,326 |
| Operating expenses | 5,808 | 5,349 | 16,468 | 15,612 |
| Operating income | $13,753 | $11,095 | $41,017 | $32,449 |
| More Personal Computing |  |  |  |  |
| Revenue | $13,192 | $13,371 | $41,198 | $41,198 |
| Cost of revenue | 5,511 | 6,095 | 17,821 | 19,111 |
| Operating expenses | 4,009 | 3,750 | 11,739 | 11,111 |
| Operating income | $3,672 | $3,526 | $11,638 | $10,976 |
| Total |  |  |  |  |
| Revenue | $82,886 | $70,066 | $241,832 | $205,283 |
| Cost of revenue | 26,828 | 21,919 | 76,849 | 63,817 |
| Operating expenses | 17,660 | 16,147 | 50,349 | 47,261 |
| Operating income | $38,398 | $32,000 | $114,634 | $94,205 |
</TABLE>"""


def test_verify_claims_accepts_a_reformatted_quote_under_a_short_segment_label():
    # The real reported bug: whether this claim passed used to depend
    # only on segment-label LENGTH, not on whether the quote was
    # genuinely faithful to the source.
    results = [_fake_result(text=_MSFT_SEGMENT_TABLE_TEXT)]
    claims = [_valid_submitted_claim(value=34681.0, unit="million", quote="Intelligent Cloud\nRevenue $34,681")]
    answer_text = "Microsoft's Intelligent Cloud segment revenue was $34,681 million [1]."
    assert verify_claims(claims, results, "q", answer_text) == []


def test_verify_claims_still_rejects_a_value_spliced_across_a_row_boundary():
    # Guards the hole an adversarial review found in an earlier candidate
    # fix (relaxing the flat anchor floor via gap-content locality): a
    # markdown row break and an empty table cell normalize to the
    # identical string, so that fix let a quote splice one row's value
    # onto an unrelated adjacent row's label. $50,780 is Productivity &
    # Business Processes' own nine-month FY2025 operating income --
    # attributing it to Intelligent Cloud must still refuse.
    results = [_fake_result(text=_MSFT_SEGMENT_TABLE_TEXT)]
    claims = [_valid_submitted_claim(
        value=50780.0, unit="million",
        quote="$50,780 Intelligent Cloud Revenue $34,681",
    )]
    answer_text = "Intelligent Cloud's nine-month operating income was $50,780 million [1]."
    warnings = verify_claims(claims, results, "q", answer_text)
    assert len(warnings) == 1
    assert warnings[0].check == "quote_not_found"


def test_verify_claims_table_grounding_overrides_the_anchor_path_false_accept():
    # This exact quote passes the OLD flat _quote_matches check on its
    # own (confirmed directly against _quote_matches while investigating
    # this fix): "Productivity and Business Processes" alone is 36
    # normalized characters, clearing the 30-char anchor floor with no
    # need for the "2025"/"$35,013" pairing to make any sense. $35,013 is
    # that segment's THREE-MONTH FY2026 revenue, not FY2025's -- table
    # grounding is authoritative here specifically so this kind of
    # pre-existing false accept can't survive.
    #
    # Corrected 2026-09-13: an earlier version of this test (during this
    # exact redesign) asserted the region-scoped rewrite should ALSO
    # accept this, reasoning it was the same already-accepted "same-row"
    # tradeoff as citing a sibling column's bare VALUE. That reasoning
    # was wrong, caught by an independent review of the redesign: "2025"
    # is one of two distinct year labels in the header row ("2026 |
    # 2025 | 2026 | 2025"), and citing it ALONE (without "2026", the
    # correct one for this cell) is a cherry-picked wrong-period LABEL,
    # not a benign same-row value citation -- the yesterday-committed
    # design (before this whole redesign) rejected this exact case too,
    # confirmed directly, so accepting it was a real regression the
    # redesign introduced, not a deliberate, already-accepted tradeoff.
    # quote_is_grounded's cherry-pick check (see table_grounding.py) is
    # what restores the correct rejection.
    results = [_fake_result(text=_MSFT_SEGMENT_TABLE_TEXT)]
    assert _quote_matches(
        "2025 Productivity and Business Processes Revenue $35,013",
        _MSFT_SEGMENT_TABLE_TEXT,
    ) is True
    claims = [_valid_submitted_claim(
        value=35013.0, unit="million",
        quote="2025 Productivity and Business Processes Revenue $35,013",
    )]
    answer_text = "Productivity and Business Processes revenue was $35,013 million [1]."
    warnings = verify_claims(claims, results, "q", answer_text)
    assert len(warnings) == 1
    assert warnings[0].check == "quote_not_found"


def test_verify_claims_falls_back_to_quote_matches_for_a_value_only_in_prose():
    # A chunk can hold both a table and prose; a value stated only in
    # the prose portion must still verify via the ordinary flat-text
    # path, not be treated as an ungrounded table claim.
    text = "Total headcount was 228,000 employees, as discussed below.\n\n" + _MSFT_SEGMENT_TABLE_TEXT
    results = [_fake_result(text=text)]
    claims = [_valid_submitted_claim(value=228000.0, unit="raw", quote="Total headcount was 228,000 employees")]
    answer_text = "Total headcount was 228,000 [1]."
    assert verify_claims(claims, results, "q", answer_text) == []


# ---------------------------------------------------------------------------
# table_grounding.py region-scoped redesign (2026-09-13) -- end-to-end
# regression tests for the two REAL failures a live 47-question eval
# baseline found in the original word-vocabulary design. Real filing
# text (CRM's remaining-performance-obligation table; NVIDIA's segment
# table), not paraphrased -- see docs/plans/2026-09-13-table-grounding-
# region-scoped-matching.md for the full diagnosis.
# ---------------------------------------------------------------------------
_CRM_RPO_TABLE_TEXT = """Remaining performance obligation consisted of the following (in billions):

<TABLE>
| Current | Noncurrent | Total |  |
| --- | --- | --- | --- |
| As of January 31, 2026 (1) | $35.1 | $37.3 | $72.4 |
| As of January 31, 2025 | $30.2 | $33.2 | $63.4 |
</TABLE>"""

_NVDA_SEGMENT_TABLE_TEXT = """The table below presents details of our reportable segments.

<TABLE>
| Compute & Networking | Graphics | Total |  |
| --- | --- | --- | --- |
| (In millions) |  |  |  |
| Three Months Ended Apr 26, 2026 |  |  |  |
| Revenue | $74,550 | $7,065 | $81,615 |
| Other segment items (1) | 21,215 | 4,124 | 25,339 |
| Operating income | $53,335 | $2,941 | $56,276 |
</TABLE>"""


def test_verify_claims_accepts_crm_full_row_verbatim_quote_for_three_independent_claims():
    # The real regression: the model quotes an entire table row verbatim
    # for EACH of 3 claims (Current/Noncurrent/Total, three genuinely
    # different metrics in one row) -- all 3 were wrongly refused by the
    # original per-cell word-vocabulary design, since it excluded
    # sibling-column content from any one cell's allowed vocabulary.
    results = [_fake_result(text=_CRM_RPO_TABLE_TEXT)]
    quote = "| As of January 31, 2026 (1) | $35.1 | $37.3 | $72.4 |"
    claims = [
        _valid_submitted_claim(value=72.4, unit="billion", quote=quote),
        _valid_submitted_claim(value=35.1, unit="billion", quote=quote),
        _valid_submitted_claim(value=37.3, unit="billion", quote=quote),
    ]
    answer_text = (
        "As of January 31, 2026, Salesforce's total remaining performance obligation was "
        "$72.4 billion [1], consisting of $35.1 billion current [1] and $37.3 billion noncurrent [1]."
    )
    assert verify_claims(claims, results, "q", answer_text) == []


def test_verify_claims_accepts_nvidia_multiline_quote_spanning_header_and_data_rows():
    # The second real regression: the model's quote spans the column-
    # header row, the separator row, a caption row, a period-label row,
    # AND the data row, all verbatim -- refused by the original design
    # for the same reason as the CRM case.
    results = [_fake_result(text=_NVDA_SEGMENT_TABLE_TEXT)]
    quote = (
        "| Compute & Networking | Graphics | Total |  |\n"
        "| --- | --- | --- | --- |\n"
        "| (In millions) |  |  |  |\n"
        "| Three Months Ended Apr 26, 2026 |  |  |  |\n"
        "| Revenue | $74,550 | $7,065 | $81,615 |"
    )
    claims = [
        _valid_submitted_claim(value=74550.0, unit="million", quote=quote),
        _valid_submitted_claim(value=7065.0, unit="million", quote=quote),
    ]
    answer_text = (
        "For the quarter ended April 26, 2026, NVIDIA's Compute & Networking segment generated "
        "$74,550 million in revenue [1], while the Graphics segment generated $7,065 million [1]."
    )
    assert verify_claims(claims, results, "q", answer_text) == []


def test_verify_claims_still_rejects_cross_segment_steal_via_near_tolerance_cell():
    # Regression B, end to end: Intelligent Cloud's real revenue
    # ($34,681M) and Productivity & Business Processes' real revenue
    # ($35,013M) are ~0.95% apart -- within the standard tolerance of
    # each other -- so a claim of $35,013M can locate BOTH cells. A quote
    # naming Intelligent Cloud with Productivity's real value must still
    # be refused.
    results = [_fake_result(text=_MSFT_SEGMENT_TABLE_TEXT)]
    claims = [_valid_submitted_claim(
        value=35013.0, unit="million",
        quote="Intelligent Cloud Revenue $35,013",
    )]
    answer_text = "Intelligent Cloud's revenue was $35,013 million [1]."
    warnings = verify_claims(claims, results, "q", answer_text)
    assert len(warnings) == 1
    assert warnings[0].check == "quote_not_found"


def test_verify_claims_rejects_a_full_wrong_period_phrase_not_just_a_bare_year():
    # HIGH-severity finding from an independent review of this exact
    # redesign, end to end: a quote citing the FULL, plausible-sounding
    # WRONG period phrase ("Three Months EndedMarch 31, 2026") alongside
    # a value that's actually the OTHER period's ($102,149M is
    # Productivity's NINE-month figure, not its three-month one) --
    # confirmed both checks 1-2 (coverage, number-presence) pass on their
    # own, since both the phrase and the value are genuinely somewhere in
    # the region; the cherry-pick check (some but not all of the header
    # row's own two period phrases) is what catches this specifically.
    results = [_fake_result(text=_MSFT_SEGMENT_TABLE_TEXT)]
    claims = [_valid_submitted_claim(
        value=102149.0, unit="million",
        quote="Three Months EndedMarch 31, 2026 Productivity and Business Processes Revenue $102,149",
    )]
    answer_text = "Productivity and Business Processes' quarterly revenue was $102,149 million [1]."
    warnings = verify_claims(claims, results, "q", answer_text)
    assert len(warnings) == 1
    assert warnings[0].check == "quote_not_found"


def test_verify_claims_rejects_nvidia_graphics_mislabel_of_computes_value():
    # Same finding, NVIDIA's segment table: $74,550M is Compute &
    # Networking's real revenue: a quote attributing it to "Graphics"
    # alone (not reproducing the whole "Compute & Networking | Graphics
    # | Total" header row) must be refused.
    results = [_fake_result(text=_NVDA_SEGMENT_TABLE_TEXT)]
    claims = [_valid_submitted_claim(value=74550.0, unit="million", quote="Graphics Revenue $74,550")]
    answer_text = "NVIDIA's Graphics segment generated $74,550 million in revenue [1]."
    warnings = verify_claims(claims, results, "q", answer_text)
    assert len(warnings) == 1
    assert warnings[0].check == "quote_not_found"


# ---------------------------------------------------------------------------
# _format_claim_retry_message (2026-09-10) -- structured-claims retry
# wording, sharing _CITATION_RETRY_GUIDANCE with the old prose retry
# message so the two can't drift apart. See
# docs/plans/2026-09-10-structured-claims-citation-verification.md.
# ---------------------------------------------------------------------------
def test_format_claim_retry_message_includes_each_warning():
    warnings = [
        CitationWarning(check="quote_not_found", citation_index=1, value=100.0, unit="raw", message="[1] quote missing"),
        CitationWarning(check="value_not_in_quote", citation_index=2, value=42.0, unit="raw", message="[2] value missing"),
    ]
    message = _format_claim_retry_message("the answer", warnings)
    assert "[1] quote missing" in message
    assert "[2] value missing" in message


def test_format_claim_retry_message_includes_the_previous_answer():
    message = _format_claim_retry_message("Apple's revenue was $100 billion.", [])
    assert "Apple's revenue was $100 billion." in message


def test_format_claim_retry_message_shares_guidance_with_prose_retry_message():
    # Both messages must share the exact same corrective guidance text --
    # extracted specifically so they can't drift apart independently.
    prose = _format_citation_retry_message("answer", ["warning"])
    claim = _format_claim_retry_message("answer", [])
    assert _CITATION_RETRY_GUIDANCE in prose
    assert _CITATION_RETRY_GUIDANCE in claim


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
