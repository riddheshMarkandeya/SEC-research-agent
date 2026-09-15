# Fixed the 4 High-priority findings from the full-codebase review

**Date:** 2026-09-06 (2nd addendum: 2026-09-07)

## Context

First full-codebase `/code-review` pass since the project's early days.
Full findings: `docs/reviews/2026-09-06-full-codebase-review.md`.

## Decision

Fixed all 4 High findings the same day: `agent.py`'s schema-violation
guards crashed instead of degrading on unhashable ticker/metric values
(§1); `eval_harness.py`'s `grade_judged()` bypassed `llm_backends.py`
entirely, losing retry/backoff (§3); `run_eval()` had no per-question
exception isolation, so one bad question discarded the whole batch's
results (§2); `compare_financial_metric` silently returned empty for
several metrics at the latest fiscal year due to a frame-anchoring gap
(§4).

## Why

See the review doc for full root-cause detail per finding. §4's initial
fallback (borrowing another company's frame) shipped with a real
regression, found and corrected the next day — see
`docs/decisions/2026-09-07-fix-get-metric-all-companies-instant-metrics.md`
for that redesign. A second addendum's layered review (Substantial-tier,
since the 09-07 redesign was a real architecture decision) surfaced 6
more findings, mostly fixed the same day: a telemetry gap that only fired
when the WHOLE comparison result was empty, not when just the requested
anchor was missing; an inaccurate docstring claim; a documented (not
fixed) trade-off in `period_end_date`-based instant-metric comparison;
plus three smaller consistency fixes.

## Files touched

`agent.py`, `eval_harness.py`, `xbrl_facts.py`.

## Verification

Full suite 380/380 after all fixes in this thread. See the review doc
for the complete verification trail.

## Related

`docs/reviews/2026-09-06-full-codebase-review.md` (full findings),
`docs/decisions/2026-09-07-fix-get-metric-all-companies-instant-metrics.md`,
`docs/decisions/2026-09-08-fix-3-medium-review-findings.md`,
`docs/decisions/2026-09-09-fix-3-more-review-findings.md`,
`docs/decisions/2026-09-10-fix-3-more-review-findings.md` (the remaining
findings from this same review, fixed in later sessions).
