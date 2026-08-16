"""
Week 3 — Hybrid retrieval: BM25 (lexical) + Chroma (vector) + reranking
--------------------------------------------------------------------------
This is the retrieval layer other code (Week 4's eval harness, Week 5's
agent) should import, rather than reimplementing search. It exists
because Week 2b's manual sanity queries surfaced a real gap: pure
semantic search missed a chunk that stated "remaining performance
obligation" almost verbatim, because that exact phrase carries more
signal as a literal keyword match than as a sentence embedding. BM25
catches exact/near-exact term matches that embeddings can smear across
many "semantically similar" but wrong-company chunks — the two methods
fail in different, complementary ways.

Pipeline per query:
  1. Pull a wide candidate pool (default 25) from BM25 and from Chroma's
     vector search, independently.
  2. Fuse the two rankings with Reciprocal Rank Fusion (RRF) — combines
     rankings, not raw scores, which sidesteps the fact that BM25 scores
     and cosine similarities live on completely different, incomparable
     scales.
  3. Rerank the fused candidate set with a cross-encoder, which scores
     each (query, passage) pair jointly rather than independently
     embedding them — slower, so only run over the ~25-40 fused
     candidates, not the full corpus, but meaningfully more accurate at
     the top of the ranking, which is what matters for citation-grounded
     answers downstream.

Usage as a library:
    from retrieval import hybrid_search
    results = hybrid_search("What is Salesforce's remaining performance obligation?", ticker="CRM")

Usage from the command line (manual spot-checking):
    python retrieval.py "your question" [--ticker MSFT] [--n 5] [--no-rerank]
"""

import argparse
import json
import re
from pathlib import Path

import chromadb
from rank_bm25 import BM25Okapi
from sentence_transformers import CrossEncoder, SentenceTransformer

CHUNKS_DIR = Path("./chunks")
CHROMA_DIR = "./chroma_db"
COLLECTION_NAME = "sec_filings"

EMBED_MODEL_NAME = "BAAI/bge-small-en-v1.5"
QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "

# A cross-encoder trained for passage reranking (MS MARCO). Small and
# CPU-friendly enough to run over ~25-40 candidates per query without
# noticeable latency, unlike running it over the full 3,207-chunk corpus.
RERANK_MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"

RRF_K = 60  # standard constant from the original Reciprocal Rank Fusion paper
CANDIDATE_POOL_SIZE = 25  # per-method pool size, before fusion/reranking


# ---------------------------------------------------------------------------
# Lazy singletons — models and indexes are expensive to load, so build
# them once per process and reuse across calls (important once this is
# imported by an eval harness or agent making many calls in one run).
# ---------------------------------------------------------------------------
_embed_model = None
_rerank_model = None
_chroma_collection = None
_bm25_index = None
_bm25_records = None  # parallel list of {"text", "metadata"} for _bm25_index


def _get_embed_model() -> SentenceTransformer:
    global _embed_model
    if _embed_model is None:
        _embed_model = SentenceTransformer(EMBED_MODEL_NAME)
    return _embed_model


def _get_rerank_model() -> CrossEncoder:
    global _rerank_model
    if _rerank_model is None:
        _rerank_model = CrossEncoder(RERANK_MODEL_NAME)
    return _rerank_model


def _get_chroma_collection():
    global _chroma_collection
    if _chroma_collection is None:
        client = chromadb.PersistentClient(path=CHROMA_DIR)
        _chroma_collection = client.get_collection(COLLECTION_NAME)
    return _chroma_collection


def _tokenize(text: str) -> list[str]:
    """Lowercase word tokenizer for BM25. Deliberately simple — no
    stemming — because financial terms of art ("remaining performance
    obligation", "full-time equivalent") are exact phrases where
    stemming would only risk merging distinct terms, not help."""
    return re.findall(r"[a-z0-9]+", text.lower())


def _load_bm25_index():
    """Build the BM25 index once from the same chunk files index_chunks.py
    reads, so both retrieval paths are always in sync with the current
    ./chunks/ output."""
    global _bm25_index, _bm25_records
    if _bm25_index is not None:
        return

    records = []
    for jsonl_path in sorted(CHUNKS_DIR.glob("*/*_chunks.jsonl")):
        with jsonl_path.open(encoding="utf-8") as f:
            for line in f:
                records.append(json.loads(line))

    if not records:
        raise RuntimeError(f"No chunks found under {CHUNKS_DIR.resolve()} — run chunk_documents.py first.")

    tokenized_corpus = [_tokenize(r["text"]) for r in records]
    _bm25_index = BM25Okapi(tokenized_corpus)
    _bm25_records = records


