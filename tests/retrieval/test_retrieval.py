"""
Unit tests for retrieval.py. Covers the pure functions only — _tokenize,
_make_id, reciprocal_rank_fusion, and _combine_fused_and_rerank (the
ranking-math half of rerank(), split out specifically so it's testable
without the live cross-encoder). bm25_search/vector_search/rerank's
model-calling half require a live Chroma index and downloaded models,
so they're exercised by manual runs (python -m sec_agent.retrieval.retrieval "...")
instead.
"""

import pytest
from rank_bm25 import BM25Okapi

from sec_agent.retrieval import retrieval
from sec_agent.retrieval.period_scope import Scope
from sec_agent.retrieval.retrieval import (
    RRF_K,
    SearchHits,
    _bm25_source,
    _choose_lists,
    _combine_fused_and_rerank,
    _make_id,
    _rank_bm25,
    _search_record,
    _ticker_indexes,
    _tokenize,
    reciprocal_rank_fusion,
)


# ---------------------------------------------------------------------------
# _tokenize
# ---------------------------------------------------------------------------
def test_tokenize_lowercases_and_splits_on_non_alphanumeric():
    tokens = _tokenize("Remaining Performance Obligation!")
    assert tokens == ["remaining", "performance", "obligation"]


def test_tokenize_splits_decimal_numbers_on_the_dot():
    # No stemming, no special-casing of decimals — "$72.4" becomes two
    # separate tokens. Documenting this as intended behavior, since it's
    # a direct consequence of the "keep the tokenizer dumb" design choice.
    tokens = _tokenize("$72.4 billion")
    assert tokens == ["72", "4", "billion"]


def test_tokenize_empty_string_returns_empty_list():
    assert _tokenize("") == []


# ---------------------------------------------------------------------------
# _make_id
# ---------------------------------------------------------------------------
def test_make_id_format():
    metadata = {"accessionNumber": "0001108524-26-000060", "chunk_index": 95}
    assert _make_id(metadata) == "0001108524-26-000060_95"


# ---------------------------------------------------------------------------
# reciprocal_rank_fusion
# ---------------------------------------------------------------------------
def _fake_hit(doc_id: str):
    """A minimal (doc_id, text, metadata) tuple — RRF doesn't inspect
    text/metadata, just carries them through, so placeholders are fine."""
    return (doc_id, f"text for {doc_id}", {"id": doc_id})


def test_rrf_favors_a_doc_ranked_in_both_lists_over_a_doc_ranked_first_in_only_one():
    # This is the worked example from the RRF explanation: doc A is #1 in
    # list 1 but absent from list 2; doc B is #3 in list 1 and #2 in list
    # 2. B should win — being found by both methods outweighs being #1 in
    # just one of them.
    list1 = [_fake_hit("A"), _fake_hit("X"), _fake_hit("B")]
    list2 = [_fake_hit("Y"), _fake_hit("B")]

    fused = reciprocal_rank_fusion([list1, list2])
    fused_ids = [doc_id for doc_id, *_ in fused]

    assert fused_ids.index("B") < fused_ids.index("A")


def test_rrf_scores_match_the_formula():
    list1 = [_fake_hit("A"), _fake_hit("X"), _fake_hit("B")]  # A=rank1, B=rank3
    list2 = [_fake_hit("Y"), _fake_hit("B")]  # B=rank2

    fused = reciprocal_rank_fusion([list1, list2], k=RRF_K)
    scores = {doc_id: score for doc_id, _, _, score in fused}

    expected_a = 1.0 / (RRF_K + 1)
    expected_b = 1.0 / (RRF_K + 3) + 1.0 / (RRF_K + 2)

    assert scores["A"] == pytest.approx(expected_a)
    assert scores["B"] == pytest.approx(expected_b)


def test_rrf_includes_docs_that_appear_in_only_one_list():
    list1 = [_fake_hit("only_in_one")]
    fused = reciprocal_rank_fusion([list1, []])
    assert [doc_id for doc_id, *_ in fused] == ["only_in_one"]


