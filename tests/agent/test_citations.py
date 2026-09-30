"""
Unit tests for citations.py: the eval grader's value_is_citation_verified,
quote matching, number candidates, and verify_claims for numeric,
qualitative and table-grounded claims.
"""

import pytest

from sec_agent.agent.calculate import call_calculate, _calculation_as_result
from sec_agent.agent.citations import (
    _CITATION_WINDOW_CHARS,
    _normalize_for_match,
    _number_candidates,
    _quote_matches,
    _strip_citation_header,
    value_is_citation_verified,
    verify_claims,
)
from tests.agent.helpers import _fake_result, _valid_calculate_args, _valid_submitted_claim


# ---------------------------------------------------------------------------
# value_is_citation_verified (eval_harness.py's numeric/comparison gate).
# Its _iter_citation_claims walk (window per marker, _NON_CLAIM_PATTERN
# stripping, caption units, tolerance) decides PASS/FAIL for every
# numeric eval question, so each property is pinned here.
# ---------------------------------------------------------------------------
def test_value_is_citation_verified_false_for_computed_ratio_in_neither_cited_source():
    # aapl-revenue-growth-q3fy2026: a self-computed percentage cited to the
    # two dollar-figure sources it was derived from, neither of which
    # states it.
    results = [
        _fake_result(text="revenue = 109417000000.0 USD"),
        _fake_result(text="revenue = 94036000000.0 USD"),
    ]
    answer = "The year-over-year revenue growth was approximately 16.27%. [1] [2]"
    assert value_is_citation_verified(16.27, "percent", answer, results) is False


def test_value_is_citation_verified_ignores_an_out_of_range_citation_index():
    assert value_is_citation_verified(20.0, "percent", "The rate was 20%. [5]", [_fake_result()]) is True


@pytest.mark.parametrize(
    "value, answer",
    [
        # Dates: "June 27, 2026" is a period label, not a claim.
        (27.0, "Revenue for the quarter ending June 27, 2026: $109,417,000,000 USD [1]"),
        (2026.0, "Revenue for the quarter ending June 27, 2026: $109,417,000,000 USD [1]"),
        # A bare 1900-2099 year next to a fiscal-period label.
        (2025.0, "Revenue in fiscal Q3 2025: $94,036,000,000 USD [1]"),
        # A form-type mention ("10-Q") with a space before it.
        (10.0, "Per the 10-Q filing [1], revenue was $109,417 million."),
    ],
)
def test_value_is_citation_verified_treats_non_claim_text_as_uncited(value, answer):
    # If _NON_CLAIM_PATTERN stopped stripping these, the number would be
    # attributed to [1], fail to match the source and grade as unverified.
    results = [_fake_result(text="revenue = 109417000000.0 USD")]
    assert value_is_citation_verified(value, "raw", answer, results) is True


def test_value_is_citation_verified_reads_a_bare_cell_under_a_caption_stated_unit():
    # crm-rpo-fy26: the source states "(in billions)" once in a caption and
    # leaves the cell bare ("$72.4").
    source_text = (
        "Remaining performance obligation consisted of the following (in billions):\n"
        "As of January 31, 2026 | $35.1 | $37.3 | $72.4"
    )
    answer = "The total remaining performance obligation was approximately $72.4 billion [1]."
    assert value_is_citation_verified(72.4, "billion", answer, [_fake_result(text=source_text)]) is True


def test_value_is_citation_verified_window_resets_at_each_citation_marker():
    # 50 is cited to [1], whose source says 100. [2]'s source does say 50,
    # but [2]'s window starts after [1], so it can't vouch for a number
    # cited earlier.
    results = [_fake_result(text="net income = 100"), _fake_result(text="revenue = 50")]
    answer = "Net income was $50 [1] and revenue was $100 [2]."
    assert value_is_citation_verified(50.0, "raw", answer, results) is False


