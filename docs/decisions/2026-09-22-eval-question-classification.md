# Classify eval questions as solid/flaky/regression, not just a pass-rate ranking

**Date:** 2026-09-22

## Context

`analyze_flakiness.py` (2026-09-18) ranks eval questions by all-time,
unbounded pass rate — one continuous number, no classification, no
time-boundedness. A question fixed weeks ago still carries its old
failing runs into that rate forever, and nothing distinguishes "genuinely
non-deterministic" from "currently, persistently broken." Both look like
"a somewhat low pass rate," and telling them apart has been done by hand,
per question, every session (see nearly every recent decision doc's
"confirmed pre-existing flakiness, not a regression" paragraph). Asked
directly how flakiness/regression are normally defined elsewhere, rather
than continuing to eyeball a sorted list.

## Decision

Extended `analyze_flakiness.py` in place with `classify_history()`, which
buckets each question into solid/flaky/regression/insufficient-data using
only a capped trailing window of recent runs (default 20, not unbounded
history), based on trailing pass/fail streaks and oscillation
(transition) count rather than aggregate rate alone. `format_summary()`
now emits four labeled sections instead of one flat ranking. Stays a pure
on-demand CLI report — no new persisted snapshot file.

## Why

Full reasoning — the prior-art research (Google's bounded-window
mitigation, academic flaky-test classification literature, Wilson score
intervals, Meta's probabilistic flakiness score, CUSUM/DeFlaker/
iDFlakies), the exact threshold defaults and their justification, and two
real algorithmic bugs an independent plan review caught before
implementation — is in the paired plan file, not re-derived here.
Additional issues found and fixed during a 3-round post-implementation
review (four sibling threshold fields missing the same validation
`window` got, a hardcoded confidence-interval label, a cross-field
validation gap between two new threshold fields) are in the paired
review file.

## Files touched

- `analyze_flakiness.py` — `ClassificationThresholds` (new, with
  `__post_init__` validation), `_trailing_streak`/`_trailing_fail_streak`/
  `_trailing_pass_streak`/`_count_transitions`/`_wilson_interval`/
  `_confidence_label`/`classify_history` (new), `summarize()` (added
  `history` field), `format_summary()` (restructured into 4 sections),
  `main()` (new CLI flags, sorts `args.reports` before `load_rows()`).
- `tests/test_analyze_flakiness.py` — full TDD: new tests for every new
  function including boundary-exact cases, updated tests for
  `summarize()`/`format_summary()`'s changed contracts.
- `docs/plans/2026-09-22-eval-question-classification.md`,
  `docs/reviews/2026-09-22-eval-question-classification.md` — paired
  plan/review.
- `PROJECT_INDEX.md`, `BACKLOG.md` — updated per the documentation
  system.

## Verification

Full detail in the paired review file. Summary: 766 tests passing (up
from 757), `ruff check .`/`pyright .` both zero errors full-repo, 91.9%
diff coverage on `analyze_flakiness.py` (above the 80% ordinary-file
bar). Run against all 127 real historical report files:
`msft-segment-revenue-comparison-q3fy2026` (24% all-time, long-documented
as chronically troubled) correctly lands in Regression; `crm-rpo-fy26`
(98% all-time) correctly lands in Solid. The recovery-streak mechanism
(added during plan review) visibly matters on real data — several
questions with a rough historical patch but a long current pass streak
correctly land in Solid instead of being dragged down by old failures,
which is the exact problem this change exists to fix.

## Related

Plan: `docs/plans/2026-09-22-eval-question-classification.md`.
Review: `docs/reviews/2026-09-22-eval-question-classification.md`.
Extends `docs/decisions/2026-09-18-flaky-eval-questions-three-fixes.md`
(which created `analyze_flakiness.py`).
