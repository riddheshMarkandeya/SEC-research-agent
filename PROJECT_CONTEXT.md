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
5. **Week 4 — eval harness** ✅ DONE (for this phase), 27 questions —
   started at 6, grew to 8 → 16 → 21 through bug-driven rounds, then two
   more FinanceBench-informed rounds (25 → 27) covering all 5 patterns
   from that analysis. **Deliberately stopped short of the original
   30-50 target**: 27 questions already surfaced 6 real, distinct,
   unfixed bugs (see "Next steps" below) — more volume without fixing
   what's already found has diminishing returns right now. Revisit
   growing further once those are fixed.
6. **Week 5 — agent layer + tool calling** ✅ DONE (v0, then extensively
   hardened through 17 lettered sub-rounds, 5a-5q — see below for all of
   them: structured XBRL facts tool, citation verification, formula
   registry, Q4-refusal fix, eval-question filtering, etc.)
7. Week 6 — expose tools as an MCP server (all 3: `search_filings`,
   `get_financial_fact`, `compare_financial_metric` — not just
   `search_filings` as originally scoped before the other two existed)
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

### `config.py` + `.env`/`.env.example` — shared environment configuration (Week 5g)

Same motivation as `companies.py` right above (single source of truth
instead of silently-drifting copies), applied to infra config instead of
ticker/company data. Before this, several values were independently
hardcoded as module-level constants in 3+ files each:

- `CHROMA_DIR = "./chroma_db"` — separately defined in `index_chunks.py`,
  `retrieval.py`, AND `query_chunks.py`. All three MUST agree, or one of
  them silently queries an empty/unrelated store instead of erroring.
- The embedding model name — same value, but already-diverged variable
  names (`MODEL_NAME` in two files, `EMBED_MODEL_NAME` in the third) —
  a live warning sign of the kind of drift `companies.py`'s own
  `COMPANIES`-variable-name collision already taught this project to
  watch for.
- The SEC `User-Agent` header — `edgar_ingest.py` built it from
  `YOUR_NAME`/`YOUR_EMAIL` constants at the top of the file;
  `xbrl_facts.py` had the same final string hardcoded a second time,
  with no shared source.
