"""
Formula registry -- every tool-computed derived metric (margins, YoY
growth, multi-year averages) lives here, separate from xbrl_facts.py's
raw-fact fetching. See
docs/decisions/2026-08-18-formulas-module-split.md.

None of these are themselves GAAP-tagged concepts (percentages/growth
rates are prose/MD&A, not structured facts) -- each is computed here
from two or more raw XBRL facts instead of returned raw for the model
to divide, so agent.py's "don't infer/combine numbers" rule doesn't
need to be relaxed for any of their output.

Usage:
    from formulas import get_gross_margin, get_yoy_growth
    get_gross_margin("NVDA", fiscal_year=2026, fiscal_period="FY")
    get_yoy_growth("AAPL", "revenue", period_end_date="2026-06-27")
"""

from typing import NamedTuple

from xbrl_facts import get_frame, get_metric

# Bundles the 3 period-selector args every get_metric() call takes
# together, purely so _compute_ratio_metric() (called from exactly one
# place, get_ratio() below) can pass them as one argument instead of
# three -- NOT a change to get_metric()'s own public signature, which
# stays as three separate positional args everywhere else in this
# codebase (a much larger, unwarranted-here change).
_Period = NamedTuple(
    "_Period", [("fiscal_year", int | None), ("fiscal_period", str), ("period_end_date", str | None)]
)


def _compute_ratio_metric(
    ticker: str,
    numerator_metric: str,
    denominator_metric: str,
    period: _Period,
    as_percent: bool = True,
) -> dict | None:
    """Shared body for gross/operating/net margin, and the return-on-
    assets/asset-turnover/cash-to-assets ratios added since -- all are
    otherwise-identical bodies differing only in which metric is the
    numerator.

    Both legs are just handed the same period (fiscal_year/
    fiscal_period/period_end_date, bundled as one _Period) and each
    resolves its own entry via get_metric() independently -- the
    period_end check below is what actually guarantees both legs agree,
    regardless of how each one got there. This also means either leg
    can be an XBRL "instant" (point-in-time balance, e.g. total_assets)
    or "duration" (income-statement) concept, or one of each --
    get_metric() already normalizes both shapes to the same {"value",
    "period_end", ...} dict, so nothing here needs to know or care which
    kind either metric is.

    `as_percent=False` (asset_turnover's case) skips the *100 and
    reports `unit: "raw"` instead of `"percent"`, rounded to 2 decimals
    instead of 1 -- numeric_utils.normalize() treats "percent" and "raw"
    as non-matching categories, so getting this wrong silently breaks
    eval grading. See
    docs/decisions/2026-08-25-formula-registry-roa-turnover-cash.md."""
    numerator = get_metric(ticker, numerator_metric, period.fiscal_year, period.fiscal_period, period.period_end_date)
    denominator = get_metric(
        ticker, denominator_metric, period.fiscal_year, period.fiscal_period, period.period_end_date
    )
    if numerator is None or denominator is None:
        return None
    if numerator["period_end"] != denominator["period_end"]:
        return None
    if denominator["value"] == 0:
        return None
    ratio = numerator["value"] / denominator["value"]
    value = round(ratio * 100, 1) if as_percent else round(ratio, 2)
    return {
        "value": value,
        "unit": "percent" if as_percent else "raw",
        "period_end": numerator["period_end"],
        "form": numerator["form"],
        "accession": numerator["accession"],
        "filed": numerator["filed"],
        "frame": numerator["frame"],
    }


RatioDefinition = NamedTuple(
    "RatioDefinition",
    [
        ("numerator_metric", str),
        ("denominator_metric", str),
        ("as_percent", bool),
        ("supports_cross_company", bool),
    ],
)

# Declarative registry for every same-period ratio-of-two-metrics
# formula. Holds only plain data (strings/bools), never function
# references, so it can't go stale under a monkeypatch the way a dict
# of function objects can. Adding a new same-period ratio is a one-line
# entry here plus get_ratio()/get_ratio_all_companies() below picking it
# up automatically -- no new function required. See
# docs/decisions/2026-08-28-ratio-definitions-table-driven-registry.md.
#
# `supports_cross_company=False` for return_on_assets/asset_turnover/
# cash_to_assets/inventory_turnover/rd_intensity: total_assets' (and
# inventory's) own SEC-assigned `frame` is None for annual instant
# facts, and SEC's frames API uses a different label format for instant
# concepts entirely, so a borrowed frame label wouldn't resolve either.
# See docs/decisions/2026-08-25-formula-registry-roa-turnover-cash.md.
RATIO_DEFINITIONS: dict[str, RatioDefinition] = {
    "gross_margin": RatioDefinition("gross_profit", "revenue", True, True),
    "operating_margin": RatioDefinition("operating_income", "revenue", True, True),
    "net_margin": RatioDefinition("net_income", "revenue", True, True),
    "return_on_assets": RatioDefinition("net_income", "total_assets", True, False),
    "asset_turnover": RatioDefinition("revenue", "total_assets", False, False),
    "cash_to_assets": RatioDefinition("cash_and_equivalents", "total_assets", True, False),
    "inventory_turnover": RatioDefinition("cost_of_revenue", "inventory", False, False),
    "rd_intensity": RatioDefinition("rd_expense", "revenue", True, False),
}


