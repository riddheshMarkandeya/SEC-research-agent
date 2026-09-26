# SEC Filing Research Agent — Project Index

> This file is an index, not a changelog. The `## Recent` section below
> is capped at 50 entries (trimmed back to 40 whenever it's exceeded) so
> reading it in full at the start of every session stays cheap
> permanently, regardless of how much project history accumulates — not
> just because it happens to be short today. Older entries live in
> `PROJECT_INDEX_ARCHIVE.md`: search it with a text search when a task
> might touch history older than what's in `Recent`, never read it in
> full. No reasoning, history, or narrative lives here directly; every
> decision, plan, and review file is its own dated file under
> `docs/decisions/`, `docs/plans/`, or `docs/reviews/`, and changes
> without one are recorded in their commit message body. See project
> `CLAUDE.md` for the documentation system this file is part of.

## Project Overview

**Goal**: a learning project to get hands-on with the current production
AI stack — RAG, agentic workflows, MCP, evals, observability — in a real
domain rather than a toy demo. Domain: SEC EDGAR filings (10-K/10-Q).
Hard constraint: free/near-zero cost (local models, local vector DB,
self-hosted observability). End state: an agent that answers financial
questions about a set of companies, grounded in their filings, with
exact citations for every numeric claim, a regression eval suite that
gates changes, tools exposed via an MCP server, and full tracing.

**Stack** (all free): SEC EDGAR APIs (`data.sec.gov`,
`www.sec.gov/Archives`) for data; `requests`+`beautifulsoup4`+`lxml` for
parsing; `sentence-transformers` (local) for embeddings; Chroma as the
vector store; Ollama (local) or Gemini free tier as the LLM; a
hand-rolled tool-calling loop as the agent; the official Python MCP SDK;
Langfuse (self-hosted or cloud free tier) for observability.

**Companies in scope**: 5 tech companies (chosen so the user can
sanity-check answers) — AAPL, MSFT, NVDA, CRM, PLTR — see
`companies.json` for the ticker/name/CIK source of truth (this file is
not a duplicate of it). Last 5 10-K/10-Q filings each. To add a company:
add a row to `companies.json`, then run `edgar_ingest.py` →
`chunk_documents.py` → `index_chunks.py` for it.

`## Recent` below holds one line per file in `docs/decisions/`,
`docs/plans/`, and `docs/reviews/`, reverse-chronological, newest
directly under the heading. `TEMPLATE.md` in each directory
is excluded. Copy the relevant `TEMPLATE.md` when starting a new file in
any of the three directories. **Capped at 50 entries**: when adding one
pushes it past 50, cut the oldest entries back down to 40 and
prepend them (verbatim, still reverse-chronological) to the top of
`PROJECT_INDEX_ARCHIVE.md`.

## Recent

- 2026-09-26 [review] WP6 code review — 2 rounds (Substantial by blast radius); `_never_tagged_hint` typed `object`, `_no_fact_period` docstring says it mirrors the lookup; rejected-call "no data" wording deferred to WP7 (d) → `docs/reviews/2026-09-26-wp6-no-data-message.md`
- 2026-09-26 [decision] WP6: no-data reply names the period used + "finds no data" wording accepted; screen 31/39 → 35/39, no REGRESSED, `pltr-government-contract-risk` watch (date claimed as a number, unrelated); gains not credited to WP6; agent `e073094f18b9` is WP7's B → `docs/decisions/2026-09-26-wp6-no-data-message.md`
- 2026-09-26 [decision] WP5: plain segment-rule wording accepted; screen 31/39 vs 33/39 REGRESSED on `nvda-revenue-two-quarter-comparison` (1/3, gate FP on inline "a ÷ b − 1"), replicate 3/3 = noise; segment override never fired (0 fact calls either way, answers `6f3a8ee`: no effect on Gemini); agent `d2131f5d5aae` → `5d3cea51c73b`; WP6 baseline = WP5 screen → `docs/decisions/2026-09-26-wp5-segment-rule.md`
- 2026-09-25 [review] WP-A rule-preservation audit — 2 rounds: prompt-audit WP5–WP8 exempted from ADR-gated docs (baselines), Trivial review row defers to diff re-classification, 3 dropped docs rules restored; small-diff security skip raised with user → `docs/reviews/2026-09-25-wp-a-review-docs-cost.md`
- 2026-09-25 [decision] WP-A: review depth by the actual diff, delta-only re-rounds, ADR-gated decision files (commit body is the default record), plan review inside the plan; revisits the five-pass floor and 2026-09-14 docs overhaul; skip list with reasons → `docs/decisions/2026-09-25-wp-a-review-docs-cost.md`
- 2026-09-25 [review] WP-A plan review — 10 findings folded in: BACKLOG header and other decision-file assumptions, wider contradiction grep, docs-health check against a scratch index, doc artifacts follow the design tier → `docs/reviews/2026-09-25-wp-a-review-docs-cost-plan-review.md`
- 2026-09-25 [plan] WP-A (review and documentation cost): current-state check, step order, WP-A reviewed under the current rules (self-check + rule-preservation audit) → `docs/plans/2026-09-25-wp-a-review-docs-cost.md`
- 2026-09-25 [plan] Workflow-skills overhaul roadmap: review of mattpocock/skills + addyosmani/agent-skills; tiered diff-based review, ADR-gated docs, tiers split by axis, new grill-me/research/wayfinder/retro/prototype, git guardrails; WP-A/B/C → `docs/plans/2026-09-25-workflow-skills-overhaul-roadmap.md`
- 2026-09-25 [review] WP5 code review (commit d45156f) — 1 round, clean, no fix commits; two findings not adopted → `docs/reviews/2026-09-25-wp5-segment-rule.md`
- 2026-09-25 [decision] Read/diff/cache habits in global §6, reviewer agents get diff commands not pasted diffs, effort default medium, new status line (context tokens + cache expiry), BACKLOG: eval summary mode, agent.py/test_agent.py split, Recurring workflow retro due 2026-10-09 → `docs/decisions/2026-09-25-read-diff-cache-habits.md`
- 2026-09-25 [review] Read/diff/cache habits — plan review 8 findings; statusline.js 2 rounds (1.0M rounding bug fixed test-first), closed clean; `/simplify` ~210k tokens/round on a 60-line script flagged for retro → `docs/reviews/2026-09-25-read-diff-cache-habits.md`
- 2026-09-25 [plan] Read/grep/cache audit of 23 sessions (Read 59% of tool output, agent.py read 847×, idle-cache rebuilds ~11%) → habits, status line, retro → `docs/plans/2026-09-25-read-diff-cache-habits.md`
- 2026-09-25 [decision] Context-management trial promoted to global CLAUDE.md §6 + global `# Compact instructions` (verified honored from user-level file via a PINEAPPLE compaction test); `showClearContextOnPlanAccept` moved to user settings; midpoint `/compact` offer for 4+-step plans → `docs/decisions/2026-09-25-promote-context-management.md`
- 2026-09-25 [review] Promote-context-management plan review (first `plan-reviewer` agent run) — 7 findings: observable earlier-break trigger, verify user-level Compact instructions, project-neutral list → `docs/reviews/2026-09-25-promote-context-management-plan-review.md`
- 2026-09-25 [plan] Promote the context-management trial (7 boundary compactions over 6 tasks, no friction) to the global workflow → `docs/plans/2026-09-25-promote-context-management.md`
- 2026-09-25 [decision] Token efficiency (global workflow): auto-compact at 300k (main-thread context was ~86% of cost, median 351k), reviewer agents with model routing, review loop ends after one clean round, instruction files −45%; `~/.claude` now a local git repo → `docs/decisions/2026-09-25-token-efficiency-workflow.md`
- 2026-09-25 [review] Token-efficiency rule-preservation audit — 13 items, 12 fixed, security reviewer on Sonnet accepted → `docs/reviews/2026-09-25-token-efficiency-rule-audit.md`
- 2026-09-25 [review] Token-efficiency plan review — 11 findings folded in: plan-reviewer stays Opus, split stop rule, `checked:` line, locator/log-summarizer dropped → `docs/reviews/2026-09-25-token-efficiency-plan-review.md`
- 2026-09-25 [plan] Token efficiency: caveman/ponytail prior art, model-routed reviewer agents, trimmed CLAUDE.md/skills, 300k auto-compact, subagent-model experiment → `docs/plans/2026-09-25-token-efficiency-workflow.md`
- 2026-09-25 [review] WP6 plan review — 1 round; Q4 hint kept with an ignored period, `fiscal_period` read as the lookup reads it, multi-year snapshot scenario, `nvda-revenue-two-quarter-comparison` named in the trace check, 3 notes filed for WP7 → `docs/reviews/2026-09-25-wp6-no-data-message-plan-review.md`
- 2026-09-25 [plan] WP6: no-data message renders the period the lookup actually used (finding 11), "finds no data" wording on both surfaces (finding 12); waits for WP5's replicate, with each WP5 outcome's effect on WP6 → `docs/plans/2026-09-25-wp6-no-data-message.md`
- 2026-09-25 [decision] WP4: rule 3 rewritten as the real number contract (derived numbers no tool reports come from `calculate`), rule 9's "despite rule 3" dropped (audit finding 3); screen accepted, 33/39 vs 37/39, 4 watch flags, Q4 override replicated as noise; agent `4f36a2b026cf` → `d2131f5d5aae` → `docs/decisions/2026-09-25-wp4-rule3-rule9.md`
- 2026-09-24 [review] WP5 plan review — 1 round; history re-counted by backend (120 Gemini runs, 2 fact calls), implementation held until WP4 closes → `docs/reviews/2026-09-24-wp5-segment-rule-plan-review.md`
- 2026-09-24 [plan] WP5: plain wording for the segment-rule emphasis (finding 4), one model-facing commit screened under the Decision rule (roadmap Step 5) → `docs/plans/2026-09-24-wp5-segment-rule.md`
- 2026-09-24 [review] WP4 code review — 4 rounds, docstring-only fixes (narrated incident, dangling "second", example placement); rule 9 qualifier and triplicated calculate guidance kept → `docs/reviews/2026-09-24-wp4-rule3-rule9.md`
- 2026-09-24 [review] WP4 plan review — 1 round; Q4-refusal override, ratio tension resolved by the "no tool reports directly" qualifier, explicit-mode attribute, trace record shape → `docs/reviews/2026-09-24-wp4-rule3-rule9-plan-review.md`
- 2026-09-24 [plan] WP4: rule 3 / rule 9 contradiction, one model-facing commit plus a docstring commit screened under the Decision rule (roadmap Step 4) → `docs/plans/2026-09-24-wp4-rule3-rule9.md`
- 2026-09-24 [decision] WP3: Group A wording (audit findings 1, 2, 5, 6) — MCP-only `search_filings` schema, fuller agent search description, calculate/compare phrase fixes; screen accepted, 37/39 vs 37/39, agent `cc984387c3e8` → `4f36a2b026cf`; searches up 47 → 62 → `docs/decisions/2026-09-24-wp3-group-a-wording.md`
- 2026-09-24 [review] WP3 code review — 2 rounds; MCP description parity ("or finds no data for"), stale docstring pointer, whole-schema parity test; derivation direction and duplicated sentences filed → `docs/reviews/2026-09-24-wp3-group-a-wording.md`
- 2026-09-24 [review] WP3 plan review — 1 round; no tests pinning fingerprints that 3c changes, "finds no data for" wording, 3b also moves `mcp`, validate against the listed schema, measured request estimate → `docs/reviews/2026-09-24-wp3-group-a-wording-plan-review.md`
- 2026-09-24 [plan] WP3: Group A wording fixes, MCP search schema plus 3 agent-text commits screened under the Decision rule (roadmap Step 3) → `docs/plans/2026-09-24-wp3-group-a-wording.md`
- 2026-09-24 [decision] WP2: committed model-input snapshot folded into per-consumer prompt fingerprints (agent/judge/mcp), eval-report provenance, `compare_prompt_versions.py`, judge nonstandard-output flag, Gemini pinned to `gemini-3.5-flash-lite`; panel baseline 37/39 at agent `cc984387c3e8` → `docs/decisions/2026-09-24-wp2-prompt-provenance.md`
- 2026-09-24 [review] WP2 code review — 5 rounds; float ceil in REGRESSED-TOTAL, self-comparison and backwards defaults, silent exclusions, un-added files not counted dirty, snapshot-check timeout and warning/exclusion drift fixed; judge parse left unchanged (evidence-gated) → `docs/reviews/2026-09-24-wp2-prompt-provenance.md`
- 2026-09-24 [review] WP2 plan review — 2 rounds; totals over shared questions, within-1-pass, re-baseline grouping, lenient-parse cases; snapshot: pure render, no repr, hash-seed check, own declarations → `docs/reviews/2026-09-24-wp2-prompt-provenance-plan-review.md`
- 2026-09-24 [plan] WP2: prompt fingerprint, eval provenance, compare script, judge flag, model pin and 13-question panel baseline (roadmap Step 1 commit 1d, Step 2) → `docs/plans/2026-09-24-wp2-prompt-provenance.md`
- 2026-09-24 [review] WP1 prompts-package code review — 3 rounds; no model-facing byte changed (hashes + 44-entry golden identical each round); doc pointers, stale docstrings, duplicated metric list and raw-unit rule fixed, pre-push glob widened to `prompts/**/*.py`; raw-unit calculate text and enum duplication filed → `docs/reviews/2026-09-24-wp1-prompts-package.md`
- 2026-09-24 [decision] All model-facing text moved into `prompts/` (agent_system, agent_tools, agent_messages, judge, mcp), byte-identical; pre-push keeps its own critical-core list; live-eval exemption for a provably pure move → `docs/decisions/2026-09-24-wp1-prompts-package.md`
- 2026-09-24 [review] WP1 plan review — no blockers; golden capture moved to the backend boundary, formatters kept in agent.py (tests monkeypatch them), judge-location wording moved to 1c → `docs/reviews/2026-09-24-wp1-prompts-package-plan-review.md`
- 2026-09-24 [plan] WP1: move model-facing text into a `prompts/` package (roadmap Step 1, commits 1a–1c), proven by hashes and a golden capture → `docs/plans/2026-09-24-wp1-prompts-package.md`
- 2026-09-24 [review] Prompt-audit roadmap plan review — 3 rounds; biased revert rule, contradicting rule-3 rewrite, false MCP descriptions, fragile fingerprint rule and a mis-targeted Step 7 (138 fiscal_year-string rejections, not extra arguments) all fixed before approval → `docs/reviews/2026-09-24-prompt-audit-roadmap-plan-review.md`
