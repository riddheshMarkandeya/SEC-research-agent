"""
Tool-call dispatch: routes each model tool call to its tool, appends what
it returns to the run's numbered sources, and returns the text the model
sees. Also owns search_filings (run_search over hybrid_search).
"""

from sec_agent.sources.companies import COMPANIES
from sec_agent.prompts import agent_messages as msg
from sec_agent.prompts.agent_tools import SEARCH_TOOL_SCHEMA
from sec_agent.retrieval.retrieval import hybrid_search
from sec_agent.tracing import traced_span
from sec_agent.agent.calculate import (
    call_calculate,
    calculation_as_result,
)
from sec_agent.agent.fact_tools import (
    call_get_financial_fact,
    fact_as_result,
    call_compare_financial_metric,
    comparison_as_results,
)
from sec_agent.agent.tool_args import (
    coerce_year_args,
    validate_tool_args,
    FISCAL_YEAR_PROPS,
)
from sec_agent.agent.tool_results import (
    format_results_block,
    format_no_fact_message,
    format_no_comparison_message,
)


CHUNKS_PER_SEARCH = 5


def _resolve_search_args(
    args: dict, fallback_query: str, searched_tickers: set[str | None]
) -> tuple[str, str | None]:
    """Extract (query, ticker) from a tool call's arguments.

    The model doesn't always include every schema-declared argument —
    observed in testing: it sometimes calls search_filings with only
    `ticker` and no `query`, despite `query` being marked required.

    The model's own `query` text is only trusted on a *retry* against a
    ticker already searched earlier in this conversation
    (`searched_tickers`) -- a deliberate refinement, not a first guess.
    The first search against each company always uses the original
    question verbatim instead, since the model's own first-pass queries
    are unreliable and no single query-phrasing instruction generalizes
    across companies. See docs/decisions/2026-08-14-agent-v0-tool-calling.md."""
    ticker = args.get("ticker")
    if ticker not in searched_tickers:
        return fallback_query, ticker
    return args.get("query") or fallback_query, ticker


def dispatch_tool_call(
    call: dict, question: str, all_results: list[dict], searched_tickers: set[str | None], verbose: bool
) -> str:
    """Runs one normalized tool call ({"name", "args"} -- the
    ModelTurn.tool_calls shape from llm_backends.py) against the right
    tool, mutating all_results/searched_tickers in place, and returns
    the content string to send back to the model. Backend-agnostic by
    construction: it only ever sees the normalized shape, never a
    backend's raw wire format, so the boundary validation inside
    call_get_financial_fact/call_compare_financial_metric (e.g.
    rejecting an invented `segment` argument) protects every backend
    without a second copy."""
    name, args = call["name"], call["args"]

    if name == "get_financial_fact":
        return _dispatch_get_financial_fact(name, args, question, all_results, verbose)
    if name == "compare_financial_metric":
        return _dispatch_compare_financial_metric(name, args, question, all_results, verbose)
    if name == "calculate":
        return _dispatch_calculate(name, args, all_results, verbose)
    return _dispatch_search_filings(call, question, all_results, searched_tickers, verbose)


def _dispatch_get_financial_fact(name: str, args: dict, question: str, all_results: list[dict], verbose: bool) -> str:
    """get_financial_fact branch body of dispatch_tool_call() -- pure
    relocation (no logic change), extracted to keep the parent's own
    branch/return count under ruff's C901/PLR0911 thresholds. Takes
    `name`/`args` directly (the parent already has both split out) --
    at 5 params this doesn't need the whole-`call`-dict trick
    _dispatch_search_filings below uses, since that one alone needs a
    6th param (searched_tickers)."""
    if verbose:
        print(f"  [tool call] get_financial_fact({args!r})")
    with traced_span("tool", name, input=args) as span:
        # Converted here too, not only inside call_get_financial_fact, so
        # the no-data reply names the year the lookup actually used.
        args = coerce_year_args(name, args, FISCAL_YEAR_PROPS)
        fact = call_get_financial_fact(args, question=question)
        if fact is None:
            span.update(output={"found": False})
            return format_no_fact_message(args)
        start_index = len(all_results) + 1
        result = fact_as_result(fact, args)
        all_results.append(result)
        span.update(output={"found": True, "value": fact.get("value")})
        return format_results_block([result], start_index)


