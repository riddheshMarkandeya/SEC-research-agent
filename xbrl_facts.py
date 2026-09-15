"""
Structured XBRL facts tool: a second agent tool, alongside
`search_filings` (retrieval.hybrid_search), for fetching a GAAP concept
directly by (company, concept, period) instead of relying on retrieval
to surface it from filing prose. See
docs/decisions/2026-08-16-xbrl-structured-facts-tool.md for why this
exists and docs/decisions/2026-08-16-fiscal-period-labels-tried-and-reverted.md
for the retrieval-side alternative that was tried and reverted first.

Endpoint: SEC's `companyconcept` API (one concept, full filing history),
not the much larger `companyfacts` API (every concept the company has
ever tagged) — a single agent tool call should fetch one metric.

Usage:
    from xbrl_facts import get_metric
    get_metric("MSFT", "rd_expense", fiscal_year=2026, fiscal_period="Q3")

Derived ratios/growth (gross_margin, yoy_growth, etc.) live in
formulas.py, not here -- see that module's docstring for why.
"""

import json
import time
from datetime import date
from pathlib import Path

import requests

from companies import load_companies
from config import SEC_USER_AGENT
from tracing import log_event

HEADERS = {"User-Agent": SEC_USER_AGENT}
CACHE_DIR = Path("./xbrl_cache")
REQUEST_DELAY_SECONDS = 0.3  # match edgar_ingest.py's courtesy delay

# DEFAULT_METRIC_TAGS/METRIC_TAG_OVERRIDES map friendly metric names to
# real GAAP tags, with a per-company override where no single tag works
# for all five covered companies (e.g. revenue: NVDA still uses
# "Revenues" while the other four use the ASC 606 tag). Each tag here
# was verified against real fetched data for all 5 companies, not
# assumed from a status code alone -- see
# docs/decisions/2026-09-15-xbrl-tag-selection-methodology.md for the
# full methodology and per-metric findings (including why InventoryNet's
# 404 for PLTR/CRM is a real business-model fact, not a gap to override).
#
# Adding a new metric here that's an XBRL "instant" (point-in-time
# balance) concept, not "duration"? Add it to INSTANT_METRICS below too
# -- see that set's own comment for why.
DEFAULT_METRIC_TAGS = {
    "revenue": "RevenueFromContractWithCustomerExcludingAssessedTax",
    "gross_profit": "GrossProfit",
    "cost_of_revenue": "CostOfRevenue",
    "rd_expense": "ResearchAndDevelopmentExpense",
    "net_income": "NetIncomeLoss",
    "operating_income": "OperatingIncomeLoss",
    "total_assets": "Assets",
    "cash_and_equivalents": "CashAndCashEquivalentsAtCarryingValue",
    "inventory": "InventoryNet",
}
METRIC_TAG_OVERRIDES = {
    "NVDA": {"revenue": "Revenues"},
}

# The only 3 metrics tagged to an XBRL "instant" (point-in-time balance)
# concept -- everything else in DEFAULT_METRIC_TAGS is "duration"
# (measured over a period). _duration_days()'s own docstring already
# confirms one concept's entries are consistently all-instant or
# all-duration, never mixed, so a static per-metric classification here
# is valid. Used by get_metric_all_companies() below to resolve instant
# metrics differently from duration ones (see that function's docstring
# for why).
INSTANT_METRICS = {"total_assets", "cash_and_equivalents", "inventory"}

# A companyconcept response's entries aren't one-per-period: a single
# 10-K/10-Q re-reports 2-3 years (or the prior-year comparative quarter)
# of the same concept, all sharing the filing's own fy/fp label (e.g.
# NVDA's FY2026 10-K reports FY2024/FY2025/FY2026 GrossProfit under one
# fy/fp label; MSFT's Q3 FY26 10-Q reports the current quarter, the
# prior-year comparative quarter, AND two 9-month YTD figures under
# another). Disambiguation needs BOTH a duration filter (quarter vs. the
# filing's own YTD figure, which shares the quarter's `end` date) and a
# max(end) tiebreak (current period vs. a same-duration prior-year
# comparative, which always has an earlier `end`). See
# docs/decisions/2026-08-16-xbrl-structured-facts-tool.md.
_QUARTER_DURATION_DAYS = (80, 100)
_ANNUAL_DURATION_DAYS = (350, 380)


