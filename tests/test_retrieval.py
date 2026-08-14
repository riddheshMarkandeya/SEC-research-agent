"""
Unit tests for retrieval.py. Covers the pure functions only — _tokenize,
_make_id, and reciprocal_rank_fusion. bm25_search/vector_search/rerank
require a live Chroma index and downloaded models, so they're exercised
by manual runs (python retrieval.py "...") documented in
PROJECT_CONTEXT.md, not here.
"""

import pytest

from retrieval import RRF_K, _make_id, _tokenize, reciprocal_rank_fusion


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