def test_value_is_citation_verified_ignores_a_number_beyond_the_window_cap():
    # A number more than _CITATION_WINDOW_CHARS before the marker isn't
    # attributed to it, so it counts as uncited rather than unverified.
    results = [_fake_result(text="Unrelated text.")]
    answer = "Revenue was 777. " + "x" * (_CITATION_WINDOW_CHARS + 10) + " [1]"
    assert value_is_citation_verified(777.0, "raw", answer, results) is True


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
# _number_candidates(text, *, unit_source=None) -- also reads bare
# numbers in `text` under a unit word found in `unit_source` (a separate,
# usually longer text). unit_source defaults to `text` itself, which is
# the single-argument form the eval grader's walk (_iter_citation_claims)
# relies on.
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
# verify_claims (2026-09-10) -- verifies a submit_answer tool call's
# structured claims. Combines three checks (quote
# grounding via _quote_matches, value attribution via _number_candidates,
# and a coverage cross-check against answer_text) into the same
# CitationWarning vocabulary, with 5 new `check` values:
# citation_out_of_range, quote_too_short, quote_not_found,
# value_not_in_quote, uncovered_number. See
# docs/plans/2026-09-10-structured-claims-citation-verification.md.
# ---------------------------------------------------------------------------
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
    assert warnings[0].quote is None


_NVDA_XBRL_SOURCE_TEXT = "revenue = 81615000000 USD (structured XBRL data, not filing prose)"


def test_strip_citation_header_removes_an_exact_header_match():
    # The real repro shape: a model's quote sometimes includes the
    # numbered header _format_results_block() displays above each
    # result's text, even though that header is never part of the
    # underlying source text the quote gets grounded against.
    meta = {"ticker": "NVDA", "form": "10-Q", "reportDate": "2026-04-26"}
    quote = f"[1] NVDA 10-Q (reportDate=2026-04-26)\n{_NVDA_XBRL_SOURCE_TEXT}"
    assert _strip_citation_header(quote, 1, meta) == _NVDA_XBRL_SOURCE_TEXT


def test_strip_citation_header_leaves_a_quote_with_no_header_unchanged():
    meta = {"ticker": "NVDA", "form": "10-Q", "reportDate": "2026-04-26"}
    assert _strip_citation_header(_NVDA_XBRL_SOURCE_TEXT, 1, meta) == _NVDA_XBRL_SOURCE_TEXT


def test_strip_citation_header_does_not_strip_a_similar_but_wrong_prefix():
    # A different citation index's header, or a differently-shaped
    # bracketed prefix, must not be mistaken for THIS citation's own
    # header -- only an exact reconstruction is stripped.
    meta = {"ticker": "NVDA", "form": "10-Q", "reportDate": "2026-04-26"}
    quote = f"[2] NVDA 10-Q (reportDate=2026-04-26)\n{_NVDA_XBRL_SOURCE_TEXT}"
    assert _strip_citation_header(quote, 1, meta) == quote


@pytest.mark.parametrize("separator", ["\n", " "])
def test_strip_citation_header_removes_a_header_echoed_without_its_index_prefix(separator):
    # Models also echo the header with its "[n] " dropped; both
    # separators after it have been seen in live quotes.
    meta = {"ticker": "NVDA", "form": "10-K", "reportDate": "2026-01-25"}
    quote = f"NVDA 10-K (reportDate=2026-01-25){separator}{_NVDA_XBRL_SOURCE_TEXT}"
    assert _strip_citation_header(quote, 1, meta) == _NVDA_XBRL_SOURCE_TEXT


@pytest.mark.parametrize(
    "other", ["NVDA 10-Q (reportDate=2026-01-25)", "NVDA 10-K (reportDate=2025-01-26)"],
)
def test_strip_citation_header_does_not_strip_an_unprefixed_header_for_other_metadata(other):
    meta = {"ticker": "NVDA", "form": "10-K", "reportDate": "2026-01-25"}
    quote = f"{other}\n{_NVDA_XBRL_SOURCE_TEXT}"
    assert _strip_citation_header(quote, 1, meta) == quote


