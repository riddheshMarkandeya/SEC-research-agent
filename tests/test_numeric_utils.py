"""
Unit tests for numeric_utils.py's extract_numbers/normalize -- split out
from test_eval_harness.py when these moved into their own module so
agent.py's verify_citations() could share them without a circular
import (agent.py <- eval_harness.py already; eval_harness.py <- agent.py
would be circular the other way).
"""

import pytest

from numeric_utils import extract_numbers, extract_numbers_with_spans, normalize


# ---------------------------------------------------------------------------
# extract_numbers
# ---------------------------------------------------------------------------
def test_extract_numbers_dollar_billion():
    assert (72.4, "billion") in extract_numbers("The total was approximately $72.4 billion.")


def test_extract_numbers_dollar_million_spelled_out():
    # Documents the now-relied-upon correct behavior behind the
    # agent.py system-prompt fix (BACKLOG.md, aapl-rd-pct-gross-profit-fy2025):
    # "million" spelled out parses correctly and normalize-matches a raw
    # claim, unlike the ambiguous "$34,550M" abbreviation the prompt used
    # to demonstrate (extract_numbers has no "M"/"B"/"K" recognition at
    # all -- a bare "M" parses as unit="raw", off by 1000x from the
    # intended value).
    assert (34550.0, "million") in extract_numbers("computed as $34,550 million / $195,201 million = 17.7%")


def test_extract_numbers_comma_grouped_raw_count():
    assert (166000.0, "raw") in extract_numbers("Apple had 166,000 full-time equivalent employees.")


def test_extract_numbers_percent_sign():
    assert (20.0, "percent") in extract_numbers("the effective tax rate was 20%")


def test_extract_numbers_percent_word():
    assert (20.0, "percent") in extract_numbers("a statutory rate of 20 percent")


def test_extract_numbers_no_digits_returns_empty_list():
    assert extract_numbers("no numbers in this sentence at all") == []


def test_extract_numbers_bare_large_decimal_not_fragmented():
    # Regression test: NUMBER_PATTERN used to cap the leading digit
    # group at 3 digits, which fragmented a comma-less run like
    # xbrl_facts.py's raw float formatting ("109417000000.0") into
    # separate wrong candidates (109, 417, 000, 000.0) instead of one
    # correct number.
    assert extract_numbers("revenue = 109417000000.0 USD") == [(109417000000.0, "raw")]


def test_extract_numbers_ignores_digit_glued_to_letter():
    # "Q3" and "FY2026" shouldn't be read as the numbers 3 / 026.
    assert extract_numbers("Revenue in fiscal Q3 2025") == [(2025.0, "raw")]
    assert extract_numbers("FY2026 results") == []


# ---------------------------------------------------------------------------
# Negative numbers -- found missing entirely during a hand-rolled-
# complexity review (2026-09-11): NUMBER_PATTERN silently dropped sign on
# every negative value, real and already-reachable through this
# codebase's OWN generated citation text (a negative XBRL fact --net
# loss, negative YoY growth-- rendered via agent.py's _format_fact_value
# uses plain str(), producing "-1234000000.0 million", which used to
# round-trip back to a POSITIVE 1234000000.0). Design grounded in the
# real ./chunks/*/*.jsonl corpus, not guessed: the accounting-parens
# convention ("(433)", "$(1,122)", "(2.5)%", "(237)%") is the format SEC
# filings actually use, confirmed live by grep before writing this fix.
# ---------------------------------------------------------------------------
def test_extract_numbers_plain_parenthesized_negative():
    assert extract_numbers("Provision for income taxes | (433) |") == [(-433.0, "raw")]


def test_extract_numbers_dollar_sign_outside_parens():
    # Real corpus format: "$(1,122)" -- the "$" sits OUTSIDE the
    # parenthesized negative, not inside it.
    assert extract_numbers("compensation expense | $(1,122) |") == [(-1122.0, "raw")]


def test_extract_numbers_negative_percent_with_decimal():
    assert extract_numbers("segment margin was (2.5)%") == [(-2.5, "percent")]


def test_extract_numbers_negative_percent_integer():
    assert extract_numbers("revenue growth of (237)%") == [(-237.0, "percent")]


def test_extract_numbers_plain_leading_minus_sign():
    # Covers the tool's own generated negative-computation text (e.g.
    # _format_computed_number's output for a negative percent_change),
    # not just filing-prose accounting parens.
    assert extract_numbers("declined by -5.2 percent") == [(-5.2, "percent")]


