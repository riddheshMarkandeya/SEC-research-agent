# Workflow skills overhaul — roadmap (from mattpocock/skills + addyosmani/agent-skills review)

## Context

The user asked for a review of two public skill repos (mattpocock/skills,
addyosmani/agent-skills), a comparison against our own `~/.claude` skills/agents, and a
token-conscious adopt/adapt/skip assessment. Discussion (2026-09-25) settled the decisions below.

Measured cost driver found along the way: since ~2026-08-01 (161 commits) the SEC project wrote
99 decision + 39 plan + 53 review files (~1.19MB), and review files show 2–5 rounds each, every
round re-running 4 passes. So beyond adopting ideas, this change **revisits two prior decisions**
(§4 of global CLAUDE.md): the unconditional five-pass review floor (`independent-review-pass`)
and the 2026-09-14 documentation overhaul (`docs/decisions/2026-09-14-documentation-system-overhaul.md`).
New information: the measured volume above + the user's explicit token-economy priority.

Both source repos are MIT-licensed; content is lifted and reworded into our own form (lean,
progressive disclosure, Python/plain-function idiom), credited in each file's frontmatter
`source:` line. Cloned copies used for research live in this session's scratchpad
(`.../scratchpad/mp`, `.../scratchpad/ao`); re-clone with `git clone --depth 1` if gone.

This is multi-session work, so per the "split large plans" preference it becomes this **roadmap**
plus three ordered BACKLOG work packages, each planned in its own plan-mode session that points
at its section here (not restating it).

## User decisions (settled)

- Approved: all skill/agent updates, new user-invoked skills, the git-guardrails hook.
- Security pass: the path-list trigger was first approved, then **dropped after measuring**.
  94 of 117 code commits since 2026-08-01 touched the candidate list, so it would save about 20%
  of passes while adding a rule file, precedence rules and a re-evaluation per delta. Instead,
  `security-reviewer` runs on every Standard+ code diff **except test-only diffs**. On a re-round
  it runs on the delta only when the delta changes non-test executable code.
- Review re-rounds: **delta-only** (round 2+ reviews only the fix diff with the pass(es) that
  flagged it + `/code-review low`; full round only if the fix touches new files; nits never
  reopen a round; `/simplify` edits get tests + `/code-review low` on their delta).
- Docs: **ADR-gated decision files** (hard to reverse + surprising + real trade-off; else the
  commit message body is the record), **plan-review findings live inside the plan**, repo plans
  only for Substantial/multi-session work, **review files only for Substantial or when a finding
  is deferred/disputed**, **rewrite `documentation-backlog-hygiene` to ~3KB**.
- UI skill upgrade **now** (web components are coming to this and other projects).
- Scope tiers: **keep the names, split the axes**: design depth by uncertainty, review depth by
  the actual diff, splitting by session fit. **The retro judges it on evidence**: keep it,
  improve it, or switch to Matt-style routing by situation. Neither source repo uses central
  tiers. Matt routes by situation (open questions? multi-session?), and Addy triggers each skill
  by description with local size rules.
- Skipped (reasons recorded in the decision file): ci-cd, git-workflow/versioning, shipping,
  deprecation, context-engineering, spec-driven, planning-breakdown, incremental-impl,
  code-simplification, doc/ADR skill, addy persona agents, sdd-cache/simplify-ignore/session-start
  hooks, Matt's tracker-bound skills (triage, to-tickets, to-spec, setup), wizard, teach,
  to-questionnaire, ask-matt, domain-modeling/CONTEXT.md, handoff, writing-for-agents (principles
  applied during rewrites instead: progressive disclosure, positive phrasing, pruning).

## Step 0 (before WP-A) — clean trees

- SEC repo has untracked WP5 docs (`docs/plans/2026-09-24-wp5-segment-rule.md`,
  `docs/reviews/2026-09-24-wp5-segment-rule-plan-review.md`, `docs/reviews/2026-09-25-wp5-segment-rule.md`);
  `~/.claude` has modified `settings.json` + a memory file. Ask the user whether to commit each
  as-is first (global §3), then save this roadmap to
  `docs/plans/2026-09-25-workflow-skills-overhaul-roadmap.md`, add WP-A/B/C as ordered
  `BACKLOG.md` items tagged `**[misc, High, Substantial]**` / `**[misc, Med, Standard]**`, and a
  PROJECT_INDEX `Recent` line. Commit only if the user asks. Then stop. Each WP gets its own
  plan-mode session, which points at its section here.

