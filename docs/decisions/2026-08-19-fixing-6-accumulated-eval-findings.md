# Fixing the 6 accumulated eval findings from growth rounds 3 and 4

**Date:** 2026-08-19 (commit `619cdde`, "Fix 4 of 6 accumulated eval
findings; partially improve a 5th")

## Context

Worked through all 6 findings from
`docs/decisions/2026-08-18-eval-growth-round3-financebench-1-2.md` and
`docs/decisions/2026-08-19-eval-growth-round4-financebench-3-5.md`.

## Decision

**4 solidly fixed (3+ consecutive clean re-runs each):**
- `nvda-total-assets-q1fy27` + `aapl-cash-equivalents-q3fy2026`: added
  `total_assets`/`cash_and_equivalents` to `DEFAULT_METRIC_TAGS`. Found a
  real, previously-unexercised bug along the way: every metric supported
  before these two was a duration concept; balance-sheet items are
  *instant* concepts (point-in-time, `end` only), and `_duration_days()`
  crashed on them. Fixed by returning `None` for instant entries and
  skipping duration-bucket disambiguation for them.
- `nvda-segment-revenue-comparison-q1fy27` (+ partial on the MSFT
  sibling): root-caused via live `--verbose` repro — the model invented a
  `segment` filter `get_financial_fact` never supported, and the old
  code only read known keys, silently dropping it — both segment calls
  returned the same consolidated total, and the model concluded the two
  segments were equal. Fixed by rejecting any call with an unrecognized
  key outright (`_FACT_ARG_KEYS`/`_COMPARE_ARG_KEYS` allow-lists), forcing
  a clean fallback to `search_filings`.
- `aapl-3yr-avg-operating-margin-fy2023-fy2025`: built
  `get_multi_year_average(ticker, metric, start_fiscal_year,
  end_fiscal_year)` in `formulas.py`, exposed as an alternate mode on
  `get_financial_fact` (same pattern as `yoy_growth`). Hit the
  `MARGIN_METRIC_FUNCTIONS`-style import-time-binding gotcha a third
  time while building this — fixed by dispatching via a plain if/elif
  chain instead of a pre-built dict.

**1 partial improvement**: `pltr-inventory-turnover-fy2025-refusal` —
added `inventory` to `DEFAULT_METRIC_TAGS` plus `is_metric_tagged()`/
`_never_tagged_hint()` (same "explain why, not just that" principle as
the Q4 hint). Works when exercised, but the model doesn't reliably reach
it — live testing showed it twice inventing a metric name
(`inventory_turnover_ratio`) that gets rejected before ever reaching the
new hint. 1 PASS / 2 FAIL across 3 live re-runs.

**1 still open**: `msft-segment-revenue-comparison-q3fy2026` failed 3/3
times, 3 DIFFERENT ways each time — too inconsistent to point at one
mechanism the way the NVDA case's invented-parameter bug did. Needed a
dedicated `--verbose` investigation session (see
`docs/decisions/2026-08-19-table-chunk-rescue-in-reranking.md`).

## Files touched

`xbrl_facts.py` (`_duration_days`, instant-fact handling),
`formulas.py` (`get_multi_year_average`), `agent.py`
(`_FACT_ARG_KEYS`/`_COMPARE_ARG_KEYS` allow-lists, `_never_tagged_hint()`).

## Verification

202/202 unit tests. Full 27-question re-runs after each fix held the
original 21 questions at their known baseline; confirmed one apparent
new failure (`aapl-operating-margin-q3fy2026`) was pre-existing
temperature variance via a direct `--verbose` repro, not caused by the
new schema fields.

## Related

`docs/decisions/2026-08-19-discover-tags-dev-tool.md` (built to make the
tag-discovery loop this round relied on faster),
`docs/decisions/2026-08-19-table-chunk-rescue-in-reranking.md` (resolves
the still-open MSFT segment question).
