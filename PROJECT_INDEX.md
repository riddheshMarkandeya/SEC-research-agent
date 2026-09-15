# SEC Filing Research Agent — Project Index

> This file is an index, not a changelog. Read it in full at the start
> of a session — it should stay short enough that doing so is cheap —
> then follow a linked file for detail on whatever's actually relevant
> to the task at hand. No reasoning, history, or narrative lives here
> directly; every decision, plan, and review is its own dated file under
> `docs/decisions/`, `docs/plans/`, or `docs/reviews/`. See project
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

## Index

One line per file in `docs/decisions/`, `docs/plans/`, and
`docs/reviews/`, reverse-chronological. `TEMPLATE.md` in each directory
is excluded. Copy the relevant `TEMPLATE.md` when starting a new file in
any of the three directories.

- 2026-09-15 [decision] Comment audit Round 4: pointer-fixed agent.py → `docs/decisions/2026-09-15-comment-audit-round4.md`
- 2026-09-15 [plan] Comment audit Round 4 design → `docs/plans/2026-09-15-comment-audit-round4.md`
- 2026-09-15 [review] Comment audit Round 4 review (self-check + fresh subagent) → `docs/reviews/2026-09-15-comment-audit-round4.md`
- 2026-09-15 [decision] Comment audit Round 3: pointer-fixed xbrl_facts.py and numeric_utils.py → `docs/decisions/2026-09-15-comment-audit-round3.md`
- 2026-09-15 [plan] Comment audit Round 3 design → `docs/plans/2026-09-15-comment-audit-round3.md`
- 2026-09-15 [review] Comment audit Round 3 review (self-check + fresh subagent) → `docs/reviews/2026-09-15-comment-audit-round3.md`
- 2026-09-15 [decision] XBRL metric-tag selection methodology, extracted from xbrl_facts.py's own comments → `docs/decisions/2026-09-15-xbrl-tag-selection-methodology.md`
- 2026-09-14 [decision] Comment audit Round 2: pointer-fixed 10 more main-source files → `docs/decisions/2026-09-14-comment-audit-round2.md`
- 2026-09-14 [plan] Comment audit Round 2 design → `docs/plans/2026-09-14-comment-audit-round2.md`
- 2026-09-14 [review] Comment audit Round 2 review (self-check + fresh subagent) → `docs/reviews/2026-09-14-comment-audit-round2.md`
- 2026-09-14 [decision] Comment audit Round 1: pointer-fixed 6 low-risk main-source files → `docs/decisions/2026-09-14-comment-audit-round1.md`
- 2026-09-14 [plan] Comment audit Round 1 design → `docs/plans/2026-09-14-comment-audit-round1.md`
- 2026-09-14 [review] Comment audit Round 1 review (self-check + fresh subagent) → `docs/reviews/2026-09-14-comment-audit-round1.md`
- 2026-09-14 [decision] Documentation system overhaul: index + per-decision files replace the narrative changelog → `docs/decisions/2026-09-14-documentation-system-overhaul.md`
- 2026-09-14 [plan] Documentation system overhaul design → `docs/plans/2026-09-14-documentation-system-overhaul.md`
- 2026-09-14 [review] Documentation system overhaul review (self-check) → `docs/reviews/2026-09-14-documentation-system-overhaul.md`
- 2026-09-14 [decision] Tool-turn-waste fix: stop re-deriving what a tool already gave → `docs/decisions/2026-09-14-tool-turn-waste.md`
- 2026-09-14 [plan] Tool-turn-waste fix design → `docs/plans/2026-09-14-tool-turn-waste.md`
- 2026-09-14 [review] Tool-turn-waste fix review → `docs/reviews/2026-09-14-tool-turn-waste.md`
- 2026-09-13 [decision] Table-grounding region-scoped redesign — fixes two live eval regressions → `docs/decisions/2026-09-13-table-grounding-region-scoped-matching.md`
- 2026-09-13 [plan] Table-grounding region-scoped redesign design → `docs/plans/2026-09-13-table-grounding-region-scoped-matching.md`
- 2026-09-13 [review] Table-grounding region-scoped redesign review — HIGH-severity regression caught before shipping → `docs/reviews/2026-09-13-table-grounding-region-scoped-matching.md`
- 2026-09-12 [decision] Structure-aware table quote grounding replaces the flat anchor floor → `docs/decisions/2026-09-12-structure-aware-table-quote-grounding.md`
- 2026-09-12 [plan] Structure-aware table quote grounding design → `docs/plans/2026-09-12-structure-aware-table-quote-grounding.md`
- 2026-09-12 [review] Structure-aware table quote grounding review → `docs/reviews/2026-09-12-structure-aware-table-quote-grounding.md`
- 2026-09-11 [decision] Verifiable `calculate` tool, plus new citation-gate stress questions → `docs/decisions/2026-09-11-calculate-tool-and-stress-questions.md`
- 2026-09-11 [decision] Negative-number support in the shared numeric extractor → `docs/decisions/2026-09-11-negative-number-support.md`
- 2026-09-11 [plan] `calculate` tool and stress-questions design → `docs/plans/2026-09-11-calculate-tool-and-stress-questions.md`
- 2026-09-11 [review] `calculate` tool and stress-questions review → `docs/reviews/2026-09-11-calculate-tool-and-stress-questions.md`
- 2026-09-11 [review] Negative-number support review — 4-round investigation → `docs/reviews/2026-09-11-negative-number-support.md`
- 2026-09-10 [decision] Citation-gate FP/FN measurement instrumentation; Ollama demoted to secondary backend → `docs/decisions/2026-09-10-citation-gate-measurement-instrumentation.md`
- 2026-09-10 [decision] Fixed 3 more full-codebase-review findings (§11/§12/§13) → `docs/decisions/2026-09-10-fix-3-more-review-findings.md`
- 2026-09-10 [decision] Structured-claims citation verification replaces the prose heuristic → `docs/decisions/2026-09-10-structured-claims-citation-verification.md`
- 2026-09-10 [plan] Citation-gate measurement instrumentation design → `docs/plans/2026-09-10-citation-gate-measurement-instrumentation.md`
- 2026-09-10 [plan] Structured-claims citation verification design → `docs/plans/2026-09-10-structured-claims-citation-verification.md`
- 2026-09-10 [review] Citation-gate measurement instrumentation review → `docs/reviews/2026-09-10-citation-gate-measurement-instrumentation.md`
- 2026-09-10 [review] Fix-3-more-review-findings (§11/§12/§13) review → `docs/reviews/2026-09-10-fix-3-more-review-findings.md`
- 2026-09-10 [review] Structured-claims citation verification review → `docs/reviews/2026-09-10-structured-claims-citation-verification.md`
- 2026-09-09 [decision] Uncited-claim detection, `get_frame()` ordering fix, `verify_retrieval.py` → `docs/decisions/2026-09-09-citation-gap-frame-ordering-retrieval-verify.md`
- 2026-09-09 [decision] Fixed 3 more full-codebase-review findings (§6/§8/§10) → `docs/decisions/2026-09-09-fix-3-more-review-findings.md`
- 2026-09-09 [decision] Schema-driven arg/input validation redesign → `docs/decisions/2026-09-09-schema-driven-arg-validation.md`
- 2026-09-09 [plan] Citation-gap/frame-ordering/retrieval-verify design → `docs/plans/2026-09-09-citation-gap-frame-ordering-retrieval-verify.md`
- 2026-09-09 [plan] Schema-driven arg validation design → `docs/plans/2026-09-09-schema-driven-arg-validation.md`
- 2026-09-09 [review] Citation-gap/frame-ordering/retrieval-verify review — five rounds → `docs/reviews/2026-09-09-citation-gap-frame-ordering-retrieval-verify.md`
- 2026-09-09 [review] Fix-3-more-review-findings (§6/§8/§10) review → `docs/reviews/2026-09-09-fix-3-more-review-findings.md`
- 2026-09-09 [review] Schema-driven arg validation review → `docs/reviews/2026-09-09-schema-driven-arg-validation.md`
- 2026-09-08 [decision] Fixed 3 Medium-priority full-codebase-review findings (§5/§7/§9) → `docs/decisions/2026-09-08-fix-3-medium-review-findings.md`
- 2026-09-08 [review] Fix-3-medium-review-findings (§5/§7/§9) review → `docs/reviews/2026-09-08-fix-3-medium-review-findings.md`
- 2026-09-07 [decision] Redesigned `get_metric_all_companies()` to split by concept type → `docs/decisions/2026-09-07-fix-get-metric-all-companies-instant-metrics.md`
- 2026-09-07 [plan] `get_metric_all_companies()` instant-metrics redesign design → `docs/plans/2026-09-07-fix-get-metric-all-companies-instant-metrics.md`
- 2026-09-06 [decision] Fixed the 4 High-priority full-codebase-review findings → `docs/decisions/2026-09-06-full-codebase-review.md`
- 2026-09-06 [review] Full-codebase review — original findings, all severities → `docs/reviews/2026-09-06-full-codebase-review.md`
- 2026-09-05 [decision] Local JSONL trace log — a Langfuse-independent backup → `docs/decisions/2026-09-05-local-jsonl-trace-log.md`
- 2026-09-05 [decision] Local-only debug events beyond the Langfuse mirror → `docs/decisions/2026-09-05-local-only-debug-events.md`
- 2026-09-04 [decision] Week 7 guardrails, part 3: Langfuse tracing → `docs/decisions/2026-09-04-langfuse-tracing.md`
- 2026-09-01 [decision] Week 7 guardrails, part 2: `mcp_server.py` auth + rate limiting → `docs/decisions/2026-09-01-mcp-server-auth-rate-limiting.md`
- 2026-08-28 [decision] Ratio-formula registration made cheap: `RATIO_DEFINITIONS` table → `docs/decisions/2026-08-28-ratio-definitions-table-driven-registry.md`
- 2026-08-26 [decision] Repo folder reorganization: `verify_*.py` → `tests/manual/`, eval data → `eval/` → `docs/decisions/2026-08-26-repo-folder-reorganization.md`
- 2026-08-26 [decision] Week 7 guardrails, part 1: citation hard-gate + Ollama retry/backoff → `docs/decisions/2026-08-26-week7-citation-hard-gate-ollama-retry.md`
- 2026-08-25 [decision] Citation-verification retry loop v2 — rebuilt against Gemini, gated → `docs/decisions/2026-08-25-citation-retry-loop-gemini-gated.md`
- 2026-08-25 [decision] Eval growth 27 → 38: multi-statement ratios, cross-section synthesis, indirect disambiguation, cross-company ranking → `docs/decisions/2026-08-25-eval-growth-27-to-38-multi-statement-ranking.md`
- 2026-08-25 [decision] Formula registry extended: return_on_assets, asset_turnover, cash_to_assets → `docs/decisions/2026-08-25-formula-registry-roa-turnover-cash.md`
- 2026-08-25 [decision] MCP server exposing all 3 agent tools over Streamable HTTP (Week 6) → `docs/decisions/2026-08-25-mcp-server-week6.md`
- 2026-08-24 [plan] Citation-verification retry-loop v2 design → `docs/plans/2026-08-24-citation-retry-loop-design.md`
- 2026-08-20 [decision] Swappable LLM backend: llm_backends.py normalizes Ollama/Gemini into one shared loop → `docs/decisions/2026-08-20-swappable-llm-backend.md`
- 2026-08-20 [decision] Comparison-reasoning bug root-caused: local-model capability limit, confirmed via Gemini → `docs/decisions/2026-08-20-comparison-reasoning-model-capability-limit.md`
- 2026-08-20 [plan] Swappable LLM backend design (Ollama/Gemini) → `docs/plans/2026-08-20-swappable-llm-backend-design.md`
- 2026-08-20 [plan] Swappable LLM backend implementation plan → `docs/plans/2026-08-20-swappable-llm-backend.md`
- 2026-08-19 [decision] `discover_tags.py`: dev-time XBRL tag discovery → `docs/decisions/2026-08-19-discover-tags-dev-tool.md`
- 2026-08-19 [decision] Eval growth round 4: 25 → 27 questions (FinanceBench priorities 3, 5) → `docs/decisions/2026-08-19-eval-growth-round4-financebench-3-5.md`
- 2026-08-19 [decision] `eval_harness.py`: `--ids`/`skip` question filtering → `docs/decisions/2026-08-19-eval-harness-ids-skip-filtering.md`
- 2026-08-19 [decision] Fixing the 6 accumulated eval findings from growth rounds 3 and 4 → `docs/decisions/2026-08-19-fixing-6-accumulated-eval-findings.md`
- 2026-08-19 [decision] Table-chunk rescue in reranking (`retrieval.py`) → `docs/decisions/2026-08-19-table-chunk-rescue-in-reranking.md`
- 2026-08-18 [decision] Citation-verification retry loop (v1) — tried and reverted → `docs/decisions/2026-08-18-citation-retry-loop-v1-tried-reverted.md`
- 2026-08-18 [decision] Wire citation-verification into eval pass/fail, not just a warning → `docs/decisions/2026-08-18-citation-verification-wired-into-eval-gate.md`
- 2026-08-18 [decision] Eval growth round 3: 21 → 25 questions (FinanceBench priorities 1-2) → `docs/decisions/2026-08-18-eval-growth-round3-financebench-1-2.md`
- 2026-08-18 [decision] FinanceBench pattern analysis, informing eval-growth priorities → `docs/decisions/2026-08-18-financebench-analysis.md`
- 2026-08-18 [decision] Formula registry: `operating_margin`, `net_margin`, `yoy_growth` → `docs/decisions/2026-08-18-formula-registry-margins-and-growth.md`
- 2026-08-18 [decision] Formula registry split into its own module (`formulas.py`) → `docs/decisions/2026-08-18-formulas-module-split.md`
- 2026-08-18 [decision] Cloud-model spike: Gemini free tier (throwaway) → `docs/decisions/2026-08-18-gemini-cloud-model-spike.md`
- 2026-08-18 [decision] Per-claim citation placement (system-prompt rule 8) → `docs/decisions/2026-08-18-per-claim-citation-placement-rule.md`
- 2026-08-18 [decision] Q4-refusal fix: tool message explains *why*, not just *that*, data is missing → `docs/decisions/2026-08-18-q4-refusal-fix.md`
- 2026-08-17 [decision] Centralized environment configuration (`config.py`) → `docs/decisions/2026-08-17-centralized-env-config.md`
- 2026-08-17 [decision] Citation-verification pass (`numeric_utils.py`, `verify_citations()`) → `docs/decisions/2026-08-17-citation-verification-pass.md`
- 2026-08-17 [decision] Cross-company comparison via SEC's `frames` API → `docs/decisions/2026-08-17-frames-api-cross-company.md`
- 2026-08-17 [decision] XBRL period matching: match on `end` date, not a computed label → `docs/decisions/2026-08-17-xbrl-period-matching-end-date-fix.md`
- 2026-08-16 [decision] Fiscal-period embedding labels — tried, measured, reverted → `docs/decisions/2026-08-16-fiscal-period-labels-tried-and-reverted.md`
- 2026-08-16 [decision] Structured XBRL facts tool (`xbrl_facts.py`, `get_financial_fact`) → `docs/decisions/2026-08-16-xbrl-structured-facts-tool.md`
- 2026-08-14 [decision] `agent.py` v0: tool-calling agent (Week 5) → `docs/decisions/2026-08-14-agent-v0-tool-calling.md`
- 2026-08-14 [decision] TDD adoption and pre-commit test gate → `docs/decisions/2026-08-14-tdd-adoption-pre-commit-hook.md`
- 2026-08-14 [decision] Shared ticker/company registry (`companies.py` + `companies.json`) → `docs/decisions/2026-08-14-ticker-company-registry.md`
- 2026-08-13 [decision] `answer.py` v0 prototype, and its 2026-08-25 retirement → `docs/decisions/2026-08-13-answer-py-prototype-and-retirement.md`
- 2026-08-13 [decision] Filing reconstruction and chunking (`chunk_documents.py`, Week 2a) → `docs/decisions/2026-08-13-chunking-pipeline.md`
- 2026-08-13 [decision] Corpus ingestion/chunking/embedding verification, and initial retrieval gaps → `docs/decisions/2026-08-13-corpus-ingestion-verification.md`
- 2026-08-13 [decision] SEC EDGAR filing ingestion (`edgar_ingest.py`, Week 1) → `docs/decisions/2026-08-13-edgar-ingestion.md`
- 2026-08-13 [decision] Embedding + Chroma indexing, and the manual query CLI (Week 2b) → `docs/decisions/2026-08-13-embedding-indexing-and-query-cli.md`
- 2026-08-13 [decision] Eval harness scaffolding, and the first rounds of bug-driven eval growth → `docs/decisions/2026-08-13-eval-harness-scaffolding-and-early-bug-hunts.md`
- 2026-08-13 [decision] Hybrid retrieval (BM25 + vector + rerank), and the MAX-of-RRF reranker fix → `docs/decisions/2026-08-13-hybrid-retrieval-and-reranker-fix.md`