@pytest.mark.parametrize(
    ("value", "unit", "source_text"),
    [
        (215.938, "billion", "revenue = 215938000000 USD (structured XBRL data, not filing prose)"),
        (71.1, "percent", "gross_margin = 71.1 percent (structured XBRL data, not filing prose)"),
    ],
)
def test_verify_claims_grounds_a_quote_with_an_unprefixed_citation_header(value, unit, source_text):
    # Real submitted claim shapes: an unprefixed header plus a scaled or
    # percent unit must still ground.
    results = [_fake_result(ticker="NVDA", form="10-K", reportDate="2026-01-25", text=source_text)]
    claims = [_valid_submitted_claim(
        value=value, unit=unit, citation_index=1,
        quote=f"NVDA 10-K (reportDate=2026-01-25)\n{source_text}",
    )]
    assert verify_claims(claims, results, "q", f"The figure was {value} {unit} [1].") == []


def test_verify_claims_grounds_a_claim_whose_quote_includes_its_own_citation_header():
    # End-to-end reproduction of the real nvda-crm-revenue-comparison
    # baseline failure (eval/eval_results/20260919T003333Z.json): the
    # model's quote for a get_financial_fact result included the
    # numbered header shown above it, dragging quote-source coverage
    # below the required threshold and causing a hard refusal on an
    # otherwise fully-correct, fully-cited answer.
    results = [_fake_result(ticker="NVDA", form="10-Q", reportDate="2026-04-26", text=_NVDA_XBRL_SOURCE_TEXT)]
    claims = [_valid_submitted_claim(
        value=81615000000, unit="raw", citation_index=1,
        quote=f"[1] NVDA 10-Q (reportDate=2026-04-26)\n{_NVDA_XBRL_SOURCE_TEXT}",
    )]
    answer_text = "NVIDIA's revenue was $81,615,000,000 [1]."
    assert verify_claims(claims, results, "q", answer_text) == []


def test_verify_claims_records_the_raw_header_included_quote_when_grounding_still_fails():
    # Caught in code review: the header must be stripped for the
    # GROUNDING check, but a resulting CitationWarning must still show
    # the model's RAW quote (header included), not the cleaned-up
    # version -- otherwise a header-echo pattern becomes invisible in
    # the warning trail for any case where grounding fails for some
    # OTHER, unrelated reason, defeating the exact diagnostic purpose
    # the earlier session's quote-capture fix (Fix B) was built for.
    # Here the claimed value (999) genuinely isn't in the source at
    # all, header stripped or not -- a real, unrelated grounding
    # failure, not the header pattern itself.
    raw_quote = f"[1] NVDA 10-Q (reportDate=2026-04-26)\n{_NVDA_XBRL_SOURCE_TEXT}"
    results = [_fake_result(ticker="NVDA", form="10-Q", reportDate="2026-04-26", text=_NVDA_XBRL_SOURCE_TEXT)]
    claims = [_valid_submitted_claim(value=999.0, unit="raw", citation_index=1, quote=raw_quote)]
    warnings = verify_claims(claims, results, "q", "NVIDIA's revenue was $999 [1].")
    assert len(warnings) == 1
    assert warnings[0].quote == raw_quote


def test_verify_claims_quote_too_short():
    results = [_fake_result(text="the reported value for the period was exactly 100")]
    claims = [_valid_submitted_claim(quote="100")]
    warnings = verify_claims(claims, results, "q", "The value was 100 [1].")
    assert len(warnings) == 1
    assert warnings[0].check == "quote_too_short"
    assert warnings[0].quote == "100"


def test_verify_claims_quote_not_found():
    results = [_fake_result(text="Research and development expenses increased due to higher headcount.")]
    claims = [_valid_submitted_claim(quote="the reported value for the period was exactly 100")]
    warnings = verify_claims(claims, results, "q", "The value was 100 [1].")
    assert len(warnings) == 1
    assert warnings[0].check == "quote_not_found"
    assert warnings[0].quote == "the reported value for the period was exactly 100"


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
    assert warnings[0].quote == "Revenue was $100 million in Q1"


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
    assert warnings[0].quote == "the reported value for the period was exactly 100"


