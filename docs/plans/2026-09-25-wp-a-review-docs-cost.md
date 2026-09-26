# WP-A — Review and documentation cost

## Context

This plan covers WP-A of `docs/plans/2026-09-25-workflow-skills-overhaul-roadmap.md` in the SEC
repo. The roadmap's "User decisions (settled)" and "WP-A" sections (items 1–11) say what to change
and why. This plan adds only three things: what the current-state check found, the order of work,
and how WP-A itself is reviewed. It doesn't reopen any settled decision.

WP-A is Substantial, because it changes the review and documentation process for every later
task. It touches markdown only: skills, agent definitions, rules, templates, CLAUDE.md files, one
memory and BACKLOG. It changes no source, test or script file.

## Current-state check (2026-09-25, both trees clean)

These roadmap assumptions still hold:
- The `independent-review-pass` `description:` still says "mandatory five-pass".
- That skill still has the five-pass floor, the "any fix → full round" stop rule and the
  `docs/reviews/` Record section.
- `design-before-building:30` still says to save the plan review as its own file.
- Global `CLAUDE.md:169` still saves every plan.
- `live-eval-verification.md:106-122` still requires a decision file per regression.
- Sizes: the docs skill is 8722 bytes (target about 3KB), the review skill 6560 and global
  CLAUDE.md 13288.

These passages would contradict the new rules and the roadmap doesn't list them. Step 5 folds
them in:
- **a.** `docs/plans/TEMPLATE.md` has no `## Plan review` or `## Review log` section. Add both.
- **b.** The `PROJECT_INDEX.md` blurb says "every decision, plan, and review is its own dated
  file". Add that the commit body is the record for everything else.
- **c.** The WP5 docs were committed in `2801940`, but the WP5 memory and `BACKLOG.md:62` still
  call them "untracked". Fix the phrase in both, alongside item 8's memory reword.
- **d.** `BACKLOG.md:3-8, 13-22` says finished work lives in `docs/decisions/`, and that an item
  must never vanish without a decision-file trace. It also says each Recurring run writes one.
  Reword to "the decision file if the ADR gate passes, else the commit body".
- **e.** Other passages assume every change has a decision file:
  - global `CLAUDE.md:115` (§4 "record that one-liner in the current decision file…"). Add "or
    commit body".
  - `live-eval-verification.md:112-115`, which cross-links to the regression-introducing change's
    decision file. Add "or its commit SHA" to the planned one line.
  - memory `feedback_split_large_plans.md:15`, "deviations go in each package's own plan and
    decision files". Rewrite it for the new record.
  - SEC `CLAUDE.md:4-6`, which points readers to `Recent` for past decisions. Add `git log`.
