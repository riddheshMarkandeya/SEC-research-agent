# Retrieving period-specific financial tables

Date: 2026-09-28
Feeds: the retrieval-miss share of "not found" failures (about 10 of 68 eval failures since 2026-09-19).
The motivating case is MSFT's Q3 FY26 segment table (`chunks/MSFT/0001193125-26-191507_chunks.jsonl`,
chunk_index 35), which never reaches the reranker.

## Question

1. What do financial-document RAG papers and systems recommend for tables? The options are a table as its
   own chunk, row-level indexing, table summaries, contextual chunk headers and parent-child retrieval.
2. Can segment figures come from structured XBRL instead, and what would that take?
3. Should retrieval filter by period metadata before ranking, and how do systems infer the period from the
   question?

## Findings (what the sources say)

**Tables and chunking**

1. **Starting a new chunk at each table helps on SEC filings.** Jimeno Yepes et al. tested this on
   FinanceBench (80 filings, 141 usable questions, 7,700 table elements). Their chunker starts a new chunk
   whenever it meets a table: "if a table element is found, a new chunk is started, preserving the entire
   table". Element-based chunking reached 53.19% QA accuracy against 48.23% for 512-token chunks, with
   about 20.8k chunks instead of 64k. Page accuracy was 67.38% against 68.09%, so the gain came mainly with
   aggregation (84.40%). Each chunk also carried keywords, a summary and a prefix ("first two sentences or
   table captions"). https://arxiv.org/html/2402.05131v3
2. **Chunk-specific context helps.** Anthropic's contextual retrieval prepends 50–100 tokens of LLM-written,
   chunk-specific context before embedding and before BM25 indexing. Its SEC-filing example adds the
   company, the quarter and the prior-period figure. Measured as top-20 retrieval failure rate against a
   5.7% baseline:
   - contextual embeddings alone: −35% (3.7%);
   - contextual embeddings plus contextual BM25: −49% (2.9%);
   - with a reranker added: −67% (1.9%).

   https://www.anthropic.com/news/contextual-retrieval
3. **A metadata prefix helps on 10-Ks, and company and year matter most.** RAGMATE-10K (25 10-Ks, 5 tech
   companies) compared ways of adding metadata. Context@5 moved as follows:

   | Method | General questions | Deeper questions |
   |---|---|---|
   | No metadata | 33.33% | 31.67% |
   | Metadata-as-text prefix | 55.00% | 65.00% |
   | Unified dual-encoder embedding | 63.33% | 60.00% |

   A prefix beat a suffix. In the field ablations, "company and year provide the strongest disambiguating
   signal". https://arxiv.org/html/2601.11863
4. **Hybrid BM25 is the strongest single method on text-and-table financial data, and tables are the main
   cause of misses.** In "From BM25 to Corrective RAG", whole documents of about 920 tokens, not chunks,
   gave these Recall@5 figures:

   | Method | Recall@5 |
   |---|---|
   | BM25 | 0.644 |
   | Dense | 0.587 |
   | Hybrid RRF | 0.695 |
   | Contextual hybrid | 0.717 |
   | Hybrid plus Cohere rerank | 0.816 |
   | HyDE | 0.544 |

   The dominant failure mode was "table structure mismatch (73%)": markdown tables embed poorly.
   https://arxiv.org/html/2604.01733v1

   T²-RAGBench found the same ordering: Hybrid BM25 was best, at about 41% Number Match against a 72–79%
   oracle-context ceiling. https://arxiv.org/abs/2506.12071
5. **Fine-tuned passage retrieval and document-first retrieval also help.** DocFinQA used 2,750-character
   chunks with 20% overlap. BM25 did poorly there. A fine-tuned ColBERT reached HR@3 0.55 and improved
   HR by 91% over Sentence-BERT. https://arxiv.org/html/2401.06915

   HiREC (LOFin benchmark, 145,897 S&P 500 filings) retrieves the document first and the passage second.
   It also rewrites the query to state the fiscal year. Page recall rose from 34.78% to 45.35%, and answer
   accuracy from 29.22% to 42.36%. Its table cross-encoder was fine-tuned on FinQA tables because "titles,
   periods, and indicators matter more than numerical values". https://arxiv.org/html/2505.20368v3
6. **Scoping retrieval to the right document matters most.** FinanceBench measured GPT-4-Turbo under four
   setups:

   | Setup | Correct | Refused |
   |---|---|---|
   | Shared vector store | 19% | 68% |
   | Single vector store (per document) | 50% | 39% |
   | Long context | 79% | 4% |
   | Oracle | 85% | 0% |

   https://arxiv.org/html/2311.11944
7. **Not found.** No primary source with numbers covered row-level table indexing or parent-child retrieval
   on SEC data. TAT-DQA was not checked in this pass.

**Structured XBRL**

8. **The EDGAR APIs exclude dimensional facts.** companyfacts, companyconcept and frames only aggregate
   facts that "apply to the entire filing entity" and use a standard taxonomy. That leaves out
   axis/member facts such as segments. frames returns one fact per entity per calendar frame (for example
   `CY2019Q1I`), not per fiscal period.
   https://www.sec.gov/search-filings/edgar-application-programming-interfaces
9. **Segments are tagged on `us-gaap:StatementBusinessSegmentsAxis`.** The FASB guide says "Segments
   [Axis]" is used for disaggregating by reportable segment, and "Consolidation Items [Axis]" reconciles
   the segments to the total. https://xbrl.fasb.org/impguidance/SG1_TIG/segmentreporting.pdf
10. **The SEC's Financial Statement and Notes data sets may carry dimensions.** A secondary search summary
    says their NUM table gained a `segments` field ("{axis}={member};") in December 2024. The primary PDF
    could not be parsed here, so this is unverified.
    https://www.sec.gov/data-research/sec-markets-data/financial-statement-notes-data-sets

**Filtering by period**

11. **Mainstream frameworks infer the filter with an LLM.** LlamaIndex's `VectorIndexAutoRetriever` says:
    "we first use the LLM to infer a set of metadata filters as well as the right query string to pass to
    the vector db". It then applies those filters inside Chroma.
    https://developers.llamaindex.ai/python/examples/vector_stores/chroma_auto_retriever/
    HiREC does something similar by rewriting the query to state the fiscal year (source in item 5).
12. **Chroma supports `$in`/`$nin` on strings.** Its docs show `$gt`/`$lt` only with numbers. A date-range
    filter would therefore need a numeric field, for example `report_ym` stored as an int.
    https://docs.trychroma.com/docs/querying-collections/metadata-filtering

## Repo facts (checked 2026-09-28)

**How chunks and searches are built today**

- Chunk metadata already carries `ticker`, `form`, `filingDate`, `reportDate`, `accessionNumber` and
  `contains_table` (`chunk_documents.py:373-385`).
- `vector_search` filters only on `ticker` (`retrieval.py:169`), and `bm25_search` does the same after
  scoring (`retrieval.py:152`).
- The `search_filings` tool takes only `query` and `ticker`. All 1,851 logged calls in
  `trace_logs/traces.jsonl` have exactly those two keys.
- Each ticker has 5 filings in the corpus. For MSFT they are the 10-Ks for 2025-06-30 and 2026-06-30, and
  the 10-Qs for 2025-09-30, 2025-12-31 and 2026-03-31.

**Tables in the corpus**

- 858 of 3,182 chunks contain a table.
- In 235 of those, `<TABLE>` starts more than 800 characters into the chunk, which is the prose-dominated
  shape of the MSFT case.
- 178 month names are glued to the preceding word ("EndedMarch", "as ofJanuary"). `_tokenize`
  (`retrieval.py:102`, `[a-z0-9]+`) turns these into tokens such as `endedmarch`, so a query term like
  "march" never matches the table header.

**The prior decision this touches**

- A uniform per-filing period prefix was already tried and reverted
  (`docs/decisions/2026-08-16-fiscal-period-labels-tried-and-reverted.md`). The suite went from 14/16 to
  13/16, because the shared prefix pushed a boilerplate PLTR chunk from vector rank 30 to rank 8. Any
  proposal that adds period text to every chunk has to answer that decision.
- `period_labels.fiscal_year_label` and `fiscal_quarter` were kept from that attempt, and they are tested.

**Tracing and gold labels**

- Traces tie each `search_filings` call to its question through `run_id`, via the root `run_agent` row's
  `input.question`.
- Of the 48 questions in `eval/eval_questions.jsonl`, 28 have an `expected_value`, and the 12 judged ones
  state their figures in `criteria`.

**BM25-only simulation of the MSFT target**

I ran a throwaway script against the real chunk files, with no index changes and no LLM. The cell shows
the target chunk's BM25 rank, which must be 25 or better to enter the candidate pool.

| Variant | Ticker filter (613 or 809 chunks) | Ticker + reportDate 2026-03-31 (108 or 143 chunks) |
|---|---|---|
| Current chunks | 40 / 45 / 29 | 10 / 11 / 9 |
| Month names de-glued | 29 / 31 / 12 | 9 / 10 / 6 |
| Table split into its own chunk, de-glued | 39 / 38 / 6 | 10 / 10 / 2 |
| Split, plus a caption header (the filing line and the last 200 characters of prose before the table) | 34 / 39 / 1 | 9 / 10 / 1 |

Each cell gives ranks for three logged queries, in this order:
1. The eval question for which segment had the highest revenue.
2. The eval question for each segment's revenue.
3. The model's own keyword query ("Note Segment Information Three Months Ended March 31 2026 …").

Vector ranks were not simulated.

## Inferences (mine, not from the sources)

1. **A period filter is the biggest BM25 lever for this failure.** It is the only change that brings both
   natural-language questions into the 25-candidate pool. Splitting tables and adding headers mostly helps
   when the query already uses the table's own vocabulary, as the model's keyword query does. This matches
   FinanceBench's single-store result (item 6) and HiREC's document-first design (item 5).
2. **A hard filter avoids the failure that sank the 2026-08-16 attempt.** A filter does not change any
   chunk's embedding or BM25 text. It only removes other filings' near-duplicate chunks, such as the prior
   quarter's summary. The period prefix failed because prepending text to every chunk shifts embeddings in
   a non-additive way, and a filter has no such effect.
3. **A filter has its own risks.**
   - Comparative figures often live in a later filing's prior-period column, so a strict filter hides them.
   - Fiscal-year wording ("fiscal 2025") has to be mapped to a 10-K `reportDate` using
     `fiscal_year_label`.
   - A wrong parse removes the right filing.

   A safer shape adds the filtered search alongside the current one: run the period-filtered BM25 and
   vector searches as two more ranked lists in the existing RRF, and keep the unfiltered pool. That way a
   wrong or absent parse falls back to today's behaviour.
4. **Most queries carry a date, so parsing works without a model.** About 1,521 of the 1,851 logged
   queries contain a date, a year or a quarter pattern. The period can be parsed in code, with no tool
   schema change and no prompt change, so the panel protocol is not triggered. An explicit
   "Month D, YYYY" date maps to `reportDate` directly. A bare year or "FY26" maps through
   `fiscal_year_label` and `fiscal_quarter`.
5. **De-gluing month names is nearly free and is a real bug.** It helps BM25 on its own (40→29, 12 on the
   keyword query). The fix belongs in `chunk_documents.clean_row` / `table_to_markdown` and needs a
   re-chunk and a re-index. Split and header changes also mean re-chunking `chunk_blocks`, which is in the
   blast-radius core.
6. **A synthetic header must never be citable text.** Contextual headers (Anthropic, item 2) are the
   best-evidenced chunk-side change. If one is added, it has to go into the indexed and embedded text only,
   never the stored or returned text. Otherwise `table_grounding` could ground a quote against text that is
   not in the filing.
7. **XBRL segment data is feasible but is not the smallest change.** Reading segments from XBRL would mean
   downloading each filing's instance document, or the FS&N data sets, and parsing contexts on
   `StatementBusinessSegmentsAxis` (plus ConsolidationItemsAxis and custom members). It would also need a
   new tool or a new mode for `get_financial_fact`. It would fix segment questions exactly, but none of
   the other table misses.

## Open questions

1. What are the vector-search ranks under the same variants? The BM25 result may not carry over, since the
   2026-08-16 regression was vector-side.
2. How many of the ~10 retrieval-miss failures are period confusion (the right table in the wrong filing
   wins) and how many are dilution (the table ranks low even inside its own filing)? The offline harness
   below answers this.
3. Should a question without a parseable period get no period list, or a list scoped to the latest
   filing? The latest filing is a guess and could be wrong for historical questions.
4. Does the FS&N NUM `segments` field exist as described, and does it cover the 10-Qs here? The primary
   PDF needs checking.
5. TAT-DQA and parent-child retrieval were not researched with numbers.

## Recommendation

**Smallest change: add period-filtered candidate lists to `hybrid_search`.**
- Parse a period from the query deterministically:
  - an explicit "Month D, YYYY" date matches `reportDate`;
  - a fiscal year or quarter maps through `period_labels`.
- When the parse resolves to one or more corpus `reportDate`s, run `bm25_search` and `vector_search` a
  second time with `reportDate $in [...]`. Pass them into `reciprocal_rank_fusion` as two extra ranked
  lists, next to the unfiltered two.
- With no parse, behaviour is unchanged.
- This touches only `retrieval.py` (blast-radius core, so it needs the live spot-check).
- It does not re-chunk, re-index or change any prompt.

**Ship the month-name de-glue fix separately** as a chunker bug fix. It needs a re-index and the chunker
spot-check.

**Keep table split with a non-citable contextual header as the next step** if the harness shows dilution
misses remain. Frame it as revisiting the 2026-08-16 decision, not repeating it: the header is
chunk-specific, not a uniform per-filing prefix.

**Offline test, with no LLM calls.** Put it in `tests/manual/eval_retrieval_offline.py` or a scratch
script. It uses the local embedding and cross-encoder models only.
1. **Build the query set.** Take every `search_filings` row in `trace_logs/traces.jsonl`. Join each to its
   root `run_agent` question by `run_id`, then to its `eval/eval_questions.jsonl` id by exact question
   text. Deduplicate on (query, ticker).
2. **Label gold chunks.**
   - For numeric questions, a gold chunk is one from the filing whose `reportDate` matches the question's
     period and whose text contains `expected_value` in filing format (for example `35,013`).
   - For judged questions, use the figures in `criteria`.
   - Hand-check the gold set for about 10 questions.
3. **Record metrics for each variant**:
   - the gold rank in the BM25 pool and in the vector pool;
   - whether gold enters the fused pool (the reach-the-reranker rate);
   - hit@5 after `rerank`.
4. **Compare these variants**:
   - V0: current;
   - V1: RRF with the added period-filtered lists;
   - V2: V1 with a strict filter instead of added lists;
   - V3: de-glue, which needs a scratch BM25 and a scratch Chroma collection built from re-chunked text;
   - V4: table split plus a non-citable header, built the same way.
5. **Guard against regressions.** This is the check the 2026-08-16 simulation lacked. For every query
   whose gold chunk is in the V0 top 5, report whether it stays there. Also list any non-gold chunk that
   moves into a top-5 slot. A variant is a candidate only if hit@5 improves and no V0 hit is lost. After
   that, run the usual live `eval_harness.py --ids` spot-check on the MSFT segment questions and the
   earlier retrieval-miss ids.
