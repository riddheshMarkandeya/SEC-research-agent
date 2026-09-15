# FinanceBench pattern analysis, informing eval-growth priorities

**Date:** 2026-08-18 (dated via commit `9523bf5`, "Grow eval set 21 -> 25
questions, priorities 1 and 2 from the FinanceBench analysis" — the
analysis itself has no dedicated commit but directly precedes and names
this one)

> Migration note: this file rescues content that originally lived inside
> `PROJECT_CONTEXT.md`'s "Next steps" `<details>` historical-log block.
> Most of that block was confirmed redundant with sections migrated
> elsewhere and dissolved with no migration — this specific entry's
> substance (which patterns were adopted and why, and the explicit
> differentiator finding) is not restated anywhere else in the document,
> so it gets its own decision file rather than being silently dropped.

## Context

Before writing further eval questions by hand, fetched the public
150-question open-source FinanceBench set (`PatronusAI/financebench` on
GitHub) to study question-shape structure.

## Decision

Confirmed zero usable company/period overlap (only 2 MSFT questions
total, both old fiscal years; AAPL/NVDA/PLTR/CRM absent entirely) —
questions can't be imported, only patterns borrowed. Adopted, in
priority order: (1) statement-scoped questions, (2) same-company
cross-segment comparisons, (3) multi-year-average ratios, (4) Yes/No +
one-line-justification judged questions, (5) "metric doesn't apply to
this business" recognition. All five were subsequently built across the
two FinanceBench-informed eval-growth rounds.

## Why

Priority 1 directly targets the exact retrieval-precision-collision
failure mode already found twice
(`nvda-gross-margin-fy26`, `msft-rd-expense-q3fy26`). Priority 5 found a
real forcing case once built: Palantir doesn't tag inventory at all
(confirmed via `fetch_concept` returning 404), unlike the other four
companies.

**A real differentiator was identified and deliberately preserved, not
copied**: zero of FinanceBench's 150 answers are refusal-style ("not
disclosed", "not available") — it doesn't test "recognize data genuinely
isn't there, don't fabricate" at all. This project's Q4-refusal/
PLTR-dividend questions test something FinanceBench doesn't — kept as a
real investment, not treated as a distraction from "real" eval growth.

Explicitly out of scope: FinanceBench pulls some questions from 8-Ks;
this project only ingests 10-K/10-Q — not extending ingestion for this.

## Files touched

None directly (research informing subsequent eval-question authoring).

## Verification

N/A — a research/analysis decision, not a code change.

## Related

`docs/decisions/2026-08-18-eval-growth-round3-financebench-1-2.md`,
`docs/decisions/2026-08-19-eval-growth-round4-financebench-3-5.md` (the
two rounds this analysis directly produced).
