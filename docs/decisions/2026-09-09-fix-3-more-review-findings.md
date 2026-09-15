# Fixed 3 more findings from the full-codebase review (§6/§8/§10)

**Date:** 2026-09-09

## Context

Continues resolving `docs/reviews/2026-09-06-full-codebase-review.md`.
Full findings and the round-2 addendum:
`docs/reviews/2026-09-09-fix-3-more-review-findings.md`.

## Decision

`chunk_documents.py`'s `strip_leading_metadata()` could truncate a
document to 1 character if fewer than 2 newlines preceded its anchor
(§6); a non-int `fiscal_year` silently misrecorded as
`"no_data_for_ticker"` telemetry instead of a schema-violation signal
(§8); `tracing.py`'s `traced_span()` never recorded exception info,
undercutting the "always-on debugging backup" it exists for (§10).

## Why

See the review doc for the traced repro of §6's truncation bug. A round-2
layered review found two real gaps in §8/§10's own fixes: the new
`fiscal_year` guard was placed before the multi-year-average branch even
checks whether it applies, wrongly rejecting a stray `fiscal_year`
alongside a valid start/end pair that the code would otherwise have
correctly ignored; and the manual Langfuse `span.update(level="ERROR")`
call added for §10 turned out to be dead code, confirmed by reading the
installed OTel SDK source directly — `start_as_current_span()` already
auto-records exceptions before this function's own `except` clause ever
runs. Removed the dead call, kept the local JSONL `error` field (the
actual gap §10 named).

## Files touched

`chunk_documents.py`, `agent.py`, `tracing.py`.

## Verification

Full suite 394/394, then 395/395 after round 2.

## Related

`docs/reviews/2026-09-09-fix-3-more-review-findings.md`,
`docs/decisions/2026-09-06-full-codebase-review.md`.
