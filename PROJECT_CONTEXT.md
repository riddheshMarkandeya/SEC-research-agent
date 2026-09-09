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

**See `CLAUDE.md` for the full binding workflow** (design-before-building,
TDD, SE principles, debugging discipline, documentation, independent
review — each scoped by change size so trivial fixes aren't bogged down
by process meant for substantial features). Agreed with the user
2026-08-24. This section keeps the narrative/historical detail behind
the one rule that predates and motivated it:

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
well-known fiscal calendars) — see `tests/manual/verify_period_labels.py`
for the tool that checks this assumption against real evidence rather
than trusting it blindly. Re-run that script after adding a new company
or pulling in older historical filings, since that's exactly when the
risk of silently crossing an undetected fiscal-year change goes up.

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

**Retired, 2026-08-25 (see "Next steps" item 4).** `agent.py` is a
strict superset of what this did — no functional code imported
`answer.py` (only comments/docs referenced it; `eval_harness.py` had
already switched to `agent.run_agent()` back in Week 5), so this was a
pure deletion, not a migration. Removed `answer.py` itself and its
dedicated `tests/test_answer.py`; updated the stale `answer.py`
mentions in `config.py`, `requirements.txt`, and `.env.example` (all
comments, no behavior change). Verified via full suite: 253 passed
(down from 258, the 5 `format_context`/`format_citation_key` tests that
existed only to cover this file), no other regressions. This section
and the CLI usage above stay as the historical record of what it was;
the code no longer exists.

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
as of this round.

### Fixing the 6 accumulated eval findings (Week 5r)

Worked through all 6 findings from rounds 3/5o and 4/5q. **4 of 6
solidly fixed, 1 partially improved, 1 still open** — verified via
repeated live re-runs, not a single sample, given this whole batch
started from run-to-run flakiness.

**Solid fixes (3+ consecutive clean re-runs each):**
- `nvda-total-assets-q1fy27` + `aapl-cash-equivalents-q3fy2026`:
  added `total_assets`/`cash_and_equivalents` to `DEFAULT_METRIC_TAGS`
  (tags `Assets`/`CashAndCashEquivalentsAtCarryingValue`, verified clean
  across all 5 companies, no overrides needed — same discipline as
  `operating_income`). **Found a real, previously-unexercised bug along
  the way**: every metric this module supported before these two was an
  XBRL *duration* concept (revenue, income — has both `start` and
  `end`); balance-sheet items like these are *instant* concepts (a
  point-in-time snapshot, `end` only) — `_duration_days()` crashed with
  `TypeError`/`KeyError` on them. Fixed by having `_duration_days()`
  return `None` for an instant entry, and having `_pick_entry()`/
  `_pick_entry_by_end_date()`/`_latest_entry()` skip duration-bucket
  disambiguation for instant facts (unnecessary anyway — a point-in-time
  balance has no quarter-vs-YTD accumulation-window collision to
  disambiguate, unlike a duration fact). 6 new tests using real captured
  NVDA `Assets` data, 185/185 full suite.
- `nvda-segment-revenue-comparison-q1fy27` +
  `msft-segment-revenue-comparison-q3fy2026` (partially — see below):
  root-caused via a live `--verbose` repro, not guessed: the model
  invented a `segment` filter `get_financial_fact` has never supported,
  and the old code only ever read known keys (`args.get(...)`), so the
  invented key was silently dropped — both a "Compute & Networking" and
  a "Graphics" call silently returned the SAME consolidated total
  instead of erroring, and the model concluded the two segments had
  equal revenue. Fixed by rejecting any call containing an unrecognized
  key outright (`_FACT_ARG_KEYS`/`_COMPARE_ARG_KEYS` allow-lists on both
  `_call_get_financial_fact`/`_call_compare_financial_metric`), forcing
  a clean fallback to `search_filings` instead of a silently-wrong
  "success." `nvda-segment-revenue-comparison-q1fy27` went 3/3 clean
  after this fix (previously flaky: sometimes right via search_filings
  luck, sometimes badly wrong via the invented-param bug).
