# Review: rule-preservation audit of the token-efficiency trims

Plan: `docs/plans/2026-09-25-token-efficiency-workflow.md`. This is a markdown and config-only
change, so the review floor is a self-check plus this independent audit.

A fresh Opus subagent compared the old versions from git (the `~/.claude` snapshot commit
`3fb59aa`, and the project's `HEAD`) against the new ones:

- global `CLAUDE.md`
- `independent-review-pass/SKILL.md`
- `design-before-building/SKILL.md`
- project `CLAUDE.md`
- the three new agent files, which now hold the moved checklists.

The audit counted only rules, qualifiers, thresholds, paths and commands that went missing or
changed meaning, and ignored the listed intentional changes.

## Pass 1: rule-preservation audit (fresh subagent)

1. **High**: the project file had two conflicting compaction lists. The new `# Compact
   instructions` said to keep failed approaches, results and background tasks. The ready-to-paste
   `/compact` line said to drop dead ends. `[Fixed]`: the `/compact` line now points at Compact
   instructions, and that section keeps one line per failed approach.
2. **High**: pass 4 is now pinned to Sonnet with no Opus escalation, a behavior change that
   wasn't on the intentional list. `[Verified, no fix needed]`: it's in the approved plan's
   agent table. It's recorded as a decision in the decision file.
3. **Med**: the agent fallback's "same model" was undefined when no model was passed.
   `[Fixed]`: it now names `model: "sonnet"` (or `"opus"` when escalated) and says not to edit
   files.
4. **Low**: the H1 `# Compact instructions` swallowed `## Design principles`. `[Fixed]`: the
   section moved to the end of the file.
5. **Low**: "fix the issue" and the two explicit `--no-verify` forms were dropped. `[Fixed]`:
   both restored.
6. **Low**: the critical-core list was attributed to `## Coverage bar`. `[Fixed]`: it's the
   rule file's `paths:` frontmatter, mirrored in `githooks/pre-push`.
7. **Low**: the pragma line lost "per `live-code-tdd.md`" and "excluded from both". `[Fixed]`:
   restored.
8. **Low**: `requirements-dev.txt` was dropped. `[Fixed]`: restored.
9. **Low**: global §1 lost "not deferred for later". `[Fixed]`: restored.
10. **Low**: global §5 lost "don't drop an objection at the first pushback" and its scope list.
    `[Fixed]`: restored.
11. **Low**: the global header depended on this project's docs. `[Fixed]`: it now points at
    `~/.claude`'s own git log first.
12. **Low**: the review start condition lost "verified working". `[Fixed]`: restored.
13. **Low**: the plan contents lost "constraints". `[Fixed]`: restored.

**Pre-existing tension:** the project file said review needs no separate ruff/pyright step,
while the skill's prerequisites say to run them. `[Fixed]`: the project file now says the
manual pre-commit checks satisfy the skill's prerequisites.

**Verified intact:**
- all tier definitions and table rows;
- greenfield-strict and the baseline rule;
- the logging and error-handling qualifiers;
- the one-commit authorization;
- "upheld twice → settled";
- `ultra` and `/security-review` bans;
- the ≥80% security bar and its exclusions;
- the pass-4 re-surface exemption;
- `/simplify` edits don't count as clean, and it re-gates after them;
- live verification starts a new round;
- the 50→40 index cap;
- the 80/90 coverage bars;
- the ruff codes;
- pyright basic mode (94% noise);
- the hook behaviors.

## Outcome

12 items fixed and 1 accepted as intended. The only open follow-ups are the new-session agent
load check and the 2-WP pilot (BACKLOG).
