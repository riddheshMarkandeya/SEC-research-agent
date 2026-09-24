# Context-management trial rules and a SessionStart docs-health audit

**Date:** 2026-09-23

## Context

Two goals drove this change:
- Make phase boundaries cheaper in context: plan approved → implement, and
  tests green → review.
- Have each session start by checking that the docs index is in good shape.

Nothing can trigger `/compact` automatically. Hooks only react to events, and
Claude can't invoke built-in slash commands.

Separately, a BACKLOG bug has been open since 2026-09-15. `check_docs_sync.py`
runs as a PreToolUse hook, so it checks a chained `git add -A && git commit`
against whatever was staged before that command ran. That means it can miss an
unindexed decision file.

## Decision

- **Plan-accept clear.** Set `showClearContextOnPlanAccept: true` in the project
  `.claude/settings.json`. Plan approval now offers "Yes, clear context and …".
- **Two trial rules** in a new "Context management (trial)" section of the
  project `CLAUDE.md`:
  1. Plans are self-contained, and step 1 of every plan saves it to
     `docs/plans/`.
  2. In interactive Standard+ tasks, stop at the implementation→review boundary
     with a ready-to-paste `/compact Keep: …` line. Autonomous runs note the
     line and continue.
- **Docs-health audit.** New `scripts/check_docs_health.py`, run by a
  SessionStart hook on `startup|resume|clear` with a 10-second timeout. It flags:
  - docs files with no entry (a line ending in `→` plus the backticked path)
    in the index or its archive
  - a `## Recent` section over its 50-entry cap

  It prints nothing when the docs are clean and always exits 0.
- **BACKLOG.** Closed the chained-commit item: the audit now catches that miss
  at the next session start. Added a new item to promote the trial rules to
  global.

## Why

**Project-local trial, not global.** The user's choice. The rules are easy to
revert and can be promoted once they've proven themselves. The global
`CLAUDE.md` isn't version-controlled.

**The setting goes in project `settings.json`.** Also the user's choice. It's
fine for a solo repo. `settings.local.json` is the alternative if the repo ever
gains contributors.

**`check_docs_sync.py` stays on PreToolUse, not SessionStart.** The user asked
about moving it. It can't move: a commit-time check has to see the staging area
at commit time.

**Revisiting the 2026-09-15 restructure's "known limitation, not solved."**
What's new since then is a repo-wide audit, which catches the chained-commit
miss one session later, never false-reports, and also covers plans and
reviews. A PostToolUse post-commit check was the direct alternative; the plan
review found it false-reports in several cases (see the review file), so the
user chose the audit alone.

**Why the SessionStart hook is audit-only.** Git status, the plan path and the
rules list already survive through the global `git status` rule, rule 1 and the
`/compact Keep:` line. Compaction doesn't change the docs, so `compact` isn't a
matcher.

**Deviations from the plan.**
- Stdin isn't read: the payload doesn't change the audit, and reading it would
  hang a manual terminal run.
- `main()` also catches `UnicodeDecodeError`, so a non-UTF-8 index degrades
  into reported context like any `OSError` (found in the implementation
  review).
- An entry is matched as the backticked path after an index line's trailing
  `→`, not any backticked occurrence, so a backticked mention in another
  entry's prose doesn't count (found in the implementation review; every
  existing entry uses that form).

**Implementation-time finding: the Recent section had drifted.** This wasn't
in the plan.
- The section's explanatory paragraph was meant to sit directly under
  `## Recent`. It had ended up in the middle of the list, with 18 entries above
  it and 37 below.
- It moved down one line per commit starting at `d3669a0`, because sessions
  naturally add new entries right under the heading.
- The audit's counter was unaffected, since it counts entries across the
  paragraph. But a naive "keep the first 40" trim would have cut the wrong
  lines.
- Fixed while trimming the section: the paragraph now sits above the
  `## Recent` heading, so adding directly under the heading is correct.
- Checked at trim time that no entries were lost: 149 entries at HEAD, plus
  the 3 new ones, gives 152, with no duplicates.
- No audit check was added for the paragraph's position. With it above the
  heading there's no longer a wrong place to insert.

## Files touched

- New:
  - `scripts/check_docs_health.py`
  - `tests/test_check_docs_health.py` (26 tests)
- Changed:
  - `.claude/settings.json` (setting and SessionStart hook)
  - `CLAUDE.md` (hooks section; new "Context management (trial)" section)
  - `BACKLOG.md`
  - `PROJECT_INDEX.md` (entries; `Recent` trimmed to 40)
  - `PROJECT_INDEX_ARCHIVE.md`

## Verification

- **Tests:** TDD; the new tests failed on import before the script existed.
  26/26 new tests pass, and the full suite has 792 passing. `ruff check .` is
  clean and `pyright .` reports 0 errors. `check_docs_health.py` has 100% line
  and branch coverage.
- **Manual runs:**
  - From the repo root, and from `C:\` with a Windows-style
    `CLAUDE_PROJECT_DIR` through the exact quoted hook command under bash, the
    script flagged `## Recent` over its cap of 50, exiting 0
    with valid SessionStart JSON.
  - After the trim to 40 it printed nothing.
- **Live:** see `docs/reviews/2026-09-23-context-management-hooks.md`. This
  covers the hook firing on a fresh session and on `/clear`, and whether it
  fires on a plan-accept clear.

## Related

- Plan: `docs/plans/2026-09-23-context-management-hooks.md`.
- Plan review: `docs/reviews/2026-09-23-context-management-hooks-plan-review.md`.
- Implementation review: `docs/reviews/2026-09-23-context-management-hooks.md`.
- Revisits `docs/decisions/2026-09-15-claude-md-restructure.md` ("known
  limitation, not solved").