def test_extract_numbers_unicode_minus_sign_recognized():
    # Found live (2026-09-12, the fixed run's own eval baseline): Gemini's
    # own rule-9 disclosure prose used the proper Unicode MINUS SIGN
    # (U+2212, "−"), not the ASCII hyphen-minus this project's regex
    # otherwise handles -- confirmed unicodedata.normalize("NFKC", ...)
    # does NOT fold U+2212 to ASCII "-" (they aren't compatibility
    # equivalents), so the existing NFKC-based quote normalization
    # elsewhere in this codebase (agent._normalize_for_match) could never
    # have caught this either. Without this, "17.9% − 20% = −2.1%"
    # extracted the final value as positive 2.1, not -2.1, which caused a
    # real "uncovered_number" false-positive gate refusal on
    # aapl-msft-tax-rate-comparison.
    assert extract_numbers("computed as 17.9% − 20% = −2.1%") == [
        (17.9, "percent"),
        (20.0, "percent"),
        (-2.1, "percent"),
    ]


def test_extract_numbers_spaced_subtraction_expression_stays_positive():
    # Found live (2026-09-12, first full eval run after shipping negative-
    # number support): a model's own disclosure prose for a computed
    # value, e.g. "(computed as 223,000 - 166,000 = 57,000)", uses a
    # SPACED hyphen as a subtraction operator, not a sign -- the earlier
    # `(?<!\d)` guard only blocked a hyphen glued directly to a preceding
    # digit (no space), so this slipped through and misread 166,000 as
    # -166000.0, which then made an otherwise-correct, fully-cited answer
    # ("aapl-msft-employee-comparison") fail citation verification
    # (spurious "-166000.0" claim not covered by any real claim).
    assert extract_numbers("computed as 223,000 - 166,000 = 57,000") == [
        (223000.0, "raw"),
        (166000.0, "raw"),
        (57000.0, "raw"),
    ]


def test_extract_numbers_iso_date_stays_positive_not_misread_as_negative():
    # Regression guard: a bare "-" gated wrong could misread the second
    # half of a hyphen-joined ISO date as a negative number sitting right
    # after the first. Every part must stay positive, unchanged from
    # today's (already-passing) behavior.
    assert extract_numbers("reported on 2024-01-25") == [(2024.0, "raw"), (1.0, "raw"), (25.0, "raw")]


def test_extract_numbers_hyphenated_range_stays_positive():
    # Regression guard: a "10-15" range must not have its second number
    # misread as negative just because a bare hyphen separates the two.
    assert extract_numbers("operating margin grew 10-15 percent") == [(10.0, "raw"), (15.0, "percent")]


def test_extract_numbers_short_negative_table_cell_still_flips_sign():
    # Found in architecture review (2026-09-11), confirmed live against
    # the real corpus at scale (554 occurrences across all 5 companies'
    # chunks): a short (1-2 digit), comma-less negative value is the
    # NORMAL shape for a table cell whose unit is stated once in the
    # table's caption, not per-cell -- e.g. a comprehensive-income
    # statement's small translation-adjustment line items. An earlier
    # version of the footnote-marker guard below (gated on digit count
    # alone, with no positional signal) wrongly swallowed ALL of these,
    # a regression worse than the false positive it was fixing.
    assert extract_numbers("Cumulative translation, net of tax | 449 | (73) | (86) | (87) |") == [
        (449.0, "raw"),
        (-73.0, "raw"),
        (-86.0, "raw"),
        (-87.0, "raw"),
    ]


def test_extract_numbers_short_negative_glued_to_line_item_label_still_flips_sign():
    # Same real shape, one more corpus example: a P&L line item ending in
    # a bare "(1)" that IS a real negative one-unit value, not a
    # footnote-reference digit -- distinguished from the footnote-marker
    # case (below) by NOT being glued to a preceding word: it starts its
    # own table cell right after a "|" delimiter.
    assert extract_numbers("amounts included in net income | (1) | 30 | 404") == [
        (-1.0, "raw"),
        (30.0, "raw"),
        (404.0, "raw"),
    ]