def test_rrf_empty_lists_produce_empty_result():
    assert reciprocal_rank_fusion([[], []]) == []


# ---------------------------------------------------------------------------
# _combine_fused_and_rerank
# ---------------------------------------------------------------------------
def _fake_candidate(doc_id: str):
    """A minimal (doc_id, text, metadata, fused_score) tuple — the fourth
    element (fused_score) isn't used by _combine_fused_and_rerank, only
    candidate order matters, so a placeholder is fine."""
    return (doc_id, f"text for {doc_id}", {"id": doc_id}, 0.0)


def test_combine_rescues_a_candidate_great_by_one_signal_but_terrible_by_the_other():
    # This is the real regression case: a chunk ranked #3 by fused
    # BM25+vector search (both methods agreed it was relevant) but #6
    # (last) by the cross-encoder, which — verified empirically — was
    # scoring it poorly due to being a long, multi-topic passage where
    # the relevant sentence was diluted among unrelated content. A pure
    # cross-encoder override, or even a straight RRF-sum of the two
    # rankings, both still buried this candidate in real testing; only
    # taking the max of the two RRF contributions rescued it. The fused
    # floor keeps that max for fused ranks up to _FUSED_FLOOR_RANKS (3).
    # Fused order (as passed in) = candidates' list order: target is #2.
    candidates = [
        _fake_candidate("good_by_both"),
        _fake_candidate("target"),
        _fake_candidate("c"),
        _fake_candidate("d"),
        _fake_candidate("e"),
        _fake_candidate("f"),
    ]
    # Cross-encoder scores: "target" scores worst (last), everything else
    # scores decently — mirrors the real case where several chunks were
    # merely "OK" by both signals while the target was great-then-terrible.
    cross_encoder_scores = [0.5, -9.0, 0.6, 0.4, 0.3, 0.2]  # target's score is the outlier

    result = _combine_fused_and_rerank(candidates, cross_encoder_scores, top_n=3)["results"]
    result_ids = [r["metadata"]["id"] for r in result]

    assert "target" in result_ids


def test_combine_top_result_favors_agreement_between_both_signals():
    candidates = [_fake_candidate(cid) for cid in ["a", "b"]]
    # "a" is fused rank 1; cross-encoder scores put "b" first.
    cross_encoder_scores = [0.1, 0.9]  # a=0.1 (rank2), b=0.9 (rank1)

    result = _combine_fused_and_rerank(candidates, cross_encoder_scores, top_n=2)["results"]

    # Both are inside the fused floor and score 1/(k+1): a by its fused rank,
    # b by its rerank rank. b's cross-encoder tie-break puts it first; both
    # make the top 2.
    result_ids = {r["metadata"]["id"] for r in result}
    assert result_ids == {"a", "b"}


def test_combine_respects_top_n():
    candidates = [_fake_candidate(cid) for cid in ["a", "b", "c", "d"]]
    cross_encoder_scores = [0.4, 0.3, 0.2, 0.1]

    result = _combine_fused_and_rerank(candidates, cross_encoder_scores, top_n=2)["results"]
    assert len(result) == 2


