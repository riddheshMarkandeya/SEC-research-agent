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
5. **Week 4 — eval harness** 🟡 GROWING, 16 questions so far (see below) —
   started at 6, deferred growth twice in favor of Week 5, then grown to
   16 in a first incremental pass after Week 5's bugs were fixed. Still
   short of the full 30-50 FinanceBench-style target.
6. **Week 5 — agent layer + tool calling** ✅ DONE (v0 — see below)
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

Single source of truth for the ticker → {name, CIK, fiscal_year_end_month}
lookup. Added after `agent.py`'s ticker→name dict and `edgar_ingest.py`'s
ticker→CIK dict were noticed to be two separately-hardcoded copies of the
same list (under the identically-named `COMPANIES` variable, which made
the duplication easy to miss). `load_companies()` reads `companies.json`
fresh on every call — no caching — since it's small and rarely changes,
and not caching means an edit takes effect without restarting anything.
Both `edgar_ingest.py` and `agent.py` now import `load_companies()`
instead of hardcoding their own list.

**`fiscal_year_end_month` (added for `period_labels.py`, below) is a
real, if currently low-probability, assumption worth flagging
explicitly:** it assumes each company's fiscal year end is fixed
forever. In reality a company *can* change it (via a transition-period
filing), and if that ever happened here without this field being
updated, `period_labels.py` would silently compute a confidently WRONG
period label and bake it into the retrieval index — worse than no label
at all, since it's wrong with full confidence rather than just absent.
For the current 5 companies over the ~15-month window of filings
actually ingested, this is a non-issue (all 5 have long-stable,
well-known fiscal calendars) — see `verify_period_labels.py` for the
tool that checks this assumption against real evidence rather than
trusting it blindly. Re-run that script after adding a new company or
pulling in older historical filings, since that's exactly when the risk
of silently crossing an undetected fiscal-year change goes up.

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

### `period_labels.py` + `verify_period_labels.py` (retrieval-precision fix attempt, Week 4/5 follow-up — tried, reverted)

Attempted to fix the two retrieval-precision bugs found by growing the
eval set to 16 questions (`nvda-gross-margin-fy26`,
`msft-rd-expense-q3fy26` — see `eval_harness.py` section for the
original diagnosis). **The specific fix described below was reverted
after the full eval suite showed a net regression** (14/16 → 13/16); it
is documented here as a tried-and-rejected approach, not a working fix.
Both bugs are still open as of this writing.

