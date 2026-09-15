# XBRL period matching: match on `end` date, not a computed label

**Date:** 2026-08-17 (commit `32b59a5`, squashed with
`docs/decisions/2026-08-17-centralized-env-config.md`)

## Context

A design-review question ("is fiscal-year date arithmetic safe to
trust, and is there something in the data itself to lean on instead?")
surfaced a real latent bug in the original fix for bug #1 in the
structured-facts tool: `resolve_fiscal_period()` converted a caller-given
`period_end_date` into a `(fiscal_year, fiscal_period)` guess, then
matched entries against *that computed label* instead of the actual date
asked about.

## Decision

Replaced the resolve-then-match approach with `_pick_entry_by_end_date()`,
which filters entries directly on `entry["end"] == period_end_date`,
using duration buckets only to disambiguate a quarter figure from an
annual/YTD figure sharing the same end date. `resolve_fiscal_period()`
was deleted, not deprecated — its whole purpose was the intermediate
computation this fix removes, and it had no other callers.

## Why

Computing a second, independent label and matching on that instead of
the ground truth already in the response meant a wrong computation
wouldn't fail loudly — it would silently match a *different, real* entry
sharing the (wrong) label, exactly the failure mode bug #1 was
originally written to fix, reintroduced one layer down. Concretely
reproduced as a newly found bug: `resolve_fiscal_period` has no "FY"
case, so passing a company's own fiscal-year-end date computed
`fiscal_period="Q4"` and searched for a 10-Q-shaped entry that doesn't
exist for a company that doesn't tag standalone Q4 — silently returning
`None` for a valid annual-figure question. Added as a regression test
before fixing, confirmed failing under the old code.

`get_gross_margin()` simplified alongside it: both legs now receive
`period_end_date` directly and `get_metric()` matches each
independently, with the existing `period_end` equality check still
catching any real divergence between the two tags.

## Files touched

`xbrl_facts.py`.

## Verification

Full suite 137/137 (5 new tests, 3 stale `resolve_fiscal_period` tests
removed), no regressions.

## Related

`docs/decisions/2026-08-16-xbrl-structured-facts-tool.md` (the original
fix this supersedes), squashed alongside
`docs/decisions/2026-08-17-centralized-env-config.md` in the same
commit.
