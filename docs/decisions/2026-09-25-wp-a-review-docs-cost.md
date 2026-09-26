# Tiered diff-based review and ADR-gated documentation (WP-A)

**Date:** 2026-09-25

## Context

The workflow-skills overhaul roadmap
(`docs/plans/2026-09-25-workflow-skills-overhaul-roadmap.md`) measured the cost of the current
process. Since about 2026-08-01, 161 commits wrote 99 decision files, 39 plan files and 53
review files (about 1.19MB). Each review file shows 2–5 rounds, and every round re-ran four
passes. This is new information, together with the user's token-economy priority, so this
change **revisits two prior decisions** (global CLAUDE.md §4):

- The unconditional five-pass review floor in `independent-review-pass`. It predates the
  `~/.claude` repo: it's already present in the `3fb59aa` snapshot, and no decision file
  records it.
- The 2026-09-14 documentation overhaul, which gave every decision, plan and review its own
  dated file.

The plan-review floor (`2026-09-17-mandatory-plan-review-floor.md`) is kept unchanged. Only
what the reviewer receives changes: the artifact plus its contract.

## Decision

WP-A of the roadmap, items 1–11, as settled in its "User decisions" section:

- **Review depth follows the actual diff**, re-classified at review time:
  - **Trivial**: `/code-review low` when code is touched, else a self-check.
  - **Standard**: `/code-review medium`, `arch-reviewer` on Sonnet, `security-reviewer`
    (skipped for test-only diffs) and `/simplify`.
  - **Substantial** (a blast-radius path or about 300+ lines): `/code-review high` and
    `arch-reviewer` on Opus.
- **Re-rounds are delta-only**: the passes that flagged the issue plus `/code-review low`, run
  against a `git stash create` snapshot. `security-reviewer` runs on the delta only when it
  changes non-test executable code. A fix outside round 1's files triggers a full round.
  Nits never reopen a round.
- **Documentation**:
  - A decision file only when the ADR gate passes (hard to reverse, surprising, a real
    trade-off). Otherwise the commit body is the record (why / verified / follow-ups).
  - Live-found regressions are exempt from the gate and still get a decision file.
  - Plan-review findings and the review log live inside the plan.
  - Repo plan copies only for Substantial or multi-session work. Review files only for
    Substantial work, or for a deferred or disputed finding.
  - The prompt-audit roadmap's WP5–WP8 keep the per-WP plan, review and decision files that
    roadmap specifies, because later WPs read their eval baselines from them. The rule is in
    SEC `CLAUDE.md`, and was found by this change's review.
  - `documentation-backlog-hygiene` is rewritten from 8722 to 3727 bytes.
- **Tiers keep their names, but the axes are split**: design depth by uncertainty, review
  depth by the diff, and size by session fit. A blast-radius diff raises review depth only,
  not documentation depth.
- **Reviewer agents**:
  - `arch-reviewer` gains Checklist C (spec conformance against the plan), a smell baseline,
    a deletion test, a guard-the-bar item and API lines.
  - `plan-reviewer` receives the artifact plus its contract and checks test seams.
  - `security-reviewer` gains an LLM/agent category.
- **Global CLAUDE.md §2** gains three lines:
  - name the questions each log must answer;
  - fire a cheap offline failure path once;
  - LLM calls log tokens, latency and retries.

## Why

- **Review cost**: most rounds after the first re-reviewed unchanged code. A delta-only
  re-round keeps the pass that found the issue and drops the re-run of the rest.
- **Security trigger**: a path-list trigger for `security-reviewer` was approved, then dropped
  after measuring. 94 of 117 code commits since 2026-08-01 touched the candidate list, so it
  would have saved about 20% of passes. The cost would have been a rule file, precedence rules
  and a re-evaluation on every delta.
- **Documentation**: most decision files recorded changes that were easy to reverse and
  unsurprising, which is what a commit body already covers. Session start still finds them,
  because SEC `CLAUDE.md` now adds `git log --grep=<module>` to the before-design step.
