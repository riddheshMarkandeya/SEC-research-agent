"""
Central ticker/company registry — single source of truth for the
ticker <-> company lookup that used to be duplicated, under the same
variable name (COMPANIES) but with different shapes, in both
edgar_ingest.py (ticker -> CIK, for fetching filings) and agent.py
(ticker -> company name, for the LLM's system prompt). Both now read
from companies.json instead of keeping their own copy, so adding or
renaming a company is a one-file edit instead of a hunt across scripts.

To add a company: add a row to companies.json (CIK can be found via
SEC's company search at https://www.sec.gov/cgi-bin/browse-edgar), then
re-run edgar_ingest.py -> chunk_documents.py -> index_chunks.py for it.
"""

import json
from pathlib import Path

COMPANIES_PATH = Path(__file__).parent / "companies.json"


def load_companies() -> dict[str, dict[str, str]]:
    """Returns {ticker: {"name": ..., "cik": ...}}, read fresh from disk
    every call — this is a small, rarely-changing file, so there's no
    real cost to not caching it, and not caching means edits to
    companies.json take effect without restarting anything."""
    return json.loads(COMPANIES_PATH.read_text(encoding="utf-8"))
