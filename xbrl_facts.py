"""
Week 5b — Structured XBRL facts tool
-------------------------------------
A second agent tool, alongside `search_filings` (retrieval.hybrid_search).
Built to fix two eval failures (`nvda-gross-margin-fy26`,
`msft-rd-expense-q3fy26`) that turned out to be a structural retrieval
limit, not a query-formulation or model-comprehension problem: NVIDIA's
71.1% gross margin and Microsoft's $8,915M Q3 FY26 R&D expense are both
numbers that live in unstructured prose competing against near-duplicate
boilerplate from the company's other filings (see PROJECT_CONTEXT.md's
`period_labels.py` section for the retrieval-side fix that was tried and
reverted). Both numbers are also GAAP concepts SEC filers tag in
structured XBRL data, fetchable directly by (company, concept, period) —
sidestepping the retrieval-collision problem for this class of question
entirely, rather than trying to out-rank the decoys.

Endpoint: SEC's `companyconcept` API (one concept, full filing history),
not the much larger `companyfacts` API (every concept the company has
ever tagged) — a single agent tool call should fetch one metric.

Usage:
    from xbrl_facts import get_metric, get_gross_margin
    get_metric("MSFT", "rd_expense", fiscal_year=2026, fiscal_period="Q3")
    get_gross_margin("NVDA", fiscal_year=2026, fiscal_period="FY")
"""

import json
import time
from datetime import date
from pathlib import Path

import requests

from companies import load_companies
from period_labels import fiscal_quarter, fiscal_year_label

HEADERS = {"User-Agent": "Rid riddhesh2307@gmail.com"}
CACHE_DIR = Path("./xbrl_cache")
REQUEST_DELAY_SECONDS = 0.3  # match edgar_ingest.py's courtesy delay

# Verified against real companyconcept responses, but this took two
# passes to get right, and the second pass is the important lesson: a
# 200 status code on a concept URL only means the company has EVER
# tagged that concept, not that it still tags it in RECENT filings.
# First pass checked only status codes and defaulted "revenue" to
# "Revenues" (200 for AAPL/MSFT/NVDA/CRM) with PLTR as the sole
# override (its "Revenues" 404s). That looked right until a live
# comparison-question test asked for CRM's most recent quarter and
# silently got nothing back -- checking the actual latest entry per
# company (not just the status code) showed AAPL's "Revenues" data
# stops in 2018 and MSFT's stops in 2011: both switched to the more
# specific ASC 606 tag years ago and never looked back. CRM's most
# recent quarter has the same gap. NVDA is the actual outlier, still
# actively using plain "Revenues" through its latest 2026 filings (and
# NVDA's own past use of the ASC 606 tag stops in 2022, so it can't be
# the default either) -- there's no single tag that works for all five
# companies, which is exactly why this is a per-company override map
# and not one shared default. All five companies do tag "GrossProfit"
# directly through their latest filings (checked the same way), which
# is what makes gross-margin-as-a-tool-computed-ratio viable without an
# extra concept lookup or override per company.
DEFAULT_METRIC_TAGS = {
    "revenue": "RevenueFromContractWithCustomerExcludingAssessedTax",
    "gross_profit": "GrossProfit",
    "cost_of_revenue": "CostOfRevenue",
    "rd_expense": "ResearchAndDevelopmentExpense",
    "net_income": "NetIncomeLoss",
}
METRIC_TAG_OVERRIDES = {
    "NVDA": {"revenue": "Revenues"},
}

# A companyconcept response's entries aren't one-per-period: a single
# 10-K/10-Q re-reports 2-3 years (or the prior-year comparative quarter)
# of the same concept in the same filing, all sharing the filing's own
# fy/fp label. Verified on NVDA's FY2026 10-K (accn 0001045810-26-000021):
# its GrossProfit entries for fy=2026/fp="FY" include FY2024, FY2025, AND
# FY2026's own values, distinguished only by `end` date. And on MSFT's
# Q3 FY26 10-Q (accn 0001193125-26-191507): its ResearchAndDevelopment-
# Expense entries for fy=2026/fp="Q3" include the current 3-month figure,
# the prior-year comparative 3-month figure, AND two 9-month
# year-to-date figures -- same fy/fp, different (start, end, duration).
# So disambiguation needs BOTH a duration filter (to separate a quarter
# from its filing's own 9-month YTD figure, which shares the quarter's
# `end` date) and a max(end) tiebreak (to separate the current period
# from a same-duration prior-year comparative, which always has an
# earlier `end`).
_QUARTER_DURATION_DAYS = (80, 100)
_ANNUAL_DURATION_DAYS = (350, 380)


