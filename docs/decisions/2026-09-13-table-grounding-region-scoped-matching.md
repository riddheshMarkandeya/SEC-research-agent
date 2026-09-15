# Table-grounding region-scoped redesign, fixing two live regressions

**Date:** 2026-09-13

## Context

Merged the 6 citation-stress questions into the main eval set (41 → 47)
and ran the first full baseline against `table_grounding.py`'s real
exercise against actual model answers. Found two real regressions
(`crm-rpo-fy26`, `nvda-segment-revenue-comparison-q1fy27`): the per-cell
word-vocabulary allowlist correctly blocks a cross-column fabrication but
also wrongly rejects a genuinely faithful multi-value row quote. A
reactive fix tried mid-investigation (an unconditional "exact substring
of the whole source wins" shortcut) was found, before landing, to reopen
the row-splice attack the whole feature exists to block — the user
stopped further ad hoc patching and asked for a full diagnosis and plan.
Full design: `docs/plans/2026-09-13-table-grounding-region-scoped-matching.md`.

## Decision

`table_grounding.py` rebuilt around a per-cell "permitted region" — the
table's own header/caption rows + the cell's governing group-label row +
its own data row, all as verbatim source text — matched via a new shared
`numeric_utils.text_coverage` primitive extracted from
`agent._quote_matches`. `_classify_row` gained a parenthesization signal
distinguishing a permanent table-wide header from a resettable per-group
label.

## Why

Testing the redesign against its own fixtures surfaced a second bug in
the same session: pure coverage let a wrong value's digits
"scatter-match" against unrelated real numbers in the same region
(measured: 94% coverage for a fabricated value with none of its own
digits actually present) — fixed with a separate tight-tolerance
number-presence check. A fresh, deliberately-skeptical architecture
review then found a HIGH-severity regression in the redesign itself,
independently re-verified before accepting it: removing the per-column
period defense had silently widened the accepted "same-row" tradeoff —
re-running yesterday's committed design against the identical fixture
confirmed it correctly rejected the exact case the redesign now passed.
Fixed with a cherry-pick check: a quote may not cite one label out of a
multi-column row while omitting the row's other labels.

## Files touched

`table_grounding.py`, `numeric_utils.py` (`text_coverage`, extracted).

## Verification

`tests/test_table_grounding.py` 17 → 21 tests with real CRM/NVIDIA
fixtures; full suite 622 → 631. Live spot-check on the 4 targeted
questions: both regressions now PASS, the original reported bug still
PASSES, zero unverified citations across all four. Full 47-question
baseline: 31/47, up from 24/47, with all 5 newly-failing questions traced
to confirmed pre-existing, unrelated causes.

## Related

`docs/plans/2026-09-13-table-grounding-region-scoped-matching.md`,
`docs/reviews/2026-09-13-table-grounding-region-scoped-matching.md`,
`docs/decisions/2026-09-12-structure-aware-table-quote-grounding.md`
(the design this replaces).
