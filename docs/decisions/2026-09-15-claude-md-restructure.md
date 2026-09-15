# Restructure CLAUDE.md into skills, path-scoped rules, and a docs-sync hook

**Date:** 2026-09-15

## Context

The global `~/.claude/CLAUDE.md` had grown to 623 lines. Both it and the
project `CLAUDE.md` load in full into every session regardless of task
relevance — Anthropic's own guidance targets under ~200 lines per file,
since longer files cost more tokens every session and measurably reduce
instruction adherence. The user asked whether to break the file up using
skills, hooks, or rules, or whether nothing needed to change.

## Decision

Restructured both `CLAUDE.md` files without changing their substantive
content:

- Six of the global file's big procedural sections (design-before-
  building, TDD carve-out, debugging discipline, documentation/backlog
  hygiene, independent review, UI guidelines) moved to personal skills
  under `~/.claude/skills/`, loaded only when that kind of work is
  actually happening. The global file shrank from 623 to 217 lines,
  keeping only the short, universally-relevant sections (scope tiers, SE
  principles, error handling, git-as-inspection-tool, revisiting prior
  decisions) plus a new section on pushing back with reasoning when
  evidence warrants it, added per user request during plan review.
- This project's two file-specific sections (the live-code TDD carve-out
  list, and the spot-check-eval/quota/regression rules) moved to two new
  `.claude/rules/*.md` files with `paths:` frontmatter, so they load only
  when the specific files they name are touched. Project `CLAUDE.md`
  shrank from 177 to 130 lines.
- A new `PreToolUse` hook (`scripts/check_docs_sync.py`) blocks a `git
  commit` when a new `docs/decisions/*.md` file is staged without
  `PROJECT_INDEX.md` also staged — a mechanical safety net for the
  documentation-backlog-hygiene skill's same-step index rule.

## Why

Two mechanisms genuinely solve "load only when relevant," verified via a
fresh `claude-code-guide` lookup at the start of this session rather than
assumed from memory: Skills load lazily (description-only until
invoked), and `.claude/rules/` files load only when a matching path is
touched. Neither existed anywhere on this machine before this change, so
there was no legacy to reconcile — a clean-slate reorganization.

Three sections (SE principles, error handling, git-as-inspection-tool)
were explicitly considered for the skill treatment too and rejected: they
are short and apply to nearly every task, with no discrete trigger moment
narrower than "any time code is touched" — extracting them would add
real risk (silently not firing right when needed) for no context
savings. The same reasoning kept "revisiting prior decisions" inline.

**Implementation-time amendment, raised back to the user rather than
decided unilaterally**: the plan's docs-sync hook was specified as
"non-blocking, informational." A second `claude-code-guide` verification
during implementation found this combination doesn't exist for
`PreToolUse` hooks — `additionalContext` injection (the only way to make
a message visible to Claude) is restricted to `UserPromptSubmit`,
`UserPromptExpansion`, `SessionStart`, and `PostModelSwitch`; exit 0 on
`PreToolUse` is a silent allow with nothing shown. Presented the user
three real options (hard block via exit 2; a `Stop`-hook post-commit
nudge; or dropping the hook); the user chose the hard block, scoped
narrowly to the exact mismatch case. See
`docs/plans/2026-09-15-claude-md-restructure.md` for the full comparison.

**Known limitation, not solved**: `PreToolUse` fires before the Bash
command runs, so a single chained `git add -A && git commit` is checked
against whatever was staged *before* that command — the hook only
reliably catches the common case where staging and committing are
separate tool calls. Logged to `BACKLOG.md`.

