# Gate replay tool (`analyze_gate_replay.py`): agent-improvement map, prerequisite 2

## Context

The agent-improvement map (`docs/plans/2026-09-28-agent-improvement-map.md`, Decisions 13 and 15)
orders the prerequisites like this: NUMBER_PATTERN fix (done, `bf9e600`) → **replay tool** → Ollama
removal → `src/` move → `agent.py` split → eval summary mode. Review S1
(`docs/plans/2026-09-28-structural-review.md`) specifies the replay tool. It does two jobs:
(a) the regression check for code-only gate changes (`verify_claims`, `table_grounding`,
`numeric_utils`); (b) the equivalence check for the pure refactors that follow. Today the replay is
a scratch script (`replay_gate.py`, session `6fb2388b`). It covers only refused runs, calls
`verify_claims` directly, and depends on a scratch `classify.py`.

Outcome: a committed, tested tool. It replays every traced agent run's final `submit_answer`
offline (no LLM, no Gemini quota) through the current gate. It reports verdicts against the logged
verdicts or against a saved baseline replay, plus drift in what each tool call would have
returned to the model.

Tier: **Substantial** (a new tool). So: TDD, a repo plan copy, a review file, and
`independent-review-pass`. It touches critical-core `agent.py` (small extractions plus one latent
crash fix), so review is escalated and those lines need 90% diff coverage.

