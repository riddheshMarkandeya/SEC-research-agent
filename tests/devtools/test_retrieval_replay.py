import json

import pytest

from sec_agent.devtools import retrieval_replay as rr


def _search(run_id, query, ticker: str | None = "MSFT", **overrides):
    return {
        "timestamp": "2026-09-20T00:00:00",
        "run_id": run_id,
        "as_type": "tool",
        "name": "search_filings",
        "input": {"query": query, "ticker": ticker},
        "output": {"result_count": 5},
        **overrides,
    }


def _gold(qid="q1", part="value", accession="A1", anchor="Revenue 35,013", own_period=True, **extra):
    return {"qid": qid, "part": part, "accession": accession, "report_date": "2026-03-31",
            "anchor": anchor, "own_period": own_period, "note": "", **extra}


def _chunk(accession, index, text, ticker="MSFT", report_date="2026-03-31"):
    return {"text": text, "metadata": {"accessionNumber": accession, "chunk_index": index, "ticker": ticker,
                                       "reportDate": report_date}}


# ---------------------------------------------------------------------------
# build_query_set
# ---------------------------------------------------------------------------
def test_build_query_set_dedupes_on_query_and_ticker_and_keeps_every_qid():
    records = [
        _search("r1", "msft revenue"),
        _search("r2", "msft revenue"),
        _search("r3", "msft revenue"),
        _search("r1", "msft revenue", ticker=None),
    ]
    ids = {"r1": "q1", "r2": "q2", "r3": "q1"}
    queries, dropped = rr.build_query_set(records, ids, {"q1", "q2"})
    assert queries == [
        {"query": "msft revenue", "ticker": "MSFT", "qids": ["q1", "q2"]},
        {"query": "msft revenue", "ticker": None, "qids": ["q1"]},
    ]
    assert dropped == {"unjoined": 0, "no_gold": 0}


def test_build_query_set_counts_unjoined_and_no_gold_spans_and_ignores_other_records():
    records = [
        _search("r1", "a"),
        _search("r9", "b"),  # run with no run_agent span
        _search("r2", "c"),  # question not in the suite
        _search("r3", "d"),  # question without gold
        {"run_id": "r1", "as_type": "tool", "name": "get_financial_fact", "input": {"metric": "x"}},
        {"run_id": "r1", "category": "llm_retry"},
    ]
    ids = {"r1": "q1", "r2": "?", "r3": "q3"}
    queries, dropped = rr.build_query_set(records, ids, {"q1"})
    assert [q["query"] for q in queries] == ["a"]
    assert dropped == {"unjoined": 2, "no_gold": 1}


# ---------------------------------------------------------------------------
# gold loading and matching
# ---------------------------------------------------------------------------
def test_load_gold_reads_rows_and_rejects_a_row_missing_a_field(tmp_path):
    path = tmp_path / "gold.jsonl"
    path.write_text(json.dumps(_gold()) + "\n\n", encoding="utf-8")
    assert rr.load_gold(path) == [_gold()]
    bad = _gold()
    del bad["anchor"]
    path.write_text(json.dumps(bad) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="line 1.*anchor"):
        rr.load_gold(path)


def test_gold_matches_normalizes_whitespace_and_requires_the_accession():
    rows = [_gold(anchor="Productivity and Business Processes  $ 35,013")]
    text = "| Productivity and\nBusiness Processes | $\t35,013 |"
    assert rr.gold_matches("Productivity and Business Processes $ 35,013 more", {"accessionNumber": "A1"}, rows) == rows
    assert rr.gold_matches(text.replace("|", "").replace("  ", " "), {"accessionNumber": "A1"}, rows) == rows
    assert rr.gold_matches("Productivity and Business Processes $ 35,013", {"accessionNumber": "A2"}, rows) == []


def test_index_gold_lists_every_matching_chunk_with_its_period_tag_and_reports_unmatched_rows():
    rows = [
        _gold(anchor="Revenue 35,013"),
        _gold(accession="B1", anchor="Revenue 35,013", own_period=False),
        _gold(part="other", anchor="never appears"),
    ]
    chunks = [
        _chunk("A1", 35, "segment note Revenue 35,013"),
        _chunk("A1", 47, "MD&A table Revenue   35,013"),
        _chunk("A1", 48, "unrelated"),
        _chunk("B1", 12, "prior period Revenue 35,013", report_date="2025-03-31"),
    ]
    index, unmatched = rr.index_gold(chunks, rows)
    assert index == {
        ("q1", "value"): [
            {"chunk": "A1_35", "ticker": "MSFT", "own_period": True, "report_date": "2026-03-31"},
            {"chunk": "A1_47", "ticker": "MSFT", "own_period": True, "report_date": "2026-03-31"},
            {"chunk": "B1_12", "ticker": "MSFT", "own_period": False, "report_date": "2025-03-31"},
        ]
    }
    assert unmatched == [rows[2]]


