# Make independent plan review a non-negotiable floor for every plan mode produces

## Context

`design-before-building`'s independent-subagent plan-review step was
conditionally gated: unconditional only for Substantial-tier plans,
extended to Standard tier only when `debugging-discipline`'s escalation
clause fired or the change touched a project-declared high-blast-radius
area (`.claude/rules/plan-review-blast-radius.md`), and never applied
to Trivial tier. The user's own experience running this workflow is
that an independent review, whenever actually spawned, has found a real
improvement almost every time — closer to the rule than the exception —
and asked for it to become a hard, unconditional rule rather than a
suggestion evaluated case-by-case: "Whenever a plan is created in plan
mode it needs to be reviewed by a subagent. Non-negotiable."

Two design forks were raised and resolved with the user directly before
drafting (`AskUserQuestion`):

1. **Enforcement mechanism** — instruction-only vs. instruction +
   mechanical `PreToolUse`/`ExitPlanMode` hook backstop. **Chosen:
   instruction-only.**
2. **Scope** — this project only vs. global. **Chosen: global.**

See Decision below for the reasoning behind each choice.

## Prior art (if applicable)

Checked the harness's own hooks documentation (cached from a prior
session) to confirm whether a mechanical `ExitPlanMode` enforcement
hook was even feasible before ruling it out for now: it is — a worked
`PermissionRequest`/`ExitPlanMode` matcher example exists, and
`PreToolUse` matches on the identical tool-name mechanism — but
mechanically verifying a review *genuinely happened*, not just that
some marker text exists in the submitted plan, is a meaningfully harder
problem than this project's existing `check_docs_sync.py` hook solves
(which checks staged files, a hard unambiguous fact). Also re-read this
project's own `independent-review-pass` skill in full, since the new
unconditional plan-review floor is explicitly modeled on its existing
"regardless of tier" code-review floor — the wording and structure
below deliberately mirror it.

## Decision / Design

**1. Rewrite `~/.claude/skills/design-before-building/SKILL.md`** so
the independent-subagent plan-review step becomes an unconditional
review floor — mirroring `independent-review-pass`'s own "regardless of
tier" code-review floor, one stage earlier (before an implementation
gets built on the plan's premises, not after). No tier gate, no
exception conditions. Effort still scales with plan size, but the step
itself is never skipped. The paragraph moved out of `## For Substantial
work` (since review is no longer Substantial-specific) now instructs
recording the review as its own `docs/reviews/` file rather than
folding it into the plan or decision file.

**2. Rewrite (not reword) `.claude/rules/plan-review-blast-radius.md`'s**
opening paragraph — the old "even at Standard tier... gets the one...
step" phrasing was on/off framing that would self-contradict once
review is unconditional. Reframed: the file's incident-grounded list
now gates *review depth* (escalated scrutiny) within the floor every
plan already gets, not whether review happens at all. The incident list
itself is untouched.

**3. Edit `~/.claude/CLAUDE.md`'s Scope tiers table**, Design & approval
row, Trivial cell, adding an explicit exception: if plan mode is
nonetheless entered for a Trivial-classified task, the review floor
still applies. This is a top-level gate question (whether the skill is
invoked at all), not skill-internal detail, so it belongs in CLAUDE.md
itself — unlike the Standard/Substantial cells, which correctly stay
untouched since they already just point to the skill.

**4. Document with the full three-artifact set** (this plan file, a
paired `docs/reviews/` file, and a `docs/decisions/` synthesis), plus
`PROJECT_INDEX.md` and `BACKLOG.md` updates — see Files and steps.

**Why**: The prior conditional carve-out (2026-09-16) was itself
already one escalation past "Substantial-tier only," justified by a
real incident (the CRM fiscal-year fix) where a Standard-tier task
needed the review but didn't get it automatically. This is the natural
next and final escalation: a conditional trigger depends on correctly
recognizing, in the moment, that a blast-radius or debugging-discipline
condition applies — a weaker guarantee than an unconditional floor.
Given the user's stated near-universal hit rate for independent plan
review surfacing real issues (this very plan's own review being a live
example — see Addendum), the risk of a conditional trigger silently not
firing is no longer worth carrying. The hook-backstop alternative was
rejected for now, not never, because proving a review genuinely
happened is a harder mechanical problem than it first looks — tracked
as a deferred `BACKLOG.md` item instead of dropped.

## Files and steps

1. `~/.claude/skills/design-before-building/SKILL.md` — frontmatter
   `description` and body rewritten per Decision §1 (global skill,
   outside this repo's git history).
2. `~/.claude/CLAUDE.md` — Scope tiers table, Design & approval row,
   Trivial cell, per Decision §3.
3. `.claude/rules/plan-review-blast-radius.md` — opening paragraph
   rewritten per Decision §2; incident list unchanged.
4. `docs/plans/2026-09-17-mandatory-plan-review-floor.md` — this file.
5. `docs/reviews/2026-09-17-mandatory-plan-review-floor.md` — the
   independent review's findings on this plan's first draft.
6. `docs/decisions/2026-09-17-mandatory-plan-review-floor.md` — short
   synthesis linking to this plan and its paired review.
7. `PROJECT_INDEX.md` — three new `## Recent` lines.
8. `BACKLOG.md` — one new item tracking the deferred hook-backstop
   option.

## Testing and verification

Prose/instruction-only change — no code, no tests, no live-code surface
per this project's `tdd-live-code-carveout`. Per `independent-review-pass`'s
own carve-out ("a change confined entirely to a non-code file... can
skip review entirely with just a self-check"), verification is: re-read
every edited/created file in full after editing to confirm no stale
tier-conditional language remains (grep for `Substantial-tier` and
`even at Standard tier` across the touched skill/rule files) and that
the CLAUDE.md Trivial-cell edit and the skill's new text are mutually
consistent.

## Addendum (if applicable)

This plan's first draft was independently reviewed by a freshly-spawned
subagent before being finalized (per the very rule it replaces, still
in force at Substantial tier while this plan was in draft — a live
demonstration of the pattern being made mandatory). The review found
three real gaps, all incorporated into the plan before approval: the
CLAUDE.md Trivial-cell gap (Decision §3), the need for a full rewrite
rather than a word-swap of `plan-review-blast-radius.md`'s framing
(Decision §2), and the missing `docs/plans/`/`docs/reviews/` artifacts
this file and its paired review now supply. See
`docs/reviews/2026-09-17-mandatory-plan-review-floor.md` for the full
findings.
