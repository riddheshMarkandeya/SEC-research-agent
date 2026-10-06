"""
SEC EDGAR filing ingestion. Fetches every 10-K and 10-Q filing from
fiscal year MIN_FISCAL_YEAR on for a set of companies (skipping those
already on disk), parses the filing HTML, and separates prose text from
tables (tables are kept separately so chunk_documents.py can convert
them to markdown instead of letting them get flattened/lost during
chunking). See docs/decisions/2026-08-13-edgar-ingestion.md.

Usage:
    pip install requests beautifulsoup4 lxml
    python -m sec_agent.sources.edgar_ingest

Output:
    var/data/<TICKER>/<accession>_meta.json   -- filing metadata
    var/data/<TICKER>/<accession>_text.txt    -- prose text
    var/data/<TICKER>/<accession>_tables.json -- extracted tables (list of table dicts)

IMPORTANT: SEC requires a descriptive User-Agent header on every request,
or it will block you. Set SEC_USER_AGENT_NAME/SEC_USER_AGENT_EMAIL in
.env to your real name/email before running (see .env.example).
"""

import json
import re
import time
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import NamedTuple

import warnings

import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

from sec_agent.sources.companies import CompanyInfo, load_companies
from sec_agent.sources.period_labels import fiscal_year_label
from sec_agent.config import DATA_DIR, SEC_USER_AGENT, SEC_USER_AGENT_EMAIL
from sec_agent.tracing import log_event

# SEC filings are often iXBRL (XHTML with embedded XML tags for financial
# data). bs4 sometimes misdetects these as pure XML and warns about it —
# harmless here since we're deliberately using the HTML parser to get
# clean text/table extraction.
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

HEADERS = {"User-Agent": SEC_USER_AGENT}

FORM_TYPES = {"10-K", "10-Q"}
# A fixed fiscal year, not "the last N filings", so the oldest filing kept
# doesn't move as new ones appear (the corpus still grows forward with each
# new filing). Labels follow period_labels.fiscal_year_label, so
# companies whose fiscal year runs ahead of the calendar (NVDA, CRM) reach
# further back in calendar time for the same cutoff.
MIN_FISCAL_YEAR = 2024

OUTPUT_DIR = DATA_DIR
REQUEST_DELAY_SECONDS = 0.3  # be polite to SEC's servers — stay under 10 req/sec
REQUEST_TIMEOUT_SECONDS = 30

# The submissions API sends many more columns; these are the ones kept.
_SUBMISSION_COLUMNS = ("form", "accessionNumber", "filingDate", "primaryDocument", "reportDate")
# These come from SEC's JSON and end up in a file name or a URL path, so
# anything outside SEC's own formats is refused rather than used. A primary
# document is one plain file name: no path separator, and never empty (an
# empty one would fetch the filing's directory listing instead).
_ACCESSION_PATTERN = re.compile(r"[0-9]{10}-[0-9]{2}-[0-9]{6}")
_PAGE_NAME_PATTERN = re.compile(r"CIK[0-9]{10}-submissions-[0-9]{3}\.json")
_DOCUMENT_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_DATE_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


# ---------------------------------------------------------------------------
# Step 1: Get the list of filings for a company
# ---------------------------------------------------------------------------
class PageSelection(NamedTuple):
    filings: list[dict]
    skipped_bad_row: int
    need_older: bool


class FilingSelection(NamedTuple):
    filings: list[dict]
    pages: int
    skipped_bad_row: int


def _rows(block: dict) -> list[dict]:
    """One submissions page (the `recent` block or an older `filings.files`
    page) arrives as parallel column arrays; this gives one dict per filing.
    Columns of unequal length raise ValueError rather than silently drop
    the trailing filings."""
    columns = [block[key] for key in _SUBMISSION_COLUMNS]
    return [dict(zip(_SUBMISSION_COLUMNS, values)) for values in zip(*columns, strict=True)]


