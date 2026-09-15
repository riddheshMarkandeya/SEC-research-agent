# Formula registry: `operating_margin`, `net_margin`, `yoy_growth`

**Date:** 2026-08-18 (commit `583c27a`, "Add formula registry:
operating_margin, net_margin, yoy_growth")

## Context

The previously-deferred formula registry was justified by concrete,
observed evidence rather than built speculatively. Growing the eval set
16→21 (see `docs/decisions/2026-08-19-eval-growth-round4-financebench-3-5.md`
for the sibling round) deliberately included two questions
(`aapl-operating-margin-q3fy2026`, `aapl-revenue-growth-q3fy2026`) the
system couldn't yet answer correctly, specifically to generate evidence
for this decision rather than to hunt for bugs. Both surfaced the same
underlying problem in two different runs:
`aapl-operating-margin-q3fy2026` once returned a flatly fabricated
**50.1%** cited as if directly retrieved, and on a separate live repro
instead self-computed **32.68%** (close to the correct 32.6%) by
retrieving operating income and revenue as separate dollar figures and
dividing them in its own reasoning text — a real violation of rule 3
("don't combine or infer numbers"), just one that happened to land close
to correct.  `aapl-revenue-growth-q3fy2026` technically PASSED (16.27%
against expected 16.4%) for the identical underlying reason: the model
computed the percentage itself from two retrieved dollar figures and got
its own arithmetic slightly wrong (16.27% vs. the mathematically correct
~16.36% from its own stated inputs) — the eval's numeric tolerance was
loose enough to mask the rule violation as a pass.

## Decision

Built the formula registry: `get_operating_margin`/`get_net_margin` (+
all-companies versions) and `get_yoy_growth`, exposed as tool arguments
on `get_financial_fact`. `_compute_ratio_metric()` extracted from
`get_gross_margin()`'s body to avoid three near-identical margin
functions.

## Why

`get_yoy_growth()` does zero date arithmetic by design — the prior
comparable period is found by reading the CURRENT period's own
SEC-assigned `fiscal_year` back off `get_metric()`'s result and asking
for `fiscal_year - 1` at the same `fiscal_period`, avoiding the exact bug
class `_pick_entry_by_end_date()` already fixed once. Deliberately scoped
`yoy_growth` to raw tagged metrics only, not margin ratios (no evidence
"growth of a percentage" is a real question shape), rejected at the
`agent.py` boundary.

This is concrete, not hypothetical, evidence for two things: (1) the
formula-registry idea solves a real problem — the model reaches for
self-computation on its own the moment it has retrievable raw
ingredients, and doesn't do so reliably; (2) the eval harness's numeric
tolerance can mask a rule-3 violation as a clean pass — fixed separately
the same session, see the citation-gate decision file below.

## Files touched

`xbrl_facts.py` (`_compute_ratio_metric`, margin functions, `yoy_growth`),
`agent.py` (`MARGIN_METRIC_FUNCTIONS` tool-dispatch wiring).

## Verification

Both target questions now PASS with exact values (32.6%, 16.4%) via a
single clean tool call each. Full suite 168/168. The Q4-refusal question
still correctly refuses without fabricating.

## Related

`docs/decisions/2026-08-18-citation-verification-wired-into-eval-gate.md`
(the tolerance-masking fix motivated by the same evidence),
`docs/decisions/2026-08-18-formulas-module-split.md` (extraction into its
own module once this grew), `docs/decisions/2026-08-25-formula-registry-roa-turnover-cash.md`
(next extension).