# ---------------------------------------------------------------------------
# per-chunk ranks, best gold, miss classes
# ---------------------------------------------------------------------------
def _order(*entries):
    """(doc_id, accession, ticker) triples, best first."""
    return [tuple(e.split(":")) for e in entries]


def test_rank_stats_counts_own_filing_rank_and_same_ticker_other_filings_ahead():
    order = _order("B1_1:B1:MSFT", "X1_1:X1:AAPL", "A1_2:A1:MSFT", "B1_2:B1:MSFT", "A1_35:A1:MSFT")
    assert rr.rank_stats(order, "A1_35") == {"rank": 5, "own_filing_rank": 2, "other_filing_ahead": 2,
                                             "other_ticker_ahead": 1}
    assert rr.rank_stats(order, "A1_99") is None


def test_gold_chunk_record_takes_pool_position_and_final_rank_from_the_real_path():
    lists = {
        "bm25": _order("A1_35:A1:MSFT"),
        "vector": _order("A1_1:A1:MSFT", "A1_35:A1:MSFT"),
        "pool": ["A1_1", "A1_35"],
        "final": ["A1_35"],
        "ce": ["A1_35", "A1_1"],
        "scope_dates": None,
    }
    record = rr.gold_chunk_record("A1_35", lists)
    assert record == {
        "chunk": "A1_35",
        "bm25": {"rank": 1, "own_filing_rank": 1, "other_filing_ahead": 0, "other_ticker_ahead": 0},
        "vector": {"rank": 2, "own_filing_rank": 2, "other_filing_ahead": 0, "other_ticker_ahead": 0},
        "pool_pos": 2,
        "final_rank": 1,
        "ce_rank": 1,
        "scope_excluded": False,
    }
    missing = rr.gold_chunk_record("A1_9", lists)
    assert (missing["bm25"], missing["vector"], missing["pool_pos"], missing["final_rank"], missing["ce_rank"]) == (
        None, None, None, None, None)


@pytest.mark.parametrize(
    "scope_dates, report_date, expected",
    [
        (["2026-03-31"], "2025-03-31", True),  # the period scope left its filing out of the search
        (["2026-03-31"], "2026-03-31", False),
        (None, "2025-03-31", False),  # an unscoped search excludes no filing
        (["2026-03-31"], None, False),  # its filing's date unknown: not judged excluded
    ],
)
def test_gold_chunk_record_marks_a_chunk_outside_the_period_scope(scope_dates, report_date, expected):
    lists = {"bm25": [], "vector": [], "pool": [], "final": [], "ce": [], "scope_dates": scope_dates}
    assert rr.gold_chunk_record("A1_35", lists, report_date)["scope_excluded"] is expected


def _rec(chunk="c", final=None, pool=None, scope_excluded=False, **ranks):
    """`ranks` sets bm25 and vector as (rank, own_filing_rank, other_filing_ahead), and ce.
    Every other chunk ahead is another ticker's."""
    def stats(v):
        return None if v is None else {"rank": v[0], "own_filing_rank": v[1], "other_filing_ahead": v[2],
                                       "other_ticker_ahead": v[0] - v[1] - v[2]}
    return {"chunk": chunk, "bm25": stats(ranks.get("bm25")), "vector": stats(ranks.get("vector")),
            "pool_pos": pool, "final_rank": final, "ce_rank": ranks.get("ce"), "scope_excluded": scope_excluded}


def test_best_gold_prefers_final_rank_then_pool_position_then_diagnostic_rank():
    a = _rec("a", final=3, pool=9)
    b = _rec("b", final=2, pool=20)
    assert rr.best_gold([a, b])["chunk"] == "b"
    c = _rec("c", pool=4)
    d = _rec("d", pool=7, bm25=(1, 1, 0))
    assert rr.best_gold([d, c])["chunk"] == "c"
    e = _rec("e", bm25=(90, 30, 5))
    f = _rec("f", vector=(40, 12, 3))
    g = _rec("g")
    assert rr.best_gold([g, e, f])["chunk"] == "f"