def test_verify_claims_qualitative_claim_quote_too_short():
    results = [_fake_result(text="the reported value for the period was exactly 100")]
    claims = [_qualitative_claim(quote="100")]
    warnings = verify_claims(claims, results, "q", "Something [1].")
    assert len(warnings) == 1
    assert warnings[0].check == "quote_too_short"
    assert "None" not in warnings[0].message
    assert warnings[0].quote == "100"


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
    from sec_agent.agent.citations import _verify_one_claim

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
    assert warnings[0].quote is None


def test_verify_claims_multi_index_citation_bracket_digits_not_treated_as_uncovered_numbers():
    # Real false positive found live 2026-09-11 (41-question baseline
    # re-run after the structured-claims redesign): _CITATION_MARKER
    # (r"\[(\d+)\]") only strips a SINGLE-index bracket like "[1]" before
    # the coverage check runs extract_numbers() on answer_text -- a
    # multi-source bracket like "[1, 3, 5]" (crm-revenue-q1fy27's real
    # answer) or "[1, 17]" (msft-net-income-fy2025-indirect's) survives
    # untouched, so the bare digits 1/3/5 (or 1/17) inside it get
    # extracted as their own spurious uncovered-number claims and refuse
    # an otherwise fully-grounded answer. (_CITATION_MARKER, used by the
    # eval grader's walk, doesn't recognize "[1, 5]" as a marker at all.)
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


def test_verify_claims_calculate_operand_exempts_a_number_from_coverage():
    # Rule 9 tells the model to show a calculate-derived value's
    # computation inline for readability (e.g. "computed as $35,695
    # million ... divided by $109,417 million ... = 32.6%"), but the
    # operands restated that way have no claims entry of their own.
    # They shouldn't need one: _ground_operand already verified both
    # against a real cited source at calculate-call time, and that
    # calculation's own all_results entry (chunk_index="calculated")
    # already records both operands in directly-extractable text -- see
    # _calculation_as_result. The final derived value (32.6%) is
    # covered normally via its own claim citing that same entry.
    calculated_entry = _fake_result(
        text=(
            "35695 million as a percentage of 109417 million = 32.6 percent "
            "(computed value, not directly stated in any filing; operands from results [1] and [2])"
        ),
        chunk_index="calculated",
    )
    results = [_fake_result(text="operating income"), _fake_result(text="total net sales"), calculated_entry]
    claims = [
        {
            "value": 32.6,
            "unit": "percent",
            "citation_index": 3,
            "quote": "35695 million as a percentage of 109417 million = 32.6 percent",
        }
    ]
    answer_text = (
        "Apple's operating margin was computed as $35,695 million in operating income divided by "
        "$109,417 million in total net sales, resulting in an operating margin of 32.6% [3]."
    )
    assert verify_claims(claims, results, "q", answer_text) == []


def test_verify_claims_calculate_entry_citation_brackets_not_treated_as_operand_values():
    # _calculation_as_result's text always ends with "...operands from
    # results [N] and [M])" -- those bracketed indices must NOT be
    # extracted as operand values themselves (and, since a unit word
    # like "million" also appears in the same text, must not get
    # scaled up into bogus million-scale candidates either). A citation
    # index deliberately chosen to also be a plausible raw claim value.
    calculated_entry = _fake_result(
        text=(
            "35695 million as a percentage of 109417 million = 32.6 percent "
            "(computed value, not directly stated in any filing; operands from results [3] and [5])"
        ),
        chunk_index="calculated",
    )
    results = [_fake_result(text="a"), _fake_result(text="b"), calculated_entry]
    claims = []
    # Genuinely uncovered claims matching the citation-index digits,
    # bare and scaled -- must still be flagged, not swallowed by the
    # calculated-entry exemption pool.
    answer_text = "The filing separately mentions 3 and 5 million unrelated units."
    warnings = verify_claims(claims, results, "q", answer_text)
    flagged = {(w.value, w.unit) for w in warnings if w.check == "uncovered_number"}
    assert (3.0, "raw") in flagged
    assert (5.0, "million") in flagged


