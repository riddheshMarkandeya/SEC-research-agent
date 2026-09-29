# Review: Remove the Ollama backend and the prose-citation fallback

Plan: `docs/plans/2026-09-29-remove-ollama-and-prose-fallback.md`. Commit `19d135b` removes Ollama
and the backend-gating sets; the second commit replaces the prose fallback with a `no_submission`
refusal. Reviewed together as `git diff 437026e` (~2,600 lines, blast-radius core: the `agent.py`
loop, `llm_backends.py`, `eval_harness.grade_judged`, `prompts/`), so Substantial passes. Suite:
1,038 tests before review, 1,043 after.

## Round 1

Passes: `/code-review` high, `arch-reviewer` (opus), `security-reviewer`, `/simplify`.
Snapshot: `579bb53` (`git stash create`).

1. **Med** (code-review, arch): the grader's per-marker window reset in `_iter_citation_claims`
   lost its only test when the `verify_citations` tests went. Code review proved it by mutation:
   the whole suite passed with the reset removed. `[Fixed]`: two `value_is_citation_verified`
   tests, one for the reset and one for the `_CITATION_WINDOW_CHARS` cap. The reset test fails on
   the same mutation.
2. **Med** (code-review): a text reply at exactly `calls_made == MAX_TOOL_ITERATIONS` was refused
   with no forced submit, although the reserved final round trip was unspent. Before the change,
   that text went to the prose checker. `[Fixed]`: `_handle_no_tool_calls_turn` spends the
   reserve (`final_turn_attempted`) on the forced submit. This deviates from plan step "no budget
   left → refuse" and plan review 6; that test now covers the reserve being spent by a pending
   tool call.
3. **Med** (code-review, arch): a stale `DEFAULT_BACKEND=ollama` in `.env` gets past argparse
   (defaults aren't checked against `choices`). The new `ValueError` was then swallowed per
   question, which saved an all-failed report labelled with the Gemini model. `[Fixed]`:
   `llm_backends.require_backend()` is called by `complete()`, `_run_agent_impl` and `run_eval`
   (both backends) before the first question. That also gives one error format (arch nit).
4. **Low** (code-review): a mixed submit+search turn's submission isn't cached the way a retried
   one is. So text twice afterwards is refused instead of re-gating it. `[Deferred → BACKLOG]`
   (Watch list, agent loop): it has not been seen live and the refusal is the safe side.
5. **Low** (code-review): `analyze_gate_replay._final_submit` could match a `no_submission`
   refusal to an earlier submit by text, for example an empty text reply against a schema-invalid
   submit with no `answer_text`. `[Fixed]`: a logged `no_submission` check returns None, and a
   test covers it.
6. **Low** (code-review, arch): `analyze_citation_gate.py`'s docstring still described
   `false_positive_by_check` as splitting the two deleted prose checks. The arch question on
   whether a `no_submission` "false positive" means a misjudgement is answered in the same place.
   `[Fixed]`: it's its own key, and the docstring says to read it as a submission failure.
7. **Low** (code-review): `_finalize_answer` picks the refusal wording by check name. The review
   suggested a `refusal=` keyword instead. `[Disputed]`: the keyword breaks the PLR0913 5-argument
   limit (tried, reverted). The `all(...)` branch is also correct for mixed warnings, since any
   claim failure keeps the claims wording, and the docstring now says so.
8. **Nit** (code-review, arch): `_finalize_cached_submission` took `submit_args` although both
   callers passed `loop_state.pre_retry_submit_args`. `[Fixed]`: it reads `loop_state` itself and
   returns None when nothing is cached.
9. **Nit** (code-review): test fixtures used the retired `uncited_claim`/`cited_claim_unsupported`
   check names. `[Fixed]` in `tests/test_agent.py` and the snapshot test's fixture (live names
   now; the snapshot bytes are unchanged). The analyzer and harness fixtures are
   `[Verified, no fix needed]`: they model old reports, which still carry those names.
10. **Nit** (arch): doc-file pointers survived in seven touched docstrings and comments
    (`_ANY_CITATION_BRACKET`, `_number_candidates`, `verify_claims`, `_format_refusal_message`,
    `_finalize_answer`, `_run_agent_impl`, and the `eval_harness` import comment), plus a
    narrated test-section header. `[Fixed]`.
11. **Nit** (arch): deleting the prose Watch entries left the "2026-09-26 backlog review" section
    empty. The `aapl-rd-pct-gross-profit-fy2025` item's refusal modes both came from the deleted
    prose checker, so its trigger can't fire. `[Fixed]`: both removed.
