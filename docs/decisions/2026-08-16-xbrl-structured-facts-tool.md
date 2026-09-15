# Structured XBRL facts tool (`xbrl_facts.py`, `get_financial_fact`)

**Date:** 2026-08-16 (commit `2906f7e`, "Add get_financial_fact XBRL
tool, fixing the two retrieval-precision bugs")

## Context

`period_labels.py`'s embedding-prefix fix failed to solve the two
retrieval-precision bugs (`nvda-gross-margin-fy26`,
`msft-rd-expense-q3fy26`). Both numbers are also GAAP concepts SEC filers
tag as structured XBRL data — fetchable directly by company + concept +
period, sidestepping the retrieval-collision problem instead of trying
to out-rank the decoys.

## Decision

New agent tool `get_financial_fact`, backed by SEC's `companyconcept`
API. `DEFAULT_METRIC_TAGS`/`METRIC_TAG_OVERRIDES` map friendly names to
real GAAP tags; `gross_margin` is computed inside the tool from
`GrossProfit`/`Revenues` rather than returned raw. `_pick_entry()`
disambiguates SEC's re-reported comparative periods by duration (quarter
≈80-100 days, year ≈350-380 days), then latest `end` date.

## Why

A `companyconcept` response isn't one-entry-per-period — a single
10-K/10-Q re-reports 2-3 years of comparative data under the identical
`fy`/`fp` label, plus a 10-Q's own 3-month and 9-month YTD figures under
that same label — the same structural risk class as the retrieval
period-matching bugs.

**Five real bugs found and fixed along the way:**
1. Fiscal-year arithmetic the model can't do reliably — a calendar date
   phrasing led the model to compute the wrong fiscal year for NVDA's
   January fiscal year end. Fixed with a `period_end_date` alternative
   input, initially via a `resolve_fiscal_period()` helper (superseded
   Week 5e — see the period-matching decision file).
2. Wrong default revenue tag — `Revenues` looked fine by HTTP-status
   check alone, but AAPL's data stops in 2018 and MSFT's in 2011 (both
   switched to the ASC 606 tag). NVDA is the actual outlier still using
   plain `Revenues`. Fixed: ASC 606 tag as default, NVDA the sole
   override.
3. Unhandled crash on an unsupported metric (model omitted `metric`
   entirely rather than skip the call) — fixed with a boundary guard.
4. Unhandled crash on an empty-string date — fixed by treating a falsy
   `period_end_date` as "not provided," plus a `try/except` for a
   malformed one.
5. Comparison questions silently incomplete — after one company returned
   "not available," the model sometimes stopped instead of trying
   `search_filings` and continuing to the next company. Fixed with an
   explicit system-prompt rule.

Known, deliberately out-of-scope limitation: NVIDIA (and most annual
filers) don't tag a standalone Q4 duration — `fiscal_period="Q4"`
returns `None` for such companies (see the Q4-refusal fix decision file).

## Files touched

`xbrl_facts.py` (new), `agent.py` (new tool wiring).

## Verification

`nvda-gross-margin-fy26` and `msft-rd-expense-q3fy26` both PASS with
exact values (71.1%, $8,915M), confirmed via direct live `agent.py` runs.
Full suite 16/16, up from 14/16, no regressions. Period-entry
disambiguation verified against real captured NVDA/MSFT data in
`tests/test_xbrl_facts.py`, not synthetic fixtures.

## Related

`docs/decisions/2026-08-16-fiscal-period-labels-tried-and-reverted.md`
(the rejected alternative this supersedes),
`docs/decisions/2026-08-17-xbrl-period-matching-end-date-fix.md`
(supersedes bug #1's original fix),
`docs/decisions/2026-08-18-q4-refusal-fix.md` (closes the Q4 gap).
