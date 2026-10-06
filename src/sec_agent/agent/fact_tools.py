"""
The get_financial_fact and compare_financial_metric tools: argument
checks, the XBRL and formula lookups behind them, and the result entries
their values become for the model to cite.
"""

from sec_agent.sources.formulas import (
    RATIO_DEFINITIONS,
    get_multi_year_average,
    get_ratio,
    get_ratio_all_companies,
    get_yoy_growth,
)
from sec_agent.prompts import agent_messages as msg
from sec_agent.prompts.agent_tools import COMPARE_TOOL_SCHEMA, FACT_TOOL_SCHEMA
from sec_agent.tracing import log_event, record_unmet_metric_request
from sec_agent.sources.xbrl_facts import DEFAULT_METRIC_TAGS, get_metric, get_metric_all_companies
from sec_agent.agent.tool_args import (
    is_valid_int,
    rejects_invalid_fiscal_year,
    coerce_year_args,
    validate_tool_args,
    FISCAL_YEAR_PROPS,
    COMPARE_FISCAL_YEAR_PROPS,
)
from sec_agent.agent.tool_results import with_unit


def call_get_financial_fact(args: dict, question: str | None = None) -> dict | None:
    """This is a real system boundary, not just an internal call — the
    model doesn't reliably respect the schema (e.g. it has called this
    with `metric` omitted entirely, or invented an unsupported `segment`
    filter). Validated generically by validate_tool_args at the boundary
    rather than trusting the schema was followed; this function only
    layers the business rules a flat schema check can't express. See
    docs/decisions/2026-08-19-fixing-6-accumulated-eval-findings.md and
    docs/decisions/2026-09-09-schema-driven-arg-validation.md.

    `yoy_growth=True` combined with a margin metric is rejected the same
    way: get_yoy_growth() only supports the raw tagged metrics (see its
    own docstring for why), so that combination isn't just unsupported,
    it's meaningless -- caught here rather than passed through.

    `start_fiscal_year`/`end_fiscal_year` (both required together, and
    rejected if combined with yoy_growth) dispatch to
    get_multi_year_average() instead of a single-period lookup (see that
    function's own docstring). Supported for every RATIO_DEFINITIONS
    metric -- formulas._get_annual_value() dispatches any of them
    generically (see its own docstring).

    `question` (optional -- only dispatch.py's tool-dispatch path has one;
    mcp_server.py's direct callers don't) is passed through to
    record_unmet_metric_request() purely for observability, see below.

    Records an unmet-metric-request event (see
    docs/decisions/2026-09-04-langfuse-tracing.md) when `metric` isn't
    recognized at all (reason="unknown_metric" -- the "should we add a
    formula for this" signal) or when it's a recognized metric/ratio but
    the underlying lookup -- get_metric(), get_ratio(), get_yoy_growth(),
    or get_multi_year_average(), all four genuine-data-lookup paths
    below -- found no data for this ticker/period
    (reason="no_data_for_ticker"). Deliberately NOT recorded for boundary
    rejections above (malformed/invented args, invalid yoy_growth/
    multi-year-average combinations) -- those are a schema-violation
    problem, not a "this formula doesn't exist yet" problem, and would
    just be noise on the signal."""
    args = coerce_year_args("get_financial_fact", args, FISCAL_YEAR_PROPS)
    if validate_tool_args("get_financial_fact", FACT_TOOL_SCHEMA, args, skip_properties=FISCAL_YEAR_PROPS):
        return None
    ticker = args["ticker"]
    metric = args["metric"]
    if metric not in DEFAULT_METRIC_TAGS and metric not in RATIO_DEFINITIONS:
        # A recognized-shape-but-unsupported metric name (the one
        # violation validate_tool_args deliberately lets through) --
        # this belongs on the unmet-metric-request signal, not a local-
        # only tool_call_rejected event, since it's real evidence a
        # formula might be worth adding.
        record_unmet_metric_request(ticker, metric, reason="unknown_metric", question=question)
        return None
    fiscal_period = args.get("fiscal_period", "FY")
    period_end_date = args.get("period_end_date")
    start_fiscal_year = args.get("start_fiscal_year")
    end_fiscal_year = args.get("end_fiscal_year")
    if start_fiscal_year is not None or end_fiscal_year is not None:
        # Deliberately does not check plain fiscal_year here -- this
        # branch never reads it, so a value here is irrelevant.
        return _get_financial_fact_multi_year_average(ticker, metric, args, question)
    # Checked AFTER the multi-year-average branch above: that branch
    # never reads fiscal_year at all, so checking it any earlier would
    # wrongly reject a valid multi-year-average request over a stray,
    # irrelevant fiscal_year value -- this must only gate the two
    # branches below, which are the only ones that actually use it.
    if rejects_invalid_fiscal_year("get_financial_fact", args):
        return None
    fiscal_year = args.get("fiscal_year")
    if args.get("yoy_growth"):
        return _get_financial_fact_yoy_growth(ticker, metric, args, question)
    if metric in RATIO_DEFINITIONS:
        result = get_ratio(ticker, metric, fiscal_year, fiscal_period, period_end_date)
    else:
        result = get_metric(ticker, metric, fiscal_year, fiscal_period, period_end_date)
    if result is None:
        record_unmet_metric_request(ticker, metric, reason="no_data_for_ticker", question=question)
    return result


