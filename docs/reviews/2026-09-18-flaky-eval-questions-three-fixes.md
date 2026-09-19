# Review: flaky-eval-questions three-fix investigation

Plan: `docs/plans/2026-09-18-flaky-eval-questions-three-fixes.md`.
Three fixes to `agent.py` (Fix A, B) and a new `analyze_flakiness.py`
(Fix C); full suite before this diff: 686 passing (after the prior
session's chunking fix).

## Plan review (independent subagent, before implementation)

Two rounds, since Fix A's first draft was substantially redesigned
mid-review.

- **Round 1** confirmed the `aapl-operating-margin-q3fy2026` repro was
  real, verified `_calculation_as_result`'s text genuinely contains
  both operands in `_number_candidates()`-extractable form, and
  confirmed `verify_claims()` already receives `all_results` as a
  parameter — but found `[Blocking]` that mirroring
  `analyze_citation_gate.py`'s `load_rows()` verbatim for
  `analyze_flakiness.py` would crash on 33 of 112 real report files
  (bare top-level JSON lists, not the dict-wrapper shape), and
  `[Worth fixing]` that the original Fix A design (threading a new
  `calculate_operands` parameter through `_dispatch_tool_call` →
  `_run_agent_impl` → `verify_claims()`) would break 13 existing
  positional test call sites, proposing the `all_results`-filtering
  alternative instead. Both fixed before implementation began.
- **Round 2** (after redesigning Fix A around the `all_results` filter)
  found `[Blocking]` a live-execution-confirmed bug: `_calculation_as_result`'s
  text always ends with `"...operands from results [N] and [M])"`, and
  `_number_candidates()` has no bracket-stripping of its own, so the
  bracketed citation indices got misparsed as spurious operand values
  and then scale-broadened (3 → 3,000,000) by the caption-unit logic.
  Fixed with the same `_ANY_CITATION_BRACKET.sub()` pre-strip
  `verify_claims`'s own `answer_numbers` extraction already uses.

## Design discussion (mid-plan, before implementation)

User raised a `claim_type: "computed"` schema alternative. Investigated
and set aside — see the paired plan file's own section on this; the
prior art it pointed to was already substantially implemented via the
`calculate` tool's existing design, and the real gap was narrower than
the proposal assumed.

## Code review (independent, after implementation — `/code-review medium`)

One finder angle produced a single, high-value, empirically-confirmed
finding:

- `[Fixed — blocking]` **Fix A's exemption pool included the
  calculate result, not just its operands.** `agent.py`'s
  `calculated_candidates` extracted every number from a `"calculated"`
  entry's *full* text via `_number_candidates()`, which includes the
  derived RESULT value (e.g. 32.6 percent) alongside the two operands.
  Confirmed live by direct call: `verify_claims([], results, "q", "The
  operating margin was 32.6%.")` returned `[]` — a completely
  unclaimed, uncited 32.6% assertion passed with zero warnings,
  directly violating this project's "every numeric claim must trace to
  a specific filing + section, or the agent refuses" principle. Fixed
  by scoping extraction to only the text before the calculated entry's
  own `"="` (`_calculation_as_result` always renders
  `"{operands expression} = {result} (computed value...)"`, so
  everything before `=` is provably operand-only). A new regression
  test, `test_verify_claims_calculate_entry_exemption_does_not_cover_the_result_itself`,
  proves the fix and was confirmed non-tautological (fails against a
  simulated reversion to the old full-text-extraction logic).

## Follow-up focused review (after the result-exemption fix)

Verified by direct execution rather than reasoning alone:
`_calculation_as_result`'s three operation branches (percent_change,
percent_of, generic) all render exactly one `"="`, confirmed by
stress-testing with negative/tiny/huge/percent-unit operands;
`CALCULATE_TOOL_SCHEMA`'s fixed operation enum and schema validation
guarantee no operand/operation text could ever inject a second `"="`
or leak the result before it; the new regression test was confirmed
to genuinely discriminate (fails under a simulated pre-fix
implementation, not just tautologically green); no further
counter-example found despite deliberate attempts. Docstring's
description of the fix and its residual risk (the pre-existing,
still-accepted `question_numbers`-style collision risk, now narrower
in scope than before this fix) confirmed accurate against the current
code.

