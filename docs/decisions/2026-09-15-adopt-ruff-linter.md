# Adopt `ruff` as this project's linter

**Date:** 2026-09-15

## Context

The global `~/.claude/CLAUDE.md` workflow gained a standing rule this
session: modularity should be enforced mechanically, by the project's
own linter/static-analysis tool, not judged unreliably by a review
subagent eyeballing function length or cohesion. This project had no
linter configured at all (`ruff` absent from the venv, `pyproject.toml`
had only `[tool.pytest.ini_options]`, no `.pre-commit-config.yaml`
entry for it) — this file is the concrete instantiation of that policy
here, the same pattern step 2's live-code carve-out already uses
(generic principle in global `CLAUDE.md`, concrete tool/rules named in
the project's own).

## Decision

Installed `ruff==0.16.7` (`requirements-dev.txt`, alongside `pytest`).
Configured in `pyproject.toml`'s new `[tool.ruff]`/`[tool.ruff.lint]`
sections: `line-length = 120`, rule selection `["E", "F", "W", "C90",
"PLR0911", "PLR0912", "PLR0913", "PLR0915"]` (standard pycodestyle/
pyflakes hygiene, plus the modularity-relevant categories — mccabe
cyclomatic complexity and Pylint's too-many-returns/branches/
arguments/statements rules — none of which ruff enables by default),
`max-complexity = 10` (ruff's own documented default, not tightened).

Ran `ruff check . --fix` once to apply safe auto-fixes only (2 missing-
trailing-newline, 2 unused-import in `edgar_ingest.py`,
`chunk_documents.py`, `tests/test_agent.py` — confirmed both removed
imports were genuinely unused elsewhere in the file, not just assumed
from the tool's own claim, and the full pytest suite (634) still passes
after applying them).

**Not fixing the remaining baseline.** After auto-fix: **155
violations** — `E501` (144, line-too-long — see Why below for why this
category is mostly low-value noise here, not a real modularity signal),
`C901` (5, excess cyclomatic complexity), `PLR0913`×2, `PLR0911`×2,
`PLR0912`×1, `PLR0915`×1 (11 combined "true modularity" findings). The
5 `C901` hits are exactly the functions the comment-audit rounds this
session already flagged by hand as oversized: `agent.py`'s
`call_get_financial_fact`, `call_calculate`, `_dispatch_tool_call`,
`_run_agent_impl` (the last one also trips `PLR0912`/`PLR0915`), plus
`tests/manual/verify_period_labels.py`'s `main`. This baseline is not
being fixed now — per the new global incremental-improvement policy,
future changes fix only what they touch; nothing here schedules a
repo-wide refactor.

**Rollout stage**: `ruff check <changed files>` scoped to files the
current change touches, run manually as part of step 7 review — not
wired into the existing pytest pre-commit hook yet. See this project's
own `CLAUDE.md` for the concrete instruction and the plan to migrate to
a hard pre-commit gate once enough of the codebase is clean.

## Why

**Mechanical enforcement over subagent judgment**: a review subagent's
read of "is this function too long" is exactly the kind of check that
isn't reliably enforced run to run — a linter is deterministic and
free to run every time, the same footing as the test suite.

**Changed-files-now, hook-later rollout, not full enforcement
immediately**: wiring `ruff` into the pre-commit hook today would block
every future commit until the entire pre-existing codebase — already
known from this session's own comment-audit rounds to include very
large files (`agent.py`, `tests/test_agent.py`) — is clean, which isn't
this task's job per the incremental-improvement policy itself. This is
an established pattern, not an ad hoc compromise: tools like
`eslint-plugin-diff` (JS) and `lint_diffs` (Python) exist specifically
to let a codebase adopt or tighten lint rules without being blocked by
legacy violations outside the current change.

**`E501` is real but mostly low-value here**: of 144 line-too-long
hits, the overwhelming majority are two deliberate patterns, not
genuine readability problems — `agent.py`'s system-prompt/tool-schema
description strings (several over 2,000 characters, meant to be read as
prose, not as code) and single-line test-fixture dicts (`test_formulas.py`,
`test_xbrl_facts.py`, `test_agent.py` — e.g. a real captured
`companyconcept` API response entry, deliberately kept on one line for
scannability). Kept `E` selected anyway (it also catches real pyflakes-
adjacent issues) rather than special-casing it out, since the
incremental-improvement policy already means these specific
violations won't be force-fixed — no need to also suppress the rule
to avoid seeing them.

## Files touched

`requirements-dev.txt` (added `ruff==0.16.7`), `pyproject.toml` (new
`[tool.ruff]`/`[tool.ruff.lint]` config), `edgar_ingest.py`,
`chunk_documents.py`, `tests/test_agent.py` (safe auto-fixes only — a
trailing newline each, and 2 unused imports removed from the latter),
this project's own `CLAUDE.md` (rollout-stage instruction),
`BACKLOG.md` (baseline-debt and hook-migration items).

## Verification

`ruff check .` actually run (not assumed) against the real repo, twice
(before and after `--fix`) — confirmed the config loads without error
and produces the counts above. Full pytest suite: 634 passed,
unchanged, after the auto-fixes were applied.

## Related

Global `~/.claude/CLAUDE.md` step 3 (incremental-improvement rule) and
step 7 (the new documentation/comment-hygiene and linter-driven
modularity review passes) — this file is their project-level
instantiation. `docs/decisions/2026-09-15-comment-audit-concluded.md`
(the sibling decision this session made about *comment* quality using
the same incremental-improvement reasoning).
