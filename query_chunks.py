"""
Week 2b — Manual sanity-check queries against the Chroma index
------------------------------------------------------------------
Runs a preset list of financial questions against the sec_filings
Chroma collection and prints the top matches so retrieval quality can
be eyeballed before Week 3 builds the real (hybrid + reranked)
retrieval layer. Not an eval harness — no scoring, just human review.

Usage:
    python query_chunks.py                  # run all preset queries
    python query_chunks.py "your question"  # run just one ad-hoc query
    python query_chunks.py "your question" --ticker MSFT --n 5
"""

import argparse
import textwrap

import chromadb
from sentence_transformers import SentenceTransformer

CHROMA_DIR = "./chroma_db"
COLLECTION_NAME = "sec_filings"
MODEL_NAME = "BAAI/bge-small-en-v1.5"

# bge-small is an asymmetric retrieval model: it was trained so that
# queries and passages live in comparably-scaled regions of the
# embedding space only when the query carries this instruction prefix.
# Passages were indexed WITHOUT it (see index_chunks.py) — using it on
# both sides, or neither, measurably hurts retrieval quality for this
# model family.
QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "

DEFAULT_N_RESULTS = 3

# A spread of query types, deliberately chosen to stress different
# parts of the pipeline:
#   - numeric lookups that should land on a <TABLE> chunk
#   - qualitative/narrative questions that should land on prose
#   - company-specific vocabulary (segment names, product lines) to
#     check the embedding model understands domain terms without
#     any fine-tuning
#   - one deliberately vague/ambiguous query, to see how retrieval
#     degrades gracefully (or doesn't) when the question is fuzzy
SANITY_QUERIES = [
    "What was Apple's total net sales for the quarter?",
    "How much stock did Apple repurchase during the period?",
    "What is Microsoft's revenue from the Intelligent Cloud segment?",
    "How does NVIDIA describe growth in data center revenue?",
    "What is Salesforce's remaining performance obligation?",
    "What are Palantir's government contract revenues?",
    "Describe the company's outstanding litigation and legal proceedings.",
    "What was the effective tax rate for the period?",
    "How much cash and cash equivalents did the company hold at period end?",
    "What risks does the company describe related to artificial intelligence competition?",
    "What risks does the company describe related to supply chain disruptions?",
    "How many full-time employees does the company have?",
    "What was the impact of foreign currency exchange rates on revenue?",
    "Describe stock-based compensation expense for the period.",
    "What is the company's dividend policy?",
]


def format_result(rank: int, document: str, metadata: dict, distance: float) -> str:
    similarity = 1 - distance  # Chroma's cosine space reports distance = 1 - cosine_sim
    preview = textwrap.shorten(document.replace("\n", " "), width=280, placeholder=" ...")
    table_flag = "[TABLE]" if metadata.get("contains_table") else "[prose]"
    return (
        f"  {rank}. sim={similarity:.3f} {table_flag} "
        f"{metadata['ticker']} {metadata['form']} "
        f"(reportDate={metadata['reportDate']}, chunk={metadata['chunk_index']})\n"
        f"     {preview}"
    )


def run_query(collection, model, query: str, n_results: int, ticker: str | None):
    query_embedding = model.encode(
        QUERY_INSTRUCTION + query,
        normalize_embeddings=True,
    )
    where = {"ticker": ticker} if ticker else None
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=n_results,
        where=where,
    )

    print(f"\nQ: {query}")
    if ticker:
        print(f"   (filtered to ticker={ticker})")
    documents = results["documents"][0]
    metadatas = results["metadatas"][0]
    distances = results["distances"][0]
    if not documents:
        print("  (no results)")
        return
    for i, (doc, meta, dist) in enumerate(zip(documents, metadatas, distances), start=1):
        print(format_result(i, doc, meta, dist))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", nargs="?", help="ad-hoc query; omit to run all preset sanity queries")
    parser.add_argument("--ticker", default=None, help="restrict results to one ticker, e.g. MSFT")
    parser.add_argument("--n", type=int, default=DEFAULT_N_RESULTS, help="results per query")
    args = parser.parse_args()

    client = chromadb.PersistentClient(path=CHROMA_DIR)
    collection = client.get_collection(COLLECTION_NAME)
    print(f"Collection '{COLLECTION_NAME}' has {collection.count()} documents.")

    model = SentenceTransformer(MODEL_NAME)

    queries = [args.query] if args.query else SANITY_QUERIES
    for query in queries:
        run_query(collection, model, query, args.n, args.ticker)


if __name__ == "__main__":
    main()