def _duration_days(entry: dict) -> int | None:
    """None for an XBRL "instant" fact (a point-in-time balance, e.g.
    Assets or CashAndCashEquivalentsAtCarryingValue) -- these have no
    `start`, only `end`, unlike a "duration" fact (revenue, income,
    expenses) which is measured over a period and has both. See
    docs/decisions/2026-08-19-fixing-6-accumulated-eval-findings.md."""
    if "start" not in entry:
        return None
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


def is_metric_tagged(ticker: str, metric: str) -> bool:
    """True if `ticker` tags `metric` in its XBRL filings AT ALL (any
    period, ever) -- distinct from get_metric() returning None for one
    SPECIFIC period that isn't available. See
    docs/decisions/2026-08-19-fixing-6-accumulated-eval-findings.md and
    docs/decisions/2026-09-15-xbrl-tag-selection-methodology.md. Reuses
    fetch_concept()'s own disk cache, so this is a cache read, not a
    second network call, whenever get_metric() already tried (and
    failed at) the same lookup moments earlier."""
    return fetch_concept(ticker, _tag_for(ticker, metric)) is not None


def _latest_entry(entries: list[dict]) -> dict | None:
    """The most recently reported entry for a concept, across all
    fiscal years/periods, whatever its duration -- used when the caller
    doesn't (or can't) specify a period at all, e.g. "the most recent
    quarter." See docs/decisions/2026-08-17-frames-api-cross-company.md
    for why this exists.

    Ties at the same `end` date (a fresh 10-Q's own quarter-length
    figure and its same-report 9-month year-to-date cumulative share an
    end date) are broken toward the SHORTER duration — "the most recent
    quarter" means the quarter itself, not a multi-quarter cumulative
    figure that happens to end on the same day. An instant fact (no
    duration to break ties with -- see `_duration_days()`) falls back to
    a third-level tiebreak on `filed`, most recent wins; this never
    interacts with the duration tiebreak above since one concept's
    entries are consistently either all-instant or all-duration, never
    a mix."""
    if not entries:
        return None
    return max(entries, key=lambda e: (e["end"], -(_duration_days(e) or 0), e.get("filed") or ""))


def _pick_entry(entries: list[dict], fiscal_year: int, fiscal_period: str) -> dict | None:
    """Filter a concept's USD entries down to the one true value for
    (fiscal_year, fiscal_period), applying the duration + max(end)
    disambiguation documented above. Returns None if nothing matches.

    An instant fact (`_duration_days()` returns None -- see its
    docstring) skips the duration-bucket check entirely: there's no
    quarter-vs-YTD-cumulative collision to disambiguate for a
    point-in-time balance, so fy/fp/form matching alone is already
    unambiguous (confirmed against real NVDA Assets data, where two
    entries share an `end` date but differ on fy/fp/form)."""
    is_annual = fiscal_period == "FY"
    lo, hi = _ANNUAL_DURATION_DAYS if is_annual else _QUARTER_DURATION_DAYS
    expected_form = "10-K" if is_annual else "10-Q"

    candidates = [
        e
        for e in entries
        if e.get("fy") == fiscal_year
        and e.get("fp") == fiscal_period
        and e.get("form") == expected_form
        and (_duration_days(e) is None or lo <= _duration_days(e) <= hi)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda e: e["end"])


