# Token-efficiency workflow: earlier compaction, model-routed reviewers, trimmed instructions

**Date:** 2026-09-25

**Scope note:** most of this change is to **global** files that apply to every project:
- `~/.claude/CLAUDE.md`
- `~/.claude/settings.json`
- `~/.claude/skills/{independent-review-pass,design-before-building}/SKILL.md`
- `~/.claude/agents/*.md`

It's recorded here because this project is where the work was done. `~/.claude` is now a local
git repo (no remote), so `git -C ~/.claude log` holds the exact before/after.

## Context

Claude token usage was high. Plan: `docs/plans/2026-09-25-token-efficiency-workflow.md`.

Baseline across this project's 23 session transcripts (8,870 main-thread calls, 476 subagents,
cache reads weighted at 0.1):

| Measure | Value |
|---|---|
| Main-thread share of cost-weighted tokens | ~86% (~440M equivalent); subagents ~70M |
| Median context per main-thread call | 351k (p90 727k, max 934k) |
| Main-thread input sent above 300k context | 80% |
| Auto-compactions | 4, all at ~934k |
| Manual compactions | 17, at 200k–906k |
| Size of a compacted session | 15–30k |
| Subagents already on Sonnet | 62% |

The reason: Opus 5.5 has a native 1M window, so it auto-compacts only at ~967k.

## Decision

1. **`autoCompactWindow: 300000`** in user settings, with three mitigations:
   - a `# Compact instructions` section in the project `CLAUDE.md`;
   - manual `/compact` at natural breaks;
   - `claude --autocompact 600k` for a deep debugging session.
2. **Three reviewer agents** in `~/.claude/agents/`, each holding its checklist:
   - `plan-reviewer`: opus;
   - `arch-reviewer`: sonnet, escalated to opus for Substantial tier or blast-radius paths;
   - `security-reviewer`: sonnet.

   Every reviewer returns one line per finding and ends with a `checked:` line. If an agent
   isn't loaded, the skills fall back to general-purpose.
3. **The review loop ends after one clean round**: no new findings and no `/simplify` edits. The
   same issue twice with no clean fix still goes to the user. This revisits the two-clean-rounds
   rule. The new information is the measured cost: WP1 alone ran 3 full rounds.
4. **Trims that keep every rule** (bytes before → after):

   | File | Before | After |
   |---|---|---|
   | global `CLAUDE.md` | 15,972 | 10,519 |
   | `independent-review-pass` | 17,336 | 6,370 |
   | `design-before-building` | 6,514 | 3,412 |
   | project `CLAUDE.md` | 11,961 | 8,183 |

   Together that's 51.8KB → 28.5KB, 45% smaller.

   Rationale stories were cut to one clause. Additions:
   - a ponytail-style minimal-solution ladder in global §1, with logging, error handling,
     validation and TDD tests explicitly exempt;
   - a new global §6 "Token economy";
   - "grep `BACKLOG.md`, don't read it whole".

## Why

- **Compaction window.** Main-thread context size, not subagent model choice, dominates cost.
  A simulation replaying the 23 sessions:

  | Window | Main-thread input | Extra compactions per session |
  |---|---|---|
  | 200k | −68% | ~4.5 |
  | 300k | −56% | ~2 |
  | 400k | −46% | ~1.5 |

  We picked 300k over 200k so fewer compactions land mid-task. That matters because
  compaction loses detail: exact errors, dead ends, and the path-scoped `.claude/rules/*` files.
  Long context has its own quality cost, though ("performance degrades as context fills",
  Claude Code best-practices doc).
- **Reviewer models.** Opus is kept wherever the reviewer's job is open-ended judgment: plan
  review, and architecture review on high-risk diffs. The plan review argued this; a Sonnet plan
  reviewer was the riskiest downgrade proposed. Security review stays on Sonnet because it's a
  fixed checklist with an 80% confidence bar. The rule audit flagged that as a behavior change;
  it was accepted because it matches the approved plan.
- **Prior art.**
  - From caveman: we adopted its subagent-contract idea (cavecrew) and its auto-clarity rule. We
    rejected chat-style compression (it measured ~8.5% savings and hurts readable pushback) and
    caveman-compress (it risks dropping qualifiers).
  - From ponytail: we adopted the ladder. Its line-level review tags were left to `/simplify`.
- **`CLAUDE_CODE_SUBAGENT_MODEL` experiment.** Not adopted. We ran `/simplify` headless on a
  148-line throwaway diff: its 4 subagents already pass `model: "sonnet"` per call, and that
  overrides the env default. So the setting adds nothing for `/simplify`, and it would have
  silently moved Explore and Plan too.
- **Dropped.** The `locator` agent (duplicates Explore, which can run on haiku per call) and the
  `log-summarizer` agent (risks mangling exact eval figures).

**Rationale kept here from the trimmed files, so it isn't lost:**
- The plan-review floor exists because it has found a real improvement almost every time.
  Examples: the 2026-09-16 CRM fiscal-year fix caught 2 more issues, and an earlier citation
  redesign shipped a dropped defense that only code review caught
  (`docs/decisions/2026-09-17-mandatory-plan-review-floor.md`).
- Skill invocation is mandatory because skipping `design-before-building` missed 3 bugs, and
  following project conventions instead of loading `tdd-live-code-carveout`/
  `documentation-backlog-hygiene` caused user-caught misses.
- The compiled `/security-review` is banned because it hangs unpredictably.

## Files touched

Global:
- `~/.claude/.gitignore` (new; allowlist)
- `~/.claude/agents/{plan-reviewer,arch-reviewer,security-reviewer}.md` (new)
- `~/.claude/CLAUDE.md`
- `~/.claude/settings.json`
- `~/.claude/skills/independent-review-pass/SKILL.md`
- `~/.claude/skills/design-before-building/SKILL.md`

Project:
- `CLAUDE.md`
- `PROJECT_INDEX.md`
- `BACKLOG.md`
- the plan, the plan review and the rule audit

## Verification

- **Sizes** as above.
- **Rule-preservation audit** by a fresh Opus subagent: 13 items, nothing core lost. 12 were
  fixed and 1 accepted (security reviewer on Sonnet). See
  `docs/reviews/2026-09-25-token-efficiency-rule-audit.md`.
- **Pre-commit docs check** passes.
- **Pending (BACKLOG):**
  - a new session confirms the agents load and the contract holds;
  - the 2-WP pilot measures tokens and finding counts against the baseline above.

**Revisit triggers:**
- the pilot shows more missed findings → restore Opus reviewers or the two-round loop;
- compaction loses something important → raise the window.

## Related

- Revisits the two-clean-rounds loop rule in `independent-review-pass`, introduced with the
  layered review; no single decision file covered it.
- Related to `docs/decisions/2026-09-23-context-management-hooks.md` (the compact-at-boundary trial).
- Plan review: `docs/reviews/2026-09-25-token-efficiency-plan-review.md`.