def test_verify_claims_calculate_entry_exemption_does_not_cover_the_result_itself():
    # Caught live in code review: an earlier version of this exemption
    # extracted every number from the calculated entry's FULL text,
    # which included the derived RESULT (32.6 percent), not just its
    # two operands -- silently letting the model state the final value
    # with no claims entry of its own at all. Only the operands (before
    # the entry's own "=") are exempt; the result must still earn
    # coverage through a real claims entry, same as any other value.
    calculated_entry = _fake_result(
        text=(
            "35695 million as a percentage of 109417 million = 32.6 percent "
            "(computed value, not directly stated in any filing; operands from results [1] and [2])"
        ),
        chunk_index="calculated",
    )
    results = [_fake_result(text="a"), _fake_result(text="b"), calculated_entry]
    claims = []  # no claims entry for 32.6% at all
    answer_text = "The operating margin was 32.6%."
    warnings = verify_claims(claims, results, "q", answer_text)
    assert any(w.check == "uncovered_number" and w.value == 32.6 for w in warnings)


def _nvda_two_quarter_revenue_scenario(operation="percent_change"):
    """Sources, a real calculate entry for `operation` (None for none),
    and claims shaped like nvda-revenue-two-quarter-comparison's real
    withheld answer."""
    results = [
        _fake_result(text="Total revenue for the quarter was $81,615 million."),
        _fake_result(text="Total revenue for the quarter was $44,062 million."),
    ]
    claims = [
        {"value": 81615.0, "unit": "million", "citation_index": 1,
         "quote": "Total revenue for the quarter was $81,615 million."},
        {"value": 44062.0, "unit": "million", "citation_index": 2,
         "quote": "Total revenue for the quarter was $44,062 million."},
    ]
    if operation is not None:
        args = _valid_calculate_args(
            operation=operation, operand_a=81615.0, operand_b=44062.0, unit_a="million", unit_b="million"
        )
        calc_result, error = call_calculate(args, results)
        assert error is None and calc_result is not None
        entry = _calculation_as_result(calc_result, args)
        results.append(entry)
        claims.append({"value": calc_result["value"], "unit": calc_result["unit"], "citation_index": 3,
                       "quote": entry["text"].split(" (computed", 1)[0]})
    return results, claims


_NVDA_REVENUE_LEAD = (
    "For the quarter ended April 26, 2026, NVIDIA reported total revenue of $81.615 billion [1]. "
    "For the prior-year quarter ended April 27, 2025, NVIDIA reported total revenue of "
    "$44.062 billion [2]. This represents an increase of 85.2% "
)


def _uncovered(warnings):
    return {(w.value, w.unit) for w in warnings if w.check == "uncovered_number"}


@pytest.mark.parametrize(
    "derivation",
    [
        # The live shape, then other ways to write the same formula: the
        # exemption must not depend on how the model phrases it.
        "(computed as $81,615,000,000 ÷ $44,062,000,000 - 1 = 85.2%) [3].",
        "(computed as $81,615,000,000 ÷ $44,062,000,000 − 1 = 85.2%) [3].",
        "(computed as $81,615,000,000 ÷ $44,062,000,000 – 1 = 85.2%) [3].",
        "(computed as ($81,615,000,000 / $44,062,000,000 − 1) × 100 = 85.2%) [3].",
        "(computed as ($81,615,000,000 ÷ $44,062,000,000) − 1 = 85.2%) [3].",
        "(computed as $81,615,000,000 ÷ $44,062,000,000 × 100 − 100 = 85.2%) [3].",
        "(computed as ($81,615,000,000 ÷ $44,062,000,000 × 100) − 100 = 85.2%) [3].",
        "(computed as 100 × ($81,615,000,000 − $44,062,000,000) / $44,062,000,000 = 85.2%) [3].",
        "(computed as ($81,615,000,000 − $44,062,000,000) × 100 / $44,062,000,000 = 85.2%) [3].",
        "(computed as $81,615,000,000 ÷ $44,062,000,000−1 = 85.2%) [3].",
        "computed as $81,615,000,000 ÷ $44,062,000,000 − 1 [3].",
        "(computed as $81,615,000,000 ÷ $44,062,000,000 − 1.) [3]",
    ],
)
def test_verify_claims_percent_change_identities_are_covered_by_the_calculation(derivation):
    # The formula's identities aren't figures any filing states; the
    # percent_change calculate call that ran is what covers them.
    results, claims = _nvda_two_quarter_revenue_scenario()
    warnings = verify_claims(claims, results, "q", _NVDA_REVENUE_LEAD + derivation)
    assert _uncovered(warnings) == set()


