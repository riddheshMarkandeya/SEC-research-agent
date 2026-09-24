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

`## Recent` below holds one line per file in `docs/decisions/`,
`docs/plans/`, and `docs/reviews/`, reverse-chronological, newest
directly under the heading. `TEMPLATE.md` in each directory
is excluded. Copy the relevant `TEMPLATE.md` when starting a new file in
any of the three directories. **Capped at 50 entries**: when adding one
pushes it past 50, cut the oldest entries back down to 40 and
prepend them (verbatim, still reverse-chronological) to the top of
`PROJECT_INDEX_ARCHIVE.md`.

## Recent

- 2026-09-24 [review] WP1 prompts-package code review — 3 rounds; no model-facing byte changed (hashes + 44-entry golden identical each round); doc pointers, stale docstrings, duplicated metric list and raw-unit rule fixed, pre-push glob widened to `prompts/**/*.py`; raw-unit calculate text and enum duplication filed → `docs/reviews/2026-09-24-wp1-prompts-package.md`
- 2026-09-24 [decision] All model-facing text moved into `prompts/` (agent_system, agent_tools, agent_messages, judge, mcp), byte-identical; pre-push keeps its own critical-core list; live-eval exemption for a provably pure move → `docs/decisions/2026-09-24-wp1-prompts-package.md`
- 2026-09-24 [review] WP1 plan review — no blockers; golden capture moved to the backend boundary, formatters kept in agent.py (tests monkeypatch them), judge-location wording moved to 1c → `docs/reviews/2026-09-24-wp1-prompts-package-plan-review.md`
- 2026-09-24 [plan] WP1: move model-facing text into a `prompts/` package (roadmap Step 1, commits 1a–1c), proven by hashes and a golden capture → `docs/plans/2026-09-24-wp1-prompts-package.md`
- 2026-09-24 [review] Prompt-audit roadmap plan review — 3 rounds; biased revert rule, contradicting rule-3 rewrite, false MCP descriptions, fragile fingerprint rule and a mis-targeted Step 7 (138 fiscal_year-string rejections, not extra arguments) all fixed before approval → `docs/reviews/2026-09-24-prompt-audit-roadmap-plan-review.md`
- 2026-09-24 [review] Prompt-surface audit and model-facing-text survey — 13 findings (description/behaviour mismatches, rule 3/9 contradiction, "None FYNone" no-data text, 138 silent fiscal_year rejections); judge-format change deferred until evidence appears; target Gemini, Claude-only rows excluded → `docs/reviews/2026-09-24-prompt-audit.md`
- 2026-09-24 [plan] Prompt-audit roadmap: `prompts/` package, fingerprinted eval provenance + compare script, panel-screened one-commit-per-finding rollout, split into BACKLOG work packages WP1–WP8 → `docs/plans/2026-09-24-prompt-audit-roadmap.md`
- 2026-09-23 [review] Docs-index pre-commit implementation review — 4 rounds; prose-arrow matches, fail-closed interpreter lookup, non-ASCII paths and non-docs dangling entries fixed → `docs/reviews/2026-09-23-docs-index-pre-commit.md`
- 2026-09-23 [decision] One docs-index check as a git pre-commit hook (blocks unindexed docs and dangling entries, warns on Recent over cap); PreToolUse and SessionStart hooks removed; hooks installed via core.hooksPath → `docs/decisions/2026-09-23-docs-index-pre-commit.md`
- 2026-09-23 [review] Docs-index pre-commit plan review — 2 must-fix (cp1252 decoding of git output, --dry-run skips hooks) → `docs/reviews/2026-09-23-docs-index-pre-commit-plan-review.md`
- 2026-09-23 [plan] Docs-index pre-commit hook replacing the PreToolUse and SessionStart checks → `docs/plans/2026-09-23-docs-index-pre-commit.md`
- 2026-09-23 [review] Context-management hooks implementation review — non-UTF-8 crash and prose-backtick false-index fixed; pre-commit consolidation deferred → `docs/reviews/2026-09-23-context-management-hooks.md`
- 2026-09-23 [decision] Context-management trial: plan-accept clear setting, two project-local CLAUDE.md rules, and a SessionStart docs-health audit (`scripts/check_docs_health.py`) closing the chained-commit BACKLOG gap → `docs/decisions/2026-09-23-context-management-hooks.md`
- 2026-09-23 [review] Context-management hooks plan review — 4 must-fix; PostToolUse post-commit check dropped → `docs/reviews/2026-09-23-context-management-hooks-plan-review.md`
- 2026-09-23 [plan] Context-management workflow design: plan-accept clear-context setting, two trial CLAUDE.md rules (self-contained plans saved first; stop-and-suggest-/compact before review), and a SessionStart docs-health audit hook → `docs/plans/2026-09-23-context-management-hooks.md`
- 2026-09-23 [decision] Restored nvda-revenue-yoy-growth-q1fy27 to eval_questions.jsonl (48 questions; designed 2026-09-11, dropped after 2x budget-exhaustion, retried since the 2026-09-16 final-turn safety net targets that exact failure) and added a final_turn_forced log event to agent.py so the safety net's own triggering is directly queryable — 3 live Gemini runs all passed, one directly confirmed the safety net rescuing a real budget-exhaustion mid-run, but only 1/3 demonstrably exercised the target two-nearby-percentages citation risk (2/3 passed via a safer table-cell citation instead); BACKLOG.md item kept open with this evidence, not closed on a superficial 3/3 pass rate → `docs/decisions/2026-09-23-restore-nvda-yoy-stress-question.md`
- 2026-09-22 [decision] Extended analyze_flakiness.py to classify eval questions as solid/flaky/regression/insufficient-data via a capped 20-run trailing window (streak/transition-based, not unbounded all-time pass rate), researched against real prior art (Google's bounded-window mitigation, academic flaky-test literature, Wilson score intervals, Meta's probabilistic flakiness score) — plan review caught 2 real algorithmic bugs pre-implementation, a 3-round post-implementation review caught 6 more (missing threshold validation, a hardcoded CI label, a cross-field validation gap); 766 tests passing, live-verified against all 127 historical reports → `docs/decisions/2026-09-22-eval-question-classification.md`
- 2026-09-22 [review] Eval-question-classification review — 3 rounds (code-review, architecture/doc-hygiene, security, /simplify x2) fixed 10 total findings across validation gaps, a duplicated helper, a hardcoded lookup table, and doc-hygiene pointer violations; converged clean on round 3 → `docs/reviews/2026-09-22-eval-question-classification.md`
- 2026-09-22 [plan] Eval-question-classification design (solid/flaky/regression/insufficient-data via capped-window streak/transition classification, Wilson CI as display-only) — independent plan review caught a misclassified-recovery bug and an unreachable solid-floor boundary before implementation → `docs/plans/2026-09-22-eval-question-classification.md`
- 2026-09-22 [decision] Closed most of the pytest-coverage baseline gap (94% overall, up from 90%; deleted superseded query_chunks.py, fully closed index_chunks.py/eval_harness.py, partially closed chunk_documents.py/mcp_server.py), turned on branch coverage after measuring real repo-wide impact (only 30 partial branches, no noise blowup), and moved ALL checks (ruff, pyright, pytest, coverage) from a pre-commit gate to a new pre-push gate so commits stay fast — explicitly revisiting four prior decisions (2026-08-14's original pytest gate, 2026-09-21's ruff gate, 2026-09-22's pyright gate, and 2026-09-22's own pytest-coverage adoption's non-gate deferral) per real, felt commit-speed friction → `docs/decisions/2026-09-22-coverage-baseline-close-and-hard-gate.md`
- 2026-09-22 [decision] Adopted pytest-cov/diff-cover coverage measurement with an incremental diff-scoped policy (80% ordinary / 90% critical-core new-changed-lines, reusing plan-review-blast-radius.md's 8-file list) — live-only lines pragma-excluded per live-code-tdd.md after reading each file directly (retrieval.py/edgar_ingest.py/index_chunks.py needed exclusions, xbrl_facts.py needed one for fetch_frame only since fetch_concept is genuinely boundary-tested, agent.py/llm_backends.py needed none, already boundary-tested); measured real baseline 90% overall (93% critical-core, 83.5% ordinary), both already above target; also stood up this repo's first `origin` GitHub remote, fixing /security-review's standing gap → `docs/decisions/2026-09-22-adopt-pytest-coverage.md`
- 2026-09-22 [decision] Migrated pyright to a hard full-repo pre-commit gate (githooks/pre-commit, alongside the existing ruff and pytest steps), resolving the 2026-09-21 ruff-gate decision's decoupling now that pyright's own 117-error baseline closed the same day → `docs/decisions/2026-09-22-pyright-pre-commit-gate.md`
- 2026-09-22 [review] Pyright-clean-refactor diff review — mandatory 5-pass independent-review-pass found and fixed 2 real issues (undeclared httpx2 import now pinned in requirements-dev.txt, missing plan-review disclaimer); surfaced a repo-wide gap (`/security-review` can't run, no `origin` remote) filed to BACKLOG.md; one code-review angle's "fabricated docs" claim checked directly and didn't hold up; `/simplify` clean → `docs/reviews/2026-09-22-pyright-clean-refactor.md`
- 2026-09-22 [decision] Implemented the pyright-clean-refactor plan (117-error basic-mode baseline resolved across 9 test/verify files via type-narrowing asserts + 4 casts + 1 comprehension rewrite + the httpx2 dependency fix, zero logic change) — pyright . 0 errors full-repo, core modules re-verified clean, full suite 707 passing, live verify_mcp_server.py run confirmed the httpx2 swap works, eval baseline 38/47 (1 below the ≥39/47 target but every failure a known pre-existing flaky question per analyze_flakiness.py, zero core-module changed, user accepted in lieu of a second full run) → `docs/decisions/2026-09-22-pyright-clean-refactor.md`
- 2026-09-22 [review] Pyright-clean-refactor plan review — confirmed error counts/breakdown and call_calculate's exactly-one-populated contract directly against code; caught and corrected a factually wrong httpx-vendoring claim for one site, fixing a real, previously-undocumented httpx/httpx2 dependency mismatch instead of suppressing it → `docs/reviews/2026-09-22-pyright-clean-refactor-plan-review.md`
- 2026-09-22 [plan] Pyright-clean-refactor design (close the 117-error basic-mode pyright baseline across 9 test/verify files via type-narrowing asserts + targeted casts + one comprehension rewrite + one dependency-import fix, zero logic change; 7 core modules + tracing.py untouched) — saved for a `/goal` autonomous run, not yet implemented → `docs/plans/2026-09-22-pyright-clean-refactor.md`
- 2026-09-21 [decision] Migrated ruff to a hard full-repo pre-commit gate (githooks/pre-commit, alongside the existing pytest hook); decoupled pyright's own migration from ruff's since pyright's 117-error baseline is unrelated and unchanged, revisiting the 2026-09-15 adoption decisions' joint-migration premise → `docs/decisions/2026-09-21-ruff-pre-commit-gate.md`
- 2026-09-21 [decision] Implemented the ruff-complexity-refactor plan (11 complexity findings + 146 E501 violations resolved, zero mangled prompt/schema strings) — ruff check . and pyright both clean, full suite 707 passing, live baseline 39/47 (>=39/47 required, no regression vs. historical flakiness) → `docs/decisions/2026-09-21-ruff-complexity-refactor.md`
- 2026-09-21 [review] Ruff-complexity-refactor code review — 8-angle independent review found and fixed 6 real issues (should-be-frozen dataclass, unrelated scope creep, unnecessary dict-passing in 3/4 dispatch helpers, a transposable-tuple return contract replaced with a named-field type, a doc-scope inaccuracy, a dropped comment's rationale); 2 findings explicitly deferred with reasoning → `docs/reviews/2026-09-21-ruff-complexity-refactor.md`
- 2026-09-21 [plan] Ruff-complexity-refactor design (fix agent.py's 4 highest-complexity functions + 3 smaller ones via pure extraction; formalize the accepted E501 long-string exception via per-file-ignore/noqa instead of fixing it) — two independent review rounds, first caught a control-flow bug in the _run_agent_impl decomposition (would have broken the loop on ordinary turns), second confirmed the fix; Addendum documents the code-review round's fixes → `docs/plans/2026-09-21-ruff-complexity-refactor.md`
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
