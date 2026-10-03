"""
Live verification of retrieval.py's period scoping, windowed (MaxP)
rerank and fused-floor rule, which need the real BM25 index, Chroma
collection and cross-encoder, so their wiring has no unit test.

Checks:
  1. a query naming NVIDIA's first quarter of fiscal 2026 is scoped to that
     10-Q's report date (2025-04-27), and every result comes from it;
  2. a query with no period falls back to the unscoped lists (no_date);
  3. MSFT's Q3 FY26 segment table chunk splits into several windows, and a
     window after the first opens with the table's carried header;
  4. search_details' results equal hybrid_search's, the call run_search makes;
  5. re-combining the exposed pool and window scores through
     _combine_fused_and_rerank reproduces those results;
  6. a scope whose dates the index doesn't hold falls back to the unscoped
     lists (filtered_empty) instead of returning nothing, and the search's
     retrieval_search trace event records it.

Exits 1 when a check fails.

Usage (from the repo root):
    python tests/manual/verify_period_scoped_rerank.py
"""

import json
import sys
from pathlib import Path

from sec_agent import config
from sec_agent.retrieval import retrieval
from sec_agent.retrieval.period_scope import Scope
from sec_agent.retrieval.rerank_windows import split_windows

NVDA_QUERY = "NVIDIA revenue for the first quarter of fiscal 2026"
NVDA_DATE = "2025-04-27"
NO_DATE_QUERY = "Microsoft cloud revenue growth drivers"
MSFT_TABLE = "0001193125-26-191507_35"
MSFT_QUERY = "Microsoft segment revenue three months ended March 31, 2026"
# A carried header sits at the very start of a window: caption, then <TABLE>.
_HEADER_START_CHARS = 200


def _ids(results: list[dict]) -> list[str]:
    return [retrieval._make_id(r["metadata"]) for r in results]


def _last_search_event() -> dict | None:
    path = Path(config.TRACE_LOG_PATH)
    if not path.is_file():
        return None
    for line in reversed(path.read_text(encoding="utf-8").splitlines()):
        record = json.loads(line)
        if record.get("category") == "retrieval_search":
            return record
    return None


def check_scoped_query() -> list[str]:
    details = retrieval.search_details(NVDA_QUERY, ticker="NVDA")
    print(f"1. scope {details['scope']}; result dates {[r['metadata']['reportDate'] for r in details['results']]}")
    problems = []
    if details["scope"]["report_dates"] != [NVDA_DATE]:
        problems.append(f"NVDA query scoped to {details['scope']}, expected [{NVDA_DATE}]")
    if any(r["metadata"]["reportDate"] != NVDA_DATE for r in details["results"]):
        problems.append("an NVDA result comes from outside the scoped filing")
    return problems


def check_unscoped_query() -> list[str]:
    details = retrieval.search_details(NO_DATE_QUERY, ticker="MSFT")
    print(f"2. scope {details['scope']}")
    return [] if details["scope"]["label"] == "no_date" else [f"no-date query scoped as {details['scope']}"]


def check_table_windows() -> list[str]:
    retrieval._load_bm25_index()
    assert retrieval._bm25_records is not None  # _load_bm25_index() always sets it
    text = next(r["text"] for r in retrieval._bm25_records if retrieval._make_id(r["metadata"]) == MSFT_TABLE)
    windows = split_windows(text, retrieval._token_counter(retrieval._get_rerank_model()))
    print(f"3. {MSFT_TABLE}: {len(text)} chars, {len(windows)} windows")
    if len(windows) < 2:
        return [f"{MSFT_TABLE} gave {len(windows)} window(s)"]
    if not any(0 <= w.find("<TABLE>") < _HEADER_START_CHARS for w in windows[1:]):
        return [f"no later window of {MSFT_TABLE} opens with the carried table header"]
    return []


def check_details_match_hybrid_search() -> list[str]:
    problems = []
    for query, ticker in ((NVDA_QUERY, "NVDA"), (MSFT_QUERY, "MSFT"), (NO_DATE_QUERY, "MSFT")):
        details = retrieval.search_details(query, ticker=ticker)
        if _ids(details["results"]) != _ids(retrieval.hybrid_search(query, ticker=ticker)):
            problems.append(f"search_details != hybrid_search for {query!r}")
        pool = retrieval.hybrid_search(query, ticker=ticker, top_k=10**6, use_rerank=False)
        candidates = [(retrieval._make_id(r["metadata"]), r["text"], r["metadata"], r["fused_score"]) for r in pool]
        if [c[0] for c in candidates] != details["pool"]:
            problems.append(f"scoped pool differs from search_details' pool for {query!r}")
        rebuilt = _ids(retrieval._combine_fused_and_rerank(candidates, details["scores"], 5)["results"])
        if rebuilt != _ids(details["results"]):
            problems.append(f"pool + scores don't rebuild the top 5 for {query!r}: {rebuilt}")
        print(f"4-5. {query[:50]!r} [{ticker}]: pool {len(details['pool'])}, windows {details['windows']}, "
              f"rescued {details['rescued']}")
    return problems


def check_filtered_empty_fallback() -> list[str]:
    original = retrieval._query_scope
    retrieval._query_scope = lambda query, ticker: Scope(("1999-12-31",), "dates", ())
    try:
        details = retrieval.search_details(NVDA_QUERY, ticker="NVDA")
    finally:
        retrieval._query_scope = original
    event = _last_search_event()
    print(f"6. scope {details['scope']}, {len(details['results'])} results; last event {event}")
    problems = []
    if details["scope"]["label"] != "filtered_empty" or not details["results"]:
        problems.append("a scope with no indexed dates didn't fall back to the unscoped lists")
    if event is None or event.get("scope", {}).get("label") != "filtered_empty":
        problems.append("the retrieval_search event doesn't record the filtered_empty fallback")
    return problems


def main() -> int:
    problems = [
        *check_scoped_query(),
        *check_unscoped_query(),
        *check_table_windows(),
        *check_details_match_hybrid_search(),
        *check_filtered_empty_fallback(),
    ]
    for p in problems:
        print(f"PROBLEM: {p}")
    print("OK" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
