# `eval_harness.py`: `--ids` / `skip` question filtering

**Date:** 2026-08-19 (commit `8a32c78`, "Add --ids / skip filtering to
eval_harness.py so a subset of questions can be run")

## Context

Eval questions had grown past what's comfortable to re-run in full at
local Ollama speed (each full 25-question run took 25-30 minutes).

## Decision

`--ids id1,id2,...` runs only the named questions, in file order. An
optional `"skip": true` field on individual questions excludes them from
the default full run without deleting them; `--include-skipped` forces
them back in. Explicit `--ids` always wins over a question's own `skip`
flag. An unknown ID raises immediately rather than silently running
fewer questions than asked for.

## Why

New pure helper `_select_questions(questions, ids, include_skipped)` is
kept separate from `run_eval()`'s live-agent loop specifically so the
filtering logic is unit-testable without any network/Ollama calls.

## Files touched

`eval_harness.py`.

## Verification

`--ids aapl-net-income-fy2025,nvda-revenue-fy26` verified live to run
exactly those 2 of 25, in file order. 6 new tests, 179/179 full suite.

## Related

This became the standard tool for the project's "targeted spot-check"
workflow used throughout every later live-code change (see project
`CLAUDE.md`'s spot-check-eval rule).
