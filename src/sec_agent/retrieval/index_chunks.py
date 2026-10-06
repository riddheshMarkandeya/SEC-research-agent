"""
Embed chunks and load them into a local Chroma collection. Reads every
var/chunks/<TICKER>/*_chunks.jsonl produced by chunk_documents.py, embeds
the chunk text with a local sentence-transformers model, and upserts
into a persistent on-disk Chroma collection with the full metadata dict
preserved (so downstream code can filter by ticker/form/date and cite
accessionNumber). See
docs/decisions/2026-08-13-embedding-indexing-and-query-cli.md.

Usage:
    python -m sec_agent.retrieval.index_chunks

Input:  var/chunks/<TICKER>/<accession>_chunks.jsonl
Output: var/chroma_db/  (persistent Chroma store, created if missing)
"""

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer

from sec_agent.config import CHROMA_DIR, CHUNKS_DIR, EMBED_MODEL_NAME
from sec_agent.tracing import log_event

COLLECTION_NAME = "sec_filings"
CHUNK_FILE_GLOB = "*/*_chunks.jsonl"
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


def load_all_chunks() -> list[dict]:
    """Read every chunk record across all tickers into memory.

    ~3,200 chunks of a few KB each is small enough to hold in memory at
    once — no need to stream. Revisit if the company list grows a lot.
    """
    records = []
    for jsonl_path in sorted(CHUNKS_DIR.glob(CHUNK_FILE_GLOB)):
        with jsonl_path.open(encoding="utf-8") as f:
            for line in f:
                records.append(json.loads(line))
    return records


def make_id(metadata: dict) -> str:
    """accessionNumber is unique per filing; chunk_index is unique within
    a filing, so the pair is a stable, globally unique Chroma document id.
    """
    return f"{metadata['accessionNumber']}_{metadata['chunk_index']}"


def corpus_identity(chunks_dir: Path) -> dict:
    """{chunk_files, chunks, sha}: a short hash over every chunk file's
    relative path and content, in sorted path order. var/ isn't versioned,
    so this is what tells two eval runs' corpora apart."""
    digest = hashlib.sha256()
    chunk_files = chunks = 0
    for path in sorted(chunks_dir.glob(CHUNK_FILE_GLOB)):
        content = path.read_bytes()
        digest.update(f"{path.relative_to(chunks_dir).as_posix()}\0".encode())
        digest.update(hashlib.sha256(content).digest())
        chunk_files += 1
        chunks += sum(1 for line in content.splitlines() if line.strip())
    return {"chunk_files": chunk_files, "chunks": chunks, "sha": digest.hexdigest()[:12]}


def _sidecar_path(chroma_dir: Path | str) -> Path:
    return Path(chroma_dir) / IDENTITY_SIDECAR


def write_identity_sidecar(chroma_dir: Path | str, identity: dict, indexed_at: str) -> None:
    _sidecar_path(chroma_dir).write_text(
        json.dumps({**identity, "indexed_at": indexed_at}, indent=2), encoding="utf-8"
    )


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
    """Called before the old collection is dropped, so a build that fails
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


def main():  # pragma: no cover -- live embedding-model + Chroma pipeline
    started = time.monotonic()
    print(f"Loading chunks from {CHUNKS_DIR.resolve()} ...")
    identity = corpus_identity(CHUNKS_DIR)
    records = load_all_chunks()
    if not records:
        print("No chunks found — run chunk_documents.py first.")
        return
    print(f"  {len(records)} chunks loaded")

    print(f"Loading embedding model {EMBED_MODEL_NAME} (first run downloads weights) ...")
    model = SentenceTransformer(EMBED_MODEL_NAME)

    # Tried prepending a period_labels.py period-label prefix to each
    # chunk's embedded text here -- reverted, net regression on the eval
    # suite (embedding models don't combine a prefix and content
    # additively, so a uniform per-filing prefix can unpredictably boost
    # the WRONG chunk within a filing). See
    # docs/decisions/2026-08-16-fiscal-period-labels-tried-and-reverted.md.
    texts = [r["text"] for r in records]
    print(f"Embedding {len(texts)} chunks (batch size {EMBED_BATCH_SIZE}) ...")
    embeddings = model.encode(
        texts,
        batch_size=EMBED_BATCH_SIZE,
        show_progress_bar=True,
        normalize_embeddings=True,  # cosine similarity via dot product
    ).tolist()

    print(f"Opening persistent Chroma store at {CHROMA_DIR} ...")
    client = chromadb.PersistentClient(path=CHROMA_DIR)

    # Drop and recreate so re-running this script (e.g. after a
    # chunk_documents.py fix, as we just did) is idempotent rather than
    # accumulating stale/duplicate rows from prior runs.
    clear_identity_sidecar(CHROMA_DIR)
    existing = [c.name for c in client.list_collections()]
    if COLLECTION_NAME in existing:
        print(f"  Existing collection '{COLLECTION_NAME}' found — deleting to reindex cleanly")
        client.delete_collection(COLLECTION_NAME)

    collection = client.create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )

    print("Upserting into Chroma ...")
    for start in range(0, len(records), CHROMA_ADD_BATCH_SIZE):
        end = start + CHROMA_ADD_BATCH_SIZE
        batch = records[start:end]
        collection.add(
            ids=[make_id(r["metadata"]) for r in batch],
            documents=[r["text"] for r in batch],
            embeddings=embeddings[start:end],
            metadatas=[r["metadata"] for r in batch],
        )
        print(f"  added {end if end < len(records) else len(records)}/{len(records)}")

    elapsed_s = round(time.monotonic() - started, 1)
    write_identity_sidecar(CHROMA_DIR, identity, datetime.now(timezone.utc).isoformat())
    log_event("index_built", documents=collection.count(), elapsed_s=elapsed_s, **identity)
    print(f"\nDone in {elapsed_s}s. Collection '{COLLECTION_NAME}' now has {collection.count()} documents; "
          f"corpus {identity}.")

    # Per-ticker breakdown, just to eyeball that nothing got dropped.
    from collections import Counter
    counts = Counter(r["metadata"]["ticker"] for r in records)
    for ticker, n in sorted(counts.items()):
        print(f"  {ticker}: {n}")


if __name__ == "__main__":
    main()
