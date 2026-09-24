# Context-management workflow rules + SessionStart docs-health audit

## Context

The goal is to make phase boundaries (plan approved → implement → tests green →
review) cheaper in context. A second goal is to start every session with the
docs system in a known state.

Nothing can trigger `/compact` automatically. Hooks only react to events, and
Claude can't run built-in slash commands itself. So this plan uses the closest
real mechanisms:

- **Plan → implement:** Claude Code's built-in `showClearContextOnPlanAccept`
  setting.
- **Tests green → review:** a CLAUDE.md rule telling Claude to stop and hand the
  user a ready-to-paste `/compact` line.
- **Session start, resume or `/clear`:** a docs-health audit hook.

Baseline, measured read-only before implementation: every file under
`docs/decisions|plans|reviews/` was indexed, but `PROJECT_INDEX.md`'s
`## Recent` held 52 entries against its cap of 50.

## Prior art

These are the current Claude Code docs (fetched 2026-09-23 from
code.claude.com: hooks, settings-reference, permission-modes, context-window):

- **`showClearContextOnPlanAccept`:** boolean, default `false`. It adds a first
  plan-approval option, "Yes, clear context and …". That option approves the
  plan, clears the conversation, and implements from the plan alone.
- **SessionStart matchers:** `startup`, `resume`, `clear`, `compact`, `fork`.
  Output can include `hookSpecificOutput.additionalContext`. The event can't
  block.
- **Stderr from a hook that exits 0** goes only to the debug log.
- **`additionalContext` is now listed for PreToolUse and PostToolUse too.** The
  2026-09-15 restructure found only four events supported it. This is new
  information.
- **Injected text** should read as facts, not imperatives, to avoid tripping
  prompt-injection defenses.
- **Path-scoped `.claude/rules/` files** are summarized away when context is
  compacted.

## Decision / Design

- **Part A:** add `"showClearContextOnPlanAccept": true` to the project
  `.claude/settings.json`.
- **Part B:** add two rules to a new "Context management (trial)" section in the
  project `CLAUDE.md`. They go in the project file, not the global one, so
  they're easy to revert and can be promoted later.
  1. Plans must stand alone. Fold the plan-review findings and the user's
     decisions into the plan before `ExitPlanMode`. Implementation step 1 saves
     the plan to `docs/plans/`. This repeats `design-before-building` on
     purpose, because CLAUDE.md reloads after a clear and skill text doesn't.
  2. In interactive Standard+ tasks, stop at the implementation→review boundary
     with a ready-to-paste `/compact Keep: …` line. In `/goal` or other
     autonomous runs, note the line and continue.
- **Part C:** new script `scripts/check_docs_health.py`, run by a SessionStart
  hook on `startup|resume|clear`. It checks two things:
  - Every docs file must be indexed by its backticked path in `PROJECT_INDEX.md`
    or `PROJECT_INDEX_ARCHIVE.md`.
  - The `## Recent` entry count must be 50 or fewer.

  When everything passes, it prints nothing, so a clean session costs no tokens.
  When something fails, it prints SessionStart JSON with `hookEventName` and the
  findings as facts. It always exits 0. A degraded state, such as a missing
  index, is reported inside the context text, because stderr is invisible.

**What was dropped during planning (user decisions):**

- **Moving `check_docs_sync.py` to SessionStart.** Rejected. The commit-time
  check has to see the staging area at commit time.
- **A PostToolUse post-commit check** to close the chained
  `git add -A && git commit` gap. Rejected. It needs HEAD-vs-SHA handling and
  can still false-report on `--dry-run`, on `|| true`, or when another session
  moves HEAD. The SessionStart audit catches the same miss one session later,
  and it also covers plans and reviews.
- **A git-state snapshot, a newest-plan line after compaction, and a rules
  list.** Rejected as redundant with Parts A and B. Compacting doesn't change
  the docs, so the audit doesn't run on `compact`.

## Scope / Out of scope

`check_docs_sync.py` itself is unchanged. Promoting the Part B rules to the
global `CLAUDE.md` is left as a BACKLOG item, to revisit after a trial of about
3 Standard+ tasks.

## Files and steps

0. Save this plan, plus the plan-review file.
1. `.claude/settings.json`: add the Part A setting and the SessionStart hook,
   with `timeout: 10` and the command
   `python "${CLAUDE_PROJECT_DIR}/scripts/check_docs_health.py"`. Check that
   `${CLAUDE_PROJECT_DIR}` expands on this machine. If it doesn't, use a relative
   path, since the script resolves its own root.
2. `tests/test_check_docs_health.py` first (red), then
   `scripts/check_docs_health.py`. Structure:
   - pure functions `unindexed_docs`, `recent_entry_count`, `build_report`
   - a thin `_read_text` / `_list_docs` I/O layer
   - repo root from `CLAUDE_PROJECT_DIR`, falling back to
     `Path(__file__).resolve().parents[1]`
   - POSIX paths throughout
   - catch only `OSError`
3. Project `CLAUDE.md`: add the Part B section. Update "This project's hooks" to
   describe the audit and state that it now catches the chained-commit gap.
4. `BACKLOG.md`:
   - Delete the chained-commit item and its now-empty 2026-09-15 restructure
     header.
   - Add a new section with a `[design, Low, Trivial]` item to promote the rules
     to global.
5. Write the decision file. Add the index entries, then trim `Recent` to 40,
   moving the oldest entries verbatim to the archive.

## Testing and verification

**Full TDD.** Everything here is pure logic plus file I/O and has no live-only
surface. Tests:

- `unindexed_docs`:
  - an indexed file passes
  - an unindexed file is flagged
  - `TEMPLATE.md` is skipped
  - a file indexed only in the ARCHIVE passes
  - a file mentioned only in prose (not backticked) is flagged
  - backslash paths are normalized
- `recent_entry_count`:
  - 50 entries gives no finding; 51 does
  - a file with no `## Recent` header
  - trailing prose and nested `  - ` bullets are not counted
- `build_report`: a clean run, each finding separately, both findings together,
  and the missing-index text
- `main()`:
  - prints nothing when clean
  - prints the exact JSON shape when there's a finding
  - exits 0 on every path

**Checks:** `ruff check .`, `pyright .`, and pytest with coverage. New lines
must meet the 80% diff bar.

**Manual:**

- Run the script before the `Recent` trim and confirm it flags the count. Run it
  after and confirm it prints nothing.
- Run it from a different working directory to prove root resolution works.

**Live:** start a new session and run `/clear`. Also check whether approving a
plan with the clear-context option fires SessionStart with source `clear`. This
is unverified, so record the result either way.