## Live verification

- **Fix A**: `eval_harness.py --backend gemini --ids
  aapl-operating-margin-q3fy2026` run 3 times
  (`eval/eval_results/20260919T00{2030,2043,2055}Z.json`). All 3
  passed; one produced the exact confirmed-bug pattern verbatim
  ("computed as operating income of $35,695 million divided by total
  net sales of $109,417 million") and passed cleanly with
  `citation_warnings: []` — a genuine live confirmation against real
  model output, not just a synthetic unit-test construction. Re-run
  once more after the result-exemption fix
  (`20260919T004319Z.json`) — still passes (this particular run didn't
  reproduce the inline-computation phrasing, but the fix only tightens
  the exemption, never loosens it, so this is expected and not a
  concern).
- **Fix B**: the full-baseline run's `nvda-crm-revenue-comparison`
  failure (see below) incidentally exercised a real
  `quote_not_found`-shaped failure on the structured-claims path, and
  its saved `citation_warning_details` now includes the actual claimed
  quote text for all three flagged claims — confirming the new field
  captures real data, not just unit-test fixtures. This also surfaced
  a genuinely new, previously-invisible finding, logged to
  `BACKLOG.md`: the model's "quote" for a `get_financial_fact`/
  `calculate` result includes `_format_results_block`'s own
  display-time citation header (`"[1] NVDA 10-Q
  (reportDate=...)\n..."`), which is never part of the underlying
  `all_results[n-1]["text"]` the quote is checked against — a likely
  contributing cause to at least this instance's `quote_not_found`, and
  possibly a recurring factor in `msft-segment-revenue-comparison-q3fy2026`'s
  long-unresolved history (not confirmed there specifically, so not
  claimed as such).
- **Fix C**: `analyze_flakiness.py` run against the full
  `eval/eval_results/*.json` history (all 116 files, including the 33
  bare-list-format ones its own loader was built to tolerate) —
  produced a sane, quota-excluded ranked table matching this
  investigation's earlier ad hoc manual findings.
- **Full 47-question Gemini baseline**: 40/47
  (`eval/eval_results/20260919T003333Z.json`), following the
  result-exemption fix. Diffed against the prior session's confirmed
  41/47 baseline (`20260918T194825Z.json`): 4 new failures
  (`pltr-dividend-2019-refusal`, `nvda-gross-margin-fy26`,
  `nvda-crm-revenue-comparison`, `nvda-rd-expense-q4fy26-refusal`), 3
  new passes (`aapl-msft-employee-comparison`,
  `pltr-government-contract-risk`, `pltr-inventory-turnover-fy2025-refusal`).
  Checked each of the 4 new failures against `analyze_flakiness.py`'s
  own historical pass-rate output (all show 41-50 historical runs at
  63-82% pass rates, well-established pre-existing flakiness, not
  first-time failures) and against its actual failure reason (2 pure
  judge-strictness cases matching the already-documented non-determinism
  pattern; 2 genuine citation-gate refusals on ordinary uncited/
  mismatched numbers, unconnected to either fix's new code paths).
  `aapl-operating-margin-q3fy2026` (Fix A's direct target) passes in
  this baseline too.

## Outcome

Shipped: Fix A (`calculated_candidates` exemption, correctly scoped to
operands only), Fix B (`quote` field on `CitationWarning`), Fix C
(`analyze_flakiness.py`), 15 new/updated tests, this plan/review/
decision triple. Full suite: 701 passing. `ruff`/`pyright` scoped to
changed files: zero new violations (pyright's `tests/test_agent.py`
count confirmed unchanged at its pre-existing 26-error baseline after
one incidental new-code type error was fixed —
`_fake_result`'s `chunk_index` parameter widened from inferred `int`
to `int | str` to match its real usage with `"calculated"`).

Still open, filed to `BACKLOG.md`:
- The prose-fallback path's own quote/window-capture gap (Fix B's
  explicitly out-of-scope finding).
- The newly-found citation-header-in-quote pattern (this review's own
  live-verification finding above).

Review loop closed after 2 rounds (code-review skill + one focused
follow-up), the second finding nothing further — within this project's
two-round cap.
