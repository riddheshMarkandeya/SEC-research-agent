# Comment audit Round 3: pointer-fixed xbrl_facts.py and numeric_utils.py

**Date:** 2026-09-15

## Context

Round 1 and Round 2 pointer-fixed 16 of 19 flagged main-source files.
The remaining 3 (`agent.py`, `xbrl_facts.py`, `numeric_utils.py`) were
bundled as one "Round 3" backlog item. Fresh inventories showed the
bundle was mis-sized: `agent.py` (2497 lines, ~45+ blocks) is far
denser than the other two combined, and its own Explore-agent inventory
hit a session usage limit partway through. Confirmed with the user:
this round covers only `xbrl_facts.py` and `numeric_utils.py`; `agent.py`
is deferred to its own Round 4.

## Decision

Pointer-fixed 14 blocks in `xbrl_facts.py` and 6 in `numeric_utils.py`,
same process as Rounds 1-2, every pointer verified by reading the
target decision file first. One new decision file written:
`docs/decisions/2026-09-15-xbrl-tag-selection-methodology.md`,
synthesizing a genuinely undocumented XBRL metric-tag-selection
investigation that had lived only as a 44-line inline comment in
`xbrl_facts.py`. `numeric_utils.py`'s ~130-line `NUMBER_PATTERN` design
comment (the single highest-value trim target identified in the
original inventory) was collapsed to roughly 30 lines, keeping the
load-bearing "why is this regex shaped this way" facts and moving the
narration to the two decision files that already covered it.

## Why

See `docs/plans/2026-09-15-comment-audit-round3.md` for the full
per-block disposition table and the Round 4 (`agent.py`) notes
preserved for the next round.

## Files touched

`xbrl_facts.py`, `numeric_utils.py` (comments/docstrings only — zero
executable code lines changed, confirmed both by a full diff read and a
programmatic tokenize-based comparison).
`docs/decisions/2026-09-15-xbrl-tag-selection-methodology.md` (new).
`BACKLOG.md` (narrowed follow-up scope to a precisely-sized Round 4),
`PROJECT_INDEX.md` (new index lines).

## Verification

Programmatic check: stripped comments/docstrings from both `HEAD` and
working-tree versions of both files via Python's `tokenize` module,
diffed the remainder — byte-identical, confirming no code changed. Full
pytest suite: 634 passed (matches baseline exactly). Two-pass review:
self-check plus a fresh subagent architecture review — see
`docs/reviews/2026-09-15-comment-audit-round3.md`.

## Related

`docs/plans/2026-09-15-comment-audit-round3.md`,
`docs/reviews/2026-09-15-comment-audit-round3.md`,
`docs/decisions/2026-09-15-xbrl-tag-selection-methodology.md` (new,
extracted this round), `docs/decisions/2026-09-14-comment-audit-round2.md`
(the round this follows up on). Follow-up work (`agent.py` Round 4, the
full `tests/` pass) logged in `BACKLOG.md`.