User decisions (2026-09-28):
- Extract shared helpers in `agent.py`, so the replay can't drift from the live gate or dispatch.
- Compare against a saved JSON baseline (`--compare base.json`). No git worktree machinery.
- Hash each rebuilt tool result, so a refactor that changes what the model would see is caught.
  This is reported separately from verdict changes (the user's suggestion).
- Step 0 is the BACKLOG edit below.

## Files and steps

### Step 0: BACKLOG, make the map the visible active workstream

- Under `## In progress`, replace "(none right now…)" with one item,
  `**[misc, Med, Substantial]** **Agent-improvement map**`. It says:
  - Link: `docs/plans/2026-09-28-agent-improvement-map.md` (merged; supersedes the gate-refusal map
    and the structural review).
  - Prerequisites in order (Decisions 13 and 15). The NUMBER_PATTERN fix is done (`bf9e600`). The
    replay tool is next.
  - After them: the map's "Proposed build order".
  - Frontier tickets: the prose fallback path and segment-table ranking.
  - No fallback backend after Ollama removal (user, 2026-09-28).
- Shorten BACKLOG.md:59. It keeps its closing record (the three finished candidates and the post-fix
  panel) and ends with "Next: see *Agent-improvement map* under In progress". This removes the
  duplicate prerequisite list.
- When the tool ships, mark the replay tool done in that item.

### Step 1: `agent.py` extractions (commit A: pure refactor, TDD)

- **`submission_warnings(args, all_results, question) -> tuple[str, list[CitationWarning]]`**
  (public). It holds `_handle_submit_turn`'s body from `agent.py:2215-2235`:
  - `validate_tool_args` fails → `answer_text = args.get("answer_text") or ""` plus the
    `no_structured_answer` warning;
  - otherwise `verify_claims`.

  `_handle_submit_turn` calls it *inside* its existing `with traced_span`, so the span output is
  unchanged.
- **`run_search(query, ticker, all_results) -> tuple[str, int]`** (public). It holds the body of
  `_dispatch_search_filings` from `agent.py:2071-2075`: `hybrid_search`, extend, format. It returns
  the content and the result count. `_dispatch_search_filings` keeps its validation,
  resolution and span, and calls this helper. The replay calls it with the span's logged,
  already-resolved `query`/`ticker`. That skips re-validation, which could reject a logged
  `ticker: None`. It also skips re-resolution, which is redundant.
- Tests first, in `tests/test_agent.py`: an invalid and a valid case for `submission_warnings`,
  and `run_search` with `hybrid_search` monkeypatched. Existing submit and search tests stay green
  unchanged, and so does the model-input snapshot.

### Step 1b: fix the budget-exhausted gate call (commit B: behavior change, stated as such)

`_finalize_after_budget_exhausted` (`agent.py:2358-2362`) indexes `pre_retry_submit_args["answer_text"]`
and `["claims"]` directly. It can hold invalid args: invalid args produce a `no_structured_answer`
warning, Gemini retries, and `pre_retry_submit_args` is set to those args (`agent.py:2243`). If the
budget then runs out, this raises `KeyError`.

Route it through `submission_warnings`. The crash becomes a refusal, and both gate call sites share
one helper. A regression test comes first: it drives this path with invalid args and asserts a
refusal, not a `KeyError`.

### Step 2: `analyze_gate_replay.py` (top level, next to `analyze_citation_gate.py`; it moves to `tools/` with the `src/` move)

**Loading (pure).**
- Reuse `trace_query.load` and `trace_query.question_ids`, and `_iso_prefix` for `--since`/`--until`.
- `group_runs(records, ids, since, until) -> list[RunTrace]` keys on runs that have a `run_agent`
  span. MCP-server root tool spans aren't agent runs; they're counted as `non_agent_runs`.
- `RunTrace` holds:
  - run_id, ts, qid and question;
  - every tool span in file order, which is call order because tool spans never nest;
  - the final `submit_answer` span;
  - the logged verdict, from `run_agent.output.citation_checks`. It's the live verdict even on a
    budget-exhausted run.
- A run with no `submit_answer` span (a prose fallback or a crash) is counted as
  `skipped_no_submit`.
- Rejected `search_filings` calls write no span, so their content is outside the hash. The module
  docstring says so.

**Rebuild.** `rebuild_results(run, search=agent.run_search) -> (all_results, call_records)` replays
**every** tool span in the run through the agent's own code:
- `get_financial_fact` → `_dispatch_get_financial_fact` (it includes the year coercion)
- `compare_financial_metric` → `_dispatch_compare_financial_metric`
- `calculate` → `_dispatch_calculate`
- `search_filings` → `search(query, ticker, all_results)`

Every tool span means spans after the last submit too, because the budget-exhausted path verifies
against the final `all_results`.

Each call record holds `{tool, content_sha256, observed}`. The content is the exact string the
model would receive. `observed` holds the fields that fidelity compares.

A per-call exception is recorded on the run as `replay_error`, and that run's replay stops. A broad
`except` is deliberate there, with a comment: one bad historical record must not abort a replay of
hundreds of runs.

Only real I/O is untested:
- The default search binding and the live XBRL path get `# pragma: no cover` where they appear.
- Routing, hashing, the `all_results` bookkeeping and error capture are unit-tested, with `search`
  injected and `agent.call_get_financial_fact` / `call_compare_financial_metric` monkeypatched.

`hybrid_search` results are memoized by `(query, ticker)` for one invocation. First searches repeat
the question verbatim, so this cuts runtime a lot. It's valid only if the Verification step 4
determinism check passes.

**Environment guards.** Before any agent call:
- Disable tracing (`tracing.TRACING_ENABLED = False`, `tracing.TRACE_LOG_PATH = ""`). Both are
  read at call time, so replays never write to `traces.jsonl` or Langfuse.
- Fail fast unless the working directory is the repo root. `xbrl_facts.CACHE_DIR` is relative to
  it, so anywhere else every lookup misses the cache.
- Snapshot the `xbrl_cache/` listing before and after, and report any new files in the summary.
  A miss fetches live SEC data and writes to the cache silently, and newer data can create
  spurious drift.

**Fidelity (pure).** `fidelity(call_records, logged_spans)` compares each call with its logged span
output:
- search: `result_count`
- fact and calculate: `found` and `value` (`agent.py:1991,2028`)
- compare: `found` and `companies` (`agent.py:2010`)

Any mismatch marks the run `drifted` (the corpus or an XBRL value changed since), so its verdict is
low-confidence.

**Verdict and grade.**
- The current verdict is `submission_warnings(final_submit.input, all_results, question)`, over the
  run's full rebuilt `all_results`.
- Numeric and comparison qids are graded with
  `eval_harness._grade_by_type(q, answer_text, all_results)` → `correct: bool`. Judged and unknown
  qids get `correct: None`.
- Grading happens offline, so no join to eval reports is needed.

**Output.**
- `--out` defaults to `trace_logs/replay-<UTC timestamp>.json` (gitignored), so nothing is
  overwritten.
- The JSON holds a header (since, until, trace file, git SHA) and one record per run: run_id, ts,
  qid, logged_checks, now_checks, now_messages, correct, drifted, replay_error and calls.
- The stdout summary follows the `analyze_citation_gate.format_summary` style:
  - runs replayed, skipped, non-agent, drifted and errored, plus new cache files;
  - refused, then and now;
  - recovered (refused → passed), split into graded correct, graded wrong (a true positive lost)
    and ungraded;
  - newly refused (passed → refused), split into graded correct (a new false positive) and graded
    wrong;
  - capped qid lists.

**`--compare base.json` (pure `compare(base, cand)`).**
- The candidate run uses the baseline's since/until by default, and refuses an explicit mismatch.
  The trace file keeps growing between the two runs.
- It reports the same buckets against the baseline, plus:
  - check-list changes that don't flip the outcome;
  - **tool-result drift**, meaning any call's `content_sha256` differs;
  - runs present on only one side.
- Exit code 1 on any verdict change or tool-result drift, otherwise 0. A pure refactor must exit 0.

**CLI:** `--file`, `--questions`, `--since`, `--until`, `--qid` (repeatable), `--out`,
`--compare`.

**Deliberately out of scope:**
- The counterfactual rule probes (P1/P2/P7) and scratch `classify.py`. A candidate rule is the
  branch's code, replayed against master's baseline.
- S1's "known-wrong set". Offline grading covers numeric and comparison questions. Judged questions
  are reported as ungraded.

### Step 3: tests, manual script, rules

- `tests/test_analyze_gate_replay.py`, TDD with synthetic trace records:
  - `group_runs`: ordering; since/until; skipped with no submit; non-agent MCP spans; the verdict
    taken from `run_agent`; a run with tool spans after the last submit (budget-exhausted shape)
  - `rebuild_results` with injected fakes: routing, hashes, error capture
  - `fidelity`: match, count mismatch, value change, found flip
  - summary buckets with the graded splits
  - `compare`: identical → 0, outcome flip, check-list change, hash drift, one-sided runs,
    since/until inheritance and mismatch refusal
  - CLI parsing, and the working-directory guard
- `tests/manual/verify_gate_replay.py`: a real rebuild on a few named run_ids, including a
  budget-exhausted one such as `da3be66608ff`. It prints fidelity, verdicts and new cache files.
- Add the tool's live search/XBRL path to `.claude/rules/live-code-tdd.md`.

### Critical files

- `agent.py`:
  - `_handle_submit_turn` ~2207 and `_dispatch_search_filings` ~2032 (extractions);
  - `_finalize_after_budget_exhausted` ~2354 (fix);
  - dispatch bodies 1970-2029 (reused).
- `trace_query.py` (`load`, `question_ids`, `_iso_prefix`) and `eval_harness.py` (`_grade_by_type`,
  `load_questions`), both reused.
- New: `analyze_gate_replay.py`, `tests/test_analyze_gate_replay.py`,
  `tests/manual/verify_gate_replay.py`.
- `BACKLOG.md`, `.claude/rules/live-code-tdd.md`.
- Docs: `docs/plans/2026-09-28-gate-replay-tool.md` (a repo copy of this plan, saved right after
  approval), `docs/reviews/2026-09-28-gate-replay-tool.md`, and `PROJECT_INDEX.md` Recent lines.

### Commits (suggested; commits only when the user asks)

0. BACKLOG step 0.
1. A: the extractions, a pure refactor.
2. B: the budget-exhausted fix, a behavior change.
3. C: the tool, its tests, the manual script, the rules update and the docs.

## Testing and verification

1. `ruff check .`, `pyright .` and `pytest --cov=. --cov-report=term-missing -q` all pass, with 90%
   on the changed `agent.py` lines and 80% on the tool.
2. The model-input snapshot passes unchanged.
3. **Re-derive the known results** (the reachable part of S1's test). Run
   `python analyze_gate_replay.py --since 2026-09-19T03:12` and check:
   - The run count and refused count cover the map's 38 refusals over 478 runs, allowing for runs
     added since.
   - The 5 runs from 09-21/22 that the map records as drifted show as drifted, and those that
     matched show as clean.
   - The refusals the map records as fixed (the header strip, identities, percent identity and
     unprefixed header) show as recovered.
   - Refused-run verdicts match the scratch script run at the same HEAD.
   - The "17 of 38 under Decisions 4/12" figure is not re-derived: it needs the dropped probes.
4. **Determinism:** replay twice at the same HEAD with `--compare`, and it exits 0. That validates
   the memoization and the equivalence use. If it doesn't exit 0, find out why before relying on
   the tool.
5. Record the wall-clock time for the `--since` run and for an unfiltered run. No Gemini quota is
   used. `traces.jsonl` has the same line count before and after, and any new cache files are
   reported.

## Plan review

Reviewer: `plan-reviewer` (Opus), 2026-09-28. It found 10 issues, all folded in:

1. **High, fixed.** The logged verdict came from the wrong span on budget-exhausted runs. It now
   comes from `run_agent.output.citation_checks`, and the replay verifies against every tool span.
   There's a test for tool spans after the submit.
2. **Med, fixed.** The second gate call site (`agent.py:2358`) had a latent `KeyError`. It now goes
   through the helper, as its own behavior-change commit B.
3. **Med, fixed.** Fidelity was too weak. It now compares `value` and `companies`.
4. **Med, fixed.** The whole-function pragma hid testable logic. The search binding is now
   injected, and only real I/O carries the pragma.
5. **Med, fixed.** The search path duplicated dispatch code. `run_search` is extracted, and the
   rationale is corrected: the risk is re-validation, not re-resolution.
6. **Med, fixed.** XBRL cache misses were silent. The cache listing is now diffed before and
   after, and there's a working-directory guard.
7. **Low, fixed.** MCP root spans are now counted as non-agent runs. Unhashed rejected searches
   are documented.
8. **Low, fixed.** `--compare` now inherits since/until, and `--out` defaults to a timestamped path.
9. **Low, fixed.** Searches are memoized, with the runtime to be measured instead of assumed.
10. **Low, fixed.** The dropped parts of S1 are named in Out of scope and Verification.

Checked fine by the reviewer:
- Disabling tracing through module globals works.
- `get_financial_fact` spans log the args before coercion.
- Search spans log the resolved args.
- File order equals call order.
- All submit spans carry `checks`.

## Review log

Full findings and dispositions: `docs/reviews/2026-09-28-gate-replay-tool.md`.

- **Round 1** (snapshot `f5edd41`; Substantial: critical-core `agent.py`). Passes: `/code-review`
  high, `arch-reviewer` (opus), `security-reviewer`, `/simplify` (4 angles). 24 unique findings: 18
  fixed, 1 deferred to BACKLOG (cwd-relative `xbrl_cache`), 5 verified with no fix needed. Security
  and efficiency found nothing.
- **Round 2** (delta `f5edd41..38116ed`). Passes: `/code-review` low, `arch-reviewer` (opus),
  `security-reviewer`. 4 findings, all fixed: a refusal event missing `withheld_answer` was misread
  as prose-final; the working-directory check ran after the `--out` check; an unrealistic test
  fixture; a stray BACKLOG blank line. Security was clean.
- **Round 3** (delta `38116ed..1d9bbf7`). Passes: `/code-review` low, `arch-reviewer` (opus),
  `security-reviewer`. No findings.
- **Round 4** (delta `1d9bbf7..211ae33`). This round restored memoization after the A/B timing
  (user decision). Passes: `/code-review` low and `security-reviewer`. No findings; the review is
  closed.

## Addendum (2026-09-28, implementation)

- **`--compare` replays the baseline's run_ids instead of inheriting since/until.** That's simpler,
  and it's exact: newer runs in a grown trace file are excluded without a timestamp bound. Passing
  `--since`/`--until`/`--qid` with `--compare` is an argument error.
- **Drifted verdict changes get their own bucket against logged verdicts.** The first live run
  showed 12 "newly refused" runs. All 12 were drifted: a `get_financial_fact` that failed at run
  time now succeeds (fiscal-year fix `264fbc6`), which shifts citation indices. Against a baseline
  both sides rebuild the same sources, so drifted runs count normally there.
- **Captured span output instead of the plan's `observed` derivation.** The replay patches
  `tracing._write_local_log` with an in-memory sink. The dispatch bodies then log their own
  found/value/companies, which fidelity compares with the logged span, so nothing is re-derived.
- **Memoization.** The plan first said it didn't speed anything up, based on 17m52s against
  18m24s. Both of those runs had the cache, so the comparison measured nothing. The review
  removed it on that basis, and the next full replay took 35m46s. A timed A/B over 176 runs took
  597s without the cache and 383s with it, so it was restored (round 4). 97% of replay time is
  the cross-encoder rerank.
- `cache_listing` is public, since the manual script uses it.
- **Changes from review:**
  - **Final submit.** The final submit is the last one whose text equals the run's final answer
    (`run_agent.output.answer` if it passed, the refusal event's `withheld_answer` if refused).
    A run whose final answer matches no submit ended on the prose path after a submit. It is
    skipped and counted as `skipped_prose_final`. There were 0 such runs in all 1,155 traced runs,
    but the shape is reachable.
  - **`--compare` exit rule.** It exits 1 on any flip; any check-count or warning-message change;
    tool-result hash drift; a new or changed replay error; or a run found on only one side. A run
    that errors identically on both sides is listed, not failed.
  - **`--out`.** It defaults to the `config.TRACE_LOG_PATH` directory, and a missing directory is
    rejected before the replay starts.
  - **Routing.** Non-search tools route through `agent._dispatch_tool_call`, not a copied routing
    table.

### Live verification results (HEAD `7571216` plus this diff)

- `--since 2026-09-19T03:12`: 472 runs replayed, 0 errored, 18 drifted.
  - Skipped: 54 non-agent, 1 with no submit, 7 with no output.
  - Refused: 38 then (matching the map's 38), 44 now.
  - Recovered: 6, all graded correct. These are exactly the map's "6 already fixed".
  - All 12 newly refused runs are drifted. 5 of the 38 refused runs are drifted, which matches
    the map's 33/38 fidelity.
  - `traces.jsonl` stayed at 8514 lines, with no new `xbrl_cache` files.
- Determinism: `--compare` against that run exits 0, with 0 verdict changes and 0 tool-result
  drift over 472 runs.
- Scratch `replay_gate.py` at the same tree: 38/38 refused-run warning lists are identical.
- `tests/manual/verify_gate_replay.py`: the budget-exhausted run `da3be66608ff` is refused then
  and now, and is correctly flagged as drifted. The clean pass `981513aa83f1` passes with no drift.
