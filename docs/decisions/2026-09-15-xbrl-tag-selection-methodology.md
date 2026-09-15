# XBRL metric-tag selection: verify the latest entry, not just the status code

**Date:** 2026-09-15

## Context

`docs/decisions/2026-08-16-xbrl-structured-facts-tool.md` documents,
tersely, that the original default revenue tag (`Revenues`) was wrong.
That entry doesn't capture the actual investigation — how the mistake
was found, why the fix generalizes, or the five later metrics
(`GrossProfit`, `OperatingIncomeLoss`, `Assets`,
`CashAndCashEquivalentsAtCarryingValue`, `InventoryNet`) added to
`DEFAULT_METRIC_TAGS` since, each individually re-verified against the
same lesson. That verification work lived only as inline comment
narration in `xbrl_facts.py` until this file.

## Decision

**The core lesson**: an SEC `companyconcept` endpoint returning HTTP
200 for a (company, tag) pair only proves the company has *ever* tagged
that concept — not that it still tags it in *recent* filings. A
tag-selection check must read each company's actual latest entry, not
just the status code.

**How the revenue tag mistake was found**: the first pass checked only
status codes and defaulted `"revenue"` → `"Revenues"`, since that tag
returned 200 for AAPL/MSFT/NVDA/CRM, with PLTR carved out as the sole
override (its `"Revenues"` 404s). This looked right until a live
comparison-question test asked for CRM's most recent quarter and
silently returned nothing. Checking each company's actual latest entry
(not just the status code) showed AAPL's `"Revenues"` data stops in
2018 and MSFT's in 2011 — both switched years ago to the more specific
ASC 606 tag (`RevenueFromContractWithCustomerExcludingAssessedTax`).
CRM's most recent quarter has the same gap. NVDA is the true outlier:
it's the only one of the five still actively using plain `"Revenues"`
through its latest 2026 filings — and NVDA's own historical use of the
ASC 606 tag stopped in 2022, so ASC 606 can't be a universal default
either. No single tag works for all five covered companies, which is
why `DEFAULT_METRIC_TAGS["revenue"]` is the ASC 606 tag with NVDA as
the sole entry in a separate `METRIC_TAG_OVERRIDES` map, rather than
one shared default.

**The same methodology, applied to every metric added since**, each
checked by reading the actual latest entry per company, not the status
code alone:
- `GrossProfit` (enables `gross_margin` as a tool-computed ratio) and
  `OperatingIncomeLoss` (enables `operating_margin`): all five
  companies tag both directly through their latest filings — no
  overrides needed.
- `Assets` and `CashAndCashEquivalentsAtCarryingValue` (added to fix
  `nvda-total-assets-q1fy27`/`aapl-cash-equivalents-q3fy2026`, which
  turned out to be retrieval/attribution failures for values that were
  actually clean structured facts): same check, all five clean for
  both.
- `InventoryNet` (added to fix
  `pltr-inventory-turnover-fy2025-refusal`): clean recent entries for
  AAPL/MSFT/NVDA, but Palantir *and* Salesforce both 404 — never tag it
  at all. This is deliberately **not** treated as a data-quality gap to
  paper over with an override: it's a real structural fact about those
  companies' business models (software/services, no physical inventory
  to report). `is_metric_tagged()` surfaces this distinction (never
  tagged at all vs. not tagged for this one period) to the model
  instead of collapsing both into one ambiguous "no data."

## Why

The "200 ≠ still current" failure mode is specifically dangerous
because it fails *quietly*: a wrong default tag doesn't crash or throw
a 404, it just returns real, valid-looking historical data that's
years out of date for the company actually asked about, which is much
harder to notice than an outright error. Re-running the same
per-company latest-entry check for every metric added afterward, rather
than assuming the revenue-tag lesson was a one-time fix, is what caught
`InventoryNet`'s different-but-adjacent case (a real, permanent 404
rather than a stale-tag mismatch) before it could be misdiagnosed as
another instance of the same bug and "fixed" with an incorrect
override.

## Files touched

`xbrl_facts.py` (`DEFAULT_METRIC_TAGS`, `METRIC_TAG_OVERRIDES`,
`is_metric_tagged()`) — this file only documents work already shipped
across several earlier commits; no code changed here.

## Verification

Each metric's tag was checked against real fetched `companyconcept`
responses for all 5 covered companies (AAPL/MSFT/NVDA/CRM/PLTR), not
assumed from documentation or status codes alone — see
`docs/decisions/2026-08-16-xbrl-structured-facts-tool.md` and
`docs/decisions/2026-08-19-fixing-6-accumulated-eval-findings.md` for
the paired eval re-runs that motivated the later additions.

## Related

`docs/decisions/2026-08-16-xbrl-structured-facts-tool.md` (the original
revenue-tag mistake and fix), `docs/decisions/2026-08-19-fixing-6-accumulated-eval-findings.md`
(`total_assets`/`cash_and_equivalents`/`inventory` additions),
`docs/decisions/2026-09-15-comment-audit-round3.md` (this file was
extracted from `xbrl_facts.py`'s own comments as part of that round).
