# Redesign `get_metric_all_companies()` to split by concept type

**Date:** 2026-09-07

## Context

The prior day's §4 fix (borrowing another covered company's SEC-assigned
`frame` as a fallback anchor) shipped with a real regression: a `frame`
anchors to a specific calendar window, and a different company's frame
represents a genuinely different real time period, not "the same
period, from someone else's data." Live-verified the actual failure:
anchoring NVDA against MSFT's frame returned NVDA's Q2 FY2027 balance
mislabeled as the requested FY2026 figure. Full design:
`docs/plans/2026-09-07-fix-get-metric-all-companies-instant-metrics.md`.

## Decision

Root-caused via two independent sources (an existing code comment
already flagging this, plus web research confirming "calendarization" is
standard for duration figures but explicitly not applied to
balance-sheet instant figures). Redesigned by splitting on concept type:
a new `INSTANT_METRICS` registry resolves each covered company
independently via its own `get_metric()` call for the requested period,
with no frame/anchor requirement at all. Duration metrics are completely
unchanged.

## Why

Two alternatives were presented and discussed before choosing this one
over a closest-date-match-with-tolerance mechanism, which would have
fought against the calendarization research rather than followed it. No
existing eval question exercised `get_metric_all_companies` for an
instant metric — the real reason neither the eval suite nor the
same-day self-review caught the original regression; closed with a new
question, `aapl-msft-total-assets-comparison`.

## Files touched

`xbrl_facts.py` (`get_metric_all_companies`, `INSTANT_METRICS`),
`agent.py` (`_comparison_as_results`).

## Verification

Full suite 378/378. Live-verified the exact repro that exposed the bug
now returns NVDA's own correct figure, not MSFT's borrowed window. See
the plan doc for the complete design and the paired review's findings
(folded into
`docs/decisions/2026-09-06-full-codebase-review.md`'s second addendum).

## Related

`docs/decisions/2026-08-17-frames-api-cross-company.md` (the original
frames design this redesigns one half of),
`docs/decisions/2026-09-06-full-codebase-review.md`.