def test_best_gold_prefers_a_chunk_the_period_scope_searched_when_neither_reached_the_pool():
    excluded = _rec("x", vector=(2, 1, 0), scope_excluded=True)
    searched = _rec("s", vector=(80, 30, 5))
    assert rr.best_gold([excluded, searched])["chunk"] == "s"
    # pool position still comes first: an unscoped fallback pooled the excluded chunk
    pooled = _rec("p", pool=8, scope_excluded=True)
    assert rr.best_gold([searched, pooled])["chunk"] == "p"


@pytest.mark.parametrize(
    "record, expected",
    [
        (_rec(final=4, pool=10), "hit"),
        (_rec(pool=12), "rerank"),
        (_rec(bm25=(40, 3, 30), vector=(200, 90, 10)), "period_confusion"),
        (_rec(bm25=(103, 40, 5), vector=(60, 11, 2)), "dilution"),
        (_rec(), "unranked"),
        # unfiltered query: only other tickers' chunks outrank it
        (_rec(vector=(30, 2, 0)), "other_ticker"),
        # the better retriever decides: vector's rank 30 beats bm25's 50
        (_rec(bm25=(50, 2, 20), vector=(30, 14, 1)), "dilution"),
        # inside the vector top 25 by exact rank, yet the approximate index left it out
        (_rec(vector=(12, 4, 8)), "index_recall"),
        # the period scope left its filing out, whatever its unscoped ranks say
        (_rec(vector=(12, 4, 8), scope_excluded=True), "scope_excluded"),
        # in the pool all the same (an unscoped fallback): judged at rerank
        (_rec(pool=8, scope_excluded=True), "rerank"),
        # unfiltered query: one same-ticker chunk from another filing ahead, 56 other tickers' chunks
        (_rec(vector=(60, 3, 1)), "other_ticker"),
    ],
)
def test_classify(record, expected):
    assert rr.classify(record) == expected


def _pool_lists(n=10, final=("p1", "p2", "p3", "p4", "p5"), tables=(), rescuable=(), combined=None):
    """`combined` is retrieval's order before the table rescue; by default
    the rescue didn't fire, so its top 5 is `final`."""
    pool = [f"p{i}" for i in range(1, n + 1)]
    if combined is None:
        combined = list(final) + [p for p in pool if p not in final]
    return {"pool": pool, "final": list(final), "tables": set(tables), "rescuable": set(rescuable),
            "combined": list(combined), "scope_dates": None}


@pytest.mark.parametrize(
    "record, lists, expected",
    [
        # the cross-encoder put it in its top 5; the fused floor let other chunks outrank it
        (_rec("p8", pool=8, ce=3), _pool_lists(), "fusion"),
        # it made the top 5 before the table rescue, which swapped it out for a table
        (_rec("p5", pool=5, ce=3),
         _pool_lists(final=("p1", "p2", "p3", "p4", "p9"), tables={"p9"}, rescuable={"p9"},
                     combined=["p1", "p2", "p3", "p4", "p5", "p6", "p7", "p8", "p9", "p10"]),
         "rescue"),
        # a qualifying table the cross-encoder ranks low, with no table in the top 5, blocked
        # from the rescue only by its fused rank past half the pool
        (_rec("p8", pool=8, ce=9), _pool_lists(tables={"p8"}, rescuable={"p8"}), "rescue_threshold"),
        # the same, but a table already made the top 5, so the rescue never runs
        (_rec("p8", pool=8, ce=9), _pool_lists(tables={"p8", "p2"}, rescuable={"p8"}), "model"),
        # within the threshold: the rescue could have picked it, so the threshold didn't block it
        (_rec("p4", pool=4, ce=9), _pool_lists(final=("p1", "p2", "p3", "p5", "p6"), tables={"p4"},
                                               rescuable={"p4"}), "model"),
        # not a qualifying table
        (_rec("p8", pool=8, ce=9), _pool_lists(tables={"p8"}), "model"),
    ],
)
def test_rerank_cause(record, lists, expected):
    assert rr.rerank_cause(record, lists) == expected


def test_evaluate_query_takes_the_rerank_cause_from_the_gold_chunk_the_cross_encoder_ranked_best():
    gold_index = {("q1", "value"): [{"chunk": "p3", "ticker": "MSFT", "own_period": True, "report_date": None},
                                    {"chunk": "p12", "ticker": "MSFT", "own_period": True, "report_date": None}]}
    pool = [f"p{i}" for i in range(1, 21)]
    lists = {"bm25": [], "vector": [], "pool": pool, "final": ["p1", "p2", "p4", "p5", "p6"],
             "ce": ["p7", "p12", *[p for p in pool if p not in ("p7", "p12", "p3")], "p3"],
             "tables": set(), "rescuable": set(), "combined": ["p1", "p2", "p4", "p5", "p6"], "scope_dates": None}
    result = rr.evaluate_query({"query": "q", "ticker": "MSFT", "qids": ["q1"]}, lists, gold_index)
    part = result["parts"][0]
    assert (part["class"], part["best"]["chunk"], part["rerank_cause"]) == ("rerank", "p3", "fusion")