- **The idea**: `period_labels.py` computes a canonical, natural-language
  period descriptor ("MSFT quarterly report, fiscal year 2026 quarter 3,
  for the three months ended March 31, 2026.") from a chunk's
  ticker/form/reportDate metadata plus the company's
  `fiscal_year_end_month` (now in `companies.json`). `fiscal_year_label()`
  and `fiscal_quarter()` are pure functions, unit tested directly and
  independently correct — the math itself was never the problem (see
  `verify_period_labels.py` below). The attempted fix prepended this
  label to the text `index_chunks.py` *embeds* and the text
  `retrieval.py`'s `_load_bm25_index()` *tokenizes*, while leaving the
  stored/displayed chunk text unprefixed (Chroma's stored `documents`,
  and `_bm25_records`, kept the original text — the LLM already gets
  ticker/form/reportDate via `agent.py`'s citation header, so this was
  meant to be an indexing-time-only change with nothing user-visible
  different).
- **Why it looked like it should fix both bugs:** NVIDIA's 10-K and each
  of its 10-Qs contain near-identical MD&A boilerplate paragraphs,
  differing only in the trailing number — without a per-filing anchor,
  BM25/vector search can't tell which filing's copy is relevant.
  Microsoft's "Highlights" section states a period as "third quarter of
  fiscal year 2026" while the Notes/table with the actual number says
  "Three Months Ended March 31, 2026" — completely different vocabulary
  for the same period, which meant the *wrong* section could win
  retrieval purely on lexical overlap with the question. The hypothesis
  was that a uniform, metadata-derived period label on every chunk would
  give near-duplicate filings a distinguishing anchor, and neutralize
  the phrasing-convention mismatch.
- **Validated cheaply before committing to the full rebuild — and this
  cheap validation is exactly what missed the regression:** simulated
  the augmentation with a throwaway BM25 index and small embedding
  batches over just the affected chunks, rather than re-running the full
  ~3,200-chunk index blind. This confirmed real, substantial rank
  improvement for both original target chunks in isolation (BM25: not in
  top 25 → rank 10; vector: rank 87 → rank 28 for NVDA; similar gains for
  MSFT). But the simulation only ever checked whether the *target*
  chunk's own rank improved — it never checked whether some *other*,
  unrelated chunk in the same filing could be boosted even more by the
  same shared prefix. That's exactly what happened.
- **The full rebuild and eval run exposed a net regression**: after
  rebuilding the real ~3,207-chunk Chroma index with the augmented text
  and running the full 16-question eval suite, the result was 13/16 —
  down from the pre-fix 14/16. Neither original target
  (`nvda-gross-margin-fy26`, `msft-rd-expense-q3fy26`) actually flipped
  to PASS (their rank improved but not enough to clear the top-5 cutoff
  `agent.py` uses), **and** a previously-passing question
  (`pltr-revenue-2025`) newly failed.
- **Root cause, precisely diagnosed**: prepending the same short prefix
  to every chunk in a filing does not apply a uniform, rank-preserving
  boost — embedding models don't combine a prefix and existing content
  additively/linearly. For the PLTR regression, an unrelated boilerplate
  chunk (generic "Notes to Consolidated Financial Statements...
  incorporated in Delaware" text, no revenue content) jumped from vector
  rank 30 to rank 8 purely from gaining the shared per-filing prefix,
  while the genuinely correct chunks only modestly improved (157→103,
  165→77) — the decoy gained disproportionately more than the target.
  Confirmed this wasn't a verbosity artifact: even a much shorter tag
  reproduced the same regression via the same cheap simulation approach,
  before committing to a second full rebuild cycle to check.
- **Resolution**: reverted `index_chunks.py` and `retrieval.py` back to
  unaugmented text (with comments in both files documenting what was
  tried and why), rebuilt the Chroma index, and reran the full eval
  suite to confirm restoration to 14/16 with no new regressions —
  confirmed. `period_labels.py`, `tests/test_period_labels.py`, and
  `verify_period_labels.py` were kept: the period-math logic is sound
  and independently verified, and remains available for a future, more
  targeted application — e.g. as a reranking-stage signal rather than
  raw embedding/BM25 input concatenation, which wasn't attempted this
  round. The two original bugs remain open; see "Immediate next steps."
- **`verify_period_labels.py`**: a re-runnable safeguard against the
  `fiscal_year_end_month` assumption described in the `companies.py`
  section above. Cross-checks the computed fiscal year/quarter for every
  ingested filing against that filing's OWN self-description, found by
  searching its raw text — not trusting the assumption, checking it
  against real evidence. **Building this caught two real bugs in the
  checker itself before it was trustworthy**, both worth keeping as
  documented lessons: (1) a naive first-match search kept grabbing a
  filing's *backward* reference to a prior period ("our Annual Report...
  for the fiscal year ended January 26, 2025") instead of its own
  current-period declaration — fixed by requiring the comparative "Nth
  quarter of fiscal year Y compared to/with the Nth quarter of fiscal
  year Y-1" construction for quarters, and checking set-membership
  across *all* matches (not just the first) for annual filings; (2) a
  regex assumed the day number and comma sat directly adjacent in text
  ("March 31, 2026"), but the raw ingested text sometimes has a line
  break in between ("March 31\n, 2026", an artifact of the original HTML
  table structure) — fixed with a whitespace-tolerant pattern. Final
  result across all 25 currently-ingested filings: **14 confirmed
  against their own text, 0 mismatches, 11 inconclusive** (no reliable
  self-description pattern found for those specific filings — not
  evidence of a problem, just no independent check available for them).

### `xbrl_facts.py` — structured-facts tool, actually fixes the two retrieval-precision bugs (Week 5b)

Where the `period_labels.py` retrieval fix above failed, this succeeds:
both `nvda-gross-margin-fy26` and `msft-rd-expense-q3fy26` are numbers
that live in unstructured prose competing against near-duplicate
boilerplate, but they're also GAAP concepts SEC filers tag as
**structured XBRL data** — fetchable directly by company + concept +
period, sidestepping the retrieval-collision problem entirely instead
of trying to out-rank the decoys. `agent.py` now has a second tool,
`get_financial_fact`, alongside `search_filings`.

- **Endpoint**: SEC's `companyconcept` API
  (`data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/{tag}.json`)
  — one concept, one company, full history — not the much larger
  `companyfacts` endpoint (every concept a company has ever tagged),
  since a single tool call should fetch one metric.
- **Metric-to-tag mapping** (`DEFAULT_METRIC_TAGS` /
  `METRIC_TAG_OVERRIDES`): friendly names (`revenue`, `gross_profit`,
  `cost_of_revenue`, `rd_expense`, `net_income`) map to real GAAP tags.
  `gross_margin` isn't a GAAP tag at all (percentages are prose/MD&A,
  not structured facts) — computed inside the tool from
  `GrossProfit`/`Revenues` instead of returned raw for the model to
  divide, so `agent.py`'s "don't infer/combine numbers" rule doesn't
  need to be relaxed for this tool's output.
- **Period-entry disambiguation** (`_pick_entry`): the part with real
  bug risk, structurally the same class of problem as the retrieval
  period-matching bugs above. A `companyconcept` response isn't
  one-entry-per-period — a single 10-K/10-Q re-reports 2-3 years of
  comparative data under the identical `fy`/`fp` label, and a 10-Q
  additionally reports both the 3-month figure AND the 9-month
  year-to-date figure under that same label. Disambiguated by duration
  (quarter ≈80-100 days, year ≈350-380 days) then taking the entry with
  the latest `end` date. Verified against real captured NVDA/MSFT data
  in `tests/test_xbrl_facts.py`, not synthetic fixtures.
- **Result: `nvda-gross-margin-fy26` and `msft-rd-expense-q3fy26` both
  PASS** with exact values (71.1%, $8,915M) — confirmed via direct
  live `agent.py` runs before trusting the eval number. Full suite:
  **16/16**, up from the 14/16 baseline, no regressions.

**Five real bugs found and fixed along the way — kept as documented
lessons, same discipline as the reverted `period_labels.py` episode
above:**

1. **Fiscal-year arithmetic the model can't do reliably.** For a
   comparison question phrased with a calendar date ("the quarter ended
   April 26, 2026"), the model passed `fiscal_year=2026` directly (the
   calendar year) instead of realizing NVDA's January fiscal year end
   means that date falls in fiscal year 2027 — a WRONG-BUT-VALID period
   match (fy=2026/Q1 exists, just for the wrong, year-earlier quarter),
   so it failed silently instead of erroring. Reproduced live via
   `agent.py --verbose` before fixing. **Fix:** added `period_end_date`
   as an alternative tool input, resolved via `resolve_fiscal_period()`
   which reuses `period_labels.py`'s `fiscal_year_label()`/
   `fiscal_quarter()` — the exact "future, more targeted application"
   flagged as a possibility when that module's embedding-prefix use was
   reverted above. The model is told explicitly not to compute this
   itself.
2. **Wrong revenue tag default.** Checking only HTTP status codes (200
   vs. 404) on each concept URL suggested `Revenues` worked for
   AAPL/MSFT/NVDA/CRM. But a 200 only means a company has *ever* tagged
   a concept, not that it still does in *recent* filings — checking the
   actual latest entry per company showed AAPL's `Revenues` data stops
   in 2018 and MSFT's in 2011 (both switched to the more specific ASC
   606 tag, `RevenueFromContractWithCustomerExcludingAssessedTax`,
   years ago); CRM's most recent quarter had the same gap. NVDA is the
   actual outlier, still actively using plain `Revenues` (and NVDA's
   own past use of the ASC 606 tag stops in 2022, so it can't be the
   shared default either). **Fix:** swapped the default to the ASC 606
   tag, made NVDA the sole override — no single tag works for all five
   companies.
