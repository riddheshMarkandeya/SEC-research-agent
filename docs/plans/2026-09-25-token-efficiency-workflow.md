# Token-efficiency workflow: model-routed reviewers, terse contracts, trimmed instructions, earlier compaction

## Context

Claude usage is heavier than it needs to be. This change edits the **global** workflow files
(`~/.claude/CLAUDE.md`, `~/.claude/skills/…`, `~/.claude/agents/…`, `~/.claude/settings.json`)
as well as this project's `CLAUDE.md`. The drivers:

- **Main-thread context dominates cost.** A baseline over this project's 23 session transcripts
  (8,870 main-thread calls, 476 subagents) found:
  - about 86% of cost-weighted tokens are main-thread input (cache reads weighted at a tenth);
  - the median call carries 351k tokens of context, p90 727k;
  - 80% of main-thread input was sent above 300k.

  Opus 5.5's native 1M window only auto-compacts at about 967k.
- **Subagents.** Many inherit Opus: only 62% of past subagents ran on Sonnet. One review round
  is `/code-review`, the passes-2/3 subagent, the security subagent and `/simplify`'s 3
  subagents. The loop needs **two** clean rounds to stop, so even a perfect change pays for two
  rounds. Subagent replies are free-form prose and land verbatim in the main context.
- **Always-loaded instructions.** The global `CLAUDE.md` (16KB) and project `CLAUDE.md` (12KB)
  load into every session and every general-purpose subagent. `independent-review-pass/SKILL.md`
  (17KB) loads for every review and sits near the 5k-token cap for re-injecting a skill after
  compaction. `BACKLOG.md` (46KB) gets read whole. Much of this bulk is incident narrative, not rules.

## Prior art

We read the actual rule files, not just the READMEs.

- **caveman** (github.com/JuliusBrussee/caveman).
  - Its measured win is *cavecrew*: cheap-model subagents that return a compressed,
    `path:line`-first result, which matters because subagent results enter the main context verbatim.
  - The chat-reply compression measured only about 8.5% fewer output tokens (JetBrains lab, 86 tasks).
  - The `caveman-compress` rewrite of memory files risks dropping qualifiers.
  - Its "auto-clarity" rule is worth copying: write plain prose for security findings,
    irreversible actions and anything ambiguous.
- **ponytail** (github.com/DietrichGebert/ponytail).
  - A 7-rung ladder: YAGNI → reuse → stdlib → native → installed dependency → one line →
    minimum code.
  - "Lazy about the solution, never about reading", with an explicit list of things never to
    skimp on (validation, data-loss handling, security).
  - It claims 54% fewer lines and 22% fewer tokens. Its `delete:`/`stdlib:`/`yagni:`/`shrink:`
    review tags overlap `/simplify`.
- **Claude Code docs** (code.claude.com/docs/en/model-config, context-window, prompt-caching):
  - the `autoCompactWindow` setting and the per-launch `--autocompact` flag;
  - what survives compaction: CLAUDE.md, memory, the plan file and git status are reloaded from
    disk; 5 recent files are re-read; skills are re-injected, capped at 5k tokens each;
    path-scoped rules are summarized away;
  - "performance degrades as context fills."

## Decision / Design

User decisions (2026-09-25):
- no caveman style in chat replies;
- trim the instruction files by hand in plain English;
- fold ponytail in selectively;
- the review loop ends after **one** clean round. This revisits `independent-review-pass`'s
  two-clean-rounds rule; the new information is the measured cost per round;
- auto-compact at **300k**, with mitigations. This was added mid-implementation after the baseline.

1. **Local git for `~/.claude`.** An allowlist `.gitignore` tracks only `CLAUDE.md`,
   `settings.json`, `keybindings.json`, `agents/`, the hand-written `skills/` (not `skills/synced/`)
   and `projects/*/memory/`. Credentials, transcripts and caches are never tracked, and the repo has
   no remote. The snapshot commit is the rollback point and the base for the rule-preservation audit.
