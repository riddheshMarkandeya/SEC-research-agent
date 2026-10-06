# Plan: package 3, uniform submit loop (improvement map, review S2 step 2)

Tier: **Substantial**. It changes the agent loop's behaviour for every question and touches the
critical core (`src/sec_agent/agent/`). Branch `package-3-submit-loop` from master `63114b9`. Commits only when the user asks.

## Context

The map's build order is 2 → 5 → 3 → 4 → 6. Packages 1, 2 and 5 are done, so package 3 is next
(`docs/plans/2026-09-28-agent-improvement-map.md`, "Proposed build order"; BACKLOG line 50).
Review S2 (`docs/plans/2026-09-28-structural-review.md:122`) asks for this: treat a failed
`submit_answer` verification as an ordinary tool error the model can answer, keep a reserved final
turn, and fold `retried_for_citations`, `pre_retry_*`, the forced-submit-on-text path and the
forced final turn into one "submit attempts left" rule.

Today the loop in `src/sec_agent/agent/agent.py` has four flags, and each extra turn type has its
own cap:
- `retried_for_citations`: one citation retry per conversation, at any point;
- `forced_submit_attempted`: one forced follow-up after a text reply;
- `final_turn_attempted`: one reserved forced turn past `MAX_TOOL_ITERATIONS`, which the
  final-turn path and the text path share, and which a forced retry also marks spent;
- `pre_retry_submit_args`: the submission cached when the retry fires.

The worst case is `MAX_TOOL_ITERATIONS + 2` requests
(`test_run_agent_never_complying_model_stays_within_max_plus_two_requests`).

**Evidence (traces since package 1, 2026-10-01T07:00Z, 135 runs):** the retry fired in 17 runs
and 4 were still refused after it. No refusal went without a retry, since package 1 closed that
gap. The 4:
- `607e58e8` and `1577f9f1` (crm-ai-risk in package 5's full run): the retry repeated the same
  `quote_not_found`;
- `86fcf166`: schema-invalid, then `uncovered_number` ×6;
- `c6552518`: a forced retry at call 7, after the final turn; `uncovered_number`, then
  `quote_not_found`.

A second attempt is the only lever the loop has on these. The gate stays unchanged.

**Revisits:** the one-retry-per-conversation cap from
`docs/decisions/2026-08-24-citation-retry-loop-design.md` (plan) and its later decisions,
including `docs/decisions/2026-09-30-citation-retry-own-slot.md`. What changed: package 1 now
gets every failed submit a retry, so the remaining refusals are second failures, and the cap is
what stops them.

### User decisions (2026-10-05)

- **Scope:** a uniform loop with more retries, not a pure refactor. A reserve of **2** forced
  turns past the budget keeps the worst case at `MAX + 2`.
- **Live check:** a base panel 3× on master, a candidate panel 3×, then a full 48 run. That's
  about 650 requests, over two quota days.

## Decision / Design

### The one rule

The turns a conversation may still take = the budget left (`MAX_TOOL_ITERATIONS - calls_made`)
plus `reserve_left` (starts at `SUBMIT_RESERVE = 2`). Every extra turn draws from that pool:

```
def _next_turn_mode(loop_state) -> "free" | "forced" | None   # pure: decides, doesn't spend
    calls_made < MAX           -> "free"    (spends a budget call, as every turn already does)
    reserve_left > 0           -> "forced"  (caller decrements reserve_left; force_tool=submit_answer)
    else                       -> None      (no turn left: finalize)
```

There's one helper `_spend_turn(loop_state, mode)` (decrements `reserve_left` when the mode is
forced). Each of today's three paths makes the same call:

