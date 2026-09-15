# Repo folder reorganization: `verify_*.py` → `tests/manual/`, eval data → `eval/`

**Date:** 2026-08-26

## Context

Pure structural cleanup, no behavior change. The repo root had
accumulated two standalone live-verification scripts sitting next to the
pytest suite in spirit but not in location, and eval harness data mixed
in with top-level code scripts.

## Decision

`verify_mcp_server.py`/`verify_period_labels.py` → `tests/manual/` (`git
mv`); each needed a one-line `sys.path.insert(0, ...)` shim, since `python
tests/manual/verify_x.py` sets `sys.path[0]` to the script's own
directory, not the CWD. `eval_questions.jsonl` + `eval_results/` →
`eval/` (`git mv`, 46 files). `eval_harness.py` itself stays at the repo
root — moving it would have forced `python -m eval.eval_harness`
everywhere for no real benefit, whereas keeping it at root and moving
only its data matches the repo's existing pattern of top-level data
folders alongside top-level code.

## Why

Historical prose mentions of the old paths were deliberately left
unchanged in this doc's older write-ups — same "the changelog describes
what was true at the time" treatment already given to `answer.py`'s
retirement section.

## Files touched

`verify_mcp_server.py`, `verify_period_labels.py` (moved),
`eval_questions.jsonl`, `eval_results/*` (moved), `eval_harness.py`
(path constants only).

## Verification

Re-ran both moved scripts live, confirming identical correct output.
Re-ran `eval_harness.py --ids <question>` live to confirm it still finds
the questions file and writes to the new location. Full suite 275/275.

## Related

None.
