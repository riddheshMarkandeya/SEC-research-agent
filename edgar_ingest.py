"""
SEC EDGAR filing ingestion. Fetches recent 10-K and 10-Q filings for a
set of companies, parses the filing HTML, and separates prose text from
tables (tables are kept separately so chunk_documents.py can convert
them to markdown instead of letting them get flattened/lost during
chunking). See docs/decisions/2026-08-13-edgar-ingestion.md.

Usage:
    pip install requests beautifulsoup4 lxml
    python edgar_ingest.py

Output:
    ./data/<TICKER>/<accession>_meta.json   -- filing metadata
    ./data/<TICKER>/<accession>_text.txt    -- prose text
    ./data/<TICKER>/<accession>_tables.json -- extracted tables (list of table dicts)

IMPORTANT: SEC requires a descriptive User-Agent header on every request,
or it will block you. Set SEC_USER_AGENT_NAME/SEC_USER_AGENT_EMAIL in
.env to your real name/email before running (see .env.example).
"""

import json
import re
import time
from pathlib import Path

import warnings

import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

from companies import load_companies
from config import SEC_USER_AGENT, SEC_USER_AGENT_EMAIL

# SEC filings are often iXBRL (XHTML with embedded XML tags for financial
# data). bs4 sometimes misdetects these as pure XML and warns about it —
# harmless here since we're deliberately using the HTML parser to get
# clean text/table extraction.
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

HEADERS = {"User-Agent": SEC_USER_AGENT}

FORM_TYPES = {"10-K", "10-Q"}
FILINGS_PER_COMPANY = 5  # last N matching filings (mix of 10-K/10-Q)

OUTPUT_DIR = Path("./data")
REQUEST_DELAY_SECONDS = 0.3  # be polite to SEC's servers — stay under 10 req/sec


# ---------------------------------------------------------------------------
# Step 1: Get the list of filings for a company
# ---------------------------------------------------------------------------
def get_filing_list(cik: str) -> list[dict]:
    """Fetch a company's filing history from the submissions API."""
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    resp = requests.get(url, headers=HEADERS)
    resp.raise_for_status()
    data = resp.json()

    recent = data["filings"]["recent"]
    filings = []
    for i in range(len(recent["form"])):
        if recent["form"][i] in FORM_TYPES:
            filings.append({
                "form": recent["form"][i],
                "accessionNumber": recent["accessionNumber"][i],
                "filingDate": recent["filingDate"][i],
                "primaryDocument": recent["primaryDocument"][i],
                "reportDate": recent["reportDate"][i],
            })
    return filings[:FILINGS_PER_COMPANY]


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


def fetch_filing_html(cik: str, accession: str, primary_doc: str) -> str:
    """Download the raw filing HTML."""
    resp = requests.get(_filing_document_url(cik, accession, primary_doc), headers=HEADERS)
    resp.raise_for_status()
    return resp.text


def get_filing_url(ticker: str, accession: str) -> str | None:
    """The real SEC EDGAR URL for an already-ingested filing, built for
    mcp_server.py's citation `source` blocks -- no new network
    call, since `cik` and `primaryDocument` are already sitting in this
    filing's own _meta.json (written by process_ticker() below, using
    the exact same `filing` dict get_filing_list() returned). Returns
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
def main():
    if "your.email@example.com" in SEC_USER_AGENT_EMAIL:
        print("⚠️  Set SEC_USER_AGENT_EMAIL in .env before running (see .env.example) — "
              "SEC will reject requests without a real-looking User-Agent.")
        return

    for ticker, info in load_companies().items():
        cik = info["cik"]
        print(f"\n=== {ticker} (CIK {cik}) ===")
        out_dir = OUTPUT_DIR / ticker
        out_dir.mkdir(parents=True, exist_ok=True)

        try:
            filings = get_filing_list(cik)
        # Broad and deliberate, matching the per-filing catch just below:
        # get_filing_list() can fail in more ways than one clean type
        # covers (requests.RequestException from the HTTP call itself,
        # ValueError/json.JSONDecodeError from a malformed body, KeyError/
        # TypeError if SEC's submissions schema doesn't match what's
        # expected) — all should degrade the same way here (skip this
        # company, keep going) rather than aborting every remaining one.
        except Exception as e:
            print(f"  ✗ Failed to fetch filing list for {ticker}: {e}")
            continue
        print(f"Found {len(filings)} filings: "
              f"{[f['form'] + ' ' + f['filingDate'] for f in filings]}")

        for filing in filings:
            accession = filing["accessionNumber"]
            print(f"  Fetching {filing['form']} filed {filing['filingDate']} "
                  f"({accession})...")

            try:
                html = fetch_filing_html(cik, accession, filing["primaryDocument"])
                text, tables = parse_filing(html)
            except Exception as e:
                print(f"    ✗ Failed: {e}")
                continue

            safe_accession = accession.replace("/", "-")
            meta = {**filing, "ticker": ticker, "cik": cik,
                    "num_tables": len(tables), "text_length": len(text)}

            # encoding="utf-8" is required explicitly — Windows defaults to
            # cp1252, which can't represent characters SEC filings sometimes
            # contain (e.g. checkbox glyphs like ☒, U+2612).
            (out_dir / f"{safe_accession}_meta.json").write_text(
                json.dumps(meta, indent=2), encoding="utf-8")
            (out_dir / f"{safe_accession}_text.txt").write_text(
                text, encoding="utf-8")
            (out_dir / f"{safe_accession}_tables.json").write_text(
                json.dumps(tables, indent=2), encoding="utf-8")

            print(f"    ✓ Saved: {len(text):,} chars text, {len(tables)} tables")

            time.sleep(REQUEST_DELAY_SECONDS)

    print(f"\nDone. Data saved under {OUTPUT_DIR.resolve()}")


if __name__ == "__main__":
    main()
