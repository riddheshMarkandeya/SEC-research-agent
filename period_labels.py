"""
Fiscal-period math (fiscal_year_label, fiscal_quarter) plus a
natural-language period-label string (period_label/chunk_period_label).
The period-label string was originally built to prepend to chunk text
for retrieval indexing -- that indexing use was tried and reverted; the
fiscal-period math is still used by verify_period_labels.py's
fiscal-year-end safeguard. See
docs/decisions/2026-08-16-fiscal-period-labels-tried-and-reverted.md.
"""

from datetime import date

from companies import load_companies


def fiscal_year_label(fiscal_year_end_month: int, report_date: date) -> int:
    """Every company covered here names a fiscal year after the calendar
    year its period END falls in (e.g. NVIDIA's fiscal year ending Jan
    25, 2026 is "fiscal year 2026"; its quarter ending Apr 26, 2026 is
    part of "fiscal year 2027", since fiscal 2027 hasn't ended yet
    within calendar 2026). Verified against each company's own
    self-description in its filing text before trusting this, not
    assumed — e.g. NVIDIA's 10-Q literally says "In the first quarter of
    fiscal year 2027" for the quarter ended April 26, 2026."""
    if report_date.month <= fiscal_year_end_month:
        return report_date.year
    return report_date.year + 1


def fiscal_quarter(fiscal_year_end_month: int, report_date: date) -> int:
    """Buckets report_date into fiscal Q1-Q4 relative to the company's
    own fiscal year end month. Q4 is also the quarter the annual report
    (10-K) covers, though callers should use "annual report" wording for
    10-Ks rather than "quarter 4" — see period_label()."""
    return ((report_date.month - fiscal_year_end_month - 1) % 12) // 3 + 1


def period_label(ticker: str, form: str, report_date_str: str, fiscal_year_end_month: int) -> str:
    """A short natural-language sentence describing a filing's period,
    meant to be prepended to a chunk's text before BM25 tokenization and
    embedding — see module docstring for why."""
    report_date = date.fromisoformat(report_date_str)
    fy = fiscal_year_label(fiscal_year_end_month, report_date)
    natural_date = f"{report_date:%B} {report_date.day}, {report_date.year}"
    if form == "10-K":
        return f"{ticker} annual report, fiscal year {fy}, for the fiscal year ended {natural_date}."
    quarter = fiscal_quarter(fiscal_year_end_month, report_date)
    return (
        f"{ticker} quarterly report, fiscal year {fy} quarter {quarter}, "
        f"for the three months ended {natural_date}."
    )


def chunk_period_label(ticker: str, form: str, report_date_str: str) -> str:
    """Convenience wrapper that looks up the company's fiscal-year-end
    month from companies.json rather than requiring every caller to pass
    it explicitly."""
    companies = load_companies()
    fiscal_year_end_month = companies[ticker]["fiscal_year_end_month"]
    return period_label(ticker, form, report_date_str, fiscal_year_end_month)
