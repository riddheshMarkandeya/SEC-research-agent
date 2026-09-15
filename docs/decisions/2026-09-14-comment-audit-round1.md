# Comment audit Round 1: pointer-fixed 6 low-risk main-source files

**Date:** 2026-09-14

## Context

The documentation-system overhaul logged a follow-up for a codebase
comment audit — many source files had multi-line decision-history
narration in comments/docstrings duplicating content now homed in
`docs/decisions/`. A full inventory (two Explore passes) found the
problem systemic across 19 main-source files and 25 test files
(`test_agent.py` alone ~101 flagged blocks). The user asked for a
smaller batch first to keep quality high.

## Decision

Round 1 covered 6 small, low-risk files — `companies.py`, `config.py`,
`formulas.py`, `mcp_server.py`, `period_labels.py`, `tracing.py` — all
found mostly `ALREADY-DOCUMENTED` during inventory. For each flagged
block: confirmed the mapping to an existing `docs/decisions/*.md` file
by reading it directly (not trusting the inventory's guess), then
replaced the narration with a terse one-line pointer, or repointed a
comment still citing the deleted `PROJECT_CONTEXT.md`. `period_labels.py`'s
module docstring also got a factual correction, not just a trim — it
described a retrieval-indexing use of the period-label string that was
actually tried and reverted (confirmed via `index_chunks.py`'s own
comment and `docs/decisions/2026-08-16-fiscal-period-labels-tried-and-reverted.md`).
No genuinely new decision-history content was found needing a fresh
decision file — the inventory's prediction that this batch would be
low-risk held.

## Why

See `docs/plans/2026-09-14-comment-audit-round1.md` for the full file
selection reasoning and per-block disposition checklist.

## Files touched

`companies.py`, `config.py`, `formulas.py`, `mcp_server.py`,
`period_labels.py`, `tracing.py` (comments/docstrings only — zero
executable code lines changed, confirmed via full diff read).
`BACKLOG.md` (corrected scope, added two properly-scoped follow-ups),
`PROJECT_INDEX.md` (new index lines).

## Verification

Full diff read confirmed comment/docstring-only changes across all 6
files. Full pytest suite: 634 passed (same as baseline). Two-pass
review: self-check plus a fresh subagent architecture review — see
`docs/reviews/2026-09-14-comment-audit-round1.md`.

## Related

`docs/plans/2026-09-14-comment-audit-round1.md`,
`docs/reviews/2026-09-14-comment-audit-round1.md`,
`docs/decisions/2026-09-14-documentation-system-overhaul.md` (the
overhaul this follows up on). Follow-up work (13 remaining main-source
files, full `tests/` pass) logged in `BACKLOG.md`.
