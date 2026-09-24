# Review: docs-index pre-commit hook plan

Plan: `docs/plans/2026-09-23-docs-index-pre-commit.md`. This is an independent
review of the draft plan by a fresh subagent before approval. It verified git
behaviour experimentally in a scratch repo.

## Findings

1. **MUST-FIX [Fixed in plan]: decode `git show` as UTF-8 explicitly.**
   - This machine runs Python 3.14 with locale cp1252 and `utf8_mode=0`.
   - `subprocess.run(text=True)` decoded `→` as `\xe2†’`, and
     `ENTRY_PATH_RE` then matched nothing. Every doc would look unindexed and
     every commit would be blocked: the hook would fail closed.
   - A byte cp1252 can't decode doesn't raise `UnicodeDecodeError` in the
     caller. It surfaces as `stdout=None`, so the planned fail-open path would
     never fire.
   - Fix: capture bytes and decode them as UTF-8 in a `_git` helper. A
     regression test reads a `→` entry through real git.
2. **MUST-FIX [Fixed in plan]: `git commit --dry-run` doesn't run pre-commit.**
   The verification step now uses a real commit followed by `reset --soft`.
3. **Verified: `GIT_INDEX_FILE`.** The hook's subprocess sees the index that
   `commit`, `commit -a` and `commit <pathspec>` actually commit.
4. **Verified: working directory.** The hook runs at the worktree root even
   when the commit starts from a subdirectory.
5. **SHOULD [Adopted]: document which paths skip the hook.**
   - `--amend` and `--allow-empty` run pre-commit.
   - Merge (which runs `pre-merge-commit` instead), rebase, cherry-pick and
     `--no-verify` skip it.
   - Because the whole staged tree is checked, the next ordinary commit
     catches the miss. The message says this, and CLAUDE.md lists the
     skipping paths.
6. **SHOULD [Adopted]: test setup.** Use real `git init` rather than stubs
   (finding 1 shows a stub would have hidden the worst bug). Set a local
   user and `delenv` `GIT_INDEX_FILE` and `GIT_DIR`. The partial-commit hook
   test calls `sys.executable` with an absolute script path.
7. **SHOULD [Adopted]: use `core.hooksPath githooks` instead of `cp`.** No
   installed copy can drift from the tracked file; the current copy already
   differed in line endings. `githooks/pre-push`'s install comment is
   updated to match.
8. **SHOULD [Adopted]: detect a missing index or archive with `git ls-files`,
   not by parsing stderr.** Also catch `FileNotFoundError` for git not on
   PATH.
9. **SHOULD [Adopted]: stale CLAUDE.md sentence.** "`--no-verify` used to
   bypass the old pre-commit hook" gets reworded. The tool sections'
   "Nothing enforces … before committing" lines, the `pyproject.toml` and
   `requirements-dev.txt` comments, and the pre-push header's "not commit
   time" all stay true.
10. **NIT [Adopted]:** fix the memory note saying a pre-commit hook enforces
    tests.
11. **Verified: a Windows Git Bash `#!/bin/sh` hook exec'ing `python` works.**
    CRLF in the working copy doesn't matter, because `git show :` returns the
    LF blob.
12. **Trade-off accepted, and one backstop suggestion declined.**
    `--no-verify` and hooks not installed in fresh clones are the same
    exposure pre-push already accepts. The reviewer suggested also running
    the docs check at pre-push. **[Not adopted]**: at push time the staged
    index may hold unrelated work in progress, and the next commit catches
    any miss anyway.

## User question during planning

"Does it check both ways?" It didn't: it only flagged docs with no entry.
**[Added]** `dangling_entries` flags entries whose file isn't in the staged
tree, and it blocks. Measured baseline: all 153 entries resolve, with no
duplicates.