- `OLLAMA_URL`/the Ollama chat model name — these were *already*
  centralized once, in `answer.py`, with `agent.py` and `eval_harness.py`
  importing them from there — better than the others, but an odd
  ownership location (an answer-generation script being the source of
  truth for two other modules' config) and worth folding into the same
  place as everything else.

**Fix**: `config.py` loads `.env` via `python-dotenv` and exposes typed
constants — `SEC_USER_AGENT`, `OLLAMA_URL`, `OLLAMA_MODEL_NAME`,
`CHROMA_DIR`, `EMBED_MODEL_NAME`, `RERANK_MODEL_NAME` — each with a
fallback equal to what was previously hardcoded, so nothing breaks
without a `.env` file. `.env.example` is committed as the documented
template; `.env` itself is gitignored (personal/machine-specific, not
secret here, but not the shared source of defaults either). Every
consuming file (`edgar_ingest.py`, `xbrl_facts.py`, `index_chunks.py`,
`query_chunks.py`, `retrieval.py`, `answer.py`, `agent.py`,
`eval_harness.py`) now imports from `config.py` instead of redefining.
Along the way, the Ollama chat model constant was renamed
`OLLAMA_MODEL_NAME` everywhere (previously ambiguously named
`MODEL_NAME`, the exact same name `index_chunks.py`/`query_chunks.py`
already used for a *completely different* model — the embedding model —
which was confusing on its own even before considering duplication).
Verified: `python -c "import <module>"` for all 8 consuming modules,
plus the full 137-test suite, both clean after the change.

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
  and independently verified, still powers `verify_period_labels.py`'s
  fiscal-year-end safeguard, and a reranking-stage-signal application
  was considered as a future alternative to raw embedding/BM25 input
  concatenation. **Decided against reviving that idea**: both original
  motivating bugs (`nvda-gross-margin-fy26`, `msft-rd-expense-q3fy26`)
  were fixed a different way, via the structured XBRL tool below — no
  open bug currently needs it.
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
- **`verify_against_xbrl()`, added in Week 5e/f**: a second, independent
  check on the same `fiscal_year_end_month` assumption, this time
  against SEC's own structured XBRL data instead of filing prose —
  motivated by the period-matching correction below, which raised the
  question of whether the data itself (rather than regex over prose)
  could verify this assumption more directly. Every 10-K-form
  `companyconcept` entry's own `end` date IS that company's fiscal year
  end for that year, so this is a stronger signal than `verify()`'s
  prose-regex approach (no "inconclusive" case, no dependency on a
  specific comparative-quarter phrasing appearing in the text) —
  complements rather than replaces it, since `verify()` separately
  checks `reportDate` metadata correctness, which this doesn't cover.
  **Found a real bug in the checker on its first live run**, same
  discipline as `verify()`'s own two bugs above: filtering on
  `form == "10-K"` alone wasn't enough — SEC's older (pre-~2020) XBRL
  data has real quality issues where clearly quarter-length entries
  (e.g. NVDA's 2009-04-26/07-26/10-25, ~90 days apart) are tagged with
  `form="10-K"` instead of `"10-Q"`, producing spurious mismatches
  across all 5 companies on the first run. Fixed by reusing
  `xbrl_facts.py`'s own `_ANNUAL_DURATION_DAYS` filter (the same
  disambiguation `_pick_entry()` already relies on) to restrict to
  genuinely year-length entries, not just ones labeled "10-K". Final
  result: **5/5 companies confirmed, 0 mismatches**, verified live
  against real cached data. No dedicated pytest file, consistent with
  `verify()`'s own existing convention of being a re-runnable
  self-verifying script rather than unit-tested.

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
   as an alternative tool input, originally resolved via a
   `resolve_fiscal_period()` helper reusing `period_labels.py`'s
   `fiscal_year_label()`/`fiscal_quarter()` — the exact "future, more
   targeted application" flagged as a possibility when that module's
   embedding-prefix use was reverted above. The model is told explicitly
   not to compute this itself. **Superseded in Week 5e below**: that
   resolve-then-match approach had its own latent bug (a computed label
   can silently mismatch); entries are now matched directly on their own
   `end` date instead, and `resolve_fiscal_period()` was removed.
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

### `numeric_utils.py` + `agent.py`'s `verify_citations()` — citation-verification pass (Week 5c)

A cheap, deterministic post-processing step: after `run_agent()` has its
final answer, check that each cited `[n]`'s numeric claim actually
appears in that result's own text before returning. No model call
needed. `run_agent()` now returns a third value, `citation_warnings:
list[str]`; `main()` prints them, `eval_harness.py` records them per
question and reports a summary count.

- **`numeric_utils.py`**: `extract_numbers()`/`normalize()`/
  `NUMBER_PATTERN`/`UNIT_MULTIPLIERS` moved out of `eval_harness.py`
  into their own module so `agent.py` could reuse them without a
  circular import (`eval_harness.py` already imports
  `agent.run_agent`). `tests/test_eval_harness.py`'s corresponding
  tests moved to `tests/test_numeric_utils.py`.
- **Motivating case**: `aapl-revenue-growth-q3fy2026` (see
  `xbrl_facts.py` section above) technically PASSED the eval, but only
  because the model self-computed a percentage from two retrieved
  dollar figures — violating `agent.py` rule 3 ("don't combine or infer
  numbers") — and cited both dollar-figure sources for a percentage
  that appears in neither. `verify_citations()` is built to catch
  exactly that shape of problem: a numeric claim near a citation marker
  whose cited source doesn't contain that number.
- **Confirmed live** against the real case (not just unit tests): the
  first working version caught the real misgrounding (16.27%/16.37%
  flagged correctly) but was nearly unusable — 12 warnings for one
  answer, only 1 of them the genuinely useful signal. Four real,
  live-found sources of false-positive noise were fixed, in the order
  found:
  1. **Dates** ("June 27, 2026" → 27, 2026 read as bare numbers) —
     stripped from the claim window via a date-matching regex before
     extraction.
  2. **Bare year-like numbers** ("fiscal Q3 2025" → 2025 survives the
     date-pattern fix since it's not glued to a month name) — any
     standalone 1900–2099 number is stripped too.
  3. **"10-K"/"10-Q" mentions** — the model's own prose routinely says
     "the 10-Q filing [1]"; "10" isn't glued to a preceding letter (a
     space precedes it), so it wasn't caught by the digit-glued-to-letter
     fix below. This was the *dominant* remaining noise source, showing
     up in the majority of a real 21-question run's answers. Stripped
     the same way as dates.
  4. **Table-caption-only units** — the most significant fix: a real,
     *correctly-answered* baseline question (`crm-rpo-fy26`, not one of
     the intentionally-hard gap questions) got a false "claims 72.4
     (billion) but that value doesn't appear" warning, because the
     source chunk states the unit once in a table caption
     ("...consisted of the following (in billions):") and leaves each
     cell value bare ("$72.4"), which `extract_numbers()` reads as 72.4
     *raw*, not 72.4 billion. Fixed with `_source_number_candidates()`:
     if a source chunk mentions a unit word anywhere, also try that unit
     against every bare/raw number extracted from it — an additive
     fallback, so it only creates new ways to verify a claim, never new
     ways to reject one that would otherwise have matched.
- **Two bugs found and fixed in the shared `NUMBER_PATTERN` itself**
  (in `numeric_utils.py`, so they also improve `grade_numeric()`'s
  extraction, not just `verify_citations()`):
  1. The leading digit group was capped at `\d{1,3}` (reasonable-looking
     for comma-grouped numbers like "1,234,567") but regex alternation
     tries branches left-to-right and stops at the first match, not the
     longest overall — so a comma-less run of many digits (e.g.
     `xbrl_facts.py`'s raw float formatting, "109417000000.0") got
     fragmented into separate wrong candidates (109, 417, 000, 000.0)
     instead of one correct number. Fixed by removing the cap
     (`\d+(?:,\d{3})*(?:\.\d+)?`).
  2. A digit run glued to a preceding letter or digit ("Q3" → read as
     3; "FY2026" → read as a fragment, "026", once the first fix let
     the regex retry at a later start position inside the same glued
     run) wasn't excluded. Fixed with a `(?<!\w)` negative lookbehind
     immediately before the digit group — `\w` excludes both letters
     and digits, so every retry position inside a glued alphanumeric
     run also fails the lookbehind, correctly rejecting the whole token
     instead of leaking a fragment.
- **Known, accepted residual limitation**: a self-authored trailing
  "References:"-style list the model sometimes appends (restating
  `[1] AAPL 10-K (reportDate=...)` as its own line) gets treated as a
  fresh citation occurrence like any inline one, and can pick up a
  nearby summary-sentence number as its "claim" even though it isn't
  really attached to a specific factual statement. Also, multi-step
  derivation work shown *between* a claim and its citation (a
  LaTeX-style calculation block) can still leak intermediate numbers
  into the window on either side — sometimes hiding a real mismatch,
  sometimes adding a harmless duplicate warning. Both are narrow enough
  in practice (residual rate on the 21-question set: 5/21 have at least
  one warning, mostly single-line and non-blocking) that further
  chasing was judged not worth it for a tool explicitly scoped as a
  cheap heuristic, not an exhaustive grounding check — documented here
  rather than silently accepted.
- **Full suite after all fixes: 19/21** (`pltr-dividend-2019-refusal`
  and `aapl-operating-margin-q3fy2026` are the only failures — the
  former is the already-documented pre-existing judged-grading
  instability for that specific question, unrelated to this change;
  the latter is the real, expected formula-registry gap from the
  `xbrl_facts.py` section above, not a bug).

### `eval_harness.py` + `agent.py` — wiring citation-verification into pass/fail, not just a warning (Week 5h)

`verify_citations()` above was informational only — printed as a
warning alongside whatever `grade_numeric()`/`grade_comparison()`
already decided, never affecting the verdict. This left a real,
previously-just-documented gap: those graders only check whether the
expected value appears *somewhere* in the answer text, which can't
distinguish a correctly-cited answer from one that states the right
number but attaches it to the wrong (or no) source. Concretely, this
is exactly the flagged-but-unfixed masking problem from the
`xbrl_facts.py`/eval-growth section above (`aapl-revenue-growth-q3fy2026`
"technically PASSED" despite a rule-3 violation).

- **Confirmed live, not assumed, before designing the fix**: re-ran
  `aapl-employees-fy25` directly — it "passes" today (166,000 appears in
  the answer), but the cited chunk `[3]` is entirely about debt notes
  and share repurchases, nothing to do with employee count. A real
  misattribution bug, not eval-harness noise.
- **`agent.py`**: `verify_citations()`'s internals were refactored
  (public signature and all 13 existing tests unchanged) into a shared
  `_iter_citation_claims()` generator yielding `(citation_index, value,
  unit, verified)` per numeric claim found near a marker. A new
  `value_is_citation_verified(value, unit, answer_text, all_results)`
  consumes the same generator to answer a narrower question: is *this
  one* expected value ever properly grounded, anywhere it's cited?
  Returns True if the value is never cited at all (nothing to
  contradict a plain match) or if *any* of its citations check out — a
  redundant wrong second citation shouldn't fail an otherwise-correct
  claim; False only if every citation attached to it fails.
- **`eval_harness.py`**: `grade_numeric()`/`grade_comparison()` gained
  an optional `all_results` parameter (defaults to `None`, preserving
  old pure-text-match behavior for existing tests/callers that don't
  have citation context) — when given, a numeric match that fails
  `value_is_citation_verified()` now flips the verdict to FAIL with an
  explanatory detail, instead of silently passing. Scoped to `numeric`/
  `comparison` question types only; `judged` questions are untouched,
  since a stray unrelated number near a qualitative claim is much
  lower-stakes than a wrong number backing the specific value being
  graded.
- **Built via TDD** (red-green-refactor): tests for
  `value_is_citation_verified()` written and confirmed failing (missing
  function) before implementation; same for `grade_numeric()`/
  `grade_comparison()`'s new parameter.
- **Live eval re-run confirmed the fix catches real bugs, not just
  passes tests**: `aapl-employees-fy25` and `aapl-revenue-growth-q3fy2026`
  both flipped from a masked PASS to a correctly-diagnosed FAIL (the
  latter being the exact case this was built to catch);
  `nvda-crm-revenue-comparison` also newly failed on an apparent
  misattributed CRM citation. `aapl-msft-tax-rate-comparison` also
  failed the same run, but for an unrelated reason (the model produced
  no citation markers at all that run) — pre-existing model-output
  variance, not something this change caused. Full suite: 148/148 unit
  tests; live eval dropped from 19/21 to 16/21 on this run, which is
  the harness now being honest about problems it used to silently
  paper over, not a regression.

### `agent.py` system-prompt rule 8 — per-claim citation placement (Week 5i) — kept

Discussing the Week 5h eval results (`nvda-crm-revenue-comparison`) surfaced a
distinct pattern from plain misattribution: the model answered
`"NVIDIA's revenue was $81.6 billion, while Salesforce's was $11.1
billion [1][2]."` — both citations bundled at the sentence's end, after
*both* facts. Given how `_iter_citation_claims()`'s windowing works,
`[1]`'s window captures both numbers (nothing resets it between them)
while `[2]`'s window is empty (nothing between two back-to-back
brackets) — so `[1]` gets blamed for "claiming" a number that's
probably really backed by `[2]`'s own source. Whether or not the
underlying retrieval was actually correct, bundled citations make
per-claim attribution ambiguous to both a human reader and this
project's own verification tooling.

- **Fix**: system-prompt rule 8 requires a citation immediately after
  each individual fact in a multi-company sentence, not bundled at the
  end. Verified live: the exact motivating question went from
  `"...$81.6 billion, while...$11.1 billion [1][2]."` to
  `"...$81.6 billion [1], while...$11.1 billion [2]."`, and the full
  eval's `nvda-crm-revenue-comparison` became a reliable PASS.
- **A real regression found immediately after, via live testing, not
  assumed**: the first wording of rule 8 broke a previously rock-solid
  question (`nvda-rd-expense-q4fy26-refusal`) 3 times in a row —
  tool-loop exhaustion or complete topic derailment (once querying
  AAPL/MSFT filings for a question purely about NVIDIA), where 5
  historical runs (3 before rule 8 existed, 2 with it stashed out
  during isolation testing) were all clean. **Root-caused via variable
  isolation** (`git stash` rule 8 in/out, same question, multiple
  samples each way) before attempting a fix — confirmed causation, not
  coincidence. **Fix**: narrowed rule 8's wording to explicitly scope it
  to multi-company sentences only and explicitly state it adds no
  requirement to single-company or refusal answers ("never search for
  extra facts just to have something to cite per-sentence"). This
  improved but did not fully restore baseline reliability (roughly 2-3
  clean out of 4 samples with the reworded rule, vs. 5/5 clean with no
  rule 8 at all) — accepted as a real, documented trade-off: rule 8's
  bundled-citation fix addresses a correctness/trust issue in graded
  numeric comparisons, while its cost is an occasional ungraceful
  failure (a safe fallback message or an unhelpful answer) on one
  specific fragile refusal-style question, not a wrong-but-confident
  answer. Current rule 8 wording is the accepted version; further
  wording iteration was deliberately stopped once two attempts showed a
  persistent pattern rather than continued unilateral guessing (see
  systematic-debugging discipline below).

### Citation-verification retry loop — tried and reverted, deferred to a more capable model (Week 5j)

With Week 5h's numeric/comparison citation gate showing real,
recurring misattribution (not just the one originally-diagnosed case,
but also `crm-revenue-q1fy27` — a previously 100%-reliable question,
confirmed via direct retrieval inspection to cite an unrelated
dividend-program chunk instead of the actual revenue chunk), the
earlier-deferred idea of having `run_agent()` self-correct on its own
unverified citations was revisited with much stronger justifying
evidence than when it was first deferred.

- **Design**: when the final answer has an unverified citation (per
  `verify_citations()`) and the run hasn't already retried once, feed
  the model its own draft answer plus the specific warning strings back
  as a corrective follow-up, and let it try again — sharing the
  existing `MAX_TOOL_ITERATIONS` budget rather than a separate one, so
  it can't compound with an already-long tool-calling sequence. Built
  via TDD as two pure, unit-tested helpers
  (`_should_retry_for_citations()`, `_format_citation_retry_message()`)
  wired into `run_agent()`'s existing loop.
- **The mechanism worked exactly as designed** — triggered correctly,
  capped at one retry, fed back the real warnings — but **did not
  reliably improve answer quality** on live testing against the two
  confirmed misattribution cases: `aapl-employees-fy25`'s retry gave up
  entirely ("I cannot confirm the exact number") instead of finding the
  correct number among the 4 other already-retrieved chunks;
  `crm-revenue-q1fy27`'s retry *did* re-locate and quote the correct
  passage, but still mislabeled which citation index it belonged to.
- **A real, worse regression found via live testing**: the first retry
  message's closing line — "This is your final attempt — give a
  complete answer now" — pushed the model to fabricate an "estimated"
  R&D figure (extrapolated from an unrelated quarter) on
  `nvda-rd-expense-q4fy26-refusal`, a question it had answered correctly
  (an honest refusal) before any retry mechanism existed — a direct
  rule-2 violation *caused by* the fix meant to improve correctness.
  Reworded the message to explicitly say an honest refusal is a
  completely acceptable retry outcome and to explicitly prohibit
  inventing/estimating — **this did not fully fix it either**: the same
  question, re-tested, still concluded with a fabricated "estimate"
  despite the explicit instruction not to.
- **Two real fix attempts at the retry message both fell short in the
  same way rule 8's two attempts did** — a pattern, not a coincidence:
  `qwen2.5:7b-instruct` appears to have a real, not-fully-wording-
  fixable difficulty overriding its own prior-turn framing on this
  specific fragile refusal-style question, whether the added pressure
  comes from a new system-prompt rule or a mid-conversation correction.
  Per this project's systematic-debugging discipline (question the
  architecture after repeated fixes land in the same failure mode
  rather than keep guessing at wording), this was brought back for a
  decision rather than attempting a third wording tweak.
- **Decision: reverted.** The retry mechanism costs one extra ~60-90s
  Ollama round trip on every citation warning without reliably
  improving the answer on this model — not a good trade. `agent.py`'s
  `run_agent()` is back to returning `verify_citations()`'s warnings
  without acting on them itself. **The eval-harness pass/fail gate
  (Week 5h) and `verify_citations()`/`value_is_citation_verified()`
  themselves are all still fully in place** — only the runtime
  self-correction attempt was removed; the warnings remain valuable for
  eval grading and are expected to matter again for tracing/observability
  in Week 7.
- **Marked as a future step**: revisit a runtime citation-retry loop
  once working with a more capable model than `qwen2.5:7b-instruct` —
  the design (`_should_retry_for_citations`/`_format_citation_retry_message`
  pattern, sharing the existing iteration budget) is sound and cheap to
  rebuild; what's missing is a model that can reliably act on corrective
  feedback without abandoning a previously-correct answer or fabricating
  under pressure to "complete" a final attempt.

### Formula registry — `operating_margin`, `net_margin`, `yoy_growth` (Week 5k)

The previously-deferred formula registry, now built: the two hard eval
questions that motivated deferring it in the first place
(`aapl-operating-margin-q3fy2026`, `aapl-revenue-growth-q3fy2026`) both
now PASS with the exact expected values (32.6%, 16.4%), via a single
clean tool call each — no self-computation, no rounding drift.

- **`operating_income` verified live before adding**, same discipline as
  the original revenue-tag lesson: `OperatingIncomeLoss` has recent,
  clean entries for all 5 companies, no per-company override needed
  (unlike revenue).
- **`xbrl_facts.py`**: `_compute_ratio_metric()` extracted from
  `get_gross_margin()`'s body once `get_operating_margin()`/
  `get_net_margin()` would otherwise have been copies of it differing
  only in the numerator metric — same duplication class `config.py`
  fixed earlier for infra constants, this time for margin formulas. Same
  consolidation for the cross-company versions
  (`_compute_ratio_metric_all_companies()`).
- **`get_yoy_growth()` does zero date arithmetic, by design**: the prior
  comparable period isn't computed as "one year before" a calendar date
  (which would reproduce the exact bug class `_pick_entry_by_end_date()`
  already fixed once) — it's found by reading the CURRENT period's own
  SEC-assigned `fiscal_year` back off `get_metric()`'s result (which now
  also exposes `fiscal_year`/`fiscal_period` for this reason) and asking
  for `fiscal_year - 1` at the same `fiscal_period`. Integer subtraction
  on a label the data already supplied, not an independent computation
  that could silently disagree with it.
- **Scoped deliberately**: `yoy_growth` only applies to the raw tagged
  metrics, not the margin ratios (no current evidence "growth of a
  percentage" is a real question shape) — rejected at the `agent.py`
  boundary rather than passed through. Not exposed on
  `compare_financial_metric` either, for the same reason (no evidence
  for a cross-company YoY-growth comparison yet).
- **Live eval confirms both target questions now pass** with the exact
  values, and the Q4-refusal question correctly still refuses without
  fabricating (`nvda-rd-expense-q4fy26-refusal` PASS). Full suite:
  168/168 unit tests. The eval run's remaining 4 failures are all
  pre-existing, already-documented comparison-type flakiness (missing
  citation markers, misattribution) — unrelated to this change, and
  themselves part of the motivation for the next planned step: testing
  against a cloud model to see how much of that flakiness is a
  `qwen2.5:7b-instruct` capability ceiling versus something still worth
  fixing locally. **Correction: `nvda-rd-expense-q4fy26-refusal`'s PASS
  here turned out not to be reliable** — later runs this session showed
  it fabricating under rule 8 and again under Gemini; see Week 5m below
  for the actual root cause and fix.

### Cloud-model spike — Gemini free tier, throwaway (Week 5l)

Tested whether `qwen2.5:7b-instruct`'s capability was the bottleneck
behind the session's recurring citation-misattribution and
comparison-question flakiness, by running the exact same system prompt,
tool schemas, and tool-dispatch logic (imported from `agent.py`, not
copied) against Google Gemini's free tier instead of local Ollama.
Spike script: `spike_gemini_eval.py` — deliberately throwaway per
`superpowers:brainstorming`'s Spike path (uncommitted, `google-genai`
installed directly into `.venv`, not added to `requirements.txt`).

- **Model**: `gemini-flash-lite-latest` (free tier). `gemini-2.5-flash`
  404'd ("no longer available to new users"); the `gemini-flash-latest`
  alias resolved to `gemini-3.7-flash`, whose free tier is only 20
  requests/day — too restrictive for a 21-question eval with multi-call
  tool loops. `gemini-flash-lite-latest` had a workable free quota.
- **Result: 19/21 passed, 20/21 cited.** Critically, **all three
  comparison-type questions passed cleanly** — the single most
  persistently flaky category on the local model all session (missing
  citations, garbled numbers) — and both previously-diagnosed
  misattribution cases (`aapl-employees-fy25`, `crm-revenue-q1fy27`)
  passed with zero citation warnings, confirming the earlier direct
  chunk-inspection finding: Gemini picks the right chunk out of the same
  5 retrieved results the local model gets wrong.
- **Two failures, both different in character from local-model
  failures**: `pltr-dividend-2019-refusal` failed on a stricter
  grading-criteria technicality (said "$0" instead of an explicit
  no-data refusal — arguably still correct, just phrased in a way the
  strict criteria disallows). `nvda-rd-expense-q4fy26-refusal` failed by
  not addressing the question at all with no citation — root-caused and
  fixed independent of the model, see Week 5m below.
- **Conclusion**: strong evidence the citation-misattribution/comparison
  flakiness fought all session was a `qwen2.5:7b-instruct` capability
  ceiling, not a retrieval or system-design problem — a free-tier cloud
  model closed nearly all the gaps with zero retrieval changes. Argues
  against building query rewriting next (recall wasn't the bottleneck,
  attribution was) and gives real evidence before pursuing stricter
  citation checks.

### Q4-refusal fix — tool message now explains *why*, not just *that*, data is missing (Week 5m)

`nvda-rd-expense-q4fy26-refusal` had been flaky all session (fabricated
under rule 8, flaky again under the reverted retry loop, then failed
differently under Gemini) — root-caused via
`superpowers:systematic-debugging` instead of another prompt tweak.

- **Root cause, confirmed directly**: `get_metric('NVDA', 'rd_expense',
  fiscal_year=2026, fiscal_period='Q4')` returns `None` — no company
  files a standalone Q4 report (only Q1-Q3 get a 10-Q; Q4 only exists
  implicitly as `FY − Q1 − Q2 − Q3`), so there's no discrete XBRL fact
  to find. The existing "no structured data found ... try
  search_filings instead" fallback message didn't say *why*, so the
  model trusted the follow-up search back — which returned pure noise
  for this query (cash flow tables, buybacks, segment revenue, nothing
  about R&D) — and fabricated a wrong-quarter number, once citing a
  chunk that didn't even contain the value it claimed.
- **Fix**: `_format_no_fact_message()`/`_format_no_comparison_message()`
  (new pure helpers, extracted from inline f-strings in `run_agent()`
  for testability) append a `_Q4_NOT_DISCLOSED_HINT` whenever
  `fiscal_period == "Q4"`, explaining the structural gap and instructing
  the model not to state any figure. Applied to both
  `get_financial_fact` and `compare_financial_metric` fallbacks — the
  same gap applies to any Q4 comparison question, not just
  single-company ones.
- **The hint needed two iterations, both caught by live re-testing, not
  assumed**: v1 said "you may mention the annual figure as context"
  (matching the eval criteria's optional allowance) — 2/3 clean, but the
  third run fabricated a wrong FY figure ($5.9B vs the real $18.5B)
  anyway. v2 dropped the explicit invitation but kept a soft "don't
  estimate" — 3/5 clean; the model still volunteered "the full fiscal
  year total is available" unprompted and fabricated a number in 1 of
  the 2 failures. v3 forbids stating *any* dollar amount at all
  (mentioning the annual figure is optional per the grading criteria, so
  a hard ban stays compliant) — **5/5 clean**, and the model now answers
  directly from the tool hint without even needing a follow-up search.
- **Verified**: 173/173 unit tests (5 new, covering both helpers' Q4
  hint behavior and message-content preservation). Full 21-question
  eval: **18/21**, target question now PASS; the 3 failures are the
  pre-existing local-model comparison/tax-rate flakiness Week 5l's
  Gemini spike already diagnosed as a model-capability limit, unrelated
  to this change.

### `formulas.py` — formula registry split out of `xbrl_facts.py` (Week 5n)

By the time Week 5k's formula registry existed, 9 of `xbrl_facts.py`'s
16 top-level functions were already formula/ratio logic
(`_compute_ratio_metric`, the three margin wrappers + their
all-companies counterparts, `_compute_ratio_metric_all_companies`,
`get_yoy_growth`), not raw XBRL fetching — more than half the file, and
about to grow further once the FinanceBench-informed eval growth
(Week 5l's roadmap) adds multi-year averages, cash-flow ratios, etc.
Unlike the raw XBRL tags (a small, bounded set SEC actually defines),
the list of financial ratios a user might ask for has no natural upper
limit — the same reasoning `config.py` used for scattered constants,
applied here to a different kind of duplication risk.

- **`formulas.py`** now owns every derived metric: `get_gross_margin`/
  `get_operating_margin`/`get_net_margin` (+ all-companies versions),
  `get_yoy_growth`, and both shared `_compute_ratio_metric*` bodies. It
  imports `get_metric`/`get_frame` from `xbrl_facts.py`.
- **`xbrl_facts.py`** shrinks back to just raw-fact fetching: tag
  resolution, period-entry disambiguation, `get_metric`, the `frames`
  API. One responsibility, matching what it was before margins got
  bolted on.
- **`agent.py`** updates its imports accordingly; `MARGIN_METRIC_FUNCTIONS`
  itself stays in `agent.py` (tool-dispatch wiring, not a formula).
- **A real gotcha, caught before it caused silent test bugs**: tests
  that monkeypatch `get_frame`/`get_gross_margin`/etc. for functions now
  living in `formulas.py` had to retarget their patches to
  `"formulas.X"`, not `"xbrl_facts.X"` — `from xbrl_facts import
  get_frame` binds a separate name in `formulas.py`'s own namespace at
  import time, so patching `xbrl_facts.get_frame` doesn't reach a call
  made via `formulas.py`'s own bare `get_frame` name. Exact same shape
  of gotcha already documented for `agent.py`'s `MARGIN_METRIC_FUNCTIONS`
  (Week 5k) — worth remembering as a general pattern, not a one-off.
- **Pure refactor, no behavior change**: 173/173 tests before and after
  the split (19 moved into a new `test_formulas.py`, none added/removed).
  Verified live through the real (unmocked) import chain too — real
  `get_operating_margin`/`get_yoy_growth` calls still return the
  previously-verified values (32.6%, 16.4% for AAPL), and
  `agent.MARGIN_METRIC_FUNCTIONS["operating_margin"][0] is
  formulas.get_operating_margin` confirms the dispatch table is wired to
  the real function, not a stale reference.

### `xbrl_facts.py`'s `frames` API — cross-company comparison in one call (Week 5d)

A second agent tool, `compare_financial_metric`, alongside
`get_financial_fact`/`search_filings`: gets one metric for all five
covered companies at once, for the same period, instead of the model
calling `get_financial_fact` five times.

- **Endpoint**: SEC's `frames` API
  (`data.sec.gov/api/xbrl/frames/us-gaap/{tag}/USD/{frame}.json`,
  e.g. `CY2026Q1`) — one concept, *every* filer that reported it for
  that period, in one call. `fetch_frame()`/`get_frame()` filter the
  (large, whole-market) response down to our 5 covered CIKs.
- **The frame label is never computed independently — it's read off an
  anchor company's own already-resolved fact.** First design considered
  computing a `"CY{year}Q{quarter}"` label from a raw calendar date with
  ordinary Jan-Mar/Apr-Jun quarter math. Checked against real data
  before writing any of that: NVIDIA's quarter ending April 26 is
  assigned frame `CY2026Q1` by SEC, not the naively-expected `CY2026Q2`
  — SEC's own bucketing tolerates a wider window than strict
  calendar-month boundaries (to accommodate the many non-calendar
  fiscal years it aggregates across). Guessing that window would have
  reproduced the exact class of period-matching bug already fought
  twice in this file. Instead, every `companyconcept` entry already
  carries its own SEC-assigned `frame` label directly (confirmed for
  all 5 covered companies' latest entries) — `get_metric()` now returns
  it, and `get_metric_all_companies()`/`get_gross_margin_all_companies()`
  resolve one company's own fact first (reusing all the already-tested
  period-resolution logic), then use *that* frame to fetch every
  covered company's value for the same bucket.
- **`get_frame()` merges across every distinct tag in play for a
  metric**, not just one — the same class of bug as the original
  revenue-tag-default mistake (see `xbrl_facts.py` section above), just
  at the frames layer: since NVDA uses `Revenues` while the other four
  use the ASC 606 tag for "revenue," a single-tag frames query would
  silently omit NVDA. Verified with real data: a `get_metric_all_companies`
  call for "revenue" correctly returns all 5 companies, each sourced
  from whichever tag it actually uses.
- **`get_gross_margin_all_companies()`** mirrors `get_gross_margin()`'s
  pattern: computed per-company from two frames (`gross_profit` /
  `revenue`) rather than returned raw, and only includes a company if
  both frames agree on its `period_end` — the two tags aren't
  guaranteed to line up per company, only checked.
- **A real gap found via a live natural-language test, not assumed**:
  asking "which company had the highest gross margin in *their most
  recent quarter*" gave the model no calendar date or fiscal label to
  anchor on, so it called `compare_financial_metric` with no period
  args at all — which used to silently return nothing
  (`fiscal_year=None` never matched anything in `_pick_entry`), and the
  model abandoned the whole comparison rather than retrying. Fixed with
  `_latest_entry()`: when no period is given at all, `get_metric()`
  (and by extension `get_gross_margin()`) now falls back to the single
  most-recently-reported entry, breaking ties at the same `end` date
  toward the *shorter* duration (a fresh 10-Q's own quarter figure over
  its same-report 9-month year-to-date cumulative, which share an end
  date) — "most recent quarter" should mean the quarter, not a longer
  cumulative that happens to end the same day.
- **A related, genuinely expected characteristic, not a bug**:
  anchoring on a company that's filed a more recent quarter than its
  peers gives partial coverage — confirmed live: anchoring on AAPL or
  MSFT (both had already filed their next quarter) returned only 1-2
  of 5 companies, while anchoring on NVDA or CRM returned all 5.
  Companies file on different, asynchronous calendars; "most recent"
  is anchor-relative, not a single shared moment. Rather than trying to
  merge across multiple anchors to force full coverage, this is
  surfaced honestly: **system-prompt rule 7** requires the model to
  explicitly name which companies were/weren't covered when
  `compare_financial_metric` returns fewer than five, rather than
  phrasing a partial comparison as if it covered "all five companies."
  Verified live: before the rule, a real answer said "PLTR had the
  highest gross margin... among our five companies" despite only 2
  ever being retrieved; after, it explicitly stated "the other
  companies did not provide a reported gross margin for that period."

### `xbrl_facts.py` — period-matching correction: match on `end`, not a computed label (Week 5e)

A design review question ("is fiscal-year date arithmetic safe to trust,
and is there something in the data itself we should be leaning on
instead?") surfaced a real latent bug in bug #1's original fix above,
not just a style concern.

- **The problem**: `resolve_fiscal_period()` converted a caller-given
  `period_end_date` into a `(fiscal_year, fiscal_period)` guess via
  `period_labels.py`'s fiscal-year arithmetic, then matched entries
  against *that computed label* (`fy`/`fp` equality in `_pick_entry`) —
  never against the actual date asked about. Every `companyconcept`
  entry already carries its own authoritative `end` date directly from
  SEC; computing a second, independent label and matching on that
  instead of the ground truth already in the response meant a wrong
  computation wouldn't fail loudly, it would silently match a
  *different, real* entry that happened to share the (wrong) label —
  exactly the failure mode bug #1 was originally written to fix, just
  reintroduced one layer down. Concretely reproduced as a **newly found,
  not previously eval-covered** bug: `resolve_fiscal_period` has no "FY"
  case (`fiscal_quarter()` only returns Q1-Q4), so passing a company's
  own *fiscal-year-end* date (e.g. NVDA's FY2026 end, "2026-01-25") as
  `period_end_date` computed `fiscal_period="Q4"` and searched for a
  10-Q-shaped quarterly entry that doesn't exist for a company that
  doesn't separately tag standalone Q4 — silently returning `None` for a
  valid annual-figure question phrased with a calendar date. Added as a
  regression test (`test_get_metric_with_fiscal_year_end_calendar_date_returns_annual_value`)
  before fixing, confirmed failing under the old code path.
- **The fix**: `_pick_entry_by_end_date()` replaces the
  resolve-then-match approach — filters entries directly on
  `entry["end"] == period_end_date`, using the existing duration buckets
  only to disambiguate a quarter figure from an annual/YTD figure that
  happens to share the same end date (preferring quarter when both
  exist, which in practice is rare — see the function's docstring).
  Ties among same-end-date, same-duration entries (e.g. a value restated
  in a later filing) break toward the most recently *filed* one, since
  `end` is now fixed by construction and the old max(`end`) tiebreak no
  longer applies. `get_gross_margin()` simplified alongside it — it used
  to pre-resolve the period once so both legs (`gross_profit`/`revenue`)
  stayed consistent; now both legs just receive `period_end_date`
  directly and `get_metric()` matches each independently, with the
  existing `period_end` equality check still catching any real
  divergence between the two tags.
- **`resolve_fiscal_period()` was deleted, not deprecated** — its whole
  purpose was the intermediate computation this fix removes, and it had
  no other callers. `period_labels.py`'s `fiscal_year_label()`/
  `fiscal_quarter()` are unaffected and still power `chunk_period_label()`
  for retrieval indexing (a genuinely different use case — labeling
  chunks for BM25/embedding, not selecting which XBRL entry to return).
- Full suite: 137/137 (5 new tests added, 3 stale `resolve_fiscal_period`
  tests removed), no regressions.

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

**Eval set later grown to 27 questions across two FinanceBench-informed
rounds (Week 5o/5q) — see those sections further below.** Deliberately
stopped short of the original 30-50 target once 27 questions had
already surfaced 6 real, distinct, unfixed bugs; growing further was
judged lower-value than fixing what's already found. See "Next steps"
at the end of this doc.

**Considered and deferred, then dropped:** RAGAS/DeepEval (open-source
RAG eval libraries with built-in *faithfulness* metrics — do the
answer's claims actually trace back to the retrieved chunks). At the
time, this project's own `grade_comparison()` had just caught exactly
the kind of error a faithfulness metric is designed for, which read as
a reason to add one as a third grading path. **Decided against it once
`value_is_citation_verified()` existed** (Week 5h, below) — it already
does faithfulness-style checking (does a cited claim's number actually
appear in its cited source) directly in this project's own grading
pipeline; a second external library would likely be redundant.

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

## Next steps

> This section used to be a running "X: FIXED, see above" log that
> duplicated every `###` write-up in "Code written so far" above it,
> growing every session until the actual open items were buried under
> ~380 lines of history. Cleaned up (2026-08-19): every already-done
> item now lives in exactly one place (its own `###` section above),
> and this section holds only what's genuinely still open, in priority
> order. Git history and the `###` sections are the changelog; this is
> the todo list.

**1. Fix the 6 accumulated eval findings from rounds 3 and 4** (Week
5o/5q above), before doing anything else eval-related — this is the
explicit reason eval growth paused at 27 questions instead of
continuing to 30-50:
- `nvda-total-assets-q1fy27` — pure retrieval miss; `total_assets` isn't
  in `DEFAULT_METRIC_TAGS`, and `search_filings` can't find the balance
  sheet table for this query at all.
- `aapl-cash-equivalents-q3fy2026` — right value, wrong/missing citation
  grounding (retrieval CAN find the chunk; attribution still fails).
- `nvda-segment-revenue-comparison-q1fy27` — misread the segment table,
  concluded both segments had equal revenue.
- `msft-segment-revenue-comparison-q3fy2026` — picked the wrong segment;
  cited figures don't match the real table at all.
- `aapl-3yr-avg-operating-margin-fy2023-fy2025` — misparsed "3-year
  average" as a Q4-specific request, echoed the Q4-not-disclosed hint
  verbatim instead of attempting the actual question.
- `pltr-inventory-turnover-fy2025-refusal` — got close (admitted it
  couldn't compute the ratio) but never named the real reason (no
  inventory line item at all) and cited an unrelated figure.

**2. Then: build the Gemini swappable-backend design** (deferred from
Week 5l's spike). Two things this unblocks at once: (a) re-testing
"local vs. cloud" properly once the above 6 fixes land, to see whether
they generalize or whether Gemini still outperforms on the same
questions; (b) revisiting the citation-verification retry loop (Week
5j, built, reverted, explicitly marked "revisit once working with a
more capable model") — Gemini is exactly that more-capable model to
test it against, now reachable via the same swappable backend instead
of the throwaway `spike_gemini_eval.py` script.

**3. Then: resume eval growth**, informed by both the FinanceBench
analysis (Week 5l) and whatever round 1-2 above surfaces:
- **Multi-statement questions** — FinanceBench had questions requiring
  two *different* statements together (e.g., operating cash flow ratio
  = CFO / current liabilities). Round 3's statement-scoped questions
  only covered one statement at a time — untested variant.
- **Pure unstructured multi-chunk synthesis** — combining two *prose*
  facts from `search_filings` within one filing, no structured XBRL
  involved. Distinct from the segment-comparison questions (which read
  both numbers from a single table) and from the margin formulas (which
  combine two *structured* XBRL calls).
- A few genuinely ambiguous/no-company-context questions, to verify
  `agent.py`'s disambiguation holds up beyond the cases spot-checked so
  far (carried over from before the FinanceBench work started).
- Toward the original 30-50 FinanceBench-style target, if still useful
  once the above is covered — not a fixed requirement, revisit whether
  it's still worth it once there's more signal.
- Ground truth for all of the above: real research against actual
  filings, same discipline as every round so far, not guessed numbers.

**4. Independent, no dependency on the above — do whenever convenient:**
decide whether `answer.py` (Week 3) stays as a simpler fallback/
baseline or gets retired. `agent.py` is a strict superset of what it
does; this is a cleanup decision, not a bug fix.

**5. Week 6 — expose tools as an MCP server.** All 3 agent tools
(`search_filings`, `get_financial_fact`, `compare_financial_metric`) —
not just `search_filings` as the plan originally said before the other
two existed.

**6. Week 7 — guardrails**: no numeric claim without citation as a hard
gate (not just a warning), retry/backoff, rate limits, Langfuse tracing.

**7. Week 8 — polish + write-up.**

<details>
<summary>Historical log (superseded by the section above — kept for the full narrative/evidence trail, not because anything here is still actionable)</summary>

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

**Citation-verification pass: DONE — see `agent.py`'s `verify_citations()`
section below.**

**`frames` API for cross-company queries: DONE — see `xbrl_facts.py`'s
frames section below.** Both approved follow-up ideas are now built;
no further items queued here.

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

**Point (2) is now FIXED — see the `eval_harness.py` + `agent.py`
"wiring citation-verification into pass/fail" section below (Week 5h).**
`aapl-revenue-growth-q3fy2026` no longer masks as a pass; it correctly
fails now, along with a live-found second real bug
(`aapl-employees-fy25`) the eval hadn't caught before either.

**The formula registry itself is now DONE too — see "Formula registry"
(Week 5k) below.** Both `aapl-operating-margin-q3fy2026` and
`aapl-revenue-growth-q3fy2026` pass with the exact expected values now.

**Also deliberately deferred: a runtime citation-verification retry
loop in `run_agent()` itself** (as opposed to the eval-harness gate
above, which stays). Built, tested, and verified live — see "Citation-
verification retry loop — tried and reverted" (Week 5j) below for the
full account. Reverted because `qwen2.5:7b-instruct` couldn't reliably
act on the corrective feedback (sometimes abandoning a previously-
correct refusal, once fabricating an estimate despite an explicit
instruction not to), so the extra ~60-90s retry cost wasn't buying
real quality. Revisit once working with a more capable model — the
design and its tests are still there if this repo trades models later.

**Cloud-model spike (Gemini, free tier): DONE — see "Cloud-model spike"
(Week 5l) below.** 19/21, with every previously-flaky comparison
question passing cleanly — strong evidence the session's recurring
citation-misattribution/comparison flakiness was a local-model
capability ceiling, not a retrieval or design gap. Recommends against
building query rewriting next (recall wasn't the bottleneck).

**`nvda-rd-expense-q4fy26-refusal` fragile-question fix: DONE — see
"Q4-refusal fix" (Week 5m) below.** Root-caused (not another prompt
tweak): the tool's "no data found" message never explained *why* Q4 has
no structured fact, so the model trusted noisy search results back and
fabricated. Fixed with a Q4-specific hint in the tool response itself.
5/5 clean on live re-testing after two hint-wording iterations; full
eval 18/21 with no regressions.

**Decided: eval growth comes first, Gemini swappable-backend comes
after.** `spike_gemini_eval.py` stays an uncommitted throwaway until
then — once the eval set is bigger/harder, revisit it as a proper
swappable-backend design so "local vs. cloud" can be re-tested on
demand rather than as a one-off spike.

**FinanceBench analysis: DONE, informing the next eval-growth round.**
Fetched the public 150-question open-source set
(`PatronusAI/financebench` on GitHub) to study structure before writing
new questions ourselves — **zero usable company/period overlap**
(only 2 MSFT questions total, both old fiscal years; AAPL/NVDA/PLTR/CRM
absent entirely), confirming questions can't be imported, only patterns
borrowed. Patterns worth adopting, in priority order:
1. **DONE (round 3, Week 5o)** — Statement-scoped questions ("...using
   the income statement") — targets the exact retrieval-precision-
   collision failure mode already found twice (`nvda-gross-margin-fy26`,
   `msft-rd-expense-q3fy26`). Covered: single-statement questions only
   (total assets / balance sheet, cash & equivalents / balance sheet) —
   see the "still open" list below for the multi-statement variant this
   didn't cover.
2. **DONE (round 3, Week 5o)** — Same-company cross-segment comparisons
   ("which segment had the lowest revenue") — a genuinely untested
   retrieval shape (correct attribution within one filing, not across
   companies); ended up pulling in NVDA and MSFT's segment tables.
3. **DONE (round 4, Week 5q)** — Multi-year-average ratios (3-year
   average operating margin) — extends the formula registry (Week 5n)
   beyond single-period ratios.
4. **DONE (round 3, Week 5o)** — Yes/No + one-line-justification judged
   questions — covered via the two segment-comparison questions, which
   are Yes/No-shaped ("did X have more revenue than Y").
5. **DONE (round 4, Week 5q)** — "Metric doesn't apply to this
   business" recognition — found a real forcing case after all:
   Palantir doesn't tag inventory at all (confirmed via `fetch_concept`
   returning 404), unlike the other four companies.
- **What we already do that FinanceBench doesn't**: zero of its 150
  answers are refusal-style ("not disclosed", "not available") — it
  doesn't test "recognize data genuinely isn't there, don't fabricate"
  at all. Our Q4-refusal/PLTR-dividend questions (and the Week 5m fix)
  are testing something this benchmark doesn't — keep investing here,
  it's a real differentiator, not a distraction from "real" eval growth.
- **Explicitly out of scope for now**: FinanceBench pulls some
  questions from 8-Ks; we only ingest 10-K/10-Q. Not extending ingestion
  for this — revisit once the core product is done and there's appetite
  to grow filing-type coverage generally, not as a side effect of eval growth.

### Eval growth round 3 — 21 → 25 questions, priorities 1 and 2 from the FinanceBench analysis (Week 5o)

Added 4 questions targeting the top two priorities from Week 5l's
FinanceBench analysis: 2 statement-scoped (a metric outside
`DEFAULT_METRIC_TAGS`, forcing unstructured retrieval), 2 same-company
segment comparisons (also covering priority 4, Yes/No-style judged
questions, since segment comparisons naturally fit that shape).
Ground truth verified directly against real retrieved chunks and/or
`fetch_concept()` before writing any question — same discipline as
every prior eval-growth round, not guessed:
- `nvda-total-assets-q1fy27`: $259,474M as of 2026-04-26, verified via
  `fetch_concept('NVDA', 'Assets')`.
- `aapl-cash-equivalents-q3fy2026`: $39,544M as of 2026-06-27, verified
  via `fetch_concept('AAPL', 'CashAndCashEquivalentsAtCarryingValue')`.
- `nvda-segment-revenue-comparison-q1fy27`: Compute & Networking
  $74,550M vs. Graphics $7,065M, quarter ended 2026-04-26 — verified
  against the exact "Revenue by Reportable Segments" table chunk.
- `msft-segment-revenue-comparison-q3fy2026`: Productivity and Business
  Processes $35,013M narrowly ahead of Intelligent Cloud $34,681M
  (More Personal Computing $13,192M), three months ended 2026-03-31 —
  deliberately close numbers, verified against one single table chunk
  containing all three segments together.

**Result: all 4 new questions FAIL, each for a different, real reason**
— not noise, and not something to "fix" by picking easier questions.
Original 21 held steady at 18/21 (same pre-existing, already-documented
local-model flakiness); nothing regressed.
- `nvda-total-assets-q1fy27`: complete miss. `total_assets` isn't in
  `DEFAULT_METRIC_TAGS`, and unstructured search genuinely can't find
  the balance sheet table for this query — confirmed directly with a
  standalone `hybrid_search()` call before writing the question, which
  returned inventory/goodwill/fair-value chunks instead, never the
  balance sheet. The live run fabricated numbers (6.0, 25797.0, 35665.0)
  from that irrelevant context, none matching the real $259,474M.
- `aapl-cash-equivalents-q3fy2026`: subtler. The model landed on the
  textually correct value (39,544) — retrieval CAN find the right
  chunk, confirmed directly beforehand — but the citation-verification
  gate caught that it wasn't actually grounded in the cited source. Real
  signal that retrievability alone doesn't guarantee correct attribution.
- `nvda-segment-revenue-comparison-q1fy27`: the model concluded both
  segments had *equal* revenue — a real misread of the segment table,
  not a defensible near-miss.
- `msft-segment-revenue-comparison-q3fy2026`: picked the wrong segment,
  and its cited figures ($45.7B, $38.9B, $18.2B) don't match any number
  in the real three-month table at all — suggests it may have pulled
  from a different period/table entirely rather than misreading close
  numbers.

**Decided: keep growing the eval set through the remaining
FinanceBench-informed priorities first, then fix the accumulated
findings one by one** (rather than stopping to fix each new failure as
it's found) — same reasoning as the very first XBRL-tool round: let
enough real findings accumulate before deciding what's worth building,
instead of reacting to one failure at a time.

### `eval_harness.py` — `--ids` / `skip` question filtering (Week 5p)

With eval questions now growing past what's comfortable to re-run in
full at local Ollama speed (each full 25-question run takes 25-30
minutes), added a way to run a specific subset instead of all-or-one:

- **`--ids id1,id2,...`** on `eval_harness.py`'s CLI — runs only the
  named questions, any count from one to many, in the file's own order
  (not the order given on the command line). Verified live: `--ids
  aapl-net-income-fy2025,nvda-revenue-fy26` ran exactly those 2 of 25,
  printed in file order.
- **Optional `"skip": true` field** on individual questions in
  `eval_questions.jsonl` — excluded from the default full run without
  deleting the question. `--include-skipped` forces them back in. Not
  applied to any of the Week 5o failures yet — that was a deliberate
  choice, not an oversight, since those are being tracked as findings
  to fix, not permanently parked.
- **Precedence, by design**: explicit `--ids` always wins over a
  question's own `skip` flag — asking for a question by ID is a
  stronger, more specific signal than the file's default, and is how
  you'd re-run a skipped question on demand without editing the file.
  An unknown ID raises immediately (`ValueError`, live-verified via the
  CLI) rather than silently running fewer questions than asked for.
- New pure helper `_select_questions(questions, ids, include_skipped)`
  in `eval_harness.py`, kept separate from `run_eval()`'s live-agent
  loop specifically so the filtering logic is unit-testable without any
  network/Ollama calls — 6 new tests, 179/179 full suite.

### Eval growth round 4 — 25 → 27 questions, priorities 3 and 5 from the FinanceBench analysis (Week 5q)

Added the remaining two priority items: a multi-year-average ratio
(beyond the formula registry's current single-period scope) and an
inapplicable-metric-recognition question. Ground truth verified before
writing, same discipline as every round:
- `aapl-3yr-avg-operating-margin-fy2023-fy2025`: 31.1%, computed from
  real unrounded per-year margins (29.82%, 31.51%, 31.97% — FY2023
  through FY2025, via `xbrl_facts.get_metric()` directly), not from
  averaging the formula registry's already-rounded 1-decimal outputs.
- `pltr-inventory-turnover-fy2025-refusal`: confirmed via
  `fetch_concept('PLTR', 'InventoryNet')` → 404 (not tagged at all,
  unlike NVDA/AAPL/MSFT which all tag it) — Palantir, as a
  software/data-analytics company, genuinely has no inventory line
  item to compute a turnover ratio from. Also confirmed live that
  `search_filings` returns nothing inventory-related for PLTR (cash
  flow tables, investment-agreement text) — there's no chunk to find
  because there's nothing to find.

**Both FAIL, in genuinely different, more specific ways than
predicted**:
- `aapl-3yr-avg-operating-margin-fy2023-fy2025`: the model completely
  **misparsed the question** — it interpreted "3-year average" as a
  request for Q4-specific figures, called `get_financial_fact` with
  `fiscal_period='Q4'` for FY2023/2024/2025, hit Week 5m's own
  Q4-not-disclosed hint, and echoed that hint's text verbatim as its
  final answer. A new bug class: multi-year-average questions get
  misread as intra-year quarterly ones, not (as expected) a rule-3
  self-computation violation.
- `pltr-inventory-turnover-fy2025-refusal`: closer to correct than a
  bare pass/fail suggests — it did say it couldn't compute the ratio —
  but never identified the *actual* reason (no inventory line item at
  all, structural to the business model), framing it as generic
  missing data instead, and pointlessly cited an unrelated cost-of-
  revenue figure ($192,934,000) as if relevant to an inventory
  question. Distinct failure shape from the Q4-refusal case: not
  fabrication, but an incomplete/imprecise refusal.

Neither yet addressed — added to the same accumulating-findings queue
as round 3 (Week 5o). All 5 FinanceBench-analysis priorities are done
as of this round. See "Next steps" at the top of this section for what
comes next (fixing these 6, then the still-open question-type gaps).

</details>

## Design principles to carry forward

- **Citations are non-negotiable.** In finance, "trust me" isn't good enough.
  Every numeric claim must trace to a specific filing + section, or the agent
  refuses. This becomes a hard guardrail in Week 7.
- **Evals before agent.** Measure first, then iterate.
- **Narrow scope, checkable outputs.** Numeric answers with exact figures are
  far easier to grade objectively than open-ended summaries.
- **Document failure modes.** The write-up value is in "here's what broke and
  how I found it," not "here's clean code."
