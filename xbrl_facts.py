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

HEADERS = {"User-Agent": SEC_USER_AGENT}
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
# extra concept lookup or override per company. "OperatingIncomeLoss"
# (added for operating_margin) checked the same way: all five companies
# have recent entries, no overrides needed there either. "Assets" and
# "CashAndCashEquivalentsAtCarryingValue" (added to fix
# nvda-total-assets-q1fy27/aapl-cash-equivalents-q3fy2026 -- both were
# retrieval/attribution failures for values that turned out to be
# perfectly clean structured facts) checked the same way too: all five
# companies have recent entries for both, no overrides needed.
# "InventoryNet" (added to fix pltr-inventory-turnover-fy2025-refusal)
# checked the same way, with a twist worth keeping: it's clean for
# AAPL/MSFT/NVDA (recent entries, no overrides needed) but Palantir and
# Salesforce genuinely never tag it at all (404) -- not a data-quality
# gap to override, a real structural fact about their business models
# (software/services companies, no physical goods inventory). See
# is_metric_tagged() below for how that distinction gets surfaced to
# the model instead of silently looking identical to "just not tagged
# for this specific period."
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


def _duration_days(entry: dict) -> int | None:
    """None for an XBRL "instant" fact (a point-in-time balance, e.g.
    Assets or CashAndCashEquivalentsAtCarryingValue) -- these have no
    `start`, only `end`, unlike a "duration" fact (revenue, income,
    expenses) which is measured over a period and has both. Every
    metric this module supported before total_assets/cash_and_equivalents
    was duration-type, so this case was never exercised until adding
    those two crashed here with a bare KeyError."""
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
    SPECIFIC period that isn't available. Motivated by
    pltr-inventory-turnover-fy2025-refusal: Palantir genuinely never
    tags InventoryNet at all, unlike "just not this quarter" -- the
    model needs to know WHICH kind of missing this is to correctly
    explain why instead of fabricating, the same "why, not just that"
    principle behind the Q4-not-disclosed hint. Reuses fetch_concept()'s
    own disk cache, so this is a cache read, not a second network call,
    whenever get_metric() already tried (and failed at) the same lookup
    moments earlier."""
    return fetch_concept(ticker, _tag_for(ticker, metric)) is not None


def _latest_entry(entries: list[dict]) -> dict | None:
    """The most recently reported entry for a concept, across all
    fiscal years/periods, whatever its duration -- used when the caller
    doesn't (or can't) specify a period at all, e.g. "the most recent
    quarter." Found live: a real cross-company comparison question
    phrased exactly that way ("their most recent quarter") had no
    calendar date or fiscal label to give get_metric(), so the model
    called compare_financial_metric with no period at all, which
    silently returned nothing (fiscal_year=None never matches anything
    in _pick_entry) and the model abandoned the comparison entirely
    rather than retrying with an actual period.

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
    exactly on `period_end_date`.

    Replaces an earlier approach that first converted the date to a
    (fiscal_year, fiscal_period) guess (via period_labels.py's fiscal-
    year arithmetic, mirroring resolve_fiscal_period()'s old role) and
    matched entries on THAT computed label instead of on the date
    itself. That had a real, silent-failure-mode risk: fiscal-year
    arithmetic is a second, independent computation of something the
    data already states directly (every entry carries its own `end`
    date) -- if that arithmetic were ever off by one, it wouldn't fail
    loudly, it would silently match a DIFFERENT real entry that happens
    to share the (wrong) computed fy/fp label, rather than the one
    actually asked about. This is exactly the shape of bug already found
    once for a model-computed fiscal year (see get_metric's "Known
    limitation" note and PROJECT_CONTEXT.md's NVDA fiscal-year-vs-
    calendar-year case) -- reproducing the same risk inside our own
    lookup code, just one level removed from the model, defeated the
    point of fixing it there. Matching directly against `end` removes
    the risk by construction: there's no computed label to be wrong,
    only a string comparison against data SEC already returned.

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
    # The empty-string check matters on its own: a real, live-observed
    # model quirk (see agent.py's _call_get_financial_fact docstring for
    # the sibling case) is that for a question with no specific calendar
    # date ("total revenue for 2025"), the model called this with
    # period_end_date="" instead of omitting it or using
    # fiscal_year/fiscal_period -- an empty string must be treated as
    # "not provided" and fall through to the fiscal_year/fiscal_period
    # path, not as a date to match against (it never matches any real
    # `end` value, so this would return None either way, but the
    # fallback path is the one the caller actually meant).
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
# Naive plan was to compute a "CY{year}Q{quarter}" frame label myself
# from a calendar date using ordinary calendar-quarter math (Jan-Mar =
# Q1, Apr-Jun = Q2, ...). Checked against real data before writing any
# of that: NVIDIA's quarter ending April 26 is assigned frame
# "CY2026Q1" by SEC, not the naively-expected "CY2026Q2" -- SEC's own
# bucketing tolerates a wider window than strict calendar-month
# boundaries (to accommodate the many non-calendar fiscal years it
# aggregates across), and guessing that window would reproduce exactly
# the class of period-matching bug already fought twice in this file
# (the fiscal-year-from-calendar-date bug, and the quarter-vs-YTD
# disambiguation in _pick_entry). Every companyconcept entry already
# carries the SEC-assigned "frame" label directly (confirmed for all 5
# covered companies' latest entries), so frame lookups are anchored to
# one company's own already-verified get_metric() resolution instead of
# computed independently.
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


def get_frame(metric: str, frame: str) -> dict[str, dict]:
    """`metric` for every covered company that reported it under
    `frame`, keyed by ticker. A single frames call only covers filers
    using ONE specific tag -- since our own companies don't all use the
    same tag for some metrics (e.g. "revenue": NVDA uses "Revenues",
    the other four use the ASC 606 tag; see DEFAULT_METRIC_TAGS/
    METRIC_TAG_OVERRIDES above), a single tag query would silently omit
    whichever covered companies use a different tag for that metric --
    the same class of bug as the original revenue-tag-default mistake,
    just at the frames layer instead of companyconcept. Queries every
    distinct tag actually in play for `metric` across the 5 covered
    companies and merges the results, so this is robust to that by
    construction rather than by remembering to special-case it."""
    companies = load_companies()
    cik_to_ticker = {int(info["cik"]): ticker for ticker, info in companies.items()}
    tags_in_play = {_tag_for(ticker, metric) for ticker in companies}

    results: dict[str, dict] = {}
    for tag in tags_in_play:
        data = fetch_frame(tag, frame)
        if data is None:
            continue
        for entry in data.get("data", []):
            ticker = cik_to_ticker.get(entry["cik"])
            if ticker is None or ticker in results:
                continue
            results[ticker] = {
                "value": entry["val"],
                "unit": "USD",
                "period_end": entry["end"],
                "accession": entry["accn"],
            }
    return results


def get_metric_all_companies(
    ticker: str,
    metric: str,
    fiscal_year: int | None = None,
    fiscal_period: str = "FY",
    period_end_date: str | None = None,
) -> dict[str, dict]:
    """`metric` for every covered company, for the same period bucket as
    `ticker`'s own period (specified the same way as get_metric() —
    fiscal_year+fiscal_period, or period_end_date). Resolves `ticker`'s
    own fact first via get_metric() to read off its SEC-assigned
    `frame` label, then fetches that frame for every covered company —
    see the module-level comment above for why this doesn't compute the
    frame label independently.

    Falls back to every OTHER covered company's own entry for the same
    period if `ticker`'s own has no frame, trying `ticker` first so
    today's behavior/tests are unaffected when it already works. Found
    in code review (2026-09-06): SEC doesn't assign a frame to the
    newest annual instant-fact entry for some companies (confirmed
    against real data for total_assets/cash_and_equivalents/inventory),
    which silently made cross-company comparisons of those metrics at
    the latest fiscal year return nothing even though every individual
    company's value is directly retrievable. `frame` is a property of
    the (metric, period) pair, not of any one company, so any covered
    company's real, SEC-assigned frame for that period is an equally
    valid anchor — this never computes a frame label itself, only
    reuses ones SEC already assigned. Returns {} only if no covered
    company has a usable frame for this period."""
    companies = load_companies()
    candidates = [ticker] + [t for t in companies if t != ticker]
    for candidate in candidates:
        anchor = get_metric(candidate, metric, fiscal_year, fiscal_period, period_end_date)
        if anchor is not None and anchor.get("frame") is not None:
            return get_frame(metric, anchor["frame"])
    return {}
