# One docs-index check, run as a git pre-commit hook

**Date:** 2026-09-23

## Context

Two scripts checked the same rule, and each defined it differently:
- a PreToolUse hook, `check_docs_sync.py`: decisions only, satisfied by any
  staged index, and blind to chained `git add && git commit`;
- a SessionStart audit, `check_docs_health.py`, added earlier today in
  `3cf7fe1`: all three docs folders, a real entry required, but only caught
  a miss at the next session.

The user asked to normalize these into one check.

## Decision

- `scripts/check_docs_health.py` is now the only check. `githooks/pre-commit`
  runs it against the staged tree.
- It **blocks** when a docs file has no index entry, or an entry names a
  missing file. The reverse check was added because the user asked whether
  it checks both ways.
- It **warns** when `## Recent` is over its cap.
- It **fails open** when git or the index can't be read.
- Both git hooks are installed through `core.hooksPath githooks`. Both are
  stored as executable (`100755`).
- Removed: the whole `.claude/settings.json` `hooks` block,
  `check_docs_sync.py` and its tests.

Details: `docs/plans/2026-09-23-docs-index-pre-commit.md`.

## Why

- **Pre-commit is the right layer.** Git runs it after staging, however the
  commit command is chained, and for commits made outside Claude Code too.
  Claude still sees a blocked commit's stderr in the Bash tool output.
- **Narrow revisit of `2026-09-22-coverage-baseline-close-and-hard-gate.md`**
  ("nothing runs at commit time"). That decision was about commit speed.
  The docs check takes about 50ms and needs only git and the standard
  library, so it doesn't bring the friction back. ruff, pyright, pytest and
  diff-cover stay on pre-push.
- **The user chose warn-only for the Recent cap.** An over-full list is
  housekeeping, not an error.
- **`core.hooksPath` instead of `cp`.** No installed copy can drift from the
  tracked file. The old copy already differed in line endings. The executable
  bit matters on Linux and macOS once git runs the tracked file directly;
  `pre-push` was `100644`.
- **The check scans the whole staged tree, not just the diff.** A miss that
  comes in through merge, rebase or `--no-verify` is caught by the next
  ordinary commit. That makes a pre-push backstop unnecessary. One was also
  unattractive: at push time the index can hold unrelated staged work.

**Found by the plan review and verified experimentally:**
- `git show` output has to be decoded as UTF-8 explicitly. Text mode uses
  cp1252 here, which garbles `→` and would have blocked every commit.
  Confirmed in this repo: text mode finds 0 arrows in the staged index.
- `commit --dry-run` doesn't run hooks.
- The hook sees the temporary index that `commit <paths>` and `commit -a`
  build.

Details: `docs/reviews/2026-09-23-docs-index-pre-commit-plan-review.md`.

## Files touched

- Changed:
  - `scripts/check_docs_health.py` (rewritten)
  - `tests/test_check_docs_health.py` (rewritten)
  - `githooks/pre-push` (install comment, mode)
  - `.claude/settings.json`
  - `CLAUDE.md`
  - `BACKLOG.md`
  - `PROJECT_INDEX.md`
- New: `githooks/pre-commit`.
- Deleted:
  - `scripts/check_docs_sync.py`
  - `tests/test_check_docs_sync.py`
  - the untracked `.git/hooks/pre-push` copy

## Verification

- **Tests:** `tests/test_check_docs_health.py`, red first.
  `main()` runs against real throwaway git repos, including a partial
  commit through an installed hook.
- **Live runs:** see `docs/reviews/2026-09-23-docs-index-pre-commit.md`.

## Related

- Revises `docs/decisions/2026-09-23-context-management-hooks.md`: the
  SessionStart audit is replaced, and `check_docs_sync.py` no longer
  "stays on PreToolUse".
- Narrowly revisits
  `docs/decisions/2026-09-22-coverage-baseline-close-and-hard-gate.md`.
- Retires the hook from `docs/decisions/2026-09-15-claude-md-restructure.md`.