def test_a_part_whose_gold_chunk_the_table_rescue_swapped_out_is_lost_to_the_rescue():
    # p12 is the cross-encoder's best gold chunk, but p3 sat in the top 5 before the rescue
    gold_index = {("q1", "value"): [{"chunk": "p3", "ticker": "MSFT", "own_period": True, "report_date": None},
                                    {"chunk": "p12", "ticker": "MSFT", "own_period": True, "report_date": None}]}
    pool = [f"p{i}" for i in range(1, 21)]
    lists = {"bm25": [], "vector": [], "pool": pool, "final": ["p1", "p2", "p4", "p5", "p9"],
             "ce": ["p12", *[p for p in pool if p not in ("p12", "p3")], "p3"],
             "tables": {"p9"}, "rescuable": {"p9"}, "combined": ["p1", "p2", "p4", "p5", "p3", "p9"],
             "scope_dates": None}
    part = rr.evaluate_query({"query": "q", "ticker": "MSFT", "qids": ["q1"]}, lists, gold_index)["parts"][0]
    assert part["rerank_cause"] == "rescue"


def test_evaluate_query_scores_each_part_of_each_qid_on_its_best_gold_chunk():
    gold_index = {
        ("q1", "PBP"): [{"chunk": "A1_35", "ticker": "MSFT", "own_period": True, "report_date": None},
                        {"chunk": "A1_47", "ticker": "MSFT", "own_period": True, "report_date": None}],
        ("q1", "IC"): [{"chunk": "B1_3", "ticker": "MSFT", "own_period": False, "report_date": None}],
        ("q2", "value"): [{"chunk": "A1_1", "ticker": "MSFT", "own_period": True, "report_date": None}],
    }
    lists = {
        "bm25": _order("A1_47:A1:MSFT", "A1_35:A1:MSFT"),
        "vector": _order("A1_35:A1:MSFT"),
        "pool": ["A1_47", "A1_35"],
        "final": ["A1_35"],
        "ce": ["A1_35", "A1_47"],
        "tables": set(),
        "rescuable": set(),
        "scope_dates": None,
    }
    result = rr.evaluate_query({"query": "q", "ticker": "MSFT", "qids": ["q1"]}, lists, gold_index)
    assert [(p["qid"], p["part"], p["hit"], p["class"], p["own_period"]) for p in result["parts"]] == [
        ("q1", "IC", False, "unranked", False),
        ("q1", "PBP", True, "hit", True),
    ]
    assert [p["rerank_cause"] for p in result["parts"]] == [None, None]
    pbp = result["parts"][1]
    assert pbp["best"]["chunk"] == "A1_35"
    assert [c["chunk"] for c in pbp["chunks"]] == ["A1_35", "A1_47"]
    assert result["final"] == ["A1_35"]


def test_evaluate_query_skips_parts_whose_gold_the_ticker_filter_excludes():
    gold_index = {
        ("q1", "AAPL"): [{"chunk": "X1_1", "ticker": "AAPL", "own_period": True, "report_date": None}],
        ("q1", "MSFT"): [{"chunk": "A1_1", "ticker": "MSFT", "own_period": True, "report_date": None}],
    }
    lists = {"bm25": _order("A1_1:A1:MSFT"), "vector": _order("A1_1:A1:MSFT"), "pool": ["A1_1"], "final": ["A1_1"],
             "ce": ["A1_1"], "tables": set(), "rescuable": set(), "scope_dates": None}
    filtered = rr.evaluate_query({"query": "q", "ticker": "MSFT", "qids": ["q1"]}, lists, gold_index)
    assert [p["part"] for p in filtered["parts"]] == ["MSFT"]
    assert filtered["out_of_scope"] == [["q1", "AAPL"]]
    unfiltered = rr.evaluate_query({"query": "q", "ticker": None, "qids": ["q1"]}, lists, gold_index)
    assert [p["part"] for p in unfiltered["parts"]] == ["AAPL", "MSFT"]
    assert unfiltered["out_of_scope"] == []


