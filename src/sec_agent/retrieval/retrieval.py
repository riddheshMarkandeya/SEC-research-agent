"""
Hybrid retrieval: BM25 (lexical) + Chroma (vector) + reranking. This is
the retrieval layer other code (the eval harness, the agent) should
import, rather than reimplementing search.

Pipeline per query:
  1. Scope by period: when the query names a period ("Q1 fiscal 2026",
     "the quarter ended April 27, 2025"), search only the matching
     filings' chunks (period_scope.py). Other periods' near-identical
     tables otherwise crowd the pool. With no period named, or nothing
     found inside the named filings, search everything.
  2. Pull a wide candidate pool (default 25) from BM25 and from Chroma's
     vector search, independently.
  3. Fuse the two rankings with Reciprocal Rank Fusion (RRF) — combines
     rankings, not raw scores, which sidesteps the fact that BM25 scores
     and cosine similarities live on completely different, incomparable
     scales.
  4. Rerank the fused candidate set with a cross-encoder, which scores
     each (query, passage) pair jointly rather than independently
     embedding them — slower, so only run over the ~25-40 fused
     candidates, not the full corpus, but meaningfully more accurate at
     the top of the ranking, which is what matters for citation-grounded
     answers downstream. Long chunks are scored by their best window
     (rerank_windows.py), since the model reads only 512 tokens.
  5. Order by the cross-encoder's rank, with a floor for the fused
     pool's top few (_combine_fused_and_rerank), then rescue a demoted
     financial table if none survived.

Usage as a library:
    from sec_agent.retrieval.retrieval import hybrid_search
    results = hybrid_search("What is Salesforce's remaining performance obligation?", ticker="CRM")

Usage from the command line (manual spot-checking):
    python -m sec_agent.retrieval.retrieval "your question" [--ticker MSFT] [--n 5] [--no-rerank]
"""

import argparse
import json
import re
from collections.abc import Callable, Mapping

import chromadb
from chromadb import Where
from rank_bm25 import BM25Okapi
from sentence_transformers import CrossEncoder, SentenceTransformer

from sec_agent.config import CHROMA_DIR, CHUNKS_DIR, EMBED_MODEL_NAME, RERANK_MODEL_NAME
from sec_agent.retrieval.period_scope import Scope, filing_list, query_report_dates
from sec_agent.retrieval.rerank_windows import max_per_owner, split_windows
from sec_agent.sources.companies import load_companies
from sec_agent.tracing import log_event

COLLECTION_NAME = "sec_filings"

QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "

# RERANK_MODEL_NAME (from config.py) is a cross-encoder trained for
# passage reranking (MS MARCO). Small and CPU-friendly enough to run
# over ~25-40 candidates per query without noticeable latency, unlike
# running it over the full 3,207-chunk corpus.

RRF_K = 60  # standard constant from the original Reciprocal Rank Fusion paper
CANDIDATE_POOL_SIZE = 25  # per-method pool size, before fusion/reranking

# Fused-pool ranks that keep the better of their fused and cross-encoder
# RRF terms; every other chunk is ranked by the cross-encoder alone. See
# _combine_fused_and_rerank. 0 would be the cross-encoder's order outright.
_FUSED_FLOOR_RANKS = 3

# See _is_rescuable_table: distinguishes a real financial data table
# (32-37 "$" occurrences in verified real chunks) from a
# glossary/definitions table (0) that's also flagged contains_table=True.
# Set well below the observed real minimum to leave margin for
# smaller-but-genuine tables.
_MIN_DOLLAR_FIGURES_FOR_TABLE_RESCUE = 5

SearchHits = list[tuple[str, str, dict]]  # (doc_id, text, metadata), best match first


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


def _get_embed_model() -> SentenceTransformer:  # pragma: no cover -- loads a real embedding model, live-only
    global _embed_model
    if _embed_model is None:
        _embed_model = SentenceTransformer(EMBED_MODEL_NAME)
    return _embed_model


def _get_rerank_model() -> CrossEncoder:  # pragma: no cover -- loads a real cross-encoder model, live-only
    global _rerank_model
    if _rerank_model is None:
        _rerank_model = CrossEncoder(RERANK_MODEL_NAME)
    return _rerank_model


def _token_counter(model: CrossEncoder) -> Callable[[str], int]:  # pragma: no cover -- real tokenizer, live-only
    """Counts tokens the way the cross-encoder will, without the special
    tokens it adds once per (query, window) pair."""
    tokenizer = model.tokenizer
    return lambda text: len(tokenizer(text, add_special_tokens=False)["input_ids"])


