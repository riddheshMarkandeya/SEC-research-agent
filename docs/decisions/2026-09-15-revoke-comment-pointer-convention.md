# Revoke the comment→decision-file pointer convention

**Date:** 2026-09-15

## Context

The 2026-09-14/15 comment audit
(`docs/decisions/2026-09-14-documentation-system-overhaul.md` through
`docs/decisions/2026-09-15-comment-audit-concluded.md`) established and
applied a convention across ~19 main-source files and several test
files: a comment explaining something non-obvious could be a terse
one-line pointer to a decision file (e.g.
`# rationale: docs/decisions/2026-09-12-<slug>.md`) instead of narrating
history inline. That convention lived in `~/.claude/CLAUDE.md`'s
SE-principles section (global, applies to every project) and was named
as an explicit review checklist item — "the pointer-not-narration rule"
— in the `independent-review-pass` skill.

The user revisited this: a file path embedded in a code comment is a
link that can rot silently. The file it names can be renamed, moved, or
deleted by later, unrelated work with no connection back to the comment
that references it, leaving something that looks authoritative but
points nowhere — a real downside the original decision didn't weigh.

## Decision

Revised two files to require comments be concise and **self-contained**
— stating the non-obvious reasoning directly, in the comment's own
words, never as a pointer/link to a decision file or other external doc:

- `~/.claude/CLAUDE.md`'s SE-principles section (the canonical statement
  of the rule).
- `~/.claude/skills/independent-review-pass/SKILL.md`'s Pass 2 checklist
  (renamed from "the pointer-not-narration rule" to "the self-contained-
  comment rule," with a pointer-style comment now named explicitly as a
  real finding).

**Not done, deliberately**: no mass refactor of the existing pointer-
style comments the 2026-09-14/15 audit introduced across the codebase.
Per explicit instruction, those are left as pre-existing style debt,
fixed opportunistically via the *already-existing* incremental-
improvement mechanism (SE-principles section: bring a touched function/
block up to the current standard as part of whatever change touches it
next) when future work happens to touch them — no dedicated cleanup pass,
no new tracking mechanism, and no `BACKLOG.md` item (this is diffuse
debt across ~30 files, the same category as an oversized function, which
also isn't individually backlogged).

## Why

This is a revisit of `docs/decisions/2026-09-14-documentation-system-overhaul.md`
and the comment-audit round decisions that applied its convention
(`2026-09-14-comment-audit-round1.md` and `round2.md`,
`2026-09-15-comment-audit-round3.md` through `round6.md`, and
`2026-09-15-comment-audit-concluded.md`) — named explicitly per this
workflow's own "revisiting prior decisions" rule, which requires saying
so out loud rather than reopening or standing by a prior call silently.
Something did change relative to the original decision: it traded "no
narration duplicated in code" for "a link that can go stale independent
of the comment," and the file-path-rot risk of that trade wasn't weighed
at the time. The fix doesn't remove the original goal (comments still
shouldn't re-narrate full incident history) — it just removes the
"point to a file instead" escape valve, replacing it with "say the
essential fact directly." `PROJECT_INDEX.md`'s index plus `git log`/
`git blame`/`git diff` already existed as the real historical record
before this change (the git-as-inspection-tool section of the same
`CLAUDE.md` already says so, for a different original purpose) — nothing
new had to be built to make this revocation safe; comments no longer
need to point anywhere because the actual index was never the comment
itself.

The broader documentation-system overhaul that
`2026-09-14-documentation-system-overhaul.md` introduced — `PROJECT_INDEX.md`,
one dated file per decision/plan/review, `BACKLOG.md`, and those files'
own `Related:` cross-linking to *each other* — is explicitly **not**
reversed by this change. That system is actively maintained and
deliberately designed to be the durable index; only the practice of
code comments linking into it is revoked.

## Files touched

`~/.claude/CLAUDE.md`, `~/.claude/skills/independent-review-pass/SKILL.md`.
No source code files.

## Verification

Prose-only change; no automated test applies. Confirmed by re-reading
both edited sections for internal consistency (neither contradicts the
surrounding text it cross-references — the version-control section's
`PROJECT_INDEX.md`/git-history pointer, the SE-principles incremental-
improvement mechanism). Confirmed via grep across all 6 skills and both
`CLAUDE.md` files that the old convention appeared in exactly these two
places before this change and nowhere else, so nothing was missed.

## Related

Amends `docs/decisions/2026-09-14-documentation-system-overhaul.md` and
the comment-audit round decisions
(`2026-09-14-comment-audit-round1.md`, `round2.md`,
`2026-09-15-comment-audit-round3.md` through `round6.md`,
`2026-09-15-comment-audit-concluded.md`) — specifically the code-comment
convention those established, not the broader documentation system they
are also part of.