def _get_financial_fact_multi_year_average(
    ticker: str, metric: str, args: dict, question: str | None
) -> dict | None:
    """Multi-year-average branch of call_get_financial_fact() -- pure
    relocation (no logic change) to keep the parent's own branch/return
    count under ruff's C901/PLR0911 thresholds. Re-derives
    start_fiscal_year/end_fiscal_year from `args` (like the sibling
    yoy_growth helper below re-derives its own period fields) rather
    than taking them as separate params: the parent's own guard
    condition already needs them as locals for its `is not None` check,
    but passing them AND `args.get("yoy_growth")` AND `question`
    separately would put this helper at 6 positional args, over
    PLR0913's threshold -- bundling would only trade one opaque `dict`
    for an equally-opaque ad hoc tuple with no real benefit here."""
    start_fiscal_year = args.get("start_fiscal_year")
    end_fiscal_year = args.get("end_fiscal_year")
    if args.get("yoy_growth") or not is_valid_int(start_fiscal_year) or not is_valid_int(end_fiscal_year):
        log_event("tool_call_rejected", tool="get_financial_fact", reason="invalid_multi_year_average_combo", args=args)
        return None
    result = get_multi_year_average(ticker, metric, start_fiscal_year, end_fiscal_year)
    if result is None:
        record_unmet_metric_request(ticker, metric, reason="no_data_for_ticker", question=question)
    return result


def _get_financial_fact_yoy_growth(ticker: str, metric: str, args: dict, question: str | None) -> dict | None:
    """yoy_growth branch of call_get_financial_fact() -- pure relocation
    (no logic change), same reasoning as
    _get_financial_fact_multi_year_average() above. Re-derives
    fiscal_year/fiscal_period/period_end_date from `args` rather than
    taking them as separate params (kept to 4 args, under ruff's
    PLR0913 threshold) -- identical values to the parent's own copies,
    since `args` doesn't change between reads."""
    fiscal_year = args.get("fiscal_year")
    fiscal_period = args.get("fiscal_period", "FY")
    period_end_date = args.get("period_end_date")
    if metric in RATIO_DEFINITIONS:
        log_event("tool_call_rejected", tool="get_financial_fact", reason="yoy_growth_unsupported_for_ratio", args=args)
        return None
    result = get_yoy_growth(ticker, metric, fiscal_year, fiscal_period, period_end_date)
    if result is None:
        record_unmet_metric_request(ticker, metric, reason="no_data_for_ticker", question=question)
    return result


def _format_fact_value(fact: dict) -> str:
    """Renders a fact's value for citation text, via with_unit."""
    return with_unit(fact["value"], fact["unit"])


def fact_as_result(fact: dict, args: dict) -> dict:
    """Wrap a get_financial_fact value in the same {text, metadata} shape
    hybrid_search results use, so it can share all_results/citation-key
    handling uniformly with search_filings results instead of needing a
    parallel code path."""
    return {
        "text": msg.FACT_RESULT_TEMPLATE.format(metric=args["metric"], value=_format_fact_value(fact)),
        "metadata": {
            "ticker": args["ticker"],
            "form": fact["form"],
            "filingDate": fact.get("filed") or fact["period_end"],
            "reportDate": fact["period_end"],
            "accessionNumber": fact["accession"],
            "chunk_index": "xbrl",
        },
    }