# ---------------------------------------------------------------------------
# summarize and coverage
# ---------------------------------------------------------------------------
def _part(qid, part, cls, own_period=True, **best):
    """`best` sets the best gold's pool position (pool) and the rerank cause (cause)."""
    hit = cls == "hit"
    return {"qid": qid, "part": part, "hit": hit, "class": cls, "own_period": own_period,
            "rerank_cause": best.get("cause"),
            "best": _rec(final=1 if hit else None, pool=best.get("pool", 1 if hit else None))}


def _result(query, *parts, ticker="MSFT"):
    return {"query": query, "ticker": ticker, "qids": sorted({p["qid"] for p in parts}), "parts": list(parts)}


def test_summarize_counts_hits_reach_classes_and_question_coverage():
    results = [
        _result("a", _part("q1", "PBP", "hit"), _part("q1", "IC", "dilution", own_period=False)),
        _result("b", _part("q1", "PBP", "rerank", pool=12, cause="model"), _part("q1", "IC", "hit", own_period=False)),
        _result("c", _part("q2", "value", "rerank", pool=3, cause="fusion")),
    ]
    s = rr.summarize(results)
    assert (s["parts"], s["hits"], s["reached"]) == (5, 2, 4)
    assert s["hit_at_5"] == pytest.approx(0.4)
    assert s["reach"] == pytest.approx(0.8)
    assert s["classes"] == {"hit": 2, "rerank": 2, "dilution": 1}
    assert s["by_period"] == {"own": {"hit": 1, "rerank": 2}, "other": {"hit": 1, "dilution": 1}}
    assert s["coverage"] == {"q1": True, "q2": False}
    assert s["rerank_causes"] == {"model": 1, "fusion": 1}
    assert (s["covered"], s["questions"]) == (1, 2)


def test_coverage_counts_a_part_only_ever_out_of_scope_as_not_hit():
    only_msft = {**_result("a", _part("q1", "MSFT", "hit")), "out_of_scope": [["q1", "AAPL"]]}
    s = rr.summarize([only_msft])
    assert s["coverage"] == {"q1": False}
    assert (s["parts"], s["out_of_scope"]) == (1, 1)


# ---------------------------------------------------------------------------
# compare guard
# ---------------------------------------------------------------------------
def test_compare_flags_a_lost_part_hit_and_lost_coverage():
    base = [_result("a", _part("q1", "PBP", "hit")), _result("b", _part("q2", "value", "hit"))]
    new = [_result("a", _part("q1", "PBP", "rerank", pool=4)), _result("b", _part("q2", "value", "hit"))]
    diff = rr.compare(base, new)
    assert diff["lost"] == [["a", "MSFT", "q1", "PBP"]]
    assert diff["gained"] == []
    assert diff["coverage_lost"] == ["q1"]
    assert diff["class_deltas"] == {"hit": -1, "rerank": 1}
    assert diff["hit_at_5_delta"] == pytest.approx(-0.5)
    assert rr.compare_failed(diff)


def test_compare_passes_on_a_pure_gain_and_counts_a_missing_part_as_not_hit():
    base = [_result("a", _part("q1", "PBP", "dilution")), _result("b", _part("q2", "value", "hit"))]
    new = [_result("a", _part("q1", "PBP", "hit")), _result("b", _part("q2", "value", "hit"))]
    diff = rr.compare(base, new)
    assert (diff["gained"], diff["coverage_gained"], diff["lost"]) == ([["a", "MSFT", "q1", "PBP"]], ["q1"], [])
    assert not rr.compare_failed(diff)
    assert rr.compare_failed(rr.compare(base, new[:1]))


def test_check_base_refuses_a_different_gold_file():
    rr.check_base({"header": {"gold_sha256": "abc"}}, "abc")
    with pytest.raises(ValueError, match="gold"):
        rr.check_base({"header": {"gold_sha256": "abc"}}, "def")


def test_queries_from_report_replays_the_base_query_list():
    base = {"queries": [{"query": "a", "ticker": None, "qids": ["q1"]}], "results": []}
    assert rr.queries_from_report(base) == [{"query": "a", "ticker": None, "qids": ["q1"]}]


def test_filter_qids_keeps_queries_for_the_chosen_questions_and_trims_their_qid_sets():
    queries = [{"query": "a", "ticker": "X", "qids": ["q1", "q2"]}, {"query": "b", "ticker": "X", "qids": ["q3"]}]
    assert rr.filter_qids(queries, ["q2"]) == [{"query": "a", "ticker": "X", "qids": ["q2"]}]
    assert rr.filter_qids(queries, None) == queries