- **f.** `Recent` holds 44 entries. WP-A adds 4, making 48 (49 if WP5's decision lands first).
  No trim is needed.

**How "Substantial" is read for doc artifacts** (a wording clarification, not a new decision).
Repo plan copies and review files follow the task's *design* tier: Substantial or multi-session.
The *review* axis doesn't count here. A blast-radius diff raises review depth only, matching
`plan-review-blast-radius.md:21-24` (no documentation-depth escalation). Step 1's pass table
also says plainly what separates Standard from Substantial. Security already runs on every
Standard+ diff except test-only ones, so the real differences are the `/code-review` level and
`arch-reviewer` on Opus. That keeps the table from looking redundant.

## Steps

0. Save this plan to SEC `docs/plans/2026-09-25-wp-a-review-docs-cost.md`. Write the plan review
   to `docs/reviews/2026-09-25-wp-a-review-docs-cost-plan-review.md`, as its own file per the
   current rule. Add both `PROJECT_INDEX` lines in the same step, not batched.
1. Roadmap item 1: `independent-review-pass`, including `description:`. Keep it at or under 6560
   bytes, and add the Standard/Substantial wording above.
2. Roadmap items 2–4:
   - `arch-reviewer`: Checklist C, smells, deletion test, guard-the-bar, API lines, doc checks
     only when docs are in the diff.
   - `plan-reviewer` and `design-before-building`: artifact plus contract, test seams,
     `## Plan review` in the plan, repo copy only for Substantial or multi-session work.
   - `security-reviewer`: the LLM/agent category.
3. Roadmap item 5: rewrite `documentation-backlog-hygiene` to about 3KB, with item 8's
   regression-exemption clause.
4. Roadmap item 6: global `CLAUDE.md`.
   - Tiers split by axis, with the doc-artifact reading above.
   - The tier-table rows.
   - The narrowed §6 plan-saving rule.
   - The §2 additions.
   - Fix e's §4 line.
   - Aim for no net growth: pay for new text with cuts.
   - *(Midpoint: offer `/compact`.)*
5. Roadmap items 8–9 and a–e:
   - `live-eval-verification.md`: one line.
   - `docs/reviews/TEMPLATE.md`: the rounds/findings/disposition layout.
   - `docs/plans/TEMPLATE.md`.
   - The `PROJECT_INDEX.md` blurb.
   - The `BACKLOG.md` header and the WP5 line phrase.
   - The WP5 and split-plans memories.
   - SEC `CLAUDE.md`: the docs section, `git log --grep` in the "before design/debugging" step,
     and lines 4-6.
6. Verification, except the docs-health check.
7. Give the implementation→review `/compact` line, then run the review below.
8. Roadmap item 10: the decision file. It links the two revisited decisions under `Related`, and
   records the roadmap's skip list with reasons and item 11's rationale (no diff-guard script; a
   `/retro` may promote one later). Then write the review file and their `PROJECT_INDEX` lines,
   and delete the WP-A BACKLOG line. Then run the docs-health check.
9. Stop. Propose one commit message per repo (`~/.claude` and SEC), and commit only if asked.

## How WP-A itself is reviewed (current rules, per the roadmap)

The current `independent-review-pass` floor applies, since the new one isn't in force yet. Under
it, a change "confined to non-code files … may skip review with a self-check". Skill and agent
frontmatter could be read as the "behavior-affecting config" that the skill counts as code.
WP-A is still treated as non-code, for two reasons:
- The 2026-09-25 token-efficiency change was the same kind of change (skill and agent files
  only), and it set the precedent: a self-check plus an audit
  (`docs/reviews/2026-09-25-token-efficiency-rule-audit.md:3-4`).
- `/code-review`, `/simplify` and `security-reviewer` target executable code, and WP-A contains
  none.

So WP-A gets:
- **A self-check.**
- **An independent rule-preservation audit.** A fresh Opus subagent compares the old versions
  (`git -C ~/.claude show HEAD:<file>` and SEC `HEAD`) with the new ones. It reports any rule,
  qualifier, threshold, path or command that went missing or changed meaning, apart from the
  intentional changes in the roadmap's WP-A section. It also gets the verification grep's hits,
  so it can judge contradictions left in files WP-A didn't touch.

The stop rules stay as they are: a clean round ends the review, and the same issue twice goes to
the user. The record goes in `docs/reviews/2026-09-25-wp-a-review-docs-cost.md`.

## Verification

- Files: `git -C ~/.claude status --short` and the SEC `git status --short` list exactly the
  files named above, including new untracked docs. `--stat` alone would miss those.
- Sizes (`wc -c`): the docs skill is about 3KB, the review skill at most 6560 bytes, and global
  CLAUDE.md about 13288 bytes or less.
- Contradiction grep: search for `five-pass|5-pass|all five|docs/reviews/|saves the plan|decision
  file|decision-file|docs/decisions|Standard\+ change`.
  - Scope: `~/.claude/{CLAUDE.md,skills,agents}` (excluding `skills/synced`), `~/.claude/projects/
    c--riddhesh-projects-SEC-research-agent/memory/`, SEC `CLAUDE.md`, `.claude/rules/`,
    `docs/*/TEMPLATE.md`, the first 25 lines of `BACKLOG.md`, and the `PROJECT_INDEX.md` blurb.
  - Judge every hit by hand. `docs/reviews/` and `docs/decisions` stay legitimate for Substantial
    work, ADR-gated decisions and regressions. No contradiction may remain.
- Docs health, after step 8, from the SEC root, against a scratch index so the real one is
  untouched:
  - `GIT_INDEX_FILE=<scratch>/idx git read-tree HEAD`
  - `GIT_INDEX_FILE=<scratch>/idx git add PROJECT_INDEX.md BACKLOG.md docs`
  - `GIT_INDEX_FILE=<scratch>/idx .venv/Scripts/python.exe scripts/check_docs_health.py`
  - It passes only with exit 0 and empty stderr. The script fails open, so exit 0 alone proves
    nothing.
- Live check: deferred to the first real Standard task afterwards. Its commit body names the
  passes that ran. The decision file lists this under follow-ups.

## Plan review

`plan-reviewer` (Opus), 2026-09-25. It found 10 items, all folded in above:
- High: the BACKLOG header's decision-file rule (d).
- Med: other decision-file assumptions (e).
- Med: the grep missed decision-file terms and the memory dir (Verification).
- Med: `check_docs_health.py` reads only the staged tree and fails open (scratch-index run, moved
  after step 8).
- Med: which tier axis gates doc artifacts (the "Substantial" reading, step 1 wording).
- Med: the skip list and item 11's rationale belonged in the decision file (step 8).
- Low: `/compact` goes before the review (step 7).
- Low: index lines added in step 0, not batched.
- Low: the auditor gets the grep hits.
- Low: why the non-code floor applies (review section).

The full text goes to the plan-review file in step 0.
