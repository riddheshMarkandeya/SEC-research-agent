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
from xbrl_facts import get_gross_margin, get_metric, DEFAULT_METRIC_TAGS

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

You have two tools:
- `get_financial_fact` searches structured XBRL data for a small set of standard financial metrics: {", ".join(sorted(DEFAULT_METRIC_TAGS)) + ", gross_margin"}. Prefer this tool FIRST whenever the question asks for one of these specific metrics for a specific fiscal year or fiscal quarter — it returns an exact, unambiguous reported value instead of relying on you to find the right sentence in a filing excerpt. It only works for these metrics and returns "not available" if the company doesn't tag it or the period wasn't recognized — fall back to `search_filings` when that happens, or for anything this tool doesn't cover (risk factors, narrative discussion, any metric not in the list above).
- `search_filings` searches these companies' 10-K/10-Q filings for anything else. Call it once per company if a question spans more than one, and call it again with a different query if your first search doesn't turn up what you need.

Do not answer from prior knowledge about these companies; every answer must come from what a tool returns.

Rules:
1. Every factual or numeric claim in your final answer must end with a citation marker like [1] or [2] referring to a search result.
2. If your searches don't turn up enough information to answer, say so explicitly rather than guessing.
3. Do not combine or infer numbers that don't appear directly in a search result (e.g. don't compute a total unless a result states it) — this does not apply to `get_financial_fact`'s own output, which is already a single reported or tool-computed value.
4. Resolve company names to the right ticker yourself (e.g. "Salesforce" -> CRM) — don't ask the user to clarify.
5. Search results often report the same metric for several different periods in one excerpt — not just in tables, but within a single sentence, e.g. "the rate was 20% for the current quarter, and 18% for the same quarter last year." Before citing a number, check that its stated period exactly matches the period asked about, even when both numbers appear right next to each other in the same sentence — do not substitute a prior-year or prior-quarter value just because it's nearby.
6. For a question spanning multiple companies, you must query EVERY company mentioned — with `search_filings` if `get_financial_fact` didn't cover it — before writing your final answer. A `get_financial_fact` call returning "not available" for one company is not a reason to stop; it means try `search_filings` for that same company next, and you must still go on to query every other company the question asks about. Do not conclude a company's data is unavailable unless you have actually searched for it."""

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
                    "description": "What to search for, as a natural-language question or phrase. Only used for a follow-up search against a company you've already searched — the first search against each company always uses the user's original question.",
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

FACT_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "get_financial_fact",
        "description": (
            "Look up an exact structured value for one standard financial metric, for one "
            "company and one period. Specify the period ONE of two ways: (a) if the question "
            "gives a specific calendar date (e.g. 'the quarter ended April 26, 2026'), pass "
            "period_end_date and leave fiscal_year/fiscal_period out -- the tool converts it to "
            "the company's own fiscal labeling for you, which you should NOT try to compute "
            "yourself (a calendar date can fall in a different fiscal year than its calendar "
            "year for these companies). (b) if the question already states the period in fiscal "
            "terms (e.g. 'fiscal year 2026', 'the third quarter of fiscal year 2026'), pass "
            "fiscal_year and fiscal_period directly instead. Returns null if the company doesn't "
            "tag this metric or the period isn't recognized -- fall back to search_filings when "
            "that happens."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "enum": list(COMPANIES.keys())},
                "metric": {
                    "type": "string",
                    "enum": sorted(DEFAULT_METRIC_TAGS) + ["gross_margin"],
                    "description": "Which metric to fetch. gross_margin is computed as gross_profit/revenue and returned as a percent; the rest are returned in USD.",
                },
                "period_end_date": {
                    "type": "string",
                    "description": "A calendar date 'YYYY-MM-DD' from the question (e.g. the quarter- or fiscal-year-end date stated). Preferred whenever the question states an actual date -- do not convert it to a fiscal year yourself.",
                },
                "fiscal_year": {
                    "type": "integer",
                    "description": "Only use this when the question states a fiscal year directly instead of a calendar date. The fiscal year as the company itself labels it -- do not guess this from a calendar date, use period_end_date instead.",
                },
                "fiscal_period": {
                    "type": "string",
                    "enum": ["FY", "Q1", "Q2", "Q3", "Q4"],
                    "description": "Only used together with fiscal_year. FY for a full fiscal year (from the 10-K), or Q1/Q2/Q3 for a quarter (from a 10-Q). Q4 is not separately available for most of these companies -- fall back to search_filings for Q4-specific figures.",
                },
            },
            "required": ["ticker", "metric"],
        },
    },
}


def _resolve_search_args(
    args: dict, fallback_query: str, searched_tickers: set[str | None]
) -> tuple[str, str | None]:
    """Extract (query, ticker) from a tool call's arguments.

    The model doesn't always include every schema-declared argument —
    observed in testing: it sometimes calls search_filings with only
    `ticker` and no `query`, despite `query` being marked required.

    The model's own `query` text is only trusted on a *retry* against a
    ticker already searched earlier in this conversation
    (`searched_tickers`). The first search against each company always
    uses the original question verbatim instead. Found by testing, not
    assumed: the model's self-written first-pass queries were the direct
    cause of two separate eval failures — a too-vague query ("Microsoft
    ... Q4 2025") buried the correct chunk among annual-report decoys,
    while a too-literal one (the exact calendar date) over-matched an
    unrelated financial-statement table instead of the prose paragraph
    that never repeats that date. Different companies phrase the same
    fact differently in their filings, so no single query-phrasing
    instruction generalized across both — but the user's own original
    question, which already contains the metric name and the period in
    their own words, retrieved the right chunk in every case tested. A
    retry search (the model deciding its first attempt came up short)
    still gets to use its own query, since that's a deliberate
    refinement rather than a first guess."""
    ticker = args.get("ticker")
    if ticker not in searched_tickers:
        return fallback_query, ticker
    return args.get("query") or fallback_query, ticker


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


def _call_get_financial_fact(args: dict) -> dict | None:
    """This is a real system boundary, not just an internal call — the
    model doesn't reliably respect the schema. Found live: asked for
    "effective tax rate" (not a supported metric, not in the schema's
    enum) and called this with metric omitted entirely rather than
    picking a valid enum value or skipping the tool, which crashed the
    whole run with an unhandled ValueError from xbrl_facts._tag_for
    before this guard existed. Same class of issue as
    _resolve_search_args's docstring above (the model doesn't always
    include every schema-declared argument) — validate here, at the
    boundary, rather than trusting the schema was followed."""
    ticker = args.get("ticker")
    metric = args.get("metric")
    if ticker not in COMPANIES or (metric not in DEFAULT_METRIC_TAGS and metric != "gross_margin"):
        return None
    fiscal_year = args.get("fiscal_year")
    fiscal_period = args.get("fiscal_period", "FY")
    period_end_date = args.get("period_end_date")
    if metric == "gross_margin":
        return get_gross_margin(ticker, fiscal_year, fiscal_period, period_end_date)
    return get_metric(ticker, metric, fiscal_year, fiscal_period, period_end_date)


def _fact_as_result(fact: dict, args: dict) -> dict:
    """Wrap a get_financial_fact value in the same {text, metadata} shape
    hybrid_search results use, so it can share all_results/citation-key
    handling uniformly with search_filings results instead of needing a
    parallel code path."""
    return {
        "text": f"{args['metric']} = {fact['value']} {fact['unit']} (structured XBRL data, not filing prose)",
        "metadata": {
            "ticker": args["ticker"],
            "form": fact["form"],
            "filingDate": fact.get("filed") or fact["period_end"],
            "reportDate": fact["period_end"],
            "accessionNumber": fact["accession"],
            "chunk_index": "xbrl",
        },
    }


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
            "tools": [FACT_TOOL_SCHEMA, SEARCH_TOOL_SCHEMA],
            "stream": False,
            # Ollama defaults to a 4096-token context window regardless of
            # what the model actually supports, which is dangerously small
            # here: a single search returns up to 5 chunks (~3000 chars
            # each), so a comparison question's SECOND tool call already
            # risks silently truncating the first company's results out of
            # context before the model ever writes its final answer. Found
            # this by inspecting `ollama ps` output (context_length: 4096)
            # after a real comparison-question run behaved suspiciously —
            # worth checking before assuming a synthesis failure is a pure
            # model-capability limit rather than a truncation bug.
            "options": {"temperature": 0.1, "num_ctx": 8192},
        },
        timeout=240,
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
    searched_tickers: set[str | None] = set()

    for _ in range(MAX_TOOL_ITERATIONS):
        message = _call_ollama(messages)
        tool_calls = message.get("tool_calls") or []

        if not tool_calls:
            return message.get("content", ""), all_results

        messages.append(message)

        for call in tool_calls:
            name = call["function"]["name"]
            args = call["function"]["arguments"]

            if name == "get_financial_fact":
                if verbose:
                    print(f"  [tool call] get_financial_fact({args!r})")
                fact = _call_get_financial_fact(args)
                if fact is None:
                    content = (
                        f"(no structured data found for metric={args.get('metric')!r} "
                        f"ticker={args.get('ticker')!r} {args.get('fiscal_period')!r} "
                        f"FY{args.get('fiscal_year')!r} — try search_filings instead)"
                    )
                else:
                    start_index = len(all_results) + 1
                    result = _fact_as_result(fact, args)
                    all_results.append(result)
                    content = _format_results_block([result], start_index)
                messages.append({"role": "tool", "content": content})
                continue

            query, ticker = _resolve_search_args(
                args, fallback_query=question, searched_tickers=searched_tickers
            )
            searched_tickers.add(ticker)
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
