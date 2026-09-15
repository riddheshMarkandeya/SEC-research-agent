# Formula registry split into its own module (`formulas.py`)

**Date:** 2026-08-18 (commit `031106a`, "Split formula registry into
formulas.py; analyze FinanceBench for eval-growth patterns")

## Context

By this point, 9 of `xbrl_facts.py`'s 16 top-level functions were already
formula/ratio logic, not raw XBRL fetching — more than half the file, and
about to grow further with the FinanceBench-informed eval-growth round.
Unlike raw XBRL tags (a small, bounded set SEC defines), the list of
financial ratios a user might ask for has no natural upper limit.

## Decision

New `formulas.py` owns every derived metric (`get_gross_margin`/
`get_operating_margin`/`get_net_margin` + all-companies versions,
`get_yoy_growth`, both `_compute_ratio_metric*` bodies); it imports
`get_metric`/`get_frame` from `xbrl_facts.py`. `xbrl_facts.py` shrinks
back to raw-fact fetching only. `agent.py`'s `MARGIN_METRIC_FUNCTIONS`
stays in `agent.py` (tool-dispatch wiring, not a formula).

## Why

Same duplication-avoidance reasoning as `config.py`, applied to a
different kind of drift. A real gotcha caught before it caused silent
test bugs: tests that monkeypatch `get_frame`/`get_gross_margin`/etc.
for functions now living in `formulas.py` had to retarget their patches
to `"formulas.X"`, not `"xbrl_facts.X"` — `from xbrl_facts import
get_frame` binds a separate name in `formulas.py`'s own namespace at
import time, so patching the source module doesn't reach a call made via
the importing module's own bare name. This exact gotcha recurred at
least twice more later in the project's history (see the
`RATIO_DEFINITIONS` and multi-year-average decision files).

## Files touched

`formulas.py` (new), `xbrl_facts.py` (shrunk), `agent.py` (import
updates), `test_formulas.py` (new, 19 tests moved from `test_xbrl_facts.py`).

## Verification

Pure refactor, no behavior change: 173/173 tests before and after.
Verified live through the real import chain too — `get_operating_margin`/
`get_yoy_growth` still return the previously-verified values, and
`agent.MARGIN_METRIC_FUNCTIONS["operating_margin"][0] is
formulas.get_operating_margin` confirms the dispatch table is wired to
the real function.

## Related

`docs/decisions/2026-08-18-financebench-analysis.md` (the other half of
this same commit).
