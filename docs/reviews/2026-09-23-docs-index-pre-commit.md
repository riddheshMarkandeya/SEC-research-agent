# Review: docs-index pre-commit hook

Plan: `docs/plans/2026-09-23-docs-index-pre-commit.md`. The change replaces the
PreToolUse `check_docs_sync.py` and the SessionStart audit with one
`githooks/pre-commit` running `scripts/check_docs_health.py` against the staged
tree. The suite had 792 tests before this diff and 790 after: the old sync and
health tests were replaced by the new health tests.

All five `independent-review-pass` passes ran each round. Rounds 1-3 found
issues; round 4 was clean on every pass, with no `/simplify` edits, which
closed the loop.

## Round 1

**Pass 1 (`/code-review`, medium)**
1. **[Fixed] Prose could count as an index entry.** Any line ending in
   `` → `x` `` matched, including the Overview's prose. A re-wrap could make
   the new dangling check block every commit. `ENTRY_PATH_RE` now requires a
   top-level `- ` bullet. All 156 existing entries are single-line bullets.
2. **[Fixed] Hook failed closed without Python.** Falling back to a missing
   `python` exited 127 and blocked every commit, contrary to "fails open". It
   now skips with a warning (verified with an empty PATH).
3. **[Fixed] Non-ASCII paths.** `ls-files` without `-z` quotes them, so an
   indexed doc showed as both unindexed and dangling. It now uses `-z`.

**Passes 2+3 (fresh subagent)**
4. **[Fixed] Dangling check ignored non-docs files.** An entry naming an
   existing `scripts/...` file was reported as missing. Entries are now checked
   against every staged file, from one whole-tree `ls-files` call.
5. **[Fixed] Nested docs counted.** `ls-files` recurses, so
   `docs/plans/sub/x.md` became a doc. `_is_doc` now requires the file to sit
   directly in a docs folder.
6. **[Fixed] Wording.** A CLAUDE.md sentence implied docs misses are caught
   only at push; the ASCII-only comment was moved to cover the whole message;
   a hook comment's file path was replaced by "the pre-push hook".
7. **[Verified, no fix needed] `.venv/bin/python` isn't probed.** It falls
   back to the system Python, and the script uses only the standard library.
   It matches pre-push's lookup.

**Pass 4 (fresh subagent, security)**: no high-confidence findings. Noted, not
a finding: with `core.hooksPath`, hook changes pulled from the remote run
without review. That adds nothing in a single-owner repo whose pre-push
already runs repo code through pytest.

**Pass 5 (`/simplify`)**
8. **[Fixed]** The TEMPLATE.md exclusion moved into `_is_doc` (one rule, one
   place). Backslash normalization was removed, since git output is always
   POSIX. The UTF-8 regression test was folded into the clean-repo test.
9. **[Skipped]** Computing `_entry_paths` once (keeps the pure functions
   taking raw text); one `cat-file --batch` call (small gain, more parsing);
   a shared hook library with pre-push (pre-push fails closed, pre-commit
   fails open).

## Round 2

- **Pass 1:** **[Fixed]** A PATH `python` that can't run the script (the
  Windows Store stub, exit 9009, or Python below 3.10) still blocked every
  commit. The hook now accepts only an interpreter that passes a 3.10+ probe.
- **Passes 2+3:** **[Fixed]** The `.venv` interpreter also goes through the
  probe, so a broken venv fails open too (one extra startup; the hook
  measures 0.27s). A stale test count was dropped from the decision file, and
  a CLAUDE.md sentence was rewrapped.
- **Pass 4:** clean.
- **Pass 5:** no edits. **[Skipped]** Forcing stderr to UTF-8 instead of
  ASCII-only text: a cp1252 console would then show mojibake instead of
  `→`.

## Round 3

- **Passes 1 and 4:** clean.
- **Passes 2+3:** **[Fixed]** A paragraph rewrap, and the CLAUDE.md fail-open
  bullet now covers "no Python 3.10+ interpreter".
- **Pass 5:** **[Fixed]** The loop `exec`s the first working candidate and
  falls through to the fail-open warning, dropping a variable and a
  conditional. **[Skipped]** `from __future__ import annotations` to lower the
  version floor: `list[str]` would still need 3.9.

## Round 4

All five passes were clean, and `/simplify` made no edits.

## Live verification

These ran in this repo through the real hook, using partial commits so the
staged work stayed uncommitted. HEAD was unchanged afterwards and scratch files
were removed.
- A plain `git commit` of an unindexed `docs/plans/zz-test.md` was blocked
  (exit 1, path shown).
- The chained `git add && git commit`, the original gap, was blocked.
- A Recent entry for a nonexistent `docs/plans/zz-gone.md` was blocked as
  dangling.
- `git rev-parse --git-path hooks` resolves to `githooks`, so pre-push still
  runs.

Hook interpreter handling, checked in scratch directories:
- Stub-only PATH and empty PATH: skipped with a warning, exit 0.
- Broken `.venv`: fell through to the PATH Python.
- Unindexed doc in a scratch repo: exit 1, so blocking still propagates
  through `exec`.

## Outcome

Everything shipped as listed above. Nothing was filed to `BACKLOG.md`: every
finding was fixed or skipped with a stated reason. Final gate: ruff clean,
pyright 0 errors, 790 tests pass, and `scripts/check_docs_health.py` has 100%
coverage. The loop closed clean at round 4.