_NVDA_PERCENT_OF_LEAD = "NVIDIA revenue was $81,615,000,000 [1] versus $44,062,000,000 [2], or 185.2% "


def test_verify_claims_percent_of_covers_100():
    results, claims = _nvda_two_quarter_revenue_scenario("percent_of")
    answer_text = _NVDA_PERCENT_OF_LEAD + "(computed as $81,615,000,000 ÷ $44,062,000,000 × 100 = 185.2%) [3]."
    assert _uncovered(verify_claims(claims, results, "q", answer_text)) == set()


@pytest.mark.parametrize(
    "derivation, identity",
    [
        ("$81,615,000,000 ÷ $44,062,000,000 − 1 + 1", (1.0, "raw")),
        ("($81,615,000,000 ÷ $44,062,000,000) − 1 + 1", (-1.0, "raw")),
        ("($81,615,000,000 ÷ $44,062,000,000 × 100) − 100 + 100", (-100.0, "raw")),
    ],
)
def test_verify_claims_percent_of_grants_only_100(derivation, identity):
    results, claims = _nvda_two_quarter_revenue_scenario("percent_of")
    answer_text = _NVDA_PERCENT_OF_LEAD + f"(computed as {derivation} = 185.2%) [3]."
    assert identity in _uncovered(verify_claims(claims, results, "q", answer_text))


@pytest.mark.parametrize("operation", [None, "add", "subtract", "multiply", "divide"])
@pytest.mark.parametrize(
    "derivation, identity",
    [
        ("$81,615,000,000 ÷ $44,062,000,000 − 1", (1.0, "raw")),
        ("($81,615,000,000 ÷ $44,062,000,000) − 1", (-1.0, "raw")),
        ("$81,615,000,000 ÷ $44,062,000,000 × 100", (100.0, "raw")),
        ("($81,615,000,000 ÷ $44,062,000,000 × 100) − 100", (-100.0, "raw")),
    ],
)
def test_verify_claims_identities_need_a_percent_calculation(operation, derivation, identity):
    # Without a percent calculation in the results, each identity is an
    # ordinary uncited number; a binary calculation doesn't count.
    results, claims = _nvda_two_quarter_revenue_scenario(operation)
    answer_text = _NVDA_REVENUE_LEAD + f"(computed as {derivation} = 85.2%)."
    assert identity in _uncovered(verify_claims(claims, results, "q", answer_text))


@pytest.mark.parametrize(
    "answer_text, uncovered",
    [
        # Only the exact unitless identities are covered, not a figure
        # with a unit and not a nearby value.
        ("Revenue fell $44,062,000,000 − $1 million [2].", (1.0, "million")),
        ("Margin rose 1% [2].", (1.0, "percent")),
        ("NVIDIA opened 99 stores [2].", (99.0, "raw")),
        ("NVIDIA opened 101 stores [2].", (101.0, "raw")),
        ("Net change was ($101) [2].", (-101.0, "raw")),
        ("Net change was −$100 million [2].", (-100.0, "million")),
        ("Headcount rose by 0.1 thousand [2].", (0.1, "thousand")),
        # Operands and results inside a derivation still need coverage.
        ("Turnover was computed as 62,408 ÷ 44,062,000,000 − 1 [2].", (62408.0, "raw")),
        ("Computed as $81,615,000,000 ÷ $44,062,000,000 − 1 = 91.3% [3].", (91.3, "percent")),
    ],
)
def test_verify_claims_percent_identities_do_not_hide_real_numbers(answer_text, uncovered):
    results, claims = _nvda_two_quarter_revenue_scenario()
    assert uncovered in _uncovered(verify_claims(claims, results, "q", answer_text))


