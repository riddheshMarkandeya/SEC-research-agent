"""
Embed chunks and load them into a local Chroma collection. Reads every
./chunks/<TICKER>/*_chunks.jsonl produced by chunk_documents.py, embeds
the chunk text with a local sentence-transformers model, and upserts
into a persistent on-disk Chroma collection with the full metadata dict
preserved (so downstream code can filter by ticker/form/date and cite
accessionNumber). See
docs/decisions/2026-08-13-embedding-indexing-and-query-cli.md.

Usage:
    python index_chunks.py

Input:  ./chunks/<TICKER>/<accession>_chunks.jsonl
Output: ./chroma_db/  (persistent Chroma store, created if missing)
"""

import json
from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer

from config import CHROMA_DIR, EMBED_MODEL_NAME

CHUNKS_DIR = Path("./chunks")
COLLECTION_NAME = "sec_filings"

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
    for jsonl_path in sorted(CHUNKS_DIR.glob("*/*_chunks.jsonl")):
        with jsonl_path.open(encoding="utf-8") as f:
            for line in f:
                records.append(json.loads(line))
    return records


def make_id(metadata: dict) -> str:
    """accessionNumber is unique per filing; chunk_index is unique within
    a filing, so the pair is a stable, globally unique Chroma document id.
    """
    return f"{metadata['accessionNumber']}_{metadata['chunk_index']}"


def main():  # pragma: no cover -- live embedding-model + Chroma pipeline, no test file exists for this module
    print(f"Loading chunks from {CHUNKS_DIR.resolve()} ...")
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

    print(f"\nDone. Collection '{COLLECTION_NAME}' now has {collection.count()} documents.")

    # Per-ticker breakdown, just to eyeball that nothing got dropped.
    from collections import Counter
    counts = Counter(r["metadata"]["ticker"] for r in records)
    for ticker, n in sorted(counts.items()):
        print(f"  {ticker}: {n}")


if __name__ == "__main__":
    main()
