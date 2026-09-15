# Hybrid retrieval (BM25 + vector + rerank), and the MAX-of-RRF reranker fix

**Date:** 2026-08-13 build (commit `6197108`, "Week 3: hybrid retrieval");
reranker fix 2026-08-15 (commit `07cbf30`, "Fix reranker demoting correct
chunks; document new comparison-synthesis bug")

## Context

Week 2b's manual sanity queries surfaced a real miss: "What is
Salesforce's remaining performance obligation?" retrieved zero CRM
chunks in the top 3 on pure vector search, despite the filing stating
"remaining performance obligation" almost verbatim — embeddings can
smear an exact term-of-art match across many "semantically similar" but
wrong chunks.

## Decision

`retrieval.py`'s `hybrid_search()` combines BM25 (lexical, built
in-process from the same `./chunks/*.jsonl` files `index_chunks.py`
reads, so the two paths can't drift out of sync) with Chroma (vector)
via Reciprocal Rank Fusion (`1/(k+rank)`, `k=60`), then reranks the fused
pool (~25-40 chunks) with `cross-encoder/ms-marco-MiniLM-L-6-v2`. This is
the module all future code (eval harness, agent) should import
(`hybrid_search()`) instead of querying Chroma directly.

## Why

RRF fuses rank *position*, not raw scores, since BM25 scores and cosine
similarities live on incomparable scales — blending them directly would
let whichever method happens to produce larger numbers dominate. After
adding BM25 + fusion, all top-5 results for the RPO query are CRM chunks
about RPO, one containing the actual $72.4B figure.

**Reranker bug and fix**: the cross-encoder was demoting a
confirmed-correct MSFT headcount chunk (ranking #3 of 48 in fused
BM25+vector) out of the top 10 entirely. The initial hypothesis
(512-token truncation) was checked directly against the tokenizer and
ruled out — the sequence was only 489 tokens, with the relevant text
present. Real cause: `ms-marco-MiniLM-L-6-v2` is trained on short
(~350 char), single-topic passages and genuinely scores this long
(~2,700 char), multi-topic chunk poorly even with the relevant content
present (rank ~43/48 by raw cross-encoder score vs rank 3/48 fused).
First fix attempt (summing the rerank rank into the RRF formula as a
third signal) was implemented and tested — it did NOT work, since
several competing "decent-by-both" chunks beat the target's
"great-fused/terrible-rerank" combination on a summed score. **Fix that
worked**: `_combine_fused_and_rerank()` scores each candidate as the
**MAX** (not sum) of its two RRF contributions, so a candidate excellent
by even one signal survives.

## Files touched

`retrieval.py` (new module; later `_combine_fused_and_rerank()` fix).

## Verification

Standalone script confirming the target chunk moved to rank ~5 under MAX
scoring; live CLI re-run confirming rank 4 of 5 (previously absent from
top 10-48); regression checks against two previously-working queries
showing no change; new unit tests in `tests/test_retrieval.py`
(including a direct regression mirroring this exact failure pattern);
full eval suite flipping the target question FAIL to PASS with no other
regressions.

## Related

`docs/decisions/2026-08-19-table-chunk-rescue-in-reranking.md` (a later,
different reranker-demotion bug on a table chunk).