def test_format_summary_names_the_losses():
    base = [_result("a", _part("q1", "PBP", "hit"))]
    new = [_result("a", _part("q1", "PBP", "rerank", pool=4))]
    text = rr.format_summary(rr.summarize(new), rr.compare(base, new))
    assert "hit@5" in text and "LOST" in text and "q1" in text and "PBP" in text


# ---------------------------------------------------------------------------
# propose-gold figure matching
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "text, value, unit, expected",
    [
        ("Revenue $ 35,013 $ 30,000", 35013, "million", ["35,013"]),  # millions
        ("RPO was $72.4 billion; table 72,391", 72.4, "billion", ["72.4", "72,391"]),  # billions -> millions
        ("Revenue 4,475,446 thousands", 4475, "million", ["4,475,446"]),  # thousands prefix
        ("Revenue 1,407,000 and 1,408", 1407, "million", ["1,407,000"]),
        ("Operating margin 32.6 % and 32.6%", 32.6, "percent", ["32.6", "32.6"]),
        ("Diluted EPS $ 2.94 vs 2.95", 2.94, "raw", ["2.94"]),
        ("Other income (1,234) net", 1234, "million", ["(1,234)"]),  # negatives in parentheses
        ("approximately 166,000 full-time", 166000, "raw", ["166,000"]),
        ("fiscal 2026 and 135,013", 35013, "million", []),  # no partial-number match
    ],
)
def test_figure_matches(text, value, unit, expected):
    assert [m.group(0) for m in rr.figure_matches(text, value, unit)] == expected


def test_question_parts_maps_comparison_labels_to_tickers_and_skips_judged():
    numeric = {"id": "n", "type": "numeric", "ticker": "AAPL", "expected_value": 1, "expected_unit": "raw"}
    comparison = {"id": "c", "type": "comparison", "expected": [
        {"ticker": "MSFT-PBP", "expected_value": 35013, "expected_unit": "million"},
        {"ticker": "AAPL", "expected_value": 2, "expected_unit": "raw"},
    ]}
    judged = {"id": "j", "type": "judged", "ticker": "AAPL", "criteria": "..."}
    assert rr.question_parts(numeric) == [("value", "AAPL", 1, "raw")]
    assert rr.question_parts(comparison) == [("MSFT-PBP", "MSFT", 35013, "million"), ("AAPL", "AAPL", 2, "raw")]
    assert rr.question_parts(judged) == []


def test_propose_gold_lists_each_matching_chunk_of_the_parts_ticker():
    question = {"id": "n", "type": "numeric", "ticker": "MSFT", "expected_value": 35013, "expected_unit": "million"}
    chunks = [
        {"text": "x" * 300 + " Revenue 35,013 " + "y" * 300,
         "metadata": {"accessionNumber": "A1", "chunk_index": 35, "ticker": "MSFT", "reportDate": "2026-03-31", "form": "10-Q"}},
        {"text": "Revenue 35,013", "metadata": {"accessionNumber": "Z", "chunk_index": 1, "ticker": "AAPL"}},
    ]
    rows = rr.propose_gold([question], chunks)
    assert len(rows) == 1
    row = rows[0]
    assert (row["qid"], row["part"], row["accession"], row["chunk_index"], row["report_date"], row["token"]) == (
        "n", "value", "A1", 35, "2026-03-31", "35,013")
    assert "35,013" in row["snippet"] and len(row["snippet"]) <= 200


def test_propose_gold_centres_each_snippet_on_its_own_match():
    question = {"id": "n", "type": "numeric", "ticker": "MSFT", "expected_value": 72.4, "expected_unit": "raw"}
    text = "a" * 300 + " 172.4 " + "b" * 300 + " 72.4 " + "c" * 300 + " 72.4 " + "d" * 300
    chunks = [{"text": text, "metadata": {"accessionNumber": "A1", "chunk_index": 1, "ticker": "MSFT"}}]
    rows = rr.propose_gold([question], chunks)
    assert len(rows) == 2
    assert "b" in rows[0]["snippet"] and "c" in rows[0]["snippet"] and "a" not in rows[0]["snippet"]
    assert "c" in rows[1]["snippet"] and "d" in rows[1]["snippet"]