def _duration_days(entry: dict) -> int:
    start = date.fromisoformat(entry["start"])
    end = date.fromisoformat(entry["end"])
    return (end - start).days


def _tag_for(ticker: str, metric: str) -> str:
    overrides = METRIC_TAG_OVERRIDES.get(ticker, {})
    tag = overrides.get(metric, DEFAULT_METRIC_TAGS.get(metric))
    if tag is None:
        raise ValueError(f"Unknown metric {metric!r} (known: {sorted(DEFAULT_METRIC_TAGS)})")
    return tag


def fetch_concept(ticker: str, tag: str) -> dict | None:
    """Fetch a company's full history for one us-gaap concept, cached to
    disk indefinitely (SEC data for a past period doesn't change once
    filed; delete the cache file to force a refetch after a new filing).
    Returns None if the company doesn't tag this concept at all (a 404
    is a real, expected outcome — see METRIC_TAG_OVERRIDES above — not
    an error)."""
    CACHE_DIR.mkdir(exist_ok=True)
    cache_path = CACHE_DIR / f"{ticker}_{tag}.json"
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))

    companies = load_companies()
    cik = companies[ticker]["cik"]
    url = f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/{tag}.json"
    resp = requests.get(url, headers=HEADERS)
    time.sleep(REQUEST_DELAY_SECONDS)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    data = resp.json()
    cache_path.write_text(json.dumps(data), encoding="utf-8")
    return data


def _pick_entry(entries: list[dict], fiscal_year: int, fiscal_period: str) -> dict | None:
    """Filter a concept's USD entries down to the one true value for
    (fiscal_year, fiscal_period), applying the duration + max(end)
    disambiguation documented above. Returns None if nothing matches."""
    is_annual = fiscal_period == "FY"
    lo, hi = _ANNUAL_DURATION_DAYS if is_annual else _QUARTER_DURATION_DAYS
    expected_form = "10-K" if is_annual else "10-Q"

    candidates = [
        e
        for e in entries
        if e.get("fy") == fiscal_year
        and e.get("fp") == fiscal_period
        and e.get("form") == expected_form
        and lo <= _duration_days(e) <= hi
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda e: e["end"])


def resolve_fiscal_period(ticker: str, period_end_date: str) -> tuple[int, str]:
    """Convert a calendar period-end date into the (fiscal_year,
    fiscal_period) pair XBRL's own fy/fp fields use, via period_labels.py's
    verified fiscal-year math.

    Exists because of a real, reproduced bug: for a comparison question
    phrased with a calendar date ("the quarter ended April 26, 2026"),
    the tool-calling model reliably passed fiscal_year=2026 directly
    (the calendar year), not realizing NVDA/CRM's January fiscal year
    end means that date falls in fiscal year 2027 -- a WRONG-BUT-VALID
    period match (fy=2026/Q1 exists, just for the wrong, year-earlier
    quarter), so it failed silently rather than erroring. Confirmed via
    a direct agent.py repro before fixing: the model called
    get_financial_fact(ticker='NVDA', fiscal_year=2026, fiscal_period='Q1')
    for a question about the quarter ended April 26, 2026, which should
    have been fiscal_year=2027. Doing this conversion in code instead of
    asking the model to do fiscal-year arithmetic reuses period_labels.py,
    which was already built and verified against real filings for
    exactly this calculation -- see PROJECT_CONTEXT.md for why an
    earlier, different application of that same module (as an embedding
    prefix) was tried and reverted; this is the "future, more targeted
    application" flagged there."""
    companies = load_companies()
    fiscal_year_end_month = companies[ticker]["fiscal_year_end_month"]
    rd = date.fromisoformat(period_end_date)
    fy = fiscal_year_label(fiscal_year_end_month, rd)
    q = fiscal_quarter(fiscal_year_end_month, rd)
    return fy, f"Q{q}"


