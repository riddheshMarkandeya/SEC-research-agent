# One docs-index check, run as a git pre-commit hook

## Context

Two scripts enforced "every docs file has an index entry", and each defined it
differently:

- **`scripts/check_docs_sync.py`** ran as a PreToolUse hook on Claude's Bash tool.
  - It covered decisions only.
  - It passed whenever `PROJECT_INDEX.md` was staged at all.
  - It ran before a chained `git add && git commit` had staged anything.
- **`scripts/check_docs_health.py`** ran as a SessionStart hook (commit
  `3cf7fe1`).
  - It covered decisions, plans and reviews, and required a real
    `→ \`path\`` entry.
  - It only caught a miss at the next session start.

The user asked to normalize these into one check. A git `pre-commit` hook
runs after staging, whatever the commit command looks like, and also covers
commits made outside Claude Code. Claude still sees a blocked commit, because
git's stderr comes back in the Bash tool output.

**User decisions:**
- **Unindexed docs** block the commit. So do **dangling index entries**: the
  user asked whether the check runs both ways, and it now does.
- **Recent over its cap** only warns.
- **Order:** the previous change was committed first.
- **Slow checks stay on pre-push.** ruff, pyright, pytest and diff-cover
  remain there, because the 2026-09-22 reasoning (commit speed) still holds
  for them. The docs check takes about 50ms and uses only git and the
  standard library.

## Decision / Design

**`scripts/check_docs_health.py` becomes the single check. It reads the
staged tree:**

- **Pure layer, kept:** `ENTRY_PATH_RE`, `unindexed_docs`,
  `recent_entry_count`.
- **Pure layer, new:** `dangling_entries(rel_paths, index_texts)` returns
  entry paths with no staged file. `_entry_paths(index_texts)` is a private
  helper shared by both functions.
- **I/O layer:** a `_git(*args)` helper runs git and **decodes stdout as
  UTF-8 itself**. A plan-review experiment showed that text mode decodes as
  cp1252 on this machine. That garbles `→`, which would block every commit.
  The helper raises `GitError` on a non-zero exit.
- **What it reads:**
  - `git ls-files --cached` for the docs list and for which index files are
    staged;
  - `git show :<file>` for the index text.
  - It honours `GIT_INDEX_FILE`, which git sets for `commit -a` and
    `commit <pathspec>`.
- **Output, on stderr:**
  - Unindexed or dangling entries: exit 1.
  - Recent over its cap: a warning, exit 0.
  - Clean: silent.
  - Degraded (`GitError`, `FileNotFoundError`, `UnicodeDecodeError`, or the
    index not staged): fail open, with a "skipped" warning.
- **Hook:** `githooks/pre-commit` execs the script with the venv python, or
  plain `python` if there's no venv.
- **Install:** both hooks now run through
  `git config core.hooksPath githooks` instead of `cp`, so no copy can drift
  from the tracked file.
- **Removed:**
  - the `.claude/settings.json` `hooks` block (PreToolUse and SessionStart);
  - `scripts/check_docs_sync.py` and its tests;
  - the untracked `.git/hooks/pre-push` copy.

## Scope / Out of scope

- The slow checks don't move.
- No pre-push docs check is added as a backstop for merge, rebase,
  cherry-pick or `--no-verify`. The check reads the whole staged tree, so
  the next ordinary commit catches any such miss.

## Files and steps

1. Commit the previous change (`3cf7fe1`). Save this plan and the plan review.
2. TDD rework of `scripts/check_docs_health.py` and
   `tests/test_check_docs_health.py`.
   - The `main()` tests run against a real `git init` repo in `tmp_path`:
     - `chdir` into it;
     - set a local user;
     - `delenv` `GIT_INDEX_FILE` and `GIT_DIR`.
3. Add `githooks/pre-commit` and set `core.hooksPath`. Update
   `githooks/pre-push`'s install comment. Delete the old hook config and
   files.
4. Docs:
   - CLAUDE.md: rewrite "This project's hooks"; update "Manual checks before
     committing", including the `--no-verify` sentence.
   - Write the decision file.
   - Delete the BACKLOG item.
   - Add the index entries.
   - Memory: `feedback_tests_before_commit.md`.

## Testing and verification

- **Unit and integration:**
  - pure-function tests for unindexed and dangling entries, and the Recent
    count;
  - real-git `main()` tests: clean; a `→` entry through the git path (the
    encoding regression); staged unindexed doc; entry only in the working
    copy; untracked doc ignored; Recent at 51 warns; no archive; index not
    staged; non-UTF-8 blob; git missing; staged deletion with the entry kept;
    a partial commit through a real hook.
- **Live in this repo, with `core.hooksPath` set:**
  - an unindexed scratch doc is blocked, both through a plain commit and
    through a chained `git add && git commit`;
  - with an entry added it passes, verified by a real commit and then
    `reset --soft`, since `--dry-run` skips hooks;
  - a dangling entry is blocked;
  - pre-push still resolves.
- **Gate and review:** `ruff`, `pyright`, `pytest --cov`, then
  `independent-review-pass`.