def _make_id(metadata: dict) -> str:
    """Must match index_chunks.py's id scheme so BM25 and Chroma results
    can be fused by a shared key."""
    return f"{metadata['accessionNumber']}_{metadata['chunk_index']}"


# ---------------------------------------------------------------------------
# Individual search methods — each returns an ordered list of
# (doc_id, text, metadata), best match first.
# ---------------------------------------------------------------------------
def bm25_search(query: str, n: int, ticker: str | None = None) -> list[tuple[str, str, dict]]:
    _load_bm25_index()
    scores = _bm25_index.get_scores(_tokenize(query))

    ranked_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    results = []
    for i in ranked_indices:
        record = _bm25_records[i]
        if ticker and record["metadata"]["ticker"] != ticker:
            continue
        if scores[i] <= 0:
            break  # BM25Okapi returns 0 for no term overlap at all — not a real match
        results.append((_make_id(record["metadata"]), record["text"], record["metadata"]))
        if len(results) >= n:
            break
    return results


def vector_search(query: str, n: int, ticker: str | None = None) -> list[tuple[str, str, dict]]:
    model = _get_embed_model()
    collection = _get_chroma_collection()
    query_embedding = model.encode(QUERY_INSTRUCTION + query, normalize_embeddings=True)

    where = {"ticker": ticker} if ticker else None
    hits = collection.query(query_embeddings=[query_embedding], n_results=n, where=where)

    results = []
    for doc, meta in zip(hits["documents"][0], hits["metadatas"][0]):
        results.append((_make_id(meta), doc, meta))
    return results


# ---------------------------------------------------------------------------
# Fusion
# ---------------------------------------------------------------------------
def reciprocal_rank_fusion(
    ranked_lists: list[list[tuple[str, str, dict]]], k: int = RRF_K
) -> list[tuple[str, str, dict, float]]:
    """
    Combine multiple ranked result lists into one, scoring each document
    by 1/(k + rank) summed across every list it appears in (rank is
    1-indexed). RRF fuses *rankings*, not raw scores — BM25 scores and
    cosine similarities aren't on comparable scales, so averaging them
    directly would let whichever method happens to produce larger
    numbers dominate. Rank position is scale-free.
    """
    fused_scores: dict[str, float] = {}
    doc_lookup: dict[str, tuple[str, dict]] = {}

    for ranked_list in ranked_lists:
        for rank, (doc_id, text, metadata) in enumerate(ranked_list, start=1):
            fused_scores[doc_id] = fused_scores.get(doc_id, 0.0) + 1.0 / (k + rank)
            doc_lookup.setdefault(doc_id, (text, metadata))

    ordered_ids = sorted(fused_scores, key=lambda d: fused_scores[d], reverse=True)
    return [(doc_id, *doc_lookup[doc_id], fused_scores[doc_id]) for doc_id in ordered_ids]


