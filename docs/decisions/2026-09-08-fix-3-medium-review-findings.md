# Fixed 3 Medium-priority findings from the full-codebase review

**Date:** 2026-09-08

## Context

Continues resolving `docs/reviews/2026-09-06-full-codebase-review.md`
(§5, §7, §9). Full findings and the two review-round addenda:
`docs/reviews/2026-09-08-fix-3-medium-review-findings.md`.

## Decision

`chunk_documents.py`'s final chunk-flush had no tail filter, emitting a
stale overlap remnant as a malformed last chunk in some filings (§5);
`edgar_ingest.py`'s `get_filing_list(cik)` call was unguarded, so one
company's network failure aborted ingestion for every later company
(§7); `formulas.py`'s ratio computation had no zero-denominator guard
(§9).

## Why

See the review doc for full root-cause detail, including two rounds of
layered review both catching real gaps in the initial fixes: the
`edgar_ingest.py` exception tuple was narrower than the function's real
failure surface (widened to a broad, commented `except Exception`,
matching the sibling catch three lines below), and the
`current_is_only_overlap` mid-loop branch lacked the same test coverage
proving genuine short content survives that the final-flush branch got.

## Files touched

`chunk_documents.py`, `edgar_ingest.py`, `formulas.py`.

## Verification

Full suite 387/387, then 388/388 after the round-2 addendum. Re-indexed
and spot-checked end-to-end once the vector index was confirmed stale
(3206 chunks re-embedded, ticker counts unchanged); spot-checked the 4
eval questions targeting the one changed filing on both backends.

## Related

`docs/reviews/2026-09-08-fix-3-medium-review-findings.md`,
`docs/decisions/2026-09-06-full-codebase-review.md`.