def _get_chroma_collection():  # pragma: no cover -- opens a real Chroma collection, live-only
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


def _load_bm25_index():  # pragma: no cover -- reads real chunk files from disk, live-only
    """Build the BM25 index once from the same chunk files index_chunks.py
    reads, so both retrieval paths are always in sync with the current
    var/chunks/ output."""
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

    # Tried tokenizing a period_labels.py period-label-prefixed version
    # of the text here (mirroring an index_chunks.py embedding change) --
    # reverted, net regression on the eval suite. See
    # docs/decisions/2026-08-16-fiscal-period-labels-tried-and-reverted.md.
    tokenized_corpus = [_tokenize(r["text"]) for r in records]
    _bm25_index = BM25Okapi(tokenized_corpus)
    _bm25_records = records


def _make_id(metadata: Mapping[str, object]) -> str:
    """Must match index_chunks.py's id scheme so BM25 and Chroma results
    can be fused by a shared key."""
    return f"{metadata['accessionNumber']}_{metadata['chunk_index']}"


# ---------------------------------------------------------------------------
# Individual search methods — each returns an ordered list of
# (doc_id, text, metadata), best match first. report_dates, when given,
# keeps only chunks from those filings.
# ---------------------------------------------------------------------------
def bm25_search(  # pragma: no cover -- queries the real BM25 index, live-only
    query: str, n: int, ticker: str | None = None, report_dates: tuple[str, ...] | None = None
) -> SearchHits:
    _load_bm25_index()
    assert _bm25_index is not None and _bm25_records is not None  # _load_bm25_index() always sets both
    scores = _bm25_index.get_scores(_tokenize(query))

    ranked_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    results = []
    for i in ranked_indices:
        record = _bm25_records[i]
        if ticker and record["metadata"]["ticker"] != ticker:
            continue
        if report_dates is not None and record["metadata"]["reportDate"] not in report_dates:
            continue
        if scores[i] <= 0:
            break  # BM25Okapi returns 0 for no term overlap at all — not a real match
        results.append((_make_id(record["metadata"]), record["text"], record["metadata"]))
        if len(results) >= n:
            break
    return results


def vector_search(  # pragma: no cover -- queries the real Chroma collection, live-only
    query: str, n: int, ticker: str | None = None, report_dates: tuple[str, ...] | None = None
) -> SearchHits:
    model = _get_embed_model()
    collection = _get_chroma_collection()
    query_embedding = model.encode(QUERY_INSTRUCTION + query, normalize_embeddings=True).tolist()

    clauses: list[Where] = []
    if report_dates is not None:
        clauses.append({"reportDate": {"$in": list(report_dates)}})
    if ticker:
        clauses.append({"ticker": {"$eq": ticker}})
    where: Where | None = None
    if len(clauses) == 1:
        where = clauses[0]
    elif clauses:
        where = {"$and": clauses}
    hits = collection.query(query_embeddings=[query_embedding], n_results=n, where=where)

    documents = hits["documents"]
    metadatas = hits["metadatas"]
    assert documents is not None and metadatas is not None  # always populated: no include= override
    results = []
    for doc, meta in zip(documents[0], metadatas[0]):
        results.append((_make_id(meta), doc, meta))
    return results


# ---------------------------------------------------------------------------
# Period scoping
# ---------------------------------------------------------------------------
def _query_scope(query: str, ticker: str | None) -> Scope:  # pragma: no cover -- reads the real chunk index, live-only
    _load_bm25_index()
    assert _bm25_records is not None  # _load_bm25_index() always sets it
    filings = filing_list((r["metadata"] for r in _bm25_records), ticker)
    months = {t: info["fiscal_year_end_month"] for t, info in load_companies().items()}
    unknown = sorted({t for t, _, _ in filings} - months.keys())
    if unknown:
        # their filings can't be scoped by fiscal period; the chunk files
        # hold a company the company list no longer does
        log_event("retrieval_scope_unknown_tickers", tickers=unknown)
    return query_report_dates(query, filings, months)


def _choose_lists(
    scope: Scope, search: Callable[[tuple[str, ...] | None], list[SearchHits]]
) -> tuple[list[SearchHits], str]:
    """The ranked lists to fuse, and a label for how they were chosen.
    search(report_dates) runs every retriever, limited to those filings, or
    unfiltered for None. A scoped query uses the filtered lists only; when
    all of them come back empty (the chunk files and the Chroma index out
    of step, say) it falls back to unfiltered rather than return nothing."""
    if not scope.report_dates:
        return search(None), scope.reason
    filtered = search(scope.report_dates)
    if any(filtered):
        return filtered, "dates"
    return search(None), "filtered_empty"