3. **Unhandled crash on an unsupported metric.** Asked for "effective
   tax rate" (not in the tool's metric enum); the model called the tool
   anyway with `metric` omitted entirely rather than skipping it, which
   crashed the whole eval run with an unhandled `ValueError` from deep
   inside `_tag_for`. **Fix:** a boundary guard in `agent.py`'s
   `_call_get_financial_fact` — same category as `_resolve_search_args`'s
   established lesson that the model doesn't reliably respect the
   schema; validate at the boundary, don't trust it.
4. **Unhandled crash on an empty-string date.** For a question with no
   specific calendar date ("total revenue for 2025"), the model called
   the tool with `period_end_date=""` instead of omitting it, crashing
   `date.fromisoformat`. **Fix:** treat a falsy `period_end_date` as
   "not provided" (falls back to `fiscal_year`/`fiscal_period`), plus a
   `try/except ValueError` as defense-in-depth for a malformed-but-
   non-empty date the model might send instead.
5. **Comparison questions silently incomplete.** After
   `get_financial_fact` returned "not available" for one company (e.g.
   AAPL, for the unsupported tax-rate metric), the model sometimes just
   stopped — never called `search_filings` for the *second* company in
   the comparison either, and answered as if that company's data simply
   didn't exist, rather than treating the null result as "try
   `search_filings` for this company, then continue to the next one."
   **Fix:** an explicit new system-prompt rule requiring every company
   in a multi-company question to be queried before answering. Reduces
   but doesn't provably eliminate the risk — re-verified correct across
   multiple live repro runs at the model's configured temperature (0.1,
   not 0, so some run-to-run variance is expected) before trusting the
   fix.