2. **Three reviewer agents in `~/.claude/agents/`.** Each checklist moves into its agent file, so
   it has one home.

   | Agent | Model | Covers |
   |---|---|---|
   | `plan-reviewer` | opus | plan review: open-ended judgment |
   | `arch-reviewer` | sonnet, but the caller passes `model: opus` for Substantial tier or when a changed path is on a project's blast-radius list (the caller checks the diff paths directly) | review passes 2+3 |
   | `security-reviewer` | sonnet | pass 4: a checklist with a ≥80% confidence bar |

   - Reviewers return one line per finding and end with a `checked:` line. Security findings and
     design disagreements get a short paragraph instead.
   - Each skill has a fallback: spawn `general-purpose` and tell it to read the agent file.
3. **Skill edits.**
   - `independent-review-pass`: spawns the new agents. The stop rule is split in two: one clean
     round ends the review; the same issue twice goes to the user. Cut to ≤8KB.
   - `design-before-building`: spawns `plan-reviewer`. Cut to ≤3.5KB.
4. **Global `CLAUDE.md`.** Trim to ≤9KB without losing any rule. Add the compact ponytail ladder,
   with an explicit exemption for logging, error handling and the tests TDD requires. Add a
   "Token economy" section (model routing, subagent contract, no narration, output to file then
   grep, grep big docs, compact at natural breaks).
5. **Auto-compaction.**
   - `autoCompactWindow: 300000`. Simulated on the past sessions: about 56% less main-thread input
     for about 2 extra compactions per session. 200k: −68% for about 4.5. 400k: −46%.
   - A project `# Compact instructions` section says what summaries must keep.
   - Launch with `claude --autocompact 600k` for a deep debugging session.
6. **Project `CLAUDE.md`.** Trim to ≤8KB. Add "grep `BACKLOG.md`, don't read it whole".
7. **Experiment: `CLAUDE_CODE_SUBAGENT_MODEL=sonnet`.** Keep it only if it reaches `/simplify`'s
   built-in subagents.

**Dropped after plan review:**
- the `locator` agent, which duplicates built-in Explore (which can be spawned on haiku per call);
- the `log-summarizer` agent, which could mangle exact eval figures;
- ponytail line-level tags in `arch-reviewer`, which duplicate `/simplify`.

## Scope / Out of scope

- No Python code changes.
- Other skills are untouched.
- `PROJECT_INDEX.md`'s `Recent` cap is unchanged and filed to BACKLOG.
- The three untracked WP5 docs files belong to the in-progress WP5 and are left alone.

## Files and steps

0. Initialize the `~/.claude` git repo and take the snapshot commit. Compute the baseline with
   scratchpad scripts over the transcripts. Save this plan and the plan review.
1. Write `~/.claude/agents/{plan-reviewer,arch-reviewer,security-reviewer}.md`.
2. Edit `~/.claude/skills/independent-review-pass/SKILL.md` and
   `~/.claude/skills/design-before-building/SKILL.md`.
3. Trim `~/.claude/CLAUDE.md` and add to it; set `autoCompactWindow` in `~/.claude/settings.json`.
4. Trim the project `CLAUDE.md` and add Compact instructions.
5. Run the `CLAUDE_CODE_SUBAGENT_MODEL` experiment.
6. Write the decision file, the rule-audit review, `PROJECT_INDEX.md` entries and `BACKLOG.md` items.
   Commit in both repos.

## Testing and verification

1. Before/after `wc -c` of the four trimmed files.
2. **Rule-preservation audit.** A fresh Opus subagent compares each old version (from git) with its
   new version and lists any rule, qualifier, threshold or path that was lost or changed meaning.
   Each item is fixed or explicitly accepted.
3. In a new session, the agents load and the output contract holds. Check the model in the
   transcript and try the fallback path once.
4. The commit passes `githooks/pre-commit`.
5. **Pilot.** The next 2 WPs compare token usage and review-finding counts against the baseline.

The review floor: this is a markdown and config-only change, so a self-check plus the audit in
step 2 is enough.
