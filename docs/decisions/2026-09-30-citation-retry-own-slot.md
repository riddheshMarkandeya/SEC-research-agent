# The citation retry gets its own slot, outside the tool budget

**Date:** 2026-09-30 (live verification finished 2026-10-01)

## Context

Since 2026-08-24 (`0ba1e5d`) the one citation retry shared `MAX_TOOL_ITERATIONS` with the
agent's tool calls: a submission whose claims failed verification got a retry only if budget
was left. Mining the traces showed that 27 of 38 gate refusals got no retry because the budget
was spent, while the retry rescued 49 of 60 runs when it did fire. This is package 1 (gate D9)
of the agent-improvement map.

## Decision

The retry fires whenever claims fail, still capped at one per conversation. Past the budget it
forces `submit_answer` and spends the reserved final turn, so nothing forced follows it.
In-budget retries stay unforced. Shipped as `f6a75db` (agent fingerprint `4051dbdc19a7`); the
commit body has the mechanics.

## Why

- The retry's value is measured (49/60 rescued); gating it on leftover budget threw away most of
  the chances to use it.
- Forcing `submit_answer` past the budget diverges from D9, which left the retry unforced: a
  search after the budget would have broken to a refusal of the old answer anyway.
- The worst case is `MAX_TOOL_ITERATIONS + 2` model sends per question, a bounded cost.

## Files touched

`src/sec_agent/agent/` (the submit loop and the retry helper), its tests, and the model-input
snapshot scenarios. See `f6a75db`.

## Verification

- Panel 3x on the gate-sensitive set (`eval/eval_results/20260930T205234Z.json`, `205532Z`,
  `205927Z`): 39/39. Explicit-mode compare against the pre-change panel (`071313Z`, `071948Z`,
  `072319Z`): no regression; pltr-inventory-turnover-fy2025-refusal went from 1/3 to 3/3.
- Full 48-question run at `9ee08ab` (same code as `f6a75db`):
  `eval/eval_results/20261001T193130Z.json`, 2026-10-01 19:19:51-19:31:31Z, **42/48**, no
  quota errors. That matches the last full run, `20260929T204453Z` at `7b5be7b` (42/48).
  - Gained: pltr-inventory-turnover-fy2025-refusal (the retry's target) and
    nvda-rd-expense-q4fy26-refusal.
  - Lost, both explained from traces, neither caused by the retry slot:
    - aapl-msft-employee-comparison: five MSFT searches never surfaced the 223,000 employee
      figure, so the final turn was forced (a retrieval miss).
    - nvda-segment-revenue-comparison-q1fy27: the model quoted two table rows word for word
      from source [10], and the gate rejected them as `quote_not_found`. Each row alone passes,
      so the gate mishandles a quote spanning rows. The retry resubmitted the same quote and was
      refused again. Reproduced offline; logged in `BACKLOG.md`.
- Refusal re-mine of the full run: the retry fired in 8 runs and 5 of them passed. The 3 that
  failed are the NVDA case above, plus msft-segment-revenue-comparison and
  crm-buyback-and-liquidity, which also failed in the previous two full runs. Gate replay of all
  48 runs: 1 refusal, no drift, and the same verdicts as logged.

## Related

- Reverses `0ba1e5d` and the design in `docs/plans/2026-08-24-citation-retry-loop-design.md`.
- `docs/decisions/2026-09-16-final-turn-safety-net.md`: the reserved final turn the forced retry
  spends.
- `docs/plans/2026-09-28-agent-improvement-map.md`: package 1.
