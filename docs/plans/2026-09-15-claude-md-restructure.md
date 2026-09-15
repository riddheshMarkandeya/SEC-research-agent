# Restructure CLAUDE.md into skills + path-scoped rules

> Copied from the plan-mode output approved this session (the
> `~/.claude/plans/...` scratch file plan mode wrote to is session-global
> and gets overwritten by the next task) — see the
> `design-before-building` skill for why this copy exists.

## Context

The global `~/.claude/CLAUDE.md` (personal dev-workflow doc, applies to every
project) had grown to **623 lines**. Anthropic's own guidance targets under
~200 lines per CLAUDE.md file — longer files consume more context tokens
every single session and measurably reduce instruction adherence — and
CLAUDE.md files are **not** lazily loaded: both the global and project files
load in full at session start regardless of whether the current task needs
that content. `@import` syntax doesn't help either — imported files still
load at launch, it's purely a readability aid, not a context-saving one.

Verified via a fresh `claude-code-guide` lookup + a repo inventory (both
completed at the start of this session): this machine had **zero** hooks,
skills, or custom agents configured anywhere (global or project) — so this
was a clean-slate reorganization, not a migration around existing
infrastructure. Two mechanisms genuinely solve the "load only when
relevant" problem and were unused until now:

- **Skills** (`~/.claude/skills/<name>/SKILL.md` for personal/global,
  `.claude/skills/` for project-scoped): only `name` + one-line
  `description` sit in context by default; the full body loads only when
  the skill is actually invoked. Right fit for *procedural workflows* that
  apply only for certain kinds of tasks.
- **Path-scoped rules** (`.claude/rules/<name>.md` with a `paths:` YAML
  frontmatter list of glob patterns): load only when Claude is working
  with matching files. Right fit for the project's two sections that
  already named specific files but sat in the always-loaded project
  CLAUDE.md regardless of what was being touched.

The scope-tiers table, SE-principles list, error-handling rules,
git-as-inspection-tool habit, and the revisit-prior-decisions rule are all
short (~15-20 lines each) and apply to *every* task regardless of kind —
those stayed inline. The big procedural sections (design-before-building,
TDD carve-out, debugging discipline, documentation/backlog hygiene,
independent review, UI guidelines) were each 30-90 lines of detail that
only matters when that specific kind of work is actually happening —
those moved to skills, referenced from a slim table in the main file.

**What did not change**: the actual rules/content. This was a
context-placement reorganization, not a rewrite of what the workflow
says.

## Approach (as approved)

1. **Six new personal skills** at `~/.claude/skills/<name>/SKILL.md`:
   `design-before-building`, `tdd-live-code-carveout`,
   `debugging-discipline`, `documentation-backlog-hygiene`,
   `independent-review-pass`, `ui-implementation-guidelines`. Each moved
   the corresponding section's content near-verbatim, with cross-
   references to other now-relocated sections rewritten to name the
   skill/section rather than a step number. `design-before-building`'s
   trigger was broadened from "Substantial-tier only" to "any non-trivial
   work," with the tier-scaling logic folded into the skill body itself
   (per user review comment) rather than gating invocation on tier alone.

