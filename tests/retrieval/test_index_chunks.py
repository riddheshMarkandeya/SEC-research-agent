"""
Unit tests for index_chunks.py's pure, deterministic helpers
(load_all_chunks/make_id). main() does live embedding + Chroma I/O and
stays # pragma: no cover, per this project's tdd-live-code-carveout
convention -- not unit-tested here.
"""

import json

import pytest

from sec_agent.retrieval import index_chunks


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


# ---------------------------------------------------------------------------
# corpus_identity and its sidecar
# ---------------------------------------------------------------------------
def _write_chunks(root, rel, lines):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(line + "\n" for line in lines), encoding="utf-8")


def test_corpus_identity_counts_files_and_chunks(tmp_path):
    _write_chunks(tmp_path, "AAPL/a_chunks.jsonl", ["{}", "{}"])
    _write_chunks(tmp_path, "MSFT/b_chunks.jsonl", ["{}"])
    (tmp_path / "MSFT" / "notes.txt").write_text("ignored", encoding="utf-8")

    identity = index_chunks.corpus_identity(tmp_path)

    assert identity["chunk_files"] == 2
    assert identity["chunks"] == 3
    assert len(identity["sha"]) == 12
    int(identity["sha"], 16)


def test_corpus_identity_is_stable_across_file_creation_order(tmp_path):
    first, second = tmp_path / "one", tmp_path / "two"
    _write_chunks(first, "AAPL/a_chunks.jsonl", ["x"])
    _write_chunks(first, "MSFT/b_chunks.jsonl", ["y"])
    _write_chunks(second, "MSFT/b_chunks.jsonl", ["y"])
    _write_chunks(second, "AAPL/a_chunks.jsonl", ["x"])
    assert index_chunks.corpus_identity(first) == index_chunks.corpus_identity(second)


def test_corpus_identity_changes_with_content_and_with_path(tmp_path):
    _write_chunks(tmp_path, "AAPL/a_chunks.jsonl", ["x"])
    before = index_chunks.corpus_identity(tmp_path)["sha"]
    _write_chunks(tmp_path, "AAPL/a_chunks.jsonl", ["x2"])
    assert index_chunks.corpus_identity(tmp_path)["sha"] != before

    other = tmp_path / "other"
    _write_chunks(other, "AAPL/renamed_chunks.jsonl", ["x2"])
    assert index_chunks.corpus_identity(other)["sha"] != index_chunks.corpus_identity(tmp_path)["sha"]


def test_corpus_identity_of_empty_or_missing_dir(tmp_path):
    empty = index_chunks.corpus_identity(tmp_path)
    assert empty["chunk_files"] == 0 and empty["chunks"] == 0
    assert index_chunks.corpus_identity(tmp_path / "missing") == empty


def test_sidecar_write_read_and_clear(tmp_path):
    identity = {"chunk_files": 1, "chunks": 2, "sha": "abcdef012345"}
    index_chunks.write_identity_sidecar(tmp_path, identity, "2026-10-06T00:00:00+00:00")

    stored = json.loads((tmp_path / index_chunks.IDENTITY_SIDECAR).read_text(encoding="utf-8"))
    assert stored == {**identity, "indexed_at": "2026-10-06T00:00:00+00:00"}
    assert index_chunks.read_identity_sidecar(tmp_path) == stored

    index_chunks.clear_identity_sidecar(tmp_path)
    assert not (tmp_path / index_chunks.IDENTITY_SIDECAR).exists()
    index_chunks.clear_identity_sidecar(tmp_path)  # already gone: no error


def test_read_identity_sidecar_missing_is_none(tmp_path):
    assert index_chunks.read_identity_sidecar(tmp_path) is None


@pytest.mark.parametrize("content", ["{not json", "[1, 2]", '{"chunks": 2}'])
def test_read_identity_sidecar_raises_on_a_corrupt_file(tmp_path, content):
    (tmp_path / index_chunks.IDENTITY_SIDECAR).write_text(content, encoding="utf-8")
    with pytest.raises(ValueError):
        index_chunks.read_identity_sidecar(tmp_path)


# ---------------------------------------------------------------------------
# corpus_provenance: never raises, records whether the index matches
# ---------------------------------------------------------------------------
def _provenance_dirs(monkeypatch, tmp_path):
    chunks, chroma = tmp_path / "chunks", tmp_path / "chroma"
    _write_chunks(chunks, "AAPL/a_chunks.jsonl", ["{}", "{}"])
    chroma.mkdir()
    events = []
    monkeypatch.setattr(index_chunks, "log_event", lambda category, **fields: events.append((category, fields)))
    return chunks, chroma, events


def test_corpus_provenance_matches_the_sidecar_of_the_same_chunks(monkeypatch, tmp_path):
    chunks, chroma, events = _provenance_dirs(monkeypatch, tmp_path)
    identity = index_chunks.corpus_identity(chunks)
    index_chunks.write_identity_sidecar(chroma, identity, "2026-10-06T00:00:00+00:00")

    # indexed_at stays out: two rebuilds of the same corpus must compare equal.
    assert index_chunks.corpus_provenance(chunks, chroma) == {"corpus": identity, "index_matches_chunks": True}
    assert events == []


def test_corpus_provenance_flags_an_index_built_from_different_chunks(monkeypatch, tmp_path):
    chunks, chroma, _ = _provenance_dirs(monkeypatch, tmp_path)
    index_chunks.write_identity_sidecar(chroma, {"chunk_files": 1, "chunks": 2, "sha": "000000000000"}, "t")
    assert index_chunks.corpus_provenance(chunks, chroma)["index_matches_chunks"] is False


def test_corpus_provenance_missing_sidecar_gives_none_and_logs(monkeypatch, tmp_path):
    chunks, chroma, events = _provenance_dirs(monkeypatch, tmp_path)
    result = index_chunks.corpus_provenance(chunks, chroma)
    assert result["index_matches_chunks"] is None
    assert result["corpus"]["chunks"] == 2
    assert [c for c, _ in events] == ["corpus_sidecar_missing"]


def test_corpus_provenance_corrupt_sidecar_gives_none_and_logs(monkeypatch, tmp_path):
    chunks, chroma, events = _provenance_dirs(monkeypatch, tmp_path)
    (chroma / index_chunks.IDENTITY_SIDECAR).write_text("[1, 2]", encoding="utf-8")
    assert index_chunks.corpus_provenance(chunks, chroma)["index_matches_chunks"] is None
    assert [c for c, _ in events] == ["corpus_sidecar_unreadable"]


def test_corpus_provenance_unreadable_chunks_give_none_and_never_raise(monkeypatch, tmp_path):
    chunks, chroma, events = _provenance_dirs(monkeypatch, tmp_path)

    def unreadable(path):
        raise PermissionError("denied")

    monkeypatch.setattr(index_chunks, "corpus_identity", unreadable)
    assert index_chunks.corpus_provenance(chunks, chroma) == {"corpus": None, "index_matches_chunks": None}
    assert [c for c, _ in events] == ["corpus_identity_failed"]
