# Review: WP-A plan (review and documentation cost)

Plan: `docs/plans/2026-09-25-wp-a-review-docs-cost.md`. WP-A of the workflow-skills overhaul
roadmap. `plan-reviewer` (Opus), 2026-09-25. It was given the plan and its contract: the roadmap's
WP-A items within the settled User decisions, and review under the *current*
`independent-review-pass` rules. It was not given the author's reasoning. All 10 findings were
folded in before approval.

## Findings

1. **High**: the `BACKLOG.md` header (lines 3-8 and 13-22) says three things that contradict the
   ADR gate: finished work "lives in `docs/decisions/`", an item must never vanish "with no
   decision-file trace", and every Recurring run writes a decision file. Neither the plan nor the
   roadmap's grep terms caught this. `[Fixed]`: plan item d rewords it to "the decision file if
   gated, else the commit body".
2. **Med**: other passages also assume every change has a decision file:
   - global `CLAUDE.md:115` (§4 stand-by one-liner);
   - `live-eval-verification.md:112-115`, which cross-links to the regression-introducing change;
   - memory `feedback_split_large_plans.md:15`;
   - SEC `CLAUDE.md:4-6`, which points only at `Recent`.

   `[Fixed]`: plan item e.
3. **Med**: the verification grep had no decision-file terms, and it narrowed `~/.claude` so that
   the git-tracked memory directory WP-A edits was left out. `[Fixed]`: the terms were added, and
   the scope now covers the memory directory, the BACKLOG header and the PROJECT_INDEX blurb.
4. **Med**: `check_docs_health.py` would have tested nothing, for four reasons:
   - it reads only the staged tree;
   - it fails open with exit 0 on a git error, a wrong cwd, or an unstaged PROJECT_INDEX;
   - it was planned before step 8 creates the docs;
   - bare `python` may be the Windows Store stub.

   `[Fixed]`: the check now runs after step 8 against a scratch `GIT_INDEX_FILE`, uses the venv
   Python, and requires empty stderr. The plan also uses `git status --short` rather than
   `--stat`, which misses untracked docs.
5. **Med**: once tiers split by axis, "Substantial" is ambiguous for doc artifacts. A blast-radius
   path makes a diff Substantial for review. However, `plan-review-blast-radius.md:21-24` says
   that path brings no documentation escalation. Separately, with security running on every
   Standard+ diff, the Standard and Substantial pass lists look almost identical. `[Fixed]`: doc
   artifacts follow the task's design tier. The step 1 wording will name what actually differs:
   the `/code-review` level and `arch-reviewer` on Opus. This is a wording clarification, not a
   reopened decision.
6. **Med**: the roadmap puts the skip list and its reasons in WP-A's decision file, and item 11's
   rationale (no diff-guard script) was planned nowhere. `[Fixed]`: step 8 adds both.
7. **Low**: global §6 gives the `/compact` line *before* the review, but step 7 had them the
   other way round. `[Fixed]`.
8. **Low**: the current docs skill says index lines are added in the same step and never batched.
   `[Fixed]`: step 0 now adds the plan and plan-review lines.
9. **Low**: the rule-preservation audit compares only changed files, so it can't see
   contradictions left in untouched files. `[Fixed]`: the auditor also gets the grep hits.
10. **Low**: the current skill counts "behavior-affecting config" as code, and skill/agent
    frontmatter could fit that. `[Fixed]`: the review section now explains why the non-code floor
    still applies, citing the 2026-09-25 token-efficiency precedent.

## Checked and found fine

- The "How WP-A itself is reviewed" reading of the current skill.
- The `Recent` count: 44, plus 4, is 48.
- The stale "untracked" WP5 phrase.
- `design-before-building:30` and `CLAUDE.md:169`.
- The file sizes.
- The step order for items 1–6 and 8–9.

## Outcome

All 10 findings were folded in. The user approved the plan.
