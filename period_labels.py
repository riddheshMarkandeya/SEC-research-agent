"""
Period-label augmentation for retrieval indexing
--------------------------------------------------
Computes a canonical, natural-language period descriptor (fiscal year +
quarter, or "annual report") for a chunk from its ticker/form/reportDate
metadata, meant to be prepended to the text fed into BM25 tokenization
and embedding in index_chunks.py and retrieval.py's _load_bm25_index() —
NOT to the text stored/shown to the LLM, which already gets
ticker/form/reportDate via agent.py's citation header
(_format_results_block).

Why this exists: SEC filings restate the same reporting period in
multiple, non-overlapping vocabularies within the same document — a
"Highlights" narrative section says "the third quarter of fiscal year
2026," while the Notes/MD&A table covering the exact same period says
"Three Months Ended March 31, 2026." Neither BM25 nor embedding
similarity bridges that gap on its own: a question phrased one way can
completely miss the chunk that states the right number using the other
convention. A related problem: a company's own quarterly and annual
filings repeat large blocks of near-identical MD&A boilerplate (e.g.
"Gross profit consists of total net revenue less cost of revenue...")
across every filing, differing only in the trailing number — without a
per-filing anchor, retrieval can't tell which filing's copy is
relevant. Diagnosed from two real eval failures (nvda-gross-margin-fy26,
msft-rd-expense-q3fy26 — see PROJECT_CONTEXT.md), not a hypothetical
problem: each target chunk's BM25/vector rank was checked directly
before deciding this was worth building.
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
