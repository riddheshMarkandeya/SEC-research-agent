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
