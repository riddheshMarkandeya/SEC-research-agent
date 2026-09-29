# Remove the Ollama backend and the prose-citation fallback

## Context

This is prerequisite 3 of the agent-improvement map (`docs/plans/2026-09-28-agent-improvement-map.md`,
Decision 13; BACKLOG `[misc, Med, Substantial]` "Remove the Ollama backend"). Small local models
aren't a target (user, 2026-09-26). Removing Ollama shrinks the `agent.py` split that comes next.
The backlog item's open points are now decided:

- **(a) No fallback backend.** When the Gemini quota runs out, work stops until the reset (map
  Decision 14, user 2026-09-28).
- **(b) Prose fallback: delete it** (user, 2026-09-29). This revisits the structural review's "keep
  it" (2026-09-28). What changed: that review's reason was "it's the Ollama path", which no longer
  holds.
  - Evidence from `trace_logs/traces.jsonl`, 1,303 Gemini runs since the submit spans started
    (2026-09-11): 149 never called `submit_answer`. All but one were quota/error empties or
    budget messages from before the safety net. One real prose answer got through
    (`pltr-inventory-turnover-fy2025-refusal`, 2026-09-25, a refusal-type question).
  - It's regex patchwork with three open gaps nobody intends to fix (BACKLOG lines 272–274).
  - When the model won't submit even after forcing, refusing is the answer that matches
    "citations are non-negotiable".
- **(c)** The `grade_judged`/`_grade` defaults of `"ollama"` are fixed below.
- **(d)** The rule file and the config comments are updated below.
- **(e)** Moot, since Ollama isn't kept.
- **Backend seam: keep it with a single entry** (user, 2026-09-29). `BACKENDS = {"gemini": ...}`,
  the `backend` parameter, `--backend`/`--judge-backend` (one choice each), `DEFAULT_BACKEND` and the
  report `backend` field all stay. A future cloud backend plugs in there. The three gating sets
  (`_CITATION_RETRY_BACKENDS`, `_FORCED_SUBMIT_BACKENDS`, `_FINAL_TURN_BACKENDS`) are removed, as the
  map says, and their conditions become unconditional.

Tier: Substantial. It touches the blast-radius core: `agent.py` loop, `llm_backends.py` send
functions, `eval_harness.grade_judged`.

## Files and steps

Two commits.

### Commit 1: remove Ollama (behaviour-identical on Gemini)

- **`llm_backends.py`**: delete `_OLLAMA_RAW_TOOL_CALLS_SCHEMA`/validator, `_ollama_message_to_turn`,
  `OLLAMA_RETRY_*`, `ollama_call`, `_ollama_start/_send/_send_followup`, the `"ollama"` BACKENDS entry,
  and `complete()`'s Ollama branch. Keep `complete()`'s `ValueError` for an unknown backend.
  Rewrite the module docstring and the comments that compare the two backends (lines ~2–35 and
  ~259–269), plus `complete()`'s docstring. Drop the `OLLAMA_*` import. Keep `import requests` only
  if something else in the file uses it; otherwise remove it.
- **`agent.py`**:
  - Delete the three gating sets.
  - `_should_retry_for_citations(warnings, already_retried)` and
    `_should_force_final_submit(already_attempted, calls_made)` drop their `backend` parameter.
  - The forced-submit condition in `_handle_no_tool_calls_turn` loses its `ctx.backend in …` term.
  - Rewrite the comments/docstrings that explain Ollama gating (~1718–1753, ~1831–1842, and the
    `_run_agent_impl` docstring ~2416–2458), plus `main()`'s `--backend` help if it names Ollama.
  - The `backend` kwarg on `_finalize_answer` / `ctx.backend` stays (seam).