## WP-A — Review and documentation cost (highest value; do first)

Files (`~/.claude` unless noted):
1. `skills/independent-review-pass/SKILL.md` (**including its `description:` line**, which still
   says "mandatory five-pass") — pass table:
   - Trivial (code): `/code-review low`.
   - Standard: `/code-review` + `arch-reviewer` + `/simplify`.
   - Substantial: all five.
   - `security-reviewer`: on every Standard+ code diff except test-only ones (Trivial:
     `/code-review low` only). A **blast-radius** path escalates `arch-reviewer` to opus
     (Standard+).
   - Re-rounds (delta-only): round 2+ reviews only the fix diff, with the pass(es) that flagged
     it, plus `/code-review low`, plus `security-reviewer` whenever the delta changes non-test
     executable code.
     - A full round runs if the fix touches files outside the round-1 diff.
     - A **nit fix** (only comment/wording, nothing executable changes) never reopens a round.
     - `/simplify` edits get tests plus the same delta rule.
   - Record: findings and dispositions of every round are kept in a `## Review log` section of
     the plan file (survives `/clear`/compaction; the stop rule's "already dispositioned" check
     reads it). On commit, a one-line summary goes in the commit body. A `docs/reviews/` file
     only for Substantial or deferred/disputed findings; deferred findings still → BACKLOG.
2. `agents/arch-reviewer.md` — add **Checklist C: Spec conformance** (caller passes the plan path;
   report missing/partial requirements, scope creep, implemented-but-wrong, quoting the plan
   line; skip with "no spec" if none). Add compact **smell baseline** (~9 Fowler smells, adapted:
   Mysterious Name, Duplicated Code, Feature Envy, Data Clumps, Primitive Obsession, Repeated
   Switches, Shotgun Surgery, Divergent Change, Speculative Generality, Middle Man; always
   judgement calls, repo standards override). Add **deletion test** + "one adapter = hypothetical
   seam". Add **guard-the-bar**: list every new suppression/weakening in the diff (`pragma: no
   cover`, `type: ignore`, `noqa`, skip markers, removed assertions, lowered thresholds, new
   empty `except`) and verify each is justified. Add API lines (contract-first, consistent
   error shape, additive change) triggered when the diff adds an endpoint/public interface.
   Doc-file checks only when doc files are in the diff.
3. `agents/plan-reviewer.md` + `skills/design-before-building/SKILL.md` — caller passes
   **artifact + contract, not conclusions** (the plan and the constraints it must satisfy; strip
   the author's justification narrative). Plan-reviewer also checks the plan names its test
   seams. Plan-review findings folded into a `## Plan review` section of the plan (replaces the
   separate `docs/reviews/` file rule). Repo copy of the plan only for Substantial or
   multi-session work. (The `/grill-me` and `/wayfinder` pointers are added in WP-B, when those
   skills exist.)
