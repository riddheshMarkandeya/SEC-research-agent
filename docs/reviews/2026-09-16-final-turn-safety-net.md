# Review: Final-turn safety net (MAX_TOOL_ITERATIONS zero-slack fix)

Plan: `C:\Users\riddh\.claude\plans\snug-jingling-pumpkin.md` (session-local
plan-mode scratch file; the durable record is
`docs/decisions/2026-09-16-final-turn-safety-net.md`). Adds a reserved,
Gemini-only, single-shot final round trip to `_run_agent_impl` when the
dispatch budget is exhausted but the model still has pending tool calls.
Test suite after this diff: 669 passing, including 8 new tests for this
change (a pre-diff count wasn't separately captured this session).

## Independent plan review (before implementation)

Per `design-before-building`'s Substantial-tier requirement, a
freshly-spawned subagent reviewed the plan itself before any code was
written. It found the first draft's core branch called `send_followup`
(a bare text turn) at a point where the model's current turn always has
real, undispatched tool calls still pending in the chat history —
exactly the "dangling function call followed by a bare user turn" shape
already documented elsewhere in this file as historically producing a
Gemini 400. `[Fixed]` — corrected to `send_tool_results` (closing out
each pending call with a synthetic result) before any code was written,
so the bug was never actually run against a live API. It also flagged
that the mechanism should be backend-gated like its two siblings rather
than left universal. `[Fixed]` — added `_FINAL_TURN_BACKENDS =
{"gemini"}`.

## Pass 1 — correctness and CLAUDE.md compliance (self, medium effort)

Diff reviewed line-by-line against `_run_agent_impl`'s existing control
flow (the `submit is not None and (not other or calls_made >=
MAX_TOOL_ITERATIONS)` branch, the `if not turn.tool_calls:` branch, and
the loop's own comment block documenting the dangling-call risk). No
findings — the new branch's reachability (`submit is None` and
`turn.tool_calls` non-empty) was traced and confirmed correct, matching
the plan exactly. `[Verified, no fix needed]`.

## Pass 2 — architecture, design, performance, refactoring + documentation/comment hygiene (fresh subagent, no memory of the implementation session)

Given the diff cold plus the decision doc and project conventions.
Confirmed correct: the new branch's placement/structure fits
`_run_agent_impl`'s existing sibling mechanisms
(`_should_retry_for_citations`/`forced_submit_attempted`); the
`send_tool_results`-not-`send_followup` fix is right, independently
re-derived from the control flow rather than taken on faith; `agent.py`
and the new manual script are clean under `ruff`/`pyright` scoped to the
diff's own lines (re-run independently, not just trusted from the
decision doc); comments are self-contained per this project's revoked-
pointer-convention rule; `BACKLOG.md`'s closed-item removal and new
items follow the tagging convention with no adjacent-line corruption;
`PROJECT_INDEX.md`'s new entry matches the existing format and is
correctly newest-first; the new eval result JSON substantiates the
decision doc's Verification narrative rather than being fabricated.

Two findings, both documentation/lint hygiene, neither affecting runtime
correctness:

1. `tests/test_agent.py` (two section-header comments) — an unfilled
   `<date>` placeholder instead of the actual `2026-09-16` date in the
   decision-file reference. `[Fixed]`.
2. `tests/test_agent.py:2977` — a newly-added line at 121 characters, one
   over ruff's 120-char limit; had slipped past the scoped ruff run
   because it was added in a later edit (the third affected test, found
   only after the first ruff pass) than when that check was run.
   `[Fixed]` — shortened the line; re-ran ruff scoped to all three
   changed files to confirm no other new-in-diff violations exist.

## Live verification

`tests/manual/verify_final_turn_safety_net.py` (new): run before the fix
(reproduced the generic-timeout bug on both refusal questions on a
retry — live model non-determinism meant the first attempt didn't
reproduce it, consistent with this project's prior documented history on
these exact questions); run after the fix (2 full runs + 2 ranking-only
reruns): both refusal questions reliably got a real submission instead
of the generic timeout, and the ranking question found CRM and produced
a correctly-grounded answer in every post-fix run (the CRM
fiscal-year-lookup bug didn't trigger in any of them, so the
grounded-but-incomplete risk case wasn't directly exercised — recorded
as an open item in the decision doc and `BACKLOG.md`, not claimed as
resolved).

Targeted `eval_harness.py --backend gemini --ids ...` (8 questions):
`pltr-inventory-turnover-fy2025-refusal` now passes cleanly (this fix's
direct target). `nvda-rd-expense-q4fy26-refusal` no longer hits the
generic timeout but still fails on judge strictness about explicit
refusal phrasing — unrelated, pre-existing, not touched by this change.
`five-company-operating-margin-ranking-fy2025` refused via the
unmodified citation gate on an unrelated quote-matching gap, not a
confidently-wrong ranking. `aapl-msft-employee-comparison` failed once;
a targeted verbose rerun confirmed the new branch never fired (5 round
trips total, nowhere near the budget boundary) and the question passed
cleanly on rerun — ordinary live-model non-determinism in the
pre-existing citation-retry path, not a regression. The other 4
comparison questions passed on the first try.

Full 47-question baseline: **39/47**, up from the prior 37/47 baseline
(net +2, exactly the 2 target questions, zero net regressions). Both
`nvda-rd-expense-q4fy26-refusal` and `pltr-inventory-turnover-fy2025-refusal`
now pass cleanly. `five-company-operating-margin-ranking-fy2025` (the
risk case) also passed, correctly naming Salesforce/CRM as lowest at
~20% with no confidently-wrong answer — the CRM fiscal-year-lookup bug
happened not to trigger this run, so this doesn't fully close the
residual risk noted below, but it's a clean positive data point. 4 of
the 5 "must not regress" comparison questions passed;
`aapl-msft-tax-rate-comparison` failed via an ordinary citation-gate
refusal unrelated to the budget (the new branch's call pattern wasn't
involved), consistent with this project's already-documented citation-
gate non-determinism.

## Outcome

Shipped: `_FINAL_TURN_BACKENDS`, `_should_force_final_submit`,
`_FINAL_TURN_SUBMIT_MESSAGE`, `final_turn_attempted`, and the new loop
branch in `agent.py`; new/updated tests in `tests/test_agent.py`; new
`tests/manual/verify_final_turn_safety_net.py`. Both review passes found
only minor documentation/lint issues, both fixed in the same round — the
review loop closed clean (no second round needed). Two residual open
items filed to `BACKLOG.md` under "From the 2026-09-16
final-turn-safety-net fix": the CRM-shaped grounded-but-incomplete risk
(mitigated by message wording, not directly exercised live) and
extending the mechanism to Ollama (deliberately deferred, no live
evidence yet). Final test-suite count: 669 passing. Full 47-question
Gemini baseline: 39/47, up from 37/47, confirming the fix live with zero
net regressions.