# ---------------------------------------------------------------------------
# _combine_fused_and_rerank -- table-chunk rescue
#
# Regression case: msft-segment-revenue-comparison-q3fy2026. The chunk with
# the actual segment revenue table ranked #14 of ~40 in the fused
# BM25+vector pool (both base signals considered it relevant) but the
# cross-encoder reranked it to #17 -- outside top_n -- in favor of
# near-duplicate MD&A boilerplate that merely echoes the segment names.
# That's a *different* candidate to rescue than
# test_combine_rescues_a_candidate_great_by_one_signal_but_terrible_by_the_
# other above: that test's "target" is great enough by its fused rank alone
# to already win the MAX-of-two-RRF-contributions combined_score. A fused
# rank of ~14 isn't good enough for that (1/(60+14) loses to any candidate
# reranked into the top 5), so the existing MAX-combine logic alone does
# NOT cover this case -- a second, explicit rescue step is needed.
# ---------------------------------------------------------------------------
def _fake_table_candidate(doc_id: str):
    # Includes several dollar figures -- a stand-in for a real financial
    # table (revenue/income breakdown), as opposed to a glossary/
    # definitions table (see _fake_glossary_table_candidate below), which
    # is also flagged contains_table=True but carries no $ figures at all.
    return (doc_id, f"$1 $2 $3 $4 $5 $6 text for {doc_id}", {"id": doc_id, "contains_table": True}, 0.0)


def _fake_glossary_table_candidate(doc_id: str):
    return (doc_id, f"text for {doc_id}", {"id": doc_id, "contains_table": True}, 0.0)


def test_combine_rescues_a_table_chunk_that_ranked_well_pre_rerank_but_got_reranked_out():
    # Fused order = list order: table chunk is fused rank 4 of 8 (top
    # half). Cross-encoder scores give it the WORST score of all 8 (last),
    # while c1/c2/c3 score best on both signals and would naturally fill
    # top_n=3 without any table chunk present at all.
    candidates = [
        _fake_candidate("c1"),
        _fake_candidate("c2"),
        _fake_candidate("c3"),
        _fake_table_candidate("table"),
        _fake_candidate("c5"),
        _fake_candidate("c6"),
        _fake_candidate("c7"),
        _fake_candidate("c8"),
    ]
    cross_encoder_scores = [0.9, 0.8, 0.7, -9.0, 0.6, 0.5, 0.4, 0.3]

    result = _combine_fused_and_rerank(candidates, cross_encoder_scores, top_n=3)["results"]
    result_ids = [r["metadata"]["id"] for r in result]

    assert "table" in result_ids
    assert len(result) == 3


def test_combine_does_not_rescue_a_table_chunk_that_also_ranked_poorly_pre_rerank():
    # Mirrors a prose question (e.g. an AI-risk question): a table chunk
    # with no lexical/semantic match ranks last in the fused pool too
    # (rank 8 of 8, outside the top-half gate) -- self-limiting behavior,
    # this must NOT be force-included just because it's the only table.
    candidates = [
        _fake_candidate("c1"),
        _fake_candidate("c2"),
        _fake_candidate("c3"),
        _fake_candidate("c5"),
        _fake_candidate("c6"),
        _fake_candidate("c7"),
        _fake_candidate("c8"),
        _fake_table_candidate("table"),
    ]
    cross_encoder_scores = [0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, -9.0]

    result = _combine_fused_and_rerank(candidates, cross_encoder_scores, top_n=3)["results"]
    result_ids = [r["metadata"]["id"] for r in result]

    assert "table" not in result_ids


def test_combine_does_not_double_rescue_when_a_table_already_survived_naturally():
    # A table chunk that's simply good by both signals should occupy its
    # earned slot as normal -- the rescue step must not force in a SECOND
    # table on top of it.
    candidates = [
        _fake_table_candidate("table"),
        _fake_candidate("c2"),
        _fake_candidate("c3"),
        _fake_candidate("c4"),
    ]
    cross_encoder_scores = [0.9, 0.8, 0.7, 0.6]

    result = _combine_fused_and_rerank(candidates, cross_encoder_scores, top_n=3)["results"]
    result_ids = [r["metadata"]["id"] for r in result]

    assert result_ids == ["table", "c2", "c3"]


