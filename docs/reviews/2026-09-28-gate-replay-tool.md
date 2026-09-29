# Review: gate replay tool (`analyze_gate_replay.py`) and the `agent.py` extractions

Plan: `docs/plans/2026-09-28-gate-replay-tool.md`. This change adds an offline tool that re-gates
every traced run's final `submit_answer` through today's gate and compares the verdicts with the
logged ones, or with a saved baseline (`--compare`). It also extracts `submission_warnings` and
`run_search` in `agent.py` and fixes a `KeyError` in `_finalize_after_budget_exhausted`. The suite
had 1077 tests before review. The review ran as Substantial because `agent.py` is critical core
and the diff was about 1,500 lines.

## Round 1

Snapshot `f5edd41`. Passes: `/code-review` high, `arch-reviewer` (opus), `security-reviewer`,
`/simplify` (reuse, simplification, efficiency and altitude agents).

`/code-review`:

1. **High**: a run can log a refused submit and then finish on the prose path. The replay
   re-gated that submit, so its verdict came from a different checker than the live one.
   `[Fixed]` The final submit is now the last submit whose text equals the final answer (the
   passed answer, or the refusal event's `withheld_answer`). A run where none matches is skipped
   as `skipped_prose_final`. There were 0 such runs in all 1,155 traced runs, but the path is
   reachable.
2. **Med**: `--compare` ignored warning messages, so a rewording of the retry feedback passed as a
   pure refactor. `[Fixed]` Messages are now compared against the baseline.
3. **Med**: a run that errors identically in the baseline and the candidate failed every later
   `--compare` (arch raised the same). `[Fixed]` Such runs go to `errored_unchanged`, which is
   listed but doesn't fail.
4. **Low**: `non_agent_runs` was counted before the window, qid and run_id filters. `[Fixed]`
5. **Low**: the report was written only at the end of an 18-minute replay, so a bad `--out`
   directory lost the whole run. `[Fixed]` The directory is checked up front, and the summary is
   printed before the write.
6. **Low**: on the budget-exhausted path, schema-invalid cached args log `tool_call_rejected` a
   second time. `[Verified, no fix needed]` The path is rare (before this change it crashed), and
   the second event truthfully records that the gate rejected the args again at finalization.
7. **Low**: `memoized()` was kept even though it measured no speed-up. Removed in round 1, then
   `[Disputed]` and restored in round 4. The "no speed-up" note in the plan was wrong: it
   compared two runs that both had the cache (see Live verification).
8. **Low**: `_dispatch` copied `agent._dispatch_tool_call`'s routing. `[Fixed]` Non-search tools
   now go through the agent's router.
9. **Low**: `require_repo_root` works around `xbrl_facts.CACHE_DIR` being relative to the working
   directory. `[Deferred → BACKLOG]` The fix belongs in `xbrl_facts` and `config`, both outside
   this diff, and it fits the upcoming `src/` move. Item: `[refactor, Low, Standard]`.

`arch-reviewer` (opus):

10. **Nit**: `submission_warnings`' docstring recorded run history ("on every live run tried").
    `[Fixed]`
11. **Nit**: `final_submit` was typed Optional but can't be None. `[Fixed]`
12. **Nit**: `_CAPTURED` was cleared only before non-search calls. `[Fixed]` It is now cleared at
    the top of every replayed call.
13. **Nit**: `_then_verdict` looked like a getter but wrote to summary buckets. `[Fixed]` It was
    replaced by `_tally_against_base`, which makes those writes explicit.
14. **Q**: the stricter `--compare` exit rule wasn't recorded in the plan. `[Fixed]` It is now in
    the plan's Addendum.
15. **Nit**: `--out` defaulted to the `--file` directory, not `trace_logs/`. `[Fixed]`
16. **Risk**: no test ran the real dispatch bodies, so renaming a logged field would have
    silently marked every run drifted. `[Fixed]` A new test runs the real `_dispatch_*` with only
    the lookups stubbed, and asserts the observed fields.
17. **Nit**: BACKLOG still said the replay tool was in progress. `[Fixed]`
18. **Q**: the review file and its index line were missing. `[Fixed]` (this file)
19. **Nit**: a test hard-coded `top_k` 5. `[Fixed]` It now uses `CHUNKS_PER_SEARCH`.

`security-reviewer`: no findings. It checked that replayed arguments still pass through the same
`validate_tool_args` boundary, that the replay sends nothing to Langfuse or the trace log, and
that the tool has no exec or deserialization sinks.

`/simplify`:

20. **Reuse**: the replay hand-rolled `agent._count_citation_checks`. `[Fixed]`
21. **Simplification**: `now_refused` can be derived from `now_checks`. `[Verified, no fix
    needed]` The explicit field keeps the saved reports readable and is None on errored runs.
22. **Simplification**: the search branch builds its observed dict by hand. `[Verified, no fix
    needed]` It is cosmetic, and the one-key literal is clearer.
23. **Simplification**: `compare_failed` builds two lists. `[Verified, no fix needed]` Cosmetic.
24. **Altitude**: `_OBSERVED_FIELDS` duplicates the dispatch bodies' span keys. `[Verified, no fix
    needed]` The real-dispatch test from finding 16 enforces them.

Efficiency: no findings.

## Round 2

Delta: `f5edd41..38116ed`. Passes: `/code-review` low, `arch-reviewer` (opus),
`security-reviewer`.

1. **Risk** (code-review and arch): a refusal event without `withheld_answer` was stored as `""`,
   so that refused run was miscounted as prose-final. `[Fixed]` It now keeps None, which falls
   back to the last submit. A test covers it.
2. **Nit** (arch): the `--out` check ran before `require_repo_root`, so running from the wrong
   directory reported the wrong error. `[Fixed]`
3. **Nit** (arch): a test fixture used a submit sequence the agent can't produce. `[Fixed]`
4. **Nit** (arch): an extra blank line in BACKLOG. `[Fixed]`

Security: no findings.

## Round 3

Delta: `38116ed..1d9bbf7`. Passes: `/code-review` low, `arch-reviewer` (opus),
`security-reviewer`. No findings.

## Round 4

Delta: `1d9bbf7..211ae33`, which restores `memoized()` and its test at the user's decision (see
Live verification). Passes: `/code-review` low, `security-reviewer`. No findings.

## Live verification

- Round 1 state (see the plan's Addendum):
  - `--since 2026-09-19T03:12` replayed 472 runs. It re-derives the map's 38 refusals, and the 6
    recovered runs all grade correct.
  - A second run compared against the first exits 0.
- After the review fixes (tree `1d9bbf7`):
  - `--compare` against the round-1 replay exits 0. All 472 runs match, including the warning
    messages that are now compared, with 0 prose-final skips.
  - `traces.jsonl` is unchanged at 8514 lines, and there are no new `xbrl_cache` files.
  - Wall time was 35m46s, against about 18m with memoization. A timed A/B over the 176 runs
    since 2026-09-26 took 597s without the cache and 383s with it (81 of 216 searches were
    hits). Finding 7's premise, that memoization gave no speed-up, came from comparing two runs
    that both had it.
  - The profile of the 41 runs since 2026-09-28 (174s) puts 97% of replay time in the
    cross-encoder rerank inside `retrieval.hybrid_search`, about 2.8s per search on CPU. XBRL
    lookups and the gate itself are negligible.

## Outcome

Everything shipped except finding 9, which is open in `BACKLOG.md` as `[refactor, Low,
Standard]`. The suite passes (1085 tests). The review closed clean after 4 rounds, with no
escalation.
