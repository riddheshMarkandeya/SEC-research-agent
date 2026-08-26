"""
Week 6 — MCP server: expose search_filings/get_financial_fact/
compare_financial_metric over Streamable HTTP
-------------------------------------------------------------
Wraps the same three tools agent.py's own tool-calling loop uses, so
any MCP client (Claude Desktop, Claude Code, another agent) can call
this project's retrieval/XBRL tooling directly. Deliberately reuses
agent.py's tool-dispatch logic (call_get_financial_fact/
call_compare_financial_metric) and tool schemas (SEARCH_TOOL_SCHEMA/
FACT_TOOL_SCHEMA/COMPARE_TOOL_SCHEMA) rather than reimplementing either
-- those already carry boundary validation and real-failure-tuned
descriptions hardened over several rounds; a second copy would drift.

Every tool result carries an always-present `source` block (ticker,
form, period, accession, and a real sec_url) rather than gating it
behind an opt-in flag -- matches how every reference information/search
MCP server behaves (e.g. brave-search's own results always include the
URL): a fact a caller can't trace back to a filing isn't very useful to
an LLM that needs to cite it. search_filings citations additionally get
a browser-native "Scroll To Text Fragment" (`#:~:text=`) anchor so a
human clicking through lands on the cited sentence, not just the top of
a 100+ page filing -- not attempted for get_financial_fact/
compare_financial_metric, since those come from structured XBRL data
with no prose position to anchor to.

Uses the low-level mcp.server.Server API (not FastMCP) specifically so
tool schemas can be supplied as plain JSON Schema dicts -- reusing
agent.py's existing schemas directly -- rather than FastMCP's default
of deriving a schema from Python type hints, which would mean
maintaining the tool descriptions twice.

Usage:
    python mcp_server.py --port 8765
"""

import json
from urllib.parse import quote

import click
import mcp.types as types
import uvicorn
from mcp.server import Server

from agent import (
    CHUNKS_PER_SEARCH,
    COMPARE_TOOL_SCHEMA,
    FACT_TOOL_SCHEMA,
    SEARCH_TOOL_SCHEMA,
    call_compare_financial_metric,
    call_get_financial_fact,
)
from edgar_ingest import get_filing_url
from retrieval import hybrid_search

TEXT_FRAGMENT_EXCERPT_MAX_LEN = 100


def _text_fragment_excerpt(text: str, max_len: int = TEXT_FRAGMENT_EXCERPT_MAX_LEN) -> str | None:
    """A short, word-boundary-truncated prefix of `text` to use as a
    `#:~:text=` fragment target, or None if no usable excerpt exists.

    Deliberately NOT "the first sentence" -- these are financial filings
    full of numbers like "$72.4 billion", so a period-based
    sentence-splitter would frequently cut mid-number. A fixed-length
    prefix sidesteps that entirely.

    Checks the EXCERPT itself for a `<TABLE>` marker, not whether the
    whole chunk contains one anywhere -- chunk_documents.py's
    `contains_table` flag is true for any chunk with a table ANYWHERE in
    it, which would wrongly suppress the fragment for a mostly-prose
    chunk whose table appears later, past where the excerpt is taken
    from."""
    text = text.strip()
    if not text:
        return None
    excerpt = text[:max_len]
    if len(text) > max_len:
        last_space = excerpt.rfind(" ")
        if last_space > 0:
            excerpt = excerpt[:last_space]
    if "<TABLE>" in excerpt:
        return None
    return excerpt


def _chunk_source(metadata: dict, text: str) -> dict:
    """Source block for one search_filings chunk result. `sec_url` is
    omitted entirely (not included as None) if this filing was never
    ingested -- shouldn't normally happen, but get_filing_url() already
    returns None gracefully for that case rather than raising."""
    source = {
        "ticker": metadata["ticker"],
        "form": metadata["form"],
        "reportDate": metadata["reportDate"],
        "filingDate": metadata["filingDate"],
        "accessionNumber": metadata["accessionNumber"],
    }
    base_url = get_filing_url(metadata["ticker"], metadata["accessionNumber"])
    if base_url:
        excerpt = _text_fragment_excerpt(text)
        source["sec_url"] = f"{base_url}#:~:text={quote(excerpt, safe='')}" if excerpt else base_url
    return source