def _dispatch_compare_financial_metric(
    name: str, args: dict, question: str, all_results: list[dict], verbose: bool
) -> str:
    """compare_financial_metric branch body of dispatch_tool_call() --
    same reasoning as _dispatch_get_financial_fact() above."""
    if verbose:
        print(f"  [tool call] compare_financial_metric({args!r})")
    with traced_span("tool", name, input=args) as span:
        data = call_compare_financial_metric(args, question=question)
        if not data:
            span.update(output={"found": False})
            return format_no_comparison_message(args)
        start_index = len(all_results) + 1
        results = comparison_as_results(data, args.get("metric", ""))
        all_results.extend(results)
        span.update(output={"found": True, "companies": sorted(data)})
        return format_results_block(results, start_index)


def _dispatch_calculate(name: str, args: dict, all_results: list[dict], verbose: bool) -> str:
    """calculate branch body of dispatch_tool_call() -- same reasoning
    as _dispatch_get_financial_fact() above."""
    if verbose:
        print(f"  [tool call] calculate({args!r})")
    with traced_span("tool", name, input=args) as span:
        calc_result, error = call_calculate(args, all_results)
        if calc_result is None:
            assert error is not None  # call_calculate's contract: exactly one of the two is None
            span.update(output={"found": False, "error": error})
            return error
        start_index = len(all_results) + 1
        result = calculation_as_result(calc_result, args)
        all_results.append(result)
        span.update(output={"found": True, "value": calc_result.get("value")})
        return format_results_block([result], start_index)


def _dispatch_search_filings(
    call: dict, question: str, all_results: list[dict], searched_tickers: set[str | None], verbose: bool
) -> str:
    """search_filings branch body of dispatch_tool_call() -- same
    reasoning as _dispatch_get_financial_fact() above; also absorbs the
    validate_tool_args/ticker-rejection guard this branch runs first.
    Unlike its three siblings, takes the whole `call` dict rather than
    `name`/`args` split out -- this branch alone needs `searched_tickers`
    too, which would put a split signature at 6 positional args, over
    PLR0913's threshold.

    soft_required={"query"}: query is schema-required (encourages the
    model to include it), but _resolve_search_args above tolerates it
    being absent by substituting the original question -- observed
    live, not a bug (see that function's own docstring) -- so a
    missing query must not be a hard rejection here.

    Checked BEFORE _resolve_search_args() runs, not after -- that
    function's own `ticker not in searched_tickers` (a set) would
    crash on a non-hashable ticker like a list, the exact unhashable-
    ticker crash class validate_tool_args is safe against (jsonschema's
    type/enum checks use plain equality, never hashing the instance)."""
    name, args = call["name"], call["args"]
    if validate_tool_args("search_filings", SEARCH_TOOL_SCHEMA, args, soft_required=frozenset({"query"})):
        raw_ticker = args.get("ticker")
        if raw_ticker is not None and (not isinstance(raw_ticker, str) or raw_ticker not in COMPANIES):
            # A hallucinated ticker gets its own actionable message
            # (names the bad value, lists valid ones) rather than a
            # generic one -- unlike get_financial_fact/
            # compare_financial_metric's boundary rejections, this is
            # the one case validate_tool_args's caller has enough
            # schema/enum context in hand to do that cheaply.
            return msg.SEARCH_INVALID_TICKER_TEMPLATE.format(ticker=raw_ticker, valid_tickers=sorted(COMPANIES))
        return msg.SEARCH_INVALID_ARGS_MESSAGE
    query, ticker = _resolve_search_args(args, fallback_query=question, searched_tickers=searched_tickers)
    searched_tickers.add(ticker)
    if verbose:
        print(f"  [tool call] search_filings(query={query!r}, ticker={ticker!r})")
    with traced_span("tool", name, input={"query": query, "ticker": ticker}) as span:
        content, result_count = run_search(query, ticker, all_results)
        span.update(output={"result_count": result_count})
        return content


def run_search(query: str, ticker: str | None, all_results: list[dict]) -> tuple[str, int]:
    """Runs one already-validated, already-resolved search, appends its
    chunks to `all_results`, and returns the content block the model
    receives plus the chunk count. Public so an offline replay of a
    traced run, which has only the resolved query/ticker, rebuilds
    exactly what the live dispatch built."""
    results = hybrid_search(query, ticker=ticker, top_k=CHUNKS_PER_SEARCH)
    start_index = len(all_results) + 1
    all_results.extend(results)
    return format_results_block(results, start_index), len(results)
