# Promote the context-management trial to the global workflow

## Context

Since 2026-09-23, the project `CLAUDE.md` has run a "Context management (trial)" with two rules:

- **Plans are self-contained.**
- **Compact at the implementation→review boundary**, using a ready-to-paste `/compact` line.

The trial also set `showClearContextOnPlanAccept` in the project settings.

The BACKLOG trigger for promoting it was "about 3 Standard+ tasks without friction".

The session transcripts show 7 boundary compactions across 6 Standard+ tasks (context-hooks,
docs-index, WP1–WP4, plus the WP4→WP5 handoff):

- They ran at 203k–473k tokens, and each compacted context was about 15–30k.
- The user's next message was always "continue", "commit" or the next work package: no
  corrections and no re-done work.
- The only friction was the long, task-specific `/compact Keep: …` line.

This trial interacts with the change made the same day: `autoCompactWindow` is now 300k. WP2
reached 473k and WP3 359k before hitting the boundary, so auto-compaction can now fire
mid-implementation.

## Decision / Design

1. **Global `~/.claude/CLAUDE.md` §6** now has a "Context management" block that replaces the
   "Context size" bullet. It covers:
   - auto-compaction at 300k, `/clear` between tasks, and `--autocompact 600k` for deep debugging;
   - self-contained plans, saved into the repo when the project keeps a plans directory;
   - compacting at the implementation→review boundary, using the short paste line;
   - an observable earlier break: for plans with 4 or more implementation steps, offer the line
     once after a green test step around the midpoint. Claude can't gauge its own token count or
     run `/compact`.
2. **A project-neutral `# Compact instructions` section** goes at the end of the global file.
   Before shrinking the project's copy, check that it's honored:
   - The docs only name the project-root CLAUDE.md.
   - Test: add a temporary "Begin the summary with PINEAPPLE" line and run a headless session
     plus `/compact` in a throwaway directory.
3. **The project `CLAUDE.md`** drops the trial section. Its Compact instructions shrink to one
   addition: exact eval figures (pass counts, agent hashes, eval-snapshot SHAs, Gemini quota
   state).
4. **`showClearContextOnPlanAccept`** moves from project settings to user settings.
5. **Docs:** a decision file, this plan, the plan review and index entries. The BACKLOG promotion
   item and its section are deleted.

## Files and steps

In the order above:

- `~/.claude/CLAUDE.md`
- `~/.claude/settings.json`
- project `CLAUDE.md`
- `.claude/settings.json`
- `BACKLOG.md`
- `PROJECT_INDEX.md`
- the decision, plan and review files

Then commit both repos.

## Testing and verification

- The PINEAPPLE check passes, and the marker is removed afterwards.
- Both settings files parse as JSON.
- `git diff` shows every trial bullet present in global §6.
- The pre-commit docs-health check passes.
- This is a markdown/config-only change, so the review floor is a self-check.