def get_ratio(
    ticker: str,
    ratio_name: str,
    fiscal_year: int | None = None,
    fiscal_period: str = "FY",
    period_end_date: str | None = None,
) -> dict | None:
    """Generic entry point for any ratio in RATIO_DEFINITIONS -- see that
    dict's own comment for why this exists instead of one function per
    ratio. Raises KeyError for an unregistered ratio_name, same as a
    plain dict lookup would; callers (agent.py) are expected to check
    `metric in RATIO_DEFINITIONS` first, same pattern already used for
    DEFAULT_METRIC_TAGS elsewhere."""
    d = RATIO_DEFINITIONS[ratio_name]
    return _compute_ratio_metric(
        ticker,
        d.numerator_metric,
        d.denominator_metric,
        _Period(fiscal_year, fiscal_period, period_end_date),
        d.as_percent,
    )


def get_gross_margin(
    ticker: str,
    fiscal_year: int | None = None,
    fiscal_period: str = "FY",
    period_end_date: str | None = None,
) -> dict | None:
    """Gross profit / revenue, as a percent. Thin wrapper over
    get_ratio() -- kept as its own named function for readability at
    call sites and because get_gross_margin_all_companies() below and
    get_multi_year_average()'s tests monkeypatch it directly."""
    return get_ratio(ticker, "gross_margin", fiscal_year, fiscal_period, period_end_date)


def get_operating_margin(
    ticker: str,
    fiscal_year: int | None = None,
    fiscal_period: str = "FY",
    period_end_date: str | None = None,
) -> dict | None:
    """Operating income / revenue, as a percent. See get_gross_margin()
    above for why this is a thin get_ratio() wrapper."""
    return get_ratio(ticker, "operating_margin", fiscal_year, fiscal_period, period_end_date)


def get_net_margin(
    ticker: str,
    fiscal_year: int | None = None,
    fiscal_period: str = "FY",
    period_end_date: str | None = None,
) -> dict | None:
    """Net income / revenue, as a percent. See get_gross_margin() above
    for why this is a thin get_ratio() wrapper."""
    return get_ratio(ticker, "net_margin", fiscal_year, fiscal_period, period_end_date)


def get_return_on_assets(
    ticker: str,
    fiscal_year: int | None = None,
    fiscal_period: str = "FY",
    period_end_date: str | None = None,
) -> dict | None:
    """Net income / total assets, as a percent -- the first ratio in this
    module combining a duration (income-statement) metric with an
    instant (balance-sheet) one. See get_gross_margin() above for why
    this is a thin get_ratio() wrapper, and RATIO_DEFINITIONS' own
    comment for why there's no cross-company counterpart."""
    return get_ratio(ticker, "return_on_assets", fiscal_year, fiscal_period, period_end_date)


def get_asset_turnover(
    ticker: str,
    fiscal_year: int | None = None,
    fiscal_period: str = "FY",
    period_end_date: str | None = None,
) -> dict | None:
    """Revenue / total assets, as a plain decimal ratio (NOT a percent --
    see _compute_ratio_metric()'s `as_percent` docstring for why this
    one specifically isn't). See get_gross_margin() above for why this
    is a thin get_ratio() wrapper."""
    return get_ratio(ticker, "asset_turnover", fiscal_year, fiscal_period, period_end_date)


def get_cash_to_assets(
    ticker: str,
    fiscal_year: int | None = None,
    fiscal_period: str = "FY",
    period_end_date: str | None = None,
) -> dict | None:
    """Cash and cash equivalents / total assets, as a percent -- both
    legs are instant (balance-sheet) concepts here, unlike
    get_return_on_assets()/get_asset_turnover() above. See
    get_gross_margin() above for why this is a thin get_ratio()
    wrapper."""
    return get_ratio(ticker, "cash_to_assets", fiscal_year, fiscal_period, period_end_date)


