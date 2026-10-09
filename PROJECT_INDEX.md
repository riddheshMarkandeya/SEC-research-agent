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
`prompts/`, `eval/`, `devtools/` for the analysis CLIs and the gate replay
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

- 2026-10-09 [decision] Per-ticker BM25 indexes use Lucene's IDF (`_LuceneIdfBM25`) instead of rank_bm25's clamped Okapi IDF, which lifted words in over half a company's chunks above rarer ones (MSFT `revenue` 0.27 < floor 1.15). Replay hit@5 587 → 630 of 981, coverage 33 → 36 of 40 (epsilon=0: 620/36; BM25Plus/BM25L rejected as library-buggy); whole-corpus index unchanged (unmeasured, BACKLOG) → `docs/decisions/2026-10-09-bm25-idf.md`
- 2026-10-09 [review] Lucene IDF for per-ticker BM25: 1 round (Standard), closed; 3 nits fixed, 1 deferred (untickered index keeps Okapi), 3 verified no fix needed → `docs/reviews/2026-10-09-bm25-idf.md`
- 2026-10-08 [decision] BM25 statistics per ticker for ticker'd searches (whole-corpus index kept for untickered): replay hit@5 480 → 587 of 981 (549 on the old corpus), coverage 34 → 33; live spot-check 3/3 incl. the MSFT segment drop; +96 MB working set. Residual losses point at rank_bm25's IDF clamp (next suspect) → `docs/decisions/2026-10-08-bm25-per-ticker-stats.md`
- 2026-10-08 [decision] Phase 2 corpus: 12 companies, 139 filings / 19,292 chunks (index 1,731 s incremental, Chroma 409 MB); TGT pinned to month 2 (end-year labels, no code change). v1 gate 46/48: scoping gate not triggered (every v1 search carries a ticker; offline exposure 224 leaked slots in 56 untickered queries). New regression found: BM25 whole-corpus statistics reorder each company's own list (replay 549 → 480), causing one MSFT segment drop → `docs/decisions/2026-10-08-phase2-ingest.md`
- 2026-10-08 [review] Phase 2 build 2 registry change: 2 rounds, closed clean; TGT month 2 adopted from code review; 5 findings deferred (cold-fetch exposure, frames validation, JNJ 2027 year end, stale fiscal-year docstrings, chunk blank-line count) → `docs/reviews/2026-10-08-phase2-ingest.md`
- 2026-10-08 [plan] Phase 2 build 2: ingest JPM, BAC, TGT, WMT, XOM, JNJ, CAT (78 new filings, 61 → 139; JNJ/TGT fiscal end months pinned by hand), then the v1 gate: offline replay base, a scoping-exposure probe and fact-tool dry run, a full v1 live run with every drop classified. TGT period labels deferred to build 5 → `docs/plans/2026-10-08-phase2-ingest.md`
- 2026-10-07 [review] Incremental indexing for `index_chunks` (per-file sha manifest + recipe in the sidecar, `--full`): 7 rounds (Substantial by diff size), closed clean. Read/id/encode now come before any mutation, and the loader and chunk count share one line splitter. 1 disputed (recipe omits torch/transformers), 2 deferred (build mode in eval records, `retrieval.py`'s duplicate chunk reader). Real corpus: full rebuild 1,091.5 s, then "up to date" → `docs/reviews/2026-10-07-incremental-indexing.md`
- 2026-10-07 [plan] Data expansion phase 2 + v2 eval suite map (wayfinder; merges the roadmap's phase-2 and harder-evals items): v1 = the old 48 frozen as a regression gate, v2 ~50 fresh questions for headroom (target 60-75%), 10-12 companies with a same-sector pair, benchmarks as taxonomy only; frozen 2026-10-08 with all tickets decided: 12 companies, a ~56-question v2 in 7 categories, v1 gates and v2 measures, build packages 1-6 ordered in BACKLOG → `docs/plans/2026-10-07-data-expansion-phase2-map.md`
- 2026-10-07 [decision] Data expansion phase 1 done: FY2024+ cutoff with paging, 61 filings / 7,572 chunks (corpus `d703a4290869`), the 25 old chunk files byte-identical; rebuild ingest 49.5 s, chunk 2 s, index 1,258 s; offline hit@5 549/981 (was 556; 7 churn, 3 distractor, 1 scoping), 37/40; live **48/48** `20261007T072322Z` (was 46/48), 0 drops, agent `07c62fe87934` → `docs/decisions/2026-10-07-data-expansion-years.md`
- 2026-10-07 [review] Data expansion phase 1: 6 rounds (Substantial, critical core); malformed SEC JSON settled as a family in round 4, canonical-date fix in round 5; 2 deferred (`get_filing_url` accession, `xbrl_facts` dates) → `docs/reviews/2026-10-07-data-expansion-years.md`
- 2026-10-06 [plan] Data expansion, phase 1 (roadmap: data → harder evals → monorepo → admin UI → chat UI; package 6 deferred for lack of headroom): FY2024+ 10-K/10-Q for the current 5 companies via a fixed fiscal-year cutoff with paging (~61 filings, 36 new), skip already-ingested filings, corpus identity in eval reports, timed full rebuild, frozen-query harness base then a full 48 run with every drop classified → `docs/plans/2026-10-06-data-expansion-years.md`
- 2026-10-06 [decision] Close package 4 (S3 not-available answer, tool-message ticket): both S3 targets now 8/8, so it became the pltr-dividend-2019-refusal criteria fix; re-grade 29/29 as expected (old criteria 6/15 on the sample), spot-check 3/3; package 6 base runs from `e8bd2a2` → `docs/decisions/2026-10-06-close-package-4-not-available-answer.md`
- 2026-10-06 [decision] Uniform submit loop (package 3; revisits the one-retry cap): one turn rule, budget left + a shared reserve of 2, "forcing failed, the run ends", worst case MAX+2; panel 39/39 vs 39/39 clean, full run 46/48 (was 44/48), no new failures; second retry not yet seen live → `docs/decisions/2026-10-06-uniform-submit-loop.md`
- 2026-10-06 [review] Package 3, 3 rounds: 1 behaviour bug fixed (in-budget tool calls after a forced follow-up are dispatched), 1 disputed (no-turn-left branches live at reserve 0), none deferred; live panel and full-run results → `docs/reviews/2026-10-06-package-3-uniform-submit-loop.md`
- 2026-10-05 [plan] Package 3, uniform submit loop (map order 2 → 5 → 3 → 4 → 6; review S2 step 2): one rule for every extra turn (budget left + a shared reserve of 2 forced turns, worst case MAX+2 unchanged), no one-retry cap, and "forcing failed, the run ends"; 4 of 17 retried runs since package 1 were refused after the retry; base panel, candidate panel, full run → `docs/plans/2026-10-05-package-3-uniform-submit-loop.md`
- 2026-10-05 [review] Score cache review: 2 rounds, identity widened to revision/activation/device/dtype, corrupt rows and open failures degrade visibly; warm gate replay 257 s vs 3,420 s uncached → `docs/reviews/2026-10-05-rerank-score-cache.md`
- 2026-10-05 [plan] Persistent call-level cross-encoder score cache for the two replay tools (SQLite under var/, keyed by the exact ordered pairs of each predict call, never used in production retrieval) → `docs/plans/2026-10-05-rerank-score-cache.md`
- 2026-10-02 [decision] Fused-floor rerank (F=3; revisits the 08-13 MAX-of-RRF rule), windowed MaxP cross-encoder scoring with table-header carry, and strict period scoping; offline 526/901, 37/40 (was 329, 31/40); live eval pending → `docs/decisions/2026-10-02-fused-floor-rerank-and-period-scoping.md`
- 2026-10-02 [review] Package 5 retrieval, 3 rounds: 19 fixed (unknown-ticker KeyError, scope-excluded miss class, best_gold ordering, pure search_details seam), 4 deferred (header budget, date-only scoping, TypedDict, tracing helper) → `docs/reviews/2026-10-02-package-5-retrieval.md`
- 2026-10-02 [plan] Package 5 (map order 2 → 5 → 3 → 4 → 6): strict period scoping + windowed MaxP rerank with header carry + fused-floor rule (F=3), ported from the harness prototypes; offline acceptance must reproduce 526/901, 37/40 (F=0: 599, 34/40); live baseline is the 20261001T193130Z run replay-adjusted under today's gate → `docs/plans/2026-10-02-package-5-retrieval.md`
- 2026-10-01 [review] Package 2 gate rules, 3 rounds: fixed a D12a guard gap (dash-only data rows let a group label go table-wide) and two rule-R gaps (span ending partway into a later row, or into a later group's label); replay unchanged (4 recovered, 0 newly refused) → `docs/reviews/2026-10-01-gate-rules-package-2.md`
- 2026-10-01 [decision] Verbatim multi-row table quotes accepted by position (rule R, D12b) plus first-row period-header reclassification (D12a), revisiting the 09-13 exact-substring revert; replay 628 runs: 4 nvda-segment refusals recovered (incl. the 10-01 loss), 0 newly refused; live spot-check 6/8, 0 refusals → `docs/decisions/2026-10-01-verbatim-table-row-span.md`
- 2026-10-01 [plan] Package 2, gate rules (improvement map): post-package-1 re-mine (17 retries, 1 loss) rescoped it to D12a first-row header reclassification + D12b verbatim row span (rule R; the nvda-segment loss), paren-gloss either-sign coverage (6 retries) and the `10-Qs` non-claim strip (1 retry); D3 and D4/D11 deferred to Watch; plan review caught a wrong-group splice in the broader D12a rule → `docs/plans/2026-10-01-gate-rules-package-2.md`
- 2026-10-01 [review] Retrieval gold-rank harness: 2 rounds (Substantial; code-review high, arch opus, security, simplify; round 2 clean), 16 round-1 items, 11 fixed; headline fixes: rerank cause taken from the ce-best gold chunk, new `index_recall` class, other_ticker vs period_confusion by larger count; rescue-displacement class and duplicate passes deferred, private-name coupling disputed; merged `49e794f` → `docs/reviews/2026-10-01-retrieval-harness.md`
- 2026-09-30 [plan] Retrieval gold-rank harness (map S5, track B): `devtools/retrieval_replay.py` replays 512 logged queries against 247 gold rows (901 query-part pairs); V0 hit@5 329, 31/40 questions, 478 of 572 misses at rerank; V6 (strict period scoping + windowed MaxP) 469 and 37/40; combination-rule table (ce 599/34, floor3 526/37); ends with package 5's spec (floor3 live first) → `docs/plans/2026-09-30-retrieval-gold-rank-harness.md`
- 2026-09-30 [decision] Citation retry gets its own slot outside the tool budget (package 1, reverses `0ba1e5d`): panel 39/39, full run 42/48 at `9ee08ab` (`20261001T193130Z`) = previous full run; +pltr-inventory, +nvda-rd refusal, -aapl-msft-employee (retrieval miss), -nvda-segment (gate rejects a verbatim two-row table quote, backlogged); retry fired 8x, 5 passed → `docs/decisions/2026-09-30-citation-retry-own-slot.md`
- 2026-09-29 [review] `agent.py` split: 2 rounds (Substantial; code-review high, arch opus, security, simplify), 18 round-1 findings, 9 fixed, 3 deferred; headline fixes: bare-number gate tests moved to `test_citations.py`, stale `agent.X` references swept across `src/` and `tests/`, plan copy put on the template; security found all 65 functions and 25 constants AST-identical; public names, `_NO_SUBMISSION_WARNING`/`_with_unit` placement deferred; replay identical over 1212 runs → `docs/reviews/2026-09-29-agent-py-split.md`
- 2026-09-29 [plan] `agent.py` split (map Decision 13 item 4): pure move into `agent/` modules tool_args, tool_results, citations, fact_tools, calculate, dispatch, submission; `agent.py` keeps the loop (2,209 → 454 lines), tests split to match; no re-export shim, `capture_events` patches `log_event` in every agent module; AST-identical bodies, 1053 tests, snapshot unchanged → `docs/plans/2026-09-29-agent-py-split.md`
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
