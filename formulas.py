"""
Week 5k/5n — Formula registry
-------------------------------------
Every tool-computed derived metric (margins, YoY growth, and future
additions) lives here, separate from xbrl_facts.py's raw-fact fetching.
Split out once formula functions grew to more than half of
xbrl_facts.py's own line count, with more on the way (multi-year
averages, cash-flow ratios, etc. from the FinanceBench-informed eval
growth) -- unlike the raw XBRL tags (a small, bounded set SEC actually
defines), the list of financial ratios a user might ask for has no
natural upper limit, so it gets its own module rather than continuing
to grow inside the fact-fetching one.

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

from xbrl_facts import get_frame, get_metric


def _compute_ratio_metric(
    ticker: str,
    numerator_metric: str,
    denominator_metric: str,
    fiscal_year: int | None,
    fiscal_period: str,
    period_end_date: str | None,
    as_percent: bool = True,
) -> dict | None:
    """Shared body for every tool-computed ratio metric (gross/operating/
    net margin, and now return-on-assets/asset-turnover/cash-to-assets).
    Extracted once operating_margin/net_margin were added alongside
    gross_margin, since all three are otherwise identical bodies
    differing only in which metric is the numerator -- copy-pasting a
    third time would reproduce exactly the kind of duplication this
    project already fixed once (see config.py's own history).

    Both legs are just handed the same fiscal_year/fiscal_period/
    period_end_date arguments and each resolves its own entry via
    get_metric() independently -- the period_end check below is what
    actually guarantees both legs agree, regardless of how each one got
    there. This also means either leg can be an XBRL "instant" (point-
    in-time balance, e.g. total_assets) or "duration" (income-statement)
    concept, or one of each -- get_metric() already normalizes both
    shapes to the same {"value", "period_end", ...} dict, so nothing
    here needs to know or care which kind either metric is.

    `as_percent=False` (asset_turnover's case) skips the *100 and
    reports `unit: "raw"` instead of `"percent"`, rounded to 2 decimals
    instead of 1 -- asset turnover is conventionally expressed as a
    decimal ratio ("1.04x"), not a percentage; found live (2026-08-25)
    that `numeric_utils.normalize()` treats "percent" and "raw" as
    different, never-cross-matching categories regardless of numeric
    equivalence, so getting this wrong isn't just a display
    preference, it silently breaks eval grading."""
    numerator = get_metric(ticker, numerator_metric, fiscal_year, fiscal_period, period_end_date)
    denominator = get_metric(ticker, denominator_metric, fiscal_year, fiscal_period, period_end_date)
    if numerator is None or denominator is None:
        return None
    if numerator["period_end"] != denominator["period_end"]:
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


def get_gross_margin(
    ticker: str,
    fiscal_year: int | None = None,
    fiscal_period: str = "FY",
    period_end_date: str | None = None,
) -> dict | None:
    """Gross profit / revenue, as a percent. See _compute_ratio_metric()
    for why this is computed here rather than returned raw."""
    return _compute_ratio_metric(ticker, "gross_profit", "revenue", fiscal_year, fiscal_period, period_end_date)


def get_operating_margin(
    ticker: str,
    fiscal_year: int | None = None,
    fiscal_period: str = "FY",
    period_end_date: str | None = None,
) -> dict | None:
    """Operating income / revenue, as a percent. See
    _compute_ratio_metric() for why this is computed here rather than
    returned raw."""
    return _compute_ratio_metric(ticker, "operating_income", "revenue", fiscal_year, fiscal_period, period_end_date)


def get_net_margin(
    ticker: str,
    fiscal_year: int | None = None,
    fiscal_period: str = "FY",
    period_end_date: str | None = None,
) -> dict | None:
    """Net income / revenue, as a percent. See _compute_ratio_metric()
    for why this is computed here rather than returned raw."""
    return _compute_ratio_metric(ticker, "net_income", "revenue", fiscal_year, fiscal_period, period_end_date)


def get_return_on_assets(
    ticker: str,
    fiscal_year: int | None = None,
    fiscal_period: str = "FY",
    period_end_date: str | None = None,
) -> dict | None:
    """Net income / total assets, as a percent -- the first ratio in this
    module combining a duration (income-statement) metric with an
    instant (balance-sheet) one. Built to answer aapl-return-on-assets-
    fy2025, one of the multi-statement eval questions deliberately added
    with no tool support (Week 5v/eval-growth round), to generate real
    evidence of what the agent does without a deterministic path --
    same discipline that originally justified the margin registry
    itself. See _compute_ratio_metric() for why this is computed here
    rather than returned raw.

    No cross-company `_all_companies` counterpart, unlike the three
    margins above -- confirmed via a live check, not assumed:
    total_assets' own SEC-assigned `frame` is None for annual instant
    facts (no bucket to anchor a frames query on), and even borrowing a
    substitute frame label from the duration numerator wouldn't work --
    SEC's frames API uses a different label format for instant concepts
    entirely. No current eval question needs a cross-company comparison
    of this ratio anyway, so this isn't worth chasing down further."""
    return _compute_ratio_metric(ticker, "net_income", "total_assets", fiscal_year, fiscal_period, period_end_date)


def get_asset_turnover(
    ticker: str,
    fiscal_year: int | None = None,
    fiscal_period: str = "FY",
    period_end_date: str | None = None,
) -> dict | None:
    """Revenue / total assets, as a plain decimal ratio (NOT a percent --
    see _compute_ratio_metric()'s `as_percent` docstring for why this
    one specifically isn't). Built to answer
    nvda-asset-turnover-fy2026. Same "no cross-company counterpart"
    reasoning as get_return_on_assets() above applies here too."""
    return _compute_ratio_metric(
        ticker, "revenue", "total_assets", fiscal_year, fiscal_period, period_end_date, as_percent=False
    )


def get_cash_to_assets(
    ticker: str,
    fiscal_year: int | None = None,
    fiscal_period: str = "FY",
    period_end_date: str | None = None,
) -> dict | None:
    """Cash and cash equivalents / total assets, as a percent -- both
    legs are instant (balance-sheet) concepts here, unlike
    get_return_on_assets()/get_asset_turnover() above. Built to answer
    msft-cash-to-assets-fy2025. Same "no cross-company counterpart"
    reasoning as get_return_on_assets() above applies here too."""
    return _compute_ratio_metric(
        ticker, "cash_and_equivalents", "total_assets", fiscal_year, fiscal_period, period_end_date
    )


def _compute_ratio_metric_all_companies(
    anchor: dict | None, numerator_metric: str, denominator_metric: str
) -> dict[str, dict]:
    """Shared body for every cross-company tool-computed percentage
    metric -- the frames-layer counterpart to _compute_ratio_metric(),
    extracted for the same reason (operating_margin_all_companies/
    net_margin_all_companies would otherwise be copies of
    gross_margin_all_companies differing only in which metric is the
    numerator). `anchor` is the caller's own already-resolved
    get_X_margin() result, passed in rather than recomputed here, since
    each margin function already knows which two metrics it's a ratio
    of. A company is included only if BOTH frames have an entry for it
    with matching period_end -- the two metrics can use different
    underlying tags (see xbrl_facts.get_frame's docstring), so their
    per-company period boundaries aren't guaranteed to align by
    construction, only checked."""
    if anchor is None or anchor.get("frame") is None:
        return {}
    numerators = get_frame(numerator_metric, anchor["frame"])
    denominators = get_frame(denominator_metric, anchor["frame"])

    results: dict[str, dict] = {}
    for t, num in numerators.items():
        den = denominators.get(t)
        if den is None or den["period_end"] != num["period_end"]:
            continue
        results[t] = {
            "value": round(num["value"] / den["value"] * 100, 1),
            "unit": "percent",
            "period_end": num["period_end"],
            "accession": num["accession"],
        }
    return results


def get_gross_margin_all_companies(
    ticker: str,
    fiscal_year: int | None = None,
    fiscal_period: str = "FY",
    period_end_date: str | None = None,
) -> dict[str, dict]:
    """Gross margin for every covered company, for the same period
    bucket as `ticker`'s own period. See _compute_ratio_metric_all_companies()
    for the shared computation."""
    anchor = get_gross_margin(ticker, fiscal_year, fiscal_period, period_end_date)
    return _compute_ratio_metric_all_companies(anchor, "gross_profit", "revenue")


def get_operating_margin_all_companies(
    ticker: str,
    fiscal_year: int | None = None,
    fiscal_period: str = "FY",
    period_end_date: str | None = None,
) -> dict[str, dict]:
    """Operating margin for every covered company, for the same period
    bucket as `ticker`'s own period. See _compute_ratio_metric_all_companies()
    for the shared computation."""
    anchor = get_operating_margin(ticker, fiscal_year, fiscal_period, period_end_date)
    return _compute_ratio_metric_all_companies(anchor, "operating_income", "revenue")


def get_net_margin_all_companies(
    ticker: str,
    fiscal_year: int | None = None,
    fiscal_period: str = "FY",
    period_end_date: str | None = None,
) -> dict[str, dict]:
    """Net margin for every covered company, for the same period bucket
    as `ticker`'s own period. See _compute_ratio_metric_all_companies()
    for the shared computation."""
    anchor = get_net_margin(ticker, fiscal_year, fiscal_period, period_end_date)
    return _compute_ratio_metric_all_companies(anchor, "net_income", "revenue")


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

    Deliberately an if/elif chain calling each margin function by its
    own bare name, not a {metric: function} dict built once at module
    load -- a dict would bind the ORIGINAL function objects at import
    time, the exact gotcha already hit twice in this project (agent.py's
    RATIO_METRIC_FUNCTIONS, and this module's own split from
    xbrl_facts.py): a test monkeypatching formulas.get_operating_margin
    would silently miss a dict-based dispatch, since the dict's own
    entry would still point at the pre-patch function. Calling the bare
    name here instead resolves it fresh from the module's own namespace
    every time, so a monkeypatch on the module attribute is always seen."""
    if metric == "gross_margin":
        return get_gross_margin(ticker, fiscal_year=fiscal_year, fiscal_period="FY")
    if metric == "operating_margin":
        return get_operating_margin(ticker, fiscal_year=fiscal_year, fiscal_period="FY")
    if metric == "net_margin":
        return get_net_margin(ticker, fiscal_year=fiscal_year, fiscal_period="FY")
    if metric == "return_on_assets":
        return get_return_on_assets(ticker, fiscal_year=fiscal_year, fiscal_period="FY")
    if metric == "asset_turnover":
        return get_asset_turnover(ticker, fiscal_year=fiscal_year, fiscal_period="FY")
    if metric == "cash_to_assets":
        return get_cash_to_assets(ticker, fiscal_year=fiscal_year, fiscal_period="FY")
    return get_metric(ticker, metric, fiscal_year=fiscal_year, fiscal_period="FY")


def get_multi_year_average(
    ticker: str, metric: str, start_fiscal_year: int, end_fiscal_year: int
) -> dict | None:
    """Average of `metric` across every fiscal year from
    start_fiscal_year through end_fiscal_year, inclusive.

    Motivated by a real eval failure with no deterministic path before
    this existed (aapl-3yr-avg-operating-margin-fy2023-fy2025): with
    nothing to call, the model reached for self-computation on its own,
    fetching each year's value via 3 separate get_financial_fact calls
    and averaging them in its own reasoning text -- a rule-3 violation
    ("don't combine numbers") the citation-verification gate correctly
    caught once, and once misparsing the whole request as a Q4-specific
    one instead. Computed here deterministically, same pattern as every
    other formula in this module.

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
