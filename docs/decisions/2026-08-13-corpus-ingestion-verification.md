# Corpus ingestion/chunking/embedding verification, and initial retrieval gaps

**Date:** 2026-08-13 (commit `c92eb3b`, initial commit)

## Context

After ingestion, chunking, and embedding were all wired up, a manual
sanity check confirmed the pipeline end-to-end before building anything
further on top of it.

## Decision

Confirmed: `grep -r "us-gaap:" ./chunks/` returns nothing; no
exhibit-index table leakage (down from 15 leaked filings to 0); only 4
chunks exceed the 3,000-char soft target (all large `<TABLE>` blocks kept
atomic by design); embedding + Chroma indexing runs end-to-end
(3,207/3,207 documents loaded across 25 filings, 5 companies).

## Why

A 15-query manual retrieval sanity check found the pipeline mostly
strong, with two known gaps flagged for follow-up: **Gap 1** — "Salesforce's
remaining performance obligation" retrieved no CRM chunk in the top 3
(MSFT/NVDA prose instead), despite CRM disclosing RPO prominently —
resolved by adding hybrid (BM25+vector) search, see
`docs/decisions/2026-08-13-hybrid-retrieval-and-reranker-fix.md`.
**Gap 2** — "How many full-time employees does the company have?" scored
noticeably lower and top-3 results weren't about headcount — this turned
out to be a company-disambiguation problem, not a retrieval quality
problem, and was resolved by giving the agent a `search_filings` tool
that resolves the ticker itself, see
`docs/decisions/2026-08-14-agent-v0-tool-calling.md`.

## Files touched

None (a verification checkpoint, not a code change).

## Verification

As described above — this section is itself the verification record.

## Related

`docs/decisions/2026-08-13-hybrid-retrieval-and-reranker-fix.md` (Gap 1),
`docs/decisions/2026-08-14-agent-v0-tool-calling.md` (Gap 2).
