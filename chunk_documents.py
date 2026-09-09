"""
Week 2 — Table-to-Markdown Conversion + Table-Aware Chunking
---------------------------------------------------------------
Takes the output of edgar_ingest.py (per-filing _text.txt with [TABLE_n]
markers, plus _tables.json) and:

  1. Cleans up each table's messy row data (SEC HTML splits currency
     symbols and padding into separate empty cells).
  2. Converts each table to a markdown table.
  3. Splices the markdown back into the text at its [TABLE_n] marker,
     so prose and the numbers it's describing live together again.
  4. Chunks the reconstructed document, treating each table as an
     atomic block that is NEVER split across chunk boundaries, and
     keeping each table bundled with its surrounding paragraph(s)
     wherever they fit within the chunk size budget.

Usage:
    python chunk_documents.py

Input:  ./data/<TICKER>/<accession>_text.txt
        ./data/<TICKER>/<accession>_tables.json
        ./data/<TICKER>/<accession>_meta.json
Output: ./chunks/<TICKER>/<accession>_chunks.jsonl
        (one JSON object per line: {text, metadata})
"""

import json
import re
from pathlib import Path

DATA_DIR = Path("./data")
CHUNKS_DIR = Path("./chunks")

# Chunk size is measured in characters as a simple proxy for tokens
# (~4 chars/token for English is a decent rule of thumb). Swap in
# tiktoken later for exact token counts if you want to tune this more
# precisely against your embedding model's limits.
TARGET_CHUNK_CHARS = 2000
MAX_CHUNK_CHARS = 3000       # hard ceiling before we force a split
OVERLAP_CHARS = 200          # trailing context carried into the next chunk

# SEC filings sometimes have hidden Inline XBRL taxonomy metadata (tag
# paths, raw dates, "us-gaap:...Member" strings) sitting outside any
# <table> tag, so Week 1's table-stripping doesn't catch it. This
# boilerplate phrase marks the start of the real, human-readable filing
# text across virtually all 10-K/10-Q filings, so we use it as a generic
# (non-company-specific) anchor to cut the junk before it.
DOCUMENT_START_ANCHOR = "SECURITIES AND EXCHANGE COMMISSION"


def strip_leading_metadata(text: str) -> str:
    """Cut everything before the standard SEC cover-page boilerplate."""
    idx = text.find(DOCUMENT_START_ANCHOR)
    if idx == -1:
        return text  # anchor not found — leave text untouched

    # Back up to the start of the "UNITED STATES" line just above the
    # anchor, if it's there, so we keep that line rather than starting
    # mid-header.
    preceding = text[:idx]
    # Need the newline TWO lines back (the one ending the line above
    # "UNITED STATES"). Guard both rfind()s explicitly rather than
    # chaining them directly: fewer than 2 newlines before the anchor
    # (e.g. "UNITED STATES" is the very first line, or shares no
    # newline with it at all) used to leave this at -1, and text[-1:]
    # doesn't mean "from the start" -- it silently truncated the whole
    # document to its last character (review §6, found live via a
    # future filing, not any of the 25 already ingested here).
    first_nl = preceding.rfind("\n")
    # No ternary on first_nl == -1 needed: when "\n" isn't in `preceding`
    # at all, it can't be found in any sub-range of it either, so the
    # inner rfind is already -1 in that case too (verified, not assumed).
    last_line_start = max(preceding.rfind("\n", 0, first_nl), 0)
    if "UNITED STATES" in preceding[-30:]:
        return text[last_line_start:].strip()
    return text[idx:].strip()


# ---------------------------------------------------------------------------
# Step 1: Clean + convert one table's rows into a markdown table
# ---------------------------------------------------------------------------
def clean_row(row: list[str]) -> list[str]:
    """
    Collapse SEC's messy cell structure: drop empty cells, then merge a
    lone '$' or '%' cell with the value next to it so numbers read
    naturally ("$" + "45,781" -> "$45,781").
    """
    non_empty = [c for c in row if c.strip() != ""]

    merged = []
    i = 0
    while i < len(non_empty):
        cell = non_empty[i]
        if cell in ("$",) and i + 1 < len(non_empty):
            merged.append(f"${non_empty[i + 1]}")
            i += 2
        elif i + 1 < len(non_empty) and non_empty[i + 1] == "%":
            merged.append(f"{cell}%")
            i += 2
        else:
            merged.append(cell)
            i += 1
    return merged