- `aapl-3yr-avg-operating-margin-fy2023-fy2025`: no deterministic path
  existed for an N-year average, so the model reached for
  self-computation on its own (once landing at 31.03% via 3 separate
  calls averaged in its own reasoning text — a rule-3 violation the
  citation gate correctly caught; once misparsing the whole request as
  Q4-specific, echoing Week 5m's own hint verbatim) — the exact same
  "model improvises the moment no tool exists" pattern that originally
  motivated the margin/yoy_growth formulas. Fixed by building
  `get_multi_year_average(ticker, metric, start_fiscal_year,
  end_fiscal_year)` in `formulas.py`, exposed on `get_financial_fact` as
  a `start_fiscal_year`/`end_fiscal_year` pair (same "alternate mode on
  the same tool" pattern as `yoy_growth`). Supports both margin ratios
  and raw metrics uniformly, unlike `yoy_growth` (raw metrics only) —
  the actual failing question needs a margin average. **Hit the exact
  `MARGIN_METRIC_FUNCTIONS`-style import-time-binding gotcha a third
  time** while building this: a `{metric: function}` dict built once at
  module load doesn't see a test's `monkeypatch.setattr("formulas.get_operating_margin",
  ...)` afterward — fixed by dispatching via a plain if/elif chain
  calling each function by its bare name instead of a dict, so every
  call re-resolves the name fresh from the module's current namespace.
  2/2 clean re-runs with the exact expected value (31.1%) after the fix.

**Partial improvement, not fully reliable:**
- `pltr-inventory-turnover-fy2025-refusal`: added `inventory` to
  `DEFAULT_METRIC_TAGS` (tag `InventoryNet` — verified clean for
  AAPL/MSFT/NVDA, and genuinely 404 for PLTR/CRM, a real fact about
  their business model, not a data-quality gap) plus a new
  `is_metric_tagged(ticker, metric)` helper and `_never_tagged_hint()`
  in `agent.py` that fires when a company never tags a metric at all
  (as opposed to just not having it for the asked-about period) —
  same "explain why, not just that" principle as the Q4 hint. **Works
  when exercised, but the model doesn't reliably reach it**: live
  testing showed it twice calling `get_financial_fact` with an invented
  metric name (`inventory_turnover_ratio`, not the schema's actual
  `inventory`) that gets rejected by the ordinary unsupported-metric
  check, never reaching the new hint at all. 1 PASS / 2 FAIL across 3
  live re-runs — a real, tested improvement (verified via direct
  `is_metric_tagged()` calls and a case where it did fire correctly),
  just not a full fix given this separate metric-naming-discoverability
  gap. Not investigated further this round.

**Still open, root cause not found:**
- `msft-segment-revenue-comparison-q3fy2026`: FAILED 3/3 times across
  this session, in 3 DIFFERENT ways each time — "no specific figures
  found," then answering about Apple instead of Microsoft entirely,
  then "doesn't correctly identify... nor provide exact figures." The
  boundary-validation fix that reliably fixed NVDA's equivalent segment
  question didn't reliably fix this one, and the failure shapes are too
  inconsistent to point at one specific mechanism yet the way the NVDA
  case's invented-`segment`-parameter bug did. Needs a dedicated
  `--verbose` investigation session, not more blind re-runs.

**Verified no regressions**: full 27-question re-runs after each fix
held the original 21 questions steady at their known baseline (same
pre-existing local-model flakiness on `aapl-employees-fy25`/
`msft-tax-rate-q2fy26`/the two comparison questions — confirmed via a
direct `--verbose` repro that one apparent new failure
(`aapl-operating-margin-q3fy2026`, self-computed 32.4% instead of the
tool-computed 32.6%) was pre-existing temperature variance, not caused
by the new `start_fiscal_year`/`end_fiscal_year` schema fields — a
clean re-run called the tool correctly with no extra keys). 202/202
unit tests.

### `discover_tags.py` — dev-time XBRL tag discovery (Week 5s)

Every entry in `xbrl_facts.py`'s `DEFAULT_METRIC_TAGS` so far (`total_assets`,
`cash_and_equivalents`, `inventory`, ...) got added the same way: an eval
question fails, then a manual guess-and-check against SEC's `companyconcept`
API confirms which tag to use. That loop only surfaces a missing metric
*after* something breaks. SEC's other XBRL endpoint, `companyfacts`,
returns every tag a company has EVER reported across all taxonomies in one
response (503 us-gaap tags for AAPL alone, ~3.8MB) — fetchable once and
browsable, turning "discover by failure" into "browse up front."

`discover_tags.py` wraps that endpoint: `fetch_company_facts(ticker)`
caches the full payload to `xbrl_cache/` (same directory, same
fetch-once-cache-forever rationale as `fetch_concept()`, since a past
period's SEC data never changes once filed), and `list_tags(ticker,
keyword=..., recent_only=..., taxonomy=...)` filters it down — by
substring, and/or to tags with at least one entry in the last ~400 days
(the same staleness trap `DEFAULT_METRIC_TAGS`'s own comment already
documents for `Revenues`: a tag existing doesn't mean a company still
reports it). Also runnable as a CLI: `python discover_tags.py PLTR
--keyword inventory`.

Deliberately NOT wired into `agent.py` or any runtime path — it's a
research tool you run by hand before writing or debugging an eval
question, not something the agent calls. Live-verified against real data:
`discover_tags.py PLTR --keyword inventory` returns 0 tags (confirming,
independently of `is_metric_tagged()`, that Palantir really has no
inventory-related concept at all), `discover_tags.py AAPL --keyword
inventory --recent-only` returns 3 (`InventoryNet` plus finished-goods/
raw-materials breakdowns not previously known about). 7 new tests
(`tests/test_discover_tags.py`), 209/209 full suite.

### `retrieval.py` — table-chunk rescue in reranking (Week 5t)

Root-caused `msft-segment-revenue-comparison-q3fy2026` (carried forward
from Week 5r) via a dedicated `--verbose` session, per the plan. NOT the
same bug as the NVDA segment question: the invented-`segment`-parameter
boundary-validation fix from Week 5r is still working correctly here too
(the model still invents `segment`, `_FACT_ARG_KEYS` still rejects it,
still falls back to `search_filings` as designed). The real failure is
downstream, in retrieval itself:

- The chunk with the real numbers ($35,013M/$34,681M/$13,192M) entered
  the fused BM25+vector candidate pool at a perfectly reasonable rank
  (#14 of ~40 -- both base retrievers considered it relevant) but the
  cross-encoder reranker (`cross-encoder/ms-marco-MiniLM-L-6-v2`) pushed
  it DOWN to #17 -- worse than its pre-rerank position, and outside
  top_n=5 -- in favor of near-duplicate MD&A boilerplate paragraphs
  repeated almost verbatim across 4 quarters' filings, which echo the
  question's segment names more than a dense numeric table does.
- No structured-XBRL escape hatch exists here the way there was for
  gross margin/R&D: `discover_tags.py MSFT --keyword segment --recent-
  only` confirms MSFT has no segment-revenue tag exposed via
  companyconcept/companyfacts (only `NumberOfReportableSegments`) --
  segment breakdowns are dimensional facts that API doesn't expose. This
  one had to be fixed in retrieval, not sidestepped.
- Fix: `_rescue_demoted_table_chunk()` in `retrieval.py`, called from
  `_combine_fused_and_rerank()`. If the reranker's own top_n contains no
  `contains_table` chunk at all, but one ranked in the top half of the
  fused pool (i.e. both base retrievers already considered it relevant),
  swap it in for the reranker's weakest surviving pick. Deliberately
  gated on the base retrievers' OWN pre-rerank confidence, not on
  guessing the question is fact/metric-seeking -- `hybrid_search` has no
  such signal at inference time, and pattern-matching question phrasing
  would repeat the same fragile-heuristic risk as the already-dropped
  `period_labels.py` reranking-signal idea. Self-limiting by
  construction: a table with no lexical/semantic match to a prose
  question (e.g. an AI-risk question) won't rank in the top half of the
  fused pool to begin with, so the rescue never fires for it.
- **Found a second bug while live-verifying the first fix**: MSFT's
  10-Qs also carry a recurring "Microsoft Cloud" metrics GLOSSARY table
  (term -> definition, zero `$` figures) that's ALSO flagged
  `contains_table=True` -- and being boilerplate repeated every quarter,
  it out-ranked the real segment-revenue table in the fused pool (rank 6
  vs rank 14). The first version of the rescue picked it by mistake,
  which would have surfaced a plausible-looking but useless table
  instead of failing loudly. Checked real chunk text directly: genuine
  financial tables had 32-37 `$` occurrences, the glossary table had 0.
  Added `_MIN_DOLLAR_FIGURES_FOR_TABLE_RESCUE = 5` as a cheap, general
  filter -- distinguishes "a table with actual reported figures" from "a
  table shaped like a table" without hardcoding any business-specific
  term.
- 8 new tests (`tests/test_retrieval.py`), including the exact glossary-
  vs-financial-table regression shape found live. 214/214 full suite.
- **Live-verified 4/4**: the correct chunk (right period, right figures)
  is now retrieved reliably (`python retrieval.py "..." --ticker MSFT
  --n 5` and 3x `python agent.py "..." --verbose`, plus the eval harness
  run itself) -- a real, solid fix for the retrieval-ranking problem this
  session set out to solve.

**But the question still FAILS** (`eval_harness.py --ids msft-segment-
revenue-comparison-q3fy2026`) -- for a new, different reason, exposed
only once the retrieval problem stopped masking it: the model
consistently (4/4 runs) states Intelligent Cloud ($34,681M) is the
highest-revenue segment despite Productivity and Business Processes
($35,013M) being right there in its own correctly-cited answer text --
a comparison/reasoning error, not a retrieval or citation problem this
time. Citation attribution was also inconsistent across runs (sometimes
every figure correctly cited to the table chunk, sometimes misattributed
to a descriptive chunk instead) -- a second, smaller open thread. Neither
investigated further yet; explicitly left open, reported to the user
rather than assumed-fixed.

**Full 27-question suite after the retrieval fix**: 22/27 passed (up
from 21/27) -- no regressions among previously-passing questions. The 5
fails are the same pre-existing baseline flakiness
(`aapl-employees-fy25`, `msft-tax-rate-q2fy26`,
`aapl-msft-employee-comparison`, `aapl-operating-margin-q3fy2026`) plus
`msft-segment-revenue-comparison-q3fy2026` itself, now failing on the
comparison-reasoning bug above instead of "no data found."
`pltr-inventory-turnover-fy2025-refusal` passed this run, consistent
with its documented ~1-in-3 flakiness (Week 5r), not caused by this fix.

### Root-causing the comparison-reasoning bug: local-model capability limit, confirmed (Week 5u)

Investigated the "correct numbers, wrong conclusion" bug above (not
blind re-runs -- three controlled, single-variable tests, per
systematic-debugging):

1. **One clean chunk (chunk 36, no % columns), nothing else in
   context.** 2/2 correct. Rules out a raw number-comparison failure
   and rules out the table's PercentageChange columns as the cause (my
   first hypothesis, disproven by evidence rather than assumed).
2. **The real 5-chunk search result, no other history.** 1/3 wrong --
   worse than one clean chunk, not as bad as the real failure rate.
3. **The full real conversation, including the model's own 3 earlier
   (rejected) `get_financial_fact` calls** -- one per segment, each
   naming a specific segment via the invented `segment` argument.
   3/3 wrong, one run hallucinating an unrelated sentence about NVIDIA.

Root cause: **self-consistency anchoring**, not arithmetic or
formatting. The model asks about "Intelligent Cloud" by name in its
own second tool call; by the time it writes the final answer, it
reconfirms that segment as significant regardless of the retrieved
numbers -- even while correctly transcribing the number that disproves
it. `_format_no_fact_message` never echoes `segment` back, so the bias
comes purely from the model rereading its own prior turns, not
anything the tool said.

Two candidate fixes considered, neither implemented:
- **System-prompt strengthening** (tried first, cheap): made the
  `get_financial_fact` bullet in `SYSTEM_PROMPT` explicitly say the
  tool cannot do per-segment/per-product lookups, naming the exact
  segments as an example. Live-tested 3x: **zero effect** -- the model
  still invented all 3 per-segment calls every run, and final-answer
  accuracy barely moved (1/3 correct vs. 0/4 before, not a real
  improvement at this sample size). Left in place (harmless, and a
  plausible aid for a more instruction-following model) but confirmed
  insufficient alone.
- **Sanitizing rejected calls before they enter message history**
  (proposed, not built): strip the invented `segment` key from what
  `run_agent` stores for a rejected call, so the model's own history
  doesn't repeat 3 distinct per-segment framings. Correctly pushed
  back on: this would rewrite what the model actually attempted,
  destroying the one source of ground truth (`--verbose` output) a
  future debugging session would need, and creating a gap between
  what a human reading the transcript sees and what the model
  reasoned over. Right call to not build this speculatively.

**Decisive test instead: same question, same agent scaffolding
(tool schemas, dispatch logic, retrieval), swapped to Gemini
(`spike_gemini_eval.py`, `gemini-flash-lite-latest`) instead of local
Ollama.** 3/3 correct. Gemini never attempted a per-segment
`get_financial_fact` call at all -- went straight to `search_filings`,
retrieved and cited the same table chunk (`[5]`, chunk 49) my Week 5t
retrieval fix surfaces, and named Productivity and Business Processes
correctly every time. This is conclusive, not just suggestive: the
retrieval fix is confirmed model-agnostic (Gemini benefits from the
exact same corrected chunk), and the remaining failure is a genuine
capability ceiling of `qwen2.5:7b-instruct` -- it invents a parameter
no model needed to invent, then can't be talked out of anchoring on
it. Not worth more prompt or history engineering on the local-model
path for this specific question; the real lever is the swappable-
backend work already on the roadmap (next steps item 2).

### Citation-verification retry loop, revisited against Gemini and gated (2026-08-25)

Week 5j built and reverted a one-time self-correction retry: when
`run_agent()`'s final answer had an unverified citation (per
`verify_citations()`), feed the model its own draft plus the specific
warnings and let it retry once. It was reverted back then because
`qwen2.5:7b-instruct` couldn't reliably act on the feedback -- see that
section above for the two documented failure modes (giving up instead
of checking already-retrieved chunks; fabricating an estimate under a
"final attempt" framing). Revisited now that the swappable-backend work
(merged `863bf03`) makes Gemini available, per that work's own explicit
follow-up note. Full design: `docs/plans/2026-08-24-
citation-retry-loop-design.md`.

- **Rebuilt against the new backend interface.** `llm_backends.py`
  gained a third per-backend function, `send_followup(state, text) ->
  ModelTurn` (`_ollama_send_followup`/`_gemini_send_followup`), since
  the retry fires only after the model has already stopped calling
  tools -- there's no tool call left to attach a result to, so
  `send_tool_results` can't express it. `BACKENDS`' tuples are now
  `(start, send_tool_results, send_followup)`.
- **Two new pure, TDD-first helpers in `agent.py`**:
  `_should_retry_for_citations(citation_warnings, already_retried,
  backend)` (capped at one retry, and gated -- see below) and
  `_format_citation_retry_message(answer, citation_warnings)`. The
  retry message's wording directly targets Week 5j's two failure modes:
  it explicitly tells the model to recheck search results ALREADY shown
  earlier in the conversation before concluding a value isn't
  supported, explicitly states an honest refusal is a fully acceptable
  outcome, explicitly forbids inventing/estimating a replacement
  number, and deliberately contains NO "final attempt"/deadline-pressure
  language -- a unit test (`test_format_citation_retry_message_never_
  uses_final_attempt_deadline_pressure`) asserts that phrasing's absence
  as a standing regression guard.
- **Live-verified, not assumed.** Repro'd the two current-at-the-time
  Gemini eval warnings before writing any code: `aapl-msft-tax-rate-
  comparison` (a genuine apparent misattribution -- the answer cited
  the wrong AAPL chunk for a $6,478M figure) and `aapl-3yr-avg-
  operating-margin-fy2023-fy2025` (confirmed, by reading the actual
  chunk text, to be unrelated checker noise: the phrase "3-year
  average" contributes a bare "3" the checker misreads as a claim --
  explicitly out of scope, not something this change could or should
  fix). Ran the motivating question live 7 times against Gemini: the
  misattribution reproduced twice, the retry fired both times, and
  fixed it once but not the other (the second attempt re-cited a
  *different* wrong chunk) -- a real, partial improvement, not a full
  fix, but critically **neither retry attempt gave up or fabricated a
  number**, unlike every Ollama failure mode Week 5j found.
- **Full-suite re-runs, both backends, same day:**
  - Gemini (`eval_results/20260825T003901Z.json`): 26/27 passed, same
    as the pre-change baseline. The motivating misattribution
    (`aapl-msft-tax-rate-comparison`) is clean in this run. A different
    question (`crm-rpo-fy26`) picked up a new warning, traced to the
    same checker-noise class as above: Gemini wrote citations as
    `[1, 2]` in one bracket (not `[1][2]` per rule 8's wording), and the
    literal "2" inside that text got misread as a claim -- confirmed by
    reading the actual chunk text (contains the real $72.4B/$35.1B/
    $37.3B figures correctly) and the raw answer text, not assumed.
  - Ollama (`eval_results/20260825T011459Z.json`): 21/27 passed, vs.
    the pre-change baseline's 20/27 -- one question flipped FAIL->PASS
    (`nvda-crm-revenue-comparison`), zero flipped PASS->FAIL. The two
    Q4-hint-bleeding-into-Q2/Q3 answers were compared word-for-word
    against the pre-change baseline and are an identical, pre-existing
    bug, unrelated to this change.
- **Decision: gated to Gemini only** despite this run showing no
  Ollama regression (`_CITATION_RETRY_BACKENDS = {"gemini"}` in
  `agent.py`, consumed by `_should_retry_for_citations`). User's call,
  made explicitly after seeing the live Ollama results: Week 5j's
  documented history against this exact mechanism, plus Ollama's own
  known run-to-run noise on comparison-shaped questions, outweighs one
  clean re-run. If Ollama is ever revisited for this, the gate is one
  line to remove, and the design/tests already generalize to it.
- **A real bug found in the mandated independent review pass (CLAUDE.md
  step 6), not live testing:** if the citation retry fired on the
  second-to-last iteration and the model's follow-up turn made a NEW
  tool call instead of just re-answering, `run_agent()`'s loop hit the
  iteration cap on that tool call and fell through to the generic
  "wasn't able to finish" message -- discarding an already-produced,
  merely-warned answer that was perfectly fine to return as-is. Fixed
  by preserving the pre-retry `(answer, warnings)` pair and returning it
  instead of the timeout message if the budget runs out after a retry
  was attempted. Unlike the rest of `run_agent()`'s loop, this exact
  control-flow shape is deterministic given a scripted turn sequence,
  so it's covered by two real unit tests
  (`test_run_agent_citation_retry_exhausting_budget_returns_pre_retry_
  answer_not_timeout`, plus a sibling confirming `send_followup` is
  never even called for the gated-out `ollama` backend) driving
  `run_agent()` through monkeypatched `BACKENDS` entries, rather than
  left to live verification alone.

### Eval set grown 27 → 35 questions: multi-statement ratios, cross-section synthesis, indirect disambiguation (2026-08-25)

Targeted the three gap categories "Next steps" item 3 had flagged from
the FinanceBench analysis, each chosen to isolate one specific untested
variable rather than just adding volume. All 8 ground-truthed against
real data (`xbrl_facts.get_metric()` calls and direct reads of actual
chunk text) before writing, same discipline as every prior round.

- **Multi-statement ratios (3 questions), no formula-registry tool
  support for any of them** — `aapl-return-on-assets-fy2025` (net
  income ÷ total assets, income statement + balance sheet),
  `nvda-asset-turnover-fy2026` (revenue ÷ total assets),
  `msft-cash-to-assets-fy2025` (cash ÷ total assets). Deliberately left
  unsupported by any tool, mirroring the exact discipline that
  justified building the margin-formula registry (Week 5k): let the
  agent's actual behavior with no deterministic path be the evidence,
  don't pre-build.
- **Pure unstructured multi-chunk synthesis (2 questions)** — two facts
  from genuinely different sections of ONE filing, not a single table:
  `aapl-cash-and-buyback-q3fy2026` combines the balance-sheet cash
  figure with the Item 2 (equity securities) share-repurchase-remaining
  figure; `crm-buyback-and-liquidity-q1fy27` combines Salesforce's own
  buyback-remaining figure with an MD&A "Interest Rate Sensitivity"
  cash-plus-marketable-securities figure. Both real, verified by reading
  the actual chunk text directly (`chunks/AAPL/..._chunks.jsonl` chunk
  40, `chunks/CRM/..._chunks.jsonl` chunks 41/77) — not assumed from
  table structure. Graded via the existing `"comparison"` type/
  `grade_comparison()` (an intentional reuse: nothing about that grader
  actually requires the two `expected` entries to be different
  companies, just that each value appears and is properly cited — the
  `ticker` field in each `expected` entry is purely a human-readable
  label, e.g. `"AAPL-buyback-remaining-availability"`, not a real
  ticker) — no eval-harness code changes needed.
- **Indirect/no-explicit-name company disambiguation (3 questions)** —
  reuses already-ground-truthed facts from existing questions
  (`nvda-revenue-fy2026-indirect`, `aapl-employees-fy25-indirect`) plus
  one new one (`msft-net-income-fy2025-indirect`), each phrased via a
  description ("the semiconductor company best known for the GPUs...",
  "the company that makes the iPhone and the Mac...") instead of naming
  the company — isolates disambiguation as the one changed variable
  against facts whose retrieval is already proven to work, per this
  project's own isolate-one-variable debugging discipline.
- **A real bug found in my own question, not the agent, before the full
  run even happened:** `nvda-asset-turnover-fy2026`'s first draft used
  `expected_unit: "percent"` (104.4), but asset turnover is
  conventionally expressed as a decimal ratio ("1.04x"), and
  `numeric_utils.normalize()` treats `"percent"` and `"raw"` as
  different, never-cross-matching categories regardless of numeric
  equivalence (104.4 vs 1.044 are the same ratio, different
  categories). Live-verified before fixing: Gemini's real answer stated
  "approximately 1.04 (or 1.044)", confirming the natural phrasing
  doesn't match a percent-typed question at all. Fixed by changing
  `expected_unit` to `"raw"`, `expected_value` to `1.04` — same
  "test the test" discipline as `grade_judged()`'s and
  `verify_citations()`'s own past bug fixes.
- **Full-suite results, both backends:**
  - Gemini (`eval_results/20260825T022950Z.json`): **33/35 passed, 8/8
    of the new questions passed cleanly with proper citations.** The 2
    failures are both pre-existing, unrelated to this round — confirmed
    by checking history, not assumed:
    `aapl-3yr-avg-operating-margin-fy2023-fy2025` failed here (this
    exact question already failed twice before, on 2026-08-19, well
    before this session — a known temperature-0.1 instruction-following
    flake on the multi-year-average tool arguments) and
    `pltr-dividend-2019-refusal` is the long-documented "$0" grading
    technicality (Week 5l).
  - Ollama (`eval_results/20260825T044611Z.json`): **23/35 passed, only
    2/8 of the new questions passed.** Among the original 27 questions,
    21/27 passed — statistically identical to the immediately-prior
    Ollama baseline (also 21/27), with exactly the same two
    comparison/segment-shaped questions swapping which side of the line
    they're on (`nvda-crm-revenue-comparison` and
    `nvda-segment-revenue-comparison-q1fy27`) — the same
    already-documented run-to-run noise pattern, not a regression from
    this round's changes.
- **Several genuinely new Ollama failure modes surfaced, each verified
  against real data rather than guessed at:**
  1. `aapl-return-on-assets-fy2025` **answered about the wrong company
     entirely** — the answer opens "Based on the provided information
     from Microsoft Corporation's filings" and computes a ratio from
     MSFT's real total-assets figure ($619,003M, confirmed to be
     MSFT's actual FY2025 value) despite the question asking only about
     Apple, with no ambiguity. A new failure class, not previously
     catalogued: this is the first observed case of `qwen2.5:7b-instruct`
     answering a different company than the one asked about outright,
     as opposed to the previously-known failure modes (self-consistency
     anchoring on an invented parameter, misattributed citations,
     Q4-hint bleeding into other quarters).
  2. `msft-cash-to-assets-fy2025` **used numbers that don't correspond
     to any real MSFT period** — checked total_assets across 7 nearby
     quarters/years via `get_metric()`, none match the stated $371,902M
     figure — appears to be a fabricated/hallucinated value the model
     then confidently divided, rather than a simple wrong-period mixup.
  3. `aapl-cash-and-buyback-q3fy2026` **retrieved a stale prior-year
     figure and self-computed a wrong workaround** instead of reading
     the current quarter's own directly-disclosed remaining-availability
     figure: it cited the June 28, 2025 10-Q's $19.8B figure, then
     computed `$100B - $25.8B = $74.2B` (the correct answer, $38.0B, is
     directly stated in the current 10-Q and never needed any
     arithmetic at all).
  4. `crm-buyback-and-liquidity-q1fy27` **used the wrong tool for the
     liquidity figure** — its stated $8.94B exactly matches CRM's real
     `cash_and_equivalents` XBRL value (confirmed via `get_metric()`),
     which excludes marketable securities, instead of the $11.8B
     combined "cash, cash equivalents and marketable securities" figure
     the question specifically asked for and that's only stated in
     prose. A precise, real example of the agent reaching for a
     structured tool that returns a *related but narrower* metric than
     what was actually asked.
  5. Both `nvda-asset-turnover-fy2026`'s and (via the direct question)
     other self-computed ratios were correctly flagged by the
     citation-verification gate on Ollama (it attached a citation to
     its self-computed 1.04 that doesn't contain that number) — but the
     *same* self-computation on Gemini slipped through ungated, because
     Gemini's version stated the ratio with **no citation marker
     attached to it at all**, and `verify_citations()`'s heuristic only
     checks numbers sitting near a citation marker; an uncited number
     has nothing to contradict, so it defaults to "nothing to verify."
     **This is a real, newly-surfaced gap** in the citation-verification
     heuristic, distinct from (worse than) the already-documented
     multi-step-derivation limitation: it's not that intermediate
     numbers leak into a legitimate citation's window, it's that a
     specific numeric claim can dodge the check entirely by simply not
     citing anything. Flagged here for a future decision, not fixed in
     this round — consistent with letting real evidence decide before
     building, same as the formula-registry deferrals.
  6. `aapl-employees-fy25-indirect`'s failure is **not new** — it got
     the right value (166,000) from the right-looking source, but
     failed the exact same citation-verification check, in the exact
     same run, as the original direct-phrased `aapl-employees-fy25`
     question. This confirms the indirect-disambiguation questions
     genuinely isolated the one variable they were meant to test:
     company resolution itself worked correctly in every one of the 3
     indirect questions on both backends; the one failure is
     inherited, pre-existing citation flakiness, unrelated to indirect
     phrasing.
- **Conclusion**: this round's clearest finding is that Gemini's
  already-established advantage generalizes to three genuinely new
  question shapes this project had never tested before (8/8 clean vs.
  2/8), and it does so not just by avoiding known failure patterns but
  by avoiding entirely new ones this round surfaced for the first time
  (wrong-company answers, fabricated numbers, stale-period retrieval,
  tool-selection mismatches) — further evidence for the Week 5u/
  swappable-backend diagnosis that these are `qwen2.5:7b-instruct`
  capability-ceiling issues, not retrieval or system-design gaps, since
  retrieval and tools were held constant and only the answering model
  changed.

**Addendum, 2026-08-25 — eval set grown 35 → 38: cross-company ranking
via `compare_financial_metric`.** Prompted by looking at the PIXIU/
FinBen benchmark (`the-finai/pixiu` on GitHub) for question-shape ideas:
its FinQA/TatQA/ConvFinQA tasks weren't directly portable (their ground
truth is against different source documents, not this project's own
5-company corpus — the same reason no other external benchmark's raw
Q/A pairs get imported here), but comparing PIXIU's coverage against
this project's own `compare_financial_metric` tool turned up a real
gap: the tool has explicit system-prompt support for cross-company
ranking ("which company had the highest gross margin" is its own
worked example, agent.py:105) but zero eval questions exercised that
code path before this. Added 3 `judged`-type questions, one per margin
already in the formula registry — `five-company-gross-margin-ranking-
fy2025` (highest → PLTR, 82.4%), `five-company-operating-margin-
ranking-fy2025` (lowest → CRM, 20.1%), `five-company-net-margin-
ranking-fy2025` (highest → NVDA, 55.6%) — deliberately spread across
different correct answers and both "highest"/"lowest" phrasing so a
model can't pattern-match its way to a pass.

- **Ground truth**: `get_{gross,operating,net}_margin_all_companies("AAPL", fiscal_year=2025, fiscal_period="FY")`
  — real computed values from ingested XBRL data, not guessed.
- **A real ambiguity surfaced and fixed before finalizing, not just a
  phrasing nitpick.** The first draft phrased the question as "using
  Apple's fiscal year 2025 as the reference period" for all five
  companies. Live-verified against Gemini: this failed outright once
  (ran out of the 6-call tool-iteration budget) and on a second manual
  run reached the right company (NVIDIA) via the wrong period — it
  called `get_financial_fact` with NVDA's own fiscal_year=2025 (period
  ended 2025-01-26, value 55.8%) instead of the calendar-matched period
  that's actually contemporaneous with Apple's FY2025 (NVDA's own
  fiscal_year=2026, ended 2026-01-25, value 55.6% — the same period
  `compare_financial_metric`'s frame-based cross-company matching
  returns, and the same period this eval file already calls "fy2026"
  everywhere else, e.g. `nvda-revenue-fy2026-indirect`). This is the
  same fiscal-year-label-vs-calendar-frame mismatch `companies.py` and
  `period_labels.py` already exist to guard against, just hit from a
  new angle (a shared ranking question across 5 non-calendar-aligned
  fiscal years) rather than a single-company date lookup. Fixed by
  spelling out each company's own correctly-labeled fiscal year and end
  date directly in the question text instead of a single blanket label
  — re-verified live, 3/3 passed on Gemini with values matching ground
  truth exactly (`eval_results/20260825T233524Z.json`).
- **Not run against Ollama** — the existing 27→35 round already
  established the Gemini-vs-Ollama gap on comparison-shaped questions
  generally; no code changed here, only new question data, so there's
  no regression risk to the other 35 questions from this addition and a
  full-suite re-run wasn't needed to confirm that.
- One `verify_citations()` unverified-citation warning appeared on the
  gross-margin question, referencing numbers not present in the actual
  answer text — looks like the already-known `verify_citations()` gap
  (Next steps item 3's addendum, above) rather than a new issue; not
  chased further here since it didn't affect the judged pass/fail.

### Formula registry extended: return_on_assets, asset_turnover, cash_to_assets (2026-08-25)

Closes out the citation-verification-gap decision from the eval-growth
round above by removing its root cause for these three ratios: no
deterministic tool existed, so the model reached for self-computation.
Same discipline that originally justified the margin registry (Week
5k) -- these three multi-statement questions had already generated real
evidence of what the agent does without a path (a wrong-company answer,
a self-computed-and-uncited ratio), so building the tool was justified
by demand already observed, not speculative.

- **`formulas.py`**: `_compute_ratio_metric()` gained an `as_percent`
  flag (default `True`) -- `asset_turnover` is the first ratio in this
  module that isn't a percent (conventionally "1.04x", not "104%");
  getting this wrong isn't just cosmetic, `numeric_utils.normalize()`
  treats `"percent"`/`"raw"` as different, never-cross-matching
  categories, which is exactly the bug already caught and fixed in the
  eval question itself before this tool existed (see the eval-growth
  section above). `get_return_on_assets` (net income ÷ total assets),
  `get_asset_turnover` (revenue ÷ total assets, `as_percent=False`),
  `get_cash_to_assets` (cash ÷ total assets) are the first ratios in
  this module combining a DURATION income-statement metric with an
  INSTANT balance-sheet one (or two instant metrics) -- `get_metric()`
  already normalizes both shapes to the same `{"value", "period_end",
  ...}` dict, so no new code was needed for this combination. Confirmed
  for one real example (AAPL FY2025: both `net_income` and
  `total_assets` report `period_end="2025-09-27"`) -- not proven to
  hold for every company/year, and doesn't need to be: this is exactly
  what `_compute_ratio_metric`'s existing `numerator["period_end"] !=
  denominator["period_end"]` check already guards, returning `None`
  gracefully on the (unobserved so far) case where a duration and
  instant fact's period ends don't line up, rather than assuming they
  always will.
- **Deliberately no cross-company `_all_companies` counterpart for any
  of the three** -- confirmed via a live check, not assumed: an annual
  instant fact's SEC-assigned `frame` is `None` (verified: AAPL FY2025
  `total_assets`'s own `frame` is `None`), so there's no frames-API
  bucket to anchor a cross-company query on, and even borrowing a
  substitute frame label from a duration numerator wouldn't resolve
  correctly -- SEC's frames API uses a different label format for
  instant concepts entirely. No current eval question needs this
  anyway. `agent.py`'s `SINGLE_COMPANY_RATIO_FUNCTIONS` (plain
  functions, not tuples) keeps these three separate from
  `RATIO_METRIC_FUNCTIONS` (renamed from `MARGIN_METRIC_FUNCTIONS`,
  which stayed margins-only) for exactly this reason --
  `compare_financial_metric`'s own boundary check only ever looks at
  `RATIO_METRIC_FUNCTIONS`, so a `SINGLE_COMPANY_RATIO_FUNCTIONS`-only
  metric name falls through to the same graceful "not supported" `{}`
  any other unrecognized metric gets, rather than a crash.
- **A real crash risk found and closed before it could ever fire**:
  adding these three names to a metric-functions dict makes them pass
  `_call_get_financial_fact`'s boundary check, which means a
  multi-year-average request combined with one of them would now reach
  `get_multi_year_average()` -- which would otherwise crash inside
  `get_metric()`'s tag lookup (`_tag_for()` raises `ValueError` for any
  name that isn't a raw GAAP tag), the exact "unhandled crash on
  unsupported metric" bug class already fixed twice before in this
  project. Closed by extending `formulas._get_annual_value()`'s
  dispatch with a branch for each of the three, mirroring its existing
  margin branches -- covered by regression tests before this was ever
  exercised live.
- **Live-verified, not just unit-tested.** Ran all three motivating
  questions directly against Gemini: `aapl-return-on-assets-fy2025` and
  `nvda-asset-turnover-fy2026` both resolved via a single clean
  `get_financial_fact` call with an exact, properly-cited value every
  time tried. `msft-cash-to-assets-fy2025` was more mixed across 4
  manual runs -- 2 called the new `cash_to_assets` tool and got a
  properly-cited answer, 2 still self-computed from two separately-
  retrieved raw values with no citation on the derived percentage
  (reproducing the exact gap this tool was built to close) -- **building
  the tool helps when the model actually reaches for it, but doesn't
  guarantee it will every time**, the same caveat this project has
  already found for other tool additions (e.g.
  `pltr-inventory-turnover-fy2025-refusal`).
- **Full-suite results, both backends, same day:**
  - Gemini (`eval_results/20260825T190858Z.json`): **34/35 passed** (up
    from 33/35), all three new ratio questions passed cleanly with
    zero citation warnings. The only fail
    (`aapl-3yr-avg-operating-margin-fy2023-fy2025`) is the same
    pre-existing temperature-0.1 flake already confirmed against
    history in the eval-growth section above. The 2 unverified
    citations this run (`crm-rpo-fy26`, `crm-ai-risk`) are the same
    already-documented bracket-formatting checker-noise class
    (Gemini's `"[4, 10]"`-style citations leaking a stray digit into a
    claim window), not new problems.
  - Ollama (`eval_results/20260825T195207Z.json`): **26/35 passed** (up
    from 23/35). Diffed question-by-question against the immediately
    prior Ollama run: `aapl-return-on-assets-fy2025` and
    `nvda-asset-turnover-fy2026` both flipped FAIL→PASS -- direct,
    attributable fixes, not noise (the ROA question no longer answers
    about Microsoft when asked about Apple; the asset-turnover question
    no longer self-computes with an unverifiable citation). Two other
    questions also flipped FAIL→PASS
    (`aapl-msft-tax-rate-comparison`, `nvda-crm-revenue-comparison`) and
    one flipped PASS→FAIL (`pltr-inventory-turnover-fy2025-refusal`) --
    all three are the same already-documented comparison/refusal-shaped
    run-to-run noise this project has characterized repeatedly, unrelated
    to this change. `msft-cash-to-assets-fy2025` stayed FAIL: the saved
    answer text contains no XBRL-tool-sourced figures and reads as a
    `search_filings`-only response (a wrong/unverifiable cash number,
    the model explicitly saying it can't find total assets to compute
    the ratio) -- inferred from the answer's own content, since
    eval_results JSON doesn't record a tool-call trace to confirm this
    directly. Reads as the same broader capability-ceiling pattern
    already established for this backend, whatever the exact mechanism.
- **Net result**: 2 of 3 target questions cleanly and repeatably fixed
  on both backends; the third (`cash_to_assets`) is a real, partial
  improvement -- the tool works correctly whenever either backend
  reaches for it, but tool-selection reliability (not the tool itself)
  remains the open variable, same class of gap already documented for
  Ollama's other tool-adoption misses.

### `mcp_server.py` (Week 6) — MCP server exposing all 3 agent tools over Streamable HTTP (2026-08-25)

Exposes `search_filings`/`get_financial_fact`/`compare_financial_metric`
to any MCP client (Claude Desktop, Claude Code, another agent), not
just this project's own `agent.py` tool-calling loop. Scoped and
designed conversationally before building (Substantial-tier, per the
workflow rules) — two real forks were resolved with the user before any
code was written: HTTP transport (chosen over stdio, since a future web
UI is planned on the same server) and plain structured JSON results
with no `[n]` citation numbering (chosen over agent.py's own
citation-marker framing, which is specific to that module's own
system prompt, not something a generic MCP client expects).

- **Reuses agent.py's existing tool logic and schemas rather than
  duplicating them.** `_call_get_financial_fact`/
  `_call_compare_financial_metric` renamed to public
  `call_get_financial_fact`/`call_compare_financial_metric` (mechanical
  rename — now genuinely used by two callers, so they stop being
  private; already covered by `tests/test_agent.py`, no new tests
  needed for the rename itself). `SEARCH_TOOL_SCHEMA`/`FACT_TOOL_SCHEMA`/
  `COMPARE_TOOL_SCHEMA`'s `parameters` dicts are passed straight through
  as each MCP `Tool`'s `input_schema` — this is why the low-level
  `mcp.server.Server` API was used instead of `FastMCP`: FastMCP derives
  a tool's schema from Python type hints/docstrings, which would mean
  maintaining these already-hardened, failure-tuned descriptions (e.g.
  "never invent an extra filter argument") a second time.
- **Every tool result carries an always-present `source` block** —
  ticker, form, period, accession, and a real `sec_url` — rather than
  gating it behind an opt-in flag. Matches how every reference
  information-retrieval MCP server behaves (checked `brave-search`'s
  own reference implementation: every result unconditionally includes
  `Title/Description/URL`, no toggle) — a fact an LLM can't trace back
  to its source isn't very useful to something that needs to cite it.
- **`sec_url` construction needed no new ingestion work.** Found that
  `edgar_ingest.py` already stores `cik` and `primaryDocument` in every
  filing's `_meta.json` (needed to fetch the HTML in the first place),
  and already had the exact URL formula in `fetch_filing_html()`.
  Extracted that formula into `_filing_document_url()` and added a
  public `get_filing_url(ticker, accession) -> str | None` that reads
  the already-on-disk `_meta.json` directly — no scan, no cache, no new
  network call. Both single-company (`get_financial_fact`, chunk
  metadata's `accessionNumber`) and cross-company
  (`compare_financial_metric`'s per-ticker `accession` via
  `xbrl_facts.get_frame()`) paths already carry what this needs.
- **`search_filings` citations additionally get a browser-native
  "Scroll To Text Fragment" (`#:~:text=`) anchor**, confirmed
  well-supported as of this session (Chrome 80+, Edge 83+, Firefox
  131+, Safari 16.1+) — so a human clicking through from a future web
  UI lands on the cited sentence, not the top of a 100+ page filing. Not
  attempted for `get_financial_fact`/`compare_financial_metric`: those
  come from structured XBRL, not chunked prose, so there's no position
  to anchor to (an XBRL-viewer-level deep link would need parsing each
  filing's own inline-XBRL markup or `FilingSummary.xml` — real,
  non-trivial ingestion work with no concrete need yet, deferred same
  as the other "let evidence decide" items above).
- **Two design mistakes caught and fixed before finalizing, not after:**
  1. Originally gated the text-fragment on the whole chunk's
     `contains_table` flag (true if `<TABLE>` appears *anywhere* in the
     chunk). Caught in review: a mostly-prose chunk with one small
     embedded table would wrongly lose its fragment entirely. Fixed to
     check the EXCERPT itself for `<TABLE>`, not the whole chunk —
     covered by `test_text_fragment_excerpt_kept_when_table_marker_is_
     past_the_excerpt`.
  2. Originally planned to extract "the first sentence" as the excerpt.
     Caught in review: these are financial filings full of numbers like
     "$72.4 billion" — a period-based sentence-splitter would frequently
     cut mid-number. Replaced with a fixed-length (100 char),
     word-boundary-truncated prefix instead, which needs no sentence
     detection at all.
- **Percent-encoding double-checked, not assumed.** The text-fragment
  spec gives `-` and `,` syntactic meaning (prefix/range separators).
  Confirmed live that Python's `urllib.parse.quote()` never encodes `-`
  regardless of `safe=`, but does encode `,` by default — and the
  spec's actual ambiguous pattern requires an *unencoded* comma
  adjacent to a hyphen (`-,` or `,-`), which can't survive once commas
  are encoded. No special-case hyphen escaping needed; verified this
  reasoning against the real live text-fragment match below rather than
  trusting the argument alone.
- **Live-verified end-to-end** via `tests/manual/verify_mcp_server.py`
  (new, re-runnable, same convention as `verify_period_labels.py`): starts
  the real server as a subprocess, connects with the real `mcp` client
  over genuine HTTP (not mocked), and checks (1) `list_tools()` returns
  exactly the 3 tools, (2) `get_financial_fact`/`compare_financial_
  metric` values match already-ground-truthed data (AAPL revenue
  FY2025 = $416,161,000,000; the 5-company gross-margin ranking from
  `eval_questions.jsonl`), (3) every returned `sec_url` is a real,
  live, fetchable SEC EDGAR URL via an actual HTTP GET — not just
  structurally plausible, (4) a `search_filings` result's text-fragment
  excerpt literally appears verbatim in the live filing page's fetched
  text, as a proxy for "a real browser will actually highlight this."
  All checks passed on the first fully-corrected run
  (`fix client's 2-tuple vs. expected 3-tuple unpacking, fix the
  verification script's own wrong assumption that get_financial_fact
  returns display-scaled "million" units instead of raw USD — both
  script bugs, not `mcp_server.py` bugs, caught by the live run itself).
- **New dependency**: `mcp==2.1.1` (pulls in `starlette`+`uvicorn` as
  its own declared dependencies — nothing extra to pin).
- **Explicitly out of scope for this round**: auth and rate-limiting on
  the HTTP server (Week 7's guardrails item); XBRL-fact-level deep
  linking beyond the plain filing URL (no concrete need yet).
- Full suite: 275/275, no regressions.

### Repo folder reorganization: verify_*.py → `tests/manual/`, eval data → `eval/` (2026-08-26)

Pure structural cleanup for legibility, no behavior change. The repo
root had accumulated two kinds of clutter: two standalone live-
verification scripts (`verify_mcp_server.py`, `verify_period_labels.py`)
sitting next to the pytest suite in spirit but not in location, and the
eval harness's input/output data (`eval_questions.jsonl`, 45 tracked
`eval_results/*.json` reports) mixed in with top-level code scripts.

- **`verify_mcp_server.py`/`verify_period_labels.py` → `tests/manual/`**
  (`git mv`, history preserved). Neither script is imported anywhere as
  code (confirmed before moving) — both are standalone, run-by-hand
  tools. Each needed a one-line `sys.path.insert(0, ...)` shim added
  right after its docstring: empirically confirmed that `python
  tests/manual/verify_x.py` sets `sys.path[0]` to the script's own
  directory, not the CWD, which would otherwise break their `from
  config import ...`/`from period_labels import ...`/`from xbrl_facts
  import ...` lines. Their own internal relative paths (`Path("./data")`,
  `subprocess.Popen([sys.executable, "mcp_server.py", ...])`) needed no
  change — those are CWD-relative, not `__file__`-relative, and both
  scripts are still meant to be run from the repo root, same as every
  other script here. Re-ran both live after the move to confirm: both
  produce the same correct output as before (`verify_period_labels.py`:
  5/5 companies confirmed, no mismatches; `verify_mcp_server.py`: all
  checks pass, including the live SEC EDGAR fetches).
- **`eval_questions.jsonl` + `eval_results/` → `eval/`** (`git mv`,
  history preserved for all 46 files). `eval_harness.py` itself stays at
  the repo root — only its two path constants
  (`QUESTIONS_PATH`/`RESULTS_DIR`) changed to point into `eval/`. Every
  existing `python eval_harness.py ...` invocation keeps working
  unchanged. Deliberately did NOT move `eval_harness.py` itself: a
  direct `python eval/eval_harness.py` invocation would break its own
  `from agent import ...`-style imports for the same sys.path reason
  above, which would have meant switching to `python -m eval.eval_harness`
  everywhere — a real workflow change for no real benefit, whereas
  keeping the harness at the root and moving only its data matches this
  repo's existing pattern of top-level data folders (`data/`, `chunks/`,
  `chroma_db/`, `xbrl_cache/`) sitting alongside top-level code scripts.
  Re-ran `eval_harness.py --ids <question>` live after the move to
  confirm it still finds the questions file and writes into the new
  `eval/eval_results/` location.
- `tests/test_eval_harness.py` needed no change — it already
  monkeypatches `RESULTS_DIR` to a `tmp_path` rather than depending on
  the real path.
- **Historical prose mentions of the old paths are deliberately left
  unchanged** — the ~50 references in this doc's older Week 3-5
  write-ups and the ~41 in `docs/superpowers/*.md` describe what was
  true at the time, same "git history and the `###` sections are the
  changelog, not rewritten after the fact" treatment already given to
  the `answer.py` retirement's historical section. Only the two *live*
  cross-references meant to be followed right now (the
  `companies.py`/`fiscal_year_end_month` note above, and this section's
  own sibling above it) were updated to the new paths.
- Full suite: 275/275, no regressions (nothing in `tests/*.py`
  references these moved paths directly).

### Week 7 guardrails, part 1: citation hard-gate + Ollama retry/backoff (2026-08-26)

Two of the four Week 7 sub-items (citation hard-gate, retry/backoff;
rate limits and Langfuse tracing deliberately deferred — see "Next
steps" below). Scoped and design-approved with the user first per
`CLAUDE.md`'s Substantial-tier process, since both are real behavior
changes with more than one reasonable shape.

- **Citation hard-gate, `agent.py`.** `verify_citations()` has existed
  since Week 5c, but only ever produced warnings printed *alongside* the
  (still-returned) answer — exactly the gap the project's own design
  principle already called out ("or the agent refuses. This becomes a
  hard guardrail in Week 7"). Added `_format_refusal_message()` and a
  single choke-point helper, `_finalize_answer()`, that both of
  `run_agent()`'s return sites now route through: if citation warnings
  are still non-empty (after Gemini's existing one-shot retry is
  exhausted, or immediately for Ollama, which gets no retry per
  `_CITATION_RETRY_BACKENDS`), the answer text itself is withheld and
  replaced with a refusal naming exactly which claim(s) failed
  verification. `mcp_server.py` needed no change — it never calls
  `run_agent()`, only the three raw tools, so there's no synthesized
  answer there to gate.
  - **This changes previously-asserted behavior**, not just adds to it:
    two existing regression tests
    (`test_run_agent_citation_retry_exhausting_budget_returns_pre_retry_answer_not_timeout`,
    `test_run_agent_citation_retry_not_attempted_for_ollama_backend`)
    asserted the raw, unverified answer text came back unchanged
    alongside its warnings. Updated both to assert the refusal is
    returned instead, while preserving what each test was actually
    regression-guarding (that the pre-retry answer's warnings — not the
    generic "wasn't able to finish" timeout message — are what the
    refusal is built from).
- **Retry/backoff, `llm_backends.py`.** Gemini already retries on
  429/503 via `_send_with_retry()` (Week 5l spike); `_ollama_call()` had
  none at all — a local `ollama serve` still starting, or a large model
  still loading into memory on first use, would fail the whole
  `run_agent()` call outright instead of a transient hiccup. Wrapped the
  existing `requests.post` in a 3-attempt linear backoff
  (`OLLAMA_RETRY_DELAY_SECONDS = 3`) on `requests.exceptions.
  ConnectionError` (including its `ConnectTimeout` subclass) only — the
  "server isn't accepting connections yet" case — deliberately not
  unified with Gemini's retry helper since the two catch different
  exception types and don't share code today.
  - **Caught in `/code-review` before shipping**: the first draft also
    retried on a plain `requests.exceptions.Timeout`, which includes
    `ReadTimeout` — meaning the connection *was* accepted and Ollama
    *was* generating, just slower than the 240s budget. This project's
    own CPU-only setup is already documented (memory,
    `PROJECT_CONTEXT.md`) to take 60-70s+ per question, so a
    `ReadTimeout` is plausibly a genuinely slow-but-working answer, not
    a stalled server — retrying it would have silently turned one 240s
    timeout into up to three (~12 minutes), indistinguishable from a
    hang. Fixed by splitting the request timeout into `(connect=10,
    read=240)` and narrowing the retry to `ConnectionError` only, so a
    slow generation still fails once at 240s (unchanged from before this
    work) while a not-yet-started server still gets retried.
- **A second `/code-review` pass on the hard gate caught a real
  eval-harness false positive, `eval_harness.py`.** The refusal message
  necessarily repeats the value it's rejecting (e.g. "[1] claims
  166000.0 ... doesn't appear in the cited source"), and
  `grade_numeric()`'s plain `extract_numbers()` scan doesn't care
  *why* a number appears in the text — so a hard-gate refusal for a
  "numeric"/"comparison" question was silently graded PASS with a
  "verified" citation whenever `expected_value` happened to be the
  same number the refusal was rejecting. Confirmed live before fixing:
  `grade_numeric(refusal_text, 166000.0, "raw", [])` returned `(True,
  "found matching value: 166000.0 (raw)")` for a message that is
  actually a refusal. Fixed by extracting `_grade()` — same rationale
  as the existing `_select_questions()` split, pure dispatch logic kept
  separate from `run_eval()`'s live loop so it's unit-testable — which
  short-circuits numeric/comparison questions to FAIL whenever
  `run_agent()`'s own `citation_warnings` return value is non-empty,
  instead of ever text-scanning a refusal. Judged questions are
  deliberately NOT short-circuited: some (e.g.
  `nvda-rd-expense-q4fy26-refusal`) are written to expect a refusal as
  the *correct* answer, and `grade_judged()` already evaluates the
  actual text against its own criteria, which is the right way to
  check whether refusing was warranted.
  - Also cleaned up `agent.py`'s `main()`, flagged in the same review
    pass: it printed the citation warnings a second time under a
    "Citation warnings:" heading even though the hard-gate refusal
    (now always what `answer` contains whenever warnings are non-empty)
    already lists them verbatim. Removed the redundant print block.
- **Verified, not just tested:** full suite green (293/293, up from
  275 — 18 new tests, red-then-green for every sub-item and every
  code-review fix, including the third pass below. TDD carve-out
  applied the same way this project already treats `run_agent()`'s own
  loop control flow (see `tests/test_agent.py`'s module docstring): the
  retry/backoff and grading-dispatch logic touched here is deterministic
  control flow *around* a live call, not the live call's own behavior,
  so unit-testing it with mocked `requests.post`/Ollama responses tests
  our own code's reaction to known exception/response shapes, not a
  fiction about what Ollama or Gemini actually do. Live-checked the
  *success* paths are unaffected — `python
  agent.py "What was Apple's total revenue for fiscal year 2024?"`
  against both `--backend gemini` and `--backend ollama` returned the
  same clean, correctly-cited $391,035,000,000 answer as before, no
  refusal. Live-checked the retry loop itself engages against a real
  (not mocked) `requests.post` call, by pointing `OLLAMA_URL` at an
  unreachable port rather than interrupting the real local `ollama
  serve` process — confirmed 3 real attempts and backoff sleeps before
  the final `ConnectionError` propagated (~21s elapsed, more than the
  ~9s of scripted backoff alone, consistent with real TCP
  connection-refused overhead on top of the two sleeps). Live-checked
  the `_grade()` fix end-to-end (not just mocked): `python
  eval_harness.py --ids crm-rpo-fy26 --backend gemini` still `PASS`es a
  normal, correctly-cited answer through the real agent loop, and
  `grade_numeric(refusal_text, 166000.0, "raw", [])` called directly
  reproduced the pre-fix false positive for the record.
- **A third review pass (multi-angle) found two more real issues, both
  fixed, plus several considered-and-declined suggestions:**
  - **Fixed**: `eval_harness.py`'s `has_citation` stat (`run_eval()`)
    matched `CITATION_PATTERN` against the raw answer text regardless of
    whether it was a refusal — but `_format_refusal_message()` echoes
    each warning's own `[n] claims ...` text verbatim, so a hard-gated
    refusal still matched `\[\d+\]` and got counted as "has a citation"
    in the printed summary and the saved report JSON, inflating the
    citation-rate stat for exactly the answers that most needed to be
    flagged as unverified. Fixed by gating `has_citation` on `not
    citation_warnings` too. Confirmed directly: `CITATION_PATTERN`
    matches a real refusal message (`True`), but `has_citation` with the
    fix applied correctly comes back `False`.
  - **Fixed**: `run_agent()`'s third return site (the generic
    "iterations exhausted" timeout fallback) hardcoded its own
    `(text, all_results, [])` tuple instead of routing through
    `_finalize_answer()` like the other two — behaviorally identical
    today (it always passes `warnings=[]`, so the gate is a no-op
    either way), but it meant the docstring's claim that "every return
    site routes through `_finalize_answer()`" wasn't literally true.
    Routed it through the same choke point for real (zero behavior
    change, confirmed by a new regression test locking in that the
    generic message still comes back byte-for-byte unchanged) so the
    single-choke-point invariant actually holds everywhere, not just in
    the two cases that happened to need it so far.
  - **Considered and declined** (documented here rather than silently
    skipped, per this project's own "let evidence decide" discipline):
    (a) unifying `_ollama_call`'s and `_send_with_retry`'s retry-loop
    shape, or their two similarly-named delay constants, into a shared
    helper — already a deliberate choice (see the "Retry/backoff" bullet
    above), the two catch different exception types today and a shared
    abstraction for two 5-line loops isn't paying for itself yet; (b)
    factoring the one-line `"\n".join(f"- {w}" for w in warnings)`
    duplicated between `_format_refusal_message` and
    `_format_citation_retry_message` into a helper — one line, not worth
    an abstraction; (c) replacing `run_agent()`'s `tuple[str, list[dict],
    list[str]]` return with a `NamedTuple`/dataclass carrying an explicit
    `refused: bool` field, so `eval_harness.py`'s `_grade()` wouldn't
    have to infer "refused" from "warnings is non-empty" — a real
    structural improvement in the abstract, but speculative today: the
    inference is correct for every currently-possible code path (single
    choke point now enforced everywhere, confirmed above), and there's
    no concrete second caller or planned "warn but don't refuse" tier
    that would actually break it yet. Revisit if one materializes,
    same YAGNI treatment as the graph-DB/HNSW-tuning deferrals earlier
    in this doc.
- A fourth `/code-review medium` pass's synthesized report came back
  empty (`[]`) — its individual finder agents only restated the
  already-declined nits above, plus one genuinely free fix applied on
  the spot: `has_citation`'s boolean expression evaluated the
  `CITATION_PATTERN` regex before checking `citation_warnings`, so a
  hard-gated refusal ran a wasted regex scan every time; reordered to
  `not citation_warnings and bool(CITATION_PATTERN.search(...))` so it
  short-circuits instead. Loop capped here per `CLAUDE.md`'s "two clean
  passes, stop" rule — full suite still green (293/293, no test-count
  change, pure reorder).

### Ratio-formula registration made cheap: `RATIO_DEFINITIONS` table + two new ratios (2026-08-28)

Prompted by the user asking whether the formula registry should become
more "dynamic," and whether the model should be allowed to do its own
arithmetic if its inputs are verified. Both were investigated against
the actual code before designing anything:

- **Letting the model compute + only verifying inputs was rejected.**
  This is exactly the failure mode `verify_citations()` was built to
  catch (see the `aapl-revenue-growth-q3fy2026` incident above): the
  model correctly cited two raw inputs and still got the arithmetic
  wrong (16.27% vs. the correct ~16.36%), undetected. Verifying inputs
  independently also can't catch a period mismatch the way
  `_compute_ratio_metric()`'s `period_end` equality check already does.
  Code stays the sole source of arithmetic; rule 3 in `SYSTEM_PROMPT` is
  unchanged.
- **A fully dynamic "model picks numerator/denominator" calculator tool
  was already considered and explicitly rejected** — `formulas.py`'s own
  module docstring says so. Not reopened.
- **What the code actually showed**: formulas have three shapes, and
  two were *already* dynamic — `get_yoy_growth()`/`get_multi_year_average()`
  both take `metric` as a free parameter and work for any raw tagged
  metric with zero new code. Only the third shape (a same-period ratio
  of two *different* metrics) was stuck at one hand-written function per
  ratio, wired into two separate dicts of function objects in `agent.py`
  (`RATIO_METRIC_FUNCTIONS`, `SINGLE_COMPANY_RATIO_FUNCTIONS`), even
  though the underlying computation (`_compute_ratio_metric()`) was
  already a fully generic two-metric engine.

**Fix**: `formulas.py` gained a `RatioDefinition` NamedTuple, a
`RATIO_DEFINITIONS: dict[str, RatioDefinition]` table (numerator metric,
denominator metric, `as_percent`, `supports_cross_company`), and two
generic functions, `get_ratio()`/`get_ratio_all_companies()`, that
dispatch through it. `RATIO_DEFINITIONS` deliberately holds only plain
data, never function references — sidesteps the exact
monkeypatch-staleness gotcha this project had already hit twice
(`_get_annual_value()`'s own docstring documents it), since there's no
function object to go stale. The 6 pre-existing named functions
(`get_gross_margin`, etc.) became one-line delegates to `get_ratio()`
instead of duplicating numerator/denominator knowledge — verified safe
by reading `tests/test_formulas.py` first: tests mocking
`xbrl_facts.fetch_concept` are unaffected (computation path unchanged),
and tests that `monkeypatch.setattr("formulas.get_gross_margin", ...)`
as an anchor replace the whole function by name, so they don't care
about its internal body either way. `_get_annual_value()`'s six-way
`if/elif` collapsed to one `if metric in RATIO_DEFINITIONS` check —
not just cleanup: a ratio added only to the table would otherwise
silently reach `get_metric()` and crash, reproducing the exact bug
class the three-branch addition for return_on_assets/asset_turnover/
cash_to_assets was built to prevent. `agent.py` deleted both old dicts;
`call_get_financial_fact()`/`call_compare_financial_metric()`, both tool
schemas' `enum` lists, and the `SYSTEM_PROMPT` metric list all now
derive from `RATIO_DEFINITIONS` (plus new `_CROSS_COMPANY_RATIOS`/
`_SINGLE_COMPANY_ONLY_RATIOS`/`_PERCENT_RATIOS`/`_DECIMAL_RATIOS` derived
lists) instead of two hand-combined literals kept in sync by hand.

**Two new ratios added**, chosen with the user from a tiered list of
candidates (both buildable from raw XBRL tags already ingested and
live-verified, no new tag-discovery work needed):
- `inventory_turnover` = `cost_of_revenue / inventory` (`as_percent=False`,
  matching `asset_turnover`'s decimal convention). Pairs with the
  existing `pltr-inventory-turnover-fy2025-refusal` question (Palantir
  correctly still refuses, no inventory tagged) — this adds the
  complementary case, a company that *does* carry inventory answered
  correctly. New eval question `nvda-inventory-turnover-fy2026`
  (expected 2.92, raw), live-fetched via `get_ratio()` itself, not
  guessed.
- `rd_intensity` = `rd_expense / revenue`. New eval question
  `msft-rd-intensity-fy2025` (expected 11.5%), same live-fetch
  discipline.
- Both `supports_cross_company=False` — no current eval question needs
  a cross-company version, easy to flip later if real demand shows up.
- **Found live, not expected**: `cost_of_revenue` (needed for
  `inventory_turnover`) resolves cleanly for NVDA but returns `None` for
  AAPL and MSFT under the current `DEFAULT_METRIC_TAGS["cost_of_revenue"]`
  tag (`CostOfRevenue`) at FY granularity — confirmed via `get_metric()`
  directly, not assumed. Likely the same "different companies use
  different tags for the same concept" pattern already documented for
  `revenue` (NVDA's own override), just not yet investigated for this
  tag. Not fixed here — no eval question currently needs AAPL/MSFT
  inventory_turnover specifically, so per this project's own "let
  evidence decide" discipline this is flagged, not chased. Revisit with
  `discover_tags.py` if a real question needs it.
- **Considered and not built**: `effective_tax_rate` (`tax_expense /
  pretax_income`) — real evidence exists for it (`msft-tax-rate-q2fy26`,
  `aapl-msft-tax-rate-comparison` already need it and currently only get
  it via `search_filings` prose), but needs 1-2 new XBRL tags discovered
  and live-verified per company first (via `discover_tags.py`, same
  process already done ~9 times) — a bounded but separate task, left for
  a follow-up.
- **Langfuse tracing backlog item** (Week 7 guardrails, still open — see
  "Next steps" below) now has an explicit requirement attached: when
  built, it should capture unmet metric/ratio requests (ticker,
  requested metric, question) — there is no logging/telemetry for this
  anywhere today (confirmed via grep, not assumed), so "let evidence
  decide" is currently 100% manual (a developer reviewing eval runs by
  eye). Deliberately not building a bespoke logging mechanism for this
  now, per the user's direction, to avoid building two separate
  observability systems.

**Two more issues caught by `/code-review` before shipping**, both fixed:
- **Fixed**: the 3 pre-existing named `_all_companies` functions
  (`get_gross_margin_all_companies`, etc.) were left hardcoding their
  numerator/denominator metric name pairs and calling
  `_compute_ratio_metric_all_companies()` directly, instead of being
  converted to `get_ratio_all_companies()` delegates like every
  single-company sibling was — a real duplication gap (an edit to
  `RATIO_DEFINITIONS` later would silently diverge from these three).
  Converting them was not purely mechanical: their existing tests
  monkeypatched the NAMED function (`formulas.get_gross_margin`, etc.)
  as the anchor source, which stopped being the real anchor path once
  the delegation went through `get_ratio()` instead — 3 of the 7 tests
  failed loudly (asserting `== {}` against what was now a real,
  unmocked network/cache call), but the other 4 were worse: they kept
  "passing" while silently no longer testing what they claimed to,
  since `_compute_ratio_metric_all_companies()`'s actual computation
  only reads `anchor["frame"]` (to key the `get_frame()` mock), never
  `anchor["value"]` — so a real anchor with a real frame silently
  produced the same mocked-fixture result regardless of the (unmocked,
  live) anchor's own value. All 7 tests updated to monkeypatch
  `formulas.get_ratio` instead, matching the pattern already used for
  `_get_annual_value()`'s tests above.
- **Fixed**: `get_ratio_all_companies()` didn't forward `as_percent` to
  `_compute_ratio_metric_all_companies()`, which hardcoded `*100`/
  `unit: "percent"` regardless of what `RATIO_DEFINITIONS` said for
  that ratio. Latent today (all 3 current `supports_cross_company=True`
  ratios are `as_percent=True`), but a real gap given this section's own
  claim that flipping a decimal ratio like `asset_turnover` to
  cross-company later is "easy" — doing so without this fix would have
  silently produced e.g. `{"value": 104.0, "unit": "percent"}` instead
  of `{"value": 1.04, "unit": "raw"}`, exactly the silent
  eval-grading-breaking mismatch `_compute_ratio_metric()`'s own
  `as_percent` docstring already warns about for the single-company
  path. `_compute_ratio_metric_all_companies()` gained the same
  `as_percent` parameter `_compute_ratio_metric()` already has.

**Verified, not just tested**: full suite green (305/305, up from 293 —
12 new tests across `test_formulas.py`/`test_agent.py`). Live-checked
both new ratios end-to-end (`eval_harness.py --ids
nvda-inventory-turnover-fy2026,msft-rd-intensity-fy2025 --backend
gemini`: 2/2 PASS, correct cited values, matching the live-fetched
ground truth exactly). Live-checked no regression on the 5 pre-existing
single-company ratio questions (gross_margin, operating_margin,
return_on_assets, asset_turnover, cash_to_assets, all `--backend
gemini`): identical values to before this change. Live-checked all 3
cross-company margin functions directly (not just via eval) after both
duplication/as_percent fixes — correct `unit: "percent"` and exact
expected values (e.g. PLTR gross margin 82.4%, CRM operating margin
20.1%) for all 5 companies each. The `five-company-*-margin-ranking`
judged eval questions FAILed on isolated single runs (twice, for two
different margins) and PASSed cleanly on an immediate re-run with no
code change in between each time — confirmed as live-model anchor-
choice non-determinism (traced directly: `compare_financial_metric`
anchored on AAPL returns full 5-company net-margin data, anchored on
NVDA/MSFT/CRM/PLTR returns `{}` for that specific ratio, a pre-existing
XBRL-frame characteristic unrelated to this diff — which anchor the
live model happens to pick varies run to run), not a regression — the
underlying dispatch data was independently confirmed correct via direct
`call_compare_financial_metric()`/`get_ratio_all_companies()` calls
before any of the flaky re-runs.

### Week 7 guardrails, part 2: `mcp_server.py` auth + rate limiting (2026-09-01)

Completes the last open Week 7 sub-item — part 1 (citation hard-gate,
Ollama retry/backoff, above) deliberately left this out since neither
touches `run_agent()`/`llm_backends.py`. Before this, `mcp_server.py`
had zero auth or throttling: anyone who could reach the port could call
any tool an unlimited number of times.

- **Auth: plain shared-secret bearer token, not the `mcp` SDK's native
  OAuth support.** `Server.streamable_http_app()` does accept
  `auth=AuthSettings(...)`/`token_verifier=...`, but `AuthSettings`
  requires `issuer_url`/`resource_server_url` (confirmed live via
  `inspect` on `mcp.server.auth.settings.AuthSettings`) — a full OAuth
  2.1 Protected Resource Metadata flow, built for multi-tenant
  OAuth-issuing deployments. This is a single-operator local/small-VM
  tool with no OAuth issuer anywhere in the stack; standing one up to
  gate one static token would be the same shape of overkill already
  rejected elsewhere in this project (a fully dynamic formula
  calculator, `effective_tax_rate` before its tags exist). Went with a
  plain `MCP_AUTH_TOKEN` shared secret instead, checked against an
  `Authorization: Bearer <token>` header.
- **Rate limiting: hand-rolled in-memory fixed-window counter, not a
  library.** No rate-limiting package (`slowapi`, `limits`, etc.) was
  already a dependency; `starlette`/`uvicorn` are already transitive via
  `mcp` (`requirements.txt:27-28`). `uvicorn.run()` runs with no
  `workers=` argument, i.e. always a single process, so an in-memory
  counter needs no cross-process coordination (no Redis, no shared
  store) — a ~30-line class was simpler and added zero new dependencies
  for a problem this small.
- **Implementation, `mcp_server.py`.** `_is_authorized(auth_header,
  expected_token)` (pure function — `expected_token == ""` disables auth
  entirely, matching every other `.env`-optional setting in this
  project) and `_RateLimiter` (fixed-window counter keyed by string,
  `now` passed in explicitly rather than read from `time.time()`
  internally, so it stays deterministic and testable without real
  sleeps) are both plain logic with no ASGI/network dependency — full
  red-green TDD, per this project's pure-logic carve-out. Both are
  wired together in one `_AuthRateLimitMiddleware` — a **plain ASGI
  middleware**, deliberately not Starlette's `BaseHTTPMiddleware` (which
  is documented to interfere with streaming responses and
  client-disconnect propagation — a real risk sitting on top of
  `streamable_http_app()`'s SSE-based transport) — added via
  `app.add_middleware(...)` in `build_app()` (confirmed live that
  `streamable_http_app()` returns a real `starlette.applications.
  Starlette` instance, so this is a supported hook, not a workaround).
  Rate limiting runs **before** auth, keyed by **client IP**, not the
  token — see the code-review fixes below for why.
- **New config, `config.py`/`.env.example`**, following the existing
  `os.getenv("NAME", "<fallback>")` convention exactly: `MCP_AUTH_TOKEN`
  (default `""`, auth disabled), `MCP_RATE_LIMIT_REQUESTS` (default
  `60`, `0` disables it), `MCP_RATE_LIMIT_WINDOW_SECONDS` (default
  `60`). Deliberately env vars, not `click` CLI flags, for the token —
  an env var doesn't show up in `ps`/process-list output the way a CLI
  argument would, matching how `GEMINI_API_KEY` is already handled.
- **Out of scope, deliberately**: per-tool rate limits (no evidence any
  one tool is disproportionately expensive), token rotation/expiry or
  multiple tokens (single shared secret is enough for "not wide open"
  on a single-operator tool, not a multi-tenant service). Also, real but
  deferred: IP-based rate limiting has an inherent gap behind a reverse
  proxy (every real caller collapses onto the proxy's own IP, or the
  literal `"unknown"` key on a transport that doesn't populate
  `scope["client"]` at all — flagged in the third code-review pass)
  since `uvicorn.run()` sees only the direct TCP peer. Fixing this
  properly means trusting an `X-Forwarded-For`-style header, which is
  its own security decision (which proxies to trust) — not worth making
  speculatively before this tool is ever actually deployed behind one.

**Issues caught by `/code-review` before shipping**, across two review
passes (the first found and fixed the 3 below; see further down for
what the second pass found):

1. **Timing side-channel on the token comparison.** `auth_header ==
   f"Bearer {expected_token}"` is a plain `==`, which short-circuits on
   the first mismatched character in CPython — a remote attacker
   measuring response latency could recover the token byte-by-byte
   instead of needing the whole secret at once. Fixed with
   `secrets.compare_digest()`.
2. **`_RateLimiter._windows` never evicted expired keys.** With the
   no-auth default (rate-limit key = client IP), a long-running server
   would keep one dict entry per distinct caller IP forever, even after
   that caller's window expired and it never reconnects — a slow,
   unbounded memory leak. Fixed by pruning every expired key (not just
   the one being checked) on each `allow()` call. (A follow-up
   efficiency pass flagged that this makes every call an O(n) full-dict
   rebuild rather than an O(1) per-key check — noted, not fixed: at this
   project's actual scale, a single-operator tool with at most a
   handful of distinct callers, the real cost is negligible, and an
   amortized/periodic-sweep version would add real complexity — a
   counter, a threshold, a test coupled to that threshold — for a
   problem that doesn't exist yet. Revisit only if this server is ever
   actually deployed at a scale where it matters.)
3. **`BaseHTTPMiddleware`'s documented streaming/SSE caveat.** The first
   version subclassed Starlette's `BaseHTTPMiddleware`, which is
   documented to interfere with streaming responses and client-
   disconnect propagation — a real risk given `streamable_http_app()`'s
   transport is SSE-based, even though today's tool calls are small,
   fast, single-shot JSON round-trips that wouldn't have surfaced it.
   Rewritten as a plain ASGI middleware (`__call__(self, scope, receive,
   send)`) instead, which doesn't have this caveat and is still a
   supported target for `app.add_middleware(...)`.

**A more significant issue surfaced on the second review pass**:
**unauthenticated requests never touched the rate limiter at all.** The
original design checked auth first, then rate-limited using the shared
token as the key. That meant a rejected (401) request short-circuited
before `_rate_limiter.allow()` ever ran — credential-guessing traffic
against `MCP_AUTH_TOKEN` was completely unthrottled, and separately,
keying by the one shared token meant every *legitimate* caller using it
drew from a single global budget, so one noisy caller could lock out
every other one. Both problems trace to the same design choice (keying
by token) and both are fixed by the same change: **rate limiting now
runs before auth, keyed by client IP.** Guessing traffic from one IP
gets throttled regardless of whether any guess is ever correct, and
separate legitimate callers no longer share a budget. Also fixed in the
same pass: the `Retry-After` header used `int()` on the already-`float`
`MCP_RATE_LIMIT_WINDOW_SECONDS`, which truncates down — a caller
retrying exactly at the advertised time on a fractional-second window
(e.g. `2.5`) could still get rate-limited again. Changed to
`math.ceil()`, so the advertised wait is never shorter than the real
one.

**Verified, not just tested.** `tests/test_mcp_server.py` gained 11 new
unit tests for `_is_authorized`/`_RateLimiter` (written red first, then
green, including one added during the code-review fix for the pruning
behavior); full suite **316/316**, up from 305. The actual HTTP
enforcement (including the auth/rate-limit *ordering*, which is glue
logic no unit test exercises) is live-only per this project's carve-out
(same reasoning as the rest of `mcp_server.py`'s protocol wiring), so
`tests/manual/verify_mcp_server.py` was extended with three new live
checks against the real running server: `check_auth()` (no/wrong bearer
token → 401, correct token → full `list_tools` round-trip succeeds),
`check_rate_limit()` (requests within a tiny `MCP_RATE_LIMIT_REQUESTS`
budget succeed, the next → 429 with a `Retry-After` header, and a
request after the window elapses succeeds again), and
`check_unauthenticated_requests_are_rate_limited()` (added for the
auth-ordering fix — repeated unauthenticated requests against a tiny
budget eventually get 429, not an endless stream of 401s, confirmed
live: `[401, 401, 429]`). All 3 pre-existing functional checks
(list_tools, get_financial_fact, compare_financial_metric, sec_url
liveness, text-fragment excerpt) still ran unauthenticated against a
default-config server and passed identically to before, confirming this
is backward compatible by default.

One real bug caught while writing `check_rate_limit()` (separate from
the code-review findings above): the manual verify script's own
server-startup readiness probe (a `GET /`) shares the same rate-limit
budget as the check's own requests, since the middleware correctly
applies to every route, not just `/mcp` — the first run failed with an
off-by-one-looking 429 on what should've been the 2nd allowed request.
Not a bug in `mcp_server.py` (a flood of requests to any route should
count against the limit); fixed by having the check sleep past the
rate-limit window once after the server becomes ready, so it starts
from a clean slate instead of coupling the test to exactly how many
requests startup happens to use.

### Week 7 guardrails, part 3: Langfuse tracing — all 4 sub-items done (2026-09-04)

Closes the last open Week 7 guardrails item. Before this, there was
zero observability into what the agent does at runtime (no record of
questions, tool calls, answers, or refusals beyond terminal scrollback),
and separately — the requirement added 2026-08-28 during the
ratio-formula-registration work — "let evidence decide" for adding new
financial-ratio formulas was 100% manual, since nothing logged "a
metric/ratio was requested and unavailable." Both addressed in one
pass rather than as two systems, per the user's explicit direction at
the time.

- **New module, `tracing.py`.** Single-responsibility, matching
  `config.py`/`numeric_utils.py`'s style — `agent.py`/`mcp_server.py`/
  `eval_harness.py` never import the `langfuse` SDK directly, only
  `traced_span()`/`record_unmet_metric_request()`/`flush()`.
  `TRACING_ENABLED = bool(LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY)`
  gates every call explicitly (same pattern
  `llm_backends._get_gemini_client()` already uses for
  `GEMINI_API_KEY`) rather than trusting the SDK's own behavior when
  unconfigured, which Langfuse's docs don't fully commit to either way
  (confirmed live: an unconfigured `Langfuse()` prints a warning and
  disables itself rather than raising — reassuring, but this project's
  own explicit gate doesn't depend on that being true).
- **Package: `langfuse==4.15.1`** (OTel-based v4 client, current at
  implementation time — pinned to what `pip install langfuse` actually
  resolved, not a guessed number). New config
  (`LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY`/`LANGFUSE_BASE_URL`,
  default `""`/`""`/`"https://cloud.langfuse.com"`) follows the
  existing `os.getenv("NAME", "<fallback>")` convention exactly.
- **Instrumentation.** `agent.py`'s `run_agent()` became a thin traced
  wrapper (renamed the real implementation to `_run_agent_impl()`) — a
  single choke point for the top-level span regardless of which of
  `_run_agent_impl`'s several internal return paths fires, needing zero
  changes to the tool-calling loop itself and no changes to any
  existing test (tracing is disabled in the test env, so `traced_span`
  yields `None` and does nothing observable). `_dispatch_tool_call()`
  wraps each of its three branches in a `"tool"`-typed span, nesting
  automatically under the `run_agent` span via the SDK's OTel-based
  context propagation (confirmed live). `mcp_server.py`'s three tool
  handlers get the same tool-span wrapping, so MCP clients get equal
  observability to the CLI/eval path.
- **The unmet-metric-request signal, inside
  `call_get_financial_fact()`/`call_compare_financial_metric()`**
  (`agent.py`) — the single shared implementation both `agent.py`'s
  dispatch and `mcp_server.py`'s wrappers already go through, so
  instrumenting here covers every entry point with no duplication.
  Both functions gained an optional `question: str | None = None`
  parameter (agent.py's dispatch has one to pass through;
  `mcp_server.py`'s direct tool callers don't, so it's `None` there).
  Two distinct `reason` values, not one, because `call_get_financial_fact()`
  already returned `None` for genuinely different situations conflated
  into one signal: `reason="unknown_metric"` fires when `metric` isn't
  recognized at all (the actual "should we add a formula" signal the
  original request was about), `reason="no_data_for_ticker"` fires when
  a *recognized* metric/ratio's underlying lookup found no data for
  this specific ticker/period (the same shape of gap already documented
  for `inventory_turnover`/AAPL/MSFT). Deliberately **not** recorded for
  boundary rejections (malformed/invented args, invalid yoy_growth/
  multi-year-average combinations) — those are a schema-violation
  problem, not a missing-formula problem, and would just be noise.
- **Out of scope, deliberately, per the user's direction**: per-call
  LLM "generation" tracing inside `llm_backends.py` (token counts,
  prompt/completion, cost/latency per Ollama/Gemini call). The
  trace-level view already answers "what did the agent do on this
  run"; per-call detail is a real but separate enhancement with no
  evidence yet that it's needed, and would mean touching all 6
  backend-specific functions across both backends. Recorded as its own
  "Next steps" item below rather than folded in here, to be scoped
  later. Also out of scope: any UI/dashboard work (Langfuse's own
  hosted dashboard is the consumer), a third `reason` value
  distinguishing "deliberately single-company-only by design" from a
  genuine cross-company data gap (a human reading the metric name in
  the dashboard can already tell), and retry/error-handling around
  Langfuse's own requests (the SDK already documents catching and
  logging its own errors).

**Verified, not just tested.** Before writing any wiring code, the
actual `langfuse` SDK was installed and inspected live (`inspect.signature`
on `Langfuse.__init__`/`start_as_current_observation`/`LangfuseSpan.update`)
to confirm the real current API shape rather than trusting doc snippets
alone — this caught that the docs' `create_event()`-style claim doesn't
exist (a short `as_type="span"` observation is the real mechanism used
here) and confirmed `as_type="tool"`/`"agent"` are real, valid types. A
throwaway smoke-test script constructed a real client with this
project's actual credentials, wrote nested spans, called `flush()`, and
then read them back via Langfuse's own `observations` API — confirming
the write path end-to-end before any production code was written, the
same "verify live, don't just trust" discipline used everywhere else in
this project. `tests/test_tracing.py` (11 new tests) and 11 new tests
in `test_agent.py` cover the pure/deterministic gating and
reason-tagging logic with mocks, red-then-green; full suite
**334/334**, up from 316. `tests/manual/verify_tracing.py` (new) runs a
real `run_agent()` question through `--backend gemini` and a real
unmet-request case, then polls Langfuse's `observations` API to confirm
both actually landed with the right shape — live-run result: the
`run_agent` span appeared (`type=AGENT`) with 1 nested tool span
underneath it, and the `unmet_metric_request` event appeared with
`reason="unknown_metric"` for a deliberately-unsupported metric name.
One bug caught while writing this script (not in the tracing code):
Langfuse's v2 `observations` endpoint always returns `input`/`output`
as raw JSON strings — the `parse_io_as_json` parameter documented for
an older version no longer exists and the API 400s on it — fixed by
parsing the strings with `json.loads()` in the verify script itself.

**Two rounds of real gaps caught by `/code-review`, both in the same
area** (the unmet-metric-request tracing, not the general span/trace
plumbing, which came back clean both times):

1. **First pass**: `call_get_financial_fact()`'s `yoy_growth` and
   `start_fiscal_year`/`end_fiscal_year` branches returned
   `get_yoy_growth()`/`get_multi_year_average()`'s result directly,
   without the same `if result is None: record_unmet_metric_request(...)`
   check the plain `get_metric()`/`get_ratio()` path already had — so a
   genuine no-data case on either path (e.g. a 3-year average spanning
   years with real gaps in tagged data) was silently invisible to the
   new signal, while the exact same kind of gap on the plain-metric
   path was captured. Fixed with the same `reason="no_data_for_ticker"`
   pattern (4 new regression tests: 2 confirming both paths now record
   it, 2 confirming the boundary-rejection combinations on those same
   paths still correctly don't).
2. **Second pass**: the opposite-direction bug in the *same* code —
   `metric not in DEFAULT_METRIC_TAGS and metric not in RATIO_DEFINITIONS`
   is `True` when `metric` is missing from `args` entirely (`None`),
   not just when it names something unrecognized. A model omitting the
   required `metric` key (a schema violation this function's own
   docstring already calls out as expected, same class of issue as the
   invented-`segment`-key case) was firing
   `record_unmet_metric_request(ticker, None, reason="unknown_metric", ...)`
   — polluting the "should we add a formula" signal with schema-noise
   entries instead of real unsupported-metric names, in both
   `call_get_financial_fact()` and `call_compare_financial_metric()`.
   Fixed by only recording when `metric is not None` (2 new regression
   tests). A third `/code-review` pass afterward found no further
   issues, closing the loop per `CLAUDE.md`'s cap.

### Local JSONL trace log — a Langfuse-independent backup (2026-09-05)

While reviewing the just-shipped Langfuse tracing, the user asked
whether logging full LLM-call detail could hit Langfuse Cloud's
free-tier cap, and whether local logging should exist as a backup.
Researched live: the free tier is **50,000 observations/month,
hard-capped with no overage** (tracing silently stops recording, isn't
billed) **and only 30-day data retention**. At this project's actual
scale (40 eval questions, ~2-3 observations/question at current
instrumentation) the cap isn't a near-term risk — but 30-day retention
means data disappears regardless, and `TRACING_ENABLED=False` (no
account configured, the default for anyone cloning this repo) meant
**zero** observability rather than degraded observability. Decided to
add local JSONL logging now, independent of the quota question, as a
permanent backup — this project already treats "don't lose evidence"
as a real principle (`eval/eval_results/*.json` is tracked in git for
exactly that reason), though this log is high-volume/regenerable
per-run rather than curated, so it's `.gitignore`d like
`chroma_db/`/`xbrl_cache/`, not tracked.

- **`traced_span()` now always writes one local JSONL line to
  `TRACE_LOG_PATH`, regardless of whether Langfuse is configured** —
  Langfuse is now the optional cloud/dashboard layer on top of an
  always-on local baseline, not the reverse. This required a real
  contract change: `traced_span()` used to yield `None` when tracing
  was disabled (every call site guarded `.update()` with `if span is
  not None:`); now it always yields a `_TracedSpan` wrapper, since the
  local log needs to capture `output` regardless of Langfuse's state.
  The now-always-true `if span is not None:` guards in `agent.py`
  (`_dispatch_tool_call`, `run_agent`) and `mcp_server.py`'s three tool
  handlers were removed as a direct, mechanical consequence — left in
  place they'd be dead conditions actively misleading a future reader,
  not just harmless.
- **`run_id` grouping via `contextvars.ContextVar`** — the same
  mechanism OTel already uses under the hood for Langfuse's own
  nesting, reimplemented locally (a handful of lines) so the JSONL log
  can group every span belonging to one `run_agent()` call (or one
  direct MCP tool call) without threading an id through every function
  signature. Deliberately just a flat `run_id` + `is_root` flag, not
  full parent/child span-id linkage like Langfuse's own model — no
  concrete need yet to reconstruct exact nesting locally.
- **`record_unmet_metric_request()` dropped its `if not TRACING_ENABLED:
  return`** — it now always goes through `traced_span()`, which itself
  decides per-concern (Langfuse span vs. local log) whether each half
  applies, so the unmet-request signal is captured locally even with no
  Langfuse account at all.
- **New config** (`config.py`/`.env.example`, same
  `os.getenv("NAME", "<fallback>")` convention): `TRACE_LOG_PATH`,
  default `"./trace_logs/traces.jsonl"`. Empty string disables it, but
  unlike every other tracing setting, this one is **on by default** —
  "always-on local backup" is the point.
- **Out of scope, deliberately**: log rotation/pruning/size caps (no
  evidence of runaway growth yet); richer local-only payloads beyond
  what's already passed to `traced_span`'s `input`/`output` (e.g. full
  retrieved chunk text) — would need a second `local_output=` parameter
  at every call site for no concrete need yet, the backup/permanence
  value is the point of this round, not maximizing local detail;
  concurrency locking around the file append — `mcp_server.py` already
  runs single-process (documented for the rate limiter), and one
  small `write()` per line is effectively atomic at this scale.

**A real bug found live, not by a test**: the very first full suite run
after this change left **18 real lines in `./trace_logs/traces.jsonl`**
in the actual project directory — every existing `agent.py`/
`mcp_server.py` test that exercises `traced_span()` indirectly (most of
them do, via `run_agent()`/`_dispatch_tool_call()`/the mcp_server tool
handlers) was writing to the real default `TRACE_LOG_PATH` during
`pytest`, since none of those pre-existing tests had any reason to mock
a local-logging concern that didn't exist yet when they were written.
Fixed with a new `tests/conftest.py` — an autouse fixture that sets
`tracing.TRACE_LOG_PATH = ""` for every test by default;
`tests/test_tracing.py`'s own tests still override it to a `tmp_path`
within themselves, which simply takes precedence for those tests.

**Six issues caught by `/code-review` before shipping**: (1) rewriting
`tests/test_tracing.py` for local-log coverage accidentally dropped the
only test exercising `record_unmet_metric_request(reason=
"no_data_for_ticker")` together with the `question=None` default on the
Langfuse-enabled path — both real, used call sites in `agent.py`
(`_run_agent_impl`'s plain-metric/`yoy_growth`/multi-year-average
no-data branches). The underlying code was already correct (nothing to
fix there), just the regression coverage for it was missing — restored
with a dedicated test. (2) `_write_local_log()` called
`path.parent.mkdir(parents=True, exist_ok=True)` on every single write
— cheap individually, but this runs on every `traced_span()` exit
(every tool call and every `run_agent()` call), so re-verifying an
already-created directory every time is wasted I/O on what's meant to
be a high-volume log. Fixed by caching the last-ensured directory
(`_ensured_log_dir`) and only calling `mkdir()` when it changes, with a
regression test asserting exactly one `mkdir()` call across two writes
to the same directory. (3) That very caching fix introduced a second-
order bug on the *next* review pass: `_ensured_log_dir` was never
invalidated on a write failure, so if `TRACE_LOG_PATH`'s directory got
deleted externally while a long-running process (`mcp_server.py`) kept
running -- plausible, since `trace_logs/` is documented as disposable/
regenerable output -- every later write would keep skipping `mkdir()`
(believing the directory already existed) and fail silently forever
until the process restarted, defeating the entire "always-on backup"
premise this feature exists for. Reproduced live via a test that
deletes the directory mid-run: without the fix, no line ever landed
again; fixed by resetting `_ensured_log_dir = None` inside the
`except OSError` handler so the next write retries `mkdir()` and
recovers on its own. (4) The exception handler was still only
`except OSError`, narrower than the module's own documented contract
("never raise, ever — logging must never break the real call it
wraps"): `json.dumps(record, default=str)` can itself raise a
non-`OSError` (e.g. `default=str`'s own fallback calling `str()` on a
value whose `__str__` raises) with no I/O involved at all. Widened to
`except Exception` with a regression test using a deliberately
unstringable object. (5) Two tests
(`test_traced_span_does_not_write_local_log_when_trace_log_path_empty`,
`test_record_unmet_metric_request_noop_when_both_langfuse_and_local_log_disabled`)
set `TRACE_LOG_PATH = ""` but asserted on an unrelated `tmp_path`
never referenced by that empty string — they'd have passed even with
the early-return guard deleted entirely. Confirmed live by actually
deleting the guard: both tests still passed. Fixed by spying on
`Path.open` and asserting it's never called — but the first attempt at
that fix (raising `AssertionError` from inside the mock) *also* failed
to catch the regression, for a subtler reason: `_write_local_log`'s own
broad `except Exception` (fix #4 above) silently swallows a raised
assertion exactly like any other error. Confirmed this the same way
(deleted the guard, watched the "fixed" test still pass) before landing
on the actual fix: track calls in a plain list and assert on it after
the `with` block, which doesn't route through the try/except at all.
(6) `traced_span()` measured duration with `time.time()` (wall clock)
instead of `time.monotonic()` — on a long-running process
(`mcp_server.py`), a backward wall-clock adjustment (e.g. an NTP
correction) mid-span would corrupt `duration_ms` in the very backup log
this feature exists to keep reliable. Fixed by switching both the start
and end reads to `time.monotonic()`, with a regression test that
freezes `time.time()` while advancing a fake `time.monotonic()` and
confirms `duration_ms` reflects the monotonic delta, not zero.

**Verified, not just tested.** `tests/test_tracing.py` grew to 18 tests
(local-log content, missing-parent-directory creation, a simulated
write failure that must not raise, `run_id`/`is_root` grouping across
nested and sibling calls, the two code-review fixes above) — written
red first, then green; full suite **347/347**, up from 336.
Live-verified twice: (1) ran a real question through `agent.py` with
`LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` forced empty in the shell
environment (so `config.py`'s `load_dotenv()` can't fill them from
`.env`) and confirmed `trace_logs/traces.jsonl` was written anyway,
with the expected `run_agent`/`get_financial_fact` lines sharing one
`run_id`; (2) extended `tests/manual/verify_tracing.py` with
`check_local_log_matches_the_same_run()` (confirms the local log and
the real Langfuse trace agree for the same live run) and
`check_local_log_independent_of_langfuse()` (flips `TRACING_ENABLED`
off in-process and confirms local logging still fires) — both pass. One
bug caught while writing the first check (not in `tracing.py`): a tool
span's own `input` (ticker/metric/etc.) never contains the marker
stamped into the free-text question, so filtering local log lines by
"contains the marker" silently found zero tool lines; fixed by locating
the `run_agent` line by marker first, then grouping every local log
line sharing its `run_id` instead of re-searching for the marker in
each one.

### Local-only debug events beyond the Langfuse mirror (2026-09-05)

The local JSONL log only ever wrote what `traced_span()`/
`record_unmet_metric_request()` already produced — exactly the same
spans/events that would also go to Langfuse if configured. The user
wanted more: local-only signal for anything "important and can help
debugging," independent of whether it's Langfuse-worthy. Several
moments in this codebase already qualified — either printed only under
`--verbose` (lost the instant the terminal scrolls) or not recorded
anywhere at all — and this project's own history above shows these
exact moments (retries, invented tool args, self-correction retries)
have repeatedly needed hand-diagnosis.

- **New `tracing.log_event(category, **fields)`.** Deliberately not
  built on `traced_span()` — a retry attempt, a rejected tool call, a
  self-correction decision are instantaneous facts, not spans of work
  with a duration, and this project doesn't want every one of these
  mirrored to a cloud dashboard. Tags `run_id` from the
  currently-open `traced_span` when called from inside one (agent.py's
  call sites always are), `None` when called standalone
  (`mcp_server.py`'s auth/rate-limit rejections happen before any span
  opens). Reuses `_write_local_log()`'s existing best-effort/
  never-raise behavior, so it also respects `TRACE_LOG_PATH` being
  disabled automatically.
- **`llm_backends.py`**: `_ollama_call()`'s `ConnectionError` retry
  loop and `_send_with_retry()`'s Gemini 429/503 retry loop had no
  logging of any kind before — a flaky local Ollama server or a
  rate-limited Gemini key was invisible after the fact. Both now log
  `llm_retry` with `backend`/`attempt`/`max_attempts`/`exhausted` (plus
  `error`/`status_code`) on every attempt. `_send_with_retry()`'s
  compound `if code not in (429, 503) or attempt == 3: raise` was split
  into two checks so the log call only fires for the retryable-error
  path — behaviorally identical control flow, confirmed by 5 new tests
  covering this function for the first time (it had none before).
- **`agent.py`**: the citation self-correction retry (`_run_agent_impl()`)
  now logs `citation_retry` (backend, warnings) right next to the
  existing `--verbose` print, so it survives non-verbose runs and eval
  sweeps. `call_get_financial_fact()`/`call_compare_financial_metric()`'s
  boundary-rejection guards (extensively documented in both functions'
  own docstrings as "don't trust the schema") now log `tool_call_rejected`
  with a specific `reason` (`unrecognized_extra_argument`,
  `unknown_ticker`, `missing_metric`, `invalid_multi_year_average_combo`,
  `yoy_growth_unsupported_for_ratio`) — previously these returned
  `None`/`{}` with **zero** signal anywhere, not even the existing
  `unmet_metric_request` event (deliberately scoped to "formula doesn't
  exist," not "model didn't follow the schema"). `missing_metric` was
  found while implementing this round, not in the original plan: the
  existing `metric is None` guard already distinguished "no formula for
  this name" from "key omitted entirely," but only the former got any
  signal — the omitted-key case was completely invisible until now.
- **`mcp_server.py`**: `_AuthRateLimitMiddleware` now logs
  `auth_rejected`/`rate_limited` (with `client_ip`) right before each
  401/429 response, so exposing this server beyond localhost comes with
  an audit trail of who's getting rejected and why.
- **Out of scope, deliberately**: per-call LLM generation tracing
  (already parked as its own future item — this round's `llm_retry`
  event is a small, distinct signal, not a reopening of that); a
  verbosity/sampling knob (these are all inherently rare, bounded
  events, not high-volume spam).

**Verified, not just tested.** New/extended tests: `tests/test_tracing.py`
(+3, `log_event`'s run_id tagging and Langfuse-independence),
`tests/test_llm_backends.py` (+5 new `_send_with_retry` tests — this
function had none before — plus assertions added to the 3 existing
`_ollama_call` retry tests), `tests/test_agent.py` (+11: one
`tool_call_rejected` case per rejection reason, "not called on
success" for both functions, and a `citation_retry` assertion added to
the existing exhausted-retry-budget test). Full suite **365/365**, up
from 347. Live-verified: pointed `OLLAMA_URL` at an unreachable port
(rather than stopping any real running `ollama serve`) and confirmed
all 3 `llm_retry` lines landed with `attempt=1,2,3`/
`exhausted=false,false,true`, correctly grouped under the same `run_id`
as the `run_agent` span — which itself was still recorded with
`output: null` even though the `ConnectionError` propagated all the way
out uncaught, confirming the `finally`-based local logging survives an
unhandled exception escaping the span, not just the happy path.
Extended `tests/manual/verify_mcp_server.py`'s `check_auth()`/
`check_rate_limit()` to assert the new local log lines appear
(`auth_rejected` ×2, `rate_limited` ×1) — one gotcha found while writing
this, same shape as the earlier rate-limit-check gotcha:
`_RunningServer`'s own startup probe (`GET /`, unauthenticated) also
gets a 401 and would otherwise inflate the count by one; fixed by
capturing the "before" baseline after the server is confirmed up
rather than before starting it.

### Fixed the 4 High-priority findings from the 2026-09-06 full-codebase review (2026-09-06)

See `docs/reviews/2026-09-06-full-codebase-review.md` for the original
findings (findings §1-§4) and `BACKLOG.md` for what's still open from
that review. All four were real, live-verified bugs, not theoretical:

- **`agent.py`'s schema-violation guards crashed instead of degrading
  (§1).** `ticker not in COMPANIES` and the matching `metric` check both
  raise `TypeError` on an unhashable value (e.g. the model passing
  `"ticker": ["AAPL"]`) — the same "don't trust the schema" lesson this
  file has already been bitten by three times, just a fourth/fifth
  still-open instance, and with zero `try`/`except` anywhere in the
  file, either crashed the whole request. Fixed with `isinstance`
  guards ahead of the existing membership checks in both
  `call_get_financial_fact` and `call_compare_financial_metric`; a
  non-string `metric` gets its own new `invalid_metric_type` rejection
  reason rather than being folded into `unknown_metric`, so it doesn't
  pollute `record_unmet_metric_request`'s formula-registration signal
  with garbage values. Also fixed: a numeric-*string*
  `start_fiscal_year`/`end_fiscal_year` crashed `formulas.py`'s
  `end_fiscal_year - start_fiscal_year`; `not isinstance(x, int)` checks
  replace the old `x is None` checks (a strict superset, so the
  existing `None` handling is unchanged).
- **`eval_harness.py`'s `grade_judged()` bypassed `llm_backends.py`
  entirely (§3), fixed first since it also reduces §2's blast radius.**
  It made its own raw `requests.post` with no retry, reintroducing the
  exact "Ollama not accepting connections yet" failure the *answering*
  path was already hardened against. `llm_backends._ollama_call()` was
  renamed to `ollama_call()` (public — it's now used from a second
  module) and its hardcoded `temperature: 0.1` became
  `state.get("temperature", 0.1)`, since the judge deliberately wants
  `0.0` for stricter grading; `grade_judged()` now builds a `state`
  dict and calls it directly, gaining the same retry/backoff and
  `log_event("llm_retry", ...)` logging the generation path already
  had, for free.
- **`eval_harness.py`'s `run_eval()` had no per-question exception
  isolation (§2).** One question exhausting its retries (now less
  likely after the §3 fix, but still possible, and other bugs could
  still raise) used to discard every already-graded result in the
  batch — no partial report, no Langfuse flush. Wrapped the per-question
  body in `try`/`except Exception` (broad and commented as deliberate:
  this is a boundary where many different failure types should all
  degrade the same way), recording a `passed: False` result with the
  exception detail instead, then continuing to the next question.
  `flush()` still always runs after the loop.
- **`compare_financial_metric` silently returned empty for
  `total_assets`/`cash_and_equivalents`/`inventory` at the latest
  fiscal year (§4).** `get_metric_all_companies()` anchored only on the
  requested ticker's own fact to read its SEC-assigned `frame`, and gave
  up if that one company's latest annual entry happened to lack a frame
  — confirmed live this happens routinely (SEC doesn't always assign a
  frame to the newest annual instant-fact entry). Since a frame is a
  property of the (metric, period) pair, not of any one company, the
  fix tries every *other* covered company's own entry for the same
  period as a fallback anchor before giving up — still never computes a
  frame label independently (ruled out by this module's own top-level
  comment, from a bug fought twice before). Requested ticker is tried
  first, so today's success path is unaffected.

**Verified, not just tested.** New/extended tests: `tests/test_agent.py`
(+5: non-hashable ticker/metric in both tool functions, non-int
multi-year-average years), `tests/test_llm_backends.py` (+2: `ollama_call`
respects/defaults `state["temperature"]`, plus a rename of `_ollama_call`
→ `ollama_call` throughout), `tests/test_eval_harness.py` (+2: `grade_judged`
tests updated to mock `ollama_call` instead of `requests.post`, one new
test asserting `temperature=0.0`/`tool_schemas=[]`, plus `run_eval()`'s
first-ever unit test for its per-question exception isolation — the
loop's control flow is pure once `run_agent`/`grade_judged` are mocked,
even though the loop as a whole is otherwise live-only),
`tests/test_xbrl_facts.py` (+2: fallback-to-another-company's-frame,
and a regression guard that the requested ticker is still tried first).
Full suite **376/376**, up from 365. Live-verified: (1) ran a small real
eval batch (`crm-rpo-fy26`, `pltr-dividend-2019-refusal`) end-to-end,
confirming `grade_judged` still parses PASS/FAIL correctly through the
new `ollama_call` path; (2) found a real case in the cached XBRL data
where NVDA's own `total_assets`/`cash_and_equivalents`/`inventory` frame
is `None` for FY2026 but MSFT's isn't, and confirmed
`get_metric_all_companies("NVDA", ...)` went from returning `{}` to
returning all 5 (3 for `inventory`, which not every company tags)
covered companies' values.

**Addendum (2026-09-07): §4's fallback shipped with a real regression,
found and corrected the next day, before the next backlog batch
started.** Borrowing another covered company's SEC-assigned `frame`
turned out to be wrong, not just an approximation: a `frame` anchors to
a specific calendar window, and a DIFFERENT company's frame represents
a genuinely different real time period, not "the same period, from
someone else's data." Live-verified the actual failure: anchoring NVDA
(own FY2026 total_assets = $206.8B, period ending 2026-01-25, no frame)
against MSFT's frame (`CY2026Q2I`, representing June 2026) returned
NVDA's *Q2 FY2027* balance ($320.3B, period ending 2026-07-26)
mislabeled as if it were the requested FY2026 figure — a plausible-
looking wrong number, worse than the original honest `{}`.

Root-caused via two independent sources rather than another guess: (1)
`formulas.py`'s own `RATIO_DEFINITIONS` comment already documented that
a borrowed frame doesn't resolve correctly for instant concepts — missed
on the first pass; (2) web research into how financial-data tools
normally solve this confirmed SEC's frame-assignment gap on instant
facts is intentional/documented SEC behavior, and that "calendarization"
(aligning fiscal periods across companies to a shared calendar window) is
standard practice for income-statement/cash-flow (duration) figures but
is explicitly **not** applied to balance-sheet (instant) figures — a
balance is a snapshot as of one date, not a period that can be shifted;
real practice compares each company's own most-recent balance sheet.

**Redesigned `get_metric_all_companies()` to split by concept type**
instead of patching the fallback further (two alternatives were
presented and discussed before choosing this one over a closest-date-
match-with-tolerance mechanism, which would have fought against the
research above rather than followed it): new `INSTANT_METRICS =
{"total_assets", "cash_and_equivalents", "inventory"}` registry: for
these, no frame, no anchor requirement at all — resolves each covered
company independently via its own `get_metric()` call for the same
requested period, returning whichever companies have data, each with its
own real `period_end` (already surfaced per-company in the citation, so
a reader sees the dates genuinely differ — nothing hidden). Duration
metrics are completely unchanged — the frames-based anchor logic was
never the problem. `agent.py`'s `_comparison_as_results()` now shows a
real `form` (10-K/10-Q) for instant-metric citations instead of always
hardcoding "XBRL frame data", since per-company `get_metric()` results
carry one and frame results still don't.

**Checked, not assumed, whether this touches any eval question**: none
of the 40 existing questions exercise `get_metric_all_companies` for an
instant metric — the only cross-company `type: "comparison"` questions
use tax rate/employee count/revenue. That's also *why* neither the eval
suite nor the same-day self-review caught the regression — a real
coverage gap, not just bad luck. Closed it: new question
`aapl-msft-total-assets-comparison` (AAPL FY2025 total_assets =
$359,241M vs. MSFT FY2025 = $619,003M, both verified live against the
real cached XBRL data, not guessed), live-verified passing end-to-end
through the real agent/retrieval stack.

**Verified, not just tested (this addendum).** `tests/test_xbrl_facts.py`:
removed the 2 tests written for the abandoned frame-borrowing fallback,
added 3 new ones for the instant-metric path (independent per-company
resolution, missing-company exclusion, and a regression guard that
`get_frame()` is never called for an instant metric). `tests/test_agent.py`:
+1 for `_comparison_as_results()`'s real-form pass-through. Full suite
**378/378**. Live-verified the exact repro that exposed the bug:
`get_metric_all_companies("NVDA", "total_assets", fiscal_year=2026, fiscal_period="FY")`
now returns NVDA's own correct $206.8B/2026-01-25 (not MSFT's borrowed
window).

**Second addendum (2026-09-07): the layered review this change actually
required (Substantial tier — a real architecture decision) surfaced 6
more real findings, caught by the `/code-review` skill's background
angle-agents where an independent architecture-focused subagent found
nothing.** Two were duplicated independently by separate review angles
— a strong signal they were real, not noise:

- **[Fixed, High] `agent.py`'s `no_data_for_ticker` telemetry only fired
  when the WHOLE comparison result was empty**, not when the requested
  `anchor_ticker` itself was missing from an otherwise non-empty one —
  newly reachable because the instant-metric path has no anchor-
  availability precondition (unlike duration). Concretely:
  `compare_financial_metric(anchor_ticker="PLTR", metric="inventory")`
  returned AAPL/MSFT/NVDA's real data with PLTR silently absent and zero
  signal that PLTR (the company actually asked about) has none. Fixed:
  `if not result or anchor_ticker not in result:` — other companies'
  data still returned (genuinely useful), telemetry now fires correctly
  for the anchor-specific gap too. Live-verified against real PLTR/
  inventory data.
- **[Fixed, Medium-High] The redesign's docstring inaccurately claimed
  duration metrics were "unchanged from before".** True relative to the
  pre-2026-09-06 codebase, false relative to what actually shipped for
  one day: yesterday's fallback applied to EVERY metric, including
  duration ones, and today's redesign silently (and correctly — the
  same borrowed-window bug applies equally there) removed it for those
  too, undocumented and untested. Fixed the docstring to say so
  explicitly; added a regression guard confirming a duration metric
  never queries another company even when its own frame is missing.
- **[Documented, not fixed, Medium] `period_end_date`-based cross-company
  comparison for instant metrics effectively collapses to one company**
  — the identical literal date is passed to every company, and
  different companies' snapshots essentially never share an exact date.
  A real, known trade-off of the chosen design (the closest-date-
  matching alternative that would have handled this was explicitly
  considered and declined during planning) — documented in the
  docstring as a known limitation rather than silently left undiscussed.
- **[Fixed, Low] `INSTANT_METRICS` could silently drift from
  `DEFAULT_METRIC_TAGS`** — a future instant metric added without also
  updating `INSTANT_METRICS` would reproduce this exact bug class with
  no guard catching it. Proportionate fix for a Low-severity, no-
  automated-cross-check-elsewhere-in-this-file risk: a cross-reference
  comment at `DEFAULT_METRIC_TAGS` itself, at the point a future editor
  would actually add a new metric.
- **[Fixed, Low] Stale `mcp_server.py` docstring** claimed cross-company
  facts never carry `form`/`filed` — no longer universally true for the
  instant-metric path. Code already handled both shapes correctly;
  updated the comment.
- **[Deferred, Low] `formulas.py`'s `RATIO_DEFINITIONS`
  `supports_cross_company=False` gate wasn't revisited** even though the
  instant-frame problem it's justified by is now partly fixed for raw
  metrics — `get_ratio_all_companies()` uses a separate, still frame-
  only path. Real, but separate, larger-scope item; added to
  `BACKLOG.md` rather than folded in here.

Full suite **380/380** after these fixes.

### Fixed 3 Medium-priority findings from the 2026-09-06 full-codebase review (2026-09-08)

See `docs/reviews/2026-09-06-full-codebase-review.md` §5/§7/§9 for the
original findings and `BACKLOG.md` for what's still open from that
review.

- **`chunk_documents.py`'s final chunk-flush had no tail filter (§5).**
  `chunk_blocks()` already dropped a small leftover chunk mid-loop when
  it was nothing but the untouched overlap carry-over from the last
  flush (a raw character slice that can land mid-`<TABLE>`), but the
  final flush after the loop ends had no equivalent check, so a filing
  that happened to end right after a mid-loop flush emitted that stale
  overlap remnant as its own malformed, mistagged last chunk. Root cause
  mattered here: the mid-loop check's `len(current) > MIN_STANDALONE_CHUNK_CHARS`
  is only a safe *proxy* for "this is pure overlap, dropping it loses
  nothing new" — the invariant that makes the proxy safe doesn't hold at
  the final flush (a short *genuine* final block, e.g. a small paragraph
  right after an oversized table, would have been silently discarded by
  the same length check — trading a "malformed duplicate chunk" bug for
  a worse "silently lost data" one). Fixed by tracking an explicit
  `current_is_only_overlap` flag instead of guessing from length, used
  at both the mid-loop and final flush; `MIN_STANDALONE_CHUNK_CHARS`
  became dead and was removed. Live-verified against the 25 already-
  ingested filings: `git stash`-ing just this fix and diffing
  before/after found AAPL's `0000320193-26-000020` 10-Q dropping from 43
  chunks to 42, with the removed chunk being exactly `OVERLAP_CHARS`
  (200) characters — the exact bug pattern — and confirmed by hand that
  its content (the signature-block `<TABLE>`) was already fully present,
  intact, in the new last chunk.
- **`edgar_ingest.py`'s `get_filing_list(cik)` call was unguarded (§7).**
  Unlike the per-filing loop right below it, one company's network
  failure aborted ingestion for every subsequent company too. Wrapped in
  a broad, commented `except Exception` — matching the per-filing catch
  three lines below rather than trying to enumerate every failure type
  `get_filing_list()` could raise (see addendum below for why the first
  attempt at the latter wasn't good enough) — printing the same
  `✗ Failed: ...` style message and continuing to the next company.
- **`formulas.py`'s ratio computation had no zero-denominator guard
  (§9).** Unlike `get_yoy_growth`, which already handles this.
  `inventory_turnover` (`cost_of_revenue / inventory`) was the most
  exposed case per the review. Added `denominator["value"] == 0` guards
  to both `_compute_ratio_metric()` (returns `None`, matching every
  other "can't compute this" path) and
  `_compute_ratio_metric_all_companies()` (skips just that company,
  matching how a period-end mismatch is already handled, rather than
  discarding the whole cross-company result).

New/extended tests: `tests/test_chunk_documents.py` (+2: drops a
final-flush-only overlap tail, keeps a short genuine final block),
`tests/test_edgar_ingest.py` (+3: `main()` continues to the next company
when `get_filing_list` raises a network error, a malformed-JSON error,
or a malformed-schema error — the live boundary functions are mocked so
this exercises `main()`'s own deterministic control flow, not a real
network call), `tests/test_formulas.py` (+2: zero-denominator returns
`None`/excludes just that company). Full suite **387/387**, then
**388/388** after the round-2 addendum below.

**Addendum: the layered review (step 7) caught a real gap in the first
`edgar_ingest.py` fix.** `/code-review` flagged that the first attempt —
`except (requests.RequestException, ValueError, KeyError)`, reasoning
from `get_filing_list()`'s two calls (`raise_for_status()`, `resp.json()`)
— was narrower than the function's real failure surface. A
fresh-subagent architecture pass (no memory of the fix) then found the
same gap from a different angle and went further: even that three-type
tuple would still miss e.g. a `TypeError` if SEC ever returned
`recent["form"]` as a non-sequence, and pointed out the fix's own
comment already claimed parity with the per-filing catch below it
without actually matching it (that catch is a bare `except Exception`).
Two independent review angles converging on the same under-broad catch
was a strong signal it was real, not noise — matching the
2026-09-07 fix's own experience with layered review. Switched to a
broad, commented `except Exception`, the same pattern already used one
scope down, and added a `ValueError` test case alongside the existing
`KeyError`/`ConnectionError` ones so more than one of the exception
tuple's original members is actually exercised.

**Second addendum: round 2 of the layered review (a second `/code-review`
pass plus 4 fresh angle-subagents on the now-fixed diff) found one more
real gap.** `chunk_blocks()`'s mid-loop overflow-close branch shares the
exact same `current_is_only_overlap` flag-check logic as the final
flush, but only the final-flush case had a test proving genuine short
content survives rather than getting dropped — a regression that
reintroduced a length check in just the mid-loop branch would have
slipped past the full suite. Added
`test_chunk_blocks_keeps_short_genuine_content_closed_out_mid_document`
and confirmed by hand (a standalone simulation of the old length-
heuristic body) that pre-fix logic really would have silently dropped
that content. Two Low-severity, non-blocking design notes from this
round (a `formulas.py` zero-guard duplication worth a future
`_safe_ratio()` extraction, and a `chunk_blocks()` latent-but-
unreachable empty-block edge case) went to `BACKLOG.md` instead of being
fixed here, per CLAUDE.md's Standard-tier minimalism rule. Full
findings: `docs/reviews/2026-09-08-fix-3-medium-review-findings.md`.

**Third addendum: re-indexed and spot-checked end-to-end after
confirming the vector index was stale.** The unit-test/`git stash`
verification above confirmed `chunk_documents.py`'s fix at the chunk
level, but `chroma_db/`'s collections predated this session by weeks —
the fix hadn't actually reached retrieval yet. Ran `index_chunks.py`
(drops and recreates the `sec_filings` collection, exactly the scenario
its own comment already anticipated: "e.g. after a
chunk_documents.py fix") — 3206 chunks re-embedded (`bge-small-en-v1.5`),
counts by ticker unchanged (AAPL 245, CRM 772, MSFT 623, NVDA 451,
PLTR 1115). Rather than the full ~40-question eval suite (expensive on
local Ollama, and the fix only changed one filing's trailing,
non-financial signature-block content), spot-checked the 4 eval
questions that actually target the one changed filing (AAPL's
`0000320193-26-000020`, its Q3 FY2026 10-Q) on both backends:
`aapl-operating-margin-q3fy2026`, `aapl-revenue-growth-q3fy2026`,
`aapl-cash-equivalents-q3fy2026`, `aapl-cash-and-buyback-q3fy2026`.
Ollama: 3/4 passed (32.6% margin, 16.4% growth, $39.544B cash all
correct); the comparison question failed the same way it's failed on
Ollama every time it's been run since 2026-08-25
(`20260825T044611Z`/`20260825T195207Z`), while passing cleanly on
Gemini both then and now (`20260825T02*`/`20260825T190858Z`/
`20260908T225358Z`) — a known local-model comparison-question ceiling
already documented under "Cloud-model spike" above, not a regression
from today's reindex. Gemini: 4/4 passed, including the comparison
question. Confirms the reindexed corpus retrieves this filing's data
correctly post-fix.

### Fixed 3 more findings from the 2026-09-06 full-codebase review (2026-09-09)

See `docs/reviews/2026-09-06-full-codebase-review.md` §6/§8/§10 for the
original findings and `BACKLOG.md` for what's still open from that
review.

- **`chunk_documents.py`'s `strip_leading_metadata()` could truncate a
  document to 1 character (§6).** Its nested `rfind()` needs the
  newline two lines back from the anchor; with fewer than 2 newlines
  preceding it (anchor on/near the very first line — never happened
  across the 25 currently-ingested filings, but nothing prevents a
  future one), the inner-then-outer `rfind` chain returned `-1`, and
  `text[-1:]` doesn't mean "from the start" in Python — it silently
  returned the document's last character. Traced by hand: `"UNITED
  STATES\nSECURITIES AND EXCHANGE COMMISSION\nreal content"` returned
  `"t"`. Fixed by guarding the outer `rfind`'s result, falling back to
  `0` (keep everything) when no second newline exists.
- **A non-int `fiscal_year` silently misrecorded as
  `"no_data_for_ticker"` telemetry (§8).** Unlike
  `start_fiscal_year`/`end_fiscal_year` (already guarded in the
  2026-09-06 High-priority batch), plain `fiscal_year` was never
  type-checked in either `call_get_financial_fact` or
  `call_compare_financial_metric` — a numeric-string year didn't crash,
  it just failed every downstream lookup and got recorded as a genuine
  data gap, polluting the "should we add a formula for this" signal
  with schema-violation false negatives. Fixed by mirroring the
  existing `invalid_metric_type` guard shape: a new
  `reason="invalid_fiscal_year_type"` rejection in both functions,
  logged via `log_event` (not `record_unmet_metric_request`, since it's
  a schema violation, not a data gap) — checked once per function,
  before any of the branches that read `fiscal_year` downstream.
- **`tracing.py`'s `traced_span()` never recorded exception info
  (§10).** `try`/`finally` with no `except` meant a crash and a clean
  no-op wrote an identical local JSONL log line and left an
  identical-looking Langfuse observation — undercutting the "always-on
  debugging backup" this exists for. Fixed by adding an
  `except Exception as e: ...; raise` between the existing `try` and
  `finally`: records `span.error = f"{type(e).__name__}: {e}"`, marks
  the Langfuse observation via `span.update(level="ERROR",
  status_message=str(e))` (the exact pattern the `langfuse` SDK's own
  internal call sites use, confirmed in the installed 4.15.1 package —
  no new API surface guessed at), then always re-raises. No
  propagation change: nothing swallowed exceptions before this fix
  either, and nothing does now — this only adds visibility. `_TracedSpan`
  gained an `error` attribute (`None` on success) and the local log
  record gained a matching `"error"` field.

New/extended tests: `tests/test_chunk_documents.py` (+2: one-newline-
and zero-newline-before-anchor cases), `tests/test_agent.py` (+2:
non-int `fiscal_year` rejected in both `call_get_financial_fact` and
`call_compare_financial_metric`), `tests/test_tracing.py` (+2: exception
recorded and re-raised, both with Langfuse enabled and disabled). All
three fixes are pure/deterministic logic — full TDD, no live-only
carve-out needed. Full suite **394/394**.

**Addendum: round 2 of the layered review (a second `/code-review` pass
plus a fresh architecture subagent) found two real gaps, both in the
§8/§10 fixes rather than §6.**

1. **`agent.py`'s new `fiscal_year` guard was placed before the
   multi-year-average branch even checks whether it applies** — that
   branch (`start_fiscal_year`/`end_fiscal_year`) never reads plain
   `fiscal_year` at all, so a stray/malformed `fiscal_year` alongside a
   *valid* start/end pair used to be silently ignored (pre-fix) but got
   wrongly rejected outright (post-fix) before ever reaching the branch
   that would have ignored it — a real regression the fix's own test
   suite never exercised (no test combined `fiscal_year` with
   `start_fiscal_year`/`end_fiscal_year`). Fixed by moving the guard to
   after the multi-year-average branch's own early returns, so it only
   gates the two branches that actually read `fiscal_year`
   (`yoy_growth` and the plain lookup). Added
   `test_call_get_financial_fact_ignores_malformed_fiscal_year_in_multi_year_average_request`
   as the regression guard.
2. **`tracing.py`'s manual Langfuse `span.update(level="ERROR", ...)`
   call was dead code** — confirmed by reading the actual installed SDK
   source (`opentelemetry/trace/__init__.py`'s `use_span()`), not
   assumed: `start_as_current_span()` already defaults to
   `record_exception=True, set_status_on_exception=True`, so it
   auto-records the exception and sets ERROR status on the real
   Langfuse span *before* control ever reaches this function's own
   `except` clause — that inner `with` block's own `__exit__` (which
   performs the auto-recording) always runs first as the exception
   unwinds through it, ending the span in the process. By the time the
   manual `.update()` call ran, `LangfuseObservationWrapper.update()`'s
   own `if not self._otel_span.is_recording(): return self` guard
   silently no-ops it — confirmed by reading `langfuse/_client/span.py`
   directly. The unit test's `_FakeObservation` stub couldn't reveal
   this: it has no `is_recording()`/close semantics, so it happily
   recorded the call anyway. Removed the manual call entirely (it was
   both redundant with and strictly less complete than OTel's own
   default recording) and rewrote the docstring/comment to document
   why, so a future maintainer doesn't "helpfully" re-add it. The local
   JSONL `error` field — the actual gap §10 named — is unaffected and
   still correctly populated; only the never-functional Langfuse-side
   addition was cut.

Round 2 also confirmed (not a new finding, re-verified independently):
the `isinstance(fiscal_year, int)` bool-subclass-of-int gotcha
(`isinstance(True, int)` is `True`) is real but pre-existing — the
identical pattern already shipped for `start_fiscal_year`/
`end_fiscal_year` before this diff, so this fix mirrors an existing,
accepted limitation rather than introducing a new one. Not worth fixing
in isolation for one call site while the other two stay as-is; added to
`BACKLOG.md` as a single cross-cutting note covering all three instead.

Full suite **395/395** after the round-2 fixes. Full findings:
`docs/reviews/2026-09-09-fix-3-more-review-findings.md`.

### Fixed 3 more findings from the 2026-09-06 full-codebase review (2026-09-10)

See `docs/reviews/2026-09-06-full-codebase-review.md` §11/§12/§13 for
the original findings and `BACKLOG.md` for what's still open from that
review.

- **`mcp_server.py` never called `tracing.flush()` on shutdown (§11).**
  Confirmed by reading the actual installed `mcp`/Starlette/uvicorn
  source, not assumed: `Server.streamable_http_app()` builds its own
  internal Starlette lifespan with no hook exposed for caller-supplied
  shutdown logic, so there's no clean way to plug into it from
  `mcp_server.py`. Separately, `uvicorn.Server` converts both `SIGINT`
  and `SIGTERM` into a clean `serve()` exit, so `uvicorn.run()` returns
  normally (no exception) on either — both realistic shutdown paths.
  Fixed with a `try/finally` around `uvicorn.run()` calling `flush()`
  in `finally`, which also covers an unexpected crash inside
  `uvicorn.run()` itself, not just the two clean-exit paths.
- **Two smaller `agent.py` consistency gaps (§12).**
  `_format_no_comparison_message` was missing the "never tagged" hint
  its sibling `_format_no_fact_message` already has (the compare tool's
  `args` already carries `anchor_ticker`/`metric` — no new plumbing
  needed, just the same `_never_tagged_hint()` call). `search_filings`
  never validated a provided ticker the way
  `call_get_financial_fact`/`call_compare_financial_metric` do — a
  hallucinated ticker fell through to `hybrid_search` with no
  rejection or telemetry signal. Fixed by rejecting a
  provided-but-invalid ticker in `_dispatch_tool_call`'s search-filings
  branch with the same `reason="unknown_ticker"` `log_event`, while
  still allowing `ticker=None` (a broad, unsure search is deliberately
  valid for this tool, unlike the other two).
- **`edgar_ingest.py`'s `parse_filing()` had zero test coverage (§13).**
  No code change — `parse_filing()` is genuinely pure (only touches its
  `html` argument, `BeautifulSoup`, and `re`; no I/O, no globals, no
  randomness), confirmed by reading the full function body, but had
  never been called directly by any test (only ever monkeypatched away
  in `main()`'s resilience tests). Added 10 unit tests covering every
  edge case the function's own comments call out: empty/layout-only
  table dropping, marker-index alignment across multiple tables,
  empty-row skipping within a table, cell/prose whitespace collapsing,
  and the header/footer noise-stripping regex (including a case
  proving it doesn't over-match ordinary prose with one `|` character).
  All 10 passed immediately against the unchanged function — this was
  a real, not just theoretical, coverage gap, not a bug.

New/extended tests: `tests/test_mcp_server.py` (+2: `main()` flushes
after `uvicorn.run()` returns, and even when it raises),
`tests/test_agent.py` (+4: comparison-message never-tagged hint
included/omitted, `search_filings` rejects an unrecognized ticker,
`search_filings` still allows no ticker filter),
`tests/test_edgar_ingest.py` (+10: `parse_filing()`, see above). Full
suite **411/411**.

**Addendum: round 2 of the layered review (a second `/code-review` pass
— 8 background finder angles — plus a fresh architecture subagent)
found four more real gaps, three of them pre-existing bugs the new
tests happened to expose or the new code happened to sit next to,
rather than something the §11/§12/§13 fixes introduced themselves.**

1. **`tracing.py`'s `flush()` had no "never raise" contract**, unlike
   `_write_local_log()`'s explicitly documented one — found
   independently by the architecture subagent and two `/code-review`
   angles. Newly consequential because of §11's own fix: `mcp_server.py`'s
   `main()` now calls `flush()` inside a `finally` wrapping
   `uvicorn.run()`, so an unguarded Langfuse network failure there would
   have replaced/masked whatever real exception `uvicorn.run()` was
   propagating — hiding the actual shutdown/crash reason. Fixed by
   wrapping `flush()`'s body in the same broad,
   commented `except Exception` pattern `_write_local_log()` already
   uses, printing to stderr instead of raising. Benefits every caller
   (`agent.py`, `eval_harness.py` too), not just the new one.
2. **`search_filings`' ticker guard still crashed on a non-hashable
   ticker** (e.g. a list) — found independently by two angles. The
   §12 fix's guard ran *after* `_resolve_search_args()`, which already
   crashes first on `ticker not in searched_tickers` (a set) for an
   unhashable value — the exact crash class `call_get_financial_fact`/
   `call_compare_financial_metric` were already fixed for on
   2026-09-06, just never closed for this third tool. Fixed by moving
   the check before `_resolve_search_args()` runs, and folding it into
   the same single `not isinstance(ticker, str) or ticker not in
   COMPANIES` condition (with the same `reason="unknown_ticker"`) the
   sibling tools already use, instead of the two separate checks the
   first pass had.
3. **`edgar_ingest.py`'s `parse_filing()` had a real, pre-existing
   leading/trailing-newline bug**, found by the architecture subagent
   (verified by actually running the function): the header/footer
   noise-stripping regex ran *after* the function's own `.strip()`, so
   removing a noise line sitting at the very start or end of a document
   left a stray blank line behind — none of the 10 new tests happened
   to combine "noise line" with "at the document edge," so the gap
   wasn't caught by the coverage addition itself. Fixed with a second
   `.strip()` after the header/footer block; also corrected that
   block's comment, which inaccurately claimed the code was "left
   commented out" when it's active.
4. **Three independent review angles flagged the same duplication**:
   the new `fiscal_year` type guard (§8, 2026-09-09) was hand-copied
   verbatim between `call_get_financial_fact` and
   `call_compare_financial_metric`. Extracted into a shared
   `_rejects_invalid_fiscal_year(tool, args)` helper.

Also applied: a redundant `if first_nl != -1 else 0` branch in §6's
`strip_leading_metadata()` fix (verified by hand and empirically that
`preceding.rfind("\n", 0, first_nl)` is already `-1` whenever
`first_nl == -1`, so the ternary never changed the result); trimmed
`mcp_server.py`'s `main()` comment, which had grown several times
longer than the 3 lines of code it explained (the deeper
investigation notes already live in this section).

Four Low-severity findings went to `BACKLOG.md` instead of being fixed
here, per CLAUDE.md's Standard-tier minimalism rule: `_never_tagged_hint()`'s
redundant SEC network call on the never-tagged-concept case (root cause
is in `xbrl_facts.fetch_concept()`'s 404-doesn't-cache behavior, a
separate, larger-scope item); `tracing.py`'s `span.error` formatting
could theoretically raise if an exception's own `__str__` raised (not
currently reachable — no exception type actually raised anywhere in
this codebase has a broken `__str__`); a broader "generic schema-driven
arg-validator" idea spanning all three tools (Substantial-scope
redesign, not a bug); and an incidental inconsistency in how the three
tools' unknown-ticker rejections are worded (a real but deliberate-
decision-later item, not a defect).

Round 3 (a third `/code-review` pass on the fixed diff) came back
clean, closing the loop. Full suite **414/414**. Full findings:
`docs/reviews/2026-09-10-fix-3-more-review-findings.md`.

### Schema-driven arg/input validation redesign (2026-09-09)

Substantial-scope redesign — see `docs/plans/2026-09-09-schema-driven-arg-validation.md`
for the full design and `docs/reviews/2026-09-09-schema-driven-arg-validation.md`
for the two-pass review. Picked up from `BACKLOG.md`'s highest-impact
open item: the same hand-rolled tool-arg validation pattern
(`call_get_financial_fact`, `call_compare_financial_metric`,
`search_filings`'s dispatch branch, each hand-checking args against its
own `*_TOOL_SCHEMA`) had broken three separate times across three
different review dates — most recently `isinstance(fiscal_year, int)`
silently accepting a JSON boolean, since `isinstance(True, int)` is
`True` in Python.

**Core fix: one generic `validate_tool_args()` in `agent.py`, backed by
the `jsonschema` library (pinned `4.26.0`, chosen over hand-rolling —
`jsonschema`'s default type checker already excludes `bool` from
`"integer"`, fixing the recurring bool/int bug as a side effect of the
library switch rather than a special case written a 4th time).** Each
`*_TOOL_SCHEMA["function"]["parameters"]` dict got `"additionalProperties":
false` added, so the same schema now doubles as both what's advertised
to the LLM and what's enforced at runtime — replacing the hand-rolled
`set(args) - _FACT_ARG_KEYS`-style extra-key checks entirely. Two
carve-outs preserve behavior a flat schema check can't express: a
`metric` enum violation is let through so callers can still route a
recognized-shape-but-unsupported metric name to
`record_unmet_metric_request()`'s telemetry instead of a silent
rejection; `fiscal_year`/`start_fiscal_year`/`end_fiscal_year` are
excluded from the generic pass entirely (their own type is still
checked by `_rejects_invalid_fiscal_year`, now itself jsonschema-backed)
since the multi-year-average request shape never reads plain
`fiscal_year` at all, and a malformed value there must be ignored, not
rejected. Also fixed as a natural side effect: `mcp_server.py`'s
`_search_filings` handler had zero ticker validation (unlike its
siblings, which inherit validation for free by delegating into
`agent.py`'s now-validated `call_*` functions) — now calls the same
`validate_tool_args()` against `SEARCH_TOOL_SCHEMA`.

**Extended to two more trust boundaries, per the user's own follow-up
question ("where else would this help?") after the core fix was
designed:**
- `llm_backends.py` used to index straight into the raw LLM response
  (`c["function"]["name"]`, `resp.candidates[0]`) with no shape check —
  a malformed/unexpected response crashed with a bare `KeyError`/
  `IndexError` *before* a tool call ever reached `agent.py`'s own
  validation. Ollama's raw response is a plain dict (a genuine
  JSON-native boundary), so it gets a `jsonschema` check; Gemini's raw
  response is an SDK object, not JSON, so `jsonschema` doesn't apply
  directly there — a plain guard clause instead (`if not resp.candidates:
  raise RuntimeError(...)`), a deliberate, documented exception. Both
  backends' *normalized* `ModelTurn.tool_calls` output (the one truly
  shared, JSON-native boundary `agent.py`'s dispatch actually indexes
  into) gets one shared `jsonschema` check regardless of which backend
  produced it.
- `companies.py`'s `load_companies()` had no runtime shape check on
  `companies.json` — a malformed entry surfaced as a confusing `KeyError`
  three layers down in some unrelated ticker/metric lookup instead of
  one clear error at load time. Fixed with a small schema + a
  `_validate()` function that re-raises `jsonschema.ValidationError` as
  a plain `ValueError` naming the file and the specific violation.

**Tests**: the ~25 existing hand-written per-field validation tests in
`tests/test_agent.py` were mostly kept (each still documents a real
found-bug scenario, not blanket-replaced) with their `reason=` string
assertions updated to the new taxonomy (`f"{property}_{violation_kind}"`,
e.g. `ticker_not_in_enum`, `fiscal_year_wrong_type`; fixed literals
`unrecognized_extra_argument`/`missing_required_argument` for the two
violation kinds with no single named property) — expected migration
cost, not a correctness change, confirmed by running the full suite
before and after each taxonomy update. New: a dedicated
`validate_tool_args` test section (schema-driven, walks properties
rather than one hand-written test per field), a direct regression test
proving `fiscal_year=True` is now rejected (the bug that motivated the
whole redesign), new `tests/test_llm_backends.py`/`tests/test_companies.py`
tests for the two extended boundaries, and a new
`tests/test_mcp_server.py` test for the previously-unvalidated
`search_filings` ticker gap. Full suite **440/440**. Manually verified
both live paths still accept legitimate args after the change: a real
`python agent.py "..."` run (Ollama backend, both `get_financial_fact`
and `search_filings` tool calls) and a full `tests/manual/verify_mcp_server.py`
pass (including the fixed `search_filings` ticker check).

**Two-pass layered review found and fixed one real regression, plus two
smaller design issues in round 2:**
1. **A real regression, round 1**: the `period_end_date` schema field
   was made nullable (`["string", "null"]`) after live testing showed
   the model can send an explicit `null` for an unset optional argument
   — but this was applied as a one-off patch to that single property
   instead of recognizing the general problem. `SEARCH_TOOL_SCHEMA`'s
   `ticker` (previously tolerated as `null` = "no filter" by the old
   hand-rolled check) and `FACT_TOOL_SCHEMA`'s `fiscal_period`/
   `yoy_growth` had the identical gap, silently turning a previously-valid
   `null` into a hard rejection. Fixed generally instead of per-property:
   `validate_tool_args` now treats any declared property's `null` value
   as equivalent to the key being absent (correctly converting to
   "missing" for a required property, "no violation" for an optional
   one), and the `period_end_date`-specific `["string", "null"]` patch
   was reverted as redundant. An unrecognized extra key is deliberately
   NOT exempted even when null-valued — `additionalProperties: false`
   must still catch it, since the key itself is the problem.
2. **Round 2 (fresh architecture subagent) found two more real issues**:
   the null-handling fix above had (in passing) routed its "which
   properties are declared" check through `set(...)`, losing the dict's
   declaration order and making `validate_tool_args`'s same-kind
   multi-violation tie-break silently depend on the process's hash seed
   instead of schema order — fixed by using the dict directly (`in` on a
   dict is already O(1), no reason to convert to a set first). Separately,
   `_validate_tool_args` (the original name) had become genuine shared
   production infrastructure imported by `mcp_server.py`, but kept its
   underscore-prefixed "internal" naming, inconsistent with every other
   cross-module import in this codebase — renamed to `validate_tool_args`
   throughout `agent.py`, `mcp_server.py`, and the tests.
3. **Round 2 also flagged two lower-priority items, deliberately not
   fixed**: `_dispatch_tool_call`'s `search_filings` branch re-derives
   ticker validity by hand a second time (after `validate_tool_args`
   already checked it) purely to pick which rejection message to show —
   filed to `BACKLOG.md` rather than fixed, since a clean fix means
   changing `validate_tool_args`'s return type across all 4 call sites
   for a 2-line message-selection convenience. A fresh
   `jsonschema.Draft202012Validator` built on every call rather than
   cached at module scope was flagged independently by both review
   rounds — left as-is both times: negligible cost given this app's
   dominant per-request latency is LLM inference itself (60-70s+ on the
   CPU-only Ollama setup), and the same-issue-twice-with-no-clean-fix
   case is exactly CLAUDE.md's own stated stopping condition for the
   review loop.

Also surfaced (not part of this change, filed to `BACKLOG.md` as new
Low items): `xbrl_facts.py`'s `get_metric()` does unchecked SEC-response
entry indexing after `_pick_entry*` filters it; `eval_harness.py`'s
`_select_questions` reads `q["id"]` before the per-question `try/except`
that contains most other malformed-question crashes.

Two originally-scoped items — the `xbrl_facts.py` `get_frame()` ordering
bug and a `retrieval.py` manual verification script — were explicitly
descoped by the user mid-planning to keep this change focused on schema
validation; both remain open in `BACKLOG.md`, untouched.

## Next steps

See `BACKLOG.md` for the live task backlog. This section used to hold
the backlog inline until it needed a 380-line cleanup pass once already
(2026-08-19) — moved out to its own file 2026-09-06 for the same
reason (a todo list embedded in a growing narrative doc doesn't stay
scannable). This file remains the narrative changelog: what changed,
why, and how it was verified, for every Standard-or-larger change, in
the `###` sections above.

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