- **`config.py`**: delete `OLLAMA_URL`/`OLLAMA_MODEL_NAME`, and rewrite the `DEFAULT_BACKEND` comment.
- **`eval_harness.py`**:
  - `grade_judged(..., backend: str = "gemini")` and `_grade(..., judge_backend: str = "gemini")`.
  - `_model_name_for` returns `GEMINI_MODEL_NAME` (keep the function; it's the seam).
  - Drop the `OLLAMA_MODEL_NAME` import. Rewrite the "no-API-key backend" reasoning in the
    `run_eval` docstring (~333–350) and the other Ollama comments.
- **`.env.example`, `requirements.txt` comments, `analyze_citation_gate.py` docstring**: remove the
  Ollama setup text. `requests` stays (EDGAR/XBRL use it).
- **Tests**:
  - `tests/test_llm_backends.py`: delete the Ollama tests.
  - `tests/test_agent.py`:
    - Delete the tests whose subject is Ollama gating (`…_false_for_ollama…`, `…_not_applied_on_ollama`,
      `…never_attempts_forcing`, `…refuses_immediately_on_ollama`, `…not_attempted_for_ollama_backend`).
    - Switch the rest from `backend="ollama"` to `"gemini"`, adding the forced-submit/retry turns
      the script now needs. That covers the prose-path tests (lines ~2600–3442), which commit 2
      then rewrites anyway, plus the `_finalize_answer(..., backend="ollama")` string args.
    - Update the calls to the two helpers whose parameter was dropped.
  - `tests/test_eval_harness.py`: rewrite the ~5 Ollama tests (default backend, model-name
    recording).
  - `tests/test_tracing.py` / `tests/test_compare_prompt_versions.py`: the string label only
    becomes `"gemini"`/`"other"`.
  - `tests/test_model_input_snapshot.py`: `loop_budget_exhausted` becomes
    `_run({"MAX_TOOL_ITERATIONS": 1}, "gemini", calc_turn, [calc_turn])` (the forced final turn
    returns a non-submit call, which then hits the break). This changes the snapshot capture, so
    regenerate it in this commit. That gives a new fingerprint while the prompt text is unchanged:
    note it in the commit body so panel comparisons aren't misread.
  - `tests/manual/verify_submit_answer.py`: delete `check_ollama`. Fix the comments in
    `verify_complete.py` and `verify_final_turn_safety_net.py`.
- **Rules**: in `.claude/rules/plan-review-blast-radius.md`, drop `_ollama_send*`. In
  `live-code-tdd.md`, "either backend" becomes "the Gemini backend".

### Commit 2: replace the prose fallback with a refusal (behaviour change)

- In `_handle_no_tool_calls_turn`, keep the one forced `submit_answer` follow-up.
  - If forcing was already attempted, or no budget is left, finalize via
    `_finalize_answer(turn.text or "", [no_submission_warning], …)`.
  - The warning is a `CitationWarning` with a new check name (`"no_submission"`) and a new
    `prompts/agent_messages.py` constant (e.g. `NO_SUBMISSION_WARNING`, "the model answered in text
    instead of calling submit_answer").
  - This reuses the existing refusal machinery, so `withheld_answer` keeps the prose for
    FP analysis and the `citation_gate_refused` log fires. No new refusal path.
- **Delete from `agent.py`**:
  - `collect_citation_warnings`, `verify_citations`, `_iter_uncited_claims`, `_SENTENCE_BREAK`
    and any helper only they use;
  - `_format_citation_retry_message`, the prose retry branch, `_AgentLoopState.pre_retry_answer`
    and its block in `_finalize_after_budget_exhausted`;
  - the `CITATION_RETRY_TEMPLATE`/`CITATION_RETRY_GUIDANCE` constants, if only the prose retry
    uses them (grep first; the structured claim retry may share the guidance).
- **Keep** `_iter_citation_claims`, `value_is_citation_verified`, `_CITATION_WINDOW_CHARS`
  and `_CITATION_MARKER`, because `eval_harness.grade_numeric` still uses them. Check each helper's
  remaining callers with grep before deleting it.
- **Update the docstrings/comments** that name the prose checker: `_finalize_answer`,
  `run_agent`/`_run_agent_impl`, `eval_harness.py:~306`, and `numeric_utils.py:167`.
- **Tests**:
  - Delete the prose-gate unit tests (`collect_citation_warnings`/`verify_citations`/
    `_iter_uncited_claims`/`_SENTENCE_BREAK`).
  - Rewrite the loop tests: text, then forced, then text again should refuse with
    `withheld_answer` set and `check == "no_submission"`; text, then a forced valid submit should
    be accepted (already covered).
  - Snapshot: `loop_prose_retry` becomes a `loop_text_after_force_refusal` scenario. Add the new
    warning text to `_render_citation_warnings`. Regenerate.
- **BACKLOG**: delete the Ollama item and the three prose-path Watch list entries (lines 272–274).
  Update the map's "Ollama removal: prose fallback path" ticket to resolved. Unblock
  "`agent.py` module boundaries".

## Error handling / logging

No new failure points. Commit 2's refusal routes through `_finalize_answer`, which already logs
`citation_gate_refused` with the warning checks. The one question that log must answer is "was
this a no-submit refusal?" (`checks == ["no_submission"]`). Fire it once in a unit test and read
the event.

## Testing and verification

1. Before commit 2, record `analyze_gate_replay.py`'s skip counters. The replay only re-gates
   submit spans, so it's a sanity check here, not an equivalence proof (see Plan review 2).
2. **After each commit:**
   - `ruff check .`, `pyright .`, `pytest --cov=. --cov-report=term-missing -q` (output to a
     scratch file);
   - check that the changed lines clear 90% (critical core);
   - `pytest tests/test_model_input_snapshot.py`: read the diff, then regenerate.
3. **Commit 1 equivalence:** the three removed sets were all `{"gemini"}`, so dropping them is a
   no-op on Gemini; the full suite and the snapshot confirm it. `grep -rni ollama` over
   `*.py`, `.env.example`, `requirements.txt` and `.claude/` returns nothing; history docs and
   `eval_results` are untouched.
4. **Commit 1 live:** `tests/manual/verify_submit_answer.py` (Gemini checks), then
   `eval_harness.py --backend gemini --ids` on 2–3 questions (one judged, so `complete()`'s Gemini
   path runs).
5. **Commit 2:**
   - The replay's skip counters are unchanged from step 1.
   - Live spot-check per `live-eval-verification.md`: `--ids pltr-inventory-turnover-fy2025-refusal`
     plus 2 ordinary numeric questions.
   - Watch the Gemini quota (500/day); no full 48-question run unless the spot-check surprises.
6. **Docs:**
   - copy this plan to `docs/plans/2026-09-29-remove-ollama-and-prose-fallback.md` as step 1;
   - write the decision file `docs/decisions/2026-09-29-remove-ollama-and-prose-fallback.md`
     (ADR gate: hard to reverse, revisits a recorded decision);
   - write a review file (Substantial);
   - add `PROJECT_INDEX.md` Recent lines and fix the Overview line 30 ("Ollama (local) or Gemini"
     becomes "Gemini free tier").
7. Offer `/compact` at the boundary between the two commits, and before `independent-review-pass`.

## Plan review

Reviewer: `plan-reviewer` (Opus), 2026-09-29, with escalated blast-radius scrutiny. Verdict: sound, but
revise before implementing. The fixes below are part of the plan, and they override the matching
earlier steps where they conflict.

1. **High. Grader regression tests were going to be lost.** `_iter_citation_claims` still drives
   `eval_harness.grade_numeric` through `value_is_citation_verified`. Of the 34 `verify_citations`
   tests, the ones shaped like `cited_claim_unsupported` (window slicing, `_NON_CLAIM_PATTERN`
   stripping) are that function's real coverage.
   **Fix (commit 2):** port each of them to `value_is_citation_verified` before deleting it. Delete
   only the tests that are purely about `_iter_uncited_claims` or `_SENTENCE_BREAK`.
2. **Med. The replay proves nothing here.** It only re-gates `submit_answer` spans, and it skips
   no-submit and prose-final runs (`analyze_gate_replay.py:140,163,272`).
   **Fix:** commit 1's equivalence evidence is that all three sets are `{"gemini"}`
   (`agent.py:1727,1753,1842`), so dropping them is a no-op on Gemini, plus the full suite and the
   snapshot. Commit 2 compares the replay's `skipped_prose_final`/`skipped_no_submit` counters before
   and after (they should be equal, since the traces are unchanged). The live spot-check then carries
   the real behaviour evidence. Drop verification steps 1 and 3's "identical verdicts" claims.
3. **Med. The refusal wording is wrong.** `REFUSAL_TEMPLATE` says the claims failed citation
   verification, which is false for a refusal where nothing was submitted.
   **Fix:** add a `NO_SUBMISSION_REFUSAL` constant ("I couldn't produce a verifiable, cited answer
   for this question, so I'm not giving one."). `_format_refusal_message` uses it when every
   warning's check is `"no_submission"`. `_finalize_answer` keeps its choke-point role, so
   `withheld_answer` and the log are unchanged. The warning text can stay short, since it's logged
   and never shown to the user through `REFUSAL_TEMPLATE`.
   - **Judge risk, noted for the spot-check:** judged refusal-type questions such as
     `pltr-inventory-turnover-fy2025-refusal` may pass a generic refusal whatever the model did.
   - An empty text turn after forcing (which used to give `""`, since `collect_citation_warnings("")`
     is `[]`) now also becomes this refusal. That's the honest outcome, but it can nudge
     refusal-question pass rates, so say so in the decision file.
4. **Med. Prompt-constant bookkeeping.**
   - Register `NO_SUBMISSION_REFUSAL` in `FINGERPRINTED` (`prompts/agent_messages.py:258+`;
     `tests/test_prompts.py` enforces this).
   - Remove the entries for the deleted `CITATION_RETRY_TEMPLATE` (`:307`),
     `CITED_CLAIM_UNSUPPORTED_TEMPLATE` and `UNCITED_CLAIM_TEMPLATE`. Their only users are
     `agent.py:1310,1325`; grep again before deleting.
   - `CITATION_RETRY_GUIDANCE` stays, since the claim retry uses it (`agent.py:1813`).
5. **Med. A missed test breaks in commit 1.** `test_run_agent_backend_default_follows_config`
   (`tests/test_agent.py:3383-3401`) scripts prose with `send_followup=None`. Now that forcing is
   unconditional, that raises TypeError.
   **Fix:** script a submit turn instead. Commit 2 also removes its patch of
   `collect_citation_warnings`.
6. **Med. The second refusal branch had no test.** Add a `_run_agent_impl` test with
   `MAX_TOOL_ITERATIONS=1` and a text start turn (no budget, so no forcing, so refuse), alongside
   the test for "forced, then text again".
7. **Low-med. A cached submission was dropped on refusal.** Take this sequence: a submit is
   refused and retried, the model answers in text, it's forced, and it answers in text again.
   **Fix:** when `loop_state.pre_retry_submit_args` is set, re-gate it the way
   `_finalize_after_budget_exhausted` does, instead of refusing with `no_submission`. Reuse that
   function's first branch rather than duplicating it. Test it.
8. **Low. Snapshot edits.** Beyond the new scenario, remove the `prose_warnings` key (`:195`) and
   the `citation_retry` key (`:227`) that the deleted helpers feed. Change the `loop_prose_retry`
   scenario as planned. The reviewer confirmed the `loop_budget_exhausted` Gemini rewrite
   reaches `BUDGET_EXHAUSTED_ANSWER`.
9. **Low. Stale references.** After commit 2, grep for every deleted symbol as well as `ollama`.
   Known hits:
   - `.claude/rules/live-eval-verification.md:26`
   - `analyze_citation_gate.py:2,38`
   - `eval_harness.py:70`
   - `tests/test_numeric_utils.py:4,255,297`
   - `agent.py:857-860,1088,1243`
   - `analyze_gate_replay.py:26,114`
   - `tests/test_mcp_server.py:8`

   Also remove the now-unused `extract_numbers_with_spans` import in `agent.py` if ruff flags it.
10. **Low. Bookkeeping.**
    - Reconcile the "8 of 478" figure (the structural review's window) with this plan's "1 real
      prose answer in 1,303 runs" in the decision file. Different windows; the conclusion holds
      either way.
    - Update BACKLOG line 50 (the active-workstream pointer).
    - **Keep** BACKLOG item 274 (`_CITATION_MARKER` multi-bracket), reworded to name the grader
      path, because it still applies there.
    - A leftover `DEFAULT_BACKEND=ollama` in a local `.env` should fail clearly: raise a
      `ValueError` naming the valid backends at the `BACKENDS[backend]` lookup in `_run_agent_impl`,
      with a unit test.

## Review log

Full record: `docs/reviews/2026-09-29-remove-ollama-and-prose-fallback.md`.

- **Round 1** (snapshot `579bb53`): `/code-review` high, `arch-reviewer` (opus), security,
  `/simplify`. 15 findings: 11 fixed, 1 deferred (mixed-turn submission cache → BACKLOG Watch
  list), 1 disputed (a `refusal=` kwarg on `_finalize_answer` breaks PLR0913), 2 verified with
  no fix needed. Security: none. `/simplify`: 1 fix.
- **Deviation from this plan (round 1, item 2):** a text reply with the dispatch budget spent now
  gets its forced submit from the reserved final round trip (`final_turn_attempted`), instead of
  being refused at once. That overrides Commit 2's "no budget left → finalize" and Plan review 6.
  Otherwise the fix would have refused text that the prose checker used to verify. The replaced
  test covers the reserve already being spent by a pending tool call.
- **Round 2** (delta vs `579bb53`): arch, `/code-review` low, security. 5 arch findings, all
  fixed (docstring ownership, explicit flag write, `final_turn_forced` log, `complete()`
  Gemini-only comment, this deviation note).
- **Round 3:** 1 arch nit fixed (reuse `_should_force_final_submit`), confirmed equivalent by a
  `/code-review` low. Closed clean.
- **Live:** `verify_complete.py` passes; `verify_final_turn_safety_net.py` 3/3 `[OK]`.