def _compute_ratio_metric_all_companies(
    anchor: dict | None, numerator_metric: str, denominator_metric: str, as_percent: bool = True
) -> dict[str, dict]:
    """Shared body for every cross-company tool-computed ratio metric --
    the frames-layer counterpart to _compute_ratio_metric(). `anchor` is
    the caller's own already-resolved get_X_margin() result, passed in
    rather than recomputed here, since each margin function already
    knows which two metrics it's a ratio of. A company is included only
    if BOTH frames have an entry for it with matching period_end -- the
    two metrics can use different underlying tags (see
    xbrl_facts.get_frame's docstring), so their per-company period
    boundaries aren't guaranteed to align by construction, only checked.

    `as_percent` mirrors _compute_ratio_metric()'s own flag -- without
    it, a decimal ratio like asset_turnover would get hardcoded
    `unit: "percent"` here, silently mislabeled. See
    docs/decisions/2026-08-28-ratio-definitions-table-driven-registry.md."""
    if anchor is None or anchor.get("frame") is None:
        return {}
    numerators = get_frame(numerator_metric, anchor["frame"])
    denominators = get_frame(denominator_metric, anchor["frame"])

    results: dict[str, dict] = {}
    for t, num in numerators.items():
        den = denominators.get(t)
        if den is None or den["period_end"] != num["period_end"] or den["value"] == 0:
            continue
        ratio = num["value"] / den["value"]
        results[t] = {
            "value": round(ratio * 100, 1) if as_percent else round(ratio, 2),
            "unit": "percent" if as_percent else "raw",
            "period_end": num["period_end"],
            "accession": num["accession"],
        }
    return results


def get_ratio_all_companies(
    ticker: str,
    ratio_name: str,
    fiscal_year: int | None = None,
    fiscal_period: str = "FY",
    period_end_date: str | None = None,
) -> dict[str, dict]:
    """Generic cross-company entry point for any ratio in
    RATIO_DEFINITIONS, matching get_ratio() above -- checks
    `supports_cross_company` FIRST and returns {} immediately if False,
    without ever computing an anchor or calling get_frame(). Deliberate:
    RATIO_DEFINITIONS' own comment explains why this is a documented
    gate rather than relying on _compute_ratio_metric_all_companies()'s
    own `anchor frame is None` short-circuit to degrade gracefully on
    its own."""
    d = RATIO_DEFINITIONS[ratio_name]
    if not d.supports_cross_company:
        return {}
    anchor = get_ratio(ticker, ratio_name, fiscal_year, fiscal_period, period_end_date)
    return _compute_ratio_metric_all_companies(anchor, d.numerator_metric, d.denominator_metric, d.as_percent)


def get_gross_margin_all_companies(
    ticker: str,
    fiscal_year: int | None = None,
    fiscal_period: str = "FY",
    period_end_date: str | None = None,
) -> dict[str, dict]:
    """Gross margin for every covered company, for the same period
    bucket as `ticker`'s own period. Thin wrapper over
    get_ratio_all_companies() -- see get_gross_margin() above for why
    that's preferred over hardcoding "gross_profit"/"revenue" again
    here (RATIO_DEFINITIONS is the single source of truth for both
    legs)."""
    return get_ratio_all_companies(ticker, "gross_margin", fiscal_year, fiscal_period, period_end_date)


def get_operating_margin_all_companies(
    ticker: str,
    fiscal_year: int | None = None,
    fiscal_period: str = "FY",
    period_end_date: str | None = None,
) -> dict[str, dict]:
    """Operating margin for every covered company, for the same period
    bucket as `ticker`'s own period. See get_gross_margin_all_companies()
    above for why this is a thin get_ratio_all_companies() wrapper."""
    return get_ratio_all_companies(ticker, "operating_margin", fiscal_year, fiscal_period, period_end_date)


def get_net_margin_all_companies(
    ticker: str,
    fiscal_year: int | None = None,
    fiscal_period: str = "FY",
    period_end_date: str | None = None,
) -> dict[str, dict]:
    """Net margin for every covered company, for the same period bucket
    as `ticker`'s own period. See get_gross_margin_all_companies() above
    for why this is a thin get_ratio_all_companies() wrapper."""
    return get_ratio_all_companies(ticker, "net_margin", fiscal_year, fiscal_period, period_end_date)


