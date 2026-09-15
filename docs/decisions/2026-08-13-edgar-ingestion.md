# SEC EDGAR filing ingestion (`edgar_ingest.py`, Week 1)

**Date:** 2026-08-13 (commit `c92eb3b`, "Initial commit: SEC filing
ingestion, chunking, and Chroma indexing pipeline")

## Context

First working component: pull real 10-K/10-Q filings for the 5 covered
companies and split each into prose + tables in a form later stages can
consume.

## Decision

`edgar_ingest.py` fetches each company's filing list from
`https://data.sec.gov/submissions/CIK{cik}.json`, downloads the primary
document from SEC's Archives URL, parses the HTML, extracts each
`<table>` separately, and replaces it in the text stream with a
`[TABLE_n]` marker so its position is preserved. Empty/layout-only tables
are dropped with no marker. Outputs, per filing, under `./data/<TICKER>/`:
`<accession>_meta.json`, `<accession>_text.txt` (prose with markers),
`<accession>_tables.json` (`[{"table_index", "rows"}]`).

## Why

The `[TABLE_n]` marker scheme exists specifically so a later stage
(`chunk_documents.py`) can re-splice each table back into the exact
prose position it came from — the prose that says "the following table
shows net sales by segment" needs to end up in the same chunk as the
actual numbers, or retrieval on a question about that content misses the
figures entirely.

## Files touched

`edgar_ingest.py` (new).

## Verification

Manual runs across all 5 companies, 25 filings.

## Gotchas found and fixed

- SEC blocks requests without a descriptive `User-Agent` (`Name
  email@example.com` format) — the #1 day-one blocker.
- Windows defaults to cp1252 and crashes on SEC checkbox glyphs (☒/☐,
  U+2612). All file writes must pass `encoding="utf-8"`.
- SEC iXBRL filings are XHTML; bs4 emits `XMLParsedAsHTMLWarning` —
  harmless, suppressed deliberately (the HTML parser gives cleaner
  text/table extraction).
- Rate limit: sleep ~0.3s between requests, stay under 10 req/sec.

## Related

`docs/decisions/2026-08-13-chunking-pipeline.md` (the next stage that
consumes this output).