def _scoped_pool(  # pragma: no cover -- runs the live retrievers
    query: str, ticker: str | None, n: int
) -> tuple[list[tuple[str, str, dict, float]], dict]:
    """The fused candidate pool, and a JSON-ready record of its scoping."""
    scope = _query_scope(query, ticker)
    lists, label = _choose_lists(
        scope, lambda dates: [bm25_search(query, n, ticker, dates), vector_search(query, n, ticker, dates)]
    )
    record = {"label": label, "report_dates": list(scope.report_dates), "invalid_dates": list(scope.invalid_dates)}
    return reciprocal_rank_fusion(lists), record


# ---------------------------------------------------------------------------
# Fusion
# ---------------------------------------------------------------------------
def reciprocal_rank_fusion(
    ranked_lists: list[SearchHits], k: int = RRF_K
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
    candidates: list[tuple[str, str, dict, float]],
    cross_encoder_scores: list[float],
    top_n: int,
    fused_floor: int | None = None,
) -> dict:
    """Pure ranking-math half of reranking, testable with fake scores.

    A chunk scores the RRF term of its cross-encoder rank. A chunk in the
    fused pool's top `fused_floor` (default _FUSED_FLOOR_RANKS, read at
    call time) scores the better of that and its fused rank's term, plus a
    1e-9 share of the cross-encoder term: a tie between two such chunks
    goes to the cross-encoder, and one with a chunk outside the floor goes
    to the floor chunk.
    The floor keeps a chunk both base retrievers put at the top (such as a
    long, many-topic passage the cross-encoder scores poorly) without
    letting every fused rank compete. On 901 logged query parts, the
    better-of-two for every rank pushed out many chunks the cross-encoder
    ranked in its top 5, while no floor at all lost a few top fused
    chunks; a floor of 3 kept the question coverage of the first.

    Returns the top_n "results" (after the table rescue), the cross-
    encoder's order "ce" and the pre-rescue order "combined" as ids, the
    id the rescue swapped in ("rescued", or None) and the "fused_floor"
    that ran.
    """
    floor = _FUSED_FLOOR_RANKS if fused_floor is None else fused_floor
    fused_rank = {doc_id: i for i, (doc_id, _, _, _) in enumerate(candidates, start=1)}
    ce_order = [
        c[0] for c, _ in sorted(zip(candidates, cross_encoder_scores), key=lambda pair: pair[1], reverse=True)
    ]
    rerank_rank = {doc_id: i for i, doc_id in enumerate(ce_order, start=1)}

    def combined_score(doc_id: str) -> float:
        ce_term = 1.0 / (RRF_K + rerank_rank[doc_id])
        if fused_rank[doc_id] > floor:
            return ce_term
        return max(1.0 / (RRF_K + fused_rank[doc_id]), ce_term) + 1e-9 * ce_term

    ranked = sorted(candidates, key=lambda c: combined_score(c[0]), reverse=True)
    final, rescued = _rescue_demoted_table_chunk(candidates, fused_rank, ranked, top_n)

    return {
        "results": [
            {"text": text, "metadata": metadata, "combined_score": combined_score(doc_id)}
            for doc_id, text, metadata, _fused_score in final[:top_n]
        ],
        "ce": ce_order,
        "combined": [c[0] for c in ranked],
        "rescued": rescued,
        "fused_floor": floor,
    }


def _is_rescuable_table(text: str, metadata: Mapping) -> bool:
    """A financial data table, not a glossary/definitions table (term ->
    definition, no figures) that is flagged contains_table all the same."""
    return bool(metadata.get("contains_table")) and text.count("$") >= _MIN_DOLLAR_FIGURES_FOR_TABLE_RESCUE


