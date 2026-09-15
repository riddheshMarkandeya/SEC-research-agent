# Eval growth round 4: 25 → 27 questions (FinanceBench priorities 3, 5)

**Date:** 2026-08-19 (commit `ace8ca7`, "Grow eval set 25 -> 27 with
multi-year-average and inapplicable-metric questions")

## Context

Completes all 5 FinanceBench-informed priorities (see
`docs/decisions/2026-08-18-financebench-analysis.md`): a multi-year-
average ratio (beyond the formula registry's single-period scope) and an
inapplicable-metric-recognition question.

## Decision

`aapl-3yr-avg-operating-margin-fy2023-fy2025`: 31.1%, computed from real
unrounded per-year margins (29.82%, 31.51%, 31.97%) via `get_metric()`
directly, not by averaging the registry's already-rounded outputs.
`pltr-inventory-turnover-fy2025-refusal`: confirmed via `fetch_concept`
→ 404 (PLTR genuinely has no inventory line item, unlike NVDA/AAPL/MSFT).

## Why

Both FAILed, in more specific ways than predicted.
`aapl-3yr-avg-operating-margin-fy2023-fy2025`: the model completely
misparsed "3-year average" as a request for Q4-specific figures, hit the
Q4-not-disclosed hint, and echoed it verbatim — a new bug class
(multi-year-average misread as intra-year quarterly), not the
rule-3-self-computation violation expected.
`pltr-inventory-turnover-fy2025-refusal`: closer to correct than a bare
pass/fail suggests — it did refuse, but never identified the *actual*
reason (no inventory line item, structural to the business), framing it
as generic missing data, and pointlessly cited an unrelated
cost-of-revenue figure.

Neither fixed immediately — added to the same accumulating-findings
queue as round 3.

## Files touched

`eval_questions.jsonl`.

## Verification

Ground truth verified against real `get_metric()`/`fetch_concept()`
calls before writing.

## Related

`docs/decisions/2026-08-19-fixing-6-accumulated-eval-findings.md`
(resolves this round's 2 findings plus round 3's 4).
