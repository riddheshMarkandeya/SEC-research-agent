# Cap PROJECT_INDEX.md's session-read cost permanently

**Date:** 2026-09-15

## Context

`PROJECT_INDEX.md` exists to replace `PROJECT_CONTEXT.md`, a single
narrative changelog that grew to 5,703 lines and became too expensive to
read every session
(`docs/decisions/2026-09-14-documentation-system-overhaul.md`). Measured
today: `PROJECT_INDEX.md` itself had reached 154 lines and 112 index
entries, spanning ~33 days of project history — roughly 3.4 entries/day
on average, with a single active session adding 6 more. Read in full
every session as originally instructed, this file was on the same
unbounded-growth trajectory that killed the old changelog, one level
removed. Not urgent at 154 lines, but foreseeable within months of
continued active use, and cheap to fix now rather than as a disruptive
migration later.

## Decision

Split `PROJECT_INDEX.md`'s single `## Index` section into a capped
`## Recent` section (the newest 50 entries, trimmed back to 40 whenever
exceeded) plus a new sibling file, `PROJECT_INDEX_ARCHIVE.md`, holding
everything older. `Recent` is read in full every session, same as
before; `PROJECT_INDEX_ARCHIVE.md` is never read in full, only grepped
on demand when a topic might be older than what's in `Recent`.

Migrated the then-current 112 entries: newest 40 kept in `Recent`,
oldest 72 moved verbatim into the archive's own `## Archive` section,
both still reverse-chronological. Updated three places to state this
consistently at their own layer of generality: `PROJECT_INDEX.md`'s own
header (names the concrete 50/40 numbers), this project's `CLAUDE.md`
documentation-system section (names the concrete two-file structure and
numbers, and updates the "check prior art" sentence to cover the
archive), and the global `~/.claude/skills/documentation-backlog-hygiene/SKILL.md`
(states the pattern generically — no numbers or filenames — as a
generalizable lesson for any project's index file once it reaches this
point).

## Why

An entry-count cap, not a calendar window: this project's own
convention already guarantees one physical line per entry, so an
entry-count cap converts exactly into a line-count cap — a calendar
window (e.g. "last 14 days") has no true hard bound, since a single
busy day can spike it arbitrarily (this session alone added 6 entries).
A single flat archive, not sharded by month/quarter: grep cost isn't
sensitive to file size at this project's scale, so sharding would add a
bookkeeping question ("which shard does this belong in") for no real
benefit. No new hook automation for the rollover: consistent with this
project's established stance against automating rare, cheap-by-hand
tasks (the ruff rollout, the docs-sync hook's narrow scope), and this
session's own finding that a `PreToolUse` hook can't inject a visible
non-blocking nudge anyway, so even a minimal automated reminder would
mean a new hard gate for a cosmetic housekeeping step — not
proportionate. The 50/40 numbers are a judgment call, not derived from a
hard constraint, chosen generously since each entry costs only ~30
tokens — the extra headroom over a tighter cap is essentially free and
reduces how often "was there something like this recently" needs the
archive at all.

This generalizes a lesson the project already learned once
(`2026-09-14-documentation-system-overhaul.md`: an ever-growing
inline narrative becomes too expensive to read every session) and
applies it recursively to the index that fix produced — hence updating
the global skill, not just this project's file, so a future project's
index gets this from the start once it grows large enough.

## Files touched

`PROJECT_INDEX.md` (split, reworded header), `PROJECT_INDEX_ARCHIVE.md`
(new), this project's `CLAUDE.md` (documentation-system section),
`~/.claude/skills/documentation-backlog-hygiene/SKILL.md` (generic
pattern). No source code, no `scripts/check_docs_sync.py` change needed
(confirmed by reading it: it only checks whether the literal string
`PROJECT_INDEX.md` is staged, which is unaffected by the split — new
entries always land in `Recent` first).

## Verification

Prose/data-file-only change; no automated test applies. Entry-count
conservation confirmed by diff: sorted union of `Recent` + `Archive`
entries is byte-for-byte identical to the pre-split entry list (112 in,
40 + 72 out, zero loss or duplication). Link resolution confirmed: all
112 linked files verified to exist on disk. Grep smoke test confirmed:
searching `PROJECT_INDEX_ARCHIVE.md` for an August-era term
(`edgar`) returns the expected entry. Both edited prose sections
(project `CLAUDE.md`, the global skill) re-read for internal consistency
with what they cross-reference.

## Related

Generalizes `docs/decisions/2026-09-14-documentation-system-overhaul.md`
(the same lesson, applied one level removed). Independent of, and not
amending, `docs/decisions/2026-09-15-revoke-comment-pointer-convention.md`
(a separate documentation-hygiene change from the same session).
