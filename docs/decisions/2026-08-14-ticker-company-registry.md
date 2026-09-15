# Shared ticker/company registry (`companies.py` + `companies.json`)

**Date:** 2026-08-14 (commit `944e200`, "Extract ticker/company registry
to companies.json")

## Context

`agent.py`'s ticker→name dict and `edgar_ingest.py`'s ticker→CIK dict
were two separately-hardcoded copies of the same 5-company list, both
under the identically-named `COMPANIES` variable — which made the
duplication easy to miss since nothing looked wrong at either call site.

## Decision

Single source of truth: `companies.json` holds
`{ticker: {name, cik, fiscal_year_end_month}}` for AAPL, MSFT, NVDA, CRM,
PLTR. `companies.py`'s `load_companies()` reads it fresh on every call
(no caching — the file is small and rarely changes, and not caching
means an edit takes effect without restarting anything). Both
`edgar_ingest.py` and `agent.py` now import `load_companies()` instead
of hardcoding their own list.

## Why

`fiscal_year_end_month` (added specifically to support `period_labels.py`,
see that decision file) carries a real, if currently low-probability,
assumption worth flagging: it assumes each company's fiscal year end is
fixed forever. A company *can* change it via a transition-period filing;
if that happened here without updating this field, `period_labels.py`
would silently compute a confidently WRONG period label and bake it into
the retrieval index — worse than no label at all. For the 5 companies
over the ~15-month window of filings actually ingested this is a
non-issue (all 5 have long-stable fiscal calendars) —
`tests/manual/verify_period_labels.py` checks this assumption against
real evidence rather than trusting it blindly; re-run it after adding a
company or pulling in older filings.

## Files touched

`companies.py` (new), `companies.json` (new), `edgar_ingest.py`,
`agent.py` (both switched from hardcoded dicts to `load_companies()`).

## Verification

Unit tests for `load_companies()`; full suite green after the switch.

## Related

`docs/decisions/2026-08-16-fiscal-period-labels-tried-and-reverted.md`
(the feature this registry's `fiscal_year_end_month` field was added
for).