**Post-review follow-up, same session**: both `CLAUDE.md` files' intros
originally carried a multi-event dated chronology of how each file
reached its current shape (this restructure, the 2026-09-12 split, the
2026-08-24 original agreement, a pointer to the separate 2026-08-14
TDD-adoption decision). The user pointed out this violates the
SE-principles section's own pointer-not-narration rule — applied so far
only to code comments, not noticed as also applying to the CLAUDE.md
files' own prose. Fixed by cutting the narration entirely: history
belongs in `PROJECT_INDEX.md`'s index (which already carries all of
these, including the 2026-08-14 file — confirmed before cutting the
inline pointer to it, so nothing became less discoverable) and in each
decision file itself, not repeated inline in the operating document
every time it changes — the same accumulation pattern that grew the old
`PROJECT_CONTEXT.md` to 5,703 lines, recreated in miniature inside
CLAUDE.md instead. The global file's version had a second, sharper
problem: its pointer to this project's `docs/decisions/` path would
dangle in any other project that same global file governs, since global
config has no project-relative doc system to point into. Global
`CLAUDE.md`: 217 → 212 lines. Project `CLAUDE.md`: 136 → 131 lines.

**Independent review found and fixed two real bugs in the first cut of
the hook** (full findings: `docs/reviews/2026-09-15-claude-md-restructure.md`):
project `CLAUDE.md` had described the hook as "non-blocking" after the
amendment above changed it to a hard block; and `is_commit_command`'s
original regex matched "git commit" as a substring anywhere in a
command, which false-positived on a command that merely echoed that text
as data — the exact false positive that occurred during this decision's
own first live hook test, at the time mislabeled as a successful
validation rather than recognized as a bug. Both fixed; see the review
file for the two smaller fixes (a null-`tool_input` crash, a
`main()`-level test-coverage gap) found in the same pass.

## Files touched

- New: 6 files under `~/.claude/skills/*/SKILL.md`; 2 files under
  `.claude/rules/`; `scripts/check_docs_sync.py`;
  `tests/test_check_docs_sync.py`; this decision file;
  `docs/plans/2026-09-15-claude-md-restructure.md`;
  `docs/reviews/2026-09-15-claude-md-restructure.md`.
- Modified: `~/.claude/CLAUDE.md`; project `CLAUDE.md` (twice — once for
  the restructure, once to fix the non-blocking/blocking
  inconsistency); `.claude/settings.json` (added the `PreToolUse` hook
  entry); `PROJECT_INDEX.md`; `BACKLOG.md`.

## Verification

- `pytest tests/test_check_docs_sync.py` — 18 tests (8 written initially
  for the pure functions, 10 more added during the review pass to cover
  `main()`'s stdin/subprocess glue and regression-test the two bugs found
  there), all passing. Full project suite: 652 passed.
- `ruff check scripts/check_docs_sync.py tests/test_check_docs_sync.py
  --fix` — clean, no findings, both before and after the review-pass fixes.
- Content-parity check: grepped for distinctive phrases from the
  original two files (e.g. "unconditional exact-substring shortcut",
  "5,703 lines", "RESOURCE_EXHAUSTED") across the new skills/rules files
  to confirm nothing was silently dropped, only relocated — independently
  re-confirmed by the review subagent.
- Line counts confirmed post-trim: global `CLAUDE.md` 623 → 217 lines;
  project `CLAUDE.md` 177 → 130 lines (136 after the post-review wording
  fix).
- `paths:` glob targets confirmed to exist at the expected repo-root
  locations for both new rule files.
- **Live hook trigger tests** (see the review file for the full
  before/after): the first round staged a throwaway
  `docs/decisions/ZZZ-hook-trigger-test.md` file without
  `PROJECT_INDEX.md` and found the false-positive bug live, rather than
  purely in a simulated test. After the regex fix, re-ran the identical
  scenario: a command merely mentioning "git commit" as text ran cleanly
  with the mismatch still staged, while a command genuinely invoking
  `git commit` still correctly blocked. The pass case (both files staged
  together) was also re-confirmed with a `git commit --dry-run`. The
  throwaway file was deleted and never committed.

## Related

Plan: `docs/plans/2026-09-15-claude-md-restructure.md`. Review:
`docs/reviews/2026-09-15-claude-md-restructure.md`.
