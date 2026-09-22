# Migrate ruff to a hard pre-commit gate, decoupled from pyright

**Date:** 2026-09-21

## Context

`docs/decisions/2026-09-21-ruff-complexity-refactor.md` brought
`ruff check .` to 0 errors full-repo (from a 155-violation baseline).
With the baseline actually gone, ruff's own adoption decision
(`docs/decisions/2026-09-15-adopt-ruff-linter.md`) and pyright's
(`docs/decisions/2026-09-15-adopt-pyright.md`) both named "migrate to a
hard pre-commit gate once enough of the codebase is clean" as the
eventual next step, but tied ruff's and pyright's migrations together
— reasonable at the time, since both baselines (155 and 154 violations)
were comparable in size. Pyright's basic-mode baseline is still 117
errors, entirely in unrelated pre-existing test files untouched by this
refactor.

## Decision

Migrated ruff alone to a hard pre-commit gate: `githooks/pre-commit`
(the tracked source of truth, since git doesn't version-control hooks
itself) now runs `ruff check .` before the existing pytest step, and
blocks the commit outright on any failure — full-repo, not just
changed files. Pyright stays on its prior changed-files-scoped review
convention, on its own independent timeline.

## Why

This revisits the 2026-09-15 adoption decisions' joint-migration
premise: new evidence (ruff's baseline reaching 0, unlike pyright's
unchanged 117) means the two tools no longer share the same trigger
condition. Gating pyright today would block every future commit on
debt this refactor never touched, for no benefit — the "migrate
together" plan was a reasonable default when both baselines were
comparable, not a commitment to keep them in lockstep regardless of how
each one's own baseline evolves. Pyright gets its own independent
`BACKLOG.md` item instead of a shared one.

## Files touched

`githooks/pre-commit` (new ruff step; also fixed a stale comment
pointing to the renamed `PROJECT_CONTEXT.md` instead of stating the
one-time setup command directly), `.git/hooks/pre-commit` (synced
copy, so the gate is active in this checkout immediately), `pyproject.toml`
(`[tool.ruff]`/`[tool.pyright]` preceding comments updated to the new
rollout stages), `CLAUDE.md` (project) (`This project's linter`/`This
project's type checker` sections' rollout-stage paragraphs rewritten),
`BACKLOG.md` (ruff's migration item deleted as done; pyright's reworded
to drop the now-dangling reference to it), `PROJECT_INDEX.md` (new
`Recent` entry).

## Verification

Confirmed the gate actually blocks, mirroring
`docs/decisions/2026-08-14-tdd-adoption-pre-commit-hook.md`'s own
verification method for the original pytest gate: appended a
deliberate ruff violation (an unused, non-top-of-file `import os`) to
`analyze_citation_gate.py`, staged and committed — the hook printed
ruff's `E402`/`F401` findings and blocked the commit before pytest ever
ran, exit code 1. Reverted the scratch change (`git restore --staged`
+ `git checkout --`), confirmed the working tree was clean again. Then
ran `ruff check .` (0 errors) and the full `pytest` suite (707 passing)
directly, confirming the doc/config edits themselves introduced no
regression.

## Related

Amends the joint-migration plan in
`docs/decisions/2026-09-15-adopt-ruff-linter.md` and
`docs/decisions/2026-09-15-adopt-pyright.md`. Builds on
`docs/decisions/2026-09-21-ruff-complexity-refactor.md` (the baseline
cleanup that made this possible) and
`docs/decisions/2026-08-14-tdd-adoption-pre-commit-hook.md` (the
original pytest-only gate this extends).
