# SEC Filing Research Agent — Project Context

> Handoff doc. Read this first to understand what this project is,
> what's built, what's next, and the decisions/gotchas discovered so far.

## Goal

A learning project to get hands-on with the current production AI stack —
**RAG, agentic workflows, MCP, evals, observability** — in a real domain
rather than a toy demo. Domain: **SEC EDGAR filings** (10-K / 10-Q).

Hard constraint: **free / near-zero cost**. Local models, local vector DB,
self-hosted observability, no paid APIs required.

End state: an agent that answers financial questions about a set of
companies, grounded in their SEC filings, with:
- exact citations (filing + section) for every numeric claim
- a regression eval suite that gates changes
- tools exposed via an MCP server
- full tracing of retrieval/tool calls/cost

## Stack (all free)

| Layer | Choice |
|---|---|
| Data | SEC EDGAR APIs (`data.sec.gov`, `www.sec.gov/Archives`) — no key, just a real `User-Agent` |
| Parsing | `requests` + `beautifulsoup4` + `lxml` |
| Embeddings | `sentence-transformers` (local) |
| Vector store | Chroma (simplest) or Qdrant |
| LLM | Ollama (local) or free-tier API credits |
| Agent | LangGraph / CrewAI / hand-rolled |
| MCP | official Python MCP SDK |
| Observability | Langfuse, self-hosted via Docker |

## Development workflow

**Tests are written alongside new code, not after — and nothing gets
committed with a failing test suite.** This started from Week 4 onward
(retroactively covering Weeks 2-4's pure/deterministic logic); apply it
to all new code going forward.

- Test suite: `pytest`, in `./tests/`, one file per module
  (`tests/test_chunk_documents.py` etc.). Config lives in `pyproject.toml`.
  Install dev deps with `pip install -r requirements-dev.txt`.
- **Scope, deliberately:** only pure/deterministic functions are unit
  tested (string/data transforms, grading logic, formatting) — no live
  network calls, no loading embedding/rerank models, no live Ollama
  calls. Code that inherently requires those (EDGAR HTTP calls, Chroma +
  embedding indexing, `generate_answer()`, `grade_judged()`'s actual
  LLM round-trip) is exercised by the manual runs already documented
  per-module below, not mocked into unit tests — mocking an embedding
  model's output would test the mock, not the code. The one exception:
  `grade_judged()`'s *response-parsing* logic (splitting "PASS\n<reason>"
  out of a reply) is tested with a mocked `requests.post`, since that
  parsing logic is itself pure and worth covering without needing a live
  server.
- Run the whole suite: `pytest` (or `pytest -v` for per-test output)
  from the project root.
- **Enforced via a git pre-commit hook**, not just convention: `git
  commit` runs the full suite first and refuses to commit if anything
  fails. The hook's source is tracked at `githooks/pre-commit` (git
  itself never version-controls hooks — that's a general git
  limitation, not specific to this repo), so a fresh clone needs one
  manual step to activate it:
  `cp githooks/pre-commit .git/hooks/pre-commit` (then ensure it's
  executable). Verified the hook actually blocks by committing a
  deliberately failing test and confirming the commit was rejected,
  same "test the test" principle as the eval harness's negative-control
  check.

## Companies in scope

