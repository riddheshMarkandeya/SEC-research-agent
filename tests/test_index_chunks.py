"""
Unit tests for index_chunks.py's pure, deterministic helpers
(load_all_chunks/make_id). main() does live embedding + Chroma I/O and
stays # pragma: no cover, per this project's tdd-live-code-carveout
convention -- not unit-tested here.
"""

import json

import index_chunks


def test_load_all_chunks_reads_across_all_ticker_directories(tmp_path, monkeypatch):
    monkeypatch.setattr(index_chunks, "CHUNKS_DIR", tmp_path)
    (tmp_path / "AAPL").mkdir()
    (tmp_path / "MSFT").mkdir()
    (tmp_path / "AAPL" / "acc1_chunks.jsonl").write_text(
        json.dumps({"text": "a", "metadata": {"accessionNumber": "acc1", "chunk_index": 0}}) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "MSFT" / "acc2_chunks.jsonl").write_text(
        json.dumps({"text": "b", "metadata": {"accessionNumber": "acc2", "chunk_index": 0}}) + "\n",
        encoding="utf-8",
    )
    records = index_chunks.load_all_chunks()
    assert {r["metadata"]["accessionNumber"] for r in records} == {"acc1", "acc2"}


def test_load_all_chunks_preserves_line_order_within_one_file(tmp_path, monkeypatch):
    monkeypatch.setattr(index_chunks, "CHUNKS_DIR", tmp_path)
    (tmp_path / "AAPL").mkdir()
    lines = [
        json.dumps({"text": t, "metadata": {"accessionNumber": "acc1", "chunk_index": i}})
        for i, t in enumerate(["first", "second", "third"])
    ]
    (tmp_path / "AAPL" / "acc1_chunks.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    records = index_chunks.load_all_chunks()
    assert [r["text"] for r in records] == ["first", "second", "third"]


def test_load_all_chunks_returns_empty_list_when_no_chunk_files_exist(tmp_path, monkeypatch):
    monkeypatch.setattr(index_chunks, "CHUNKS_DIR", tmp_path)
    assert index_chunks.load_all_chunks() == []


def test_make_id_formats_accession_and_chunk_index():
    assert (
        index_chunks.make_id({"accessionNumber": "0000320193-24-000123", "chunk_index": 5})
        == "0000320193-24-000123_5"
    )


def test_make_id_handles_chunk_index_zero():
    # Regression-shaped: chunk_index=0 is falsy -- f"{...}" must still
    # format it as "0", not silently drop it.
    assert index_chunks.make_id({"accessionNumber": "acc1", "chunk_index": 0}) == "acc1_0"