# ---------------------------------------------------------------------------
# main, with the live corpus and retriever swapped for fakes
# ---------------------------------------------------------------------------
@pytest.fixture
def cli(tmp_path, monkeypatch):
    """Files for one question with one gold chunk, and a retriever whose
    final top 5 is set per test through `final`."""
    questions = tmp_path / "questions.jsonl"
    questions.write_text(json.dumps({"id": "q1", "type": "numeric", "ticker": "MSFT", "question": "rev?",
                                     "expected_value": 35013, "expected_unit": "million"}) + "\n", encoding="utf-8")
    traces = tmp_path / "traces.jsonl"
    traces.write_text("\n".join(json.dumps(r) for r in [
        _search("r1", "msft revenue"),
        {"run_id": "r1", "as_type": "agent", "name": "run_agent", "input": {"question": "rev?"}},
    ]) + "\n", encoding="utf-8")
    gold = tmp_path / "gold.jsonl"
    gold.write_text(json.dumps(_gold(accession="A1", anchor="Revenue 35,013")) + "\n", encoding="utf-8")
    corpus = [_chunk("A1", 35, "Revenue 35,013"), _chunk("A1", 36, "other")]
    final = {"ids": ["A1_35"]}

    def retrieve(query, ticker):
        order = [("A1_35", "A1", "MSFT"), ("A1_36", "A1", "MSFT")]
        pool = ["A1_35", "A1_36"]
        return {"bm25": order, "vector": order, "pool": pool, "final": final["ids"],
                "ce": ["A1_36", "A1_35"], "tables": set(), "rescuable": set(),
                "combined": final["ids"] + [p for p in pool if p not in final["ids"]], "scope_dates": None}

    monkeypatch.setattr(rr, "_load_corpus", lambda: corpus)
    floors = []
    monkeypatch.setattr(rr, "_live_retriever", lambda c, fused_floor: floors.append(fused_floor) or retrieve)
    monkeypatch.setattr(rr.eval_harness, "_git_state", lambda: {"git_sha": "abc", "git_dirty": False, "dirty_files": []})
    args = ["--file", str(traces), "--questions", str(questions), "--gold", str(gold)]
    return {"tmp": tmp_path, "args": args, "final": final, "gold": gold, "floors": floors, "traces": traces}


def test_main_writes_a_base_report_and_compare_exits_1_on_a_lost_hit(cli, capsys):
    base = cli["tmp"] / "base.json"
    assert rr.main([*cli["args"], "--out", str(base)]) == 0
    report = json.loads(base.read_text(encoding="utf-8"))
    assert report["queries"] == [{"query": "msft revenue", "ticker": "MSFT", "qids": ["q1"]}]
    assert report["summary"]["hits"] == 1
    assert report["header"]["dropped"] == {"unjoined": 0, "no_gold": 0, "malformed_lines": 0}
    assert report["header"]["gold_sha256"] == rr.file_sha256(cli["gold"])

    cli["final"]["ids"] = ["A1_36"]
    assert rr.main([*cli["args"], "--out", str(cli["tmp"] / "new.json"), "--compare", str(base)]) == 1
    assert "LOST q1/value" in capsys.readouterr().out


@pytest.mark.parametrize("fail", [False, True])
def test_main_drops_retrievals_trace_events_during_the_run_and_restores_the_writer(cli, monkeypatch, fail):
    written, calls = [], []
    monkeypatch.setattr(rr.tracing, "_write_local_log", written.append)
    recorder = rr.tracing._write_local_log
    stub = rr._live_retriever([], None)  # the cli fixture's stub

    def retrieve(query, ticker):
        calls.append(query)
        rr.retrieval.log_event("retrieval_search")  # what a live search logs
        if fail:
            raise RuntimeError("retriever failed mid-run")
        return stub(query, ticker)

    monkeypatch.setattr(rr, "_live_retriever", lambda c, fused_floor: retrieve)
    if fail:
        with pytest.raises(RuntimeError):
            rr.main([*cli["args"], "--out", str(cli["tmp"] / "r.json")])
    else:
        assert rr.main([*cli["args"], "--out", str(cli["tmp"] / "r.json")]) == 0
    assert calls and written == []
    assert rr.tracing._write_local_log is recorder


def test_main_refuses_a_base_measured_against_other_gold_and_unmatched_gold_rows(cli, capsys):
    base = cli["tmp"] / "base.json"
    rr.main([*cli["args"], "--out", str(base)])
    cli["gold"].write_text(json.dumps(_gold(anchor="Revenue 99,999")) + "\n", encoding="utf-8")
    assert rr.main([*cli["args"], "--out", str(cli["tmp"] / "n.json"), "--compare", str(base)]) == 2
    assert "different gold" in capsys.readouterr().err
    assert rr.main([*cli["args"], "--out", str(cli["tmp"] / "n.json")]) == 2
    assert "matches no chunk" in capsys.readouterr().err


