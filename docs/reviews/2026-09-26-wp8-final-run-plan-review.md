# Review: WP8 plan, final full run and prompt-audit wrap-up (one independent plan-review round)

Plan: `docs/plans/2026-09-26-wp8-final-run.md`. The plan runs the full 48-question suite once
at agent `7aec53939ce3` and compares the 47 shared questions against the two pre-audit full
runs, `20260921T222521Z` (39/47) and `20260922T062823Z` (38/47). It explains every drop from
traces, reruns only the unexplained ones, writes the WP8 and rollout summary decision files,
and files the roadmap's deferred items. HEAD was `91c3bc8`.

## Pass 1: self-check of the roadmap's Steps 8–9 against HEAD `91c3bc8`
- **[Changed in plan] Question count:** the suite has 48 questions; the baselines have 47.
  `nvda-revenue-yoy-growth-q1fy27` (restored in `3bae1d8`) is reported separately.
- **[Changed in plan] Model:** the baselines ran on the `gemini-flash-lite-latest` alias,
  while this run is pinned. Recorded as a caveat.
- **[User decision] Model pin:** keep `gemini-3.5-flash-lite` (the roadmap says to unpin or
  record keeping it).
- **[User decision] Reruns:** rerun unexplained drops 3× on the same day.
- **[Moot]** Step 9 (f), recorded at WP7. **[Nothing to file]** Step 9 (c): no WP was
  reverted.

## Round 1: plan-reviewer (Opus)

**Must-fix:** none.

**Should-fix, all adopted:**
1. **The bar:** it is the 47-question `cand` sum ≥ 38. The compare tool's REGRESSED flags,
   exit code 1, "panel total" footer and `answer_model` warning are expected with 2 base runs
   against 1 candidate run, and don't block.
2. **A run that is cut short is invalid.** Dropped rows or `RESOURCE_EXHAUSTED` mean no
   reruns and a full rerun on the next quota day. A failed bar or an unexplained regression
   gets a BACKLOG item and a regression note.
3. **The rerun rule is fixed in advance.** ≥ 1/3 is noise; 0/3 after 2/2 is an unexplained
   regression; 0/3 after 1/2 is flaky and goes on watch.
4. **Drops are explained for any question that passed either baseline,** including the three
   that went 1/2.
5. **Panel-question drops are checked first against the WP7 screen,** which ran at the same
   fingerprint.
6. **The trace kinds `final_turn_forced` and `tool_arg_coerced` postdate the baselines.**
   Baseline windows start at their first `run_agent` span.
7. **The traces can't measure quota.** The gate checks that there are no `run_agent` spans,
   and reruns are capped at 5 questions.

**Nits, adopted:**
8. **The gate also checks** the `.env` pin and the snapshot test.
9. **The summary table's rows** for WP1, WP2 and WP7 are specified.
10. **The index** goes 44 → 48.

**Verified by the reviewer:**
- **Baselines:** pass counts, identical question sets, and 37 questions passing in both.
- **Explicit mode** handles unstamped reports and candidate-only questions.
- **Fingerprint** `7aec53939ce3`.
- **Commits since WP7** don't change what the model sees.
