# Review: plan for making independent plan review a non-negotiable floor

> This reviews a **plan**, not a finished diff — `design-before-building`'s
> pre-implementation review pass, not `independent-review-pass`'s
> post-implementation code review. Adapted from this template's usual
> Pass 1/Pass 2 diff-review shape accordingly, per the template's own
> "use judgment" note for reviews that don't fit the single-diff case.

Plan: `docs/plans/2026-09-17-mandatory-plan-review-floor.md`. The plan
proposes rewriting the global `design-before-building` skill so its
independent-subagent plan-review step becomes an unconditional floor
(no tier gate), plus supporting edits to `~/.claude/CLAUDE.md` and this
project's `.claude/rules/plan-review-blast-radius.md`.

## Independent plan review (fresh subagent, no memory of the drafting session)

Given the first draft of the plan plus the current, unmodified content
of `design-before-building/SKILL.md`, `plan-review-blast-radius.md`,
`~/.claude/CLAUDE.md`, `independent-review-pass/SKILL.md`, and this
project's documentation-hygiene conventions, and asked explicitly
whether the plan actually achieves "no tier gate, no exceptions,"
whether cross-references stay consistent, and whether a simpler diff
would suffice.

- **[Fixed]** The plan's claim that no `~/.claude/CLAUDE.md` edit was
  needed was wrong: the Scope tiers table's Design & approval row has a
  literal `skip` in the Trivial cell, which — left as-is — would still
  silently block the review floor for a Trivial-classified task that
  nonetheless enters plan mode (a real scenario, since plan mode is a
  session toggle independent of tier classification, not a hypothetical
  edge case). Fixed by adding an explicit exception to the Trivial cell
  itself (Decision §3 in the plan).
- **[Fixed]** `plan-review-blast-radius.md`'s opening paragraph was
  built around on/off phrasing ("gets the one... step **even at
  Standard tier**") that only parses if review is otherwise absent at
  Standard tier — leaving it in place while prepending new "floor"
  framing would have produced a self-contradictory document. The plan
  initially described this as "reword the top framing paragraph," which
  understated the scope of the fix needed. Fixed by fully rewriting the
  paragraph (Decision §2) rather than patching around the old sentence.
- **[Fixed]** The documentation plan undershot this project's own
  precedent for a comparable cross-cutting workflow change: the
  2026-09-15 CLAUDE.md restructure produced a full paired
  `docs/plans/` + `docs/reviews/` + `docs/decisions/` set, while this
  plan's first draft proposed only a decision file with the review
  "folded in... or a separate note if the review surfaced changes" —
  contradicting `documentation-backlog-hygiene`'s rule that the three
  artifact roles stay distinct. Fixed by committing to the full
  three-artifact set (this file included) rather than leaving it
  optional.
- **[Verified, no fix needed]** The core mechanism — moving the
  Substantial-only "how to run the review" paragraph into the
  tier-independent part of the skill, and reframing the blast-radius
  file to gate depth rather than whether-review-happens — was judged
  sound and not gratuitous: leaving that paragraph under a header that
  means "Substantial-only" would have been actively misleading once
  review applies to every tier, so the restructuring is required by the
  semantic change, not optional polish.
- **[Verified, no fix needed]** Depth-scaling is preserved correctly:
  the plan keeps "effort still scales with plan size" and repurposes
  the blast-radius file to control depth, matching how
  `independent-review-pass` already treats its own floor (unconditional
  pass, tier-scaled effort) — the one genuinely useful thing the old
  (a)/(b) trigger conditions did isn't lost.
- **[Flagged, addressed by inlining exact text]** The plan initially
  described the SKILL.md edit only at a summary level ("move this
  paragraph," "make this unconditional"), which risked a literal
  verbatim-move during implementation reintroducing stale
  "Substantial-tier plan" wording inside the now tier-independent text,
  or leaving the frontmatter description's trailing parenthetical
  orphaned after a find-replace. Addressed by inlining the exact
  replacement prose for both the frontmatter description and the body
  paragraphs directly into the plan, with an explicit post-edit
  instruction to grep for the literal string `Substantial-tier` in the
  result.

## Considered and ruled out

- BACKLOG.md tag format `[design, Low, TBD]` for the deferred
  hook-backstop item — checked against real precedent (the "revisit
  Pyright strict mode" item uses the same `design` tag for an
  evaluated-and-deferred alternative), consistent with actual usage.
- The harness's `ExitPlanMode`-as-hook-matcher feasibility claim — the
  plan self-flags this as coming from a cached prior-session doc fetch,
  and it isn't load-bearing since the hook option was rejected anyway;
  low risk either way.
- Whether "any plan produced in plan mode" cleanly covers every real
  scenario — yes, once combined with the CLAUDE.md Trivial-cell fix
  above; no further gap found.

## Outcome

All three confirmed findings were incorporated into the plan before
`ExitPlanMode` approval (see the plan's own Addendum section). No
second review round was run — the findings were structural/textual
(cross-reference consistency, documentation completeness), not
substantive disagreements with the core approach, and all were folded
into the plan directly rather than requiring a re-review cycle.