2. **Slimmed `~/.claude/CLAUDE.md`** (623 → ~340 lines incl. the new
   section 5 added below) keeping: the scope-tiers table (reworked to
   point at skill names), SE principles, error handling & logging,
   git-as-inspection-tool, revisiting prior decisions — all short and
   universally relevant. Explicitly considered and rejected turning SE
   principles / error handling / git-as-inspection-tool into skills too
   (see the file's own inline note): they're small and continuously
   relevant with no discrete trigger moment, so extraction would add
   invocation risk for no context savings.

3. **New section 5, "Pushing back with reasoning"** (added per user
   review comment): when there's good reasoning/evidence against what the
   user is suggesting, say so and keep the conversation open until the
   user either engages the substance or raises something new — a bare
   repeated instruction doesn't retire the disagreement. Placed alongside
   "revisiting prior decisions" since it's the same family, and kept
   inline for the same short-and-universal reasoning.

4. **Two new path-scoped rules** for the project:
   `.claude/rules/live-code-tdd.md` (paths: `edgar_ingest.py`,
   `xbrl_facts.py`, `index_chunks.py`, `retrieval.py`, `agent.py`,
   `llm_backends.py`) and `.claude/rules/live-eval-verification.md`
   (paths: `numeric_utils.py`, `agent.py`, `retrieval.py`), each carrying
   the removed project-CLAUDE.md content verbatim (adjusted cross-refs).
   Project `CLAUDE.md` shrank from 177 to ~140 lines (slightly more than
   the ~110-120 originally estimated, since it also gained the new hooks
   section — see below).

5. **New hook**: a `PreToolUse` hook on the Bash tool
   (`.claude/settings.json`) running `scripts/check_docs_sync.py` as a
   mechanical safety net for the index-sync part of the
   documentation-hygiene convention.

## Implementation-time amendment: hook design (exit 2, not non-blocking)

The plan as approved specified this hook as "non-blocking, informational" —
warn on a mismatch but let the commit proceed. **This turned out to be
technically impossible.** A second `claude-code-guide` verification during
implementation confirmed `PreToolUse` hooks have no exit-code path that
both allows the tool call *and* surfaces text to Claude in the same turn:
`additionalContext` injection is restricted to `UserPromptSubmit`,
`UserPromptExpansion`, `SessionStart`, and `PostModelSwitch` — not
`PreToolUse`. Exit 0 is a silent allow (nothing shown); only exit 2
(a hard block) makes the message visible.

This was raised back to the user with the real alternatives (hard block
on exit 2; a `Stop`-hook post-commit nudge; or dropping the hook
entirely) rather than silently picking one or shipping the
originally-specified design knowing it would be a no-op. **The user chose
the hard-block (exit 2) option**, scoped narrowly: it only fires when a
`git commit` command is about to run *and* a new `docs/decisions/*.md`
file is staged without `PROJECT_INDEX.md` also staged — never on an
ordinary commit. This is a stronger intervention than "advisory only" but
is simple, reliable, and matches the actual goal (making sure the index
really gets updated) better than a warning that would never have been
seen.

**Known limitation, documented rather than solved**: `PreToolUse` fires
before the Bash command executes. A single chained command like
`git add -A && git commit -m "..."` is checked against whatever was
already staged *before* that command ran, not what it's about to stage —
so the hook only reliably catches the common case where `git add` and
`git commit` are separate tool calls (which matches this workflow's usual
pattern of reviewing `git status` after staging, before committing).

## Files touched

**New:**
- `~/.claude/skills/design-before-building/SKILL.md`
- `~/.claude/skills/tdd-live-code-carveout/SKILL.md`
- `~/.claude/skills/debugging-discipline/SKILL.md`
- `~/.claude/skills/documentation-backlog-hygiene/SKILL.md`
- `~/.claude/skills/independent-review-pass/SKILL.md`
- `~/.claude/skills/ui-implementation-guidelines/SKILL.md`
- `.claude/rules/live-code-tdd.md`
- `.claude/rules/live-eval-verification.md`
- `scripts/check_docs_sync.py`, `tests/test_check_docs_sync.py`
- `hooks.PreToolUse` entry in `.claude/settings.json`
- `docs/plans/2026-09-15-claude-md-restructure.md` (this file)
- `docs/decisions/2026-09-15-claude-md-restructure.md`

**Modified:**
- `~/.claude/CLAUDE.md` (623 → ~340 lines)
- `CLAUDE.md` (project root, 177 → ~140 lines)
- `PROJECT_INDEX.md`

## Verification

See the paired decision file's Verification section for what was actually
run (unit tests, ruff, line counts, manual hook trigger test).
