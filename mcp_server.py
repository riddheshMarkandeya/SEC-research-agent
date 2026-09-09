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
import math
import secrets
import time
from urllib.parse import quote

import click
import mcp.types as types
import uvicorn
from mcp.server import Server
from starlette.responses import JSONResponse

from agent import (
    CHUNKS_PER_SEARCH,
    COMPARE_TOOL_SCHEMA,
    FACT_TOOL_SCHEMA,
    SEARCH_TOOL_SCHEMA,
    call_compare_financial_metric,
    call_get_financial_fact,
    validate_tool_args,
)
from config import MCP_AUTH_TOKEN, MCP_RATE_LIMIT_REQUESTS, MCP_RATE_LIMIT_WINDOW_SECONDS
from edgar_ingest import get_filing_url
from retrieval import hybrid_search
from tracing import flush, log_event, traced_span

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
    value. `form`/`filed` are only included when present -- not every
    fact shape has them: compare_financial_metric's duration-metric
    facts (via xbrl_facts.get_frame()) carry neither, only value/unit/
    period_end/accession; its instant-metric facts (total_assets etc.,
    2026-09-07 redesign, via plain get_metric() per company) DO carry
    both, same as a single-company get_financial_fact result."""
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
    """Unlike get_financial_fact/compare_financial_metric above (which
    inherit boundary validation for free by delegating into agent.py's
    already-validated call_get_financial_fact/call_compare_financial_metric),
    this handler builds its result directly from hybrid_search() with no
    such delegation -- so it never got the same validation an MCP client
    could bypass entirely (a hallucinated ticker used to fall through to
    hybrid_search with no rejection, unlike the agent.py dispatch path,
    found during the 2026-09-09 schema-validator redesign). Uses the same
    generic validate_tool_args() agent.py's own search_filings dispatch
    branch does, against the same SEARCH_TOOL_SCHEMA, so both entry
    points enforce identical rules from one source of truth. soft_required
    -- query is schema-required but the empty-query case below has always
    just returned [] rather than erroring, so a missing query still isn't
    a hard rejection here either."""
    with traced_span("tool", "search_filings", input=args) as span:
        if validate_tool_args("search_filings", SEARCH_TOOL_SCHEMA, args, soft_required=frozenset({"query"})):
            span.update(output={"found": False, "rejected": True})
            return []
        query = args.get("query")
        if not query:
            return []
        results = hybrid_search(query, ticker=args.get("ticker"), top_k=CHUNKS_PER_SEARCH)
        span.update(output={"result_count": len(results)})
        return [{"text": r["text"], "source": _chunk_source(r["metadata"], r["text"])} for r in results]


def _get_financial_fact(args: dict) -> dict:
    # call_get_financial_fact() records its own unmet-metric-request
    # event internally (no `question` here -- MCP tool calls carry no
    # free-text question) -- this span is just the general tool-call
    # trace, same as agent.py's _dispatch_tool_call.
    with traced_span("tool", "get_financial_fact", input=args) as span:
        fact = call_get_financial_fact(args)
        if fact is None:
            span.update(output={"found": False})
            return {"error": "not available for this company/metric/period"}
        span.update(output={"found": True, "value": fact.get("value")})
        return {"value": fact["value"], "unit": fact["unit"], "source": _fact_source(args["ticker"], fact)}


def _compare_financial_metric(args: dict) -> dict:
    with traced_span("tool", "compare_financial_metric", input=args) as span:
        data = call_compare_financial_metric(args)
        if not data:
            span.update(output={"found": False})
            return {"error": "not available for this metric/period"}
        span.update(output={"found": True, "companies": sorted(data)})
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


def _is_authorized(auth_header: str | None, expected_token: str) -> bool:
    """expected_token == "" means auth is disabled (opt-in, matches
    every other .env-optional setting in this project -- see
    config.py's MCP_AUTH_TOKEN). Uses a constant-time comparison since
    this gates a network-reachable server -- a plain `==` short-circuits
    on the first mismatched character, letting a remote attacker recover
    the token byte-by-byte via response-timing measurements instead of
    needing the whole secret at once. Found in code review."""
    if not expected_token:
        return True
    if auth_header is None:
        return False
    return secrets.compare_digest(auth_header, f"Bearer {expected_token}")


class _RateLimiter:
    """Fixed-window request counter per key, in-memory -- fine since
    mcp_server.py always runs as a single uvicorn process (no
    `workers=`, see main() below), so there's no cross-process state to
    coordinate. `now` is passed in explicitly rather than read from
    time.time() internally so it stays pure/deterministic and testable
    without real sleeps."""

    def __init__(self, max_requests: int, window_seconds: float):
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._windows: dict[str, tuple[float, int]] = {}

    def allow(self, key: str, now: float) -> bool:
        if self._max_requests <= 0:
            return True
        # Prune every expired key, not just `key` -- with the no-auth
        # default (rate-limit key = client IP), a long-running server
        # would otherwise keep one entry per distinct caller forever,
        # even after that caller's window expired and it never
        # reconnects. Found in code review.
        self._windows = {k: v for k, v in self._windows.items() if now - v[0] < self._window_seconds}
        window_start, count = self._windows.get(key, (now, 0))
        if count >= self._max_requests:
            self._windows[key] = (window_start, count)
            return False
        self._windows[key] = (window_start, count + 1)
        return True


_rate_limiter = _RateLimiter(MCP_RATE_LIMIT_REQUESTS, MCP_RATE_LIMIT_WINDOW_SECONDS)


class _AuthRateLimitMiddleware:
    """Plain ASGI middleware (not Starlette's BaseHTTPMiddleware, which
    is documented to interfere with streaming responses and
    client-disconnect propagation -- a real risk on top of
    streamable_http_app()'s SSE-based transport).

    Rate limiting runs BEFORE auth, keyed by client IP rather than the
    shared token. Originally built the other way around (auth first,
    keyed by token when auth is enabled) -- code review caught two real
    problems with that: (1) a rejected (401) request never touched the
    rate limiter at all, so credential-guessing traffic against
    MCP_AUTH_TOKEN was completely unthrottled; (2) keying by the one
    shared token meant every legitimate caller using it drew from a
    single global budget, so one noisy caller could lock out every
    other one. Keying by IP and checking first fixes both: guessing
    traffic from one IP gets throttled regardless of whether any guess
    is ever correct, and separate legitimate callers (different IPs)
    no longer share a budget."""

    def __init__(self, app):
        self._app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self._app(scope, receive, send)

        client = scope.get("client")
        key = client[0] if client else "unknown"
        if not _rate_limiter.allow(key, time.time()):
            # Local-only debug event (Week 7 follow-up) -- lets someone
            # exposing this server audit "who's getting rejected" after
            # the fact; not sent to Langfuse (no traced_span is open at
            # this point anyway -- this runs before any tool dispatch).
            log_event("rate_limited", client_ip=key)
            response = JSONResponse(
                {"error": "rate limit exceeded"},
                status_code=429,
                headers={"Retry-After": str(math.ceil(MCP_RATE_LIMIT_WINDOW_SECONDS))},
            )
            return await response(scope, receive, send)

        headers = dict(scope.get("headers") or [])
        auth_header = headers.get(b"authorization")
        auth_header = auth_header.decode("latin-1") if auth_header is not None else None

        if not _is_authorized(auth_header, MCP_AUTH_TOKEN):
            log_event("auth_rejected", client_ip=key)
            response = JSONResponse({"error": "unauthorized"}, status_code=401)
            return await response(scope, receive, send)

        return await self._app(scope, receive, send)


def build_app(host: str = "127.0.0.1"):
    """Returns a standard ASGI (Starlette) app -- stateless_http=True
    since every tool call here is independent, with no need for
    session state across requests. Kept as its own standalone app for
    now (not mounted into a larger one), but streamable_http_app()'s
    return value is composable, so a future web UI's non-MCP routes
    (e.g. a /chat endpoint calling agent.run_agent()) can be mounted
    alongside this at that point instead of needing a redesign."""
    server = Server("sec-research-agent", on_list_tools=_handle_list_tools, on_call_tool=_handle_call_tool)
    app = server.streamable_http_app(stateless_http=True, host=host)
    app.add_middleware(_AuthRateLimitMiddleware)
    return app


@click.command()
@click.option("--host", default="127.0.0.1", help="Host to bind to")
@click.option("--port", default=8765, help="Port to listen on for HTTP")
def main(host: str, port: int):
    # uvicorn.run() returns normally (no exception) on both SIGINT and
    # SIGTERM, so `finally` here flushes Langfuse on every real shutdown,
    # not just uncaught errors -- see PROJECT_CONTEXT.md's 2026-09-10
    # section for why this is `finally` and not a Starlette lifespan hook.
    try:
        uvicorn.run(build_app(host=host), host=host, port=port)
    finally:
        flush()


if __name__ == "__main__":
    main()
