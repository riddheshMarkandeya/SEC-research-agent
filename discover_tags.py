"""
Dev-time XBRL tag discovery: fetch SEC's `companyfacts` API, which
returns EVERY tag a company has ever reported across all taxonomies in
one response, and let you browse/search it directly to find candidate
metrics before writing (or debugging) an eval question, instead of
discovering one only after an eval question fails. See
docs/decisions/2026-08-19-discover-tags-dev-tool.md.

Deliberately NOT used by the runtime agent path: xbrl_facts.py's
fetch_concept() stays on the narrower `companyconcept` endpoint (one tag
per call, ~KBs) because one agent tool call should fetch one metric, not
the multi-MB everything-payload this module fetches (companyfacts
returned 503 us-gaap tags / ~3.8MB for AAPL alone). This is a research
tool you run by hand, not something agent.py imports.

Usage (library):
    from discover_tags import list_tags
    list_tags("PLTR", keyword="inventory")
    list_tags("AAPL", recent_only=True)  # only tags AAPL still reports

Usage (CLI):
    python discover_tags.py PLTR --keyword inventory
    python discover_tags.py AAPL --recent-only
"""

import argparse
import json
import time
from datetime import date, timedelta
from pathlib import Path

import requests

from companies import load_companies
from config import SEC_USER_AGENT

HEADERS = {"User-Agent": SEC_USER_AGENT}
CACHE_DIR = Path("./xbrl_cache")
REQUEST_DELAY_SECONDS = 0.3  # match xbrl_facts.py's courtesy delay

# A tag existing in companyfacts at all doesn't mean the company still
# reports it -- xbrl_facts.py hit this exact trap with "Revenues" (AAPL's
# stops in 2018, MSFT's in 2011, both still 200 on companyconcept). 400
# days covers one full annual filing cycle plus buffer for a company
# whose most recent 10-K/10-Q is slightly behind today.
_RECENT_CUTOFF_DAYS = 400


def fetch_company_facts(ticker: str) -> dict:
    """Fetch a company's full companyfacts payload (every tag it has ever
    reported, across all taxonomies), cached to disk indefinitely -- same
    rationale as xbrl_facts.fetch_concept: SEC data for a past period
    doesn't change once filed, delete the cache file to force a refetch."""
    CACHE_DIR.mkdir(exist_ok=True)
    cache_path = CACHE_DIR / f"{ticker}_companyfacts.json"
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))

    companies = load_companies()
    cik = companies[ticker]["cik"]
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
    resp = requests.get(url, headers=HEADERS)
    time.sleep(REQUEST_DELAY_SECONDS)
    resp.raise_for_status()
    data = resp.json()
    cache_path.write_text(json.dumps(data), encoding="utf-8")
    return data


def _has_recent_entry(tag_data: dict) -> bool:
    cutoff = date.today() - timedelta(days=_RECENT_CUTOFF_DAYS)
    for entries in tag_data.get("units", {}).values():
        for entry in entries:
            if date.fromisoformat(entry["end"]) >= cutoff:
                return True
    return False


def list_tags(
    ticker: str,
    keyword: str | None = None,
    recent_only: bool = False,
    taxonomy: str = "us-gaap",
) -> list[str]:
    """List every tag `ticker` has reported under `taxonomy` (default
    us-gaap; SEC's other taxonomy is "dei", entity-level facts like share
    count rather than financials). Optionally filter to tag names
    containing `keyword` (case-insensitive substring) and/or to tags with
    at least one entry in roughly the last year (`recent_only`) -- a tag
    existing doesn't mean the company still reports it, the same
    staleness pitfall documented in xbrl_facts.DEFAULT_METRIC_TAGS."""
    data = fetch_company_facts(ticker)
    tags = data.get("facts", {}).get(taxonomy, {})
    names = list(tags.keys())
    if keyword:
        kw = keyword.lower()
        names = [n for n in names if kw in n.lower()]
    if recent_only:
        names = [n for n in names if _has_recent_entry(tags[n])]
    return sorted(names)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ticker")
    parser.add_argument("--keyword", type=str, default=None)
    parser.add_argument("--recent-only", action="store_true")
    parser.add_argument("--taxonomy", type=str, default="us-gaap")
    args = parser.parse_args()

    tags = list_tags(
        args.ticker,
        keyword=args.keyword,
        recent_only=args.recent_only,
        taxonomy=args.taxonomy,
    )
    print(f"{len(tags)} tag(s) for {args.ticker} ({args.taxonomy}):")
    for tag in tags:
        print(f"  {tag}")