def get_yoy_growth(
    ticker: str,
    metric: str,
    fiscal_year: int | None = None,
    fiscal_period: str = "FY",
    period_end_date: str | None = None,
) -> dict | None:
    """Year-over-year percent change in `metric`, comparing the current
    period to the SAME fiscal_period one year earlier.

    No date arithmetic, by design: the prior period isn't computed as
    "one year before" a calendar date (which would reproduce the exact
    bug class xbrl_facts._pick_entry_by_end_date()'s docstring already
    fixed once) -- it's found by reading the CURRENT period's own
    SEC-assigned fiscal_year straight off get_metric()'s result and
    asking for `fiscal_year - 1` at the same fiscal_period instead.
    Simple integer subtraction on a label the data already supplied, not
    an independent computation that could silently disagree with it.

    Scoped to the raw tagged metrics only (revenue, gross_profit,
    cost_of_revenue, rd_expense, net_income, operating_income) -- NOT
    the margin ratios (gross_margin/operating_margin/net_margin), since
    there's no current evidence "growth of a percentage" is a question
    this needs to answer; passing one of those raises the same
    ValueError xbrl_facts._tag_for() already raises for any unrecognized
    metric.

    Returns {"value": float (percent), "unit": "percent", "period_end",
    "form", "accession", "filed", "frame"} for the CURRENT period, or
    None if either period is unavailable or the prior value is zero
    (growth is undefined)."""
    current = get_metric(ticker, metric, fiscal_year, fiscal_period, period_end_date)
    if current is None or current.get("fiscal_year") is None:
        return None
    prior = get_metric(ticker, metric, fiscal_year=current["fiscal_year"] - 1, fiscal_period=current["fiscal_period"])
    if prior is None or prior["value"] == 0:
        return None
    growth_pct = (current["value"] - prior["value"]) / prior["value"] * 100
    return {
        "value": round(growth_pct, 1),
        "unit": "percent",
        "period_end": current["period_end"],
        "form": current["form"],
        "accession": current["accession"],
        "filed": current["filed"],
        "frame": current["frame"],
    }


def _get_annual_value(ticker: str, metric: str, fiscal_year: int) -> dict | None:
    """Resolves either a margin ratio or a raw tagged metric for one
    fiscal year, uniformly, so get_multi_year_average() can average
    either kind without caring which it is. Always fiscal_period="FY" --
    a multi-YEAR average is fundamentally an annual concept with no
    natural quarterly reading, unlike get_yoy_growth()'s same-quarter
    comparison.

    Checks RATIO_DEFINITIONS and dispatches through the generic
    get_ratio() rather than a per-ratio if/elif chain -- safe from the
    dict-of-stale-function-objects gotcha (see
    docs/decisions/2026-08-18-formulas-module-split.md and
    docs/decisions/2026-08-28-ratio-definitions-table-driven-registry.md)
    since RATIO_DEFINITIONS holds only plain data, never function
    references. This also means a NEW ratio added only to
    RATIO_DEFINITIONS works here automatically, with no new named
    function required."""
    if metric in RATIO_DEFINITIONS:
        return get_ratio(ticker, metric, fiscal_year=fiscal_year, fiscal_period="FY")
    return get_metric(ticker, metric, fiscal_year=fiscal_year, fiscal_period="FY")


def get_multi_year_average(
    ticker: str, metric: str, start_fiscal_year: int, end_fiscal_year: int
) -> dict | None:
    """Average of `metric` across every fiscal year from
    start_fiscal_year through end_fiscal_year, inclusive. See
    docs/decisions/2026-08-19-fixing-6-accumulated-eval-findings.md for
    why this exists (a real eval failure with no deterministic path
    before it did).

    Unlike get_yoy_growth() (deliberately scoped to raw metrics only),
    this supports BOTH margin ratios and raw tagged metrics -- the
    actual failing question needs a margin average, so margins can't be
    excluded the way yoy_growth excludes them.

    Averages the RAW per-year values (not display-rounded ones) --
    ground truth for the motivating question was itself derived this
    way, from unrounded per-year margins, not by averaging
    get_operating_margin()'s own 1-decimal-rounded output.

    Returns None if the range has fewer than 2 years (a 1-year "average"
    isn't meaningful -- checked before any fetching, not after), if
    start comes after end, or if ANY year in the range is unavailable.
    Metadata (period_end/form/accession/filed/frame) in the result comes
    from the most recent (end_fiscal_year) year -- fiscal years are
    monotonic, so the last one fetched in the range is always the most
    recent, no separate comparison needed."""
    if end_fiscal_year - start_fiscal_year < 1:
        return None
    values = []
    latest = None
    for fiscal_year in range(start_fiscal_year, end_fiscal_year + 1):
        result = _get_annual_value(ticker, metric, fiscal_year)
        if result is None:
            return None
        values.append(result["value"])
        latest = result
    assert latest is not None  # loop always runs >=1 time (checked above), always sets latest
    average = sum(values) / len(values)
    return {
        "value": round(average, 1) if latest["unit"] == "percent" else average,
        "unit": latest["unit"],
        "period_end": latest["period_end"],
        "form": latest["form"],
        "accession": latest["accession"],
        "filed": latest["filed"],
        "frame": latest.get("frame"),
    }