4. `agents/security-reviewer.md` — add **LLM/agent category** (OWASP LLM Top 10 subset): model
   output treated as untrusted (never into eval/shell/SQL/paths without validation), prompt
   injection via retrieved/fetched text (system prompt isn't a security boundary), secrets kept
   out of the context window, tool-argument validation.
5. `skills/documentation-backlog-hygiene/SKILL.md` — rewrite to ~3KB: ADR gate (3 criteria) for
   decision files; otherwise commit message body (why / verified / follow-ups) is the record;
   index/backlog rules kept, incident narrative cut; backlog tag legend unchanged.
6. `CLAUDE.md` (global):
   - **Scope tiers: keep the names, split the axes** (user decision). The tier section defines:
     - **Design depth by uncertainty.** One-sentence test: if the diff can be described in one
       sentence and there's one reasonable approach, the plan is short. The plan-review floor
       stays.
     - **Review depth by the actual diff, re-classified at review time**, not by the guess made
       at the start. Under ~30 changed lines and no blast-radius path → Trivial passes.
       A blast-radius path or ~300+ lines → Substantial passes. Otherwise Standard.
     - **Size by session fit.** ~300+ lines or more than one session → split, or use
       `/wayfinder` (from WP-B).
     - `independent-review-pass` item 1 uses this diff-based classification.
   - Tier-table rows for Documentation and Independent review match items 1 and 5.
   - **§6 "step 1 of every approved plan saves the plan there"** is narrowed to Substantial or
     multi-session plans.
   - §2 gains: name the 2–4 questions a log must answer; where the trigger is cheap or offline
     (not burning Gemini quota), fire the failure path once and read the actual log line; for
     LLM calls, log tokens, latency and retries.
7. (Dropped: the trust-boundary rule file. See User decisions.)
8. SEC exceptions and leftovers that would otherwise contradict the new rules:
   - Live-found regressions keep their decision file ("document failure modes"). Add one line
     to `live-eval-verification.md` and one exemption clause to the docs skill, and nothing more.
   - `docs/reviews/TEMPLATE.md`: drop the per-pass layout for a rounds/findings/disposition
     layout that matches the new pass table.
   - Memory `project_wp5_pending_replicate.md`: WP5's close-out is a regression record, so its
     decision file still exists under the exemption. Reword so this is explicit.
9. SEC `CLAUDE.md`:
   - Documentation-system section updated for the ADR gate, the commit-message record and the
     regression exemption.
   - The "before design/debugging, search `Recent`" step adds `git log --grep=<module>`, since
     Standard changes no longer produce index lines.
10. Decision file (this change meets the ADR gate) in SEC `docs/decisions/`, linking the two
    revisited decisions under `Related`; PROJECT_INDEX line.
11. No pre-push diff-guard script. The `arch-reviewer` guard-the-bar item covers new
    suppressions, and a `/retro` may promote it to a deterministic check if reviewers keep
    catching the same thing.

## WP-B — Debugging, TDD and new user-invoked skills

1. `skills/debugging-discipline/SKILL.md` → ~5KB: merge Matt's `diagnosing-bugs` method — Phase 1
   build a tight red-capable feedback loop (ordered loop-type list; completion = one command
   already run that goes red on the exact symptom; for LLM/eval flakiness raise the repro rate),
   minimise until every element is load-bearing, 3–5 ranked falsifiable hypotheses shown to the
   user before testing, tagged debug logs (`[DEBUG-xxxx]`) with grep cleanup, "no correct seam is
   itself a finding", cleanup checklist. Keep our stash-bisect, two-fail stop and plan-mode
   escalation; incident story → one sentence.
2. `skills/tdd-live-code-carveout/SKILL.md` — add anti-patterns (implementation-coupled,
   **tautological**, horizontal slicing → vertical slices/tracer bullets) and "plan names the test
   seams at the highest existing seam". ~+1KB.
3. New global skills. The invocation mode is chosen per skill, because a
   `disable-model-invocation: true` skill can't be loaded by another skill or a subagent:

   | Skill | Invocation | Called or suggested by |
   |---|---|---|
   | `grill-me` | model-invocable, narrow description ("user asks to be grilled, or a skill hands off to it") | `design-before-building` (fuzzy requirements), `wayfinder` (grilling tickets) |
   | `research` | model-invocable | `design-before-building` (prior art / unverified facts), `wayfinder` (research tickets) |
   | `wayfinder` | user-invoked | `design-before-building` + global CLAUDE.md |
   | `retro` | user-invoked | global CLAUDE.md session-start check |
   | `prototype` (WP-C) | model-invocable, and the suggesting skill offers it before building | `ui-implementation-guidelines`, `design-before-building` |

   - `grill-me`: Matt's `grilling` near-verbatim: a design tree, frontier rounds, numbered
     questions each with a recommended answer, facts found by a subagent, done when the frontier
     is empty. Plus Addy's stop test ("can I predict your answer to the next 3 questions?") and
     the want-vs-should-want line.
   - `research`: a background agent reads primary sources and writes a cited markdown file where
     the repo keeps notes (here: linked from the map or plan that asked for it).
   - `wayfinder` (~4KB), adapted to **how we already run big efforts**. Our 2026-09-24
     prompt-audit roadmap was a 40KB design written up front, followed by build WPs. Wayfinder
     adds the phase before that, for when the design isn't knowable yet. Adaptation:
     - **One file per effort**: `docs/plans/<date>-<slug>-map.md` (indexed like any plan).
       Sections:
       - `Destination`
       - `Notes` (standing rules, e.g. the prompt audit's "Decision rule" and eval-quota
         budget)
       - `Decisions so far` (one line per resolved ticket, with a ≤5-line answer and links)
       - `Open tickets`: each has a Question, a Type, `Blocked by:`, and a status of
         open / in progress
       - `Not yet specified` (fog)
       - `Out of scope`
     - **One BACKLOG line per map** points to it ("next: frontier ticket X"), not one line per
       ticket. BACKLOG stays grep-only, and the map is the single source of ticket state.
     - Dropped from Matt's version: claiming by assignee, tracker blocking links and the setup
       skill. We're one user with sequential sessions.
     - Ticket types: `research` (AFK, `research` skill, may run in parallel), `grilling`
       (`grill-me`), `prototype`, and `task`. For this project, a `task` includes spending eval
       quota to learn a fact, e.g. "run the baseline panel".
     - **One decision ticket per session** (research tickets excepted). Default is
       plan-don't-do.
     - **When the fog clears, the map turns into the build phase.** Its `Decisions so far` is the
       design, and build WPs are added as ordered BACKLOG items, each planned in its own session
       pointing at the map. This is today's roadmap+WP convention, with the map replacing the
       up-front 40KB roadmap.
     - **When to use which**: open decisions block writing the plan → wayfinder. Design is clear
       but too big for one session → skip straight to the build phase (roadmap + WPs, as today).
     - The in-flight prompt-audit roadmap is not migrated.
   - `retro`: **all of it lives globally.**
     - The skill holds the whole procedure: our measurements (main-thread vs subagent tokens,
       cache rewrites, post-compaction friction, reviewer finding counts, `/simplify` cost, drift
       and bloat in CLAUDE.md and skills) plus Matt's categories (navigation, a deterministic
       check for anything mechanical, no-op instructions, tool economy, information access).
     - Its parameter is a project: repo path plus transcript folder.
     - Records go in `~/.claude/retros/YYYY-MM-DD.md`, in the global git repo. Seed it with a
       2026-09-25 baseline file that restates that session's measured figures itself, with no
       pointer into the project.
     - Project-specific findings go to that project's BACKLOG.
     - **Standing agenda item: judge the tier scheme on evidence.** Look at tasks whose diff-based
       review tier differed from their starting tier, review passes run versus real findings, and
       tokens per tier. Decide whether to keep it, improve it, or replace it with a Matt-style
       situation router. Until then, the WP-A version stands.
     - Cadence is derived, not stored: global CLAUDE.md says "at session start, if the newest
       `~/.claude/retros/` file is 14+ days old, suggest `/retro`". No due date has to be
       rewritten anywhere.
     - This removes the project BACKLOG "Recurring: workflow retro" item and the
       `project_workflow_retro_due.md` memory, and brings forward that item's own "bundle as a
       global skill on the second run" plan. The Pilot BACKLOG item stays; the first `/retro`
       run closes it out.
