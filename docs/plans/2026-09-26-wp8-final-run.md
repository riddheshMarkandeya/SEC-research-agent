# WP8: final full run and prompt-audit wrap-up

Roadmap: `docs/plans/2026-09-24-prompt-audit-roadmap.md`, Steps 8–9 (and "How this roadmap is
executed"). BACKLOG: the WP8 line. This plan records only what changed since the roadmap.

## Context
WP1–WP7 are closed: every prompt WP was accepted at its screen, and none was reverted. WP8
spends the roadmap's one full-suite run to check the audit's end state against the last two
full runs from before the audit. It then writes the rollout summary and files the deferred
items, which closes the roadmap.

**Tier:** Standard. No code changes; docs and one eval run. Nothing touches the blast-radius
paths.

## Changes since the roadmap
- **Two baselines, not unstamped runs of the same shape.** The comparison reports are
  `20260921T222521Z` (39/47) and `20260922T062823Z` (38/47).
  - Both have **47** questions. The suite now has **48**: `nvda-revenue-yoy-growth-q1fy27` was
    restored in `3bae1d8`.
  - It is reported separately, with no baseline, against its own historical runs.
  - The bar applies to the 47 shared questions. The roadmap's working bar is "38–39/47"; the
    48-question total is recorded alongside.
- **The baselines used the model alias.** Their `answer_model`/`judge_model` is
  `gemini-flash-lite-latest`. WP2 pinned `gemini-3.5-flash-lite`, which is what the alias
  resolved to on 2026-09-24. The baselines are from 09-21/22, so whether the alias pointed to
  the same model then is unknown. The decision file states this as a caveat, not a
  confound that has been ruled out.
- **The trace check uses `trace_query.py`** (added 2026-09-26), not a scratch script.
- **Model pin** (Step 9), user decision: **keep** `GEMINI_MODEL_NAME=gemini-3.5-flash-lite`,
  recorded as a decision. Every report since WP2 is on this model, and the baseline-improvement
  plan needs the same stability. Re-pin deliberately if the alias moves or the model is
  deprecated.
- **Step 9 (f)** is moot (already recorded at WP7). **Step 9 (c)** (confirmed-and-reverted
  findings) has nothing to file: WP3–WP7 were all accepted.

## Steps
0. **On approval:**
   - `git status` must be clean;
   - save this plan as `docs/plans/2026-09-26-wp8-final-run.md`;
   - save its plan review as `docs/reviews/2026-09-26-wp8-final-run-plan-review.md`;
   - mark the BACKLOG WP8 line IN PROGRESS;
   - add 2 index lines;
   - make one docs commit by path.
1. **Pre-run gate** (2026-09-27, after 07:00 UTC):
   - the tree is clean;
   - HEAD is past the step-0 commit;
   - the `agent` fingerprint is `7aec53939ce3` (`python -c "import prompts;
     print(prompts.prompt_fingerprint())"`);
   - no `run_agent` spans since 07:00 (`python trace_query.py counts --kind run_agent --since
     2026-09-27T07`). The trace log records runs, not Gemini requests, so it can't measure
     quota directly;
   - `.env` has `GEMINI_MODEL_NAME=gemini-3.5-flash-lite` (it's untracked, so the fingerprint
     can't show it);
   - the snapshot test is green (`pytest -q tests/test_model_input_snapshot.py`, no quota), or
     explicit mode excludes the report as unverified.
2. **The run.** `python eval_harness.py --backend gemini > <scratch log>`, 48 questions,
   about 250 requests, run in the background. Record the start and end times for the trace
   window.
3. **Compare.** `python compare_prompt_versions.py --base-files
   eval/eval_results/20260921T222521Z.json eval/eval_results/20260922T062823Z.json
   --candidate-files <new>` (explicit mode accepts the unstamped baselines).
   - **The bar is the 47-question sum ≥ 38**, not the tool's verdict. Sum the `cand` column
     (the new question is listed separately as candidate-only and left out of the total).
     These are expected and don't block:
     - **REGRESSED flags and exit code 1.** With 2 base runs vs 1 candidate, any question
       at 1/2 or 2/2 that fails drops ≥ 0.5.
     - **The "panel total" footer.** It was built for 13×3 panels.
     - **The `answer_model` differs warning.** The baselines used the alias; this run is
       pinned.
   - **Run cut short:** if `load()` reports dropped rows, or the log shows
     `RESOURCE_EXHAUSTED`, the run is invalid.
     - Skip the reruns.
     - Record the run.
     - Rerun the full suite on the next quota day.
   - Check `nvda-revenue-yoy-growth-q1fy27` against its earlier runs (`analyze_flakiness.py`,
     or its rows in the reports since `3bae1d8`).
4. **Explain each drop, without spending quota.** This covers every question that passed in
   **either** baseline and fails now. That includes the three that went 1/2:
   - `aapl-msft-employee-comparison`;
   - `nvda-gross-margin-fy26`;
   - `msft-rd-intensity-fy2025`.

   A **panel question** is first compared with its 3 WP7 screen runs, which have the same
   fingerprint `7aec53939ce3` (`20260926T085714Z/090017Z/090341Z`). If it passed there, the drop
   is noise, and it doesn't use rerun budget. For every other drop:
   - read the report row (`detail`, `gate_withheld_*`, `citation_warnings`);
   - read the run with `python trace_query.py runs --qid <id> --since <run start>`.

   **Targeted rerun** (user decision: yes): 3× on the drops the trace doesn't explain, run
   the same day.
   - **Hard cap: 5 questions.** That's about 125 requests, which fits within about 250 left
     after the run.
   - Run `python eval_harness.py --backend gemini --ids <ids>` three times, then compare
     explicitly with the baselines.
   - **Rule, fixed now:** passing at least 1 of 3 is **noise**. 0/3 on a question that passed
     2/2 before is an **unexplained regression**. 0/3 on a question that was 1/2 is
     **flaky, watch**.
   - **Outcome of an unexplained regression, or a sum under 38:** a BACKLOG item with a
     priority, and a regression note in the WP8 decision file, per
     `.claude/rules/live-eval-verification.md`. Code fixes stay out of scope for WP8.
5. **Grep for the judge flag:** `lenient parse disagrees` in the new report. There were 0
   hits in all reports so far. A hit files finding 7's trigger as met.
6. **Trace check** (run window vs the two baseline windows): `trace_query.py counts` by
   `kind,reason` for these kinds:
   - `tool_call_rejected`, `tool_arg_coerced`, `unmet_metric_request`;
   - `citation_gate_refused`, `final_turn_forced`, `llm_retry`.

   Plus `runs` for any drop.
   - **The baseline windows start at their first `run_agent` span.** A report's name is its
     end time, so the start has to come from the trace.
   - `final_turn_forced` (added 09-23) and `tool_arg_coerced` (added 09-26) postdate the
     baselines, so they are reported for the current run only.
7. **Docs** (one commit for the report, one for the docs, both by path):
   - **WP8 decision file** `docs/decisions/2026-09-27-wp8-final-run.md`: the run, the
     comparison, the drop explanations, the lenient grep, the trace counts, the model-pin
     decision, and the caveats (47 vs 48, alias vs pin).
   - **Summary decision file** `docs/decisions/2026-09-27-prompt-audit-rollout.md`: one table
     row per WP (WP1–WP8) with commit(s), fingerprint, panel B → C, outcome and watch flags,
     each linking its WP file.
     - WP1's row is its move checks (hash and golden outputs), not a panel.
     - WP2's row is the baseline, so it has no B.
     - WP7's figures come from its file as corrected in `cbc2bf4`. This is the roadmap's Step 9 file.
   - **BACKLOG (Step 9):**
     - (a) finding 7, deferred, moved to the **Watch list** with its trigger (`lenient parse
       disagrees` in a report);
     - (b) one Low item for notes 8–10: all-caps emphasis, tool bullets duplicating the
       descriptions, rule 9's size, the cross-surface duplicate sentences and the hard-coded
       "five companies";
     - (d) the baseline-improvement plan as the next piece of work, naming the "− 1" gate
       false positive and the Q4-hint vs judge conflict as candidates;
     - (e) the Step 7 follow-ups as one item: reason-bearing rejections via `on_reject`
       (including WP7 (d), boundary rejections), `calculate`'s generic missing-argument
       message, MCP search's silent `[]`, and WP7 (a), yoy prior-year naming;
     - delete the WP8 line;
     - the "From the 2026-09-24 prompt-audit roadmap" section keeps only the items still
       open.
   - **Index:** 4 Recent lines in total (44 → 48, no trim).
   - A self-check review of the docs, since there is no code.

## Out of scope
Any prompt or code change (including the "− 1" gate fix and the harness malformed-question
bug); re-stamping historical reports; Ollama; `/retro` (the user runs it).

## Critical files
- Read: `eval_harness.py`, `compare_prompt_versions.py`, `trace_query.py`,
  `analyze_flakiness.py`, the WP1–WP7 decision files, `docs/reviews/2026-09-24-prompt-audit.md`.
- Written: the new report, the two decision files, `BACKLOG.md`, `PROJECT_INDEX.md`, and the
  plan and plan-review copies.

## Verification
- **The roadmap's Step 8 bar:** the 47-question pass count is at or above 38, and every drop
  in a non-panel question is explained.
- The compare output and trace counts are in the WP8 decision file.
- The summary table has a row for every WP decision file.
- The docs-health pre-commit hook passes.

## Plan review (1 round, plan-reviewer on Opus)

**Must-fix:** none. Every factual claim checked out.

**Should-fix, all adopted**
1. **The compare tool's REGRESSED flags, exit code 1, "panel total" footer and `answer_model`
   warning aren't the bar.** The bar is the 47-question `cand` sum ≥ 38.
2. **A cut-short run is invalid, and a failed bar has a stated outcome.** A run cut short gets
   no reruns and a full rerun on the next quota day. A failed bar or an unexplained regression
   gets a BACKLOG item and a regression note.
3. **The rerun needs a fixed rule.** ≥ 1/3 is noise; 0/3 after 2/2 is an unexplained
   regression; 0/3 after 1/2 is flaky, watch.
4. **Drops now cover any question that passed in either baseline,** including the three at 1/2.
5. **Panel drops are checked against the WP7 screen first,** which ran at the same
   fingerprint, before any rerun budget is used.
6. **Two trace kinds postdate the baselines** and are reported for the current run only. The
   baseline window starts come from the first `run_agent` span.
7. **Quota can't be read from traces.** The pre-run gate checks for no `run_agent` spans, and
   the reruns have a hard cap of 5 questions.

**Nits, adopted**
8. The pre-run gate also checks the `.env` pin and the snapshot test.
9. The summary table's rows for WP1, WP2 and WP7 are stated.
10. The index goes 44 → 48, so no trim.

**Verified by the reviewer**
- The baselines are 39/47 and 38/47, with identical question sets; 37 questions pass in both.
- The new question is the only difference.
- Explicit mode keeps unstamped reports and lists the new question separately.
- The fingerprint is `7aec53939ce3`.
- The commits after WP7 don't change what the model sees.
