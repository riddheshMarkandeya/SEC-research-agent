# Turn flaky eval questions into solid passes: three targeted fixes

**Date:** 2026-09-18

## Context

Following the 2026-09-17 chunking fix (41/47 live-confirmed), the next
request was to investigate the eval suite's flaky questions broadly and
find what's fixable. A three-round investigation (full historical
pass-rate scan, BACKLOG/decision-history cross-reference, and a
deep-dive into a promising `gate_withheld_would_have_passed: True`
cluster) narrowed an initially-overclaimed "widespread pattern" down to
one clean, well-evidenced bug — `aapl-operating-margin-q3fy2026`'s
`calculate`-tool operands weren't recognized as already-grounded when
restated in the answer's readability recap — plus two supporting gaps:
`CitationWarning` never captured the actual failing quote text (the
explicit blocker on `msft-segment-revenue-comparison-q3fy2026`'s
month-long unresolved history), and nothing distinguished Gemini
quota-exhaustion artifacts from real agent failures in historical
pass-rate analysis.

## Decision

Three fixes, all in `agent.py` except the third:

1. **Fix A**: `verify_claims()`'s coverage check now recognizes a
   successful `calculate` call's own operands (extracted from its
   synthetic `all_results` entry, scoped to only the text before that
   entry's own `"="` so the derived result itself still requires its
   own claim) as already-grounded, mirroring the existing
   `question_numbers` exemption pattern.
2. **Fix B**: `CitationWarning` gained a `quote` field, populated at
   the structured-claims path's quote-related checks.
3. **Fix C**: a new `analyze_flakiness.py` script ranks questions by
   historical pass rate while excluding Gemini-quota/network-error rows
   from the count.

## Why

Full reasoning, including a design alternative (`claim_type: "computed"`)
considered and set aside, and two real bugs a total of three
independent review rounds caught and fixed before/after implementation,
is in the paired plan and review files — not re-derived here.

## Files touched

- `agent.py` — `CitationWarning` (new `quote` field), `verify_claims`,
  `_verify_numeric_claim`, `_verify_qualitative_claim`.
- `tests/test_agent.py` — 15 new/updated tests; `_fake_result`'s
  `chunk_index` type widened to `int | str`.
- `analyze_flakiness.py`, `tests/test_analyze_flakiness.py` — new.
- `docs/plans/2026-09-18-flaky-eval-questions-three-fixes.md`,
  `docs/reviews/2026-09-18-flaky-eval-questions-three-fixes.md` —
  paired plan/review.
- `PROJECT_INDEX.md`, `BACKLOG.md` — updated per the documentation
  system.

## Verification

Full detail in the paired review file. Summary: full test suite 701
passing; `ruff`/`pyright` zero new violations; Fix A confirmed live
against Gemini (a real run reproduced the exact bug pattern and passed
cleanly); Fix B confirmed live (a real citation-gate failure's saved
report now shows the actual claimed quote text, immediately surfacing a
new finding — see `BACKLOG.md`); Fix C confirmed against the full
116-file historical report set. Full 47-question Gemini baseline:
40/47 — down from the prior session's 41/47, but every diff checked
individually against `analyze_flakiness.py`'s own historical pass-rate
output and confirmed to be pre-existing, well-documented flakiness
(41-50 historical runs each, 63-82% pass rates), not a regression from
either fix; `aapl-operating-margin-q3fy2026` (Fix A's direct target)
passes in this baseline.

## Related

Plan: `docs/plans/2026-09-18-flaky-eval-questions-three-fixes.md`.
Review: `docs/reviews/2026-09-18-flaky-eval-questions-three-fixes.md`.
Follows `docs/decisions/2026-09-17-fix-orphaned-table-overlap-chunking.md`.
Distinct from the still-open `BACKLOG.md` item on `nvda-gross-margin-fy26`'s
second-claim-quote-mismatch mechanism (line ~205 as of this writing) —
a different, more narrowly-scoped bug than the one this decision fixes.
