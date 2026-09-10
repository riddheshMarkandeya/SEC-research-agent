"""
One-time (re-runnable) live verification of retrieval.py's model-calling
half: bm25_search/vector_search/hybrid_search/rerank all require a real
Chroma index, downloaded embedding/reranker models, and the actual
ingested ./chunks/ corpus -- exactly the kind of live dependency this
project's CLAUDE.md carve-out says gets a manual script instead of a
mocked unit test (mocking would only test the mock, not the code).
tests/test_retrieval.py already covers the pure ranking-math half
(_tokenize, _make_id, reciprocal_rank_fusion, _combine_fused_and_rerank)
in full; this script is what was missing for the rest (review §14,
docs/reviews/2026-09-06-full-codebase-review.md).

Runs a handful of real known queries through bm25_search, vector_search,
hybrid_search (both with and without reranking), and reports in a
checked/confirmed/problems style, same spirit as
verify_period_labels.py -- informational, not a hard assert-and-exit-1
gate, since "is this the single best chunk" is a judgment call a human
should eyeball via the printed preview, not something this script can
verify exactly. What IS mechanically checkable and treated as a real
problem: a search returning zero results, or a ticker-filtered search
returning a result from the WRONG company (either would mean retrieval
itself, not just ranking quality, is broken).

Usage (from the repo root):
    python tests/manual/verify_retrieval.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from retrieval import CHUNKS_DIR, bm25_search, hybrid_search, vector_search

# Real questions this project already asks in eval_questions.jsonl,
# reused here rather than invented fresh -- they're already known to be
# realistic phrasings, and covering a ticker-filtered query, an
# unfiltered (broad) query, and a couple of different companies/topics
# exercises the paths that matter: ticker filtering, the no-filter case,
# and enough topic variety that a totally broken embedding/BM25 index
# would show up as zero results somewhere.
QUERIES = [
    ("What is Salesforce's total remaining performance obligation?", "CRM"),
    ("What risks does Apple describe related to artificial intelligence?", "AAPL"),
    ("NVIDIA data center revenue", "NVDA"),
    ("risks related to dependence on government contracts", None),
]


def _setup_missing() -> str | None:
    """None if the live dependencies this script needs look present,
    else a human-readable message explaining what to run first -- same
    "fail with a clear setup message, not a raw traceback" spirit as
    retrieval.py's own _load_bm25_index() RuntimeError."""
    if not any(CHUNKS_DIR.glob("*/*_chunks.jsonl")):
        return f"No chunks found under {CHUNKS_DIR.resolve()} -- run chunk_documents.py first."
    from config import CHROMA_DIR

    if not Path(CHROMA_DIR).exists():
        return f"No Chroma index found at {CHROMA_DIR} -- run index_chunks.py first."
    return None


def _check_one(label: str, results: list, ticker: str | None) -> tuple[bool, str]:
    """(ok, message) for one search call's results -- ok is False only
    for the two mechanically-checkable problems described in the module
    docstring (empty results, or a ticker-filter violation); anything
    else is reported for a human to eyeball, not treated as a failure."""
    if not results:
        return False, f"{label}: 0 results -- PROBLEM"
    if ticker:
        wrong = {r["metadata"]["ticker"] for r in results if r["metadata"]["ticker"] != ticker}
        if wrong:
            return False, f"{label}: returned other ticker(s) {sorted(wrong)} despite ticker={ticker!r} -- PROBLEM"
    top = results[0]
    preview = top["text"].replace("\n", " ")[:150]
    return True, f"{label}: {len(results)} results, top={top['metadata']['ticker']} {top['metadata']['form']!r} -- {preview!r}"


def verify() -> tuple[int, int, list[str]]:
    checked = 0
    confirmed = 0
    problems = []

    for query, ticker in QUERIES:
        print(f"\nQ: {query!r} (ticker={ticker!r})")

        bm25_hits = [
            {"text": text, "metadata": metadata} for _, text, metadata in bm25_search(query, 5, ticker=ticker)
        ]
        vector_hits = [
            {"text": text, "metadata": metadata} for _, text, metadata in vector_search(query, 5, ticker=ticker)
        ]
        hybrid_hits = hybrid_search(query, ticker=ticker, top_k=5, use_rerank=True)
        fused_only_hits = hybrid_search(query, ticker=ticker, top_k=5, use_rerank=False)

        for label, results in [
            ("bm25_search", bm25_hits),
            ("vector_search", vector_hits),
            ("hybrid_search (reranked)", hybrid_hits),
            ("hybrid_search (fused only, no rerank)", fused_only_hits),
        ]:
            checked += 1
            ok, message = _check_one(label, results, ticker)
            print(f"  {message}")
            if ok:
                confirmed += 1
            else:
                problems.append(f"{query!r}: {message}")

    return checked, confirmed, problems


def main():
    setup_problem = _setup_missing()
    if setup_problem:
        print(f"Setup needed, skipping: {setup_problem}")
        return

    checked, confirmed, problems = verify()
    print(f"\n{'-' * 60}\nChecked {checked} searches across {len(QUERIES)} queries, {confirmed} returned non-empty, ticker-correct results.\n")
    if problems:
        print(f"PROBLEMS ({len(problems)}):")
        for p in problems:
            print(f"  {p}")
    else:
        print("No problems found. Eyeball the previews above for plausibility -- this script can't judge relevance, only that retrieval ran and returned the right company's data.")


if __name__ == "__main__":
    main()
