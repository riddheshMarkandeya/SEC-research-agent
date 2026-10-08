"""
Live verification of index_chunks.build_index's incremental path against
a real Chroma store and the real embedding model, which unit tests can't
show: that delete-by-accession plus add leaves exactly the current chunk
files' ids in the collection, and that the sidecar stays correct.

With fresh temp chunk and Chroma directories and three small chunk files:
  1. first build: full rebuild, every chunk embedded, ids as expected;
  2. second build: nothing to do, nothing embedded, sidecar bytes
     unchanged;
  3. one file re-chunked with fewer chunks, one added, one removed:
     the ids match the current files exactly, the deleted row count is
     the old chunk count of the replaced and removed files, and
     corpus_provenance says the index matches the chunks;
  4. the sidecar's recipe version changed by hand: full rebuild;
  5. the sidecar corrupted: full rebuild, no exception;
  6. a changed chunk file that isn't valid JSON, has a blank line or an
     undecodable byte, has a record without id fields, or repeats a
     chunk_index: the build raises before touching the index, so the
     sidecar and rows are left as they were, and logs exactly one
     index_build_aborted event whose notes name the file and line of a
     parse or decode error;
  7. every chunk file removed: an incremental run deletes all their rows.

Exits 1 when any check fails.

Usage (from the repo root):
    python tests/manual/verify_incremental_index.py
"""

import json
import sys
import tempfile
from pathlib import Path
from unittest import mock

import chromadb

from sec_agent.retrieval import index_chunks

FAILURES: list[str] = []


def check(label: str, ok: bool, detail: object = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f": {detail}" if detail and not ok else ""))
    if not ok:
        FAILURES.append(label)


def write_chunk_file(chunks_dir: Path, ticker: str, accession: str, n: int, tag: str = "") -> None:
    path = chunks_dir / ticker / f"{accession}_chunks.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps({
            "text": f"{ticker} filing {accession} chunk {i} {tag} revenue grew in the period",
            "metadata": {"ticker": ticker, "accessionNumber": accession, "chunk_index": i, "form": "10-K"},
        })
        for i in range(n)
    ]
    path.write_text("".join(line + "\n" for line in lines), encoding="utf-8")


def expected_ids(files: dict[str, int]) -> set[str]:
    return {f"{acc}_{i}" for acc, n in files.items() for i in range(n)}


def collection_ids(chroma_dir: Path) -> set[str]:
    client = chromadb.PersistentClient(path=str(chroma_dir))
    return set(client.get_collection(index_chunks.COLLECTION_NAME).get()["ids"])


def step_first_and_unchanged(chunks_dir: Path, chroma_dir: Path, sidecar: Path) -> dict[str, int]:
    write_chunk_file(chunks_dir, "AAA", "acc-a", 4)
    write_chunk_file(chunks_dir, "BBB", "acc-b", 3)
    write_chunk_file(chunks_dir, "CCC", "acc-c", 2)
    files = {"acc-a": 4, "acc-b": 3, "acc-c": 2}

    print("1. first build")
    result = index_chunks.build_index(chunks_dir, chroma_dir)
    check("full rebuild", result.update.full_rebuild, result.update)
    check("embedded every chunk", result.embedded == 9, result.embedded)
    check("ids match", collection_ids(chroma_dir) == expected_ids(files))

    print("2. unchanged corpus")
    before = sidecar.read_bytes()
    result = index_chunks.build_index(chunks_dir, chroma_dir)
    update = result.update
    check("incremental, nothing to do",
          not update.full_rebuild and not (update.add or update.replace or update.delete), update)
    check("embedded nothing", result.embedded == 0, result.embedded)
    check("sidecar bytes unchanged", sidecar.read_bytes() == before)
    return files


def step_replace_add_remove(chunks_dir: Path, chroma_dir: Path) -> dict[str, int]:
    print("3. replace (fewer chunks), add, remove")
    write_chunk_file(chunks_dir, "AAA", "acc-a", 2, tag="rechunked")
    write_chunk_file(chunks_dir, "DDD", "acc-d", 3)
    (chunks_dir / "CCC" / "acc-c_chunks.jsonl").unlink()
    files = {"acc-a": 2, "acc-b": 3, "acc-d": 3}
    result = index_chunks.build_index(chunks_dir, chroma_dir)
    update = result.update
    check("incremental", not update.full_rebuild, update)
    check("add/replace/delete lists",
          (update.add, update.replace, update.delete)
          == (["DDD/acc-d_chunks.jsonl"], ["AAA/acc-a_chunks.jsonl"], ["CCC/acc-c_chunks.jsonl"]),
          update)
    check("embedded the added and replaced chunks", result.embedded == 5, result.embedded)
    check("deleted old rows of replaced + removed files", result.deleted == 4 + 2, result.deleted)
    check("ids match exactly", collection_ids(chroma_dir) == expected_ids(files),
          collection_ids(chroma_dir) ^ expected_ids(files))
    check_provenance(chunks_dir, chroma_dir)
    return files