def _fact_source(ticker: str, fact: dict) -> dict:
    """Source block for one get_financial_fact/compare_financial_metric
    value. `form`/`filed` are only included when present -- the
    cross-company facts compare_financial_metric returns (via
    xbrl_facts.get_frame()) carry no form/filed, only value/unit/
    period_end/accession, so this can't assume every fact has them."""
    source = {"ticker": ticker, "period_end": fact["period_end"], "accession": fact["accession"]}
    if "form" in fact:
        source["form"] = fact["form"]
    if "filed" in fact:
        source["filed"] = fact["filed"]
    url = get_filing_url(ticker, fact["accession"])
    if url:
        source["sec_url"] = url
    return source


def _search_filings(args: dict) -> list[dict]:
    query = args.get("query")
    if not query:
        return []
    results = hybrid_search(query, ticker=args.get("ticker"), top_k=CHUNKS_PER_SEARCH)
    return [{"text": r["text"], "source": _chunk_source(r["metadata"], r["text"])} for r in results]


def _get_financial_fact(args: dict) -> dict:
    fact = call_get_financial_fact(args)
    if fact is None:
        return {"error": "not available for this company/metric/period"}
    return {"value": fact["value"], "unit": fact["unit"], "source": _fact_source(args["ticker"], fact)}


def _compare_financial_metric(args: dict) -> dict:
    data = call_compare_financial_metric(args)
    if not data:
        return {"error": "not available for this metric/period"}
    return {
        ticker: {"value": fact["value"], "unit": fact["unit"], "source": _fact_source(ticker, fact)}
        for ticker, fact in data.items()
    }


_TOOL_HANDLERS = {
    "search_filings": _search_filings,
    "get_financial_fact": _get_financial_fact,
    "compare_financial_metric": _compare_financial_metric,
}

_TOOL_SCHEMAS = (SEARCH_TOOL_SCHEMA, FACT_TOOL_SCHEMA, COMPARE_TOOL_SCHEMA)


async def _handle_list_tools(ctx, params) -> types.ListToolsResult:
    return types.ListToolsResult(
        tools=[
            types.Tool(
                name=schema["function"]["name"],
                description=schema["function"]["description"],
                input_schema=schema["function"]["parameters"],
            )
            for schema in _TOOL_SCHEMAS
        ]
    )


async def _handle_call_tool(ctx, params: types.CallToolRequestParams) -> types.CallToolResult:
    handler = _TOOL_HANDLERS.get(params.name)
    if handler is None:
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=f"Unknown tool: {params.name!r}")],
            is_error=True,
        )
    result = handler(params.arguments or {})
    return types.CallToolResult(content=[types.TextContent(type="text", text=json.dumps(result))])


def build_app(host: str = "127.0.0.1"):
    """Returns a standard ASGI (Starlette) app -- stateless_http=True
    since every tool call here is independent, with no need for
    session state across requests. Kept as its own standalone app for
    now (not mounted into a larger one), but streamable_http_app()'s
    return value is composable, so a future web UI's non-MCP routes
    (e.g. a /chat endpoint calling agent.run_agent()) can be mounted
    alongside this at that point instead of needing a redesign."""
    server = Server("sec-research-agent", on_list_tools=_handle_list_tools, on_call_tool=_handle_call_tool)
    return server.streamable_http_app(stateless_http=True, host=host)


@click.command()
@click.option("--host", default="127.0.0.1", help="Host to bind to")
@click.option("--port", default=8765, help="Port to listen on for HTTP")
def main(host: str, port: int):
    uvicorn.run(build_app(host=host), host=host, port=port)


if __name__ == "__main__":
    main()
