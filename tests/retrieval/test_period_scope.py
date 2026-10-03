"""Unit tests for period_scope: which filings' report dates a search query
names. Expected dates come from each company's fiscal calendar (NVIDIA's
fiscal year ends in January, Microsoft's in June), not from the code."""

from sec_agent.retrieval.period_scope import Scope, filing_list, query_report_dates

NVDA = [
    ("NVDA", "10-K", "2025-01-26"),  # fiscal 2025
    ("NVDA", "10-Q", "2025-04-27"),  # Q1 fiscal 2026
    ("NVDA", "10-Q", "2025-07-27"),  # Q2 fiscal 2026
    ("NVDA", "10-K", "2026-01-25"),  # fiscal 2026
]
MSFT = [
    ("MSFT", "10-K", "2025-06-30"),  # fiscal 2025
    ("MSFT", "10-Q", "2026-03-31"),  # Q3 fiscal 2026
]
FY_END = {"NVDA": 1, "MSFT": 6}


def scope(query: str, filings=None) -> Scope:
    return query_report_dates(query, NVDA if filings is None else filings, FY_END)


# ---------------------------------------------------------------------------
# Explicit dates
# ---------------------------------------------------------------------------
def test_explicit_date_matches_its_report_date():
    assert scope("revenue for the quarter ended April 27, 2025") == Scope(("2025-04-27",), "dates", ())


def test_explicit_date_matches_a_report_date_within_seven_days():
    assert scope("three months ended April 30, 2025").report_dates == ("2025-04-27",)


def test_explicit_date_more_than_seven_days_away_matches_nothing():
    assert scope("as of May 10, 2025") == Scope((), "no_match", ())


def test_every_explicit_date_counts():
    assert scope("April 27, 2025 versus July 27, 2025").report_dates == ("2025-04-27", "2025-07-27")


def test_unmatched_explicit_date_falls_through_to_the_fiscal_year():
    assert scope("as of May 20, 2025, first quarter of fiscal 2026").report_dates == ("2025-04-27",)


def test_impossible_explicit_dates_are_skipped_not_raised():
    result = scope("September 31, 2025 and February 29, 2025 and January 0, 2025")
    assert result == Scope((), "no_date", ("September 31, 2025", "February 29, 2025", "January 0, 2025"))


def test_impossible_date_beside_a_fiscal_year_still_scopes_by_the_year():
    result = scope("fiscal 2026 as of September 31, 2025")
    assert result == Scope(("2026-01-25",), "dates", ("September 31, 2025",))


# ---------------------------------------------------------------------------
# Fiscal years and quarters
# ---------------------------------------------------------------------------
def test_fiscal_year_without_a_quarter_matches_the_annual_report_only():
    assert scope("NVIDIA total revenue in fiscal 2026").report_dates == ("2026-01-25",)


def test_fiscal_year_and_quarter_match_that_quarterly_report():
    assert scope("Q2 fiscal 2026 data center revenue").report_dates == ("2025-07-27",)


def test_quarter_in_words():
    assert scope("second quarter of fiscal year 2026").report_dates == ("2025-07-27",)


def test_two_digit_fiscal_year():
    assert scope("FY26 annual revenue").report_dates == ("2026-01-25",)


def test_only_the_first_fiscal_year_counts():
    assert scope("fiscal 2025 compared with fiscal 2026").report_dates == ("2025-01-26",)


def test_fiscal_year_with_no_filing_is_no_match():
    assert scope("fiscal 2019 revenue") == Scope((), "no_match", ())


def test_no_period_in_the_query():
    assert scope("data center revenue growth drivers") == Scope((), "no_date", ())


def test_without_a_ticker_every_company_is_matched_on_its_own_calendar():
    assert scope("fiscal 2025 revenue", NVDA + MSFT).report_dates == ("2025-01-26", "2025-06-30")


# ---------------------------------------------------------------------------
# filing_list
# ---------------------------------------------------------------------------
METADATAS = [
    {"ticker": "NVDA", "form": "10-Q", "reportDate": "2025-04-27"},
    {"ticker": "NVDA", "form": "10-Q", "reportDate": "2025-04-27"},
    {"ticker": "MSFT", "form": "10-Q", "reportDate": "2025-04-30"},
]


def test_filing_list_is_one_entry_per_filing():
    assert filing_list(METADATAS, None) == [("NVDA", "10-Q", "2025-04-27"), ("MSFT", "10-Q", "2025-04-30")]


def test_a_ticker_scoped_list_keeps_other_companies_dates_from_scoping_the_query():
    # MSFT's 2025-04-30 is within 7 days of the named date; an NVDA search
    # must still scope to NVDA's own filing only.
    filings = filing_list(METADATAS, "NVDA")
    assert filings == [("NVDA", "10-Q", "2025-04-27")]
    assert query_report_dates("April 30, 2025", filings, FY_END).report_dates == ("2025-04-27",)


def test_a_filing_of_a_company_with_no_fiscal_year_end_is_skipped_not_raised():
    # chunk files for a company no longer in the company list
    filings = [*NVDA, ("OLD", "10-K", "2025-12-31")]
    assert query_report_dates("fiscal 2026 revenue", filings, FY_END).report_dates == ("2026-01-25",)
