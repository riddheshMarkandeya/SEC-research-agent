"""
Week 3 — Citation-grounded answer generation
-------------------------------------------------
Retrieves chunks via retrieval.hybrid_search(), feeds them to a local
LLM (via Ollama) with an explicit "cite everything or refuse" prompt,
and prints the answer alongside a citation key that maps each [n]
marker back to a real filing (ticker/form/reportDate/accessionNumber).

This is a v0 prototype, not the final agent — it exists so Week 4's
eval harness has something concrete to grade before Week 5 builds a
proper agent loop around it. Enforcement of the "no citation, no claim"
rule is currently just a prompt instruction; nothing here parses the
output to verify every sentence actually has a [n] marker attached, or
that cited numbers match the source text. That's exactly the kind of
gap the Week 4 eval suite should catch.

Usage:
    python answer.py "What is Salesforce's remaining performance obligation?" --ticker CRM
"""

import argparse

import requests

from retrieval import hybrid_search

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL_NAME = "qwen2.5:7b-instruct"

SYSTEM_PROMPT = """You are a financial research assistant. You answer questions ONLY using the numbered filing excerpts provided below — never from prior knowledge about the company.

Rules:
1. Every factual or numeric claim in your answer must end with a citation marker like [1] or [2] referring to the excerpt it came from.
2. If the excerpts do not contain enough information to answer the question, say so explicitly rather than guessing.
3. Do not combine or infer numbers that don't appear directly in an excerpt (e.g. don't compute a total unless the excerpts state it)."""


def format_context(results: list[dict]) -> str:
    blocks = []
    for i, r in enumerate(results, start=1):
        meta = r["metadata"]
        header = f"[{i}] {meta['ticker']} {meta['form']} (reportDate={meta['reportDate']})"
        blocks.append(f"{header}\n{r['text']}")
    return "\n\n".join(blocks)


def format_citation_key(results: list[dict]) -> str:
    lines = []
    for i, r in enumerate(results, start=1):
        meta = r["metadata"]
        lines.append(
            f"  [{i}] {meta['ticker']} {meta['form']} filed {meta['filingDate']} "
            f"(reportDate={meta['reportDate']}, accession={meta['accessionNumber']}, "
            f"chunk={meta['chunk_index']})"
        )
    return "\n".join(lines)


def generate_answer(query: str, ticker: str | None = None, top_k: int = 5) -> tuple[str, list[dict]]:
    results = hybrid_search(query, ticker=ticker, top_k=top_k)
    context = format_context(results)

    user_prompt = f"Filing excerpts:\n\n{context}\n\nQuestion: {query}"

    response = requests.post(
        OLLAMA_URL,
        json={
            "model": MODEL_NAME,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "options": {"temperature": 0.1},
        },
        timeout=120,
    )
    response.raise_for_status()
    answer = response.json()["message"]["content"]
    return answer, results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", help="question to answer")
    parser.add_argument("--ticker", default=None, help="restrict retrieval to one ticker, e.g. MSFT")
    parser.add_argument("--k", type=int, default=5, help="number of chunks to retrieve as context")
    args = parser.parse_args()

    answer, results = generate_answer(args.query, ticker=args.ticker, top_k=args.k)

    print(f"\nQ: {args.query}\n")
    print(answer)
    print("\nSources:")
    print(format_citation_key(results))


if __name__ == "__main__":
    main()
