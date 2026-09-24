# Restore `nvda-revenue-yoy-growth-q1fy27`, log the final-turn safety net's own trigger

**Date:** 2026-09-23

## Context

Investigating whether `eval/citation_stress_questions.jsonl`'s questions
had been lost (they hadn't — all 6 were merged into `eval_questions.jsonl`
on 2026-09-13, confirmed via `git show da8af5c^`) surfaced a 7th question
that was *designed* the same 2026-09-11 session but never committed
anywhere: `nvda-revenue-yoy-growth-q1fy27`, targeting a citation-verifier
risk where the source states two nearby percentages ("up 85% from a year
ago and up 20% sequentially"). It failed live verification against
Gemini twice that session via tool-budget exhaustion (`MAX_TOOL_ITERATIONS=6`
hit with no answer submitted — a non-verdict, not a graded FAIL) and was
dropped per this project's two-strikes debugging discipline, leaving a
still-open `BACKLOG.md` item.

Retrying now was judged a legitimate re-test, not blind repetition: a
Gemini-only final-turn safety net (`_should_force_final_submit`,
`agent.py:2077`) was added 2026-09-16 specifically to intercept this
exact budget-exhaustion shape.

## Decision

1. Added the question back to `eval/eval_questions.jsonl` (48 questions
   total) — **kept permanently regardless of live-verification outcome**,
   per explicit direction: this is now something `analyze_flakiness.py`
   tracks going forward, not something to keep re-attempting by hand.
2. Added a `log_event("final_turn_forced", ...)` call in `agent.py`'s
   `_force_final_submit_turn`, closing a real gap: the safety net
   engaging was previously only visible via a `--verbose` print or by
   inferring it from counting trace spans, not a direct, queryable
   signal.
3. Ran the question live against Gemini 3 times to gather real
   behavioral data (not to gate a keep/revert decision).

## Why

Deferred to the paired plan file for the full reasoning (prior art on
retry legitimacy, the citation-source verification methodology, the
bounded scope of the `agent.py` logging change) — not re-derived here.

## Live verification results (all 3 runs, `--backend gemini`)

All 3 runs **passed** (`grade_numeric`, 0 citation warnings each) — but
the automated PASS/FAIL alone doesn't confirm the target risk was
exercised, since a model can pass by citing a different, unambiguous
source instead of the risky sentence. Manual inspection of each run's
citation quote (via `eval/eval_results/*.json` + `trace_logs/traces.jsonl`)
found:

| Run | Report | Outcome | Cited source |
|---|---|---|---|
| 1 | `20260923T235310Z.json` | PASS | Table cell: `"Total \| $81,615 \| $44,062 \| $37,553 \| 85%"` — safe, unambiguous, does NOT exercise the target risk |
| 2 | `20260923T235436Z.json` | PASS | Same table cell (self-computed 85% from the two cited dollar figures) — does NOT exercise the target risk. **Also: this run hit `MAX_TOOL_ITERATIONS=6` with a pending `calculate` call, and the final-turn safety net fired** (`final_turn_forced` event: `calls_made=6, pending_tools=["calculate"]`) — a live, first-hand confirmation that the 2026-09-16 fix rescues exactly the failure shape that killed this question in 2026-09-11, rather than falling through to the old "wasn't able to finish" non-verdict. |
| 3 | `20260923T235540Z.json` | PASS | The risky prose sentence itself: `"Revenue was $81.6 billion, up 85% from a year ago and up 20% sequentially."` — **genuinely exercises the target risk**, and the verifier correctly extracted 85% (YoY), not 20% (sequential). |

**Honest summary**: the original budget-exhaustion failure mode is
resolved — confirmed directly, not just inferred, via the new log event
firing exactly once and the run still completing cleanly. The target
citation-verifier risk (confusing YoY with sequential growth) is
*sometimes* exercised and handled correctly (1/3 runs) but the question
doesn't *reliably* force that engagement — 2/3 runs took a safer,
equally-valid table-cell route instead. This is real, useful signal, not
a clean "resolved" — the `BACKLOG.md` item stays open, updated with this
evidence, rather than being closed on a superficial 3/3 pass rate.

## Files touched

- `eval/eval_questions.jsonl` — new line, `nvda-revenue-yoy-growth-q1fy27`.
- `agent.py` — `_force_final_submit_turn` gained a `final_turn_forced`
  log event.
- `tests/test_agent.py` — extended
  `test_run_agent_final_turn_safety_net_rescues_a_clean_refusal` to
  assert the new log event fires with the expected fields.
- `BACKLOG.md` — the "two nearby PERCENTAGES" item rewritten with this
  session's evidence, kept open (not resolved).
- `PROJECT_INDEX.md` — new `Recent` line.

## Verification

`agent.py` change: full suite 766 passing, `ruff check .`/`pyright .`
both zero errors full-repo — an independent review (architecture +
security) found the change correctly scoped, correctly placed, and
confirmed local-only (never Langfuse-forwarded), with one cosmetic
duplication fixed (a `pending_tool_names` list computed once and reused,
instead of twice). The eval question itself: live-verified 3 times
against real Gemini calls, as detailed above — this IS the verification,
not a proxy for it.

## Related

Plan: (this session's plan-mode output, not separately saved to
`docs/plans/` — a Standard-tier live-verification-gated data change).
Amends the still-open item this decision references in `BACKLOG.md`.
Extends `docs/decisions/2026-09-11-calculate-tool-and-stress-questions.md`
(where this question was originally designed) and
`docs/decisions/2026-09-16-final-turn-safety-net.md` (the fix that made
retrying legitimate).
