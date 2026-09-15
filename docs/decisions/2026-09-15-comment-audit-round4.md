# Comment audit Round 4: pointer-fixed agent.py

**Date:** 2026-09-15

## Context

Rounds 1-3 pointer-fixed 18 of the 19 flagged main-source files.
`agent.py` (2497 lines, the largest and densest file in the codebase —
~45+ narrated blocks, denser than Round 2's entire 10-file batch
combined) was deferred to its own round.

## Decision

Pointer-fixed agent.py's comments/docstrings in four passes: dead
`PROJECT_CONTEXT.md` references (5 spots, repointed to real decision
files or, for the project's own standing design principle, to
`CLAUDE.md`), blocks citing `docs/plans/*.md` directly (repointed to
their paired `docs/decisions/*.md` files), remaining ALREADY-DOCUMENTED
blocks (confirmed each mapping before pointer-fixing), and a set of
judgment-call blocks needing careful KEEP-the-reasoning/TRIM-the-
narrative treatment (`_ground_operand`'s three-case error taxonomy,
`_SENTENCE_BREAK`'s regex-design comment, `validate_tool_args`'s
carve-out semantics, `_quote_grounded_in_source`'s table-authoritative
design choice, `_iter_uncited_claims`'s reachability contract) — all
kept in substance, only the incident-narration wrapper trimmed.

## Why

See `docs/plans/2026-09-15-comment-audit-round4.md` for the full
per-section disposition list.

## Files touched

`agent.py` (comments/docstrings only — zero executable code lines
changed, confirmed both by `ast.parse()` and a programmatic
tokenize-based comparison). `BACKLOG.md` (removed the completed Round 4
item), `PROJECT_INDEX.md` (new index lines).

## Verification

Programmatic check: stripped comments/docstrings from both `HEAD` and
working-tree versions of `agent.py` via Python's `tokenize` module,
diffed the remainder — byte-identical, confirming no code changed. Full
pytest suite: 634 passed (matches baseline exactly). Two-pass review:
self-check plus a fresh subagent architecture review, specifically
briefed to check for both over-trimming and under-trimming given this
round's judgment-call density — see
`docs/reviews/2026-09-15-comment-audit-round4.md`.

## Related

`docs/plans/2026-09-15-comment-audit-round4.md`,
`docs/reviews/2026-09-15-comment-audit-round4.md`,
`docs/decisions/2026-09-15-comment-audit-round3.md` (the round this
follows up on). This completes the original 19-file main-source
inventory from Round 1; the full `tests/` pass remains logged in
`BACKLOG.md`.