def table_to_markdown(table: dict) -> str:
    """Convert a {"table_index": n, "rows": [[...], ...]} dict to markdown."""
    rows = [clean_row(r) for r in table["rows"]]
    rows = [r for r in rows if r]  # drop any rows that cleaned to nothing

    if not rows:
        return ""

    n_cols = max(len(r) for r in rows)
    # Pad every row to the same width so the markdown table renders correctly
    padded = [r + [""] * (n_cols - len(r)) for r in rows]

    header, *body = padded
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(["---"] * n_cols) + " |",
    ]
    for row in body:
        lines.append("| " + " | ".join(row) + " |")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Step 2: Splice markdown tables back into the text at their markers
# ---------------------------------------------------------------------------
def reconstruct_document(text: str, tables: list[dict]) -> str:
    """Replace every [TABLE_n] marker with that table's markdown form."""
    text = strip_leading_metadata(text)
    table_lookup = {t["table_index"]: t for t in tables}

    def replace_marker(match: re.Match) -> str:
        idx = int(match.group(1))
        table = table_lookup.get(idx)
        if table is None:
            return ""  # marker with no matching table data — drop silently
        md = table_to_markdown(table)
        if not md:
            return ""
        # Wrap in explicit tags so the chunker can identify table blocks
        # and treat them as atomic/unsplittable.
        return f"\n<TABLE>\n{md}\n</TABLE>\n"

    return re.sub(r"\[TABLE_(\d+)\]", replace_marker, text)


