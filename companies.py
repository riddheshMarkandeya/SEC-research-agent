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

import jsonschema

COMPANIES_PATH = Path(__file__).parent / "companies.json"

# Every downstream reader (agent.py, xbrl_facts.py, period_labels.py,
# edgar_ingest.py) does raw info["name"]/info["cik"]/info["fiscal_year_end_month"]
# indexing with no defensive check of its own -- a malformed entry used to
# surface as a confusing KeyError three layers down in some unrelated
# ticker/metric lookup, rather than one clear error at load time (found
# during the 2026-09-09 schema-validator redesign).
_COMPANIES_SCHEMA = {
    "type": "object",
    "additionalProperties": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "cik": {"type": "string"},
            "fiscal_year_end_month": {"type": "integer", "minimum": 1, "maximum": 12},
        },
        "required": ["name", "cik", "fiscal_year_end_month"],
        "additionalProperties": False,
    },
}


def _validate(data: dict) -> None:
    """Raises ValueError, naming companies.json and the specific
    violation, if data doesn't match _COMPANIES_SCHEMA -- one clear
    failure at load/import time (agent.py imports COMPANIES at module
    level) instead of a mystery KeyError deep in an unrelated lookup
    later. Catches the specific jsonschema.ValidationError type, not a
    broad `except Exception`, since that's the only exception this call
    can actually raise."""
    try:
        jsonschema.validate(data, _COMPANIES_SCHEMA)
    except jsonschema.ValidationError as e:
        raise ValueError(f"companies.json is malformed: {e.message}") from e


def load_companies() -> dict[str, dict[str, str]]:
    """Returns {ticker: {"name": ..., "cik": ...}}, read fresh from disk
    every call — this is a small, rarely-changing file, so there's no
    real cost to not caching it, and not caching means edits to
    companies.json take effect without restarting anything."""
    data = json.loads(COMPANIES_PATH.read_text(encoding="utf-8"))
    _validate(data)
    return data
