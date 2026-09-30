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


def _chunk(accession, index, text, ticker="MSFT"):
    return {"text": text, "metadata": {"accessionNumber": accession, "chunk_index": index, "ticker": ticker}}


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
        _chunk("B1", 12, "prior period Revenue 35,013"),
    ]
    index, unmatched = rr.index_gold(chunks, rows)
    assert index == {
        ("q1", "value"): [
            {"chunk": "A1_35", "ticker": "MSFT", "own_period": True},
            {"chunk": "A1_47", "ticker": "MSFT", "own_period": True},
            {"chunk": "B1_12", "ticker": "MSFT", "own_period": False},
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
    assert rr.rank_stats(order, "A1_35") == {"rank": 5, "own_filing_rank": 2, "other_filing_ahead": 2}
    assert rr.rank_stats(order, "A1_99") is None


def test_gold_chunk_record_takes_pool_position_and_final_rank_from_the_real_path():
    lists = {
        "bm25": _order("A1_35:A1:MSFT"),
        "vector": _order("A1_1:A1:MSFT", "A1_35:A1:MSFT"),
        "pool": ["A1_1", "A1_35"],
        "final": ["A1_35"],
    }
    record = rr.gold_chunk_record("A1_35", lists)
    assert record == {
        "chunk": "A1_35",
        "bm25": {"rank": 1, "own_filing_rank": 1, "other_filing_ahead": 0},
        "vector": {"rank": 2, "own_filing_rank": 2, "other_filing_ahead": 0},
        "pool_pos": 2,
        "final_rank": 1,
    }
    missing = rr.gold_chunk_record("A1_9", lists)
    assert (missing["bm25"], missing["vector"], missing["pool_pos"], missing["final_rank"]) == (None, None, None, None)


def _rec(chunk="c", final=None, pool=None, bm25=None, vector=None):
    def stats(v):
        return None if v is None else {"rank": v[0], "own_filing_rank": v[1], "other_filing_ahead": v[2]}
    return {"chunk": chunk, "bm25": stats(bm25), "vector": stats(vector), "pool_pos": pool, "final_rank": final}


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
    ],
)
def test_classify(record, expected):
    assert rr.classify(record) == expected


def test_evaluate_query_scores_each_part_of_each_qid_on_its_best_gold_chunk():
    gold_index = {
        ("q1", "PBP"): [{"chunk": "A1_35", "ticker": "MSFT", "own_period": True},
                        {"chunk": "A1_47", "ticker": "MSFT", "own_period": True}],
        ("q1", "IC"): [{"chunk": "B1_3", "ticker": "MSFT", "own_period": False}],
        ("q2", "value"): [{"chunk": "A1_1", "ticker": "MSFT", "own_period": True}],
    }
    lists = {
        "bm25": _order("A1_47:A1:MSFT", "A1_35:A1:MSFT"),
        "vector": _order("A1_35:A1:MSFT"),
        "pool": ["A1_47", "A1_35"],
        "final": ["A1_35"],
    }
    result = rr.evaluate_query({"query": "q", "ticker": "MSFT", "qids": ["q1"]}, lists, gold_index)
    assert [(p["qid"], p["part"], p["hit"], p["class"], p["own_period"]) for p in result["parts"]] == [
        ("q1", "IC", False, "unranked", False),
        ("q1", "PBP", True, "hit", True),
    ]
    pbp = result["parts"][1]
    assert pbp["best"]["chunk"] == "A1_35"
    assert [c["chunk"] for c in pbp["chunks"]] == ["A1_35", "A1_47"]


def test_evaluate_query_skips_parts_whose_gold_the_ticker_filter_excludes():
    gold_index = {
        ("q1", "AAPL"): [{"chunk": "X1_1", "ticker": "AAPL", "own_period": True}],
        ("q1", "MSFT"): [{"chunk": "A1_1", "ticker": "MSFT", "own_period": True}],
    }
    lists = {"bm25": _order("A1_1:A1:MSFT"), "vector": _order("A1_1:A1:MSFT"), "pool": ["A1_1"], "final": ["A1_1"]}
    filtered = rr.evaluate_query({"query": "q", "ticker": "MSFT", "qids": ["q1"]}, lists, gold_index)
    assert [p["part"] for p in filtered["parts"]] == ["MSFT"]
    assert filtered["out_of_scope"] == [["q1", "AAPL"]]
    unfiltered = rr.evaluate_query({"query": "q", "ticker": None, "qids": ["q1"]}, lists, gold_index)
    assert [p["part"] for p in unfiltered["parts"]] == ["AAPL", "MSFT"]
    assert unfiltered["out_of_scope"] == []


# ---------------------------------------------------------------------------
# summarize and coverage
# ---------------------------------------------------------------------------
def _part(qid, part, cls, own_period=True, pool=None):
    hit = cls == "hit"
    return {"qid": qid, "part": part, "hit": hit, "class": cls, "own_period": own_period,
            "best": _rec(final=1 if hit else None, pool=pool if pool is not None else (1 if hit else None))}


def _result(query, *parts, ticker="MSFT"):
    return {"query": query, "ticker": ticker, "qids": sorted({p["qid"] for p in parts}), "parts": list(parts)}


def test_summarize_counts_hits_reach_classes_and_question_coverage():
    results = [
        _result("a", _part("q1", "PBP", "hit"), _part("q1", "IC", "dilution", own_period=False)),
        _result("b", _part("q1", "PBP", "rerank", pool=12), _part("q1", "IC", "hit", own_period=False)),
        _result("c", _part("q2", "value", "rerank", pool=3)),
    ]
    s = rr.summarize(results)
    assert (s["parts"], s["hits"], s["reached"]) == (5, 2, 4)
    assert s["hit_at_5"] == pytest.approx(0.4)
    assert s["reach"] == pytest.approx(0.8)
    assert s["classes"] == {"hit": 2, "rerank": 2, "dilution": 1}
    assert s["by_period"] == {"own": {"hit": 1, "rerank": 2}, "other": {"hit": 1, "dilution": 1}}
    assert s["coverage"] == {"q1": True, "q2": False}
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
    assert rr.figure_matches(text, value, unit) == expected


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
        return {"bm25": order, "vector": order, "pool": ["A1_35", "A1_36"], "final": final["ids"]}

    monkeypatch.setattr(rr, "_load_corpus", lambda: corpus)
    monkeypatch.setattr(rr, "_live_retriever", lambda c: retrieve)
    monkeypatch.setattr(rr.eval_harness, "_git_state", lambda: {"git_sha": "abc", "git_dirty": False, "dirty_files": []})
    args = ["--file", str(traces), "--questions", str(questions), "--gold", str(gold)]
    return {"tmp": tmp_path, "args": args, "final": final, "gold": gold}


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