# ---------------------------------------------------------------------------
# Reranking
# ---------------------------------------------------------------------------
def _combine_fused_and_rerank(
    candidates: list[tuple[str, str, dict, float]], cross_encoder_scores: list[float], top_n: int
) -> list[dict]:
    """Pure ranking-math half of rerank() — separated out so it's unit-
    testable with fake scores, without needing the live cross-encoder.

    Combines the original fused (BM25+vector) ranking with the cross-
    encoder's ranking by taking, per candidate, the BETTER of the two
    RRF contributions — not letting the cross-encoder's ranking fully
    replace the fused one, and (importantly) not simply summing the two
    either.

    Found by evidence, not by assumption: `cross-encoder/ms-marco-MiniLM-
    L-6-v2` was trained on short, single-topic MS MARCO web passages
    (~350 chars average). Our chunks run up to ~3000 chars and are often
    multi-topic (e.g. one real MSFT chunk covers device competition,
    gaming, and search ads before finally reaching a "Human Capital
    Resources" paragraph with the actual employee count). Verified by
    inspecting the cross-encoder's own tokenized input directly (no
    truncation was happening — the relevant sentence was fully present)
    that the model itself, not a truncation bug, was scoring that chunk
    very low (rank 43 of 48) despite it being rank 3 of 48 in the fused
    BM25+vector ranking — two independent signals strongly agreed the
    chunk was relevant, and a single cross-encoder judgment overrode both.

    A first attempt summed the two rankings' RRF contributions (i.e. ran
    reciprocal_rank_fusion() again, one layer up). That still buried the
    chunk: several competing chunks were merely *decent* by both signals
    (e.g. fused rank ~20, rerank rank ~5), and a sum of two OK scores beat
    one great score (fused rank 5) plus one terrible one (rerank rank 44).
    Taking the MAX of the two RRF contributions instead means a candidate
    only needs to be excellent by ONE signal to survive — which is what
    actually rescued this chunk in testing (confirmed empirically before
    committing to this over the sum approach, not assumed to be better).
    """
    fused_rank = {doc_id: i for i, (doc_id, _, _, _) in enumerate(candidates, start=1)}
    rerank_rank = {
        doc_id: i
        for i, ((doc_id, _, _, _), _) in enumerate(
            sorted(zip(candidates, cross_encoder_scores), key=lambda pair: pair[1], reverse=True), start=1
        )
    }

    def combined_score(doc_id: str) -> float:
        return max(1.0 / (RRF_K + fused_rank[doc_id]), 1.0 / (RRF_K + rerank_rank[doc_id]))

    ranked = sorted(candidates, key=lambda c: combined_score(c[0]), reverse=True)

    return [
        {"text": text, "metadata": metadata, "combined_score": combined_score(doc_id)}
        for doc_id, text, metadata, _fused_score in ranked[:top_n]
    ]


def rerank(query: str, candidates: list[tuple[str, str, dict, float]], top_n: int) -> list[dict]:
    """Score each (query, passage) pair jointly with a cross-encoder, then
    combine with the fused ranking via _combine_fused_and_rerank() — see
    that function's docstring for why a straight override or sum of the
    two rankings both failed in testing."""
    if not candidates:
        return []

    model = _get_rerank_model()
    pairs = [(query, text) for _, text, _, _ in candidates]
    scores = model.predict(pairs)

    return _combine_fused_and_rerank(candidates, scores, top_n)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def hybrid_search(
    query: str,
    ticker: str | None = None,
    top_k: int = 5,
    use_rerank: bool = True,
    candidate_pool_size: int = CANDIDATE_POOL_SIZE,
) -> list[dict]:
    """Run BM25 + vector search, fuse with RRF, optionally rerank, and
    return the top_k results as {"text", "metadata", ...score...} dicts."""
    bm25_hits = bm25_search(query, candidate_pool_size, ticker=ticker)
    vector_hits = vector_search(query, candidate_pool_size, ticker=ticker)
    fused = reciprocal_rank_fusion([bm25_hits, vector_hits])

    if use_rerank:
        return rerank(query, fused, top_k)

    return [
        {"text": text, "metadata": metadata, "fused_score": score}
        for _, text, metadata, score in fused[:top_k]
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", help="question to search for")
    parser.add_argument("--ticker", default=None, help="restrict to one ticker, e.g. MSFT")
    parser.add_argument("--n", type=int, default=5, help="number of results to show")
    parser.add_argument("--no-rerank", action="store_true", help="skip the cross-encoder rerank step")
    args = parser.parse_args()

    results = hybrid_search(args.query, ticker=args.ticker, top_k=args.n, use_rerank=not args.no_rerank)

    print(f"\nQ: {args.query}")
    if args.ticker:
        print(f"   (filtered to ticker={args.ticker})")
    for i, r in enumerate(results, start=1):
        meta = r["metadata"]
        score = r.get("combined_score", r.get("fused_score"))
        table_flag = "[TABLE]" if meta.get("contains_table") else "[prose]"
        preview = r["text"].replace("\n", " ")[:250]
        print(
            f"  {i}. score={score:.4f} {table_flag} {meta['ticker']} {meta['form']} "
            f"(reportDate={meta['reportDate']}, chunk={meta['chunk_index']})\n"
            f"     {preview} ..."
        )


if __name__ == "__main__":
    main()