# ---------------------------------------------------------------------------
# Step 3: Chunk the reconstructed document
# ---------------------------------------------------------------------------
def split_by_sentences(text: str, max_chars: int) -> list[str]:
    """Last-resort split: sentence boundaries, then hard character slicing
    if a single 'sentence' is still too long (e.g. a run-on legal clause)."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    if len(sentences) == 1:
        # No sentence boundaries found at all — hard slice as a final fallback.
        return [text[i:i + max_chars] for i in range(0, len(text), max_chars)]

    result = []
    for s in sentences:
        if len(s) > max_chars:
            result.extend(s[i:i + max_chars] for i in range(0, len(s), max_chars))
        else:
            result.append(s)
    return result


def split_prose_block(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """
    Cascading fallback for a prose block that has no blank-line paragraph
    breaks (common in some filings' Business/Risk Factors sections, which
    can otherwise pass through as one 40,000+ character block). Tries
    single-newline splits first, then sentence boundaries, then hard
    slicing — each step only engaged if the previous one still leaves
    something oversized.
    """
    if len(text) <= max_chars:
        return [text]

    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if len(lines) > 1:
        result = []
        for line in lines:
            if len(line) > max_chars:
                result.extend(split_by_sentences(line, max_chars))
            else:
                result.append(line)
        return result

    return split_by_sentences(text, max_chars)


def is_exhibit_index_table(table_markdown: str) -> bool:
    """
    Detects the boilerplate 'Exhibit Index' tables that appear near the end
    of nearly every 10-K/10-Q (columns like 'Exhibit Number', 'Filing Date',
    'Incorporated by Reference'). These are pure filing-administration
    metadata — historical 8-K/10-Q cross-references for legal documents —
    with no financial or business content, and their column structure is
    consistent enough across filers to detect generically rather than
    filtering by section header (which would risk dropping adjacent,
    genuinely useful content like the financial statement index).
    """
    header_region = table_markdown[:400].lower()
    # Multi-row/colspan headers (e.g. "Exhibit" + "Number" spanning two
    # source cells) lose their separating space during Week 1's cell-text
    # extraction and collapse to "exhibitnumber". Match on a whitespace-
    # stripped copy too so both "Exhibit Number" and "ExhibitNumber" hit.
    header_region_nospace = re.sub(r"\s+", "", header_region)
    exhibit_signal = (
        "exhibit number" in header_region
        or "exhibit no" in header_region
        or "exhibitnumber" in header_region_nospace
        or "exhibitno" in header_region_nospace
    )
    reference_signal = (
        "incorporated by reference" in header_region
        or "filing date" in header_region
        or "incorporatedbyreference" in header_region_nospace
        or "filingdate" in header_region_nospace
    )
    return exhibit_signal and reference_signal


def split_into_blocks(document: str) -> list[str]:
    """
    Split the document into atomic blocks: either a whole <TABLE>...</TABLE>
    block, or a paragraph of prose. Tables are never broken up. Prose
    paragraphs larger than MAX_CHUNK_CHARS are run through split_prose_block
    so a section with no blank-line breaks (e.g. a dense Risk Factors
    section) can't pass through as one giant unsplit block. Exhibit-index
    boilerplate tables are dropped entirely (see is_exhibit_index_table).
    """
    blocks = []
    # Split on <TABLE>...</TABLE> while keeping the tables as their own blocks
    parts = re.split(r"(<TABLE>.*?</TABLE>)", document, flags=re.DOTALL)
    for part in parts:
        if part.startswith("<TABLE>"):
            if is_exhibit_index_table(part):
                continue  # drop boilerplate exhibit-index table
            blocks.append(part.strip())
        else:
            # Split remaining prose into paragraphs
            for para in re.split(r"\n\s*\n", part):
                para = para.strip()
                if not para:
                    continue
                if len(para) > MAX_CHUNK_CHARS:
                    blocks.extend(split_prose_block(para))
                else:
                    blocks.append(para)
    return blocks


def chunk_blocks(blocks: list[str]) -> list[str]:
    """
    Greedily accumulate blocks into chunks up to TARGET_CHUNK_CHARS.
    A table block is always kept whole, even if it alone exceeds the
    target (better an oversized-but-coherent chunk than a broken table).
    Adds a small trailing overlap of prose for context continuity.

    `current_is_only_overlap` tracks whether `current` is nothing but
    that untouched overlap carry-over (true right after the reset below,
    false the moment any block gets merged into it or it's replaced by a
    fresh block). This is checked -- not guessed from length -- before
    ever emitting `current`, mid-loop or at the final flush below: an
    overlap-only remnant is a raw character slice that duplicates
    content already in the previous chunk and can land mid-`<TABLE>`, so
    it's dropped rather than emitted as a malformed, mistagged chunk.
    Genuine content is always kept, no matter how short -- a length
    check alone can't tell the two cases apart once the loop has ended
    (e.g. a short final paragraph reached via the fresh-block branch
    below is real, never-before-emitted content, not overlap).
    """
    chunks = []
    current = ""
    current_is_only_overlap = False

    for block in blocks:
        candidate = f"{current}\n\n{block}".strip() if current else block

        if len(candidate) <= MAX_CHUNK_CHARS:
            current = candidate
            current_is_only_overlap = False
            if len(current) >= TARGET_CHUNK_CHARS:
                chunks.append(current)
                # carry a small tail forward for continuity
                current = current[-OVERLAP_CHARS:]
                current_is_only_overlap = True
        else:
            # Adding this block would overflow — close out current chunk,
            # unless it's nothing but the untouched overlap tail (see
            # docstring above).
            if current and not current_is_only_overlap:
                chunks.append(current)
            # Start fresh with this block (even if it alone is oversized —
            # tables must stay atomic, so we accept the occasional big chunk)
            current = block
            current_is_only_overlap = False

    if current and not current_is_only_overlap:
        chunks.append(current)

    return chunks


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def process_filing(text_path: Path):
    accession_stem = text_path.stem.replace("_text", "")
    ticker_dir = text_path.parent
    ticker = ticker_dir.name

    meta_path = ticker_dir / f"{accession_stem}_meta.json"
    tables_path = ticker_dir / f"{accession_stem}_tables.json"

    if not meta_path.exists() or not tables_path.exists():
        print(f"  Skipping {accession_stem} — missing meta or tables file")
        return

    text = text_path.read_text(encoding="utf-8")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    tables = json.loads(tables_path.read_text(encoding="utf-8"))

    document = reconstruct_document(text, tables)
    blocks = split_into_blocks(document)
    chunks = chunk_blocks(blocks)

    out_dir = CHUNKS_DIR / ticker
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{accession_stem}_chunks.jsonl"

    with out_path.open("w", encoding="utf-8") as f:
        for i, chunk_text in enumerate(chunks):
            record = {
                "text": chunk_text,
                "metadata": {
                    "ticker": ticker,
                    "form": meta["form"],
                    "filingDate": meta["filingDate"],
                    "reportDate": meta["reportDate"],
                    "accessionNumber": meta["accessionNumber"],
                    "chunk_index": i,
                    "contains_table": "<TABLE>" in chunk_text,
                    "char_length": len(chunk_text),
                },
            }
            f.write(json.dumps(record) + "\n")

    print(f"  {accession_stem}: {len(chunks)} chunks "
          f"({sum('<TABLE>' in c for c in chunks)} contain tables)")


def main():
    if not DATA_DIR.exists():
        print(f"No data found at {DATA_DIR.resolve()} — run edgar_ingest.py first.")
        return

    for ticker_dir in sorted(DATA_DIR.iterdir()):
        if not ticker_dir.is_dir():
            continue
        print(f"\n=== {ticker_dir.name} ===")
        for text_path in sorted(ticker_dir.glob("*_text.txt")):
            process_filing(text_path)

    print(f"\nDone. Chunks saved under {CHUNKS_DIR.resolve()}")


if __name__ == "__main__":
    main()