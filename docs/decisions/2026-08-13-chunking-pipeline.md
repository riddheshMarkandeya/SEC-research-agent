# Filing reconstruction and chunking (`chunk_documents.py`, Week 2a)

**Date:** 2026-08-13 (commit `c92eb3b`, initial commit; the exhibit-index
table-matching fix described below landed in the same early period,
before the codebase had per-change commits granular enough to date it
separately)

## Context

Week 1's ingestion output needed reassembling into full documents (table
markers spliced back into place) and splitting into retrieval-sized
chunks.

## Decision

`strip_leading_metadata()` cuts hidden Inline XBRL taxonomy junk sitting
outside any `<table>` tag, anchored on the boilerplate phrase "SECURITIES
AND EXCHANGE COMMISSION" (present in virtually every 10-K/10-Q, chosen
over per-company hardcoding). `clean_row()` merges SEC's split
currency/padding cells. `table_to_markdown()` converts each table to
markdown. `reconstruct_document()` re-splices each `[TABLE_n]` marker
with its markdown table, wrapped in `<TABLE>...</TABLE>` so the chunker
treats it as atomic. `is_exhibit_index_table()` drops boilerplate
exhibit-index tables at the table level (not by dropping Item 15
wholesale, preserving the financial-statement index and auditor's
report). `split_into_blocks()`/`split_prose_block()` split into atomic
blocks — tables never broken, oversized prose falls through a cascade
(blank-line paragraphs → single newlines → sentence boundaries → hard
slice). `chunk_blocks()` greedily accumulates to ~2000 chars (3000 hard
cap, ~200-char overlap), dropping leftover overlap-only fragments.

## Why

Filings are not structurally uniform: AAPL/MSFT/PLTR have blank-line
paragraph breaks, but NVDA's Business and Risk Factors sections did not,
so the whole section came through as one 47,000-121,000 char block
without the cascading fallback splitter.

Multi-row table headers get mangled (SEC uses merged/colspan cells for
headers like "Three Months Ended" spanning columns) — Week 1's cell-text
extraction doesn't preserve colspan, so "first row = header" flattens
them. Accepted as a known limitation: row data and numbers stay accurate,
which is what matters for retrieval.

## Files touched

`chunk_documents.py` (new).

## Verification

Manual runs across the corpus; `is_exhibit_index_table()`'s original
header match (`"exhibit number"`) missed 15 of 25 filings' exhibit
tables due to colspan collapsing `"Exhibit"` + `"Number"` into
`"ExhibitNumber"` — fixed by also matching a whitespace-stripped copy of
the header region.

## Related

`docs/decisions/2026-08-13-edgar-ingestion.md` (upstream),
`docs/decisions/2026-08-13-embedding-indexing-and-query-cli.md`
(downstream consumer). Later hardening:
`docs/decisions/2026-09-08-fix-3-medium-review-findings.md` (final-flush
tail bug), `docs/decisions/2026-09-09-fix-3-more-review-findings.md`
(`strip_leading_metadata()` truncation bug).