4. Global CLAUDE.md gains a compact **"On-demand skills: suggest when…"** list (the five rows
   above, one line each). That way every user-invoked or suggested skill has a pointer from
   something that always loads.
5. Memory: update `feedback_split_large_plans.md` to name `/wayfinder` and its build phase.
   Delete `project_workflow_retro_due.md` and its MEMORY.md line.
6. `skills/design-before-building/SKILL.md`: offer `grill-me` when requirements are fuzzy,
   `research` when a decision waits on external facts, and `/wayfinder` when open decisions or
   size exceed one session.

## WP-C — UI skill and git guardrails

1. `skills/ui-implementation-guidelines/SKILL.md` → ~4KB core: add reference-led design contract
   (screen's job, primary action, required states, responsive rules, rejected patterns), the
   "avoid the AI aesthetic" table, real-browser verification paragraph (built-in `/run`; choose
   Chrome DevTools MCP vs Playwright MCP at first UI task). On-demand references:
   `references/accessibility.md` (WCAG 2.1 AA, from Addy's checklist) and
   `references/web-performance.md` (CWV targets + measure/fix/keep-or-revert, ~2KB).
2. New `prototype` skill (user-invoked): LOGIC branch (single HTML state-machine walkthrough) and
   UI branch (several radically different variants switchable by URL param), throwaway rules.
3. Git guardrails: new `~/.claude/hooks/block-dangerous-git.js`.
   - Written in **node** (v24.14.1 installed), not Matt's bash + jq, which isn't guaranteed on
     this Windows box.
   - PreToolUse hook in the global `settings.json`, matcher **`Bash|PowerShell`**. Matt's `Bash`
     matcher would miss PowerShell git calls.
   - Parsing: split the command on `&&`, `||`, `;`, `|` and newlines. Match only segments whose
     command is `git` (allowing `git -C <path>`). This avoids false positives on
     `python recalc.py --force`, `pip --force-reinstall`, and commit messages that mention
     `reset --hard`.
   - Blocks `git push` (any form), `git reset --hard`, `git clean -f*`, `git branch -D`,
     `git checkout .`, `git restore .`.
   - **Verify first**: log one real PowerShell-tool payload to confirm the field is
     `tool_input.command`, and check whether a `!`-prefixed user command bypasses PreToolUse.
     If it doesn't, the user pushes from their own terminal.
   - Unit-style cases, piped as JSON:
     - exit 2: `git push origin master`, `git -C x push`, `cd a && git reset --hard`
     - exit 0: `git status`, `python recalc.py --force`,
       `git commit -m "avoid reset --hard"`
   - Update SEC CLAUDE.md "Hooks" section (currently "No Claude Code hooks are used").
   - WP-C doesn't depend on WP-A or WP-B, so it can land any time.

## Verification

- Each WP: `git -C ~/.claude diff --stat` matches the listed files; each rewritten skill's size
  checked (`wc -c`) against its target.
- WP-A:
  - Grep `~/.claude` and the SEC `CLAUDE.md`/`.claude/rules/`/`docs/*/TEMPLATE.md` for
    `five-pass`, `5-pass`, `all five`, `docs/reviews/` and "saves the plan". No contradiction may
    remain.
  - `check_docs_health.py` still passes.
  - The first real Standard task afterwards is the live check that the tiered review runs as
    written. Note the passes run in its commit body.
- WP-C: run the hook cases listed in WP-C item 3, then make one real blocked call in-session.
- Review per WP under the **new** `independent-review-pass` rules once WP-A lands (WP-A itself is
  reviewed under the current rules, since the new ones aren't in force yet).

## Plan review

`plan-reviewer` (opus), 2026-09-25. It was given the plan and its contract, not the author's
reasoning. All findings are folded in:
1. High: leftover contradictions (global §6 plan-saving, the live-eval regression decision rule,
   the review TEMPLATE, the WP5 memory, the independent-review-pass `description:`). Now in WP-A
   items 1, 6 and 8, with a regression exemption from the ADR gate.
2. High: delta re-rounds skipped the security trigger, and "nit" and "new files" were undefined.
   The trigger is now re-evaluated on every delta. A nit means comment/wording only with no
   executable change. "New files" means files outside the round-1 diff.
3. Med: the path list had blind spots. The trigger now also fires on new source files and
   dependency manifests, the list is extended, and tier/modifier precedence is stated.
4. Med: review records had no home before a commit. They go in the plan's `## Review log`
   section.
5. Med: `check_diff_guards.py` would misfire and wasn't worth its cost. Dropped and replaced by a
   BACKLOG item (WP-A item 11).
6. Med: WP-A pointed at skills that don't exist yet. The pointers moved to WP-B item 5.
7. Med: the hook's naive matching, plus unverified PowerShell-payload and `!`-bypass
   assumptions. It now parses segments, has a test case list, and has a verify-first step.
8. Low: session start no longer sees Standard changes. Now `git log --grep` in SEC `CLAUDE.md`.
9. Low: the §2 "fire the failure path" line clashed with the Gemini quota. Now caveated.

Revisions after the user's plan comments (2026-09-25):
- The security path trigger was dropped on measured evidence, which also makes finding 3 moot.
- The regression exemption was cut to one line per file.
- The diff-guard BACKLOG item was dropped.
- `wayfinder` was redesigned around our roadmap+WP flow.
- `retro` is now fully global.
- Invocation modes are chosen per skill, and each on-demand skill gets a suggestion pointer from
  an always-loaded file.
- The status line works: the script runs and its fields are documented. Custom status lines only
  render in the CLI terminal, not the VS Code extension panel, so nothing needs fixing.
