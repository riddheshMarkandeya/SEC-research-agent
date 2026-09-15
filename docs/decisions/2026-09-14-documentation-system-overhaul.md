# Documentation system overhaul: index + per-decision files replace the narrative changelog

**Date:** 2026-09-14

## Context

`PROJECT_CONTEXT.md` had grown to 5,703 lines and ~65 sections as one
continuously-appended narrative changelog, read in full at the start of
every session. Code comments across the repo had the same problem —
multi-line decision-history narrations embedded in docstrings/comments
instead of living in a changelog/plan/review doc. The user asked for a
system modeled on this session's own auto-memory (`MEMORY.md` index +
individual files, loaded on demand) and this project's own
`docs/plans/`/`docs/reviews/` convention.

## Decision

Replaced the single narrative file with five distinct artifact roles:
`PROJECT_INDEX.md` (renamed and repurposed from `PROJECT_CONTEXT.md` —
a short project overview plus a one-line, linked, reverse-chronological
index entry per file in the three directories below), `docs/decisions/`
(new — one dated file per Standard+ change, never appended to),
`docs/plans/`, `docs/reviews/` (unchanged conventions, now with real
`TEMPLATE.md` files), and `BACKLOG.md` (tightened: done items are
deleted, not struck through). All 62 of `PROJECT_CONTEXT.md`'s original
headers were migrated into 56 new `docs/decisions/*.md` files. Both
`CLAUDE.md` files (global and project) were updated to encode the new
model as standing workflow rules, including a comment-pointer policy
(terse links to a decision file are fine; retelling history inline in
code is not).

## Why

See `docs/plans/2026-09-14-documentation-system-overhaul.md` for the
full design reasoning, prior-art check (ADR/MADR, Changesets), and the
tradeoffs accepted (a recurring index-sync cost, in exchange for never
again reading 5,700+ lines to find one prior decision).

## Files touched

`CLAUDE.md` (global and project), `BACKLOG.md`, `PROJECT_CONTEXT.md` →
`PROJECT_INDEX.md`, 56 new `docs/decisions/*.md` files plus
`docs/decisions/TEMPLATE.md`, `docs/plans/TEMPLATE.md`,
`docs/reviews/TEMPLATE.md`.

## Verification

See `docs/reviews/2026-09-14-documentation-system-overhaul.md` for the
full self-check: index-integrity diff (81 files ↔ 81 index links, zero
mismatch), `BACKLOG.md` hygiene greps (clean), repo-wide
`PROJECT_CONTEXT` sweep, and a content-fidelity spot-check against the
pre-migration file (via `git show HEAD:PROJECT_CONTEXT.md`).

## Related

`docs/plans/2026-09-14-documentation-system-overhaul.md`,
`docs/reviews/2026-09-14-documentation-system-overhaul.md`. Deferred
follow-up (not part of this change): the codebase comment-audit/rewrite
that extracts decision-history narration out of 19 `.py` files' comments
and into `docs/decisions/` — see `BACKLOG.md`.
