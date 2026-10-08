"""
Embed chunks and load them into a local Chroma collection. Reads every
var/chunks/<TICKER>/*_chunks.jsonl produced by chunk_documents.py, embeds
the chunk text with a local sentence-transformers model, and adds it to
a persistent on-disk Chroma collection with the full metadata dict
preserved (so downstream code can filter by ticker/form/date and cite
accessionNumber).

Runs are incremental: only chunk files that are new or changed since the
last build are embedded, and rows of changed or removed files are
deleted first. A full rebuild happens when the sidecar's per-file
manifest is missing or unreadable, the embedding recipe changed, or the
collection's row count disagrees with the sidecar.

Usage:
    python -m sec_agent.retrieval.index_chunks [--full]

    --full  drop the collection and re-embed everything. Run it before a
            baseline eval comparison: incremental adds and deletes can
            shift HNSW top-k ties slightly from a fresh build.

Input:  var/chunks/<TICKER>/<accession>_chunks.jsonl
Output: var/chroma_db/  (persistent Chroma store, created if missing)
"""

import argparse
import hashlib
import json
import time
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import chromadb
import sentence_transformers
from sentence_transformers import SentenceTransformer

from sec_agent.config import CHROMA_DIR, CHUNKS_DIR, EMBED_MODEL_NAME
from sec_agent.tracing import log_event

COLLECTION_NAME = "sec_filings"
CHUNK_FILE_SUFFIX = "_chunks.jsonl"
CHUNK_FILE_GLOB = f"*/*{CHUNK_FILE_SUFFIX}"
# Bump by hand whenever the encode path changes (the text handed to the
# encoder, normalize_embeddings, ...): such a change alters every vector
# without altering any chunk file, so only this tells an incremental run
# that the stored vectors are stale.
INDEX_RECIPE_VERSION = 1
# Written into the Chroma directory after a successful build, so an eval
# can tell whether the index it queries was built from today's chunk files.
IDENTITY_SIDECAR = "corpus_identity.json"
STALE_INDEX_NOTE = ("the Chroma index was built from different chunk files than the chunks directory holds; "
                    "re-run index_chunks")

# bge-small is trained for asymmetric retrieval (short query -> long
# passage). Queries need an instruction prefix at search time (see
# retrieval.py's own QUERY_INSTRUCTION) but passages being indexed do
# NOT -- encode them raw, as below; getting this backwards measurably
# hurts retrieval. See
# docs/decisions/2026-08-13-embedding-indexing-and-query-cli.md.
EMBED_BATCH_SIZE = 64
CHROMA_ADD_BATCH_SIZE = 500  # keep well under Chroma's internal max-batch limit


def load_chunks(paths: Iterable[Path]) -> list[dict]:
    """Read every chunk record of the given files into memory, in order.

    ~7,500 chunks of a few KB each is small enough to hold in memory at
    once — no need to stream. Revisit if the company list grows a lot.
    """
    records = []
    for jsonl_path in paths:
        # Split as _scan_chunk_files does, so its chunk count matches what
        # loads here, and decode per line, so a bad byte has a line number.
        for n, raw in enumerate(jsonl_path.read_bytes().splitlines(), start=1):
            try:
                records.append(json.loads(raw.decode("utf-8")))
            except ValueError as e:  # JSONDecodeError and UnicodeDecodeError
                # Their own positions are within this one line, not the file.
                e.add_note(f"in {jsonl_path} line {n}")
                raise
    return records


def make_id(metadata: dict) -> str:
    """accessionNumber is unique per filing; chunk_index is unique within
    a filing, so the pair is a stable, globally unique Chroma document id.
    """
    return f"{metadata['accessionNumber']}_{metadata['chunk_index']}"