**Known, deliberately out-of-scope limitation:** NVIDIA (and most
annual filers) don't separately tag a standalone Q4 duration — Q4 is
implicitly "FY minus the three 10-Q quarters," not a directly reported
concept. `fiscal_period="Q4"` returns `None` for such companies,
falling back to `search_filings`; not solved here since no current eval
question needs it.

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
   fact. The criteria needs revisiting, not the agent. **Fixed — see the
   dedicated PLTR-grading writeup further down this section for the full
   diagnosis (a systematic judge misreading, not run-to-run noise) and
   the reworded criteria.**

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

**First growth pass: 8 → 16 questions, 14/16 passed.** Deliberately kept
small (per plan: grow incrementally and see what breaks, rather than
writing 30-50 questions before learning anything) and targeted the
coverage gaps `PROJECT_CONTEXT.md` had flagged — NVDA and PLTR previously
had zero `numeric` questions, only one company pair had been compared,
and no question had used a fiscal-quarter label instead of a calendar
date. Every new fact was sourced from the raw ingested filing text/tables
(`./data/<TICKER>/*_text.txt`, `*_tables.json`), not the chunks and not
the model, and the two new `judged` criteria were negative-control
tested (3/3 stable pass on a hand-written good answer, 3/3 stable fail
on a hand-written bad answer, for each) before being added — same
discipline used for the PLTR fix. All 8 original questions still passed
(no regression from growing the set). Full report:
`eval_results/20260816T224625Z.json`.

**Two new questions failed, and both are a genuinely different class of
bug than anything fixed so far** — not query-formulation, not
comprehension, but a structural retrieval-precision limit:

