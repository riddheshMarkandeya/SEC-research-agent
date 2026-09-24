# Review: context-management hooks plan (independent plan review)

Plan: `docs/plans/2026-09-23-context-management-hooks.md`.

**What was reviewed:** the draft plan, before implementation. At that stage it
had four parts:

- (A) the plan-accept clear setting
- (B) two CLAUDE.md trial rules
- (C) a SessionStart hook injecting git state, docs health, the newest plan and
  a list of rules files
- (D) a PostToolUse post-commit check in `check_docs_sync.py`

**Reviewer:** a fresh subagent with no memory of the planning session. It
re-fetched the current hooks, settings-reference and permission-modes docs to
verify the plan's claims.

**Verified directly by the reviewer, no issue:**

- `showClearContextOnPlanAccept` exists and behaves as the plan says.
- `## Recent` has 52 entries.
- All 127 docs files are indexed.
- A PostToolUse Bash payload carries `tool_response.stdout`.
- A SessionStart hook with no matcher covers every session source.
- Revisiting the 2026-09-15 decision is legitimate, because the docs now list
  `additionalContext` for PreToolUse and PostToolUse.

## Findings and dispositions

1. **[must-fix] The plan wrongly said stderr from a SessionStart hook that exits
   0 is shown to the user.** It only reaches the debug log.
   - `[Fixed in plan]` Any degraded state is now reported inside the injected
     context text.
2. **[must-fix] The JSON output needs `hookEventName`**, or schema validation
   drops the output.
   - `[Fixed in plan]` An exact-shape test was added.
3. **[must-fix] Part D's `main()` needed a defined fallback when
   `hook_event_name` is missing.**
   - `[Moot]` The user dropped Part D.
4. **[must-fix] Part D's HEAD-based check can false-report.** Cases: `--dry-run`
   and `|| true` commits, HEAD moved by another session, and root or merge
   commits.
   - `[Moot]` Part D was dropped, and this finding was a main reason why.
5. **[should-fix] Drop Part D.** The SessionStart audit already catches the
   chained-commit gap one session later and covers plans and reviews too.
   - `[Adopted]` The user chose to drop it.
6. **[should-fix] The hook's working directory and the spaces in the repo path
   make relative paths fragile.**
   - `[Fixed in plan]` The script resolves the root from `CLAUDE_PROJECT_DIR`,
     falling back to `__file__`. The hook command is quoted.
7. **[should-fix] Windows backslash paths would never match the forward-slash
   paths in the index.** Also, a path mentioned only in prose shouldn't count as
   indexed.
   - `[Fixed in plan]` Paths are compared with `.as_posix()` against their
     backticked form, and tests cover both cases.
8. **[should-fix] The compact-time "newest plan" line could point to a stale,
   unrelated plan.**
   - `[Moot]` The line was dropped when the user trimmed Part C.
9. **[should-fix] Rule 2's hard stop would stall autonomous runs such as
   `/goal`.**
   - `[Fixed in plan]` Autonomous runs are exempt.
10. **[should-fix] The comment-hygiene rule applies to any docstrings
    touched.**
    - `[Fixed in plan]` New docstrings must be self-contained.
    - `check_docs_sync.py` is no longer edited.
11. **[should-fix] A git snapshot could quietly replace the git-status-first
    rule.**
    - `[Moot]` The snapshot was dropped.
12. **[nit] The Recent-count parser needs a fixture with trailing prose and
    nested bullets.**
    - `[Fixed in plan]`
13. **[nit] The rules list after compaction is marginal.**
    - `[Adopted]` Dropped.
14. **[nit] BACKLOG conventions.** Deleting the item leaves an empty section
    header, and the new item needs its own header.
    - `[Fixed in plan]`
15. **[nit] Settings placement, plus a hook `timeout`.** The default timeout is
    600 seconds.
    - `[Fixed in plan]` The timeout is set to 10 seconds, and the placement is
      recorded in the decision file.
16. **[nit] Keep the new CLAUDE.md section short**, since the file is already
    about 200 lines.
    - `[Fixed in plan]` At most 10 lines.

**Follow-up question from the user after the review:** is Part C needed at all,
if we're already compacting after planning and after implementing? The answer
was only partly. Its compaction-related pieces duplicated Parts A and B.
The docs-health audit is independent of compaction and is what closes the
chained-commit gap. The user chose to keep the audit only.

## Outcome

The plan was approved with Parts A, B, and a trimmed C (audit only) after 4
must-fix, 7 should-fix and 5 nit findings. Of these, 10 were fixed in the plan,
2 were adopted as scope cuts, and 4 became moot because of those cuts.