- **No pre-push diff-guard script (item 11)**: a `check_diff_guards.py` would misfire and
  wasn't worth its cost. `arch-reviewer`'s guard-the-bar item covers new suppressions,
  skip markers and lowered thresholds. A `/retro` may promote it to a deterministic check if
  reviewers keep catching the same thing.
- **Global CLAUDE.md grew by 683 bytes** (13288 → 13971), missing the no-net-growth aim.
  - The first draft grew by 1082 bytes. Tightening the tier and logging text brought it down.
  - The rest is required WP-A content: the axis split, the new table rows and the §2 lines.
  - Cutting unrelated rules to make room risked changing their meaning. The WP-B/C retros and
    the recurring workflow retro can revisit this.
- **Skills and agents assessed but not adopted**, with reasons:
  - **Solo project with no release process**: ci-cd, git-workflow/versioning, shipping and
    deprecation. The pre-push gate already does CI's job.
  - **Already covered here**:
    - spec-driven and planning-breakdown: the plan file is the spec, and multi-session work
      already splits into roadmap + work packages.
    - incremental-impl: `tdd-live-code-carveout`.
    - code-simplification: `/simplify`.
    - doc/ADR skill: `documentation-backlog-hygiene`.
    - context-engineering and handoff: §6 and the Compact instructions.
    - domain-modeling/CONTEXT.md: `PROJECT_INDEX.md`.
  - **Duplicates our reviewer agents**: the addy persona agents.
  - **Hook machinery with no payoff here**: the sdd-cache, simplify-ignore and session-start
    hooks. CLAUDE.md and the index already load at session start.
  - **Bound to an issue tracker we don't use** (BACKLOG.md is the tracker): triage,
    to-tickets, to-spec and setup.
  - **Persona or interactive formats with no current need**: wizard, teach, to-questionnaire
    and ask-matt. WP-B's `grill-me` covers the questioning.
  - **Absorbed during the rewrites rather than added as a file**: writing-for-agents
    (progressive disclosure, positive phrasing, pruning).

## Files touched

- **`~/.claude`**:
  - `CLAUDE.md`;
  - `agents/{arch,plan,security}-reviewer.md`;
  - the `independent-review-pass`, `design-before-building` and
    `documentation-backlog-hygiene` skills;
  - three memories: split-plans, the WP5 replicate and the project-context doc.
- **SEC**:
  - `CLAUDE.md`, `.claude/rules/live-eval-verification.md`, `BACKLOG.md` and
    `PROJECT_INDEX.md`;
  - `docs/plans/TEMPLATE.md` and `docs/reviews/TEMPLATE.md`;
  - the WP-A plan, its plan review, this file and the review file.

## Verification

- **Byte sizes**:
  - review skill: 6495 bytes, under its 6560 limit;
  - docs skill: 3727 bytes;
  - global CLAUDE.md: 13971 bytes.
- **Contradiction grep** across both instruction sets (the plan's Verification section). Every
  remaining hit was judged legitimate.
- **Review**: an independent rule-preservation audit, recorded in
  `docs/reviews/2026-09-25-wp-a-review-docs-cost.md`.
- **Docs-health check**: run against a scratch index.
- **Follow-up, live check**: the first real Standard task after this names the passes it ran
  in its commit body. That confirms the new review tier works in practice.

## Related

- Plan: `docs/plans/2026-09-25-wp-a-review-docs-cost.md`. Plan review:
  `docs/reviews/2026-09-25-wp-a-review-docs-cost-plan-review.md`.
- Roadmap: `docs/plans/2026-09-25-workflow-skills-overhaul-roadmap.md` (WP-A).
- Revisits `docs/decisions/2026-09-14-documentation-system-overhaul.md`.
- Revisits the five-pass review floor in `independent-review-pass` (no decision file; see
  `git -C ~/.claude log -S five-pass`).
- Keeps `docs/decisions/2026-09-17-mandatory-plan-review-floor.md`.