def _is_canonical_date(value: str) -> bool:
    """YYYY-MM-DD and a real calendar date. fromisoformat alone also takes
    forms like 20240630, which sort wrongly as strings: the oldest-row
    choice compares filingDate strings, and retrieval matches and sorts
    reportDate strings from the chunk metadata."""
    if not _DATE_PATTERN.fullmatch(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _ingestable_fiscal_year(row: dict, fiscal_year_end_month: int) -> int | None:
    """The row's fiscal year, or None (logged) for a row that can't be
    ingested: a kept field that isn't a string (a null, say), an accession
    number or primary document outside SEC's format, or a filingDate or
    reportDate that isn't a canonical date."""
    if not all(isinstance(row[key], str) for key in _SUBMISSION_COLUMNS):
        reason = "non_string_field"
    elif not _ACCESSION_PATTERN.fullmatch(row["accessionNumber"]):
        reason = "bad_accession"
    elif not _DOCUMENT_PATTERN.fullmatch(row["primaryDocument"]):
        reason = "bad_primary_document"
    elif not _is_canonical_date(row["filingDate"]):
        reason = "bad_filing_date"
    elif not _is_canonical_date(row["reportDate"]):
        reason = "bad_report_date"
    else:
        return fiscal_year_label(fiscal_year_end_month, date.fromisoformat(row["reportDate"]))
    log_event("ingest_row_skipped", reason=reason, accession=row["accessionNumber"], form=row["form"],
              report_date=row["reportDate"], filing_date=row["filingDate"],
              primary_document=row["primaryDocument"])
    return None


def select_filings(rows: list[dict], fiscal_year_end_month: int, min_fiscal_year: int) -> PageSelection:
    """Keeps the 10-K/10-Q rows whose reportDate falls in fiscal year
    min_fiscal_year or later. need_older says an older page could still
    hold filings inside the cutoff: the oldest-filed 10-K/10-Q row here is
    still inside it, or the page has no usable 10-K/10-Q row at all."""
    kept: list[tuple[dict, int]] = []
    skipped_bad_row = 0
    for row in rows:
        if row["form"] not in FORM_TYPES:
            continue
        fiscal_year = _ingestable_fiscal_year(row, fiscal_year_end_month)
        if fiscal_year is None:
            skipped_bad_row += 1
            continue
        kept.append((row, fiscal_year))

    if not kept:
        return PageSelection([], skipped_bad_row, need_older=True)
    _, oldest_filed_fiscal_year = min(kept, key=lambda pair: pair[0]["filingDate"])
    filings = [row for row, fiscal_year in kept if fiscal_year >= min_fiscal_year]
    return PageSelection(filings, skipped_bad_row, need_older=oldest_filed_fiscal_year >= min_fiscal_year)


def collect_filings(
    recent: dict,
    older_files: list[dict],
    fetch_page: Callable[[str], dict],
    fiscal_year_end_month: int,
    min_fiscal_year: int,
) -> FilingSelection:
    """Selects from the `recent` block, then reads older pages, newest
    first, only while select_filings says the cutoff isn't reached yet.
    fetch_page(name) returns one older page's column block."""
    page = select_filings(_rows(recent), fiscal_year_end_month, min_fiscal_year)
    filings, skipped_bad_row, pages = list(page.filings), page.skipped_bad_row, 1
    for older in sorted(older_files, key=lambda f: f["filingTo"], reverse=True):
        if not page.need_older:
            break
        page = select_filings(_rows(fetch_page(older["name"])), fiscal_year_end_month, min_fiscal_year)
        filings.extend(page.filings)
        skipped_bad_row += page.skipped_bad_row
        pages += 1
    return FilingSelection(filings, pages, skipped_bad_row)


def _get_json(url: str) -> dict:  # pragma: no cover -- live SEC call, always monkeypatched in tests
    resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT_SECONDS)
    resp.raise_for_status()
    return resp.json()


def _page_url(name: str) -> str:
    """The URL of one older submissions page. The name comes from SEC's
    JSON, so one outside SEC's format raises ValueError rather than reach
    an unintended path."""
    if not _PAGE_NAME_PATTERN.fullmatch(name):
        raise ValueError(f"unexpected submissions page name: {name!r}")
    return f"https://data.sec.gov/submissions/{name}"


def _fetch_older_page(name: str) -> dict:  # pragma: no cover -- live SEC call, always monkeypatched in tests
    time.sleep(REQUEST_DELAY_SECONDS)
    return _get_json(_page_url(name))


def get_filing_list(  # pragma: no cover -- live SEC call, always monkeypatched in tests
    cik: str, fiscal_year_end_month: int
) -> FilingSelection:
    """Every 10-K/10-Q from MIN_FISCAL_YEAR on, from the submissions API,
    paging into `filings.files` when `recent` doesn't reach back that far."""
    data = _get_json(f"https://data.sec.gov/submissions/CIK{cik}.json")
    return collect_filings(
        data["filings"]["recent"], data["filings"].get("files", []), _fetch_older_page,
        fiscal_year_end_month, MIN_FISCAL_YEAR,
    )


