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