def test_combine_rescue_prefers_a_dollar_dense_table_over_a_glossary_table():
    # Real regression shape found while verifying the fix above: MSFT's
    # 10-Qs also contain a recurring "Microsoft Cloud" metrics GLOSSARY
    # table (term -> definition, zero $ figures) that's flagged
    # contains_table=True the same as a real revenue-breakdown table, and
    # -- being boilerplate repeated every quarter -- ranked BETTER in the
    # fused pool (rank 6) than the actual numeric segment-revenue table
    # (rank 14). Picking by fused rank alone rescued the useless glossary
    # table instead. Both are excluded from the natural (pre-rescue)
    # top_n here (worst two cross-encoder scores) and both qualify for
    # the top-half fused-rank gate -- only the dollar-figure filter tells
    # them apart.
    candidates = [
        _fake_candidate("c1"),
        _fake_candidate("c2"),
        _fake_candidate("c3"),
        _fake_glossary_table_candidate("glossary"),
        _fake_table_candidate("financial"),
        _fake_candidate("c6"),
        _fake_candidate("c7"),
        _fake_candidate("c8"),
        _fake_candidate("c9"),
        _fake_candidate("c10"),
    ]
    cross_encoder_scores = [0.9, 0.8, 0.7, -8.0, -9.0, 0.6, 0.5, 0.4, 0.3, 0.2]

    result = _combine_fused_and_rerank(candidates, cross_encoder_scores, top_n=3)["results"]
    result_ids = [r["metadata"]["id"] for r in result]

    assert "financial" in result_ids
    assert "glossary" not in result_ids


def test_combine_rescue_does_not_fire_when_only_a_glossary_table_is_available():
    # No dollar-dense table anywhere in the pool -- don't force in a
    # useless glossary table just because it's the only contains_table
    # candidate, even though its fused rank (4 of 8, within the top-half
    # gate) would otherwise make it eligible (this is the exact same
    # pool shape as
    # test_combine_rescues_a_table_chunk_that_ranked_well_pre_rerank_but_
    # got_reranked_out above, with the table swapped for a glossary
    # table, confirming the dollar filter -- not the gate -- is what
    # blocks it). Leaving the natural (table-free) ranking stands.
    candidates = [
        _fake_candidate("c1"),
        _fake_candidate("c2"),
        _fake_candidate("c3"),
        _fake_glossary_table_candidate("glossary"),
        _fake_candidate("c5"),
        _fake_candidate("c6"),
        _fake_candidate("c7"),
        _fake_candidate("c8"),
    ]
    cross_encoder_scores = [0.9, 0.8, 0.7, -9.0, 0.6, 0.5, 0.4, 0.3]

    result = _combine_fused_and_rerank(candidates, cross_encoder_scores, top_n=3)["results"]
    result_ids = [r["metadata"]["id"] for r in result]

    assert result_ids == ["c1", "c2", "c3"]


# ---------------------------------------------------------------------------
# _combine_fused_and_rerank -- the fused floor
#
# The cross-encoder's rank decides, except that a chunk in the fused pool's
# top `fused_floor` keeps the better of its two RRF terms. Measured on 901
# logged query parts: max-of-ranks for every rank (the old rule) squeezed out
# chunks the cross-encoder ranked in its top 5, while dropping the fused
# rank entirely lost a few chunks both base retrievers ranked at the top.
# ---------------------------------------------------------------------------
def _ids(results: list[dict]) -> list[str]:
    return [r["metadata"]["id"] for r in results]


def test_floor_zero_is_the_cross_encoders_order():
    candidates = [_fake_candidate(cid) for cid in ["a", "b", "c", "d"]]
    combined = _combine_fused_and_rerank(candidates, [0.1, 0.4, 0.3, 0.2], top_n=3, fused_floor=0)
    assert _ids(combined["results"]) == ["b", "c", "d"]
    assert combined["ce"] == ["b", "c", "d", "a"]


def test_floor_keeps_a_fused_top_chunk_the_cross_encoder_ranks_low():
    # "a" is fused rank 1 but the cross-encoder's last: under the floor it
    # keeps its fused term, 1/(k+1), tying "b" (the cross-encoder's first),
    # which takes the tie. Without the floor "a" would drop out.
    candidates = [_fake_candidate(cid) for cid in ["a", "b", "c", "d"]]
    combined = _combine_fused_and_rerank(candidates, [0.1, 0.4, 0.3, 0.2], top_n=3, fused_floor=3)
    assert _ids(combined["results"]) == ["b", "a", "c"]


