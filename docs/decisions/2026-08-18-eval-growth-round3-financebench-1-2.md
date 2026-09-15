# Eval growth round 3: 21 → 25 questions (FinanceBench priorities 1-2)

**Date:** 2026-08-18 (commit `9523bf5`, "Grow eval set 21 -> 25
questions, priorities 1 and 2 from the FinanceBench analysis")

## Context

Implements the top two priorities from the FinanceBench pattern analysis
(see `docs/decisions/2026-08-18-financebench-analysis.md`): statement-
scoped questions and same-company cross-segment comparisons.

## Decision

Added 4 questions, each ground-truthed directly against real data before
writing: `nvda-total-assets-q1fy27` ($259,474M via `fetch_concept`),
`aapl-cash-equivalents-q3fy2026` ($39,544M via `fetch_concept`),
`nvda-segment-revenue-comparison-q1fy27` (Compute & Networking $74,550M
vs Graphics $7,065M), `msft-segment-revenue-comparison-q3fy2026`
(Productivity $35,013M narrowly ahead of Intelligent Cloud $34,681M,
deliberately close numbers).

## Why

**All 4 new questions FAILed, each for a different, real reason** — not
noise, and deliberately not "fixed" by picking easier questions.
`nvda-total-assets-q1fy27`: complete miss — `total_assets` wasn't in
`DEFAULT_METRIC_TAGS` and unstructured search genuinely can't find the
balance sheet table (confirmed via a standalone `hybrid_search()` call
beforehand). `aapl-cash-equivalents-q3fy2026`: subtler — the model found
the textually correct value, but the citation-verification gate caught
that it wasn't actually grounded in the cited source.
`nvda-segment-revenue-comparison-q1fy27`: the model concluded both
segments had *equal* revenue, a real misread of the table.
`msft-segment-revenue-comparison-q3fy2026`: picked the wrong segment
with cited figures matching no number in the real table at all.

Decided to keep growing the eval set through the remaining
FinanceBench-informed priorities first, then fix the accumulated
findings one by one — same "let evidence accumulate before deciding what
to build" reasoning as the original XBRL-tool round.

## Files touched

`eval_questions.jsonl`.

## Verification

Ground truth verified directly against real retrieved chunks and/or
`fetch_concept()` before writing each question.

## Related

`docs/decisions/2026-08-18-financebench-analysis.md`,
`docs/decisions/2026-08-19-eval-growth-round4-financebench-3-5.md`,
`docs/decisions/2026-08-19-fixing-6-accumulated-eval-findings.md` (where
these 4 findings, plus round 4's 2, were resolved).