def _pick_entry_by_end_date(entries: list[dict], period_end_date: str) -> dict | None:
    """Filter a concept's USD entries down to the one true value ending
    exactly on `period_end_date`, matched directly against each entry's
    own `end` date rather than a computed fiscal-year/fiscal-period
    label -- see docs/decisions/2026-08-17-xbrl-period-matching-end-date-fix.md
    for why matching on a computed label is a real, silent-failure-mode
    risk this avoids by construction.

    Duration still disambiguates a quarter's own figure from an
    annual/YTD figure that happens to share the same `end` date (see the
    module-level comment above _QUARTER_DURATION_DAYS) -- a quarter-
    length entry is preferred when both exist for the same end date.
    That collision is rare in practice: it would require a fiscal year's
    own end date to also have a standalone quarter entry, and get_metric's
    docstring already notes most of these companies don't separately tag
    a standalone Q4 -- so a fiscal-year-end date usually has ONLY an
    annual-duration entry to begin with, not a competing quarter one.

    An instant fact (`_duration_days()` returns None -- see its
    docstring) has no quarter-vs-annual collision to disambiguate at
    all, since a point-in-time balance has no accumulation window --
    falls back to a third pool matched on end-date alone, still broken
    by the same most-recently-filed tiebreak below."""
    candidates = [e for e in entries if e["end"] == period_end_date]
    if not candidates:
        return None
    quarters = [
        e for e in candidates
        if _duration_days(e) is not None and _QUARTER_DURATION_DAYS[0] <= _duration_days(e) <= _QUARTER_DURATION_DAYS[1]
    ]
    annual = [
        e for e in candidates
        if _duration_days(e) is not None and _ANNUAL_DURATION_DAYS[0] <= _duration_days(e) <= _ANNUAL_DURATION_DAYS[1]
    ]
    instant = [e for e in candidates if _duration_days(e) is None]
    pool = quarters or annual or instant
    if not pool:
        return None
    # Same end date can legitimately appear more than once (e.g. this
    # year's 10-Q and next year's 10-Q both report last year's comparative
    # quarter) -- prefer whichever was filed most recently, since a later
    # filing is never less authoritative than an earlier restatement of
    # the same period.
    return max(pool, key=lambda e: e.get("filed") or "")


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
      2026") -- matched directly against each entry's own `end` date via
      _pick_entry_by_end_date() rather than trusting the caller (or our
      own fiscal-year arithmetic) to convert it to a fiscal label first;
      see that function's docstring for why matching on the date itself
      is safer than matching on a computed label.

    Known limitation: NVIDIA (and most annual filers) don't separately
    tag a standalone Q4 duration -- Q4 is implicitly "FY minus the three
    10-Q quarters," not a directly reported concept. fiscal_period="Q4"
    will return None for such companies; not solved here since neither
    target eval question needs it.

    A third way: give NEITHER (fiscal_year stays None, period_end_date
    stays falsy) to get the single most recently reported value instead
    -- for "the most recent quarter," where the caller has no specific
    date or fiscal label to give. See _latest_entry()'s docstring for
    why this was added (a real cross-company comparison question
    phrased exactly that way silently returned nothing before this
    existed).

    Returns {"value": float, "unit": "USD", "period_end": "YYYY-MM-DD",
    "form": str, "accession": str, "fiscal_year": int, "fiscal_period":
    str, ...} or None if unavailable (caller should fall back to
    search_filings). fiscal_year/fiscal_period are read directly off the
    matched entry's own fy/fp fields (not recomputed) -- get_yoy_growth()
    anchors on these to find the prior-year period without doing any
    date arithmetic itself.
    """
    tag = _tag_for(ticker, metric)
    data = fetch_concept(ticker, tag)
    if data is None:
        return None
    entries = data.get("units", {}).get("USD", [])
    # An empty string must be treated as "not provided" and fall through
    # to the fiscal_year/fiscal_period path, not as a date to match
    # against -- see docs/decisions/2026-08-16-xbrl-structured-facts-tool.md
    # (bug #4) and agent.py's own sibling case for the model quirk this
    # guards against.
    if period_end_date:
        entry = _pick_entry_by_end_date(entries, period_end_date)
    elif fiscal_year is None:
        entry = _latest_entry(entries)
    else:
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
        "frame": entry.get("frame"),
        "fiscal_year": entry.get("fy"),
        "fiscal_period": entry.get("fp"),
    }


# ---------------------------------------------------------------------------
# frames — one metric, every covered company, one (or few) API calls
# ---------------------------------------------------------------------------
# The frame label is never computed independently from a calendar date
# (SEC's own quarter bucketing doesn't follow ordinary calendar-quarter
# math for non-calendar fiscal years -- see
# docs/decisions/2026-08-17-frames-api-cross-company.md). Every
# companyconcept entry already carries the SEC-assigned "frame" label
# directly, so frame lookups are anchored to one company's own
# already-verified get_metric() resolution instead.
def fetch_frame(tag: str, frame: str) -> dict | None:
    """Fetch one us-gaap concept for every SEC filer that reported it
    for a given frame (e.g. "CY2026Q1"), cached to disk indefinitely —
    same rationale as fetch_concept(). Returns None on a 404 (the tag
    isn't reported for that particular frame at all, a real outcome for
    some tag/frame combinations, not an error)."""
    CACHE_DIR.mkdir(exist_ok=True)
    cache_path = CACHE_DIR / f"frame_{tag}_{frame}.json"
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))

    url = f"https://data.sec.gov/api/xbrl/frames/us-gaap/{tag}/USD/{frame}.json"
    resp = requests.get(url, headers=HEADERS)
    time.sleep(REQUEST_DELAY_SECONDS)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    data = resp.json()
    cache_path.write_text(json.dumps(data), encoding="utf-8")
    return data


def _frame_entry(entry: dict) -> dict:
    """One frame-API `data` entry, normalized to the same shape get_frame()
    returns per ticker -- factored out so get_frame()'s tag-override
    branch (see below) doesn't have to duplicate this construction."""
    return {
        "value": entry["val"],
        "unit": "USD",
        "period_end": entry["end"],
        "accession": entry["accn"],
    }


