"""
Text the model receives back from its tools: the numbered citation header
and results block for retrieved sources and the no-data messages for fact
and comparison lookups, the CLI's printed citation key, and the shared
value-with-unit rendering used in citation text.
"""

from sec_agent.sources.companies import COMPANIES
from sec_agent.prompts import agent_messages as msg
from sec_agent.sources.xbrl_facts import DEFAULT_METRIC_TAGS, is_metric_tagged


def with_unit(value: float | int | str, unit: str) -> str:
    """Renders a value with its unit for citation text. "raw" (the unit for
    any RATIO_DEFINITIONS entry with as_percent=False, e.g. asset_turnover/
    inventory_turnover) is an internal normalize()-category label from
    numeric_utils.py, not a natural-language unit -- omitted here so a
    plain ratio reads as "1.04", not the internal-sounding "1.04 raw"."""
    if unit == "raw":
        return str(value)
    return msg.VALUE_WITH_UNIT_TEMPLATE.format(value=value, unit=unit)


def citation_header(i: int, meta: dict) -> str:
    """The exact citation header text format_results_block() shows the
    model above result [i]'s own text. Shared with
    citations._strip_citation_header() so the two can never independently
    drift out of sync if this format ever changes -- the strip has to
    reconstruct precisely what the model was actually shown, not a
    close guess."""
    return msg.CITATION_HEADER_TEMPLATE.format(
        i=i, ticker=meta["ticker"], form=meta["form"], report_date=meta["reportDate"]
    )


def format_results_block(results: list[dict], start_index: int) -> str:
    """Format one search call's results as numbered excerpts, continuing
    the numbering from start_index rather than restarting at [1] — so
    citation numbers stay globally consistent across multiple tool calls
    within the same conversation."""
    if not results:
        return msg.NO_SEARCH_RESULTS_MESSAGE

    blocks = []
    for offset, r in enumerate(results):
        i = start_index + offset
        header = citation_header(i, r["metadata"])
        blocks.append(msg.RESULT_BLOCK_TEMPLATE.format(header=header, text=r["text"]))
    return msg.RESULT_BLOCK_SEPARATOR.join(blocks)


def _never_tagged_hint(ticker: object, metric: object) -> str | None:
    """None unless `ticker` genuinely never tags `metric` at all (as
    opposed to just not having it for the specific period asked about)
    -- see xbrl_facts.is_metric_tagged()'s own docstring. Scoped to raw
    DEFAULT_METRIC_TAGS metrics only: is_metric_tagged()/_tag_for() only
    understand those names, and would raise for a margin metric name
    like "gross_margin" (not itself a GAAP tag) rather than telling us
    anything meaningful about it."""
    # The type check comes first: a list from a malformed call is
    # unhashable and would raise on the membership test.
    if not (isinstance(ticker, str) and isinstance(metric, str)):
        return None
    if metric not in DEFAULT_METRIC_TAGS or ticker not in COMPANIES:
        return None
    if is_metric_tagged(ticker, metric):
        return None
    return msg.NEVER_TAGGED_HINT_TEMPLATE.format(ticker=ticker, metric=metric)


def _no_fact_period(args: dict) -> str:
    """The period call_get_financial_fact's lookup used (or, for a
    rejected call, the period arguments it was sent), so the no-data reply
    names it instead of echoing absent arguments. The branch order must
    mirror call_get_financial_fact and xbrl_facts.get_metric; nothing
    else keeps the two in step."""
    start, end = args.get("start_fiscal_year"), args.get("end_fiscal_year")
    if start is not None or end is not None:
        # A missing side renders as None: that is what was sent, and why
        # the call was rejected.
        return msg.NO_FACT_PERIOD_MULTI_YEAR.format(start=start, end=end)
    # Truthy, not "is not None": get_metric treats an empty date as absent.
    if args.get("period_end_date"):
        return msg.NO_FACT_PERIOD_END_DATE.format(date=args["period_end_date"])
    if args.get("fiscal_year") is not None:
        return msg.NO_FACT_PERIOD_FISCAL.format(
            fiscal_period=args.get("fiscal_period", "FY"),
            fiscal_year=args["fiscal_year"],
        )
    return msg.NO_FACT_PERIOD_LATEST


def format_no_fact_message(args: dict) -> str:
    """Kept separate from the call site so the hints are unit-testable
    without a model round-trip. Both hints exist because a bare "not
    found" leaves the model unaware WHY data is missing, and it then
    trusts noisy search results and fabricates instead of refusing."""
    message = msg.NO_FACT_TEMPLATE.format(
        metric=args.get("metric"),
        ticker=args.get("ticker"),
        period=_no_fact_period(args),
    )
    if args.get("fiscal_period") == "Q4":
        message += msg.NO_DATA_HINT_SEPARATOR + msg.Q4_NOT_DISCLOSED_HINT
    never_tagged = _never_tagged_hint(args.get("ticker"), args.get("metric"))
    if never_tagged:
        message += msg.NO_DATA_HINT_SEPARATOR + never_tagged
    return message


def format_no_comparison_message(args: dict) -> str:
    """compare_financial_metric counterpart to format_no_fact_message --
    the same Q4 reporting gap and never-tagged-concept gap both apply
    just as much to a cross-company comparison question as to a
    single-company one. The never-tagged hint only reflects the anchor
    company (args' `anchor_ticker`, this tool's ticker key), not every
    company in the comparison -- same scoping limit _never_tagged_hint()
    itself already documents, not a new one introduced here."""
    message = msg.NO_COMPARISON_TEMPLATE.format(metric=args.get("metric"))
    if args.get("fiscal_period") == "Q4":
        message += msg.NO_DATA_HINT_SEPARATOR + msg.Q4_NOT_DISCLOSED_HINT
    never_tagged = _never_tagged_hint(args.get("anchor_ticker"), args.get("metric"))
    if never_tagged:
        message += msg.NO_DATA_HINT_SEPARATOR + never_tagged
    return message


def format_citation_key(all_results: list[dict]) -> str:
    lines = []
    for i, r in enumerate(all_results, start=1):
        meta = r["metadata"]
        lines.append(
            f"  [{i}] {meta['ticker']} {meta['form']} filed {meta['filingDate']} "
            f"(reportDate={meta['reportDate']}, accession={meta['accessionNumber']}, "
            f"chunk={meta['chunk_index']})"
        )
    return "\n".join(lines)