def test_main_propose_gold_writes_candidates(cli):
    out = cli["tmp"] / "proposed.jsonl"
    assert rr.main([*cli["args"], "--propose-gold", str(out)]) == 0
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert [(r["qid"], r["chunk_index"], r["token"]) for r in rows] == [("q1", 35, "35,013")]


def test_main_rejects_compare_with_qid(cli):
    with pytest.raises(SystemExit):
        rr.main([*cli["args"], "--compare", "x.json", "--qid", "q1"])


def test_main_rejects_a_qid_with_no_gold(cli, capsys):
    with pytest.raises(SystemExit):
        rr.main([*cli["args"], "--out", str(cli["tmp"] / "r.json"), "--qid", "q1-typo"])
    assert "q1-typo" in capsys.readouterr().err


def test_main_reports_unreadable_gold_and_base_files_without_a_traceback(cli, capsys):
    out = ["--out", str(cli["tmp"] / "r.json")]
    missing = cli["tmp"] / "missing.json"
    bad = cli["tmp"] / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    args = [a if a != str(cli["gold"]) else str(missing) for a in cli["args"]]
    assert rr.main([*args, *out]) == 2
    assert rr.main([*cli["args"], *out, "--compare", str(missing)]) == 2
    assert rr.main([*cli["args"], *out, "--compare", str(bad)]) == 2
    err = capsys.readouterr().err
    assert err.count("retrieval_replay: ") == 3 and "Traceback" not in err


def test_main_compare_header_describes_the_base_query_set(cli):
    base = cli["tmp"] / "base.json"
    assert rr.main([*cli["args"], "--out", str(base), "--qid", "q1"]) == 0
    new = cli["tmp"] / "new.json"
    other = ["--file", str(cli["tmp"] / "unused.jsonl"), *cli["args"][2:]]
    assert rr.main([*other, "--out", str(new), "--compare", str(base)]) == 0
    base_header = json.loads(base.read_text(encoding="utf-8"))["header"]
    header = json.loads(new.read_text(encoding="utf-8"))["header"]
    assert (header["trace_file"], header["qids"], header["gold_questions_without_queries"]) == (
        base_header["trace_file"], ["q1"], base_header["gold_questions_without_queries"])


# ---------------------------------------------------------------------------
# --since and --fused-floor
# ---------------------------------------------------------------------------
def test_records_since_keeps_records_at_or_after_the_prefix():
    records = [{"timestamp": "2026-10-01T19:20:00"}, {"timestamp": "2026-10-02T08:00:00"}, {"timestamp": "2026-10-03"}]
    assert rr.records_since(records, "2026-10-02") == records[1:]
    assert rr.records_since(records, None) == records


def test_since_keeps_a_search_whose_run_started_before_the_window(cli, capsys):
    # The run's agent span is logged before the window starts; its search
    # inside the window must still be joined to its question.
    cli["traces"].write_text("\n".join(json.dumps(r) for r in [
        {"timestamp": "2026-09-19T23:59:00", "run_id": "r1", "as_type": "agent", "name": "run_agent",
         "input": {"question": "rev?"}},
        _search("r1", "msft revenue"),
        _search("r0", "old query", timestamp="2026-09-01T00:00:00"),
    ]) + "\n", encoding="utf-8")
    out = cli["tmp"] / "since.json"
    assert rr.main([*cli["args"], "--out", str(out), "--since", "2026-09-20"]) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["queries"] == [{"query": "msft revenue", "ticker": "MSFT", "qids": ["q1"]}]
    assert report["header"]["since"] == "2026-09-20"


def test_main_rejects_compare_with_since(cli):
    with pytest.raises(SystemExit):
        rr.main([*cli["args"], "--compare", "x.json", "--since", "2026-09-20"])


def test_fused_floor_is_passed_to_the_retriever_and_recorded(cli):
    out = cli["tmp"] / "f0.json"
    assert rr.main([*cli["args"], "--out", str(out), "--fused-floor", "0"]) == 0
    assert cli["floors"] == [0]
    assert json.loads(out.read_text(encoding="utf-8"))["header"]["fused_floor"] == 0


def test_fused_floor_defaults_to_retrievals_own(cli):
    out = cli["tmp"] / "fd.json"
    assert rr.main([*cli["args"], "--out", str(out)]) == 0
    assert cli["floors"] == [None]
    assert json.loads(out.read_text(encoding="utf-8"))["header"]["fused_floor"] == rr.retrieval._FUSED_FLOOR_RANKS
