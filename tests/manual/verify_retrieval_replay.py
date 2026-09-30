"""
Live verification of retrieval_replay.py's measurement binding
(_live_retriever), which needs the real BM25 index, Chroma collection and
models, so it has no unit test.

Checks, on 30 logged queries sampled with a fixed seed:
  1. the tool's final top 5 equals a direct hybrid_search(query, ticker),
     the call run_search makes;
  2. its exact vector ordering agrees with vector_search(query, 25, ticker)
     (Chroma's HNSW) on the top 25. HNSW is approximate and can miss a
     truly closer chunk, pulling in rank 26 instead; that's counted as a
     recall miss, not a failure. A failure is an HNSW result the exact
     ordering ranks past BOUNDARY, which would mean the two rank by
     different similarities;
  3. the final top 5 is drawn from the fused pool.
Then prints MSFT Q3 FY26 segment table chunk 35's ranks for the research
note's three MSFT queries, whose BM25 ranks there were 40, 45 and 29.

Exits 1 when a check fails.

Usage (from the repo root):
    python tests/manual/verify_retrieval_replay.py
"""

import random
import sys
from pathlib import Path

from sec_agent import config
from sec_agent.devtools import retrieval_replay as rr
from sec_agent.devtools import trace_query
from sec_agent.eval import eval_harness
from sec_agent.retrieval.retrieval import _make_id, hybrid_search, vector_search

SAMPLE = 30
BOUNDARY = 30
TARGET = "0001193125-26-191507_35"
MSFT_QIDS = ("msft-segment-revenue-comparison-q3fy2026", "msft-three-segments-revenue-q3fy2026")
KEYWORD_PREFIX = "Note Segment Information Three Months Ended March 31"


def _logged_queries(records: list[dict]) -> list[tuple[str, str | None]]:
    seen: dict[tuple, None] = {}
    for r in records:
        if r.get("as_type") == "tool" and r.get("name") == "search_filings":
            seen.setdefault((trace_query.get(r, "input.query") or "", trace_query.get(r, "input.ticker")), None)
    return list(seen)


def _msft_queries(logged: list[tuple[str, str | None]]) -> list[tuple[str, str | None]]:
    questions = {q["id"]: q["question"] for q in eval_harness.load_questions(config.QUESTIONS_PATH)}
    keyword = next(((q, t) for q, t in logged if q.startswith(KEYWORD_PREFIX)), None)
    return [(questions[qid], "MSFT") for qid in MSFT_QIDS] + ([keyword] if keyword else [])


def main() -> int:
    records, _ = trace_query.load(Path(config.TRACE_LOG_PATH))
    logged = _logged_queries(records)
    sample = random.Random(0).sample(logged, min(SAMPLE, len(logged)))
    corpus = rr._load_corpus()
    retrieve = rr._live_retriever(corpus)

    problems = []
    same_order = recall_misses = 0
    for query, ticker in sample:
        lists = retrieve(query, ticker)
        direct = [_make_id(r["metadata"]) for r in hybrid_search(query, ticker=ticker)]
        if lists["final"] != direct:
            problems.append(f"final != hybrid_search for {query[:60]!r} [{ticker}]: {lists['final']} vs {direct}")
        hnsw = [d for d, _, _ in vector_search(query, 25, ticker=ticker)]
        exact_rank = {d: i for i, (d, _, _) in enumerate(lists["vector"], start=1)}
        far = [d for d in hnsw if exact_rank.get(d, 10**9) > BOUNDARY]
        if far:
            problems.append(f"HNSW result ranked past {BOUNDARY} exactly for {query[:60]!r} [{ticker}]: {far}")
        recall_misses += any(exact_rank.get(d, 10**9) > 25 for d in hnsw)
        same_order += hnsw == [d for d, _, _ in lists["vector"][:25]]
        if not set(lists["final"]) <= set(lists["pool"]):
            problems.append(f"final not within pool for {query[:60]!r} [{ticker}]")
    print(f"checked {len(sample)} queries; exact vector top 25 in HNSW's order for {same_order}; "
          f"HNSW recall misses (a closer chunk skipped) for {recall_misses}")

    print(f"\n{TARGET} (MSFT Q3 FY26 segment table):")
    for query, ticker in _msft_queries(logged):
        record = rr.gold_chunk_record(TARGET, retrieve(query, ticker))
        bm25, vector = record["bm25"], record["vector"]
        print(f"  bm25 {bm25 and bm25['rank']}  vector {vector and vector['rank']}  pool {record['pool_pos']}  "
              f"final {record['final_rank']}  class {rr.classify(record)}  <- {query[:70]!r}")
        print(f"      bm25 detail {bm25}  vector detail {vector}")

    for p in problems:
        print(f"PROBLEM: {p}")
    print("OK" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
