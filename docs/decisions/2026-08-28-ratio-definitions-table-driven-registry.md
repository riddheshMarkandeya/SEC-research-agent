# Ratio-formula registration made cheap: `RATIO_DEFINITIONS` table

**Date:** 2026-08-28

## Context

Prompted by the user asking whether the formula registry should become
more "dynamic," and whether the model should do its own arithmetic if
inputs are verified. Both investigated against the actual code before
designing anything.

## Decision

Letting the model compute + only verifying inputs was rejected — this is
exactly the failure mode `verify_citations()` was built to catch (the
`aapl-revenue-growth-q3fy2026` incident): correctly-cited inputs with
wrong arithmetic, undetected; verifying inputs independently also can't
catch a period mismatch the way `_compute_ratio_metric()`'s equality
check already does. A fully dynamic calculator tool was already
considered and rejected (`formulas.py`'s own docstring says so).

What the code actually showed: two of three formula shapes were already
dynamic (`get_yoy_growth`/`get_multi_year_average` take `metric` as a
free parameter); only same-period ratios of two different metrics were
stuck at one hand-written function each. Fix: a `RatioDefinition`
NamedTuple, a `RATIO_DEFINITIONS` table (numerator, denominator,
`as_percent`, `supports_cross_company`), and generic `get_ratio()`/
`get_ratio_all_companies()`. The table deliberately holds only plain
data, never function references — sidesteps the monkeypatch-staleness
gotcha already hit twice. Two new ratios added with the user:
`inventory_turnover`, `rd_intensity`.

## Why

`_get_annual_value()`'s six-way `if/elif` collapsed to one `if metric in
RATIO_DEFINITIONS` check — not just cleanup, a ratio added only to the
table would otherwise silently reach `get_metric()` and crash, the exact
bug class the three-branch addition was built to prevent.

Two issues caught by `/code-review` before shipping: the 3 pre-existing
named `_all_companies` functions were left hardcoding their metric pairs
instead of delegating through `get_ratio_all_companies()` — a real
duplication gap, and converting them exposed 3 of 7 tests that were
"passing" while silently no longer testing what they claimed to (the
underlying computation only reads `anchor["frame"]`, never
`anchor["value"]`). Also: `get_ratio_all_companies()` didn't forward
`as_percent`, latent today but a real gap given the section's own claim
that flipping a decimal ratio to cross-company later is "easy."

## Files touched

`formulas.py` (`RatioDefinition`, `RATIO_DEFINITIONS`, `get_ratio`,
`get_ratio_all_companies`), `agent.py` (deleted both old hardcoded dicts,
derived enum lists/system-prompt text from the table).

## Verification

Full suite 305/305 (up from 293). Live-checked both new ratios
end-to-end (2/2 PASS matching live-fetched ground truth), no regression
on the 5 pre-existing single-company ratios, all 3 cross-company margin
functions directly for all 5 companies. The 5-company ranking judged
questions failed then passed on immediate re-runs, confirmed as
live-model anchor-choice non-determinism, not a regression.

## Related

`docs/decisions/2026-08-25-formula-registry-roa-turnover-cash.md`
(the pattern this generalizes).
