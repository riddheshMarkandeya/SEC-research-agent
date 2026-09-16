# Final-turn safety net for MAX_TOOL_ITERATIONS zero-slack bug

**Date:** 2026-09-16

## Context

`agent.py`'s tool-calling loop has `MAX_TOOL_ITERATIONS = 6`, but
`calls_made` starts at 1 (the initial model turn already counts as
spent) and increments once per round trip — so a question needing all 5
dispatch turns to gather data had zero turns left to call
`submit_answer`, even when every call succeeded and the model already
held everything it needed. Confirmed live on two correct-REFUSAL
questions (`nvda-rd-expense-q4fy26-refusal`,
`pltr-inventory-turnover-fy2025-refusal`): both could make 5 fully
successful, zero-error dispatch calls, then die with a generic canned
timeout message instead of ever getting a chance to submit the refusal
they'd earned.

This was deliberately scoped out of the 2026-09-14 tool-turn-waste fix
(`docs/plans/2026-09-14-tool-turn-waste.md`) because any remedy touches
the loop's most entangled state (`calls_made`/`forced_submit_attempted`/
`retried_for_citations`/`pre_retry_submit_args`) and carries a
documented wrong-answer risk: a live run on
`five-company-operating-margin-ranking-fy2025` made 4 successful
`get_financial_fact` calls but never reached CRM (a separate,
already-tracked fiscal-year-lookup bug) before the budget ran out — a
naive forced final submit there would confidently name the wrong
company using 4 real, correctly-grounded citations, since the citation
gate (`verify_claims`) only checks that cited values are truthful, not
that the retrieved data set is complete for the question.

## Decision

Added a reserved, single-shot, Gemini-only forced-submit-only final
round trip. `MAX_TOOL_ITERATIONS` itself is unchanged (still 6). When
the dispatch budget is exhausted but the model is still actively
requesting tool calls (not already replying in prose — that case has
its own existing forced-submit mechanism), the loop spends exactly one
extra round trip: every pending tool call is answered with a synthetic
"not run" result, and `force_tool="submit_answer"` hard-constrains the
model's next reply. Whatever gets submitted still goes through the
completely unmodified `verify_claims`/`_finalize_answer` citation gate.