def test_extract_numbers_footnote_marker_in_parens_stays_positive():
    # Found in code review (2026-09-11), confirmed live against real
    # corpus text: a bare 1-2 digit parenthesized reference marker is
    # extremely common filing boilerplate ("Mark whether the Registrant
    # (1) has filed... and (2) has been..." appears on literally every
    # 10-K's cover page in this project's own corpus) -- a naive
    # "any (NUM) is negative" rule would misread these as -1/-2, which
    # could then falsely "verify" an unrelated small-negative-value claim
    # against a source that never actually stated one.
    assert extract_numbers("Mark whether the Registrant (1) has filed") == [(1.0, "raw")]


def test_extract_numbers_footnote_marker_glued_to_table_label_stays_positive():
    # Real corpus shape: a footnote marker attached to a row LABEL, with
    # the actual value in a separate cell -- the marker itself must not
    # be misread as a negative value sitting right next to the real one.
    assert extract_numbers("Total debt securities (1) $ 433") == [(1.0, "raw"), (433.0, "raw")]


def test_extract_numbers_single_digit_negative_percent_still_flips_sign():
    # The footnote-marker guard above must NOT swallow a genuine
    # single-digit negative percentage -- real corpus shape ("(4)%",
    # confirmed live in AAPL chunk data). A footnote marker is never
    # immediately followed by "%", so this is a safe, evidence-based way
    # to tell the two apart.
    assert extract_numbers("accessories declined (4)%") == [(-4.0, "percent")]


def test_extract_numbers_bare_year_in_parens_stays_positive():
    # Regression guard found live in the real corpus: "(2013)" is common
    # boilerplate (COSO framework citations in every 10-K's internal-
    # controls section; exhibit-index references), not an accounting
    # negative -- confirmed via grep against ./chunks/*/*.jsonl before
    # writing this guard, not assumed. A naive "any (NUM) is negative"
    # rule would have turned these into spurious -2013 candidates.
    assert extract_numbers("Internal Control - Integrated Framework (2013) issued by") == [(2013.0, "raw")]


def test_extract_numbers_with_spans_paren_negative_span_is_digits_only():
    # Span precedent (matches the existing "$" exclusion): the reported
    # span covers just the digit substring, not the wrapping parens.
    text = "loss of (433) thousand"
    [(value, unit, start, end)] = extract_numbers_with_spans(text)
    assert (value, unit) == (-433.0, "thousand")
    assert text[start:end] == "433"


# ---------------------------------------------------------------------------
# extract_numbers_with_spans -- position-aware sibling of extract_numbers,
# added for agent.py's uncited-numeric-claim detection (verify_citations()),
# which needs to measure a claim's distance from the nearest [n] citation
# marker in the ORIGINAL answer text, not just its (value, unit).
# ---------------------------------------------------------------------------
def test_extract_numbers_with_spans_returns_correct_offsets():
    text = "revenue was $72.4 billion last quarter"
    [(value, unit, start, end)] = extract_numbers_with_spans(text)
    assert (value, unit) == (72.4, "billion")
    assert text[start:end] == "72.4"


def test_extract_numbers_with_spans_matches_extract_numbers_values():
    # Same (value, unit) pairs as the position-less version, just with
    # spans attached -- extract_numbers() itself becomes a thin wrapper
    # around this, so the two must never drift apart.
    text = "Apple had 166,000 full-time equivalent employees, a 20% increase."
    with_spans = [(v, u) for v, u, _, _ in extract_numbers_with_spans(text)]
    assert with_spans == extract_numbers(text)


def test_extract_numbers_with_spans_empty_for_no_digits():
    assert extract_numbers_with_spans("no numbers in this sentence at all") == []


# ---------------------------------------------------------------------------
# normalize — the percent/scale category-safety guarantee
# ---------------------------------------------------------------------------
def test_normalize_percent_stays_raw_value():
    assert normalize(20, "percent") == ("percent", 20)


def test_normalize_billion_applies_multiplier():
    category, value = normalize(72.4, "billion")
    assert category == "scale"
    assert value == pytest.approx(72_400_000_000)


def test_normalize_raw_is_unchanged_scale_value():
    assert normalize(166000, "raw") == ("scale", 166000)


def test_normalize_percent_and_raw_are_different_categories():
    # This is the exact guarantee grade_numeric() (and verify_citations())
    # depend on: a literal "20" must never be treated as satisfying an
    # expected "20 percent".
    percent_category, _ = normalize(20, "percent")
    scale_category, _ = normalize(20, "raw")
    assert percent_category != scale_category