def get_frame(metric: str, frame: str) -> dict[str, dict]:
    """`metric` for every covered company that reported it under
    `frame`, keyed by ticker. A single frames call only covers filers
    using ONE specific tag -- since our own companies don't all use the
    same tag for some metrics (see DEFAULT_METRIC_TAGS/
    METRIC_TAG_OVERRIDES above and
    docs/decisions/2026-09-15-xbrl-tag-selection-methodology.md), a
    single-tag query would silently omit whichever covered companies use
    a different tag. Queries every distinct tag actually in play for
    `metric` and merges the results, robust to that by construction."""
    companies = load_companies()
    cik_to_ticker = {int(info["cik"]): ticker for ticker, info in companies.items()}
    # sorted(), not a bare set iteration, for deterministic processing
    # order if two distinct tags ever report data for the SAME ticker --
    # only a FALLBACK tie-break; the ticker's-own-designated-tag
    # preference below decides the winner in the common case. See
    # docs/decisions/2026-09-09-citation-gap-frame-ordering-retrieval-verify.md.
    tags_in_play = sorted({_tag_for(ticker, metric) for ticker in companies})

    results: dict[str, dict] = {}
    winning_tag: dict[str, str] = {}
    for tag in tags_in_play:
        data = fetch_frame(tag, frame)
        if data is None:
            continue
        for entry in data.get("data", []):
            ticker = cik_to_ticker.get(entry["cik"])
            if ticker is None:
                continue
            if ticker in results:
                if tag == winning_tag[ticker]:
                    # Same-tag duplicate entry (e.g. an amended filing
                    # appearing twice under one accession), not a
                    # cross-tag disagreement -- must not be mislabeled as
                    # one below. First-entry-wins here, silently.
                    continue
                # Prefer the ticker's OWN designated tag over whichever
                # tag happened to be processed first: _tag_for(ticker,
                # metric) already gives the objectively correct answer
                # for THIS ticker, so a plain alphabetical tie-break
                # would be arbitrary, not principled. See
                # docs/decisions/2026-09-09-citation-gap-frame-ordering-retrieval-verify.md.
                designated_tag = _tag_for(ticker, metric)
                if tag == designated_tag:
                    log_event(
                        "xbrl_tag_conflict",
                        metric=metric,
                        frame=frame,
                        ticker=ticker,
                        winning_tag=tag,
                        winning_value=entry["val"],
                        discarded_tag=winning_tag[ticker],
                        discarded_value=results[ticker]["value"],
                    )
                    winning_tag[ticker] = tag
                    results[ticker] = _frame_entry(entry)
                    continue
                log_event(
                    "xbrl_tag_conflict",
                    metric=metric,
                    frame=frame,
                    ticker=ticker,
                    winning_tag=winning_tag[ticker],
                    winning_value=results[ticker]["value"],
                    discarded_tag=tag,
                    discarded_value=entry["val"],
                )
                continue
            winning_tag[ticker] = tag
            results[ticker] = _frame_entry(entry)
    return results