def get_metric(
    ticker: str,
    metric: str,
    fiscal_year: int | None = None,
    fiscal_period: str = "FY",
    period_end_date: str | None = None,
) -> dict | None:
    """Look up one structured financial fact.

    Two ways to specify the period -- callers give exactly one:
    - fiscal_year + fiscal_period ("FY" or "Q1"/"Q2"/"Q3"/"Q4"): the same
      labels the filings themselves use, for when a question already
      states the period in fiscal terms ("fiscal year 2026").
    - period_end_date (a calendar "YYYY-MM-DD"): for when a question
      states a calendar date instead ("the quarter ended April 26,
      2026") -- resolved to the right fiscal_year/fiscal_period via
      resolve_fiscal_period() rather than trusting the caller to do that
      arithmetic (see resolve_fiscal_period's docstring for why that
      matters).

    Known limitation: NVIDIA (and most annual filers) don't separately
    tag a standalone Q4 duration -- Q4 is implicitly "FY minus the three
    10-Q quarters," not a directly reported concept. fiscal_period="Q4"
    will return None for such companies; not solved here since neither
    target eval question needs it.

    Returns {"value": float, "unit": "USD", "period_end": "YYYY-MM-DD",
    "form": str, "accession": str} or None if unavailable (caller should
    fall back to search_filings).
    """
    if period_end_date:
        # Another real, live-observed model quirk (see agent.py's
        # _call_get_financial_fact docstring for the sibling case): for
        # a question with no specific calendar date ("total revenue for
        # 2025"), the model called this with period_end_date="" instead
        # of omitting it or using fiscal_year/fiscal_period, which
        # crashed date.fromisoformat with an unhandled ValueError and
        # took down the whole eval run. The truthy check handles the
        # empty-string case; the try/except is defense-in-depth for a
        # non-empty but malformed date the model might send instead.
        try:
            fiscal_year, fiscal_period = resolve_fiscal_period(ticker, period_end_date)
        except ValueError:
            return None
    tag = _tag_for(ticker, metric)
    data = fetch_concept(ticker, tag)
    if data is None:
        return None
    entries = data.get("units", {}).get("USD", [])
    entry = _pick_entry(entries, fiscal_year, fiscal_period)
    if entry is None:
        return None
    return {
        "value": entry["val"],
        "unit": "USD",
        "period_end": entry["end"],
        "form": entry["form"],
        "accession": entry["accn"],
        "filed": entry.get("filed"),
    }


def get_gross_margin(
    ticker: str,
    fiscal_year: int | None = None,
    fiscal_period: str = "FY",
    period_end_date: str | None = None,
) -> dict | None:
    """Gross margin isn't itself a GAAP-tagged concept (percentages are
    prose/MD&A, not structured facts) -- computed here from two
    structured facts (GrossProfit / Revenues) instead of returned raw
    for the model to divide, so agent.py's "don't infer/combine numbers"
    rule doesn't need to be relaxed for this tool's output. See
    get_metric() for the fiscal_year/fiscal_period vs. period_end_date
    tradeoff -- resolved once here rather than in each get_metric() call
    so both legs use the identical resolved period, and see get_metric's
    body for why this is a truthy check + try/except rather than an
    `is not None` check."""
    if period_end_date:
        try:
            fiscal_year, fiscal_period = resolve_fiscal_period(ticker, period_end_date)
        except ValueError:
            return None
    gross_profit = get_metric(ticker, "gross_profit", fiscal_year, fiscal_period)
    revenue = get_metric(ticker, "revenue", fiscal_year, fiscal_period)
    if gross_profit is None or revenue is None:
        return None
    if gross_profit["period_end"] != revenue["period_end"]:
        return None
    margin_pct = gross_profit["value"] / revenue["value"] * 100
    return {
        "value": round(margin_pct, 1),
        "unit": "percent",
        "period_end": gross_profit["period_end"],
        "form": gross_profit["form"],
        "accession": gross_profit["accession"],
        "filed": gross_profit["filed"],
    }
