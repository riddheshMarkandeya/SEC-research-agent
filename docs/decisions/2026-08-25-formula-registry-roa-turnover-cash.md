# Formula registry extended: return_on_assets, asset_turnover, cash_to_assets

**Date:** 2026-08-25

## Context

Closes the citation-verification-gap decision from
`docs/decisions/2026-08-25-eval-growth-27-to-38-multi-statement-ranking.md`
by removing its root cause for three ratios: no deterministic tool
existed, so the model reached for self-computation. These three
questions had already generated real evidence of what the agent does
without a path (a wrong-company answer, a self-computed-and-uncited
ratio) — building the tool was justified by observed demand, not
speculation.

## Decision

`_compute_ratio_metric()` gained an `as_percent` flag (default `True`) —
`asset_turnover` is the first ratio that isn't a percent. Added
`get_return_on_assets`, `get_asset_turnover` (`as_percent=False`),
`get_cash_to_assets` — the first ratios combining a duration
income-statement metric with an instant balance-sheet one, which
`get_metric()` already normalizes to the same shape. Deliberately no
cross-company `_all_companies` counterpart for any of the three
(confirmed live: an annual instant fact's SEC-assigned `frame` is
`None`, so there's no frames-API bucket to anchor on).

## Why

A real crash risk found and closed before it could fire: adding these
three names to a metric-functions dict makes them pass the boundary
check, which means a multi-year-average request combined with one of
them would otherwise crash inside `get_metric()`'s tag lookup — closed
by extending `_get_annual_value()`'s dispatch, covered by regression
tests before ever exercised live.

Live-verified, not just unit-tested: `aapl-return-on-assets-fy2025` and
`nvda-asset-turnover-fy2026` resolved cleanly every time tried;
`msft-cash-to-assets-fy2025` was more mixed across 4 manual runs (2
called the new tool cleanly, 2 still self-computed with no citation) —
the tool helps when the model reaches for it, but doesn't guarantee it
will every time, a caveat already documented elsewhere in this project.

## Files touched

`formulas.py`, `agent.py` (`SINGLE_COMPANY_RATIO_FUNCTIONS`,
`_get_annual_value()`).

## Verification

Gemini 34/35 (up from 33/35, all three new questions clean). Ollama
26/35 (up from 23/35) — `aapl-return-on-assets-fy2025` and
`nvda-asset-turnover-fy2026` both flipped FAIL→PASS as direct,
attributable fixes; `msft-cash-to-assets-fy2025` stayed FAIL, consistent
with the already-established broader capability-ceiling pattern.

## Related

`docs/decisions/2026-08-25-eval-growth-27-to-38-multi-statement-ranking.md`
(the evidence that motivated this),
`docs/decisions/2026-08-28-ratio-definitions-table-driven-registry.md`
(the next generalization of this pattern).
