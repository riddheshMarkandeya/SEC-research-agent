# Embedding + Chroma indexing, and the manual query CLI (Week 2b)

**Date:** 2026-08-13 (commit `c92eb3b`, initial commit)

> **Grouping note**: this file merges two originally separate, thin
> `PROJECT_CONTEXT.md` sections — `index_chunks.py` (24 lines) and
> `query_chunks.py` (9 lines) — since both are the same Week 2b
> embedding/indexing work, same commit, and neither justifies its own
> file at that length. Flagged explicitly per the migration plan's
> thin-section grouping guidance.

## Context

Chunks needed to be embedded and loaded into a searchable local vector
store, plus a way to sanity-check retrieval quality by eye before any
formal eval harness existed.

## Decision

**`index_chunks.py`**: embeds every chunk with `BAAI/bge-small-en-v1.5`
(not the more commonly-cited `all-MiniLM-L6-v2`) and loads them into a
persistent local Chroma collection, dropped and rebuilt on every run
(not incrementally upserted) so a chunking fix can't leave stale/
duplicate rows behind. Document id = `{accessionNumber}_{chunk_index}`.
Full metadata dict preserved per point.

**`query_chunks.py`**: runs a preset list of 15 financial questions
(numeric/table-seeking, qualitative/narrative, domain-vocab, one
deliberately vague) against the collection and prints top matches for
human eyeballing, not scoring. Also supports ad hoc queries via
`python query_chunks.py "custom question" --ticker MSFT --n 5`.

## Why

BGE is trained for **asymmetric** retrieval (short query → long
passage), matching the actual use case (a financial question against a
filing chunk) better than a general sentence-similarity model. The
tradeoff: queries need an instruction prefix
(`"Represent this sentence for searching relevant passages: "`) at
search time; passages are indexed *without* it — getting this backwards
measurably hurts retrieval for this model family. Embeddings are
L2-normalized with `hnsw:space: cosine`.

## Files touched

`index_chunks.py` (new), `query_chunks.py` (new).

## Verification

`grep -r "us-gaap:" ./chunks/` returns nothing; no exhibit-index table
leakage; only 4 chunks exceed the 3,000-char soft target (all large
`<TABLE>` blocks, by design); embedding + Chroma indexing runs
end-to-end (3,207/3,207 documents loaded). See
`docs/decisions/2026-08-13-corpus-ingestion-verification.md` for the
full manual retrieval sanity check this enabled.

## Related

`docs/decisions/2026-08-13-chunking-pipeline.md` (upstream),
`docs/decisions/2026-08-13-hybrid-retrieval-and-reranker-fix.md`
(the module that supersedes direct Chroma querying for all later code).
