"""
Unit tests for period_labels.py. Covers all four pure/near-pure
functions — fiscal_year_label, fiscal_quarter, period_label, and
chunk_period_label (which only does static-file lookup via
companies.json, no network/model calls, so it's fine to test directly).

Every case here mirrors a fact independently confirmed from the actual
filing text during diagnosis, not invented expectations. See
docs/decisions/2026-08-16-fiscal-period-labels-tried-and-reverted.md.
"""

from datetime import date

from period_labels import chunk_period_label, fiscal_quarter, fiscal_year_label, period_label


# ---------------------------------------------------------------------------
# fiscal_year_label
# ---------------------------------------------------------------------------
def test_fiscal_year_label_within_fiscal_year_end_month_uses_same_calendar_year():
    # MSFT's fiscal year ends in June; a quarter ending in March falls
    # within the calendar year matching its own fiscal year number.
    assert fiscal_year_label(6, date(2026, 3, 31)) == 2026


def test_fiscal_year_label_after_fiscal_year_end_month_rolls_to_next_calendar_year():
    # MSFT's fiscal Q1 (Jul-Sep) reports a September reportDate but
    # belongs to the fiscal year that ENDS the following June -- NVIDIA's
    # own 10-Q text confirms this pattern explicitly ("the first quarter
    # of fiscal year 2027" for a quarter ending in April, one month after
    # NVIDIA's January fiscal year end).
    assert fiscal_year_label(6, date(2025, 9, 30)) == 2026


def test_fiscal_year_label_nvda_annual_matches_its_own_self_description():
    # NVIDIA's 10-K covering the year ended Jan 25, 2026 calls itself
    # "fiscal year 2026" in its own text.
    assert fiscal_year_label(1, date(2026, 1, 25)) == 2026


def test_fiscal_year_label_nvda_next_quarter_rolls_forward():
    assert fiscal_year_label(1, date(2026, 4, 26)) == 2027


# ---------------------------------------------------------------------------
# fiscal_quarter
# ---------------------------------------------------------------------------
def test_fiscal_quarter_msft_q3():
    # Verified against MSFT's own 10-Q text: "Highlights from the third
    # quarter of fiscal year 2026" for the quarter ended March 31, 2026.
    assert fiscal_quarter(6, date(2026, 3, 31)) == 3


def test_fiscal_quarter_msft_q1():
    assert fiscal_quarter(6, date(2025, 9, 30)) == 1


def test_fiscal_quarter_msft_q2():
    # Matches this project's own msft-tax-rate-q2fy26 eval question.
    assert fiscal_quarter(6, date(2025, 12, 31)) == 2


def test_fiscal_quarter_msft_q4_is_the_fiscal_year_end():
    assert fiscal_quarter(6, date(2026, 6, 30)) == 4


# ---------------------------------------------------------------------------
# period_label
# ---------------------------------------------------------------------------
def test_period_label_10k_says_annual_report():
    label = period_label("NVDA", "10-K", "2026-01-25", fiscal_year_end_month=1)
    assert "annual report" in label
    assert "fiscal year 2026" in label
    assert "January 25, 2026" in label


def test_period_label_10q_says_quarterly_report_with_quarter_number():
    label = period_label("MSFT", "10-Q", "2026-03-31", fiscal_year_end_month=6)
    assert "quarterly report" in label
    assert "fiscal year 2026 quarter 3" in label
    assert "March 31, 2026" in label


# ---------------------------------------------------------------------------
# chunk_period_label
# ---------------------------------------------------------------------------
def test_chunk_period_label_looks_up_fiscal_year_end_month_from_companies_json():
    label = chunk_period_label("PLTR", "10-K", "2025-12-31")
    assert "annual report" in label
    assert "fiscal year 2025" in label