12. **Nit** (arch): `NO_SUBMISSION_REFUSAL` differed from the plan's text, and "rather than risk an
    unsupported number" reads oddly on qualitative questions. `[Fixed]`: the clause was dropped
    and the snapshot regenerated.
13. **Nit** (arch): a duplicate rounding test. `[Fixed]`: removed.
14. **Nit** (arch): `_should_retry_for_citations`/`_should_force_final_submit` are now one-line
    predicates. `[Verified, no fix needed]`: they're named and unit-tested, and the `agent.py`
    module-boundaries ticket comes next.
15. **Nit** (arch): the `prompts/` comments say "even after being forced", which was wrong for
    the no-budget path. `[Verified, no fix needed]` after item 2: every `no_submission` refusal
    now follows a forced turn. The one `agent.py` comment and the decision file that said "or no
    budget left" were corrected instead.

Security: no findings. It traced every return site through `_finalize_answer`, checked where
`withheld_answer` goes (local JSONL and the report only), and checked backend-name validation.

`/simplify`: reuse, efficiency and altitude found nothing. Simplification: the budget-edge flag
write was reduced (later made explicit in round 2). Skipped, as the backend seam is a user
decision: `_model_name_for` returning a constant, and the manual script's `backend` parameter.

## Round 2

Delta: `git diff 579bb53`. Passes: `arch-reviewer` (opus), `/code-review` low,
`security-reviewer`.

`/code-review` low and security found nothing.

1. **Risk** (arch): the `_AgentLoopState` docstring still said each flag had one writer, but
   `final_turn_attempted` now has two. `[Fixed]`: it names both and calls the flag the shared
   reserve.
2. **Nit** (arch): `final_turn_attempted = not has_budget` also writes False, which is safe only
   by a monotonicity argument. `[Fixed]`: `if not has_budget: ... = True`.
3. **Nit** (arch): spending the reserve on a text reply was only visible under `--verbose`.
   `[Fixed]`: it logs `final_turn_forced` with `pending_tools=[]`, matching the pending-tool path.
   The test asserts the event.
4. **Nit** (arch): `complete()` now always calls Gemini after `require_backend`, so a second
   registered backend would be judged by Gemini silently. `[Fixed]`: a comment at the call says
   the body is Gemini-only.
5. **Q** (arch): the budget-edge fix contradicts the plan's text and plan review 6.
   `[Fixed]`: recorded as a deviation (round 1 item 2) here and in the plan's Review log.

## Round 3

Delta: the four round-2 fixes. Passes: `arch-reviewer` (opus), `/code-review` low,
`security-reviewer`.

`/code-review` low and security found nothing. Security checked that the `final_turn_forced` log
line carries no answer or question text, and that the shared reserve can't be spent twice.

1. **Nit** (arch): the text path re-implemented the reserve check that
   `_should_force_final_submit` owns. `[Fixed]`: it calls the predicate, and the predicate's
   docstring now names both paths. A `/code-review` low on that hunk confirmed it's
   behaviour-identical (`has_budget` short-circuits; otherwise `calls_made >= MAX` holds).

## Live verification

- Before review, on the committed and working trees: `eval_harness --ids crm-rpo-fy26,aapl-ai-risk`
  2/2 (`eval_results/20260929T084534Z.json`), and
  `--ids pltr-inventory-turnover-fy2025-refusal,aapl-employees-fy25,msft-tax-rate-q2fy26` 3/3
  (`eval_results/20260929T192122Z.json`).
- After the review fixes:
  - `tests/manual/verify_complete.py` passes, which covers `complete()` after `require_backend`.
  - `tests/manual/verify_final_turn_safety_net.py` gives 3/3 `[OK]`. Both refusal questions
    submitted instead of timing out, and the ranking question cited CRM, with no `[WATCH]`.
- Not triggered live: the text-reply-at-budget-edge path and the `no_submission` refusal. Both
  are too rare to provoke on demand (about 1 in 1,300 traced runs), so unit tests cover them.

## Outcome

Closed clean after four rounds (the fourth a single `/code-review` low on an equivalent
refactor). 21 findings in total: 17 fixed, 1 deferred, 1 disputed, 2 verified with no fix needed.
The deferred mixed-turn submission cache is a `[bug (latent), Low, Standard]` item on the
BACKLOG Watch list. Final suite: 1,043 passed; ruff and pyright clean; diff coverage 100% on
changed lines.
