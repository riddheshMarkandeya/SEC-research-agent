# Citation-verification pass (`numeric_utils.py`, `verify_citations()`)

**Date:** 2026-08-17 (commit `2845b2b`, "Add citation-verification pass
to agent.py, fixing real number-extraction bugs")

## Context

`aapl-revenue-growth-q3fy2026` technically passed its eval, but only
because the model self-computed a percentage from two retrieved dollar
figures — violating rule 3 ("don't combine or infer numbers") — and
cited both dollar-figure sources for a percentage that appears in
neither.

## Decision

A cheap, deterministic post-processing step: after `run_agent()`'s final
answer, check that each cited `[n]`'s numeric claim actually appears in
that result's own text. No model call needed. `run_agent()` returns a
third value, `citation_warnings: list[str]`. `extract_numbers()`/
`normalize()`/`NUMBER_PATTERN`/`UNIT_MULTIPLIERS` moved into a new
`numeric_utils.py` so `agent.py` could reuse them without a circular
import.

## Why

The first working version caught the real misgrounding but was nearly
unusable (12 warnings for one answer, only 1 genuinely useful). Four
real, live-found noise sources were fixed in order: dates read as bare
numbers; bare year-like numbers ("fiscal Q3 2025"); "10-K"/"10-Q"
mentions (the dominant noise source); and table-caption-only units
(a correctly-answered `crm-rpo-fy26` got a false warning because the
unit is stated once in a table caption and each cell value is bare —
fixed with `_source_number_candidates()`, an additive fallback that only
creates new ways to *verify* a claim).

Two bugs found in `NUMBER_PATTERN` itself (also improving
`grade_numeric()`): the leading digit group was capped at `\d{1,3}`,
fragmenting a comma-less long run of digits (raw float formatting like
"109417000000.0") into wrong pieces — fixed by removing the cap; a digit
run glued to a preceding letter/digit ("Q3" read as 3) wasn't excluded —
fixed with a `(?<!\w)` negative lookbehind.

Known, accepted residual limitation: a self-authored trailing
"References:" list can pick up a nearby number as its "claim" even
though it's not attached to a specific statement; multi-step derivation
shown between a claim and its citation can leak intermediate numbers.
Judged narrow enough (5/21 questions had at least one warning, mostly
single-line, non-blocking) not worth chasing further for a tool
explicitly scoped as a cheap heuristic.

## Files touched

`numeric_utils.py` (new), `agent.py` (`verify_citations()`,
`_iter_citation_claims()`).

## Verification

Full suite after all fixes: 19/21 (the 2 failures are pre-existing,
unrelated — a judged-grading instability and the operating-margin
formula gap).

## Related

`docs/decisions/2026-08-18-citation-verification-wired-into-eval-gate.md`
(wires this from warning-only into pass/fail).
