"""
Unit tests for retrieval.py. Covers the pure functions only — _tokenize,
_make_id, reciprocal_rank_fusion, and _combine_fused_and_rerank (the
ranking-math half of rerank(), split out specifically so it's testable
without the live cross-encoder). bm25_search/vector_search/rerank's
model-calling half require a live Chroma index and downloaded models,
so they're exercised by manual runs (python retrieval.py "...")
documented in PROJECT_CONTEXT.md, not here.
"""

import pytest

from retrieval import RRF_K, _combine_fused_and_rerank, _make_id, _tokenize, reciprocal_rank_fusion


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
    # taking the max of the two RRF contributions rescued it.
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

    result = _combine_fused_and_rerank(candidates, cross_encoder_scores, top_n=3)
    result_ids = [r["metadata"]["id"] for r in result]

    assert "target" in result_ids


def test_combine_top_result_favors_agreement_between_both_signals():
    candidates = [_fake_candidate(cid) for cid in ["a", "b"]]
    # "a" is fused rank 1; cross-encoder scores put "b" first.
    cross_encoder_scores = [0.1, 0.9]  # a=0.1 (rank2), b=0.9 (rank1)

    result = _combine_fused_and_rerank(candidates, cross_encoder_scores, top_n=2)

    # a: max(1/(k+1), 1/(k+2)) = 1/(k+1) (its fused rank)
    # b: max(1/(k+2), 1/(k+1)) = 1/(k+1) (its rerank rank)
    # Tied under this scoring scheme — both should be present in the top 2.
    result_ids = {r["metadata"]["id"] for r in result}
    assert result_ids == {"a", "b"}


def test_combine_respects_top_n():
    candidates = [_fake_candidate(cid) for cid in ["a", "b", "c", "d"]]
    cross_encoder_scores = [0.4, 0.3, 0.2, 0.1]

    result = _combine_fused_and_rerank(candidates, cross_encoder_scores, top_n=2)
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

    result = _combine_fused_and_rerank(candidates, cross_encoder_scores, top_n=3)
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

    result = _combine_fused_and_rerank(candidates, cross_encoder_scores, top_n=3)
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

    result = _combine_fused_and_rerank(candidates, cross_encoder_scores, top_n=3)
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

    result = _combine_fused_and_rerank(candidates, cross_encoder_scores, top_n=3)
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

    result = _combine_fused_and_rerank(candidates, cross_encoder_scores, top_n=3)
    result_ids = [r["metadata"]["id"] for r in result]

    assert result_ids == ["c1", "c2", "c3"]
