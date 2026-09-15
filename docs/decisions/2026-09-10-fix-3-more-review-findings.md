# Fixed 3 more findings from the full-codebase review (§11/§12/§13)

**Date:** 2026-09-10

## Context

Closes out the last items from
`docs/reviews/2026-09-06-full-codebase-review.md`. Full findings and the
round-2 addendum: `docs/reviews/2026-09-10-fix-3-more-review-findings.md`.

## Decision

`mcp_server.py` never called `tracing.flush()` on shutdown, since
`Server.streamable_http_app()` exposes no shutdown hook (§11) — fixed
with `try/finally` around `uvicorn.run()`. Two smaller `agent.py`
consistency gaps: the comparison-message formatter was missing a hint
its sibling already had, and `search_filings` never validated a provided
ticker the way the other two tools do (§12). `edgar_ingest.py`'s
`parse_filing()` had zero direct test coverage despite being genuinely
pure (§13) — 10 new tests, all passed immediately against the unchanged
function.

## Why

A round-2 layered review (8 background finder angles plus a fresh
architecture subagent) found four more real gaps, three of them
pre-existing bugs the new tests happened to expose rather than something
§11/§12/§13 introduced: `flush()` had no "never raise" contract, newly
consequential because §11's own fix now calls it from a `finally`
wrapping `uvicorn.run()`; `search_filings`' new ticker guard still
crashed on a non-hashable value because it ran after a different
crash-prone check; `parse_filing()` had a real pre-existing leading/
trailing-newline bug the new coverage didn't happen to combine with an
edge-of-document noise line; and three independent review angles flagged
the same `fiscal_year`-guard duplication, extracted into a shared
helper.

## Files touched

`mcp_server.py`, `agent.py`, `edgar_ingest.py`.

## Verification

Full suite 411/411, then 414/414 after round 2. A round-3 pass came back
clean, closing the loop.

## Related

`docs/reviews/2026-09-10-fix-3-more-review-findings.md`,
`docs/decisions/2026-09-06-full-codebase-review.md`.
