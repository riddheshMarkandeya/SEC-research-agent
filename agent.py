"""
Week 5 — Agent layer: tool-calling over hybrid_search
-----------------------------------------------------------
answer.py (Week 3) is a single-shot pipeline: the caller must already
know which ticker to search (`--ticker CRM`). That's exactly the gap
Week 3's residual finding flagged — an unfiltered, un-scoped query like
"how many employees does the company have" doesn't reliably surface the
right chunk, even though the *retrieval* is fine once properly scoped.
The fix isn't better retrieval, it's a layer that figures out *which*
company(ies) a question is about before searching — that's what an
agent with a callable search tool does, and a hardcoded pipeline can't.

This file gives the LLM a `search_filings` tool (wrapping
retrieval.hybrid_search) instead of pre-fetching context ourselves. The
model decides what to search for, which ticker to restrict to (if any),
and whether it needs to search again — e.g. calling the tool twice, once
per company, to answer a comparison question across two of the five
covered companies. This is real tool-calling via Ollama's OpenAI-style
`tools` API (verified against qwen2.5:7b-instruct's actual wire format
before writing this: `arguments` comes back as a parsed dict, and the
follow-up tool-result message needs only `{"role": "tool", "content":
...}` — no `tool_call_id` required, unlike OpenAI's API).

Usage:
    python agent.py "How many full-time employees does Apple have?"
    python agent.py "Compare Apple's and Microsoft's effective tax rates." --verbose
"""

import argparse

import requests

from answer import MODEL_NAME, OLLAMA_URL
from companies import load_companies
from retrieval import hybrid_search

MAX_TOOL_ITERATIONS = 6
CHUNKS_PER_SEARCH = 5

# The companies this agent is scoped to, read from companies.json (see
# companies.py) rather than hardcoded here — this used to be its own
# ticker->name dict, duplicating edgar_ingest.py's separate ticker->CIK
# dict under the same COMPANIES name, which is exactly the kind of
# two-copies-of-the-truth setup that drifts silently. Baked into the
# system prompt below rather than exposed as a "list_companies" tool —
# a handful of static facts don't justify a round trip, and every model
# tested so far already knows "Salesforce" -> CRM without help; this
# just makes explicit which companies are actually indexed.
COMPANIES = {ticker: info["name"] for ticker, info in load_companies().items()}

SYSTEM_PROMPT = f"""You are a financial research assistant answering questions about SEC filings for five companies:
{chr(10).join(f"- {ticker}: {name}" for ticker, name in COMPANIES.items())}

You have a `search_filings` tool that searches these companies' 10-K/10-Q filings. Use it to find the information you need before answering — call it once per company if a question spans more than one, and call it again with a different query if your first search doesn't turn up what you need. Do not answer from prior knowledge about these companies; every answer must come from what the tool returns.

Rules:
1. Every factual or numeric claim in your final answer must end with a citation marker like [1] or [2] referring to a search result.
2. If your searches don't turn up enough information to answer, say so explicitly rather than guessing.
3. Do not combine or infer numbers that don't appear directly in a search result (e.g. don't compute a total unless a result states it).
4. Resolve company names to the right ticker yourself (e.g. "Salesforce" -> CRM) — don't ask the user to clarify."""

SEARCH_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "search_filings",
        "description": "Search SEC 10-K/10-Q filing excerpts for one of the five covered companies.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What to search for, as a natural-language question or phrase.",
                },
                "ticker": {
                    "type": "string",
                    "enum": list(COMPANIES.keys()),
                    "description": "Restrict the search to one company's filings. Omit only if genuinely unsure which company the question is about.",
                },
            },
            "required": ["query"],
        },
    },
}


def _resolve_search_args(args: dict, fallback_query: str) -> tuple[str, str | None]:
    """The model doesn't always include every schema-declared argument —
    observed in testing: it sometimes calls search_filings with only
    `ticker` and no `query`, despite `query` being marked required.
    Fall back to the original question rather than search on an empty
    string or crash on a missing key."""
    query = args.get("query") or fallback_query
    ticker = args.get("ticker")
    return query, ticker


def _format_results_block(results: list[dict], start_index: int) -> str:
    """Format one search call's results as numbered excerpts, continuing
    the numbering from start_index rather than restarting at [1] — so
    citation numbers stay globally consistent across multiple tool calls
    within the same conversation."""
    if not results:
        return "(no matching filing excerpts found for this search)"

    blocks = []
    for offset, r in enumerate(results):
        i = start_index + offset
        meta = r["metadata"]
        header = f"[{i}] {meta['ticker']} {meta['form']} (reportDate={meta['reportDate']})"
        blocks.append(f"{header}\n{r['text']}")
    return "\n\n".join(blocks)


def _format_citation_key(all_results: list[dict]) -> str:
    lines = []
    for i, r in enumerate(all_results, start=1):
        meta = r["metadata"]
        lines.append(
            f"  [{i}] {meta['ticker']} {meta['form']} filed {meta['filingDate']} "
            f"(reportDate={meta['reportDate']}, accession={meta['accessionNumber']}, "
            f"chunk={meta['chunk_index']})"
        )
    return "\n".join(lines)


def _call_ollama(messages: list[dict]) -> dict:
    response = requests.post(
        OLLAMA_URL,
        json={
            "model": MODEL_NAME,
            "messages": messages,
            "tools": [SEARCH_TOOL_SCHEMA],
            "stream": False,
            "options": {"temperature": 0.1},
        },
        timeout=120,
    )
    response.raise_for_status()
    return response.json()["message"]


def run_agent(question: str, verbose: bool = False) -> tuple[str, list[dict]]:
    """Run the tool-calling loop until the model produces a final answer
    (no more tool calls) or MAX_TOOL_ITERATIONS is hit. Returns the
    answer text and every chunk retrieved across all tool calls, in the
    same global [n] order the model was shown them in — this is what
    lets the printed citation key line up with the model's citations.

    Known simplification: no deduplication if two tool calls happen to
    surface the same chunk (e.g. two related queries against the same
    company). Fine for now — a duplicate citation is cosmetic, not a
    correctness problem — but worth revisiting if it gets noisy."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]
    all_results: list[dict] = []

    for _ in range(MAX_TOOL_ITERATIONS):
        message = _call_ollama(messages)
        tool_calls = message.get("tool_calls") or []

        if not tool_calls:
            return message.get("content", ""), all_results

        messages.append(message)

        for call in tool_calls:
            query, ticker = _resolve_search_args(call["function"]["arguments"], fallback_query=question)
            if verbose:
                print(f"  [tool call] search_filings(query={query!r}, ticker={ticker!r})")

            results = hybrid_search(query, ticker=ticker, top_k=CHUNKS_PER_SEARCH)
            start_index = len(all_results) + 1
            all_results.extend(results)

            messages.append({"role": "tool", "content": _format_results_block(results, start_index)})

    return (
        "I wasn't able to finish answering within the allotted number of searches. "
        "Try asking a more specific or narrower question.",
        all_results,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question", help="question to answer")
    parser.add_argument("--verbose", action="store_true", help="print each tool call as it happens")
    args = parser.parse_args()

    answer, results = run_agent(args.question, verbose=args.verbose)

    print(f"\nQ: {args.question}\n")
    print(answer)
    if results:
        print("\nSources:")
        print(_format_citation_key(results))


if __name__ == "__main__":
    main()
