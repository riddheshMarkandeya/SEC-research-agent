# Review: token-efficiency workflow plan (plan review)

Plan: `docs/plans/2026-09-25-token-efficiency-workflow.md`. An independent plan review by a fresh
general-purpose subagent (Opus) with no memory of the planning session. Scope: plan only, no code.

## Pass 1: independent plan review (fresh subagent)

1. **Med**: savings rank differently than assumed. The one-clean-round loop is largest, then
   Sonnet reviewers, then smaller CLAUDE.md files, then terse output, then the skill trim. No
   baseline existed. `[Fixed]`: a baseline step was added. It later showed main-thread context
   outweighs every subagent lever, which led to the auto-compact step.
2. **High**: the one-clean-round edit must split the stop rule. Today "two clean rounds" and "same
   issue twice" share one sentence, and the frontmatter and line 236 say "two-round cap".
   `[Fixed]`: the plan splits the two rules and updates both references.
3. **High**: `plan-reviewer` on Sonnet is the riskiest downgrade. Plan review is open-ended
   judgment. The blast-radius rule file only loads when a matching path is touched, which may not
   happen in plan mode. `[Fixed]`: `plan-reviewer` defaults to Opus.
4. **Med**: `arch-reviewer` does judgment work too. `[Fixed]`: it stays on Sonnet but escalates to
   Opus for Substantial tier or a blast-radius path. The caller checks the diff paths directly,
   without relying on rule auto-load. A Sonnet trial at Substantial tier is filed to BACKLOG.
5. **Med**: the terse contract doesn't fit plan review, and `No issues.` carries no evidence.
   `[Fixed]`: every reviewer ends with a `checked:` line, and `plan-reviewer` is exempt from the
   one-line format.
6. **Med**: the plan's "TDD one-check minimum" misstates `tdd-live-code-carveout`, and the ponytail
   tags duplicate `/simplify`. `[Fixed]`: the wording now names the tests that skill requires, and
   `arch-reviewer` keeps only design-level YAGNI.
7. **Med**: once the checklists move into agent files, there's no fallback if the agent type isn't
   loaded. `[Fixed]`: each skill gets a fallback line (spawn general-purpose and have it read the
   agent file).
8. **Low**: the mechanics were checked.
   - Confirmed: frontmatter `model` and the per-call override, which takes precedence.
   - Confirmed for general-purpose: subagents load CLAUDE.md.
   - Unverified: whether agents load mid-session.
   - `tools: Bash` can't be scoped to git commands.

   `[Verified, no fix needed]`: the "new session" check is kept, and read-only is stated as a
   convention.
9. **Low**: the `locator` and `log-summarizer` agents are YAGNI. `[Fixed]`: both dropped.
10. **Low**: `CLAUDE_CODE_SUBAGENT_MODEL` might cover the built-in spawns. `[Fixed]`: it's now an
    experiment in this change, not a BACKLOG item.
11. **Low**: the decision file lives in one project but covers global files. `[Fixed]`: the
    decision file says so explicitly.

## Outcome

All 11 findings were folded into the plan before approval. The reviewer's verdict: sound
direction once items 2, 3 and 5 were fixed, which they are.