def test_floor_does_not_reach_past_its_fused_rank():
    # 16 candidates; "deep" is fused rank 4 and the cross-encoder's last.
    # A floor of 3 doesn't cover it, so the cross-encoder's top 5 win.
    ids = ["c1", "c2", "c3", "deep"] + [f"x{i}" for i in range(12)]
    candidates = [_fake_candidate(cid) for cid in ids]
    scores = [0.9, 0.8, 0.7, -9.0] + [0.6 - i * 0.01 for i in range(12)]
    combined = _combine_fused_and_rerank(candidates, scores, top_n=5, fused_floor=3)
    assert "deep" not in _ids(combined["results"])


def test_floor_keeps_fused_rank_two_with_cross_encoder_rank_fifteen():
    ids = ["top", "target"] + [f"x{i}" for i in range(14)]
    candidates = [_fake_candidate(cid) for cid in ids]
    scores = [0.99, -5.0] + [0.9 - i * 0.01 for i in range(13)] + [-9.0]  # target is ce rank 15 of 16
    combined = _combine_fused_and_rerank(candidates, scores, top_n=5, fused_floor=3)
    assert combined["ce"].index("target") == 14
    assert "target" in _ids(combined["results"])


def test_a_tie_on_the_floor_goes_to_the_cross_encoder():
    # "a" is fused 1 / ce 3 and "c" fused 3 / ce 1: both score 1/(k+1)
    # under the floor; the cross-encoder breaks the tie for "c".
    candidates = [_fake_candidate(cid) for cid in ["a", "b", "c"]]
    combined = _combine_fused_and_rerank(candidates, [0.1, 0.5, 0.9], top_n=3, fused_floor=3)
    assert _ids(combined["results"])[:2] == ["c", "a"]


def test_the_default_floor_is_read_when_called(monkeypatch):
    monkeypatch.setattr(retrieval, "_FUSED_FLOOR_RANKS", 0)
    candidates = [_fake_candidate(cid) for cid in ["a", "b", "c", "d"]]
    assert _ids(_combine_fused_and_rerank(candidates, [0.1, 0.4, 0.3, 0.2], top_n=3)["results"]) == ["b", "c", "d"]


def test_the_rescue_still_applies_under_both_floors_and_is_reported():
    candidates = [_fake_candidate(c) for c in ["c1", "c2", "c3"]] + [_fake_table_candidate("table")] + [
        _fake_candidate(c) for c in ["c5", "c6", "c7", "c8"]
    ]
    scores = [0.9, 0.8, 0.7, -9.0, 0.6, 0.5, 0.4, 0.3]
    for floor in (0, 3):
        combined = _combine_fused_and_rerank(candidates, scores, top_n=3, fused_floor=floor)
        assert _ids(combined["results"]) == ["c1", "c2", "table"]
        assert combined["rescued"] == "table"
        assert combined["combined"][:3] == ["c1", "c2", "c3"]  # the order before the rescue


def test_no_rescue_is_reported_as_none():
    candidates = [_fake_candidate(cid) for cid in ["a", "b", "c", "d"]]
    assert _combine_fused_and_rerank(candidates, [0.4, 0.3, 0.2, 0.1], top_n=2)["rescued"] is None


# ---------------------------------------------------------------------------
# _choose_lists -- strict period scoping and its fallbacks
# ---------------------------------------------------------------------------
def _searcher(filtered: list[list], unfiltered: list[list]):
    calls = []

    def search(report_dates):
        calls.append(report_dates)
        return unfiltered if report_dates is None else filtered

    return search, calls


HIT = [("id", "text", {})]