# ---------------------------------------------------------------------------
# Step 2: Fetch and parse a single filing document
# ---------------------------------------------------------------------------
def _filing_document_url(cik: str, accession: str, primary_doc: str) -> str:
    """The real, fetchable SEC EDGAR URL for one filing's primary
    document. Extracted out of fetch_filing_html() so get_filing_url()
    below builds the exact same URL from the same three inputs, rather
    than risking a second, independently-drifting copy of this formula."""
    accession_nodash = accession.replace("-", "")
    cik_nozero = str(int(cik))  # SEC archive paths use non-padded CIK
    return f"https://www.sec.gov/Archives/edgar/data/{cik_nozero}/{accession_nodash}/{primary_doc}"


def fetch_filing_html(  # pragma: no cover -- live SEC document fetch, always monkeypatched in tests
    cik: str, accession: str, primary_doc: str
) -> str:
    """Download the raw filing HTML."""
    resp = requests.get(
        _filing_document_url(cik, accession, primary_doc), headers=HEADERS, timeout=REQUEST_TIMEOUT_SECONDS
    )
    resp.raise_for_status()
    return resp.text


def get_filing_url(ticker: str, accession: str) -> str | None:
    """The real SEC EDGAR URL for an already-ingested filing, built for
    mcp_server.py's citation `source` blocks -- no new network
    call, since `cik` and `primaryDocument` are already sitting in this
    filing's own _meta.json (written by _ingest_ticker() below, from
    the exact `filing` dict get_filing_list() selected). Returns
    None if this (ticker, accession) was never ingested."""
    meta_path = OUTPUT_DIR / ticker / f"{accession}_meta.json"
    if not meta_path.exists():
        return None
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    return _filing_document_url(meta["cik"], accession, meta["primaryDocument"])


def parse_filing(html: str) -> tuple[str, list[dict]]:
    """
    Split a filing into prose text and tables.

    Returns:
        (clean_text, tables) where tables is a list of
        {"table_index": int, "rows": [[cell, cell, ...], ...]}
    """
    soup = BeautifulSoup(html, "lxml")

    # Pull out tables first so their content doesn't end up duplicated
    # or mangled in the prose text extraction. Each removed table is
    # replaced with a [TABLE_n] marker left IN PLACE in the text, so
    # chunk_documents.py can splice the markdown version of the table
    # back in at the exact spot it came from (instead of text and tables
    # living as two disconnected documents with no positional link
    # between them).
    tables = []
    for idx, table_tag in enumerate(soup.find_all("table")):
        rows = []
        for tr in table_tag.find_all("tr"):
            cells = [
                re.sub(r"\s+", " ", cell.get_text(strip=True))
                for cell in tr.find_all(["td", "th"])
            ]
            # Skip rows that are entirely empty (common in SEC HTML tables
            # used purely for layout/spacing)
            if any(cells):
                rows.append(cells)

        if rows:
            tables.append({"table_index": idx, "rows": rows})
            # Leave a marker in the text stream at this table's position.
            # Wrapped in newlines so it lands on its own line once we
            # extract text below.
            table_tag.replace_with(f"\n[TABLE_{idx}]\n")
        else:
            # Empty/layout-only table — just drop it, no marker needed.
            table_tag.decompose()

    # Now extract prose text from what's left (markers included)
    text = soup.get_text(separator="\n")
    text = re.sub(r"\n{3,}", "\n\n", text)  # collapse excess blank lines
    text = re.sub(r"[ \t]+", " ", text)
    text = text.strip()

    # ------------------------------------------------------------------
    # Strips repeating page header/footer noise (e.g. "Apple Inc. |
    # Q3 2026 Form 10-Q | 13") -- a generic pattern (matches "<Anything>
    # | <Anything> | <page#>" on its own line) that catches most
    # companies' variants without hardcoding company names.
    text = re.sub(
        r"^.{0,80}\|.{0,60}\|\s*\d{1,4}\s*$",
        "",
        text,
        flags=re.MULTILINE,
    )
    text = re.sub(r"\n{3,}", "\n\n", text)  # re-collapse blank lines after stripping
    # A noise line at the very start or end of the document leaves a
    # stray leading/trailing newline behind, since the earlier .strip()
    # above ran before this block existed to create one. See
    # docs/decisions/2026-09-10-fix-3-more-review-findings.md.
    text = text.strip()
    # ------------------------------------------------------------------

    return text, tables


# ---------------------------------------------------------------------------
# Main ingestion loop
# ---------------------------------------------------------------------------
_FILE_SUFFIXES = ("_tables.json", "_text.txt", "_meta.json")


def _already_ingested(out_dir: Path, accession: str) -> bool:
    """All three files present. A filing missing any of them is fetched
    again, since chunk_documents drops a filing without its text or tables."""
    return all((out_dir / f"{accession}{suffix}").exists() for suffix in _FILE_SUFFIXES)


