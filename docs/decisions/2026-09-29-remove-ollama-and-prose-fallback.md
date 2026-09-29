# Remove the Ollama backend and the prose-citation fallback

**Date:** 2026-09-29

## Context

Small local models aren't a target (user, 2026-09-26), and there will be no fallback backend
when the Gemini quota runs out (map Decision 14). That left Ollama as dead weight in the
blast-radius core, and it was prerequisite 3 of the agent-improvement map. Removing it raised the
map's open ticket: does the prose-citation fallback (`collect_citation_warnings` and its prose
retry) stay as Gemini's last resort? The structural review (2026-09-28) had said keep it, partly
because it was "the Ollama path". That reason goes away with Ollama.

## Decision

- **Commit 1:** remove Ollama. The `BACKENDS` seam stays with one entry (`gemini`), along with
  `--backend`/`--judge-backend`. The three backend-gating sets are gone, since all three were
  `{"gemini"}`.
- **Commit 2:** delete the agent's prose gate. A text reply still gets one forced `submit_answer`
  turn, paid for by the reserved final round trip if the dispatch budget is spent. If the model
  answers in text again, the answer is refused:
  - it gets a `no_submission` warning and `NO_SUBMISSION_REFUSAL` wording;
  - the text is kept as `withheld_answer`.

  A submission cached by an earlier retry is re-gated instead of refused, since it is the model's
  last verifiable answer. The grader's `_iter_citation_claims` / `value_is_citation_verified`
  walk stays; `eval_harness.grade_numeric` uses it.

## Why

- **How much the prose path helped.** The evidence is `trace_logs/traces.jsonl` from 2026-09-11
  on, when submit spans start: 1,303 Gemini runs, 149 of them without a `submit_answer` span.
  - All but one of those 149 were quota/error empties, or budget messages from before the
    final-turn safety net.
  - One real prose answer got through: `pltr-inventory-turnover-fy2025-refusal` (2026-09-25), a
    refusal-type question.
  - The structural review's "8 of 478" counted a different window and didn't separate out errors.
    The conclusion is the same either way: it's nearly unused.
- **What it cost.** Regex patchwork with three open BACKLOG gaps nobody intended to fix
  (`_SENTENCE_BREAK` abbreviations, no quote capture, multi-source brackets), plus a separate
  retry path and loop state (`pre_retry_answer`).
- **Refusing is the principled outcome.** An answer with no structured claims can't be checked,
  and "citations are non-negotiable" means refusing it.
- **Two known effects on eval numbers:**
  - Judged refusal-type questions may now pass on the generic no-submission refusal, whatever the
    model actually did.
  - An empty text turn after forcing used to come back as `""` with no warnings; it now becomes
    this refusal.

  Both are rare (about 1 in 1,300 runs).
- **Why the seam was kept.** The user chose to keep the one-entry `BACKENDS` protocol and flags
  over collapsing them: report fields and `compare_prompt_versions` stay unchanged, and a future
  cloud backend plugs in without re-threading.

## Files touched

- Commit 1:
  - `llm_backends.py`, `agent.py`, `config.py`, `eval_harness.py`
  - `.env.example`, `requirements.txt`, `analyze_citation_gate.py`
  - `.claude/rules/{plan-review-blast-radius,live-code-tdd}.md`
  - `tests/` and `tests/manual/`
  - `prompts/model_input_snapshot.json`
- Commit 2:
  - `agent.py`, `prompts/agent_messages.py`
  - comments in `eval_harness.py`, `numeric_utils.py`, `analyze_*.py` and
    `.claude/rules/live-eval-verification.md`
  - `tests/test_agent.py`, `tests/test_model_input_snapshot.py`, the snapshot
  - `BACKLOG.md`, the agent-improvement map

## Verification

- **Checks:** ruff and pyright clean on both commits; the full suite passes; diff coverage 100% on
  changed lines in commit 1 and in commit 2.
- **Prompt fingerprint:** both commits change it.
  - Commit 1 changes no model-read text. One snapshot scenario had to move from Ollama to Gemini.
  - Commit 2 removes the prose retry message and adds the no-submission refusal.
- **Live, commit 1:**
  - `tests/manual/verify_complete.py` and `verify_submit_answer.py` pass.
  - `eval_harness --ids crm-rpo-fy26,aapl-ai-risk`: 2/2 (`eval_results/20260929T084534Z.json`).
- **Live, commit 2:** `--ids pltr-inventory-turnover-fy2025-refusal,aapl-employees-fy25,msft-tax-rate-q2fy26`:
  3/3 (`eval_results/20260929T192122Z.json`). All three submitted normally, so the no-submission
  path itself is covered by unit tests only; it's too rare to trigger on demand.
- **Replay:** `analyze_gate_replay.py` only re-gates submit spans, so it can't prove the change
  safe. Its skip counters read only the traces, so they can't change here.
  - Baseline on the commit-1 tree, full history, 1,157 runs replayed: skipped 58 non-agent,
    237 no submit, 83 no output, 0 prose final. 0 errored, 114 drifted.
  - Over full history, refusals move from 134 logged to 276 now. That compares today's gate
    against the older gates that logged those verdicts; the replay runs `submission_warnings`/
    `verify_claims`, which this change doesn't touch.
  - The replay tool's documented comparison window is `--since 2026-09-19T03:12`.

## Related

- Plan: `docs/plans/2026-09-29-remove-ollama-and-prose-fallback.md`
- Map: `docs/plans/2026-09-28-agent-improvement-map.md` (Decision 13, prerequisite 3; the
  "Ollama removal: prose fallback path" ticket)
- Revisits: `docs/plans/2026-09-28-structural-review.md` ("Deleting the prose fallback: keep it")
