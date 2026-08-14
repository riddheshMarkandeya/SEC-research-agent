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

## Companies in scope

5 tech companies, chosen because the user knows the sector and can
sanity-check answers:

| Ticker | CIK (10-digit) |
|---|---|
| AAPL | 0000320193 |
| MSFT | 0000789019 |
| NVDA | 0001045810 |
| CRM  | 0001108524 |
| PLTR | 0001321655 |

Last 5 10-K/10-Q filings each.

## 8-week plan (where we are)

1. **Week 1 — EDGAR ingestion** ✅ DONE
2. **Week 2a — table→markdown + chunking** ✅ DONE
3. **Week 2b — embeddings + Chroma indexing** ✅ DONE
4. **Week 3 — hybrid retrieval (vector + BM25) + reranking + citation-grounded answers** ✅ DONE (v0 prototype — see below)
5. **Week 4 — eval harness** ⬅️ **NEXT** (build BEFORE the agent — 30-50
   FinanceBench-style numeric Q&A, exact-match on figures, LLM-as-judge on prose)
6. Week 5 — agent layer + tool calling
7. Week 6 — expose tools as an MCP server
8. Week 7 — guardrails (no numeric claim without citation), retry/backoff,
   rate limits, Langfuse tracing
9. Week 8 — polish + write-up

Note the deliberate ordering: **evals come before the agent**, so there's a
way to measure whether each change helps before iterating on agent behavior.

## Code written so far

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

**Week 4 — eval harness (build BEFORE the agent):**
- 30-50 FinanceBench-style questions across the 5 companies, mixing
  exact-numeric ("what was X's net sales in Q3") and prose/qualitative
  ("what risks does X describe related to Y") questions
- Exact-match grading on numeric answers against the source filing;
  LLM-as-judge for prose answers (grounding + relevance, not just fluency)
- Should exercise `answer.py` end-to-end, including the citation-check
  gap noted above (does every claim actually carry a valid `[n]`? does
  the cited excerpt actually contain the claimed number?) — this is
  where that gets caught mechanically instead of by spot-checking
- Worth deliberately including a few questions like the employee-count
  one (ambiguous company, or asked without ticker context) to get a
  baseline score *before* Week 5's agent adds query routing, so the
  improvement is measurable rather than assumed

## Design principles to carry forward

- **Citations are non-negotiable.** In finance, "trust me" isn't good enough.
  Every numeric claim must trace to a specific filing + section, or the agent
  refuses. This becomes a hard guardrail in Week 7.
- **Evals before agent.** Measure first, then iterate.
- **Narrow scope, checkable outputs.** Numeric answers with exact figures are
  far easier to grade objectively than open-ended summaries.
- **Document failure modes.** The write-up value is in "here's what broke and
  how I found it," not "here's clean code."
