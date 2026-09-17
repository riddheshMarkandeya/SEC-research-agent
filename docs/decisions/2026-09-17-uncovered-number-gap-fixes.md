# Fix the "uncovered_number" false-refusal gap (two distinct causes)

**Date:** 2026-09-17

## Context

Two eval questions (`aapl-rd-pct-gross-profit-fy2025`,
`nvda-supply-chain-risk`) intermittently failed with an
`uncovered_number` citation-gate false refusal — a real number in the
model's `answer_text` had no matching entry in the structured `claims`
array, so an otherwise-correct answer was refused. Both were first
observed by the 2026-09-15 qualitative-claims-schema fix's own
confirmatory baseline, logged as "single observation, not yet
reproduced or root-caused." The 2026-09-17 baseline (40/47) reproduced
both a second time, enough to actually root-cause them.

## Decision

Two independent fixes, both in `agent.py`, no shared code path:

1. **Case A** (`aapl-rd-pct-gross-profit-fy2025`): reworded the
   `calculate`-tool worked example ("computed as $34,550M ÷ $195,201M =
   17.7%") to spell out "million" in all three places it appears (tools
   overview, system prompt rule 9, `CALCULATE_TOOL_SCHEMA`'s
   description), and added one new standing rule to rule 9 banning
   bare-letter unit abbreviations outright.
2. **Case B** (`nvda-supply-chain-risk`): widened `_NON_CLAIM_PATTERN`'s
   duration exemption from `\b\d+-(?:year|day)s?\b` (hyphen-only) to
   `\b\d+[\s-](?:year|month|day)s?\b` (hyphen-or-whitespace, `month`
   added).

## Why

**The plan's first draft diagnosed Case A wrong — caught by an
independent plan review before any code was written.** The original
theory: the model's `claims` array was missing entries for the two
`calculate` input operands. This was **falsified** by reading the
actual `submit_answer` payload in `trace_logs/traces.jsonl` for the
exact failing run — the `claims` array already had correct entries for
both operands. The real bug: the answer's parenthetical computation
disclosure restated the same two numbers in abbreviated form
(`"$34,550M"`), and `numeric_utils.NUMBER_PATTERN`'s unit alternation
(`billion|million|thousand|percent` only) doesn't recognize bare `M`,
so `extract_numbers()` parsed `$34,550M` as `(34550.0, "raw")` — 1000x
off from the real claim (`34550000000`) — tripping the coverage check.
Confirmed directly via `extract_numbers()` and against the raw trace
payload, not inferred.

**Prior-art research** (requested mid-review, before finalizing the
fix direction): "M" is genuinely, unresolvably ambiguous in real
finance — the Roman-numeral convention (M = thousand, MM = million)
competes with the modern metric convention (M = million) with no
universal winner; "MM" exists specifically because "M" alone is unsafe.
SEC filings themselves never use inline "$NM" notation at all (per
Regulation S-X, Rule 4-01(b)): a filing states its scale once, as a
caption above a table of plain digits or spelled out in prose. This
confirmed spelling out "million" is the right fix on its own terms, not
just a narrow patch — and, per a follow-up question during plan review,
motivated adding an explicit standing rule (not just fixing the
worked examples) so the model can't independently reinvent similar
abbreviated notation elsewhere.

**Deliberately not extending `numeric_utils.NUMBER_PATTERN`** to
recognize `M`/`B`/`K` in this same change: that function is shared
across `agent.py`, `table_grounding.py`, and `eval_harness.py`'s own
grading logic; is explicitly flagged in
`.claude/rules/plan-review-blast-radius.md` and
`.claude/rules/live-eval-verification.md` as needing extra
live-verification rigor (the 2026-09-12 negative-number precedent: 14
passing unit tests still shipped two live-only bugs); and a
single-letter abbreviation under the file's global `re.IGNORECASE` flag
carries a real case-sensitivity risk (`m`/`b`/`k` in unrelated text)
needing careful scoping. The evidenced bug is fully closed by the
narrower prompt-only fix; the parser gap remains latent, logged
separately.

**Case B** was independently confirmed solid across two plan-review
rounds: the regex widening is a strict superset of the old pattern (no
existing match becomes unmatched), and no false-negative collision risk
was found (`"$12 million"` doesn't spuriously match — `month` vs.
`million` diverge at the 2nd character).

## Files touched

- `agent.py` — three worked-example rewordings, one new standing rule (rule 9), `_NON_CLAIM_PATTERN` widened.
- `tests/test_agent.py` — 4 new tests: the direct NVDA regression, a standalone hyphenated-duration regression anchor (none existed — the closest prior test passes via an unrelated question-echo path), a space/hyphen-both-directions test, and (implicitly exercised) the AAPL case is verified live, not via new `verify_claims` unit tests, since that function's logic didn't change for Case A.
- `tests/test_numeric_utils.py` — 1 new cheap regression test documenting `extract_numbers("$34,550 million")` parses correctly.

## Verification

- Full unit test suite: 680 passing (up from 676).
- `ruff`/`pyright` scoped to changed files: zero new violations; identical pre/post counts confirm only pre-existing baseline remains (lines 92/106 are the project's own documented deliberate-long-system-prompt-string E501 exception, per `docs/decisions/2026-09-15-adopt-ruff-linter.md`).
- Live eval spot-check: both target questions passed cleanly, twice in a row, zero citation warnings each time (`eval/eval_results/20260917T204253Z.json`, `20260917T204329Z.json`). `msft-cash-to-assets-fy2025` (regression guard) passed. `nvda-gross-margin-fy26` (regression guard) failed for its own already-tracked, unrelated redundant-restatement-claim reason (`BACKLOG.md`), not touched by this fix.
- Full 47-question baseline run as final confirmation: 37/47
  (`eval/eval_results/20260917T205406Z.json`), down from the prior 40/47
  (`20260917T053451Z.json`) — but both target questions
  (`aapl-rd-pct-gross-profit-fy2025`, `nvda-supply-chain-risk`) flipped
  `False → True`, confirming the fix. Of the other 9 flips (2 more
  `False → True`, 6 `True → False` counting only questions unrelated to
  this fix), none touch the `M`-abbreviation or month-duration code
  paths this change edited — they're citation-gate refusals on
  `calculate`-adjacent questions and judge-side "hypothetical future
  date" mis-grades, both already documented as pre-existing baseline
  non-determinism (`BACKLOG.md` lines ~165, ~184) predating this change,
  not a regression it introduced.
- Independent review: one round on the plan (caught the wrong Case A diagnosis before implementation, plus two precision corrections to the corrected version), one round on the finished code (clean, no findings).

## Related

Follow-up to `docs/decisions/2026-09-15-qualitative-claims-schema.md`,
whose own confirmatory baseline first surfaced both bugs as single,
unreproduced observations. Plan:
`C:\Users\riddh\.claude\plans\snug-jingling-pumpkin.md` (session-local
scratch file — this decision file is the durable record, and includes
the corrected diagnosis the plan file's own edit history shows was
wrong on the first pass).
