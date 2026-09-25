# Read/diff/cache habits, status line, medium effort, recurring workflow retro

**Date:** 2026-09-25

**Scope note:** mostly global files (`~/.claude/…`), recorded here where the work was done.

## Context

A read/grep and cache audit of the 23 session transcripts. Evidence and numbers are in
`docs/plans/2026-09-25-read-diff-cache-habits.md`. In short:
- Read is 59% of tool output, led by 847 overlapping reads of `agent.py` and re-reads of
  auto-loaded files.
- Diffs added another 4.6M chars.
- Cache rebuilds after an idle hour or a `/model` switch cost about 11%.
- Output tokens cost about 8%.

The user asked whether to rotate the trace log. The data says no: it's never read whole.

## Decision

- Global CLAUDE.md §6 gets **Reading**, **Diffs** and **Cache** rule groups.
- The review skill and reviewer agents take diff *commands*, run `--stat` first, and read code
  in ranges.
- The global `effortLevel` is now medium.
- A new status line, `~/.claude/scripts/statusline.js` (with tests), shows context tokens and
  the cache expiry time.
- Backlog changes:
  - new: an eval summary mode and the `agent.py`/`test_agent.py` split;
  - rewritten: the trace-helper item;
  - new: a **Recurring workflow retro** (due 2026-10-09, every 2 weeks, gated on at least 4
    Standard+ tasks), surfaced through a memory file.

## Why

- **The rules target the measured sinks directly.** The cheapest token is the one never read.
  A result stays in context until the next compaction.
- **The `/effort` wording follows the docs.** The plan review suspected `/effort` rebuilds the
  cache like `/model` does. The prompt-caching docs say it keeps the cache on Opus 5.5 and
  Fable 5.1 with a subscription, and rebuilds it on other models.
- **The status line exists because Claude can't see its own token count.** It shows the user
  when to `/compact`, and when the cache will go cold. The expiry is an absolute time because
  the status line doesn't refresh while idle, and the context is a plain count so an
  `--autocompact` launch can't make it wrong.
- **The retro cadence fits the data.** 23 sessions ran in 31 days, so two weeks with at least
  4 Standard+ tasks gives enough data. The Recurring exception is pinned in the BACKLOG header,
  and every run writes a decision file, so the "never vanish without a trace" rule still holds.
- **The retro skill is deferred to the second run.** By then the repeated need is real; before
  that, it would be YAGNI.
- **Plan review**: 8 findings. Findings 1–7 were folded in. Finding 8 (the Opus effort override
  is redundant) was kept as an explicit pin. See
  `docs/reviews/2026-09-25-read-diff-cache-habits.md`.

## Files touched

- **Global:** `CLAUDE.md`, `settings.json`, `.gitignore` (`!/scripts/`), `scripts/statusline.js`
  and `scripts/statusline.test.js`, `skills/independent-review-pass/SKILL.md`,
  `agents/{arch,security}-reviewer.md`, memory `project_workflow_retro_due.md` and `MEMORY.md`.
- **Project:** `BACKLOG.md`, `PROJECT_INDEX.md`, the plan, this decision and the review.

## Verification

- 11 `node:test` cases pass, including the 1.0M rounding boundary that `/code-review` found.
- The docs' sample JSON renders `Opus · ctx 16k · cache warm until 11:00 (45k if cold) · 5h 24%`.
- Settings parse as JSON.
- The five-pass review, including the reviewer agents' first real contract run, is in the
  review file.

## Related

- Builds on `docs/decisions/2026-09-25-token-efficiency-workflow.md` and
  `docs/decisions/2026-09-25-promote-context-management.md`.
