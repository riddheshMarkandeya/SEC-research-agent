"""
Live verification that a ticker'd BM25 search ranks with statistics from
that ticker's own chunks only, so adding other companies to var/chunks/
can't reorder it. Needs the real chunk files, so it has no unit test.

Checks:
  1. bm25_search(q, ticker="MSFT") equals an oracle built here straight
     from rank_bm25 over MSFT's chunks alone (red while the index spans
     every company);
  2. bm25_search(q, ticker="MSFT") equals _rank_bm25 over the MSFT entry
     of retrieval._bm25_by_ticker, the index it is meant to use.

Also prints, for information: the MSFT Q3 FY26 segment table's BM25 rank
for msft-three-segments-revenue-q3fy2026's queries, unscoped and scoped
to its 10-Q, and the index load time. On the whole-corpus index the
unscoped ranks were 119, 46 and 42 (124, 38 and 36 before the phase 2
companies were added).

Exits 1 when a check fails.

Usage (from the repo root):
    python tests/manual/verify_bm25_ticker_stats.py
"""

import sys
import time

from rank_bm25 import BM25Okapi

from sec_agent.retrieval import retrieval

TICKER = "MSFT"
SEGMENT_TABLE = "0001193125-26-191507_47"
REPORT_DATE = "2026-03-31"
QUERIES = [
    "What was Microsoft's revenue for each of its three reportable segments — Productivity and Business "
    "Processes, Intelligent Cloud, and More Personal Computing — for the three months ended March 31, 2026?",
    '"Productivity and Business Processes" revenue "Intelligent Cloud" "More Personal Computing" '
    "three months ended March 31, 2026",
    "Note 16 Segment Information Three Months Ended March 31, 2026 Productivity and Business Processes "
    "Intelligent Cloud More Personal Computing revenue",
]
DEPTH = 200


def _ids(hits: retrieval.SearchHits) -> list[str]:
    return [doc_id for doc_id, _, _ in hits]


def _rank_of(doc_id: str, hits: retrieval.SearchHits) -> int | None:
    ids = _ids(hits)
    return ids.index(doc_id) + 1 if doc_id in ids else None


def main() -> int:
    started = time.perf_counter()
    retrieval._load_bm25_index()
    print(f"index load: {time.perf_counter() - started:.1f} s")
    assert retrieval._bm25_records is not None

    own = [r for r in retrieval._bm25_records if r["metadata"]["ticker"] == TICKER]
    oracle = BM25Okapi([retrieval._tokenize(r["text"]) for r in own])
    per_ticker = getattr(retrieval, "_bm25_by_ticker", {}).get(TICKER)

    failed = False
    for query in QUERIES:
        live = retrieval.bm25_search(query, DEPTH, ticker=TICKER)
        expected = _oracle_ranking(oracle, own, query)
        scoped = retrieval.bm25_search(query, DEPTH, ticker=TICKER, report_dates=(REPORT_DATE,))
        print(f"\n{query[:90]}")
        print(f"  segment table rank: unscoped {_rank_of(SEGMENT_TABLE, live)}, "
              f"scoped {_rank_of(SEGMENT_TABLE, scoped)}")

        ok = _ids(live) == _ids(expected)
        print(f"  [{'PASS' if ok else 'FAIL'}] matches an MSFT-only oracle")
        failed |= not ok

        ok = per_ticker is not None and _ids(live) == _ids(retrieval._rank_bm25(*per_ticker, query, DEPTH, None))
        print(f"  [{'PASS' if ok else 'FAIL'}] matches _rank_bm25 over _bm25_by_ticker[{TICKER!r}]")
        failed |= not ok

    print("\nRED" if failed else "\nGREEN")
    return 1 if failed else 0


def _oracle_ranking(oracle: BM25Okapi, own: list[dict], query: str) -> retrieval.SearchHits:
    """Ranked independently of retrieval._rank_bm25, so check 1 doesn't
    compare that function with itself."""
    scores = oracle.get_scores(retrieval._tokenize(query))
    order = sorted(range(len(own)), key=lambda i: scores[i], reverse=True)
    hits = [(retrieval._make_id(own[i]["metadata"]), own[i]["text"], own[i]["metadata"])
            for i in order if scores[i] > 0]
    return hits[:DEPTH]


if __name__ == "__main__":
    sys.exit(main())