def chunk_ids(records: list[dict]) -> list[str]:
    """Each record's Chroma id, in order. Raises ValueError on a repeated
    id, which Chroma would otherwise reject only part-way through adding."""
    ids = [make_id(r["metadata"]) for r in records]
    duplicates = sorted(i for i, n in Counter(ids).items() if n > 1)
    if duplicates:
        raise ValueError(f"duplicate chunk ids in the chunk files: {duplicates[:5]}")
    return ids


def _scan_chunk_files(chunks_dir: Path) -> tuple[dict, dict[str, str]]:
    """(identity, {relpath: file sha256 hex}) from one read of each chunk
    file, so the per-file hashes can't disagree with the identity sha."""
    digest = hashlib.sha256()
    hashes: dict[str, str] = {}
    chunks = 0
    for path in sorted(chunks_dir.glob(CHUNK_FILE_GLOB)):
        content = path.read_bytes()
        rel = path.relative_to(chunks_dir).as_posix()
        file_digest = hashlib.sha256(content)
        digest.update(f"{rel}\0".encode())
        digest.update(file_digest.digest())
        hashes[rel] = file_digest.hexdigest()
        chunks += sum(1 for line in content.splitlines() if line.strip())
    identity = {"chunk_files": len(hashes), "chunks": chunks, "sha": digest.hexdigest()[:12]}
    return identity, hashes


def corpus_identity(chunks_dir: Path) -> dict:
    """{chunk_files, chunks, sha}: a short hash over every chunk file's
    relative path and content, in sorted path order. var/ isn't versioned,
    so this is what tells two eval runs' corpora apart."""
    return _scan_chunk_files(chunks_dir)[0]


def build_manifest(hashes: dict[str, str]) -> dict[str, dict]:
    """{relpath: {sha, accession}} for the sidecar. The accession comes from
    the filename, which the chunker keeps as the ingest stem, so an empty
    chunk file still gets one and a later run can delete its rows."""
    return {
        rel: {"sha": sha, "accession": Path(rel).name.removesuffix(CHUNK_FILE_SUFFIX)}
        for rel, sha in hashes.items()
    }


def current_recipe() -> dict:
    """What decides the vectors besides the chunk files themselves; any
    difference from the sidecar's recipe forces a full rebuild."""
    return {
        "embed_model": EMBED_MODEL_NAME,
        "index_recipe_version": INDEX_RECIPE_VERSION,
        "sentence_transformers": sentence_transformers.__version__,
    }


@dataclass(frozen=True)
class IndexUpdate:
    """What a build must do. full_rebuild: drop the collection and embed
    every file. Otherwise add/replace/delete are chunk-file relpaths:
    new, changed, and gone since the sidecar's manifest. reason says why,
    for the log and the console."""
    full_rebuild: bool
    reason: str
    add: list[str] = field(default_factory=list)
    replace: list[str] = field(default_factory=list)
    delete: list[str] = field(default_factory=list)

    @property
    def is_noop(self) -> bool:
        return not (self.full_rebuild or self.add or self.replace or self.delete)


def _is_manifest(files: object) -> bool:
    return isinstance(files, dict) and all(
        isinstance(entry, dict) and isinstance(entry.get("sha"), str) and isinstance(entry.get("accession"), str)
        for entry in files.values()
    )


def _full_rebuild_reason(sidecar: dict | None, indexed_count: int | None, recipe: dict,
                         force_full: bool) -> str | None:
    if force_full:
        return "forced (--full)"
    if sidecar is None:
        return "no readable sidecar (first build, or a previous build did not finish)"
    triggers = [  # first one that holds wins
        (not _is_manifest(sidecar.get("files")), "sidecar has no valid per-file manifest"),
        (sidecar.get("recipe") != recipe, f"embedding recipe changed: {sidecar.get('recipe')} -> {recipe}"),
        (indexed_count is None, f"collection '{COLLECTION_NAME}' missing"),
        (indexed_count != sidecar.get("chunks"),
         f"collection holds {indexed_count} rows but the sidecar recorded {sidecar.get('chunks')}"),
    ]
    return next((reason for holds, reason in triggers if holds), None)


