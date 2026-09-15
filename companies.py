"""
Central ticker/company registry: single source of truth for the
ticker <-> company lookup used by edgar_ingest.py and agent.py. See
docs/decisions/2026-08-14-ticker-company-registry.md.

To add a company: add a row to companies.json (CIK can be found via
SEC's company search at https://www.sec.gov/cgi-bin/browse-edgar), then
re-run edgar_ingest.py -> chunk_documents.py -> index_chunks.py for it.
"""

import json
from pathlib import Path

import jsonschema

COMPANIES_PATH = Path(__file__).parent / "companies.json"

# Downstream readers (agent.py, xbrl_facts.py, period_labels.py,
# edgar_ingest.py) do raw info["name"]/info["cik"]/info["fiscal_year_end_month"]
# indexing with no check of their own -- validating here catches a
# malformed entry at load time instead of a confusing KeyError deep in
# an unrelated lookup later. See
# docs/decisions/2026-09-09-schema-driven-arg-validation.md.
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