New code, all in `agent.py`:
- `_FINAL_TURN_BACKENDS = {"gemini"}` and `_should_force_final_submit(already_attempted, calls_made, backend)`, near `_should_retry_for_citations`.
- `_FINAL_TURN_SUBMIT_MESSAGE`, near `_FORCE_SUBMIT_MESSAGE` — explicitly re-surfaces system prompt rules 2/6/7 (refuse rather than guess; query every company; name what's missing) and explicitly forbids inventing/estimating, mirroring `_CITATION_RETRY_GUIDANCE`'s already-proven wording. Deliberately no "final attempt"/deadline-pressure language — that exact framing previously caused fabrication on `nvda-rd-expense-q4fy26-refusal` in an earlier, reverted design (`docs/decisions/2026-08-18-citation-retry-loop-v1-tried-reverted.md`), the same canary question this fix targets.
- `final_turn_attempted` state flag in `_run_agent_impl`, and the branch itself, inserted at the point the loop used to unconditionally `break` on budget exhaustion.

## Why

**Not a structural "found:True/False" signal.** The alternative
considered (widening `_dispatch_tool_call`'s return type, flagged as
possible future work in the 2026-09-14 plan) was traced through both
target cases and found wrong for one of them:
`pltr-inventory-turnover`'s entire *correct* trace consists of
`found: False` (PLTR genuinely doesn't tag inventory) — a rule
withholding the safety net whenever `found: False` appears would never
fire for the exact case this fix targets. The CRM ranking danger isn't
a failed call, it's a call that was *never made* — no per-call boolean
distinguishes "search space exhausted" from "budget ran out
mid-gather." Declining this closes the 2026-09-14 plan's "future work"
flag at this exact spot rather than leaving it open.

**Gated to Gemini only**, matching `_CITATION_RETRY_BACKENDS`/
`_FORCED_SUBMIT_BACKENDS`'s existing precedent: this is a directive
nudge injected right as budget runs out, structurally the same kind of
corrective-pressure mechanism `qwen2.5:7b-instruct` was found unreliable
under in an earlier, reverted design. No live evidence existed for how
Ollama responds to this specific nudge, so Ollama's behavior on budget
exhaustion is left completely unchanged; extending to it is future work
pending its own evidence.

**The residual risk is mitigated by message wording, not eliminated.**
The citation gate still can't detect an incomplete-but-internally-
consistent data set — if forced to answer, the model could in principle
state a wrong ranking using only the companies it actually has, all
correctly grounded, and pass `verify_claims`. This can't be closed
structurally without the classifier already rejected above. The
mitigation re-surfaces the model's own existing self-assessment
instructions (rules 2/6/7) at the moment it matters most, rather than
inventing new completeness logic under pressure — the same reliance the
un-forced case already makes on those rules, extended to one more turn.

**Independent plan review caught a real bug before implementation**: the
first draft of the branch used `send_followup` (a bare text turn). Since
the branch only fires when the model's current turn has real,
undispatched tool calls, those calls are already recorded in Gemini's
chat history as pending/unanswered — following them with a bare user
turn is exactly the "dangling function call followed by a bare user
turn" shape already documented elsewhere in this file as historically
producing a Gemini 400. Corrected to use `send_tool_results` (closing
out each pending call with a synthetic result) before the review
completed, so this was never actually run against a live API.

## Files touched

- `agent.py` — `_FINAL_TURN_BACKENDS`, `_should_force_final_submit`, `_FINAL_TURN_SUBMIT_MESSAGE`, `final_turn_attempted` state, and the loop branch in `_run_agent_impl`.
- `tests/test_agent.py` — new unit tests for `_should_force_final_submit` and the new loop branch (rescues a clean refusal, fires at most once, not applied on Ollama, message has no deadline-pressure language); updated 3 existing tests whose scripted `BACKENDS` tuples collided with the new branch's boundary (one needed no change at all once traced — the Gemini-only gate made it unreachable there).
- `tests/manual/verify_final_turn_safety_net.py` — new live-repro script, following `verify_submit_answer.py`/`verify_tool_turn_waste.py`'s informational-not-hard-gate convention.

## Verification

- Full unit test suite green (669 passing), including the new and updated tests.
- `ruff`/`pyright` scoped to changed lines: clean (no new violations on any line this change added or modified; pre-existing baseline violations on untouched nearby lines left alone per this project's changed-files-scoped rollout stage).
- Manual live-repro script (`tests/manual/verify_final_turn_safety_net.py`), run before the fix: reproduced the bug (`[BUG STILL PRESENT]` on both refusal questions on a retry — live model non-determinism meant the first attempt didn't reproduce it, consistent with this project's prior documented experience with these exact questions). Run after the fix (2 full runs plus 2 ranking-only reruns): both refusal questions reliably got a real submission instead of the generic timeout; the ranking question found CRM and produced a correctly-grounded answer in all post-fix runs (the CRM fiscal-year-lookup bug didn't trigger in any of them, so the specific "confidently-wrong-missing-CRM" scenario was not directly exercised live — see Risks below).
- Targeted `eval_harness.py --backend gemini --ids ...` spot-check (8 questions): `pltr-inventory-turnover-fy2025-refusal` now passes cleanly. `nvda-rd-expense-q4fy26-refusal` no longer hits the generic timeout, but still fails on judge strictness about explicit refusal phrasing — an unrelated, pre-existing issue this fix doesn't touch. `five-company-operating-margin-ranking-fy2025` refused via the (unmodified) citation gate on an unrelated quote-matching gap, not a confidently-wrong ranking. `aapl-msft-employee-comparison` failed once; a targeted verbose rerun confirmed the new branch never fired (only 5 round trips total, nowhere near the budget boundary) and the question passed cleanly on rerun — ordinary live-model non-determinism in the pre-existing citation-retry path, not a regression from this change. The other 4 comparison questions passed on the first try.
- Full 47-question baseline: **39/47**, up from the prior 37/47 baseline (2026-09-15's qualitative-claims-schema fix). Both target questions now pass cleanly: `nvda-rd-expense-q4fy26-refusal` and `pltr-inventory-turnover-fy2025-refusal`. Critically, the risk case — `five-company-operating-margin-ranking-fy2025` — also passed, correctly identifying Salesforce/CRM as lowest at ~20% (the CRM fiscal-year-lookup bug happened not to trigger this run, so all 5 companies' data was available); no confidently-wrong ranking was observed anywhere in this run. The 5 "must not regress" comparison questions: 4/5 passed (`nvda-revenue-two-quarter-comparison`, `aapl-msft-employee-comparison`, `aapl-msft-total-assets-comparison`, `msft-three-segments-revenue-q3fy2026`); `aapl-msft-tax-rate-comparison` failed via an ordinary citation-gate refusal unrelated to the budget (confirmed the new branch doesn't fire for this question's call pattern) — consistent with this project's already-extensively-documented citation-gate non-determinism, not a regression from this change. Net: +2 over the prior baseline, exactly matching the 2 questions this fix targets, with zero net regressions.

## Risks / open items not fully resolved

- The CRM-shaped grounded-but-incomplete risk (§Why above) is mitigated, not eliminated, and wasn't directly exercised in live testing — the intermittent CRM fiscal-year-lookup bug (BACKLOG.md) didn't trigger in any post-fix live run (manual script or full baseline), so the model always had all 5 companies' data available when forced to submit. If a future run does hit that combination and produces a confidently-wrong ranking, this design needs revisiting (stronger message wording, or a narrower gate that also checks the most recent tool call's own scope) before reaching for a structural classifier.
- Up to three single-shot "extra" round trips can now stack in one Gemini conversation (prose-forcing + citation-retry + this new safety net) — worst-case turn count per conversation is now `MAX_TOOL_ITERATIONS + 3`, not `+2`.
- Extending this mechanism to Ollama is deliberately left as future work pending its own live evidence, not evaluated in this change.

## Related

Follow-up to `docs/plans/2026-09-14-tool-turn-waste.md`'s Mechanism 4,
deliberately scoped out there. Plan for this change:
`C:\Users\riddh\.claude\plans\snug-jingling-pumpkin.md` (session-local
plan-mode scratch file — this decision file is the durable record).