def plan_index_update(current: dict[str, str], sidecar: dict | None, indexed_count: int | None,
                      recipe: dict, force_full: bool) -> IndexUpdate:
    """Compare the current {relpath: sha} against the sidecar's manifest.
    Anything that leaves the stored vectors untrustworthy (no manifest, a
    recipe change, a collection edited outside this script) is a full
    rebuild; otherwise only new, changed and removed files are touched."""
    reason = _full_rebuild_reason(sidecar, indexed_count, recipe, force_full)
    if reason is not None:
        return IndexUpdate(full_rebuild=True, reason=reason)
    assert sidecar is not None  # _full_rebuild_reason returns a reason when it is None
    old = {rel: entry["sha"] for rel, entry in sidecar["files"].items()}
    add = [rel for rel in current if rel not in old]
    replace = [rel for rel in current if rel in old and old[rel] != current[rel]]
    delete = [rel for rel in old if rel not in current]
    reason = "up to date" if not (add or replace or delete) else "changed chunk files"
    return IndexUpdate(full_rebuild=False, reason=reason, add=add, replace=replace, delete=delete)


def _sidecar_path(chroma_dir: Path | str) -> Path:
    return Path(chroma_dir) / IDENTITY_SIDECAR


def write_identity_sidecar(chroma_dir: Path | str, identity: dict, indexed_at: str, *,
                           recipe: dict | None = None, files: dict | None = None) -> None:
    sidecar = {**identity, "indexed_at": indexed_at}
    if recipe is not None:
        sidecar["recipe"] = recipe
    if files is not None:
        sidecar["files"] = files
    _sidecar_path(chroma_dir).write_text(json.dumps(sidecar, indent=2), encoding="utf-8")


def read_identity_sidecar(chroma_dir: Path | str) -> dict | None:
    """The identity the index was last built from, or None when no build
    has finished since the sidecar was cleared. Raises ValueError on a
    corrupt file, including valid JSON that isn't an identity."""
    path = _sidecar_path(chroma_dir)
    if not path.exists():
        return None
    sidecar = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(sidecar, dict) or not isinstance(sidecar.get("sha"), str):
        raise ValueError(f"{path} holds no corpus sha")
    return sidecar


def clear_identity_sidecar(chroma_dir: Path | str) -> None:
    """Called before the collection is changed, so a build that fails
    part-way leaves no identity claiming the index matches the chunks."""
    _sidecar_path(chroma_dir).unlink(missing_ok=True)


def corpus_provenance(chunks_dir: Path, chroma_dir: Path | str) -> dict:
    """{corpus, index_matches_chunks} for a run's record. corpus is computed
    live from chunks_dir, because BM25 and period scoping read the chunk
    files themselves, and is None when they can't be read. The match flag
    says whether the Chroma index was built from those same files, and is
    None when that can't be told. Never raises."""
    try:
        corpus = corpus_identity(chunks_dir)
    except OSError as e:
        log_event("corpus_identity_failed", error=f"{type(e).__name__}: {e}")
        return {"corpus": None, "index_matches_chunks": None}
    try:
        sidecar = read_identity_sidecar(chroma_dir)
    except (OSError, ValueError) as e:  # json.JSONDecodeError is a ValueError
        log_event("corpus_sidecar_unreadable", error=f"{type(e).__name__}: {e}")
        return {"corpus": corpus, "index_matches_chunks": None}
    if sidecar is None:
        log_event("corpus_sidecar_missing", chroma_dir=str(chroma_dir))
        return {"corpus": corpus, "index_matches_chunks": None}
    return {"corpus": corpus, "index_matches_chunks": sidecar["sha"] == corpus["sha"]}


