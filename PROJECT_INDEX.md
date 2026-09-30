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
vector store; Gemini free tier as the LLM; a
hand-rolled tool-calling loop as the agent; the official Python MCP SDK;
Langfuse (self-hosted or cloud free tier) for observability.

**Companies in scope**: 5 tech companies (chosen so the user can
sanity-check answers) — AAPL, MSFT, NVDA, CRM, PLTR — see
`src/sec_agent/sources/companies.json` for the ticker/name/CIK source of
truth (this file is not a duplicate of it). Last 5 10-K/10-Q filings
each. To add a company: add a row to `companies.json`, then run
`python -m sec_agent.sources.edgar_ingest` →
`python -m sec_agent.retrieval.chunk_documents` →
`python -m sec_agent.retrieval.index_chunks` for it.

**Layout and setup**: code lives in the `src/sec_agent/` package
(`agent/`, `verification/`, `sources/`, `retrieval/`, `llm/`,
`prompts/`, `eval/`, `tools/` for the analysis CLIs and the gate replay
tool, plus `config`, `tracing`, `mcp_server`); tests mirror the package
under `tests/`. `pip install -r requirements.txt` includes the required
editable install (`-e .`), and CLIs run as `python -m
sec_agent.<pkg>.<module>`. Generated data
(`data/`, `chunks/`, `chroma_db/`, `xbrl_cache/`, `trace_logs/`) lives
in the gitignored `var/`, anchored to the project root; committed eval
questions and results stay in `eval/`.

`## Recent` below holds one line per file in `docs/decisions/`,
`docs/plans/`, and `docs/reviews/`, reverse-chronological, newest
directly under the heading. `TEMPLATE.md` in each directory
is excluded. Copy the relevant `TEMPLATE.md` when starting a new file in
any of the three directories. **Capped at 50 entries**: when adding one
pushes it past 50, cut the oldest entries back down to 40 and
prepend them (verbatim, still reverse-chronological) to the top of
`PROJECT_INDEX_ARCHIVE.md`.

## Recent