1. **`nvda-gross-margin-fy26` — near-duplicate boilerplate across a
   company's own filings collides at retrieval time.** NVIDIA's 10-K and
   each of its 4 10-Qs all contain their own copy of the same MD&A
   definitional paragraph ("Gross profit consists of total net revenue
   less cost of revenue...") before stating that period's gross margin
   figure — the paragraphs are near-identical except for the trailing
   number. Confirmed directly: the correct chunk (containing "Gross
   margins decreased to 71.1% in fiscal year 2026 from 75.0% in fiscal
   year 2025") doesn't appear in the top 25 of *either* BM25 or vector
   search — not a reranking problem, a fusion-stage miss. Since the
   chunks compete almost entirely on shared boilerplate rather than the
   period-specific number, retrieval can't reliably tell which filing's
   copy is relevant.
2. **`msft-rd-expense-q3fy26` — a different section's phrasing wins
   retrieval instead of the section with the actual number.** The
   question's exact words ("third quarter of fiscal year 2026") echo the
   MD&A's own "Highlights from the third quarter of fiscal year 2026..."
   bullet-point summary almost verbatim, so that chunk dominates BM25 and
   vector search (rank 1 and rank 2 respectively) — but it's a business
   highlights section that never states the R&D dollar figure. The chunk
   that does (the "OPERATING EXPENSES / Research and Development" table)
   phrases the period differently ("Three Months Ended March 31, 2026")
   and lands at rank 8 in vector search only, absent from BM25's top 25,
   so it loses the fusion race.

**Why this isn't fixed the same way the tax-rate bug was:** that fix
worked by trusting the user's own question text over the model's
rewritten query, because the original question's wording reliably
matched the *correct* chunk's phrasing. Here, the question's wording
matches a *different, wrong* chunk just as well or better than the
right one, for reasons specific to how each filing happens to repeat
period labels in multiple, differently-phrased sections. No query
rewrite fixes this in general — a real fix would need to change what
gets retrieved, not how it's asked for (e.g. tagging each chunk more
strongly with its own period metadata, independent of which section's
prose phrasing happens to mention it). **Not yet fixed — queued as a
future retrieval-pipeline investigation, not a quick patch.** Left both
questions in the eval set rather than swapping them for easier ones,
since a known, well-diagnosed gap is more useful long-term than a
higher pass count that hides it.

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

**PLTR refusal grading criteria: FIXED — 8/8 eval questions now pass.**
Diagnosed as a systematic (not random) judge misreading, not agent
behavior: with the original criteria, `grade_judged()` called 5 times at
`temperature: 0.0` against the exact same (objectively correct) agent
answer failed all 5 times, every time for the same wrong reason — it
read the agent's mention of unrelated EPS (earnings-per-share) figures
as if they were dividend-per-share figures, even though EPS and DPS are
different metrics and the answer never states a dividend amount. Fixed
by rewording the criteria to explicitly name EPS as an example of an
unrelated figure that does *not* violate it, and to state precisely what
*would* fail it (a dollar amount presented as an actual per-share
dividend for 2019). **Verified, not assumed:** the reworded criteria
against the same fixed answer text passed 5/5 times, and against two
deliberately-bad answers (one with a fabricated dividend figure, one
that doesn't refuse at all) failed 3/3 times each — same "test the
grading, not just the pipeline" discipline used earlier for the
numeric/comparison graders. **Final 8-question re-run: 8/8 passed, 8/8
cited** (`eval_results/20260816T214953Z.json`) — the first clean run
since the eval harness was built.

**Eval set grown from 8 to 16 questions — see the `eval_harness.py`
section above for the two new findings.** As predicted, growing the
question set surfaced real signal a clean 8/8 run couldn't: two new
failures (`nvda-gross-margin-fy26`, `msft-rd-expense-q3fy26`), both a
genuinely new class of bug — retrieval-precision collisions between
near-duplicate boilerplate or differently-phrased sections within a
company's own filings, not query formulation and not model
comprehension.

**First attempted fix — reverted, see `period_labels.py` section
above.** Prepending a computed period label to each chunk's
embedded/tokenized text produced a net regression on the full eval
suite (14/16 → 13/16: neither original target flipped to PASS, and a
previously-passing question newly failed) and was reverted.

**Second attempted fix — succeeded: see `xbrl_facts.py` section
above.** A second agent tool (`get_financial_fact`) fetches these
specific numbers directly from SEC's structured XBRL `companyconcept`
API instead of relying on unstructured-text retrieval to find them at
all — sidestepping the retrieval-collision problem entirely rather than
trying to out-rank the decoys. **Both `nvda-gross-margin-fy26` and
`msft-rd-expense-q3fy26` now PASS.** Full suite: **16/16**, up from
14/16, confirmed with no regressions. Five real bugs were found and
fixed along the way (fiscal-year-from-calendar-date arithmetic, wrong
revenue tag default, two unhandled crashes on malformed tool-call
arguments, and a multi-company comparison-completeness gap) — see the
`xbrl_facts.py` section for full detail on each.

**Next — two follow-up ideas approved and in scope now**, both aimed at
squeezing more out of the SEC API surface itself rather than adding new
homegrown logic:
1. **`frames` API for cross-company queries.** A fourth SEC XBRL
   endpoint beyond `submissions`/`companyconcept`/`companyfacts`:
   `frames/us-gaap/{tag}/USD/CY2026Q1.json` returns one concept for
   *every* company that reported it in one period, in a single call.
   Useful for "which of our 5 companies had the best gross margin this
   quarter" — today that's 5 sequential `companyconcept` calls; with
   `frames` it's 1. Add as a second function in `xbrl_facts.py`.
2. **Cheap citation-verification pass.** After the model writes its
   final answer, check that each cited `[n]`'s numeric claim actually
   appears in that result's text/value before returning — catches
   silent misgrounding for the cost of a regex check, no extra model
   call needed.

**Deliberately deferred to a future round, not next-up: a curated,
tool-computed formula registry beyond `gross_margin`** (operating
margin, net margin, YoY revenue growth). This is NOT the rejected
general-purpose-calculator idea — the model would never do arithmetic
itself, it'd ask for a named metric and the tool computes it
deterministically from XBRL facts, same pattern as `get_gross_margin`.
But it carries a different risk than the arithmetic-tool one: an
open-ended, ever-growing list of hand-written formulas to maintain.
Parked rather than built now, on the reasoning that it's better to let
real demand (from eval questions, like `aapl-operating-margin-q3fy2026`
and `aapl-revenue-growth-q3fy2026` added below, both of which currently
have no way to be answered correctly) justify which specific formulas
are worth the maintenance cost, rather than pre-building a list.

Worth deferring model-swap questions until after `frames` and citation
verification, since neither currently-open item is a generation-quality
gap.

**Eval set grown again, 16 → 21 questions, deliberately including two
questions the current system can't yet answer correctly** — the point
was to generate real evidence for the formula-registry deferral
decision above, not to hunt bugs. Verified ground truth by computing
each new value from real `get_metric()` calls (and spot-checking two
directly against the raw filing tables, not just the API) before
writing the question: `aapl-net-income-fy2025` and
`nvda-cost-of-revenue-fy2026` broaden coverage of metrics
`xbrl_facts.py` already supports (both PASS, confirming the tool
generalizes beyond the two metrics the original bug-fix touched);
`nvda-rd-expense-q4fy26-refusal` tests the documented Q4 limitation
(PASS — the agent correctly admits NVIDIA doesn't separately report a
standalone Q4 figure, rather than fabricating one from the annual
total); `aapl-operating-margin-q3fy2026` and
`aapl-revenue-growth-q3fy2026` target the formula-registry gap
directly. Result: **20/21**, no regressions on the original 16.

The two formula-registry-gap questions surfaced something more
specific and more useful than a simple pass/fail:
- `aapl-operating-margin-q3fy2026` **FAILED**, but not uniformly the
  same way twice. The recorded eval run answered a fabricated **50.1%**
  cited as if directly retrieved. A live repro immediately after instead
  self-computed **32.68%** (close to the verified 32.6%) by retrieving
  operating income and revenue as separate dollar figures via
  `search_filings` and doing the division itself in its reasoning text
  — a real violation of `agent.py` rule 3 ("don't combine or infer
  numbers"), just one that happened to land close to correct this time.
  Two runs, two different failure modes (fabrication vs. rule-violating
  self-computation), same underlying cause: no deterministic path to
  this number exists yet.
- `aapl-revenue-growth-q3fy2026` **technically PASSED** (16.27% against
  an expected 16.4%), but for the same underlying reason as the
  above — the agent retrieved two `get_financial_fact` dollar values
  (one via a follow-up `period_end_date` call for the prior-year
  quarter) and computed the percentage itself, again violating rule 3,
  and got its own arithmetic slightly wrong in the process (16.27% vs.
  the mathematically correct ~16.36% from its own stated inputs) — the
  eval's numeric-match tolerance was loose enough to accept the
  difference as a pass, which masked the rule violation rather than
  catching it.

This is concrete, not hypothetical, evidence for two things: (1) the
formula-registry idea is solving a real problem, not a speculative one
— the model reaches for self-computation on its own, unprompted, the
moment it has retrievable raw ingredients, and doesn't do so reliably;
(2) the eval harness's current numeric-tolerance matching can mask a
rule-3 violation as a clean pass, which is itself worth tightening
before the formula registry (or any future numeric feature) gets built
and needs trustworthy eval signal.

**Then — continue growing `eval_questions.jsonl`** toward the full
30-50 question, FinanceBench-style set, now informed by two full rounds
of real findings instead of guessing what might break:
- Go back into the actual filings to find and verify ground-truth figures
  — real research, not guessing plausible-looking numbers
- Cover PLTR/NVDA/AAPL more evenly across both 10-K and 10-Q forms
- More comparison-style questions, including ones that require correct
  *attribution* (which entity a number belongs to), since
  `grade_comparison()` doesn't check that yet
- A few genuinely ambiguous/no-company-context questions, to verify
  `agent.py`'s disambiguation holds up beyond the cases spot-checked so far
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
