"""
Week 1 — SEC EDGAR Filing Ingestion
------------------------------------
Fetches recent 10-K and 10-Q filings for a set of companies, parses the
filing HTML, and separates prose text from tables (tables are kept
separately so Week 2 can convert them to markdown instead of letting
them get flattened/lost during chunking).

Usage:
    pip install requests beautifulsoup4 lxml
    python edgar_ingest.py

Output:
    ./data/<TICKER>/<accession>_meta.json   -- filing metadata
    ./data/<TICKER>/<accession>_text.txt    -- prose text
    ./data/<TICKER>/<accession>_tables.json -- extracted tables (list of table dicts)

IMPORTANT: SEC requires a descriptive User-Agent header on every request,
or it will block you. Set EMAIL below to your real email before running.
"""

import json
import re
import time
from pathlib import Path

import warnings

import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

# SEC filings are often iXBRL (XHTML with embedded XML tags for financial
# data). bs4 sometimes misdetects these as pure XML and warns about it —
# harmless here since we're deliberately using the HTML parser to get
# clean text/table extraction.
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

# ---------------------------------------------------------------------------
# CONFIG — edit this before running
# ---------------------------------------------------------------------------
YOUR_NAME = "Rid"
YOUR_EMAIL = "riddhesh2307@gmail.com"  # <-- put a real email here, SEC checks format

HEADERS = {"User-Agent": f"{YOUR_NAME} {YOUR_EMAIL}"}

# 10-digit zero-padded CIKs for the 5 starter companies
COMPANIES = {
    "AAPL": "0000320193",
    "MSFT": "0000789019",
    "NVDA": "0001045810",
    "CRM":  "0001108524",
    "PLTR": "0001321655",
}

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
def fetch_filing_html(cik: str, accession: str, primary_doc: str) -> str:
    """Download the raw filing HTML."""
    accession_nodash = accession.replace("-", "")
    cik_nozero = str(int(cik))  # SEC archive paths use non-padded CIK
    url = f"https://www.sec.gov/Archives/edgar/data/{cik_nozero}/{accession_nodash}/{primary_doc}"
    resp = requests.get(url, headers=HEADERS)
    resp.raise_for_status()
    return resp.text


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
    # replaced with a [TABLE_n] marker left IN PLACE in the text, so Week 2
    # can splice the markdown version of the table back in at the exact
    # spot it came from (instead of text and tables living as two
    # disconnected documents with no positional link between them).
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
    # OPTIONAL: strip repeating page header/footer noise (e.g.
    # "Apple Inc. | Q3 2026 Form 10-Q | 13"). Left commented out for now —
    # it's cosmetic and doesn't hurt chunking/retrieval much, and writing
    # a per-company matcher isn't worth it yet. If it starts bothering you
    # later, this generic pattern (matches "<Anything> | <Anything> | <page#>"
    # on its own line) should catch most companies' variants without
    # hardcoding company names:
    #
    text = re.sub(
        r"^.{0,80}\|.{0,60}\|\s*\d{1,4}\s*$",
        "",
        text,
        flags=re.MULTILINE,
    )
    text = re.sub(r"\n{3,}", "\n\n", text)  # re-collapse blank lines after stripping
    # ------------------------------------------------------------------

    return text, tables


# ---------------------------------------------------------------------------
# Main ingestion loop
# ---------------------------------------------------------------------------
def main():
    if "your.email@example.com" in YOUR_EMAIL:
        print("⚠️  Set YOUR_EMAIL at the top of this script before running — "
              "SEC will reject requests without a real-looking User-Agent.")
        return

    for ticker, cik in COMPANIES.items():
        print(f"\n=== {ticker} (CIK {cik}) ===")
        out_dir = OUTPUT_DIR / ticker
        out_dir.mkdir(parents=True, exist_ok=True)

        filings = get_filing_list(cik)
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