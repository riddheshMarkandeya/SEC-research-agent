"""
Unit tests for index_chunks.py's pure, deterministic helpers
(load_chunks, make_id, the sidecar and plan_index_update). build_index()
and main() do live embedding + Chroma I/O and stay # pragma: no cover,
per this project's tdd-live-code-carveout convention; a manual script
against a real Chroma store and model exercises them instead.
"""

import json

import pytest

from sec_agent.retrieval import index_chunks


def test_load_chunks_preserves_line_order_within_one_file(tmp_path):
    path = tmp_path / "AAPL" / "acc1_chunks.jsonl"
    path.parent.mkdir()
    lines = [
        json.dumps({"text": t, "metadata": {"accessionNumber": "acc1", "chunk_index": i}})
        for i, t in enumerate(["first", "second", "third"])
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    records = index_chunks.load_chunks([path])
    assert [r["text"] for r in records] == ["first", "second", "third"]


def test_load_chunks_rejects_a_blank_line_as_the_bm25_reader_does(tmp_path):
    # Skipping it would let the vector index accept a file that BM25's own
    # reader then fails on at query time.
    path = tmp_path / "AAPL" / "acc1_chunks.jsonl"
    path.parent.mkdir()
    path.write_text('{"text": "a"}\n\n{"text": "b"}\n', encoding="utf-8")
    with pytest.raises(json.JSONDecodeError) as raised:
        index_chunks.load_chunks([path])
    assert raised.value.__notes__ == [f"in {path} line 2"]


def test_load_chunks_names_the_file_and_line_of_an_undecodable_byte(tmp_path):
    path = tmp_path / "AAPL" / "acc1_chunks.jsonl"
    path.parent.mkdir()
    path.write_bytes(b'{"text": "a"}\n{"text": "b"}\n{"text": "\xff"}\n')
    with pytest.raises(UnicodeDecodeError) as raised:
        index_chunks.load_chunks([path])
    assert raised.value.__notes__ == [f"in {path} line 3"]


def test_corpus_identity_counts_exactly_the_records_load_chunks_returns(tmp_path):
    # build_index compares the collection's row count with this count.
    _write_chunks(tmp_path, "AAPL/a_chunks.jsonl", ['{"text": "a"}', '{"text": "a2"}'])
    (tmp_path / "MSFT").mkdir()
    (tmp_path / "MSFT" / "b_chunks.jsonl").write_bytes(b'{"text": "b"}\r\n{"text": "b2"}\r\n{"text": "b3"}')
    (tmp_path / "MSFT" / "c_chunks.jsonl").write_bytes(b'{"text": "c"}\r{"text": "c2"}\r')
    files = sorted(tmp_path.glob(index_chunks.CHUNK_FILE_GLOB))
    assert index_chunks.corpus_identity(tmp_path)["chunks"] == len(index_chunks.load_chunks(files)) == 7


def test_load_chunks_of_no_files_is_empty():
    assert index_chunks.load_chunks([]) == []


def test_make_id_formats_accession_and_chunk_index():
    assert (
        index_chunks.make_id({"accessionNumber": "0000320193-24-000123", "chunk_index": 5})
        == "0000320193-24-000123_5"
    )


def test_make_id_handles_chunk_index_zero():
    # Regression-shaped: chunk_index=0 is falsy -- f"{...}" must still
    # format it as "0", not silently drop it.
    assert index_chunks.make_id({"accessionNumber": "acc1", "chunk_index": 0}) == "acc1_0"


def _record(acc, i):
    return {"text": "t", "metadata": {"accessionNumber": acc, "chunk_index": i}}


def test_chunk_ids_are_in_record_order():
    assert index_chunks.chunk_ids([_record("b", 1), _record("a", 0)]) == ["b_1", "a_0"]


def test_chunk_ids_raise_on_a_duplicate_naming_it():
    with pytest.raises(ValueError, match=r"duplicate chunk ids.*'a_0'") as raised:
        index_chunks.chunk_ids([_record("a", 0), _record("b", 0), _record("a", 0)])
    assert "b_0" not in str(raised.value)


def test_chunk_ids_raise_on_a_record_without_id_fields():
    with pytest.raises(KeyError):
        index_chunks.chunk_ids([{"text": "t", "metadata": {"ticker": "AAPL"}}])


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


def test_scan_chunk_files_hashes_each_file_by_relpath_in_sorted_order(tmp_path):
    _write_chunks(tmp_path, "MSFT/b_chunks.jsonl", ["y"])
    (tmp_path / "AAPL").mkdir()
    (tmp_path / "AAPL/a_chunks.jsonl").write_bytes(b"x\n")

    identity, hashes = index_chunks._scan_chunk_files(tmp_path)

    assert list(hashes) == ["AAPL/a_chunks.jsonl", "MSFT/b_chunks.jsonl"]
    # sha256sum of b"x\n", computed outside Python.
    assert hashes["AAPL/a_chunks.jsonl"] == "73cb3858a687a8494ca3323053016282f3dad39d42cf62ca4e79dda2aac7d9ac"
    assert identity == index_chunks.corpus_identity(tmp_path)


def test_scan_chunk_files_hash_changes_with_content(tmp_path):
    _write_chunks(tmp_path, "AAPL/a_chunks.jsonl", ["x"])
    _, before = index_chunks._scan_chunk_files(tmp_path)
    _write_chunks(tmp_path, "AAPL/a_chunks.jsonl", ["x2"])
    _, after = index_chunks._scan_chunk_files(tmp_path)
    assert before["AAPL/a_chunks.jsonl"] != after["AAPL/a_chunks.jsonl"]


def test_load_chunks_reads_only_the_given_files(tmp_path):
    _write_chunks(tmp_path, "AAPL/a_chunks.jsonl", ['{"text": "a"}', '{"text": "a2"}'])
    _write_chunks(tmp_path, "MSFT/b_chunks.jsonl", ['{"text": "b"}'])
    records = index_chunks.load_chunks([tmp_path / "AAPL/a_chunks.jsonl"])
    assert [r["text"] for r in records] == ["a", "a2"]


def test_build_manifest_takes_the_accession_from_the_filename():
    hashes = {"AAPL/0000320193-24-000123_chunks.jsonl": "aa", "MSFT/acc2_chunks.jsonl": "bb"}
    assert index_chunks.build_manifest(hashes) == {
        "AAPL/0000320193-24-000123_chunks.jsonl": {"sha": "aa", "accession": "0000320193-24-000123"},
        "MSFT/acc2_chunks.jsonl": {"sha": "bb", "accession": "acc2"},
    }


def test_build_manifest_covers_an_empty_chunk_file(tmp_path):
    # An empty file has no records to read an accession from; its manifest
    # entry is what later deletes its rows, so it still needs one.
    (tmp_path / "AAPL").mkdir()
    (tmp_path / "AAPL/acc9_chunks.jsonl").write_bytes(b"")
    _, hashes = index_chunks._scan_chunk_files(tmp_path)
    assert index_chunks.build_manifest(hashes)["AAPL/acc9_chunks.jsonl"]["accession"] == "acc9"


def test_sidecar_round_trips_recipe_and_files(tmp_path):
    identity = {"chunk_files": 1, "chunks": 2, "sha": "abcdef012345"}
    recipe = {"embed_model": "m", "index_recipe_version": 1, "sentence_transformers": "5.7.0"}
    files = {"AAPL/acc1_chunks.jsonl": {"sha": "aa", "accession": "acc1"}}
    index_chunks.write_identity_sidecar(tmp_path, identity, "t", recipe=recipe, files=files)
    assert index_chunks.read_identity_sidecar(tmp_path) == {
        **identity, "indexed_at": "t", "recipe": recipe, "files": files,
    }


def test_current_recipe_names_the_model_and_versions():
    recipe = index_chunks.current_recipe()
    assert recipe["embed_model"] == index_chunks.EMBED_MODEL_NAME
    assert isinstance(recipe["index_recipe_version"], int)
    assert isinstance(recipe["sentence_transformers"], str)


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
# plan_index_update: full rebuild vs incremental add/replace/delete
# ---------------------------------------------------------------------------
RECIPE = {"embed_model": "m", "index_recipe_version": 1, "sentence_transformers": "5.7.0"}


def _sidecar(files, chunks=5, recipe=RECIPE):
    return {"chunk_files": len(files), "chunks": chunks, "sha": "abcdef012345", "indexed_at": "t",
            "recipe": recipe,
            "files": {rel: {"sha": sha, "accession": rel.split("/")[1].removesuffix("_chunks.jsonl")}
                      for rel, sha in files.items()}}


CURRENT = {"A/a_chunks.jsonl": "s1", "B/b_chunks.jsonl": "s2"}


def _plan(current=CURRENT, sidecar=None, indexed_count=5, recipe=RECIPE, force_full=False):
    if sidecar is None:
        sidecar = _sidecar(CURRENT)
    return index_chunks.plan_index_update(current, sidecar, indexed_count, recipe, force_full)


def test_plan_unchanged_corpus_is_an_empty_incremental_update():
    update = _plan()
    assert not update.full_rebuild
    assert (update.add, update.replace, update.delete) == ([], [], [])
    assert update.is_noop


def test_plan_one_changed_file_is_not_a_noop():
    assert not _plan(current={**CURRENT, "B/b_chunks.jsonl": "new"}).is_noop
    assert not _plan(force_full=True).is_noop


def test_read_sidecar_or_none_treats_a_corrupt_sidecar_as_missing_and_logs(monkeypatch, tmp_path):
    events = []
    monkeypatch.setattr(index_chunks, "log_event", lambda category, **fields: events.append(category))
    (tmp_path / index_chunks.IDENTITY_SIDECAR).write_text("{not json", encoding="utf-8")
    assert index_chunks._read_sidecar_or_none(tmp_path) is None
    assert events == ["index_sidecar_unreadable"]


def test_read_sidecar_or_none_returns_a_readable_sidecar(tmp_path):
    index_chunks.write_identity_sidecar(tmp_path, {"chunk_files": 0, "chunks": 0, "sha": "abcdef012345"}, "t")
    sidecar = index_chunks._read_sidecar_or_none(tmp_path)
    assert sidecar is not None and sidecar["sha"] == "abcdef012345"


def test_plan_classifies_new_changed_and_removed_files():
    old = {"A/a_chunks.jsonl": "s1", "B/b_chunks.jsonl": "old", "C/c_chunks.jsonl": "s3"}
    current = {"A/a_chunks.jsonl": "s1", "B/b_chunks.jsonl": "s2", "D/d_chunks.jsonl": "s4"}
    update = _plan(current=current, sidecar=_sidecar(old))
    assert not update.full_rebuild
    assert update.add == ["D/d_chunks.jsonl"]
    assert update.replace == ["B/b_chunks.jsonl"]
    assert update.delete == ["C/c_chunks.jsonl"]


def _without(key):
    sidecar = _sidecar(CURRENT)
    del sidecar[key]
    return sidecar


@pytest.mark.parametrize("kwargs", [
    pytest.param({"force_full": True}, id="forced"),
    pytest.param({"sidecar": _without("files")}, id="files-missing"),
    pytest.param({"sidecar": {**_sidecar(CURRENT), "files": ["A/a_chunks.jsonl"]}}, id="files-not-a-dict"),
    pytest.param({"sidecar": {**_sidecar(CURRENT), "files": {"A/a_chunks.jsonl": "s1"}}}, id="entry-not-a-dict"),
    pytest.param({"sidecar": {**_sidecar(CURRENT), "files": {"A/a_chunks.jsonl": {"sha": "s1"}}}},
                 id="entry-without-accession"),
    pytest.param({"sidecar": _without("recipe")}, id="recipe-missing"),
    pytest.param({"recipe": {**RECIPE, "embed_model": "other"}}, id="model-changed"),
    pytest.param({"recipe": {**RECIPE, "index_recipe_version": 2}}, id="recipe-version-changed"),
    pytest.param({"recipe": {**RECIPE, "sentence_transformers": "6.0.0"}}, id="st-version-changed"),
    pytest.param({"indexed_count": None}, id="no-collection"),
    pytest.param({"indexed_count": 4}, id="count-mismatch"),
])
def test_plan_full_rebuild_triggers(kwargs):
    update = _plan(**kwargs)
    assert update.full_rebuild
    assert update.reason


def test_plan_no_sidecar_is_a_full_rebuild():
    update = index_chunks.plan_index_update(CURRENT, None, 5, RECIPE, False)
    assert update.full_rebuild and update.reason


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
