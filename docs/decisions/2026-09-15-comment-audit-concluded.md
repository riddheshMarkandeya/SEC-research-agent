# Comment-audit initiative concluded

**Date:** 2026-09-15

## Context

Rounds 1-6 of the comment audit (see Related below) worked through the
codebase's old-style comments/docstrings that re-narrated decision
history inline instead of pointing to the `docs/decisions/*.md` file
that already covers the same ground. By the end of Round 6: all 19
originally-flagged main-source files (`companies.py` through
`agent.py`) are done, plus 9 of 25 `tests/` files (5 small files in
Round 5; `test_llm_backends.py`, `test_xbrl_facts.py`,
`test_formulas.py`, `test_eval_harness.py` in Round 6). 16 test files
remained queued as Round 6b/6c and Rounds 7-10+ in `BACKLOG.md`,
including `test_agent.py` (3,713 lines, the single densest file found
during the whole audit).

## Decision

**Stop scheduling dedicated future rounds for the remaining 16 test
files.** Their comment cleanup is not abandoned — it's deferred to
opportunistic per-touch cleanup: whenever one of these files is next
touched for another reason (a bug fix, a new test, a refactor), bring
the narration in the *specific function or block being touched* up to
the same pointer-not-narration standard the finished files already
meet, per the new global `CLAUDE.md` incremental-improvement policy
(see Related). No further `BACKLOG.md` items track this file-by-file;
the general policy itself is the standing instruction now.

## Why

This revisits the original "do all of `tests/` eventually, just in
scoped batches" framing set at the start of Round 5 — not on a whim,
but on genuinely new information the six rounds themselves produced:
the real scope turned out to be far larger and more uneven than
expected (`test_agent.py` alone is larger than `agent.py`, the file
that itself needed a dedicated round), and the marginal value of a
polished test-file comment is lower than a polished main-source
comment (test comments are read far less often, as `BACKLOG.md` itself
already noted when de-prioritizing this work below the main-source
pass). Per the new global `CLAUDE.md` step 10 ("Revisiting prior
decisions"), that's a legitimate reason to revisit the original
scoping decision, named explicitly here rather than silently dropping
the remaining backlog items.

## Files touched

`BACKLOG.md` (removed the full comment-audit section — six rounds'
worth of pointer-only entries for completed work, plus the now-shelved
Round 6b/6c/7/8/9/10+ items), `PROJECT_INDEX.md` (this file's index
line).

## Verification

N/A — a documentation/backlog decision, no code changed.

## Related

`docs/decisions/2026-09-14-comment-audit-round1.md`,
`docs/decisions/2026-09-14-comment-audit-round2.md`,
`docs/decisions/2026-09-15-comment-audit-round3.md`,
`docs/decisions/2026-09-15-comment-audit-round4.md`,
`docs/decisions/2026-09-15-comment-audit-round5.md`,
`docs/decisions/2026-09-15-comment-audit-round6.md` (the six completed
rounds), `docs/decisions/2026-09-15-adopt-ruff-linter.md` (the
project-level instantiation of the incremental-improvement policy this
decision defers to).