def test_scoped_query_uses_only_the_filtered_lists():
    search, calls = _searcher([HIT, []], [HIT, HIT])
    lists, label = _choose_lists(Scope(("2025-04-27",), "dates", ()), search)
    assert (lists, label, calls) == ([HIT, []], "dates", [("2025-04-27",)])


def test_unscoped_query_searches_unfiltered_once():
    search, calls = _searcher([HIT, HIT], [HIT, []])
    lists, label = _choose_lists(Scope((), "no_date", ()), search)
    assert (lists, label, calls) == ([HIT, []], "no_date", [None])


def test_both_filtered_lists_empty_falls_back_to_unfiltered():
    search, calls = _searcher([[], []], [HIT, HIT])
    lists, label = _choose_lists(Scope(("1999-12-31",), "dates", ()), search)
    assert (lists, label, calls) == ([HIT, HIT], "filtered_empty", [("1999-12-31",), None])


# ---------------------------------------------------------------------------
# _search_record -- what search_details returns and logs
# ---------------------------------------------------------------------------
def test_search_record_exposes_the_pool_scores_tables_scope_and_floor():
    fused = [_fake_candidate("a"), _fake_table_candidate("t"), _fake_glossary_table_candidate("g")]
    scope_record = {"label": "dates", "report_dates": ["2025-04-27"], "invalid_dates": []}
    record = _search_record(fused, [0.1, 0.9, 0.5], scope_record, top_k=2)
    # t and a tie at 1/(k+1) (t's cross-encoder rank, a's fused rank under the
    # default floor); t wins on the cross-encoder, a still outranks g
    assert _ids(record["results"]) == ["t", "a"]
    assert record["pool"] == ["a", "t", "g"]
    assert record["scores"] == [0.1, 0.9, 0.5]
    assert record["ce"] == ["t", "g", "a"]
    assert (record["tables"], record["rescuable"]) == ({"t", "g"}, {"t"})
    assert (record["scope"], record["fused_floor"]) == (scope_record, 3)


def test_search_record_reports_the_floor_it_ran():
    fused = [_fake_candidate("a"), _fake_candidate("b")]
    record = _search_record(fused, [0.1, 0.9], {"label": "no_date", "report_dates": [], "invalid_dates": []},
                            top_k=1, fused_floor=0)
    assert (_ids(record["results"]), record["fused_floor"]) == (["b"], 0)


def test_search_record_of_an_empty_pool_is_empty():
    record = _search_record([], [], {"label": "no_date", "report_dates": [], "invalid_dates": []}, top_k=5)
    assert (record["results"], record["pool"], record["rescued"]) == ([], [], None)


# ---------------------------------------------------------------------------
# Per-ticker BM25 statistics: _ticker_indexes, _rank_bm25
# ---------------------------------------------------------------------------
def _record(ticker: str, chunk_index: int, text: str, report_date: str = "2026-03-31") -> dict:
    metadata = {"ticker": ticker, "accessionNumber": f"acc-{ticker}", "chunk_index": chunk_index,
                "reportDate": report_date}
    return {"text": text, "metadata": metadata}


# Within A, "revenue" and "cloud" are equally rare, so a1 (three "revenue")
# outranks a2 (one "cloud"). B's chunks all say "revenue", which, counted
# into the statistics, makes "revenue" common and "cloud" rare instead.
_A_RECORDS = [
    _record("A", 1, "revenue revenue revenue alpha"),
    _record("A", 2, "cloud beta gamma delta"),
    _record("A", 3, "other words here only"),
]
_B_RECORDS = [_record("B", i, f"revenue filler{i} more text") for i in range(6)]
_QUERY = "revenue cloud"


def _indexes(records: list[dict]) -> dict[str, tuple[BM25Okapi, list[dict]]]:
    return _ticker_indexes(records, [_tokenize(r["text"]) for r in records])


def _ranked(hits: SearchHits) -> list[str]:
    return [doc_id for doc_id, _, _ in hits]