- 2026-09-29 [review] `src/` layout move: 3 rounds (Substantial; code-review high, arch opus, security, simplify), 16 findings, 10 fixed; headline fixes: `var/xbrl_cache` mkdir crashed on a fresh clone, eval paths are defined once in `config`, provenance pathspecs are derived from path constants (resolved), and the config test checks the real defaults; `tools` package rename deferred → `docs/reviews/2026-09-29-src-layout-move.md`
- 2026-09-29 [plan] `src/` layout move (map prerequisite 4): code into `src/sec_agent/` (agent, verification, sources, retrieval, llm, prompts, eval) and `tools/`, basenames kept, editable install replaces sys.path hacks; generated data anchored under root `var/`; critical core widened to whole-subpackage globs (user); replay identical over 1211 runs after each commit → `docs/plans/2026-09-29-src-layout-move.md`
- 2026-09-29 [review] Ollama and prose-fallback removal: 3 rounds (Substantial; code-review high, arch opus, security, simplify), 21 findings, 17 fixed; headline fixes: a text reply at the budget edge now spends the reserved final round trip on a forced submit, a stale `DEFAULT_BACKEND` fails up front via `require_backend`, and the grader's window reset is tested again; mixed-turn submission cache deferred → `docs/reviews/2026-09-29-remove-ollama-and-prose-fallback.md`
- 2026-09-29 [decision] Prose-citation fallback deleted with Ollama: text after a forced submit is refused (`no_submission`, `NO_SUBMISSION_REFUSAL`), a retry-cached submission is re-gated instead; revisits the structural review's keep-it (its reason was the Ollama path); 1 real prose answer in 1,303 traced Gemini runs → `docs/decisions/2026-09-29-remove-ollama-and-prose-fallback.md`
- 2026-09-29 [plan] Remove Ollama and the prose-citation fallback (map prerequisite 3): commit 1 drops the Ollama backend and the three backend-gating sets, keeping the one-entry BACKENDS seam; commit 2 replaces the prose fallback with a refusal when the model won't submit even after forcing (1 real prose answer in 1,303 traced Gemini runs) → `docs/plans/2026-09-29-remove-ollama-and-prose-fallback.md`
- 2026-09-28 [review] Gate replay tool: 4 rounds (Substantial; code-review high, arch opus, security, simplify), 24 findings in round 1 plus 4 in round 2; headline fix: a run can end on the prose path after a submit, so the replay picks the submit matching the final answer; cwd-relative `xbrl_cache` deferred → `docs/reviews/2026-09-28-gate-replay-tool.md`
- 2026-09-28 [plan] Gate replay tool (`analyze_gate_replay.py`, map prerequisite 2): offline re-gating of every traced run's final submit via the agent's own dispatch; verdicts vs logged or a saved baseline (`--compare`, exit 1 on any change incl. tool-result hash drift); extracts `submission_warnings`/`run_search`, fixes budget-exhausted KeyError → `docs/plans/2026-09-28-gate-replay-tool.md`
- 2026-09-28 [plan] Agent-improvement map (merged): supersedes the gate-refusal map and structural review for ticket state; prerequisites first (NUMBER_PATTERN fix → replay tool → Ollama removal → agent.py split → eval summary mode), then retry slot, gate rules, uniform submit loop, not-available answer, period-scoped retrieval, thinking A/B → `docs/plans/2026-09-28-agent-improvement-map.md`
- 2026-09-28 [plan] Structural review (self-grilled): 68 fails since 09-19 = 41 gate, 11 judge, 10 retrieval, 6 wrong; verbatim quotes upheld (value-location test loses 2 true catches); proposals: replay as regression gate, uniform submit loop, first-class not-available answer, thinking-level A/B, period-aware retrieval → `docs/plans/2026-09-28-structural-review.md`
- 2026-09-28 [plan] Gate-refusal flakiness map (wayfinder, self-grilled): offline replay of 38 refusals since 09-19; 6 already fixed; 27/38 got no corrective retry (82% rescue when it runs); retry-slot fix decided pending user OK; frontier: segment-table ranking fix, commit replay tool → `docs/plans/2026-09-28-gate-refusal-flakiness-map.md`
- 2026-09-27 [decision] Unprefixed citation-header strip: `_strip_citation_header` also strips the exact header minus `[n] ` (revisits 09-19 exact-match-only; 17 of 29 traced header echoes were unprefixed); commit `022e851`, fingerprint unchanged `7aec53939ce3`; spot-check 6/6 (WP8 0/2) but no run echoed the header → `docs/decisions/2026-09-27-unprefixed-citation-header-strip.md`
- 2026-09-27 [review] Unprefixed citation-header strip review: Substantial passes, 2 rounds, 3 fixed, 1 disputed (derive test headers via `_citation_header` = tautological) → `docs/reviews/2026-09-27-unprefixed-citation-header-strip.md`
- 2026-09-27 [decision] Prompt-audit rollout summary: roadmap closed; one row per WP1–WP8 (commits, fingerprints, panel B → C, watch); WP1–WP7 accepted, none reverted; open items filed (baseline-improvement plan next) → `docs/decisions/2026-09-27-prompt-audit-rollout.md`
- 2026-09-27 [decision] WP8 final run: 40/47 vs 39/47 and 38/47 (bar ≥ 38 met), 41/48 with the restored question; 3 drops all explained (PLTR panel noise; both NVDA = unprefixed citation-header echo → `quote_not_found`, promoted from Watch list); 0 lenient-parse hits; model pin kept; report `20260927T071935Z` → `docs/decisions/2026-09-27-wp8-final-run.md`
- 2026-09-26 [review] WP8 plan review — 1 round; bar = 47-question cand sum ≥ 38 (compare flags expected with 2 base vs 1 cand), panel drops checked against the WP7 screen first, fixed 3× rerun rule, cut-short run = invalid → `docs/reviews/2026-09-26-wp8-final-run-plan-review.md`
- 2026-09-26 [plan] WP8: one full 48-question run at agent `7aec53939ce3` vs `20260921T222521Z`/`20260922T062823Z` (47 shared), drops explained from traces with `trace_query.py`, model pin kept, rollout summary + deferred items → `docs/plans/2026-09-26-wp8-final-run.md`
- 2026-09-26 [review] WP7 code review — 2 rounds (Substantial by blast radius); whole-float years now converted (fixed a `range()` crash in the multi-year average), `"0000"` stays rejected; 0 deferred → `docs/reviews/2026-09-26-wp7-fiscal-year-strings.md`
- 2026-09-26 [decision] WP7: 4-digit year strings (and whole floats) convert to int, "same no-data reply" wording accepted; screen 35/39 → 36/39, no REGRESSED, `nvda-revenue-two-quarter-comparison` watch ("− 1" gate FP); 0 year strings sent in the window, so 7a not exercised live; agent `7aec53939ce3` → `docs/decisions/2026-09-26-wp7-fiscal-year-strings.md`
- 2026-09-26 [review] WP7 plan review — 1 round; 7a gets its own fingerprint via a dispatcher snapshot scenario, ≥350-request screen cutoff, shorter "same no-data reply" wording, 4-digit strings only → `docs/reviews/2026-09-26-wp7-fiscal-year-strings-plan-review.md`
- 2026-09-26 [plan] WP7: convert 4-digit `fiscal_year` strings to int at the fact/compare boundary (7a) and replace "rejected outright" / "returns null" (7b); BACKLOG (a)/(d) moved to WP8 follow-ups → `docs/plans/2026-09-26-wp7-fiscal-year-strings.md`
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