def _save_filing(out_dir: Path, accession: str, meta: dict, text: str, tables: list[dict]) -> None:
    """Meta is written last, so a crash part-way leaves no meta file and
    the filing is fetched again on the next run rather than half-skipped."""
    # encoding="utf-8" is required explicitly — Windows defaults to
    # cp1252, which can't represent characters SEC filings sometimes
    # contain (e.g. checkbox glyphs like ☒, U+2612).
    (out_dir / f"{accession}_tables.json").write_text(json.dumps(tables, indent=2), encoding="utf-8")
    (out_dir / f"{accession}_text.txt").write_text(text, encoding="utf-8")
    (out_dir / f"{accession}_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


def _ingest_ticker(ticker: str, info: CompanyInfo, out_dir: Path) -> dict | None:
    """Fetches and saves one company's selected filings, skipping those
    already on disk so their files (and the chunk IDs built from them)
    stay byte-identical. Returns counts, or None when the filing list
    itself couldn't be fetched."""
    cik = info["cik"]
    # Every SEC request is preceded by the pause, this one included, so
    # one company's last fetch and the next company's list don't go out
    # back to back.
    time.sleep(REQUEST_DELAY_SECONDS)
    try:
        selection = get_filing_list(cik, info["fiscal_year_end_month"])
    # Broad and deliberate: the list fetch can fail as a requests error, a
    # malformed JSON body (ValueError) or an unexpected submissions schema
    # (KeyError/TypeError), and each means the same here: skip this
    # company and keep going with the rest.
    except Exception as e:
        print(f"  ✗ Failed to fetch filing list for {ticker}: {e}")
        log_event("ingest_filing_list_failed", ticker=ticker, error=f"{type(e).__name__}: {e}")
        return None

    out_dir.mkdir(parents=True, exist_ok=True)
    to_fetch = [f for f in selection.filings if not _already_ingested(out_dir, f["accessionNumber"])]
    counts = {"selected": len(selection.filings), "skipped_present": len(selection.filings) - len(to_fetch),
              "saved": 0, "failed": 0}
    print(f"Selected {counts['selected']} filings from {selection.pages} page(s), "
          f"{counts['skipped_present']} already present")
    log_event("ingest_filing_list", ticker=ticker, pages=selection.pages, selected=counts["selected"],
              skipped_present=counts["skipped_present"], skipped_bad_row=selection.skipped_bad_row)

    for filing in to_fetch:
        # Before every fetch, failed ones included: a run of failures (an
        # SEC rate-limit response, say) must not turn into a request burst.
        time.sleep(REQUEST_DELAY_SECONDS)
        accession = filing["accessionNumber"]
        print(f"  Fetching {filing['form']} period {filing['reportDate']} "
              f"filed {filing['filingDate']} ({accession})...")
        # Broad and deliberate: one filing's fetch or parse failure (HTTP
        # error, timeout, malformed HTML) must not stop the company's rest.
        try:
            html = fetch_filing_html(cik, accession, filing["primaryDocument"])
            text, tables = parse_filing(html)
        except Exception as e:
            print(f"    ✗ Failed: {e}")
            log_event("ingest_filing_failed", ticker=ticker, accession=accession, error=f"{type(e).__name__}: {e}")
            counts["failed"] += 1
            continue

        meta = {**filing, "ticker": ticker, "cik": cik, "num_tables": len(tables), "text_length": len(text)}
        _save_filing(out_dir, accession, meta, text, tables)
        counts["saved"] += 1
        print(f"    ✓ Saved: {len(text):,} chars text, {len(tables)} tables")
    return counts


def main():  # pragma: no cover -- live SEC ingestion orchestration loop
    if "your.email@example.com" in SEC_USER_AGENT_EMAIL:
        print("⚠️  Set SEC_USER_AGENT_EMAIL in .env before running (see .env.example) — "
              "SEC will reject requests without a real-looking User-Agent.")
        return

    started = time.monotonic()
    totals = {"selected": 0, "skipped_present": 0, "saved": 0, "failed": 0, "companies_failed": 0}
    for ticker, info in load_companies().items():
        print(f"\n=== {ticker} (CIK {info['cik']}) ===")
        counts = _ingest_ticker(ticker, info, OUTPUT_DIR / ticker)
        if counts is None:
            totals["companies_failed"] += 1
            continue
        for key, value in counts.items():
            totals[key] += value

    elapsed_s = round(time.monotonic() - started, 1)
    log_event("ingest_done", min_fiscal_year=MIN_FISCAL_YEAR, elapsed_s=elapsed_s, **totals)
    print(f"\nDone in {elapsed_s}s: {totals}. Data saved under {OUTPUT_DIR.resolve()}")


if __name__ == "__main__":
    main()