def test_a_tickers_bm25_ranking_does_not_depend_on_other_tickers():
    alone = _rank_bm25(*_indexes(_A_RECORDS)["A"], _QUERY, 10, None)
    together = _rank_bm25(*_indexes(_A_RECORDS + _B_RECORDS)["A"], _QUERY, 10, None)

    # precondition: one index over every ticker, filtered to A afterwards,
    # orders A's chunks differently, so this fixture exercises the bug
    everything = _A_RECORDS + _B_RECORDS
    whole = BM25Okapi([_tokenize(r["text"]) for r in everything])
    whole_hits = _rank_bm25(whole, everything, _QUERY, 20, None)
    whole_a = [doc_id for doc_id in _ranked(whole_hits) if doc_id.startswith("acc-A")]
    assert whole_a != _ranked(alone)

    assert _ranked(alone) == ["acc-A_1", "acc-A_2"]
    assert together == alone


def test_ticker_indexes_hold_one_entry_per_ticker_with_its_own_records():
    indexes = _indexes(_B_RECORDS[:2] + _A_RECORDS + _B_RECORDS[2:])
    assert sorted(indexes) == ["A", "B"]
    assert indexes["A"][1] == _A_RECORDS
    assert indexes["B"][1] == _B_RECORDS


# "common" is in 3 of 4 chunks, "half" in 2. rank_bm25's Okapi IDF is
# negative for the first and exactly 0 for the second, and it lifts the
# negative one to a floor that puts the commoner word above the rarer.
_IDF_RECORDS = [
    _record("A", 1, "common half alpha"),
    _record("A", 2, "common half beta"),
    _record("A", 3, "common gamma"),
    _record("A", 4, "delta epsilon"),
]


def test_a_tickers_idf_falls_as_a_word_gets_commoner():
    index, _ = _indexes(_IDF_RECORDS)["A"]
    assert 0 < index.idf["common"] < index.idf["half"] < index.idf["alpha"]


def test_a_chunk_matching_only_a_word_in_half_the_chunks_still_ranks():
    index, recs = _indexes(_IDF_RECORDS)["A"]
    assert _ranked(_rank_bm25(index, recs, "half", 10, None)) == ["acc-A_1", "acc-A_2"]


def test_rank_bm25_keeps_only_the_given_report_dates():
    records = [_record("A", 1, "revenue alpha", "2026-03-31"), _record("A", 2, "revenue beta", "2025-12-31"),
               _record("A", 3, "unrelated words")]
    index, recs = _indexes(records)["A"]
    assert _ranked(_rank_bm25(index, recs, "revenue", 10, ("2025-12-31",))) == ["acc-A_2"]


def test_rank_bm25_stops_at_the_first_chunk_with_no_query_term():
    index, recs = _indexes(_A_RECORDS)["A"]
    assert _ranked(_rank_bm25(index, recs, "cloud", 10, None)) == ["acc-A_2"]


def test_rank_bm25_caps_the_results_at_n():
    index, recs = _indexes(_A_RECORDS)["A"]
    assert _ranked(_rank_bm25(index, recs, _QUERY, 1, None)) == ["acc-A_1"]


def test_bm25_source_is_the_whole_corpus_index_without_a_ticker():
    whole = _indexes(_A_RECORDS)["A"]
    assert _bm25_source(None, whole, {}) is whole
    assert _bm25_source("", whole, {}) is whole


def test_bm25_source_is_the_tickers_own_index_with_a_ticker():
    by_ticker = _indexes(_A_RECORDS + _B_RECORDS)
    assert _bm25_source("B", by_ticker["A"], by_ticker) is by_ticker["B"]


def test_bm25_source_is_none_for_a_ticker_with_no_chunks():
    by_ticker = _indexes(_A_RECORDS)
    assert _bm25_source("ZZZ", by_ticker["A"], by_ticker) is None
