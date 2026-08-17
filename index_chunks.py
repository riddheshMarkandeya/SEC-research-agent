"""
Week 2b — Embed chunks and load them into a local Chroma collection
---------------------------------------------------------------------
Reads every ./chunks/<TICKER>/*_chunks.jsonl produced by
chunk_documents.py, embeds the chunk text with a local sentence-
transformers model, and upserts into a persistent on-disk Chroma
collection with the full metadata dict preserved (so Week 3+ can
filter by ticker/form/date and Week 7 can cite accessionNumber).

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
# passage), which matches our use case (a financial question against a
# filing chunk) better than a general sentence-similarity model like
# all-MiniLM-L6-v2. The tradeoff for using an asymmetric model: queries
# need an instruction prefix at search time (see query_chunks.py) but
# passages being indexed do NOT — encode them raw, as below.
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


def main():
    print(f"Loading chunks from {CHUNKS_DIR.resolve()} ...")
    records = load_all_chunks()
    if not records:
        print("No chunks found — run chunk_documents.py first.")
        return
    print(f"  {len(records)} chunks loaded")

    print(f"Loading embedding model {EMBED_MODEL_NAME} (first run downloads weights) ...")
    model = SentenceTransformer(EMBED_MODEL_NAME)

    # Tried prepending a period_labels.py period-label prefix to each
    # chunk's embedded text (to fix nvda-gross-margin-fy26 and
    # msft-rd-expense-q3fy26 -- see PROJECT_CONTEXT.md), but reverted:
    # it caused a regression on a previously-passing query
    # (pltr-revenue-2025). Diagnosed directly: an unrelated boilerplate
    # chunk's vector rank jumped from 30 to 8 purely from gaining the
    # same shared prefix, disproportionately more than the actually
    # correct chunk improved (157->103) -- embedding models don't
    # combine a prefix and content additively, so a uniform per-filing
    # prefix can unpredictably boost the WRONG chunk within a filing
    # even while it helps the RIGHT chunk across filings. Net effect on
    # the eval suite was a regression (14/16 -> 13/16), so reverted
    # rather than kept as a net-negative change. period_labels.py's
    # functions are still used by verify_period_labels.py and remain
    # available for a future, more targeted application (e.g. a
    # reranking-stage signal rather than raw embedding-input
    # concatenation).
    texts = [r["text"] for r in records]
    print(f"Embedding {len(texts)} chunks (batch size {EMBED_BATCH_SIZE}) ...")
    embeddings = model.encode(
        texts,
        batch_size=EMBED_BATCH_SIZE,
        show_progress_bar=True,
        normalize_embeddings=True,  # cosine similarity via dot product
    )

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
