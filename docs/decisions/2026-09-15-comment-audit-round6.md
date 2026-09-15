# Comment audit Round 6: pointer-fixed 4 large unit-test files

**Date:** 2026-09-15

## Context

Round 5 pointer-fixed 5 small `tests/` files. `BACKLOG.md`'s Round 6
item bundled 15 more files across 3 themed sub-groups; this round
covers only the sub-group confirmed "mostly self-citing, routine
pointer-fix" material.

## Decision

Pointer-fixed `tests/test_llm_backends.py`, `tests/test_xbrl_facts.py`,
`tests/test_formulas.py`, `tests/test_eval_harness.py`. Every pointer
verified against its target decision file before applying. One small
gap found (`test_eval_harness.py`'s `answer_model`-tracking comment)
was handled with a light trim rather than a new decision file, per the
established "don't create a tiny dedicated file for a one-liner" rule.
Several blocks explaining load-bearing algorithmic reasoning (not just
incident history) were kept mostly intact, trimming only the
narrative wrapper.

## Why

See `docs/plans/2026-09-15-comment-audit-round6.md` for the full
per-file disposition list.

## Files touched

`tests/test_llm_backends.py`, `tests/test_xbrl_facts.py`,
`tests/test_formulas.py`, `tests/test_eval_harness.py`
(comments/docstrings only — zero executable code lines changed,
confirmed both by a full diff read and a programmatic tokenize-based
comparison). `BACKLOG.md` (marked sub-group (a) done, renumbered
sub-groups (b)/(c) as Round 6b/6c), `PROJECT_INDEX.md` (new index
lines).

## Verification

Programmatic check: stripped comments/docstrings from both `HEAD` and
working-tree versions of all 4 edited files via Python's `tokenize`
module, diffed the remainder — byte-identical, confirming no code
changed. Full pytest suite: 634 passed (matches baseline exactly).
Two-pass review: self-check plus a fresh subagent architecture review
— see `docs/reviews/2026-09-15-comment-audit-round6.md`.

## Related

`docs/plans/2026-09-15-comment-audit-round6.md`,
`docs/reviews/2026-09-15-comment-audit-round6.md`,
`docs/decisions/2026-09-15-comment-audit-round5.md` (the round this
follows up on). Follow-up work (Round 6b, 6c, and Rounds 7-10+) logged
in `BACKLOG.md`.
