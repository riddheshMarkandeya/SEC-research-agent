# Structure-aware table quote grounding replaces the flat anchor floor

**Date:** 2026-09-12

## Context

Picked up the `_QUOTE_ANCHOR_CHARS` backlog item, planned as a
straightforward "scale-aware anchor floor" fix. Investigation before
writing code showed that framing was wrong and needed a full re-plan.
Full design: `docs/plans/2026-09-12-structure-aware-table-quote-grounding.md`.

## Decision

New module `table_grounding.py`, parsing `<TABLE>` blocks into rows
classified as label/data/header/separator/blank, locating a claimed
value in a specific grid cell, and checking a quote's words are
explained only by that cell's own row-label, governing group-label, and
column's period header — not the whole row, not sibling columns.
Authoritative over `_quote_matches` whenever the claimed value is in a
table cell.

## Why

Reconstructed the real MSFT failure: a faithful quote split across
sparse cells scored below the flat anchor floor purely by segment-label
length. The proposed "loosen the floor" fix was tried, measured, and
rejected — a locality-based relaxation passed the real case but then let
a quote splice one row's value onto an unrelated adjacent row's label,
verified directly against `_verify_one_claim`. Chasing that further
found the existing flat floor was ALSO already accepting equivalent
misattributions (wrong period, 10x-inflated value) whenever a label was
long enough — the anchor floor was never really a label/value-alignment
defense.

A second real bug found in this fix's own two-pass review: an early
`quote_is_grounded` version required a cell's literal rendered text in
the quote — stricter than `_quote_matches` ever was, wrongly rejecting a
model restating a value without exact formatting. Fixed by comparing
quote-embedded numbers BY VALUE while label words stay a literal
word-level check. A fresh architecture review found one real robustness
gap (`_period_header_index`'s column-shift correction computed once per
table from an arbitrary sample row) — fixed by computing it fresh per
row.

## Files touched

`table_grounding.py` (new), `agent.py`
(`_quote_grounded_in_source`).

## Verification

17 new tests against REAL filing text, plus 4 end-to-end tests in
`test_agent.py`. Full suite 601 → 622. The required live spot-check was
attempted but blocked by Gemini quota exhaustion — explicitly left
outstanding, not assumed passed (see
`docs/decisions/2026-09-13-table-grounding-region-scoped-matching.md`
for where it was actually confirmed).

## Related

`docs/plans/2026-09-12-structure-aware-table-quote-grounding.md`,
`docs/reviews/2026-09-12-structure-aware-table-quote-grounding.md`,
`docs/decisions/2026-09-13-table-grounding-region-scoped-matching.md`
(fixes two live regressions found once this shipped).