def call_compare_financial_metric(args: dict, question: str | None = None) -> dict[str, dict]:
    """Same boundary-validation reasoning as call_get_financial_fact —
    don't trust the schema was followed; validate_tool_args generically
    rejects an unrecognized extra key (e.g. an invented `segment` filter)
    rather than silently ignoring it. No yoy_growth here: there's no
    current evidence/use case for a cross-company YoY-growth comparison,
    so it isn't exposed on this tool (see get_yoy_growth()'s docstring).
    A ratio with `supports_cross_company=False` (return_on_assets/
    asset_turnover/cash_to_assets/inventory_turnover/rd_intensity) still
    passes this function's own boundary check (it's a real, known ratio
    name -- COMPARE_TOOL_SCHEMA's own metric enum is narrower, only
    prompts.agent_system.CROSS_COMPANY_RATIOS, but validate_tool_args
    lets any metric-enum violation through regardless of which schema
    declared it, deferring to this same broader RATIO_DEFINITIONS
    check), but get_ratio_all_companies() checks the flag internally
    and returns the same graceful `{}` any other unsupported metric
    gets -- see RATIO_DEFINITIONS' own comment for why there's no
    cross-company version of those five yet.

    Same unmet-metric-request tracing as call_get_financial_fact -- see
    that function's docstring. The
    `supports_cross_company=False` case above also lands in the generic
    `reason="no_data_for_ticker"` bucket rather than a third reason
    value: a human looking at the metric name in the Langfuse dashboard
    can already tell that case apart, not worth the extra complexity."""
    args = coerce_year_args("compare_financial_metric", args, COMPARE_FISCAL_YEAR_PROPS)
    if validate_tool_args(
        "compare_financial_metric", COMPARE_TOOL_SCHEMA, args, skip_properties=COMPARE_FISCAL_YEAR_PROPS
    ):
        return {}
    anchor_ticker = args["anchor_ticker"]
    metric = args["metric"]
    if metric not in DEFAULT_METRIC_TAGS and metric not in RATIO_DEFINITIONS:
        # See call_get_financial_fact's matching guard: a recognized-
        # shape-but-unsupported metric name belongs on the unmet-metric-
        # request signal, not a local-only tool_call_rejected event.
        record_unmet_metric_request(anchor_ticker, metric, reason="unknown_metric", question=question)
        return {}
    if rejects_invalid_fiscal_year("compare_financial_metric", args):
        return {}
    fiscal_year = args.get("fiscal_year")
    fiscal_period = args.get("fiscal_period", "FY")
    period_end_date = args.get("period_end_date")
    if metric in RATIO_DEFINITIONS:
        result = get_ratio_all_companies(anchor_ticker, metric, fiscal_year, fiscal_period, period_end_date)
    else:
        result = get_metric_all_companies(anchor_ticker, metric, fiscal_year, fiscal_period, period_end_date)
    # anchor_ticker not in result (not just `not result`) matters:
    # instant metrics resolve each company independently with no
    # requirement that the requested anchor itself has data (e.g. PLTR
    # doesn't tag inventory but AAPL/MSFT do) -- a non-empty-but-anchor-
    # missing result must still record that the specific company asked
    # about has no data, even though everyone else's data is genuinely
    # returned. See
    # docs/decisions/2026-09-07-fix-get-metric-all-companies-instant-metrics.md.
    if not result or anchor_ticker not in result:
        record_unmet_metric_request(anchor_ticker, metric, reason="no_data_for_ticker", question=question)
    return result


def comparison_as_results(data: dict[str, dict], metric: str) -> list[dict]:
    """Wrap a {ticker: fact} dict (from compare_financial_metric) as a
    list of {text, metadata} results, one per company, reusing the same
    shape fact_as_result uses for a single company. A frames entry
    (duration metrics) doesn't carry a "form" field — "XBRL frame data"
    stands in for it rather than guessing 10-K vs. 10-Q. Instant metrics
    resolve independently per company via get_metric(), which DOES carry
    a real form — used when present via fact.get(...) instead of always
    hardcoding the frame fallback label. See
    docs/decisions/2026-09-07-fix-get-metric-all-companies-instant-metrics.md."""
    results = []
    for ticker, fact in sorted(data.items()):
        results.append(
            {
                "text": msg.COMPARISON_RESULT_TEMPLATE.format(
                    ticker=ticker, metric=metric, value=_format_fact_value(fact)
                ),
                "metadata": {
                    "ticker": ticker,
                    "form": fact.get("form", msg.COMPARISON_FRAME_FORM),
                    "filingDate": fact["period_end"],
                    "reportDate": fact["period_end"],
                    "accessionNumber": fact["accession"],
                    "chunk_index": "xbrl",
                },
            }
        )
    return results
