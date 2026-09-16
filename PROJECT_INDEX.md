# SEC Filing Research Agent — Project Index

> This file is an index, not a changelog. The `## Recent` section below
> is capped at 50 entries (trimmed back to 40 whenever it's exceeded) so
> reading it in full at the start of every session stays cheap
> permanently, regardless of how much project history accumulates — not
> just because it happens to be short today. Older entries live in
> `PROJECT_INDEX_ARCHIVE.md`: search it with a text search when a task
> might touch history older than what's in `Recent`, never read it in
> full. No reasoning, history, or narrative lives here directly; every
> decision, plan, and review is its own dated file under
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

## Recent

One line per file in `docs/decisions/`, `docs/plans/`, and
`docs/reviews/`, reverse-chronological. `TEMPLATE.md` in each directory
is excluded. Copy the relevant `TEMPLATE.md` when starting a new file in
any of the three directories. **Capped at 50 entries**: when adding one
pushes this section past 50, cut the oldest entries back down to 40 and
prepend them (verbatim, still reverse-chronological) to the top of
`PROJECT_INDEX_ARCHIVE.md`.

- 2026-09-15 [decision] Capped PROJECT_INDEX.md's session-read cost — split into a 50-entry-capped Recent section plus PROJECT_INDEX_ARCHIVE.md, generalizing the 2026-09-14 overhaul recursively → `docs/decisions/2026-09-15-cap-project-index-growth.md`
- 2026-09-15 [decision] Revoked the comment→decision-file pointer convention (comments must now be self-contained, no file-path links) — amends the 2026-09-14 documentation-system overhaul and comment-audit rounds → `docs/decisions/2026-09-15-revoke-comment-pointer-convention.md`
- 2026-09-15 [decision] Expanded ruff's PLR selection (added PLR0402, scoped PLR2004 away from tests/) after surveying the full PLR family with real hit counts → `docs/decisions/2026-09-15-expand-ruff-plr-rules.md`
- 2026-09-15 [review] Ruff PLR-expansion review — clean, no findings → `docs/reviews/2026-09-15-expand-ruff-plr-rules.md`
- 2026-09-15 [decision] Restructured CLAUDE.md (global + project) into personal skills, path-scoped `.claude/rules/`, and a docs-sync hook → `docs/decisions/2026-09-15-claude-md-restructure.md`
- 2026-09-15 [plan] CLAUDE.md restructure design → `docs/plans/2026-09-15-claude-md-restructure.md`
- 2026-09-15 [review] CLAUDE.md restructure review — found/fixed a doc inconsistency, a hook false-positive, a crash edge case, and a test-coverage gap → `docs/reviews/2026-09-15-claude-md-restructure.md`
- 2026-09-15 [decision] Adopt ruff as this project's linter, changed-files-scoped for now → `docs/decisions/2026-09-15-adopt-ruff-linter.md`
- 2026-09-15 [decision] Comment-audit initiative concluded (19/19 main-source, 9/25 tests/ files done; rest deferred to opportunistic per-touch cleanup) → `docs/decisions/2026-09-15-comment-audit-concluded.md`
- 2026-09-15 [decision] Comment audit Round 6: pointer-fixed 4 large unit-test files → `docs/decisions/2026-09-15-comment-audit-round6.md`
- 2026-09-15 [plan] Comment audit Round 6 design → `docs/plans/2026-09-15-comment-audit-round6.md`
- 2026-09-15 [review] Comment audit Round 6 review (self-check + fresh subagent) → `docs/reviews/2026-09-15-comment-audit-round6.md`
- 2026-09-15 [decision] Comment audit Round 5: pointer-fixed 5 small tests/ files → `docs/decisions/2026-09-15-comment-audit-round5.md`
- 2026-09-15 [plan] Comment audit Round 5 design → `docs/plans/2026-09-15-comment-audit-round5.md`
- 2026-09-15 [review] Comment audit Round 5 review (self-check + fresh subagent) → `docs/reviews/2026-09-15-comment-audit-round5.md`
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