def _rescue_demoted_table_chunk(
    candidates: list[tuple[str, str, dict, float]],
    fused_rank: dict[str, int],
    ranked: list[tuple[str, str, dict, float]],
    top_n: int,
) -> tuple[list[tuple[str, str, dict, float]], str | None]:
    """If the reranker's top_n contains no table chunk at all, but a
    rescuable table chunk already ranked in the top half of the fused
    BM25+vector pool (i.e. both base retrievers considered it relevant),
    swap it in for the weakest surviving slot. Returns the ranking and the
    swapped-in id, or None when nothing was swapped.

    Deliberately gated on the base retrievers' OWN pre-rerank confidence,
    not on guessing the question is fact/metric-seeking -- self-limiting
    by construction: a table with no lexical/semantic match to a prose
    question won't rank in the top half of the fused pool to begin with,
    so the rescue never fires for it. `contains_table` alone isn't enough:
    a glossary table is flagged too and can outrank a data table in the
    fused pool, so only _is_rescuable_table's figure count tells them
    apart."""
    if any(metadata.get("contains_table") for _, _, metadata, _ in ranked[:top_n]):
        return ranked, None  # a table chunk already survived on its own merits

    threshold = len(candidates) // 2
    top_n_ids = {doc_id for doc_id, _, _, _ in ranked[:top_n]}
    table_candidates = [
        c
        for c in candidates
        if _is_rescuable_table(c[1], c[2]) and fused_rank[c[0]] <= threshold and c[0] not in top_n_ids
    ]
    if not table_candidates:
        return ranked, None

    best_table = min(table_candidates, key=lambda c: fused_rank[c[0]])
    return ranked[: top_n - 1] + [best_table], best_table[0]


def _window_scores(query: str, texts: list[str]) -> tuple[list[float], int]:  # pragma: no cover -- real cross-encoder
    """Each text's best cross-encoder score over its windows, and the
    number of windows scored, from one predict call over every window."""
    model = _get_rerank_model()
    count_tokens = _token_counter(model)
    pairs, owner = [], []
    for i, text in enumerate(texts):
        for window in split_windows(text, count_tokens):
            pairs.append((query, window))
            owner.append(i)
    scores = model.predict(pairs).tolist() if pairs else []
    return max_per_owner(owner, scores, len(texts)), len(pairs)


def _search_record(
    fused: list[tuple[str, str, dict, float]],
    scores: list[float],
    scope_record: dict,
    top_k: int,
    fused_floor: int | None = None,
) -> dict:
    """search_details' return value without "windows", from the fused
    pool, its window scores and its scoping (see search_details)."""
    return {
        **_combine_fused_and_rerank(fused, scores, top_k, fused_floor),
        "pool": [doc_id for doc_id, _, _, _ in fused],
        "scores": scores,
        "tables": {doc_id for doc_id, _, metadata, _ in fused if metadata.get("contains_table")},
        "rescuable": {doc_id for doc_id, text, metadata, _ in fused if _is_rescuable_table(text, metadata)},
        "scope": scope_record,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def search_details(  # pragma: no cover -- orchestrates the live-only functions above
    query: str,
    ticker: str | None = None,
    top_k: int = 5,
    candidate_pool_size: int = CANDIDATE_POOL_SIZE,
    fused_floor: int | None = None,
) -> dict:
    """One reranked search with everything that decided it, so a
    measurement tool reads retrieval's own ranks instead of restating its
    rules: the top_k "results" (what hybrid_search returns), the fused
    "pool" ids with their window "scores" in pool order, the "ce",
    "combined", "rescued" and "fused_floor" fields of
    _combine_fused_and_rerank, the pool's "tables" and "rescuable" ids,
    the period "scope" and the number of "windows" scored. fused_floor
    None uses _FUSED_FLOOR_RANKS; a measurement tool passes another to
    compare rules on one search. Logs one retrieval_search event."""
    fused, scope_record = _scoped_pool(query, ticker, candidate_pool_size)
    scores, windows = _window_scores(query, [text for _, text, _, _ in fused]) if fused else ([], 0)
    record = {**_search_record(fused, scores, scope_record, top_k, fused_floor), "windows": windows}
    log_event(
        "retrieval_search",
        ticker=ticker,
        scope=scope_record,
        pool_size=len(fused),
        windows=windows,
        fused_floor=record["fused_floor"],
        rescued=record["rescued"] is not None,
    )
    return record


def hybrid_search(  # pragma: no cover -- orchestrates the live-only functions above
    query: str,
    ticker: str | None = None,
    top_k: int = 5,
    use_rerank: bool = True,
    candidate_pool_size: int = CANDIDATE_POOL_SIZE,
) -> list[dict]:
    """Run the period-scoped BM25 + vector search, fuse with RRF,
    optionally rerank, and return the top_k results as
    {"text", "metadata", ...score...} dicts."""
    if use_rerank:
        return search_details(query, ticker, top_k, candidate_pool_size)["results"]

    fused, _ = _scoped_pool(query, ticker, candidate_pool_size)
    return [
        {"text": text, "metadata": metadata, "fused_score": score}
        for _, text, metadata, score in fused[:top_k]
    ]


def main():  # pragma: no cover -- CLI entry point, live-only
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