def test_verify_claims_subtraction_after_calculate_raw_unit_is_not_a_negative_claim():
    # Models copy calculate's "raw" unit word into the answer; the operand
    # after "raw −" is a subtrahend, not a -359,241,000,000 claim.
    results = [
        _fake_result(text="Total assets were $619,003,000,000 at June 30, 2025."),
        _fake_result(text="Total assets were $359,241,000,000 at September 27, 2025."),
    ]
    args = _valid_calculate_args(
        operation="subtract", operand_a=619003000000.0, operand_b=359241000000.0, unit_a="raw", unit_b="raw"
    )
    calc_result, error = call_calculate(args, results)
    assert error is None and calc_result is not None
    entry = _calculation_as_result(calc_result, args)
    results.append(entry)
    claims = [
        {"value": 619003000000.0, "unit": "raw", "citation_index": 1,
         "quote": "Total assets were $619,003,000,000"},
        {"value": 359241000000.0, "unit": "raw", "citation_index": 2,
         "quote": "Total assets were $359,241,000,000"},
        {"value": calc_result["value"], "unit": calc_result["unit"], "citation_index": 3,
         "quote": entry["text"].split(" (computed", 1)[0]},
    ]
    answer_text = (
        "Microsoft: $619,003,000,000 [1]. Apple: $359,241,000,000 [2]. The difference is "
        "$259,762,000,000, computed as 619,003,000,000 raw − 359,241,000,000 raw = 259,762,000,000 [3]."
    )
    assert verify_claims(claims, results, "q", answer_text) == []


def test_verify_claims_non_claim_noise_in_answer_text_is_not_flagged():
    results = [_fake_result(text="Apple filed its 10-K covering the period.")]
    claims = []
    answer_text = "Apple filed its 10-K on June 27, 2026, covering fiscal year 2026, as discussed in Note 1."
    assert verify_claims(claims, results, "q", answer_text) == []


def test_verify_claims_hyphenated_year_and_day_durations_exempted_from_coverage():
    # Direct regression anchor for _NON_CLAIM_PATTERN's N-year/N-day
    # exemption, exercised through the coverage scan itself -- unlike
    # test_verify_claims_question_echo_exempts_a_number_from_coverage
    # above (which passes via the question-echo path and would pass
    # even if this exemption didn't exist), this has no question-echo
    # to fall back on.
    results = [_fake_result(text="lease terms")]
    claims = []
    answer_text = "The lease has a 3-year initial term with a 30-day renewal notice period."
    assert verify_claims(claims, results, "q", answer_text) == []


def test_verify_claims_duration_in_months_not_flagged_as_uncovered_number():
    # Real incident (BACKLOG.md, nvda-supply-chain-risk): a genuinely
    # qualitative claim (no value/unit, correctly per the 2026-09-15
    # schema) whose own quote incidentally contains a duration -- the
    # coverage scan has no claim to match "12" against, since a
    # qualitative claim contributes nothing to claimed_normalized.
    results = [_fake_result(text="lead times can extend beyond 12 months due to supply constraints")]
    claims = [_qualitative_claim(quote="lead times can extend beyond 12 months")]
    answer_text = "NVIDIA has experienced extended lead times of more than 12 months [1]."
    assert verify_claims(claims, results, "q", answer_text) == []


def test_verify_claims_space_separated_and_hyphenated_month_durations_exempted():
    # Confirms the widened _NON_CLAIM_PATTERN separator (hyphen OR
    # whitespace) works both directions for all three nouns, not just
    # the one evidenced "N months" shape.
    results = [_fake_result(text="reporting periods")]
    claims = []
    answer_text = "Reported over a 12 month period, compared to a 6-month prior period."
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
# tests/verification/test_table_grounding.py.
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
