# Fix the citation-header-in-quote grounding bug

**Date:** 2026-09-19

## Context

The prior session's Fix B (capturing the model's actual claimed quote
text in `CitationWarning`) immediately surfaced a new, previously-
invisible finding on the very next live baseline run:
`nvda-crm-revenue-comparison` was refused despite 3 genuinely-correct
values. Root-caused precisely: the model's quote for a
`get_financial_fact`/`calculate` result sometimes includes
`_format_results_block`'s own display-time citation header (e.g. `"[1]
NVDA 10-Q (reportDate=2026-04-26)\n..."`), which is never part of the
underlying source text the quote is grounded against — confirmed by
direct execution that this drags coverage to 63%, well under the 90%
threshold `_quote_matches()` requires.

## Decision

`_verify_one_claim` now strips a claim's quote of its own citation
index's header (reconstructed from `all_results` metadata via a new
shared `_citation_header` helper, exact-match only) before any
grounding check runs, while still recording the model's raw,
unstripped quote on any resulting `CitationWarning` — via a new
`_ClaimQuote(raw, grounding)` pairing threaded through
`_verify_numeric_claim`/`_verify_qualitative_claim`.

## Why

Full reasoning — including two real issues an independent code-review
round caught and fixed before this was considered done (a raw-quote-
preservation regression against the prior session's own Fix B, and a
resulting argument-count violation) — is in the paired plan and review
files, not re-derived here.

## Files touched

- `agent.py` — new `_citation_header`, `_strip_citation_header`,
  `_ClaimQuote`; `_format_results_block` (refactored to the shared
  helper); `_verify_one_claim`, `_verify_numeric_claim`,
  `_verify_qualitative_claim`.
- `tests/test_agent.py` — 5 new tests.
- `docs/plans/2026-09-19-citation-header-in-quote-fix.md`,
  `docs/reviews/2026-09-19-citation-header-in-quote-fix.md` — paired
  plan/review.
- `PROJECT_INDEX.md`, `BACKLOG.md` — updated per the documentation
  system.

## Verification

Full detail in the paired review file. Summary: full test suite 707
passing; `ruff`/`pyright` back to the exact pre-existing baseline;
`nvda-crm-revenue-comparison` (the confirmed repro) re-run 3 times live
against Gemini, 3/3 passed. `msft-segment-revenue-comparison-q3fy2026`
re-run 3 times as a secondary, not-guaranteed check — still failed for
3 different reasons, none attributable to this fix either way since
judged-type questions don't get citation-gate evidence captured in the
saved report; treated as expected pre-existing chronic flakiness, not
evidence against the fix.

## Related

Plan: `docs/plans/2026-09-19-citation-header-in-quote-fix.md`. Review:
`docs/reviews/2026-09-19-citation-header-in-quote-fix.md`. Follows
`docs/decisions/2026-09-18-flaky-eval-questions-three-fixes.md`, whose
Fix B is what surfaced this finding. Resolves the
`[bug (latent), Med, Standard]` `BACKLOG.md` item from that session.