def _read_sidecar_or_none(chroma_dir: Path) -> dict | None:
    """The sidecar, or None when it's missing or unreadable: either way
    the build can't trust the stored vectors and rebuilds fully."""
    try:
        return read_identity_sidecar(chroma_dir)
    except (OSError, ValueError) as e:  # json.JSONDecodeError is a ValueError
        log_event("index_sidecar_unreadable", error=f"{type(e).__name__}: {e}")
        return None


@dataclass(frozen=True)
class IndexResult:
    """update: what the build decided. embedded: chunks embedded and added.
    deleted: rows removed for replaced and removed files."""
    update: IndexUpdate
    embedded: int
    deleted: int


def _has_collection(client) -> bool:  # pragma: no cover -- live Chroma
    return COLLECTION_NAME in [c.name for c in client.list_collections()]


def _collection_count(client) -> int | None:  # pragma: no cover -- live Chroma
    if not _has_collection(client):
        return None
    return client.get_collection(COLLECTION_NAME).count()


def _recreate_collection(client):  # pragma: no cover -- live Chroma
    if _has_collection(client):
        print(f"  Existing collection '{COLLECTION_NAME}' found — deleting to reindex cleanly")
        client.delete_collection(COLLECTION_NAME)
    return client.create_collection(name=COLLECTION_NAME, metadata={"hnsw:space": "cosine"})


def _delete_files(collection, rels: list[str], manifest: dict) -> int:  # pragma: no cover -- live Chroma
    """Remove every row of each file's accession, not just the ids the new
    file still has, so a re-chunk into fewer chunks leaves no orphans."""
    deleted = 0
    for rel in rels:
        deleted += collection.delete(where={"accessionNumber": manifest[rel]["accession"]})["deleted"]
    return deleted


def _embed(records: list[dict]) -> list:  # pragma: no cover -- live model
    if not records:
        return []
    print(f"Loading embedding model {EMBED_MODEL_NAME} (first run downloads weights) ...")
    model = SentenceTransformer(EMBED_MODEL_NAME)

    # Tried prepending a period_labels.py period-label prefix to each
    # chunk's embedded text here -- reverted, net regression on the eval
    # suite (embedding models don't combine a prefix and content
    # additively, so a uniform per-filing prefix can unpredictably boost
    # the WRONG chunk within a filing).
    # Any change to what's encoded or how must bump INDEX_RECIPE_VERSION:
    # it alters the vectors without altering a chunk file's sha.
    texts = [r["text"] for r in records]
    print(f"Embedding {len(texts)} chunks (batch size {EMBED_BATCH_SIZE}) ...")
    return model.encode(
        texts,
        batch_size=EMBED_BATCH_SIZE,
        show_progress_bar=True,
        normalize_embeddings=True,  # cosine similarity via dot product
    ).tolist()


def _add(collection, records: list[dict], ids: list[str],
         embeddings: list) -> None:  # pragma: no cover -- live Chroma
    print("Adding to Chroma ...")
    for start in range(0, len(records), CHROMA_ADD_BATCH_SIZE):
        end = min(start + CHROMA_ADD_BATCH_SIZE, len(records))
        batch = records[start:end]
        collection.add(
            ids=ids[start:end],
            documents=[r["text"] for r in batch],
            embeddings=embeddings[start:end],
            metadatas=[r["metadata"] for r in batch],
        )
        print(f"  added {end}/{len(records)}")


