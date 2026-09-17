# Made independent plan review an unconditional floor for every plan mode produces

**Date:** 2026-09-17

## Context

`design-before-building`'s independent-subagent plan-review step was
conditionally gated (Substantial tier by default, Standard tier only
under two named trigger conditions, never Trivial). The user asked for
it to become a hard, unconditional rule instead — "non-negotiable" —
based on their own experience that the review, whenever actually run,
has found a real improvement almost every time. Full reasoning, the two
design forks resolved via `AskUserQuestion` (enforcement mechanism,
scope), and the plan itself: `docs/plans/2026-09-17-mandatory-plan-review-floor.md`.

## Decision

Rewrote `~/.claude/skills/design-before-building/SKILL.md` (global) so
the plan-review step is an unconditional floor mirroring
`independent-review-pass`'s own "regardless of tier" code-review floor.
Added a Trivial-tier exception to `~/.claude/CLAUDE.md`'s Scope tiers
table so a plan produced in plan mode still gets reviewed even for a
task classified Trivial. Reframed this project's
`.claude/rules/plan-review-blast-radius.md` from gating whether review
happens to gating how much extra scrutiny it gets. Enforcement is
instruction-only, not backed by a mechanical hook — a `PreToolUse`/
`ExitPlanMode` hook was confirmed technically feasible but rejected for
now, tracked in `BACKLOG.md` instead.

## Why

See the plan's own Decision/Design and Why content — this file is a
short synthesis, not a retelling. In brief: the prior conditional
carve-out was itself already one escalation past "Substantial-tier
only"; given the review's near-universal hit rate for surfacing real
issues, a conditional trigger's risk of silently not firing was no
longer worth carrying relative to an unconditional floor.

## Files touched

- `~/.claude/skills/design-before-building/SKILL.md`
- `~/.claude/CLAUDE.md`
- `.claude/rules/plan-review-blast-radius.md`
- `docs/plans/2026-09-17-mandatory-plan-review-floor.md`
- `docs/reviews/2026-09-17-mandatory-plan-review-floor.md`
- `docs/decisions/2026-09-17-mandatory-plan-review-floor.md` (this file)
- `PROJECT_INDEX.md`
- `BACKLOG.md`

## Verification

Prose/instruction-only change — self-check only, per
`independent-review-pass`'s non-code-file carve-out. Full verification
approach: `docs/plans/2026-09-17-mandatory-plan-review-floor.md`'s own
Testing and verification section.

## Related

Supersedes the conditional carve-out that lived in
`design-before-building/SKILL.md`'s body text since 2026-09-16 (no
separate decision file existed for that carve-out itself — closest
incident citations are `docs/decisions/2026-09-16-crm-fiscal-year-lookup-fix.md`
and `docs/decisions/2026-09-17-fix-judge-hypothetical-date-bug.md`).
Paired plan: `docs/plans/2026-09-17-mandatory-plan-review-floor.md`.
Paired review: `docs/reviews/2026-09-17-mandatory-plan-review-floor.md`.
