# Wire citation-verification into eval pass/fail, not just a warning

**Date:** 2026-08-18 (commit `3f364a9`, "Wire citation-verification into
eval harness pass/fail, not just a warning")

## Context

`verify_citations()` was informational only — a warning alongside
whatever `grade_numeric()`/`grade_comparison()` already decided, never
affecting the verdict. Those graders only check whether the expected
value appears *somewhere* in the answer text, unable to distinguish a
correctly-cited answer from one that states the right number attached to
the wrong (or no) source. Confirmed live before designing the fix:
`aapl-employees-fy25` "passes" today (166,000 appears), but the cited
chunk `[3]` is entirely about debt notes and share repurchases.

## Decision

`agent.py`'s `verify_citations()` internals refactored into a shared
`_iter_citation_claims()` generator; a new
`value_is_citation_verified(value, unit, answer_text, all_results)`
answers "is *this specific* expected value ever properly grounded,
anywhere it's cited?" — True if never cited at all (nothing to
contradict), or if *any* of its citations check out. `eval_harness.py`'s
`grade_numeric()`/`grade_comparison()` gained an optional `all_results`
parameter (default `None`, preserving old behavior for existing
tests/callers) — when given, a numeric match that fails verification
flips the verdict to FAIL with an explanation. Scoped to `numeric`/
`comparison` types only; `judged` questions untouched.

## Why

Built via TDD, red-green-refactor. Live re-run confirmed the fix catches
real bugs, not just tests: `aapl-employees-fy25` and
`aapl-revenue-growth-q3fy2026` both flipped from a masked PASS to a
correctly-diagnosed FAIL; `nvda-crm-revenue-comparison` also newly failed
on an apparent misattributed citation.

## Files touched

`agent.py`, `eval_harness.py`.

## Verification

148/148 unit tests. Live eval dropped from 19/21 to 16/21 on this run —
the harness being honest about problems it used to silently paper over,
not a regression.

## Related

`docs/decisions/2026-08-17-citation-verification-pass.md` (the mechanism
this wires in), `docs/decisions/2026-08-18-per-claim-citation-placement-rule.md`
(the next fix motivated by this run's results).
