# Migrate pyright to a hard pre-commit gate

**Date:** 2026-09-22

## Context

`docs/decisions/2026-09-22-pyright-clean-refactor.md` brought
`pyright .` (basic mode) to 0 errors full-repo, closing the 117-error
baseline that `docs/decisions/2026-09-21-ruff-pre-commit-gate.md` left
unresolved when it migrated ruff alone to a hard gate one day earlier
and explicitly decoupled the two tools' migrations ("pyright stays on
its prior changed-files-scoped review convention... on its own
independent timeline"). With that baseline now gone, the original
joint-migration intent named in both
`docs/decisions/2026-09-15-adopt-ruff-linter.md` and
`docs/decisions/2026-09-15-adopt-pyright.md` — "migrate to a hard
pre-commit gate once enough of the codebase is clean" — is unblocked
for pyright too.

## Decision

Migrated pyright to a hard pre-commit gate, joining ruff:
`githooks/pre-commit` now runs `pyright .` between the existing
`ruff check .` step and the pytest step, and blocks the commit outright
on any failure — full-repo, not just changed files. Order is ruff →
pyright → pytest, fastest check first (verified: ruff ~0.05-0.07s,
pyright ~13s warm, full pytest ~14s for 707 tests), so a commit with
an actual violation fails as fast as possible instead of waiting
through a slower check first.

## Why

This resolves the 2026-09-21 decoupling rather than reopening it —
that decision split ruff and pyright apart specifically because
pyright's baseline was unrelated debt untouched by that day's refactor,
not because the two tools should stay separately gated indefinitely; it
said as much directly ("Pyright gets its own independent `BACKLOG.md`
item instead of a shared one"). The new evidence that resolves it:
pyright's own baseline independently reached 0
(`2026-09-22-pyright-clean-refactor.md`), the exact trigger condition
the 2026-09-21 doc named — so the same migration now applies on
pyright's own timeline, as anticipated rather than as a reversal.

**Risk this gate carries that ruff's doesn't, worth naming explicitly**:
ruff's gate is built on an explicit, curated `[tool.ruff.lint] select`
list — a ruff version bump alone can't introduce a violation class this
project didn't opt into. Pyright basic mode has no equivalent opt-in
list, and this project's own strict-mode rejection (4,655 errors, ~94%
noise from dict-shaped data flow) is direct evidence of how hard its
noise profile can swing on non-code-authored triggers (a pyright
version bump, a third-party stub update). If a future dependency bump
ever surfaces a burst of unrelated new errors, the guidance is to
bypass with `git commit --no-verify` and file a `BACKLOG.md`
re-baseline item, rather than blocking unrelated work indefinitely on
debt nobody authored.

## Files touched

`githooks/pre-commit` (new pyright step inserted between ruff and
pytest), `.git/hooks/pre-commit` (synced copy, so the gate is active in
this checkout immediately), `pyproject.toml` (`[tool.pyright]`
preceding comment updated to the new rollout stage), `requirements-dev.txt`
(ruff's and pyright's preceding comments corrected — both still
described a changed-files-scoped convention neither tool follows
anymore; ruff's had been stale since its own 2026-09-21 migration and
was missed then, fixed here incidentally alongside pyright's, same as
that migration's own stale-comment fix to `githooks/pre-commit`),
`CLAUDE.md` (project) (`This project's type checker` section's
rollout-stage paragraph rewritten to mirror `This project's linter`'s),
`BACKLOG.md` (pyright's migration item deleted as done), `PROJECT_INDEX.md`
(new `Recent` entry).

Adding pyright made `githooks/pre-commit`'s binary-lookup-with-fallback
and run-and-block shell logic a third copy-paste of an identical
pattern (ruff's and pytest's blocks already existed) — past the
"rule of three" this project's own incremental-improvement convention
names as the trigger for extracting, and caught by this change's own
`independent-review-pass`. Factored into two small POSIX-sh functions
(`find_bin`, `run_check`), cutting the file from 55 to 34 lines with
identical messages and exit codes for all three checks — re-verified
via the same scratch-commit method below after refactoring.

## Verification

Confirmed the gate actually blocks, mirroring
`docs/decisions/2026-09-21-ruff-pre-commit-gate.md`'s own verification
method: appended a deliberate, isolated pyright type-mismatch
(`_scratch_pyright_gate_check: int = "not an int"`) to
`analyze_citation_gate.py` — the same file ruff's own verification
used — staged and committed. The hook ran ruff first (passed, no ruff
violation from the added line — confirmed neither `PLR2004` nor `F841`
matches a module-level annotated assignment), then ran pyright, which
reported the `reportAssignmentType` error and blocked the commit before
pytest ever ran, exit code 1. Reverted the scratch change (`git restore
--staged` + `git checkout --`), confirmed the working tree was clean
again. Then ran `ruff check .` (0 errors), `pyright .` (0 errors), and
the full `pytest` suite (707 passing) directly, confirming the seven
doc/config edits introduced no regression and that ruff's own gate
behavior is unchanged by pyright's insertion into the sequence.

## Related

Resolves the joint-migration plan in
`docs/decisions/2026-09-15-adopt-ruff-linter.md` and
`docs/decisions/2026-09-15-adopt-pyright.md`. Directly mirrors
`docs/decisions/2026-09-21-ruff-pre-commit-gate.md` (ruff's own
migration, one day earlier) and builds on
`docs/decisions/2026-09-22-pyright-clean-refactor.md` (the baseline
cleanup that made this possible).