def build_index(chunks_dir: Path, chroma_dir: Path,
                force_full: bool = False) -> IndexResult:  # pragma: no cover -- live model + Chroma
    """Bring the Chroma collection in line with the chunk files: a full
    rebuild when the stored vectors can't be trusted (see
    plan_index_update), else delete and re-embed only the changed files."""
    started = time.monotonic()
    print(f"Scanning chunks in {chunks_dir.resolve()} ...")
    identity, hashes = _scan_chunk_files(chunks_dir)
    sidecar = _read_sidecar_or_none(chroma_dir)
    client = chromadb.PersistentClient(path=str(chroma_dir))
    update = plan_index_update(hashes, sidecar, _collection_count(client), current_recipe(), force_full)
    if update.is_noop:
        log_event("index_up_to_date", **identity)
        print(f"Index up to date: corpus {identity}.")
        return IndexResult(update, 0, 0)
    if not hashes and update.full_rebuild:
        # Nothing to build from, so the existing index and sidecar are left
        # alone. An incremental plan still runs: it deletes the removed files.
        print("No chunks found — run chunk_documents.py first.")
        return IndexResult(update, 0, 0)
    print(f"{'Full rebuild' if update.full_rebuild else 'Incremental update'}: {update.reason}")

    # Read, id and encode before touching the index: a malformed chunk file,
    # a missing or repeated id, or a model failure then raises with the
    # previous build and its sidecar intact. A failure inside Chroma after
    # this point still leaves no sidecar, so the next run rebuilds fully.
    to_embed = list(hashes) if update.full_rebuild else sorted(update.add + update.replace)
    try:
        records = load_chunks(chunks_dir / rel for rel in to_embed)
        ids = chunk_ids(records)
        embeddings = _embed(records)
    except Exception as e:  # deliberately broad: any failure here is logged, then re-raised unchanged
        log_event("index_build_aborted", mode="full" if update.full_rebuild else "incremental",
                  error=f"{type(e).__name__}: {e}", notes=getattr(e, "__notes__", []), **identity)
        raise

    # Cleared before any mutation, so a build that fails part-way leaves no
    # identity claiming the index matches the chunks; the next run then
    # sees no sidecar and rebuilds fully.
    clear_identity_sidecar(chroma_dir)
    if update.full_rebuild:
        collection = _recreate_collection(client)
        deleted = 0
    else:
        assert sidecar is not None  # an incremental plan always comes from a sidecar
        collection = client.get_collection(COLLECTION_NAME)
        deleted = _delete_files(collection, update.replace + update.delete, sidecar["files"])
    _add(collection, records, ids, embeddings)
    embedded = len(records)

    documents = collection.count()
    elapsed_s = round(time.monotonic() - started, 1)
    if documents != identity["chunks"]:
        # No sidecar is written, so the next run rebuilds fully by itself.
        log_event("index_count_mismatch", documents=documents, elapsed_s=elapsed_s, **identity)
        print(f"\nWARNING: collection has {documents} documents but the chunk files hold "
              f"{identity['chunks']}; re-run with --full.")
        return IndexResult(update, embedded, deleted)

    write_identity_sidecar(chroma_dir, identity, datetime.now(timezone.utc).isoformat(),
                           recipe=current_recipe(), files=build_manifest(hashes))
    log_event("index_built", mode="full" if update.full_rebuild else "incremental", reason=update.reason,
              added=len(update.add), replaced=len(update.replace), removed=len(update.delete),
              embedded=embedded, deleted=deleted, documents=documents, elapsed_s=elapsed_s, **identity)
    print(f"\nDone in {elapsed_s}s: embedded {embedded}, deleted {deleted}. Collection "
          f"'{COLLECTION_NAME}' now has {documents} documents; corpus {identity}.")

    # Per-ticker breakdown of what this run embedded, to eyeball that nothing got dropped.
    counts = Counter(str(r["metadata"].get("ticker") or "?") for r in records)
    for ticker, n in sorted(counts.items()):
        print(f"  {ticker}: {n}")
    return IndexResult(update, embedded, deleted)


def main():  # pragma: no cover -- live embedding-model + Chroma pipeline
    parser = argparse.ArgumentParser(description="Embed chunk files into the Chroma index.")
    parser.add_argument("--full", action="store_true",
                        help="drop the collection and re-embed every chunk file")
    args = parser.parse_args()
    build_index(CHUNKS_DIR, Path(CHROMA_DIR), force_full=args.full)


if __name__ == "__main__":
    main()