def step_untrusted_sidecar(chunks_dir: Path, chroma_dir: Path, sidecar: Path, files: dict[str, int]) -> None:
    print("4. recipe version changed in the sidecar")
    stored = json.loads(sidecar.read_text(encoding="utf-8"))
    stored["recipe"]["index_recipe_version"] = -1
    sidecar.write_text(json.dumps(stored), encoding="utf-8")
    result = index_chunks.build_index(chunks_dir, chroma_dir)
    check("full rebuild", result.update.full_rebuild, result.update)
    check("ids match", collection_ids(chroma_dir) == expected_ids(files))

    print("5. corrupt sidecar")
    sidecar.write_text("{not json", encoding="utf-8")
    result = index_chunks.build_index(chunks_dir, chroma_dir)
    check("full rebuild", result.update.full_rebuild, result.update)
    check("ids match", collection_ids(chroma_dir) == expected_ids(files))
    check_provenance(chunks_dir, chroma_dir)


VALID_B0 = b'{"text": "x", "metadata": {"ticker": "BBB", "accessionNumber": "acc-b", "chunk_index": 0}}\n'
# label: (file bytes, exception type, file line the note must name, or None for no note)
BAD_FILES = {
    "not JSON": (b"{not json\n", json.JSONDecodeError, 1),
    "blank line": (VALID_B0 + b"\n", json.JSONDecodeError, 2),
    "undecodable byte": (VALID_B0 + b'{"text": "\xff"}\n', UnicodeDecodeError, 2),
    "record without id fields": (b'{"text": "x", "metadata": {"ticker": "BBB"}}\n', KeyError, None),
    "duplicate chunk_index": (VALID_B0 * 2, ValueError, None),
}


def step_malformed_file(chunks_dir: Path, chroma_dir: Path, sidecar: Path, files: dict[str, int]) -> None:
    print("6. bad changed file: raises before touching the index")
    path = chunks_dir / "BBB" / "acc-b_chunks.jsonl"
    good = path.read_bytes()
    events: list[tuple[str, dict]] = []
    real_log_event = index_chunks.log_event

    def capture(name: str, **fields) -> None:
        events.append((name, fields))
        real_log_event(name, **fields)

    with mock.patch.object(index_chunks, "log_event", capture):
        for label, (content, expected, note_line) in BAD_FILES.items():
            events.clear()
            before = sidecar.read_bytes() if sidecar.exists() else b""
            path.write_bytes(content)
            try:
                index_chunks.build_index(chunks_dir, chroma_dir)
                check(f"{label}: build raised", False, "no exception")
            except Exception as e:  # deliberately broad: any raise still runs the checks below
                # Exact type: JSONDecodeError subclasses ValueError, so isinstance
                # couldn't tell a parse failure from the duplicate-id guard.
                check(f"{label}: build raised {expected.__name__}", type(e) is expected, repr(e))
            aborted = [fields for name, fields in events if name == "index_build_aborted"]
            check(f"{label}: abort logged once", len(aborted) == 1, events)
            notes = [f"in {path} line {note_line}"] if note_line else []
            check(f"{label}: logged note names line {note_line}" if note_line else f"{label}: no note logged",
                  bool(aborted) and aborted[0]["notes"] == notes, aborted)
            check(f"{label}: sidecar bytes unchanged", sidecar.exists() and sidecar.read_bytes() == before)
            check(f"{label}: ids unchanged", collection_ids(chroma_dir) == expected_ids(files))
    path.write_bytes(good)
    result = index_chunks.build_index(chunks_dir, chroma_dir)
    check("file restored: nothing to do", result.update.is_noop, result.update)


def step_all_removed(chunks_dir: Path, chroma_dir: Path) -> None:
    print("7. every chunk file removed")
    for path in chunks_dir.glob(index_chunks.CHUNK_FILE_GLOB):
        path.unlink()
    result = index_chunks.build_index(chunks_dir, chroma_dir)
    check("incremental delete of all three",
          not result.update.full_rebuild and len(result.update.delete) == 3, result.update)
    check("deleted every row", result.deleted == 8, result.deleted)
    check("collection empty", collection_ids(chroma_dir) == set())
    check_provenance(chunks_dir, chroma_dir)


def check_provenance(chunks_dir: Path, chroma_dir: Path) -> None:
    provenance = index_chunks.corpus_provenance(chunks_dir, chroma_dir)
    check("provenance says the index matches", provenance["index_matches_chunks"] is True, provenance)


def main() -> int:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        chunks_dir, chroma_dir = Path(tmp) / "chunks", Path(tmp) / "chroma"
        chroma_dir.mkdir()
        sidecar = chroma_dir / index_chunks.IDENTITY_SIDECAR
        step_first_and_unchanged(chunks_dir, chroma_dir, sidecar)
        files = step_replace_add_remove(chunks_dir, chroma_dir)
        step_untrusted_sidecar(chunks_dir, chroma_dir, sidecar, files)
        step_malformed_file(chunks_dir, chroma_dir, sidecar, files)
        step_all_removed(chunks_dir, chroma_dir)

    print(f"\n{'ALL PASS' if not FAILURES else f'{len(FAILURES)} FAILED: {FAILURES}'}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