| Turn the model returned | `free` | `forced` | `None` |
|---|---|---|---|
| Submit that fails the gate (pure, or mixed past the budget) | retry message as the submit's tool result, not forced | same, with `force_tool=submit_answer` | finalize the refusal with this submit's warnings |
| Text reply | forced follow-up (`FORCE_SUBMIT_MESSAGE`, always forced, as today) | same | finalize the cached submit, else `NO_SUBMISSION` refusal |
| Non-submit tool calls | dispatch (unchanged) | "not run" results + forced submit | `break` → cached submit, else `BUDGET_EXHAUSTED_ANSWER` |
| Mixed submit+search, in budget | dispatch + `MIXED_TURN_RESUBMIT_MESSAGE` (unchanged) | n/a (past the budget it's a submit) | n/a |

**The rule that comes first: forcing failed, so the run ends.** When the previous send carried
`force_tool=submit_answer` and the model replies with anything but a submit (text or tool
calls), the run ends. It finalizes the cached submit if there is one, else the `NO_SUBMISSION`
refusal for text, or `BUDGET_EXHAUSTED_ANSWER` for tool calls. This check runs before the table.
Forcing again wouldn't work and would only burn a request. It keeps today's "text again after
forcing is refused" behaviour (`test_agent.py:125`) and the "tool call after a forced turn
re-gates the cache" behaviour (`test_agent.py:771`, `:785`, `:797`) without per-conversation
flags.

**`last_turn_forced` is set from the `force_tool` actually sent, not from the mode.** The text
follow-up is forced even in `free` mode. The handlers make the sends, so `_LoopStep` gains a
`forced: bool` field. The handler sets it, and the parent copies it into `loop_state` along with
the `calls_made` increment. `_dispatch_pending_calls` (never forced) sets it to False.

### State after the change (`_AgentLoopState`)

- `calls_made` (unchanged ownership: the parent loop increments it).
- `reserve_left: int = SUBMIT_RESERVE`.
- `last_turn_forced: bool`, set by the parent from `_LoopStep.forced` (see above).
- `retries: int`, a count for logs, passed to `_finalize_answer(retries=…)`.
- `last_submit_args: dict | None`, the **latest** failing submission, raw args (the same reason
  as today: re-gated against the current `all_results`). It replaces `pre_retry_submit_args`.

`retried_for_citations`, `forced_submit_attempted`, `final_turn_attempted`,
`_should_retry_for_citations` and `_should_force_final_submit` are deleted. The
`_AgentLoopState` docstring is rewritten around the one rule, and the long ownership notes
shrink to match.

### Behaviour differences from today (each one gets a test)

1. Repeated failing submits inside the budget each get a retry. Today only the first does.
2. Past the budget, any mix of 2 forced turns: final turn + retry, retry + retry, or text
   follow-up + retry. Today it's the reserve (1) plus one retry if unspent.
3. **Text follow-ups are no longer capped at one per run.** Today the sequence text → forced
   follow-up → bad submit → free retry → text ends the run, because `forced_submit_attempted`
   stays True. Under the new rule the last send (the retry) wasn't forced, so a second forced
   follow-up fires. The number of follow-ups is bounded only by budget plus reserve, which is
   still within `MAX + 2`. This gets its own test.
4. The worst case stays `MAX + 2` requests. The existing bound test is kept, and a
   retry-forever model gets its own bound test.

Kept by the forcing-failed rule, with their tests unchanged: text right after any forced send
(`test_agent.py:125`, including the in-budget case of text → forced follow-up → text), and a tool
call right after a forced retry or final turn (`:771`, `:785`, `:797`).

Unchanged: the gate (`submission_warnings`, `verify_claims`), every model-visible string (the
retry guidance has no "final attempt" wording on purpose, so a second retry reads correctly with
no prompt change), the mixed-turn rule, and `_finalize_answer` as the single exit.

### Logging (§2)

These questions must be answerable from `traces.jsonl` alone: how many retries a run took, which
path spent each reserve turn, and whether a run ended because the reserve ran out.
- `citation_retry`: add `attempt` (1-based: the first retry is 1) and `reserve_left`. Keep
  `forced`, `calls_made` and `pending_tools`.
- `final_turn_forced`: it now fires on **every** forced non-retry send, in budget or past it.
  Today an in-budget text follow-up logs nothing. Add `reserve_left`, and `trigger`
  (`pending_tools` | `text`).
- `citation_gate_refused`: `_finalize_answer` takes `retries: int` in place of `retried: bool`,
  so one source drives both fields. It logs `retries` and also `retried=retries > 0`, since
  `analyze_citation_gate.py` and older traces use `retried`. Update the 8 calls in
  `tests/agent/test_submission.py:55-185`.
- A new `submit_turns_ended` event (`calls_made`, `retries`, `reserve_left`, `reason`:
  `no_turn_left` | `forcing_failed`, `ending`: `refused` | `cached` | `budget_message`) fires
  from both ending paths: no turn left, and the forcing-failed rule.

Fire one exhaustion path offline in a unit test with `capture_events`, and read the line.

### Files

- `src/sec_agent/agent/agent.py`: the state, `_next_turn_mode`/`_spend_turn`, the three handlers
  (`_handle_submit_turn`, `_send_citation_retry`, `_handle_no_tool_calls_turn`,
  `_force_final_submit_turn`), the cache finalizers and the docstrings. The loop body keeps its
  shape. Reuse `_not_run_results`, `_dispatch_pending_calls`, `_finalize_answer` and
  `submission_warnings` as they are.
- `src/sec_agent/agent/submission.py`: `_finalize_answer`'s `retried: bool` becomes
  `retries: int`, and the "one-time retry" docstring of `_format_claim_retry_message` (`:28`) is
  updated.
- `src/sec_agent/devtools/analyze_citation_gate.py:38-43`: the "one-shot corrective retry"
  caveat is updated to say the latest of possibly several attempts.
- `agent.py`'s `_run_agent_impl` docstring (`:390-409`) and `_AgentLoopState`'s are rewritten.
- `tests/agent/test_agent.py`: tests of the deleted predicates become `_next_turn_mode` table
  tests. Loop tests that pin the one-retry cap are rewritten to the new rule. Use the existing
  `_install_scripted_backend` / `_verify_sequence` helpers. Rows: the 4 behaviour differences
  plus each `None` row.
- `tests/prompts/test_model_input_snapshot.py`: the fake backend calls `next(turns)` (`:289`),
  so scripts that are too short raise `StopIteration`. Two scenarios need longer scripts:
  - `loop_force_claimretry_refusal` (`:348`): 2 turns now; it needs one per retry until the
    budget plus reserve runs out. Extend it, rename it to `loop_retries_until_turns_run_out`,
    and update `expected_calls`. It doubles as the second-retry scenario.
  - `loop_mixed_turn_retry_at_budget` (`:373`): 1 turn now, and it needs 2.

  `loop_retry_after_final_turn` keeps its count. Read the diff, then regenerate. The
  fingerprint changes, which is expected.
- `tests/manual/verify_uniform_submit_loop.py`: a live repro written first, modelled on
  `verify_retry_slot.py`. It uses the low budget and injects `quote_not_found` on the first two
  **submit-gate checks**, counted at `submission_warnings` per submit span, so the cached
  re-gate and a schema-invalid submit can't use up an injection. Before the change it shows a
  refusal after one retry. After it, a second retry runs, Gemini accepts two forced submit
  results with no 400, and the events carry the new fields. About 12–15 requests (3 questions).

## Files and steps

1. Save this plan to `docs/plans/2026-10-05-package-3-uniform-submit-loop.md`. Add its
   `PROJECT_INDEX.md` line.
2. **Base panel (quota day 1, about 195 requests):** on clean master `63114b9`, run
   `python -m sec_agent.eval.eval_harness --backend gemini --ids <PANEL>` 3×. PANEL is the 13
   IDs in `docs/plans/2026-09-24-prompt-audit-roadmap.md:423`. It doesn't depend on the code and
   can run while steps 3–6 are built.
3. Write `tests/manual/verify_uniform_submit_loop.py` and run it on master. It should show red:
   refused after one retry. (About 12–15 requests.)
4. TDD at the `_run_agent_impl` seam with the scripted fake backend: the rule table, the
   forcing-failed rule (text and tool-call replies, in budget and past it), behaviour
   differences 1–3, the bounds, and the log fields, including `submit_turns_ended` from both
   ending paths. Red first, then implement.
5. Regenerate the snapshot (`UPDATE_SNAPSHOT=1`) after reading its diff.
6. Gates: `ruff check .`, `pyright .`, `pytest --cov=. --cov-report=term-missing -q`, with 90%
   diff coverage on `agent/`. Replay identity: run
   `python -m sec_agent.devtools.analyze_gate_replay --compare <saved baseline>` over all traces
   before and after. It must be identical, since the gate is untouched. Re-run the manual
   script: green.
7. Give the user the `/compact` line, then `independent-review-pass` (Substantial, critical core:
   code-review high, arch-reviewer opus with this plan, security-reviewer, simplify). Commit:
   one commit for the model-affecting change, with the snapshot in it.
8. **Candidate panel 3× (quota day 2, about 195 requests)** on the committed tree. Run
   `compare_prompt_versions` explicit mode, base files from step 2. Then follow the Decision
   rule (screen → replicate → attribute).
9. **Full 48 run** (about 250 requests; the same day if quota allows, else day 3). Compare it
   against package 5's `20261003T030904Z` (44/48), replay-adjusted with today's gate. Explain
   every drop from traces.
10. Re-mine: run `analyze_gate_replay` over the full run's window, and count from
    `citation_retry.attempt` how many runs used a second retry and how many it rescued.
11. Docs: a decision file `docs/decisions/2026-10-0x-uniform-submit-loop.md` (revisits the
    one-retry cap; Related → the 08-24 and 09-30 decisions), a review file, `PROJECT_INDEX.md`
    lines, the map (package 3 done, package 4 next) and the BACKLOG line 50 update.

## Testing and verification

- Unit: every row of the rule table, the 4 differences, the `MAX + 2` bound for a model that
  never complies and for one that keeps failing submits, and the log fields via
  `capture_events`.
- Offline: replay identical across all traces, and the snapshot diff read and explained.
- Live: the manual script green, then the panel screen with no REGRESSED, then the full run
  ≥ 44/48 with every drop explained. Success means 1 or more of the retried-then-refused runs
  rescued by a second attempt, with no new refusal class.

## Risks

- A second retry could reward the model for guessing a new quote instead of fixing the
  citation. The gate still checks every quote, so the risk is a refusal, never a wrong
  answer. Watch for retries that cite a different source with the same number.
- More forced turns cost quota only on failing runs (about 4 of 135).
- `analyze_gate_replay._final_submit` scans from the end (`analyze_gate_replay.py:125`), and
  the cache now holds the latest submit, so the two agree. That's a better fit than today's
  first-submit cache.

## Plan review

Round 1 (`plan-reviewer`, Opus, 2026-10-05). Verdict: the approach fits and the `MAX + 2` bound
holds on every path. All findings are folded in.
- **[High, fixed]** `last_turn_forced` was unspecified, and tracking the mode would break
  text → forced follow-up → text in budget. It's now set from the `force_tool` actually sent,
  carried on `_LoopStep.forced`.
- **[Med, fixed]** A tool call right after a forced turn ends the run today (tests `:771`,
  `:785`, `:797`), and the plan's table would have sent another forced turn. The rule is now
  "forcing failed, the run ends" for any non-submit reply.
- **[Med, fixed]** Difference 3 isn't unchanged: text follow-ups are no longer capped at one.
  It's listed and tested now.
- **[Med, fixed]** Two snapshot scenarios would hit `StopIteration`. Their scripts are extended
  and named in the plan.
- **[Low, fixed]** An in-budget forced follow-up and a forcing-failed ending left no log line.
  `final_turn_forced` now fires on every forced send, `submit_turns_ended` covers both ending
  paths, and `attempt` is 1-based.
- **[Low, fixed]** `retries` replaces `retried` on `_finalize_answer`, so one source drives both
  log fields, and the 8 calls in `test_submission.py` are listed.
- **[Low, fixed]** Stale "one retry" text is listed in `analyze_citation_gate.py`,
  `submission.py:28` and the `_run_agent_impl` docstring.
- **[Low, fixed]** The manual script injects per submit-gate check, so the re-gate can't use up
  an injection. The request estimate is now 12–15.
- Confirmed sound: the `MAX + 2` bound, the mixed turn at the budget edge (one function response
  per call), two forced submit results in a row (already seen live, in `c6552518`), latest-submit
  caching against the replay's `_final_submit`, and the retry wording.

## Implementation deviations

- `_spend_turn(loop_state, mode)` became `_take_turn(loop_state)`, which decides and spends in one
  call. `_send_citation_retry` became `_try_citation_retry`: it calls `_take_turn` itself and
  returns a `_LoopStep` (or None), keeping it under ruff's PLR0913 limit.
- `submit_turns_ended.ending` is `gate_refused | cached | no_submission | budget_message`, not
  `refused | cached | budget_message`. A refusal of the last submission and a refused text reply
  are different endings, and traces need to tell them apart.
- The snapshot scenario `loop_submit_schema_mismatch` also needed a longer script
  (`MAX_TOOL_ITERATIONS: 2`, 3 turns) to avoid `StopIteration`.
- The forcing-failed rule is narrowed (review round 1): tool calls replying to a forced send are a
  forcing failure only past the budget. In budget they are dispatched, as on master.

## Review log

Diff re-classified at review time: Substantial (~640 changed lines, critical core).

### Round 1 (snapshot `c03c951`)

Passes: `/code-review high`, `arch-reviewer` (sonnet), `security-reviewer`, `/simplify`.

- **[Fixed]** code-review: the forcing-failed rule ended a run when a tool-call reply to an
  in-budget forced follow-up still had budget, answering `BUDGET_EXHAUSTED_ANSWER` after 2 of 6
  calls. Master dispatched it. The rule now applies to tool calls only past the budget. New test
  `test_run_agent_tool_calls_after_an_in_budget_forced_followup_are_dispatched`.
- **[Verified, no fix needed]** code-review: an in-budget mixed submit+search turn's submit is never
  cached in `last_submit_args`. It was never gated, so it isn't a "failing submission", and master
  didn't cache it either.
- **[Fixed]** code-review: the manual script's second injection decides a `[RESERVE SPENT]` run's
  refusal, against its docstring's "gated for real". The docstring and label now say so.
- **[Fixed]** code-review: the manual script spent an injection on a schema-invalid submit, against
  the plan. Injections are now counted per schema-valid submit-turn check.
- **[Disputed, tests changed]** code-review: the no-turn-left branches of
  `_handle_no_tool_calls_turn` / `_force_final_submit_turn` are dead. That's only true while
  `SUBMIT_RESERVE >= 1`; with a reserve of 0 they are the ending path. The hand-built-state tests
  are replaced by `test_run_agent_with_no_reserve_ends_at_the_budget_without_a_send`, which drives
  them through the real loop.
- **[Verified, no fix needed]** code-review: a mixed submit+search reply to an in-budget forced
  send is dispatched. Gemini's forced mode allows only `submit_answer`, and in-budget tool calls
  are now dispatched consistently (first finding).
- **[Fixed]** code-review + arch: stale test names and comments (the deleted post-loop fallback,
  "fires at most once", "the one retry", "spends the final turn") are reworded and renamed.
- **[Fixed]** code-review + arch: the `ending` values differed from the plan. The deviation is
  recorded above, and the `_log_turns_ended` docstring lists all four.
- **[Fixed]** arch: `reason`/`ending` are now typed as `Literal` (`EndReason`, `Ending`).
- **[Verified, no fix needed]** arch: the `_end_run(turn=None)` sentinel. Both call sites read
  clearly, and an explicit `text` parameter would carry the same None.
- **[Fixed]** arch: plan deviations (`_take_turn`, `_try_citation_retry`, the schema-mismatch
  scenario) are recorded above.
- security: no findings.

- **[Fixed]** simplify (simplification + altitude): the loop's forcing-failed `elif` re-derived
  the routing of the two branches after it. It's deleted; `_end_before_forcing` is now the shared
  prelude of `_handle_no_tool_calls_turn` and `_force_final_submit_turn` (forcing failed, else no
  turn left). Same inputs end the run, and the snapshot is unchanged.
- **[Skipped]** simplify: drop `_LoopStep.forced` and have handlers write `last_turn_forced`.
  The parent owning that state is the plan-reviewed design.
- **[Skipped]** simplify: shared trace-tail helper for `tests/manual/` (the copy exists in 3-4
  scripts outside this diff), a shared log-field dict, a `log_calls` fixture, a `trigger`
  Literal, and the manual script's single-pass event filter. Optional or negligible.

After the fixes: ruff clean, pyright 0 errors, 1261 passed. diff-cover vs master is 100% overall
and 100% on `src/sec_agent/agent/*`. The snapshot is unchanged by the fixes.

### Round 2 (delta `git diff c03c951`)

Passes: `/code-review high`, `arch-reviewer` (sonnet), `security-reviewer`. No behaviour bugs; the
traced routing matches c03c951 except the intended in-budget dispatch fix.

- **[Fixed]** code-review: the manual script's `[RESERVE SPENT]` label always blamed the injection,
  even when the run ended on `forcing_failed` (cached submission re-gated by the real gate). The
  verdict now follows `submit_turns_ended.reason`.
- **[Fixed]** code-review + arch: `_run_agent_impl`, `_log_turns_ended` and `_end_before_forcing`
  docstrings now say tool calls are a forcing failure only past the budget; the reflowed paragraph
  is rewrapped.
- **[Fixed]** code-review: `test_run_agent_non_submit_reply_to_a_forced_send_ends_the_run` renamed
  `..._past_the_budget_ends_the_run`.
- **[Fixed]** code-review: the in-budget dispatch test now asserts the dispatched payload, so a
  synthetic "not run" reply can't pass it.
- **[Fixed]** code-review: `_end_before_forcing` returns the `_LoopStep` itself.
- security: no findings (bound still MAX + 2; every exit through `_finalize_answer`).

### Round 3 (round-2 fixes)

The snapshot before round-2 fixes was missed; the delta is the hunks listed above. Passes:
`/code-review low`, `security-reviewer`. No findings from either. Review closed (stop rule: a clean round).

After round 2-3 fixes: ruff clean, pyright 0 errors, 1261 passed, diff-cover vs master 100%
overall and 100% on `src/sec_agent/agent/*`. Snapshot unchanged.
