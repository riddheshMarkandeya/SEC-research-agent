# Fiscal-period embedding labels — tried, measured, reverted

**Date:** 2026-08-16 (commit `db37afc`, "Add fiscal-year verification
tooling; revert period-label retrieval fix")

## Context

Growing the eval set to 16 questions surfaced two retrieval-precision
bugs (`nvda-gross-margin-fy26`, `msft-rd-expense-q3fy26`): NVIDIA's 10-K
and each 10-Q contain near-identical MD&A boilerplate differing only in
the trailing number, so BM25/vector search can't tell which filing's
copy is relevant without a per-filing anchor; MSFT's "Highlights" section
describes a period differently than the table stating the actual number,
so the wrong section could win on lexical overlap.

## Decision

**Tried and reverted.** `period_labels.py` computed a canonical
natural-language period descriptor from a chunk's metadata plus
`fiscal_year_end_month`, prepended to the text embedded/tokenized at
indexing time (leaving stored/displayed text unprefixed). Reverted after
the full eval suite showed a net regression (14/16 → 13/16): neither
original target flipped to PASS, and a previously-passing question
(`pltr-revenue-2025`) newly failed.

## Why

A cheap simulation (a throwaway BM25 index + small embedding batches
over just the affected chunks) had shown real rank improvement for both
target chunks in isolation — but only ever checked whether the *target*
chunk's own rank improved, never whether an unrelated chunk in the same
filing could be boosted even more by the same shared prefix. The full
rebuild exposed exactly that: prepending the same short prefix to every
chunk in a filing is not a uniform, rank-preserving boost — embedding
models don't combine a prefix and existing content additively. For the
PLTR regression, a generic boilerplate chunk (no revenue content) jumped
from vector rank 30 to rank 8 purely from the shared per-filing prefix,
while the genuinely correct chunks only modestly improved. Confirmed
this wasn't a verbosity artifact — even a much shorter tag reproduced
the same regression.

`period_labels.py`'s underlying period-math functions
(`fiscal_year_label()`, `fiscal_quarter()`) were kept — independently
correct and unit-tested, and still power `verify_period_labels.py`'s
fiscal-year-end safeguard. A reranking-stage-signal application was
considered as a future alternative but explicitly not revived once both
motivating bugs were fixed a different way (the structured XBRL tool).

`verify_period_labels.py` (built alongside this) cross-checks the
computed fiscal year/quarter for every ingested filing against the
filing's own self-description. Building it caught two real bugs in the
checker itself: a naive first-match search grabbed a filing's backward
reference to a prior period instead of its own current-period
declaration; a regex assumed no line break between a day number and its
comma, which real ingested text sometimes has. Result across all 25
filings: 14 confirmed, 0 mismatches, 11 inconclusive (no reliable
self-description pattern available, not evidence of a problem).
`verify_against_xbrl()` (Week 5e/f) added a second, independent check
against SEC's own XBRL data — found a real bug on its first live run
(pre-~2020 XBRL data mislabels some quarter-length entries as `10-K`)
before confirming 5/5 companies clean.

## Files touched

`period_labels.py` (new, kept), `tests/manual/verify_period_labels.py`
(new, kept), `index_chunks.py`/`retrieval.py` (augmentation tried then
reverted, comments left documenting what was tried and why).

## Verification

Full eval suite restored to 14/16 with no new regressions after revert.

## Related

`docs/decisions/2026-08-16-xbrl-structured-facts-tool.md` (the approach
that actually fixed both motivating bugs).
