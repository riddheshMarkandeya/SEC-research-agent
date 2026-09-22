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

- 2026-09-22 [decision] Migrated pyright to a hard full-repo pre-commit gate (githooks/pre-commit, alongside the existing ruff and pytest steps), resolving the 2026-09-21 ruff-gate decision's decoupling now that pyright's own 117-error baseline closed the same day → `docs/decisions/2026-09-22-pyright-pre-commit-gate.md`
- 2026-09-22 [review] Pyright-clean-refactor diff review — mandatory 5-pass independent-review-pass found and fixed 2 real issues (undeclared httpx2 import now pinned in requirements-dev.txt, missing plan-review disclaimer); surfaced a repo-wide gap (`/security-review` can't run, no `origin` remote) filed to BACKLOG.md; one code-review angle's "fabricated docs" claim checked directly and didn't hold up; `/simplify` clean → `docs/reviews/2026-09-22-pyright-clean-refactor.md`
- 2026-09-22 [decision] Implemented the pyright-clean-refactor plan (117-error basic-mode baseline resolved across 9 test/verify files via type-narrowing asserts + 4 casts + 1 comprehension rewrite + the httpx2 dependency fix, zero logic change) — pyright . 0 errors full-repo, core modules re-verified clean, full suite 707 passing, live verify_mcp_server.py run confirmed the httpx2 swap works, eval baseline 38/47 (1 below the ≥39/47 target but every failure a known pre-existing flaky question per analyze_flakiness.py, zero core-module changed, user accepted in lieu of a second full run) → `docs/decisions/2026-09-22-pyright-clean-refactor.md`
- 2026-09-22 [review] Pyright-clean-refactor plan review — confirmed error counts/breakdown and call_calculate's exactly-one-populated contract directly against code; caught and corrected a factually wrong httpx-vendoring claim for one site, fixing a real, previously-undocumented httpx/httpx2 dependency mismatch instead of suppressing it → `docs/reviews/2026-09-22-pyright-clean-refactor-plan-review.md`
- 2026-09-22 [plan] Pyright-clean-refactor design (close the 117-error basic-mode pyright baseline across 9 test/verify files via type-narrowing asserts + targeted casts + one comprehension rewrite + one dependency-import fix, zero logic change; 7 core modules + tracing.py untouched) — saved for a `/goal` autonomous run, not yet implemented → `docs/plans/2026-09-22-pyright-clean-refactor.md`
- 2026-09-21 [decision] Migrated ruff to a hard full-repo pre-commit gate (githooks/pre-commit, alongside the existing pytest hook); decoupled pyright's own migration from ruff's since pyright's 117-error baseline is unrelated and unchanged, revisiting the 2026-09-15 adoption decisions' joint-migration premise → `docs/decisions/2026-09-21-ruff-pre-commit-gate.md`
- 2026-09-21 [decision] Implemented the ruff-complexity-refactor plan (11 complexity findings + 146 E501 violations resolved, zero mangled prompt/schema strings) — ruff check . and pyright both clean, full suite 707 passing, live baseline 39/47 (>=39/47 required, no regression vs. historical flakiness) → `docs/decisions/2026-09-21-ruff-complexity-refactor.md`
- 2026-09-21 [review] Ruff-complexity-refactor code review — 8-angle independent review found and fixed 6 real issues (should-be-frozen dataclass, unrelated scope creep, unnecessary dict-passing in 3/4 dispatch helpers, a transposable-tuple return contract replaced with a named-field type, a doc-scope inaccuracy, a dropped comment's rationale); 2 findings explicitly deferred with reasoning → `docs/reviews/2026-09-21-ruff-complexity-refactor.md`
- 2026-09-21 [plan] Ruff-complexity-refactor design (fix agent.py's 4 highest-complexity functions + 3 smaller ones via pure extraction; formalize the accepted E501 long-string exception via per-file-ignore/noqa instead of fixing it) — two independent review rounds, first caught a control-flow bug in the _run_agent_impl decomposition (would have broken the loop on ordinary turns), second confirmed the fix; Addendum documents the code-review round's fixes → `docs/plans/2026-09-21-ruff-complexity-refactor.md`

One line per file in `docs/decisions/`, `docs/plans/`, and
`docs/reviews/`, reverse-chronological. `TEMPLATE.md` in each directory
is excluded. Copy the relevant `TEMPLATE.md` when starting a new file in
any of the three directories. **Capped at 50 entries**: when adding one
pushes this section past 50, cut the oldest entries back down to 40 and
prepend them (verbatim, still reverse-chronological) to the top of
`PROJECT_INDEX_ARCHIVE.md`.

- 2026-09-19 [decision] Fixed a citation-header-in-quote grounding bug (a model's quote sometimes echoed _format_results_block's display-only header, dragging quote-source coverage below threshold) — strip the header via a shared _citation_header helper before grounding, while preserving the raw quote on any CitationWarning via a new _ClaimQuote(raw, grounding) pairing (a real regression against the prior session's own Fix B, caught by code review); live-confirmed 3/3 on the repro question → `docs/decisions/2026-09-19-citation-header-in-quote-fix.md`
- 2026-09-19 [review] Citation-header-in-quote fix review — found a raw-quote-preservation regression and its resulting PLR0913 arg-count violation, both fixed; 3 other findings confirmed as the plan's already-accepted exact-match-only limitation → `docs/reviews/2026-09-19-citation-header-in-quote-fix.md`
- 2026-09-19 [plan] Citation-header-in-quote fix design → `docs/plans/2026-09-19-citation-header-in-quote-fix.md`
- 2026-09-18 [decision] Fixed 3 eval-flakiness gaps: verify_claims() now exempts already-grounded calculate-tool operands from the uncovered_number check (scoped to exclude the derived result itself, per a live-execution-caught review bug); CitationWarning gained a quote field; new analyze_flakiness.py ranks questions by historical pass rate excluding quota-error rows — 40/47 baseline, all diffs confirmed pre-existing flakiness, no regression → `docs/decisions/2026-09-18-flaky-eval-questions-three-fixes.md`
- 2026-09-18 [review] Flaky-eval-questions fix review — 2 rounds caught a test-breaking parameter design, a bracket-misparse bug, and (post-implementation) a result-value exemption hole, all fixed; live spot-check confirmed both citation-gate fixes against real Gemini output → `docs/reviews/2026-09-18-flaky-eval-questions-three-fixes.md`
- 2026-09-18 [plan] Flaky-eval-questions three-fix design → `docs/plans/2026-09-18-flaky-eval-questions-three-fixes.md`
- 2026-09-17 [decision] Fixed an orphaned-table-fragment chunking bug (chunk_blocks()'s raw-slice overlap could land mid-table, hiding a real row from citation grounding and causing a wrong-cell false match) — made the overlap table-boundary-aware; corpus-wide re-chunk/re-index confirms 0 unbalanced-tag chunks; full-baseline Gemini confirmation (obtained 2026-09-18) 41/47, all 3 targeted questions pass, 6 flips confirmed pre-existing flaky-question non-determinism via historical pass-rate check, not a regression → `docs/decisions/2026-09-17-fix-orphaned-table-overlap-chunking.md`
- 2026-09-17 [review] Orphaned-table-overlap fix review — code review found a real find-vs-rfind bug (over-stripped a valid adjacent table), fixed with a proof and a third regression test; plan review caught a missing blast-radius rule entry → `docs/reviews/2026-09-17-fix-orphaned-table-overlap-chunking.md`
- 2026-09-17 [plan] Orphaned-table-overlap fix design → `docs/plans/2026-09-17-fix-orphaned-table-overlap-chunking.md`
- 2026-09-17 [decision] Made independent-subagent plan review an unconditional floor for every plan mode produces (was conditionally gated to Substantial tier + two Standard-tier trigger conditions) — global skill, CLAUDE.md Trivial-tier exception, and blast-radius rule reframed; hook backstop considered, deferred at user's choice → `docs/decisions/2026-09-17-mandatory-plan-review-floor.md`
- 2026-09-17 [review] Plan-review-floor plan review — independent review caught a CLAUDE.md Trivial-tier gap, an under-scoped rule-file rewrite, and missing docs/plans+docs/reviews artifacts, all fixed before approval → `docs/reviews/2026-09-17-mandatory-plan-review-floor.md`
- 2026-09-17 [plan] Plan-review-floor design → `docs/plans/2026-09-17-mandatory-plan-review-floor.md`
- 2026-09-17 [decision] Fixed the eval judge's "hypothetical/future date" mis-grading bug (grade_judged had no temporal grounding, so a post-training-cutoff 2026 filing date got called fabricated) — injected real wall-clock date into the judge prompt; independent review caught an over-broad system-prompt wording and a test date-race, both fixed; baseline 37/47 → 44/47 → `docs/decisions/2026-09-17-fix-judge-hypothetical-date-bug.md`
- 2026-09-17 [decision] Fixed the uncovered_number false-refusal gap (two distinct causes: ambiguous "$34,550M" abbreviation in a worked example broke number parsing; _NON_CLAIM_PATTERN didn't exempt "N months" durations) — plan review caught a wrong first-draft diagnosis before implementation; baseline 40/47 → 37/47 but both target questions now pass, other flips are pre-existing non-determinism → `docs/decisions/2026-09-17-uncovered-number-gap-fixes.md`
- 2026-09-16 [review] CRM fiscal-year-lookup fix review — independent plan review caught 2 root-cause/tiebreak issues before implementation; code review found 2 minor doc-accuracy nits, both fixed → `docs/reviews/2026-09-16-crm-fiscal-year-lookup-fix.md`
- 2026-09-16 [decision] Fixed CRM's off-by-one annual fiscal-year tagging in xbrl_facts (raw `fy` tag one year behind CRM's own label) — match on end-date's calendar year instead; eval spot-check 3/3 ranking questions now pass → `docs/decisions/2026-09-16-crm-fiscal-year-lookup-fix.md`
- 2026-09-16 [review] Final-turn safety net review — independent plan review caught a dangling-function-call bug before implementation; code review found 2 minor doc/lint hygiene misses, both fixed → `docs/reviews/2026-09-16-final-turn-safety-net.md`
- 2026-09-16 [decision] Fixed MAX_TOOL_ITERATIONS zero-slack bug (no turn left to submit after 5 dispatch calls) — added a Gemini-only reserved final-turn safety net, budget itself unchanged, baseline 37/47 → 39/47 → `docs/decisions/2026-09-16-final-turn-safety-net.md`
- 2026-09-15 [decision] Fixed the qualitative-claims placeholder-value false-refusal bug (model invented value=1 for non-numeric citations) — made value/unit optional in SUBMIT_TOOL_SCHEMA, baseline 36/47 → 37/47 → `docs/decisions/2026-09-15-qualitative-claims-schema.md`
- 2026-09-15 [decision] Adopted pyright in basic mode (strict mode's real baseline was 4,655 errors, ~94% noise; basic was 154) — fixed all core-module findings live-verified → `docs/decisions/2026-09-15-adopt-pyright.md`
- 2026-09-15 [decision] Evaluated pytest-archon/import-linter for architecture-boundary enforcement — rejected, doesn't fit this project's flat (no-package) module layout → `docs/decisions/2026-09-15-evaluate-architecture-linters.md`
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