def get_metric_all_companies(
    ticker: str,
    metric: str,
    fiscal_year: int | None = None,
    fiscal_period: str = "FY",
    period_end_date: str | None = None,
) -> dict[str, dict]:
    """`metric` for every covered company, for the same period
    (specified the same way as get_metric() — fiscal_year+fiscal_period,
    or period_end_date).

    Instant (balance-sheet) metrics -- INSTANT_METRICS, i.e.
    total_assets/cash_and_equivalents/inventory -- are resolved
    independently per company: no SEC frame, no anchor requirement at
    all. Real financial-analysis practice ("calendarization") explains
    why: calendar-window alignment across companies is standard for
    income-statement/cash-flow (duration) figures, but explicitly NOT
    applied to balance-sheet figures -- a balance is a snapshot as of
    one date, not a period that can be shifted. Each company's own
    real, correctly-resolved period_end is returned as-is; a company
    with no data for the period is simply excluded, not fatal to the
    others.

    Known limitation: calling this with `period_end_date` instead of
    fiscal_year/fiscal_period passes the identical literal date to every
    company, and different companies' balance-sheet snapshots essentially
    never land on the exact same calendar date -- so a period_end_date-
    anchored instant comparison effectively collapses to whichever
    company (usually only the caller's own anchor) happens to match
    exactly. fiscal_year/fiscal_period doesn't have this problem: each
    company resolves its OWN fy/fp labels independently. Not fixed here;
    revisit if a real question needs it. See
    docs/decisions/2026-09-07-fix-get-metric-all-companies-instant-metrics.md
    for why instant metrics are resolved independently per company at
    all (no SEC frame, no anchor requirement), rather than via the same
    frame-borrowing mechanism duration metrics use below.

    Duration metrics (revenue, income, etc.) resolve `ticker`'s own fact
    via get_metric() to read its SEC-assigned `frame`, then fetch that
    frame for every covered company (see the module-level comment above
    for why this doesn't compute the frame label independently). Returns
    {} if `ticker`'s own fact isn't available or has no frame, with NO
    fallback to another company's frame -- see the decision file above
    for why a same-company-frame fallback here would reintroduce the
    exact bug that redesign fixed for instant metrics."""
    if metric in INSTANT_METRICS:
        results: dict[str, dict] = {}
        for candidate in load_companies():
            fact = get_metric(candidate, metric, fiscal_year, fiscal_period, period_end_date)
            if fact is not None:
                results[candidate] = fact
        return results
    anchor = get_metric(ticker, metric, fiscal_year, fiscal_period, period_end_date)
    if anchor is None or anchor.get("frame") is None:
        return {}
    return get_frame(metric, anchor["frame"])