5 tech companies, chosen because the user knows the sector and can
sanity-check answers. **`companies.json` is the source of truth** for
the ticker/name/CIK list — this table is just a human-readable summary
of it, kept for quick reference; edit `companies.json` (via
`companies.py`'s `load_companies()`), not this table, when adding a
company. Both `edgar_ingest.py` (needs the CIK) and `agent.py` (needs
the name, for its system prompt) read from it now, instead of each
keeping its own copy — they used to, under the same `COMPANIES` name
but different shapes, which is exactly the kind of duplication that
drifts silently.

| Ticker | Name | CIK (10-digit) |
|---|---|---|
| AAPL | Apple Inc. | 0000320193 |
| MSFT | Microsoft Corporation | 0000789019 |
| NVDA | NVIDIA Corporation | 0001045810 |
| CRM  | Salesforce, Inc. | 0001108524 |
| PLTR | Palantir Technologies Inc. | 0001321655 |

Last 5 10-K/10-Q filings each. To add a company: add a row to
`companies.json` (find its CIK via SEC's company search), then run
`edgar_ingest.py` → `chunk_documents.py` → `index_chunks.py` for it —
no code changes needed elsewhere.

## 8-week plan (where we are)

1. **Week 1 — EDGAR ingestion** ✅ DONE
2. **Week 2a — table→markdown + chunking** ✅ DONE
3. **Week 2b — embeddings + Chroma indexing** ✅ DONE
4. **Week 3 — hybrid retrieval (vector + BM25) + reranking + citation-grounded answers** ✅ DONE (v0 prototype — see below)
5. **Week 4 — eval harness** 🟡 SCAFFOLDING DONE, question set still only 6
   questions — see below. Growing it to 30-50 was explicitly deferred
   (twice) in favor of moving to Week 5.
6. **Week 5 — agent layer + tool calling** ✅ DONE (v0 — see below) ⬅️
   **loop back and grow the Week 4 question set before Week 6**, ideally
   including comparison-style questions (see Week 5's synthesis finding)
7. Week 6 — expose tools as an MCP server
8. Week 7 — guardrails (no numeric claim without citation), retry/backoff,
   rate limits, Langfuse tracing
9. Week 8 — polish + write-up

Note the deliberate ordering: **evals come before the agent**, so there's a
way to measure whether each change helps before iterating on agent
behavior. **This project deviated from that ordering** — Week 5 was built
on a 6-question baseline instead of the full 30-50 — a conscious tradeoff
to keep momentum, not an accident. Worth being honest that this makes it
harder to say precisely whether Week 5 "helped" in any measured sense;
Week 5's own manual testing already surfaced a real quality gap (below)
that a proper eval set would very likely have caught faster.

## Code written so far

### `companies.py` + `companies.json` — shared ticker/company registry

Single source of truth for the ticker → {name, CIK} lookup. Added after
`agent.py`'s ticker→name dict and `edgar_ingest.py`'s ticker→CIK dict
were noticed to be two separately-hardcoded copies of the same list
(under the identically-named `COMPANIES` variable, which made the
duplication easy to miss). `load_companies()` reads `companies.json`
fresh on every call — no caching — since it's small and rarely changes,
and not caching means an edit takes effect without restarting anything.
Both `edgar_ingest.py` and `agent.py` now import `load_companies()`
instead of hardcoding their own list.

### `edgar_ingest.py` (Week 1) — working

Pulls filings and splits each into prose + tables.

- Fetches filing list from `https://data.sec.gov/submissions/CIK{cik}.json`
- Downloads primary doc from `https://www.sec.gov/Archives/edgar/data/{cik_nozero}/{accession_nodash}/{primary_doc}`
- Parses HTML, extracts each `<table>` separately, and **replaces it in the
  text stream with a `[TABLE_n]` marker** so position is preserved
- Empty/layout-only tables are dropped with no marker

Outputs per filing, under `./data/<TICKER>/`:
- `<accession>_meta.json` — form, dates, accession, ticker, cik, counts
- `<accession>_text.txt` — prose with `[TABLE_n]` markers in place
- `<accession>_tables.json` — `[{"table_index": n, "rows": [[cell,...],...]}]`

**Gotchas already hit and fixed:**
- SEC blocks requests without a descriptive `User-Agent` (format: `Name email@example.com`) — this is the #1 day-one blocker
- Windows defaults to cp1252 and crashes on SEC checkbox glyphs (☒ / ☐, U+2612). All file writes must pass `encoding="utf-8"`
- SEC iXBRL filings are XHTML; bs4 emits `XMLParsedAsHTMLWarning`. Harmless, suppressed deliberately (we want the HTML parser for clean text/table extraction)
- Rate limit: sleep ~0.3s between requests, stay under 10 req/sec

### `chunk_documents.py` (Week 2a) — written, needs final verification run

Reconstructs each filing and chunks it.

1. `strip_leading_metadata()` — cuts hidden Inline XBRL taxonomy junk
   (`us-gaap:...Member`, raw dates) that sits *outside* any `<table>` tag and
   so survives Week 1's stripping. Anchors on the boilerplate phrase
   `"SECURITIES AND EXCHANGE COMMISSION"`, which appears in virtually every
   10-K/10-Q — chosen over per-company hardcoding.
2. `clean_row()` — SEC HTML splits currency symbols and padding into separate
   cells (`["Americas", "$", "45,781", "", "", ...]`). Drops empties, merges
   `$`/`%` with the adjacent value.
3. `table_to_markdown()` — converts to a markdown table.
4. `reconstruct_document()` — replaces each `[TABLE_n]` marker with the
   markdown table, wrapped in `<TABLE>...</TABLE>` tags so the chunker can
   treat it as atomic. **This is the whole point of the marker scheme:** the
   prose that says "the following table shows net sales by segment" must end
   up in the same chunk as the actual numbers, or retrieval on
   "why did Europe sales increase" misses the figures.
5. `is_exhibit_index_table()` — drops boilerplate exhibit-index tables
   (detected by header columns: "Exhibit Number" + "Incorporated by
   Reference"/"Filing Date"). These are pure filing-administration metadata
   with no financial content, and are structurally near-identical across
   companies — leaving them in risks polluting top-k retrieval with
   format-similarity matches. Filtered at the *table* level, not by dropping
   Item 15 wholesale, so the financial-statement index and auditor's report
   are preserved.
6. `split_into_blocks()` / `split_prose_block()` — splits into atomic blocks.
   Tables are never broken. Oversized prose falls through a cascade:
   blank-line paragraphs → single newlines → sentence boundaries → hard slice.
7. `chunk_blocks()` — greedily accumulates blocks to ~2000 chars (3000 hard
   cap), with ~200-char overlap. Drops leftover overlap-only fragments.

Outputs `./chunks/<TICKER>/<accession>_chunks.jsonl`, one JSON object per line:
```json
{"text": "...", "metadata": {"ticker","form","filingDate","reportDate","accessionNumber","chunk_index","contains_table","char_length"}}
```

**Gotchas already hit and fixed:**
- **Filings are not structurally uniform.** AAPL/MSFT/PLTR have blank-line
  paragraph breaks; NVDA's Business and Risk Factors sections did not, so the
  whole section came through as ONE 47,000–121,000 char block. Hence the
  cascading fallback splitter. This is a good write-up talking point.
- Multi-row table headers get mangled — SEC uses merged cells / colspan for
  headers like "Three Months Ended" spanning columns, then dates below.
  Week 1's cell-text extraction doesn't preserve colspan, so "first row =
  header" flattens them. **Known, accepted limitation** — the row data and
  numbers are accurate, which is what matters for retrieval. Documented
  rather than fixed.
- Cosmetic page header/footer noise (`Apple Inc. | Q3 2026 Form 10-Q | 13`)
  remains. A generic non-hardcoded regex for it is in the file, commented
  out. Deliberately left off: low-signal, doesn't meaningfully hurt
  embeddings, not worth per-company effort yet.
- `is_exhibit_index_table()`'s original header match (`"exhibit number"`,
  `"exhibit no"`) missed 15 of 25 filings' exhibit tables. Same root cause
  as the multi-row-header limitation above: colspan headers like "Exhibit"
  + "Number" collapse to `"ExhibitNumber"` with no space during cell-text
  extraction. Fixed by also matching against a whitespace-stripped copy of
  the header region.

### `index_chunks.py` (Week 2b) — working

Embeds every chunk and loads them into a persistent local Chroma collection.

- Model: `BAAI/bge-small-en-v1.5`, not the more commonly-cited
  `all-MiniLM-L6-v2`. BGE is trained for **asymmetric** retrieval (short
  query → long passage), which matches the actual use case — a financial
  question against a filing chunk — better than a general sentence-
  similarity model. The tradeoff: queries need an instruction prefix
  (`"Represent this sentence for searching relevant passages: "`) at
  search time; passages are indexed *without* it. Getting this backwards
  (or applying it to both/neither) measurably hurts retrieval for this
  model family.
- Embeddings are L2-normalized (`normalize_embeddings=True`) and the
  collection is created with `hnsw:space: cosine`.
- Collection is dropped and rebuilt on every run (rather than incrementally
  upserted) so re-running after a chunking fix — like the exhibit-index fix
  above — can't leave stale/duplicate rows behind.
- Document id = `{accessionNumber}_{chunk_index}` — globally unique and
  stable across re-runs.
- Full metadata dict is preserved on every point (ticker, form, filingDate,
  reportDate, accessionNumber, chunk_index, contains_table, char_length),
  needed for filtered retrieval and citations later.

### `query_chunks.py` (Week 2b) — working

Runs a preset list of 15 financial questions (numeric/table-seeking,
qualitative/narrative, domain-vocab, one deliberately vague) against the
Chroma collection and prints top matches with similarity score, ticker,
form, table/prose flag, and a text preview — for human eyeballing, not
scoring. `python query_chunks.py "custom question" --ticker MSFT --n 5`
for ad-hoc queries.

### `retrieval.py` (Week 3) — working

Hybrid retrieval: BM25 (lexical) + Chroma (vector) → Reciprocal Rank
Fusion → cross-encoder rerank. This is the module future code (Week 4
eval harness, Week 5 agent) should import (`hybrid_search()`) rather than
querying Chroma directly.

- **Why hybrid, concretely:** Week 2b's manual sanity queries surfaced a
  real miss — "What is Salesforce's remaining performance obligation?"
  retrieved zero CRM chunks in the top 3 on pure vector search, despite
  CRM's filing stating "remaining performance obligation" almost
  verbatim. Embeddings can smear an exact term-of-art match across many
  "semantically similar" but wrong chunks; BM25 catches the literal
  phrase. After adding BM25 + fusion, all top-5 results for that query
  are CRM chunks about RPO — one containing the actual $72.4B figure.
- BM25 index is built in-process from the same `./chunks/*.jsonl` files
  `index_chunks.py` reads (`_load_bm25_index()`), so the two retrieval
  paths can't drift out of sync. Tokenizer is deliberately simple
  (lowercase, no stemming) — financial terms of art are exact phrases
  where stemming risks merging distinct terms rather than helping.
- **Fusion via RRF, not raw score averaging:** BM25 scores and cosine
  similarities live on incomparable scales, so blending them directly
  would let whichever method happens to produce larger numbers dominate.
  Reciprocal Rank Fusion (`1/(k + rank)`, summed across each ranked list
  a document appears in, `k=60`) fuses rank *position* instead, which is
  scale-free.
- **Reranking:** the fused candidate pool (~25-40 chunks) is rescored
  with `cross-encoder/ms-marco-MiniLM-L-6-v2`, which scores each
  (query, passage) pair jointly rather than independently embedding
  them. Cross-encoders are too slow to run over the full 3,207-chunk
  corpus but are cheap over a few dozen candidates, and are meaningfully
  more accurate at the top of the ranking — which is what matters most
  since only the top few chunks become LLM context.
- **Reranker bug, root cause, and fix (found via `eval_harness.py`'s
  8-question run — see that section below for the failing eval case):**
  the cross-encoder was demoting a confirmed-correct chunk (MSFT
  headcount, "we employed approximately 223,000 people... on a
  full-time basis") out of the top 10 entirely, despite it ranking #3
  of 48 in the fused BM25+vector ranking. **Initial hypothesis (512-token
  truncation cutting off the relevant sentence) was checked directly
  against the cross-encoder's own tokenizer and ruled out** — the full
  sequence was only 489 tokens, under the 512 limit, with the relevant
  text demonstrably present in the decoded tokens. **Real cause:**
  `ms-marco-MiniLM-L-6-v2` is trained on short (~350 char), single-topic
  MS MARCO passages, and genuinely scores this long (~2,700 char),
  multi-topic chunk (device competition → gaming → search ads → human
  capital) poorly even though the relevant content is present —
  confirmed by the numbers: rank #3/48 by fused score, but rank ~43/48
  by raw cross-encoder score. **First fix attempt (rejected):** treat
  the cross-encoder ranking as a third signal and re-run
  `reciprocal_rank_fusion()` summing it with the original fused rank.
  Implemented and empirically tested — did NOT fix it, because several
  competing chunks were "decent" (not great, not terrible) by both
  signals, and their summed scores beat the target's "great fused rank +
  terrible rerank rank" combination. **Fix that worked:** `rerank()`'s
  ranking math was extracted into `_combine_fused_and_rerank(candidates,
  cross_encoder_scores, top_n)`, which scores each candidate as the
  **MAX** (not sum) of its two RRF contributions —
  `max(1/(k+fused_rank), 1/(k+rerank_rank))` — so a candidate that's
  excellent by even one signal survives, rather than needing to be
  decent by both. Verified via: a standalone script showing the target
  chunk moving to rank ~5 under MAX scoring; a live CLI re-run
  (`python retrieval.py "full-time employees as of June 30, 2026"
  --ticker MSFT --n 5`) showing it now at rank 4 of 5 (previously absent
  from the top 10-48); regression checks against two previously-working
  queries (CRM RPO, AAPL employee count) showing no change; new unit
  tests in `tests/test_retrieval.py` including a direct regression test
  mirroring this exact failure pattern (great-by-one-signal,
  terrible-by-the-other); and the full eval suite re-run (see
  `eval_harness.py` section) showing the target question flip from FAIL
  to PASS with no other regressions. `main()`'s CLI score display now
  reads `combined_score` (renamed from `rerank_score`).
- CLI: `python retrieval.py "question" [--ticker MSFT] [--n 5] [--no-rerank]`.

### `answer.py` (Week 3) — working, v0 prototype

Retrieves via `hybrid_search()`, feeds numbered excerpts to a local LLM
through Ollama with a "cite everything or refuse" system prompt, prints
the answer plus a citation key mapping each `[n]` back to a real filing
(ticker/form/reportDate/accessionNumber).

- **LLM: `qwen2.5:7b-instruct` via Ollama**, not the smaller `qwen3.5:4b`
  that happened to already be pulled. Chose to pull a stronger model
  rather than default to what was on hand — a 4B model's weaker
  instruction-following on strict citation formatting would have made it
  hard to tell, in Week 4's evals, whether a failure was a retrieval
  problem or a model-capability problem. Runs locally, zero cost, no
  external API — this machine's GPU (Quadro P1000, 4GB VRAM) doesn't
  fully fit a 7B model, so Ollama partially offloads to CPU; slower per
  query but fine at this project's query volume.
- Requires `ollama serve` running locally (defaults to
  `http://localhost:11434`) with `qwen2.5:7b-instruct` pulled.
- **This is explicitly a v0 prototype, not the final agent** (that's
  Week 5). Grounding is currently enforced only by prompt instruction —
  nothing here parses the output to verify every claim actually carries
  a `[n]` marker, or that a cited number matches the source text
  character-for-character. That verification gap is exactly what Week
  4's eval suite should be built to catch, per this project's
  evals-before-agent ordering.
- Spot-checked both success and refusal paths: correctly cites only the
  one CRM chunk (of 5 retrieved) that actually contains RPO figures
  rather than citing all 5 indiscriminately; correctly refuses to
  fabricate a 2019 dividend figure for PLTR when asked, stating the
  excerpts don't cover that period instead of guessing.
- CLI: `python answer.py "question" [--ticker CRM] [--k 5]`.

**Residual finding — not a bug, a scoping note for Week 5:** the
employee-count query (Gap 2, above) still doesn't reliably surface the
right chunk in an *unfiltered* top-5 across all 5 companies, even after
hybrid search + reranking — some off-topic PLTR prose about "employees"
in a risk-factor context outranks AAPL/MSFT's real headcount
disclosures. But filtered to the correct ticker, the real answer ranks
#1 by a wide margin every time. This means the retrieval layer itself is
sound; what's missing is *company disambiguation* — figuring out which
ticker(s) a question is actually about before calling `hybrid_search()`.
That's squarely a Week 5 agent-layer responsibility (tool-calling/query
routing), not something to bolt onto the retrieval module.

### `eval_harness.py` + `eval_questions.jsonl` (Week 4/5) — scaffolding done, 8 questions, real findings surfaced

Runs every question in `eval_questions.jsonl` through **`agent.run_agent()`**
(switched from `answer.generate_answer()` as of Week 5 — the agent resolves
which ticker(s) a question is about itself, matching real usage, and lets
comparison questions exercise the multi-tool-call path) and grades the
result, so changes can be measured against a saved baseline instead of
eyeballed. A question's `"ticker"`/`"tickers"` field is now purely
documentation for a human skimming the file — it's not passed into the
call. Three grading strategies, chosen per-question by a `"type"` field:

- **`"numeric"` — exact-match, no LLM involved.** `extract_numbers()`
  regex-scans the generated answer for every number-like token ($, commas,
  decimals, unit words), normalizes each to a comparable scale (percent
  stays its own category — 20 raw and 20% must never compare equal;
  `billion`/`million`/`thousand` become multipliers on a shared "scale"
  category), and passes if *any* extracted number lands within ~1%
  relative tolerance of the question's `expected_value`. Deterministic
  and free to run.
- **`"comparison"` — like `"numeric"`, but for multi-company questions.**
  `expected` is a list of `{"ticker", "expected_value", "expected_unit"}`
  entries; passes only if *every* entity's value is found, via
  `grade_numeric()` run once per entity. Added specifically to catch, by
  design, an answer that correctly retrieves multiple companies' figures
  but only reports one of them. Known limitation: doesn't check that a
  found number is *attributed* to the right entity, only that both
  numbers appear somewhere in the text — good enough for the failure mode
  it was built to catch, not a full faithfulness check.
- **`"judged"` — LLM-as-judge, for qualitative or refusal questions**
  where there's no single correct number to diff against. A second Ollama
  call is given the question, the answer, and a short pass/fail
  `"criteria"` string, and returns PASS/FAIL + a one-sentence reason.
  `temperature: 0.0` here (stricter than generation's `0.1`) — a grader
  should be as consistent as possible run-to-run.
- Every graded answer also gets a citation-marker check (`[\d+]` regex)
  reported alongside the pass/fail, independent of question type.
- Each run's full results are saved as timestamped JSON under
  `./eval_results/` — tracked in git, since the whole point is comparing
  runs over time.

**Sanity-checked the grading itself, not just the pipeline:** ran a
4-question negative-control set with deliberately wrong expected values
and inverted criteria, and confirmed all 4 correctly FAIL.

**Found a bug in `num_ctx` before any of this eval work meant anything:**
the very first live run against `agent.py` timed out, and `ollama ps`
showed `context_length: 4096` — Ollama's default, far too small once a
tool call returns 5 chunks (~3000 chars each) plus the system prompt, let
alone a comparison question's *second* tool call stacking on top. Fixed
by setting `"num_ctx": 8192` explicitly in every Ollama call
(`agent.py`, `answer.py`, `eval_harness.py`'s judge) — worth flagging
because this could easily have been misdiagnosed as a pure model-
capability limitation instead of silent context truncation.

**8-question run, pre-fix: 6/8 passed, 8/8 cited** (saved at
`eval_results/20260815T030212Z.json`). Both failures were investigated
down to a root cause, not left as "the model got it wrong":

1. **`aapl-msft-employee-comparison` FAILED — a real, diagnosed retrieval
   bug, not a model-capability problem.** The agent stated a fabricated
   MSFT employee count (verified: the exact string it output doesn't
   appear anywhere in the source data) attached to a citation for a real
   but unrelated chunk (share-repurchase/dividend tables). Root cause,
   confirmed by direct comparison: the correct chunk (containing
   "we employed approximately 223,000 people... on a full-time basis")
   ranks **#3** in the fused BM25+vector results for the agent's actual
   query — comfortably inside the top 5 — but **the cross-encoder
   reranker demotes it out of the top 10 entirely**, promoting several
   irrelevant financial tables instead. The model never saw the right
   number, so it filled the gap with a plausible-looking one. This is a
   `retrieval.py` reranking-quality bug, reproduced on demand via
   `python retrieval.py "full-time employees as of June 30, 2026"
   --ticker MSFT --n 15 --no-rerank` vs. the same command with reranking
   on. **Fixed — see the `retrieval.py` section above (`_combine_fused_and_rerank`,
   MAX-of-RRF-contributions).**
2. **`pltr-dividend-2019-refusal` FAILED — a grading-criteria problem,
   not an agent bug.** The agent inferred "Palantir did not pay a
   dividend in 2019" from the filing's actual statement ("No dividends
   have been declared as of December 31, 2025") — a logically valid
   inference (if none had *ever* been declared by 2025, none were
   declared in 2019), not a fabrication. The eval criteria was written
   against the more conservative `answer.py` behavior and didn't
   anticipate the agent reasoning this confidently forward from a stated
   fact. The criteria needs revisiting, not the agent. **Still open.**

**This is exactly the outcome the "get real signal before deciding
anything" plan was for:** neither failure supports swapping to a bigger/
cloud model as the fix — one is a reranker bug, the other is a test-
design issue. Concrete argument for finishing the retrieval-quality fix
*before* spending any more effort on model choice or company/history
expansion.

**8-question re-run, post reranker-fix: still 6/8 passed, 8/8 cited**
(saved at `eval_results/20260815T223031Z.json`). The reranker fix worked
exactly as intended — `aapl-msft-employee-comparison` now **PASSES**
(MSFT's 223,000 figure is retrieved and correctly attributed). But a
different question flipped from PASS to FAIL, keeping the total at 6/8:

3. **`aapl-msft-tax-rate-comparison` FAILED (new) — a synthesis bug, not
   a retrieval bug.** The agent reported MSFT's effective tax rate for
   "the three months ended December 31, 2025" as 18%, when the correct
   figure (verified in the source filing) is 20%; 18% is actually the
   rate for a *different* period (nine months ended March 31, 2026) that
   appeared in a separate retrieved chunk. Confirmed this is NOT a
   reranker regression: running the agent's likely retrieval query
   directly (`python retrieval.py "Microsoft effective tax rate three
   months ended December 31, 2025" --ticker MSFT --n 5`) puts the
   correct chunk (20%, explicitly for "three and six months ended
   December 31, 2025") at **rank 1**. The correct number was sitting
   right there in context. Notably, the *standalone* version of this same
   question (`msft-tax-rate-q2fy26`, no comparison) still passes and
   correctly discriminates between all three quarters' rates (20%/19%/18%)
   present in its context, explicitly reasoning "for the quarter
   specifically asked... 20%." So the model *can* do this disambiguation
   — it just doesn't reliably do it when the prompt is also juggling a
   second company's figures at the same time. Reads as a genuine
   qwen2.5:7b-instruct synthesis-reliability limit under multi-entity
   comparison load, distinct from (and not fixed by) the retrieval-side
   reranker fix. **Not yet fixed.** Also a reminder that `agent.py` runs
   generation at `temperature: 0.1`, not 0 — some run-to-run variance in
   exactly which failure surfaces is expected.

**Net effect of the reranker fix:** proven to fix the specific bug it
targeted (verified three ways: standalone retrieval CLI check, live eval
re-run, new unit tests), with no regression on the previously-passing
questions. The pass count staying at 6/8 is not the fix "not working" —
it's a different, previously-masked bug (comparison-synthesis reliability)
becoming visible now that the retrieval layer is no longer the
dominant failure mode. Worth carrying into any future model-swap
decision: with retrieval now solid, remaining comparison-question
failures are a cleaner signal on the *model's* synthesis quality.

**Comparison-synthesis bug — root cause and fix (see `agent.py` section
below for the code).** Reproduced `aapl-msft-tax-rate-comparison` live
with `agent.py --verbose` and found it was actually two compounding
issues, not one:

1. **Query-formulation fragility.** The agent's own tool-call query for
   MSFT was `'effective tax rate Microsoft Corporation Q4 2025'` — a
   garbled, self-invented period label — which buried the correct
   Dec-2025 10-Q chunk near the bottom of the MSFT results while three
   *annual* 10-K tax-rate chunks crowded the front. **First attempted
   fix (system prompt rule: "include the exact date in your query")
   partially backfired** — it fixed MSFT (whose filings restate exact
   dates in prose: "three and six months ended December 31, 2025") but
   broke AAPL (whose filings describe periods as "the third quarter of
   2026," never repeating the literal calendar date — the literal date
   only appears in unrelated financial-statement table headers, which
   the more literal query then over-matched instead). No single
   query-phrasing instruction generalized across both companies' filing
   styles. **What actually worked, tested directly against both
   companies:** using the user's own original question text as the
   search query (untouched by the model) got the correct chunk to rank
   #1 for *both* AAPL and MSFT, standalone and in the comparison. Implemented
   as a `_resolve_search_args()` change: the model's own `query` text is
   now only trusted on a *retry* against a ticker already searched once
   in the conversation (`searched_tickers` tracks this in `run_agent()`)
   — the first search against each company always uses the original
   question verbatim, regardless of what query the model supplies.
2. **Same-sentence current-vs-prior-year confusion.** Even after query
   formulation was fixed and the correct chunk was retrieved prominently,
   the model still sometimes misread it: the source sentence is "Our
   effective tax rate was 20% for... December 31, 2025, and 18% for...
   December 31, 2024" — one sentence, two periods — and the model
   grabbed the prior-year clause instead of the current one. This is a
   comprehension issue, not a retrieval one; no chunk-ranking fix can
   address it. Fixed by sharpening the system prompt's period-matching
   rule with a concrete same-sentence example ("the rate was 20% for the
   current quarter, and 18% for the same quarter last year") rather than
   only warning about tables. Verified stable across 3 repeated runs of
   the same question (temperature is 0.1, so some sampling variance is
   expected; all 3 completed runs got the current-period value right).

**Final 8-question re-run, both fixes applied: 7/8 passed, 8/8 cited**
(saved at `eval_results/20260816T073528Z.json`) — the best result yet.
Both `aapl-msft-tax-rate-comparison` and `aapl-msft-employee-comparison`
pass, the standalone `msft-tax-rate-q2fy26` regression introduced by an
earlier interim version of the fix (see below) is resolved, and none of
the other four questions regressed. The sole failure,
`pltr-dividend-2019-refusal`, is the same already-documented
grading-criteria issue — confirmed the agent's actual answer text is
unchanged from prior runs (still correctly refuses to state a dividend
figure); this run's judge flagged it for an unrelated reason ("provides
specific EPS figures, which implies dividend information indirectly" —
EPS and dividends aren't the same thing, a judge-quality quirk, not an
agent behavior change).

**A worthwhile detour, kept here rather than erased, because the
mid-course correction is itself the lesson:** an interim version of this
fix (system-prompt rules only, no query override) got
`aapl-msft-tax-rate-comparison` to pass but broke the previously-solid
standalone `msft-tax-rate-q2fy26` — removing the query-precision
instruction (because it had broken AAPL) let MSFT's query formulation
drift vague again, and with only one search's worth of results (5 chunks,
vs. 10 in a comparison question) there was no second search's results to
fall back on, so the correct chunk missed the top 5 entirely. This is
what motivated moving the fix from "tell the model how to phrase its
query" (fragile, company-dependent) to "don't let the model's phrasing
matter for the first search" (the `_resolve_search_args` override) —
each version was tested against the real failing case before being
accepted, not assumed correct from reasoning alone.

**Explicitly deferred:** growing this to the full 30-50 question,
FinanceBench-style set — that requires going back into the actual
filings to find and verify ground truth, which is real research work,
not scaffolding.

**Considered and deferred:** RAGAS/DeepEval (open-source RAG eval
libraries with built-in *faithfulness* metrics — do the answer's claims
actually trace back to the retrieved chunks). Notably, this project's own
`grade_comparison()` just caught exactly the kind of error a faithfulness
metric is designed for (a citation pointing at content that doesn't
support the claim) — reinforces that this is worth adding as a *third*
grading path once the question set grows, rather than a purely
theoretical nice-to-have.

### `agent.py` (Week 5) — v0 tool-calling agent

`answer.py` (Week 3) is a single-shot pipeline: the caller must already
know the ticker (`--ticker CRM`). That's exactly what Week 3's residual
finding flagged as out of scope for the retrieval layer — an unscoped
question like "how many employees does the company have" doesn't
reliably surface the right chunk, even though retrieval is fine once
properly scoped. `agent.py` closes that gap by giving the LLM a callable
`search_filings` tool (wrapping `retrieval.hybrid_search`) instead of
us pre-fetching context — the model decides what to search, which
ticker to restrict to, and whether to search again, rather than the
caller deciding upfront.

- **Real tool-calling via Ollama's OpenAI-style `tools` API**, not a
  hand-rolled "parse the model's text for a command" hack. Verified the
  actual wire format empirically before writing the loop, since getting
  this wrong would fail silently: `tool_calls[].function.arguments`
  comes back as an already-parsed dict (not a JSON string, unlike
  OpenAI's API), and the follow-up tool-result message only needs
  `{"role": "tool", "content": ...}` — no `tool_call_id` required.
- **The model doesn't reliably fill every schema field.** Observed
  qwen2.5:7b-instruct calling `search_filings` with only `ticker`, no
  `query`, despite `query` being marked `"required"` in the schema.
  `_resolve_search_args()` falls back to the original question in that
  case rather than searching on an empty string or crashing — schemas
  are a strong hint to the model, not a guarantee.
- **The model's own search query is only trusted on a retry, not the
  first search against a company** (`_resolve_search_args()`'s
  `searched_tickers` parameter, `run_agent()`'s `searched_tickers` set).
  Added after diagnosing a real comparison-question failure down to the
  model's self-written first-pass queries: they were prone to being
  either too vague (dropping the exact date/period a question named,
  burying the correct chunk among decoys) or, when the system prompt
  instead told the model to include exact dates, too literal (a query
  containing "June 27, 2026" over-matched an unrelated financial-
  statement table that repeats that date as a column header, instead of
  the tax-rate paragraph that never repeats it in prose). Different
  companies phrase the same fact differently in their own filings, so no
  single query-phrasing instruction generalized. What did generalize,
  tested directly: using the user's own original question as the query
  retrieved the correct chunk for every case tried. The first search
  against each not-yet-searched ticker now always uses the original
  question verbatim; a genuine retry (the model deciding its first
  search against an already-searched company came up short) still gets
  to use the model's own reworded query. See `eval_harness.py`'s section
  below for the full diagnosis and evidence.
- **Company name resolution is baked into the system prompt** (a static
  ticker → company-name table for the 5 covered companies), not a
  separate tool call — five static facts don't justify a round trip,
  and every model tried so far already knows "Salesforce" → CRM
  unprompted; the prompt just makes the covered-company scope explicit.
- **Citations stay globally numbered across multiple tool calls**
  within one conversation (`_format_results_block(results,
  start_index)` continues numbering from where the previous call left
  off) — necessary so a comparison question's final answer can cite
  `[1]`-`[5]` from the first company's search and `[6]`-`[10]` from the
  second without renumbering collisions.
- `MAX_TOOL_ITERATIONS = 6` as a basic runaway-loop guardrail — full
  guardrails (rate limits, retry/backoff) are Week 7's job, this is just
  "don't loop forever."
- **Known simplification:** no deduplication if two tool calls surface
  the same chunk. Cosmetic (a duplicate citation), not a correctness
  issue — noted rather than fixed.

**Manually verified two real scenarios** (no live-model integration
tests yet — deferred, see Development workflow section):
- *"How many full-time employees does Apple have?"* (no `--ticker`
  flag, company named in prose) → agent called
  `search_filings(query="full-time employees", ticker="AAPL")` on its
  own and answered correctly with citation — this is the direct fix for
  Week 3's residual finding.
- *"Compare Apple's and Microsoft's effective tax rates."* → agent
  correctly called the tool twice (once per company) and citation
  numbering stayed consistent ([1]-[5] AAPL, [6]-[10] MSFT), but the
  final answer didn't actually compare — it discussed MSFT at length and
  never stated Apple's numbers. **Initial hypothesis (recorded here at
  the time) was a pure synthesis/generation-quality gap.** That
  hypothesis turned out to be incomplete: the eval harness's follow-up
  investigation (see `eval_harness.py`'s section below) found Ollama was
  silently running with a 4096-token context window — likely truncating
  content mid-conversation for a two-tool-call question — *and*
  separately found the cross-encoder reranker actively demoting correct
  chunks out of the top results for at least one real query. Both are
  concrete, fixable pipeline bugs that could each independently explain
  what looked like a synthesis failure. **Lesson worth keeping:** a
  single manually-observed failure with no chunk-level or context-level
  inspection can look like "the model isn't smart enough" when the real
  cause is upstream — this is why the eval harness's evidence-based
  diagnosis (grep the source data, compare reranked vs. non-reranked
  output) mattered more than the original hypothesis.

## Verified working

Ingestion + chunking have been run across all 5 companies (25 filings,
3,207 chunks total). Confirmed:
- `grep -r "us-gaap:" ./chunks/` returns nothing
- No exhibit-index table leakage (down from 15 leaked filings to 0)
- Only 4 chunks exceed the 3,000-char soft target, max 4,497 — all 4 are
  large `<TABLE>` blocks kept atomic by design, not a bug
- Embedding + Chroma indexing runs end-to-end (3,207/3,207 documents loaded)

**Manual retrieval sanity check (15 queries) — mostly strong, two known gaps:**
- Numeric/table queries (net sales, buybacks, cash balances) correctly
  retrieve the right company's table, usually as the #1 hit
- Qualitative queries (litigation, AI risk, supply chain) correctly retrieve
  topically relevant prose
- **Gap 1:** "Salesforce's remaining performance obligation" retrieves no
  CRM chunk in the top 3 (MSFT/NVDA prose instead), despite CRM disclosing
  RPO prominently. Likely needs lexical/BM25 matching on the exact phrase,
  not just semantic similarity — a concrete case for Week 3's hybrid search.
- **Gap 2:** "How many full-time employees does the company have?" scores
  noticeably lower (~0.63 vs ~0.7–0.85 elsewhere) and top-3 results aren't
  actually about headcount. Needs investigation in Week 3 — unclear yet
  whether it's a phrasing issue or the Human Capital sections are poorly
  chunked/embedded.

## Immediate next steps

**Reranker bug: FIXED** (see `retrieval.py` and `eval_harness.py`
sections above) — `_combine_fused_and_rerank()` now takes the MAX of the
fused-rank and rerank-rank RRF contributions per candidate. Verified via
unit tests, a live CLI regression check, and a full eval re-run
(`aapl-msft-employee-comparison` flipped FAIL → PASS, no regressions on
previously-passing questions).

**Comparison-synthesis bug: FIXED** (see `agent.py` and `eval_harness.py`
sections above). Root cause was two compounding issues, not one: the
agent's self-written search queries were unreliable in company-dependent
ways (too vague for MSFT, too literal for AAPL once "include the exact
date" was tried), and separately the model sometimes misread a
current-vs-prior-year figure sitting in the same sentence. Fixed by (1)
having `_resolve_search_args()` ignore the model's own query on the
first search against each company and always use the original question
instead (a retry against an already-searched company still uses the
model's query), and (2) sharpening the system prompt's period-matching
rule with a concrete same-sentence example. Final eval: **7/8 passed,
8/8 cited** (`eval_results/20260816T073528Z.json`) — both target
comparison questions pass, no regressions elsewhere.

**Top priority now — revisit the PLTR refusal question's grading
criteria.** The only remaining failure, and unrelated to anything fixed
this session. Not an agent bug: the agent's answer is unchanged across
every run so far (correctly refuses to state a 2019 dividend figure,
grounded in real citations) — it's the LLM-as-judge that's inconsistent
about whether this counts as satisfying the criteria (one run's judge
even flagged unrelated EPS figures as if they implied dividend
information). Worth either rewording the criteria to be less ambiguous
for a judge, or replacing `"judged"` grading with a `"numeric"`-style
refusal check for this question (e.g. assert no dollar figure resembling
a per-share dividend appears at all) so it doesn't depend on judge mood.

**Second priority — now that both diagnosed retrieval/synthesis bugs are
fixed, this is a natural point to decide on `qwen2.5:7b-instruct` vs. a
stronger/cloud model for generation**, if a future eval run (post
question-set growth) keeps surfacing comprehension-level failures that
prompt tuning can't reach. Not urgent right now — the last eval run
found nothing that pointed at a capability ceiling, only fixable pipeline
issues — but worth keeping in mind as the next lever if that changes.

**Then — grow `eval_questions.jsonl` beyond 8 questions**, now informed
by real findings instead of guessing what might break:
- Go back into the actual filings to find and verify ground-truth figures
  — real research, not guessing plausible-looking numbers
- Cover all 5 companies and both 10-K/10-Q forms more evenly (currently
  AAPL/CRM/MSFT-heavy)
- More comparison-style questions, now that `grade_comparison()` exists
  and is proven to catch real failures — including ones that require
  correct *attribution* (which entity a number belongs to), since the
  current comparison grading doesn't check that yet
- A few ambiguous/no-company-context questions, to verify `agent.py`'s
  disambiguation holds up beyond the cases spot-checked so far
- Decide whether `answer.py` (Week 3) stays as a simpler fallback/
  baseline or gets retired — `agent.py` is a strict superset of what it does

**Then Week 6 — expose tools as an MCP server**, wrapping the same
`search_filings` tool `agent.py` already defines.

## Design principles to carry forward

- **Citations are non-negotiable.** In finance, "trust me" isn't good enough.
  Every numeric claim must trace to a specific filing + section, or the agent
  refuses. This becomes a hard guardrail in Week 7.
- **Evals before agent.** Measure first, then iterate.
- **Narrow scope, checkable outputs.** Numeric answers with exact figures are
  far easier to grade objectively than open-ended summaries.
- **Document failure modes.** The write-up value is in "here's what broke and
  how I found it," not "here's clean code."
