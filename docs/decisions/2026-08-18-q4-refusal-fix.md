# Q4-refusal fix: tool message explains *why*, not just *that*, data is missing

**Date:** 2026-08-18 (commit `a055f1a`, "Fix Q4-refusal fabrication: tool
message now explains why, not just that, Q4 data is missing")

## Context

`nvda-rd-expense-q4fy26-refusal` had been flaky all session (fabricated
under rule 8, flaky under the reverted retry loop, then failed
differently under Gemini). Root-caused via systematic debugging instead
of another prompt tweak.

## Decision

Confirmed root cause directly: `get_metric('NVDA', 'rd_expense',
fiscal_year=2026, fiscal_period='Q4')` returns `None` — no company files
a standalone Q4 report (only Q1-Q3 get a 10-Q; Q4 exists only implicitly
as `FY − Q1 − Q2 − Q3`). The existing "no structured data found... try
search_filings instead" fallback message didn't say *why*, so the model
trusted a noisy follow-up search and fabricated a wrong-quarter number.
Fix: `_format_no_fact_message()`/`_format_no_comparison_message()` (new
pure helpers, extracted for testability) append a
`_Q4_NOT_DISCLOSED_HINT` whenever `fiscal_period == "Q4"`, explaining the
structural gap and instructing the model not to state any figure.

## Why

The hint needed two live iterations to actually land: v1 allowed
mentioning the annual figure as context — 2/3 clean, but the third run
fabricated a wrong FY figure anyway. v2 dropped the invitation but kept
a soft "don't estimate" — 3/5 clean, still volunteered the annual total
and fabricated once. v3 forbids stating *any* dollar amount at all
(mentioning the annual figure stays optional per grading criteria, so a
hard ban stays compliant) — 5/5 clean, and the model now answers
directly from the tool hint without even needing a follow-up search.

## Files touched

`agent.py` (`_format_no_fact_message`, `_format_no_comparison_message`).

## Verification

173/173 unit tests (5 new). Full 21-question eval: 18/21, target question
now PASS; the 3 remaining failures are the pre-existing local-model
comparison/tax-rate flakiness already diagnosed by the Gemini spike.

## Related

`docs/decisions/2026-08-18-gemini-cloud-model-spike.md` (surfaced this
question's flakiness under a second backend),
`docs/decisions/2026-08-16-xbrl-structured-facts-tool.md` (the original
Q4 limitation this closes).
