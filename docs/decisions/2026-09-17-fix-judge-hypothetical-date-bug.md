# Fix the eval judge's "hypothetical/future date" mis-grading bug

**Date:** 2026-09-17

## Context

`BACKLOG.md` had a latent item: `grade_judged()` (the LLM-as-judge
grading used for `judged`-type eval questions) sometimes failed a
genuinely correct, well-cited answer because it cited a real, current
SEC filing date (2025/2026) that falls after the judge model's own
training cutoff — the judge reflexively called this "hypothetical" or
"future" data. First logged 2026-09-14 from a single, unreproduced
observation, with an explicit trigger: fix it "if it recurs at a rate
that shows up reliably."

The full 47-question baseline run right after the 2026-09-17
uncovered-number-gap fix (`eval/eval_results/20260917T205406Z.json`)
reproduced this exact failure mode 3 times in one run, independently:
`msft-segment-revenue-comparison-q3fy2026`, `five-company-gross-margin-
ranking-fy2025`, `five-company-operating-margin-ranking-fy2025`. All
three had `citation_warnings: []` — cleanly-cited, correctly-grounded
answers — and were failed anyway on "fabricated hypothetical" grounds.
The trigger condition was met.

## Decision

Two additive changes to `eval_harness.py`, no agent-side code touched:

1. `JUDGE_SYSTEM_PROMPT` gained one instruction, scoped narrowly: don't
   treat a date as fabrication evidence merely because it's unfamiliar
   (post-cutoff); only treat a date as hypothetical if it falls after
   the real current date the prompt supplies. The "at or before today"
   condition is stated directly in this same sentence, not split across
   the system prompt and user prompt as separate claims that only work
   in combination — an independent review round caught the first-draft
   wording doing exactly that (a system-prompt clause asserting dates
   are unconditionally real, with the actual "at or before today" gate
   living only in the user prompt) as a latent fragility, even though
   the two strings happened to combine correctly as shipped.
2. `grade_judged()`'s `user_prompt` now injects the real wall-clock date
   (`datetime.now(timezone.utc)`, reusing the exact pattern
   `save_report()` already uses for its own timestamp at
   `eval_harness.py:411`) so the judge has a concrete "today" instead of
   its own stale internal sense of the present.

## Why

Root cause, confirmed directly against a real result row (not inferred):
`five-company-gross-margin-ranking-fy2025`'s actual JSON in
`20260917T205406Z.json` shows `has_citation: true`, `citation_warnings:
[]` — nothing wrong with the answer — while the judge's own FAIL reason
read "used fabricated, hypothetical future financial data for periods
that have not yet occurred." `JUDGE_SYSTEM_PROMPT`/`grade_judged`'s
`user_prompt` gave the judge zero grounding for what "today" is, so a
judge model trained before 2026 had no way to tell a real 2026 filing
date from a hallucinated one in the answer being graded.

This is purely an eval-measurement defect, not an agent defect — the
fix touches no agent-generation code and carries zero risk of changing
what the agent actually answers.

Injecting wall-clock time rather than hardcoding a "2025/2026 are real"
date range targets the actual root cause (missing temporal grounding)
so the fix stays correct as real time moves forward, instead of needing
another patch next year.

**Assumption made explicit** (flagged by independent review): this
implicitly assumes grading happens contemporaneously with generation.
True for every call site today — `grade_judged` only ever runs
synchronously inside `run_eval`, immediately after the answer is
generated; no regrade-from-saved-report tool exists anywhere in this
codebase. Would need revisiting if one is ever added.

**Caveat**: `BACKLOG.md`'s original item noted this failure mode did
NOT reproduce in an earlier baseline (the judge is non-deterministic
across live calls of the identical grading prompt) — 3/3 in one run was
strong enough evidence to fix, but shouldn't be read as "this always
fires."

**Process notes from two independent review passes:**
- The plan itself was reviewed before implementation (per
  `.claude/rules/plan-review-blast-radius.md`, which this change also
  extends to name `eval_harness.py`'s `grade_judged`/`JUDGE_SYSTEM_PROMPT`
  going forward — a "trust the numbers" risk category: this code decides
  what counts as PASS/FAIL eval-wide without ever showing up as an agent
  regression). That review confirmed the diagnosis against real code and
  data, and flagged that the system-prompt wording should be narrowly
  scoped rather than a blanket "assume all dates are real" claim.
- The finished diff was reviewed a second time and found two more
  issues, both fixed before this doc was written: (a) the narrow-scoping
  intent from the plan review hadn't fully survived into the shipped
  wording — the "at or before today" gate lived only in the user prompt,
  leaving the system prompt's own sentence over-broad in isolation; (b)
  the new regression test computed "today" via a second, independent
  `datetime.now(timezone.utc)` call and compared it to the one inside
  `grade_judged`, a real (if rare) UTC-midnight race — changed to a
  format-only regex assertion instead.

## Files touched

- `eval_harness.py` — `JUDGE_SYSTEM_PROMPT` + `grade_judged()`'s
  `user_prompt` construction.
- `tests/test_eval_harness.py` — one new regression test
  (`test_grade_judged_user_prompt_includes_todays_real_date`) asserting
  the constructed prompt includes an injected current-date string,
  using the file's existing mocked-`complete()` pattern.
- `.claude/rules/live-eval-verification.md` — added `eval_harness.py`
  to the named scope requiring a live spot-check beyond unit tests.
- `.claude/rules/plan-review-blast-radius.md` — added
  `eval_harness.py`'s `grade_judged`/`JUDGE_SYSTEM_PROMPT` as a new
  "changes what counts as PASS/FAIL eval-wide" risk category.

## Verification

- Full unit test suite: 681 passing.
- `ruff`/`pyright` scoped to changed files: zero new violations (5
  pre-existing `E501`s in `tests/test_eval_harness.py`, none on touched
  lines; `pyright` 0 errors both before and after).
- Live spot-check: the 3 confirmed-affected questions plus 1 regression
  guard (`five-company-net-margin-ranking-fy2025`, already passing) ran
  clean twice in a row — 7/7 passes, zero "hypothetical"-style
  mis-grades (`eval/eval_results/20260917T212334Z.json`,
  `20260917T212423Z.json`).
- Full 47-question baseline: 37/47 → 44/47
  (`eval/eval_results/20260917T213518Z.json`). All three target
  questions flipped `False → True`. Of the other 6 flips (5 more
  `False → True`, 1 `True → False`), none are `judged`-type questions —
  this change's code path (`grade_judged`) only runs for `judged`-type
  questions, so it structurally cannot have caused them; they're
  numeric/comparison-type questions subject to this project's
  already-documented agent-side, citation-gate non-determinism
  (`BACKLOG.md`).
- Independent review: one round on the plan (confirmed the diagnosis
  against real code/data, flagged the system-prompt scoping), one round
  on the finished code (found and fixed the two issues noted above).

## Related

Closes the 2026-09-14 `BACKLOG.md` item (eval judge date mis-grading).
Follow-up to the same-day `docs/decisions/2026-09-17-uncovered-number-gap-fixes.md`,
whose own confirmatory baseline (`20260917T205406Z.json`) is what
reproduced this bug 3 times in one run and met the fix trigger. Plan:
`C:\Users\riddh\.claude\plans\snug-jingling-pumpkin.md` (session-local
scratch file — this decision file is the durable record).
