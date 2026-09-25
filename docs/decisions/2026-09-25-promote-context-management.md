# Promote the context-management trial to the global workflow

**Date:** 2026-09-25

## Context

The project-local "Context management (trial)" started on 2026-09-23 with two rules:
self-contained plans, and a `/compact` at the implementation→review boundary. It also set
`showClearContextOnPlanAccept` in project settings. Its BACKLOG promotion trigger was met. See
the plan: `docs/plans/2026-09-25-promote-context-management.md`.

## Decision

- **Global `~/.claude/CLAUDE.md` §6** gains a "Context management" block. It holds the promoted
  rules, plus an observable earlier-break rule for plans with 4 or more implementation steps.
- **A project-neutral `# Compact instructions` section** is added globally.
- **Project `CLAUDE.md`**: the trial section is removed. What remains of its Compact instructions
  is one project addition: exact eval figures.
- **`showClearContextOnPlanAccept`** moves to user settings.

## Why

**Evidence.** Boundary compactions ran 7 times across 6 Standard+ tasks (context-hooks,
docs-index, WP1–WP4, the WP4→WP5 handoff):
- they ran at 203k–473k and compacted to about 15–30k;
- the user's next message was always "continue", "commit" or the next work package, with no
  corrections or re-done work;
- afterwards, work resumed by re-reading the plan or roadmap and went straight into review.

The only friction was the long task-specific paste line, now shortened to point at Compact
instructions. No complaints is not proof of no loss, so the 2026-09-25 token-efficiency pilot
item keeps watching.

**Revisits two prior choices** from `docs/decisions/2026-09-23-context-management-hooks.md`
(global §4):
- the setting was project-local by the user's choice;
- the trial stayed project-local partly because the global `CLAUDE.md` wasn't version-controlled.

What changed:
- the trial evidence above;
- `~/.claude` has been a local git repo since the same day.

**Earlier break.** Auto-compaction now runs at 300k. WP2 (473k) and WP3 (359k) passed that
before their review boundary. The added rule offers `/compact` after a green test step around
the midpoint of longer plans. The trigger is observable, because Claude can't reliably judge
its own token count or run `/compact` itself (plan review finding 1).

**The global Compact instructions are honored.** The docs only name the project-root
`CLAUDE.md`. A direct test confirmed the user-level file works too: a temporary "Begin the
summary with the word PINEAPPLE" line, then a headless session plus `/compact` in a throwaway
directory. The summary began with PINEAPPLE. The marker was then removed.

## Files touched

- `~/.claude/CLAUDE.md`
- `~/.claude/settings.json`
- `CLAUDE.md`
- `.claude/settings.json`
- `BACKLOG.md` (promotion item removed)
- `PROJECT_INDEX.md`

## Verification

- The PINEAPPLE test passed.
- Both settings files parse as JSON.
- `git diff` shows every trial rule present in global §6.
- The pre-commit docs-health check passed.

## Related

- Amends `docs/decisions/2026-09-23-context-management-hooks.md`.
- Builds on `docs/decisions/2026-09-25-token-efficiency-workflow.md`.
- Plan review: `docs/reviews/2026-09-25-promote-context-management-plan-review.md`.
