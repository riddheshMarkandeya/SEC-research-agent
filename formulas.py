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
) -> dict | None:
    """Shared body for every tool-computed percentage metric (gross/
    operating/net margin). Extracted once operating_margin/net_margin
    were added alongside gross_margin, since all three are otherwise
    identical bodies differing only in which metric is the numerator --
    copy-pasting a third time would reproduce exactly the kind of
    duplication this project already fixed once (see config.py's own
    history).

    Both legs are just handed the same fiscal_year/fiscal_period/
    period_end_date arguments and each resolves its own entry via
    get_metric() independently -- the period_end check below is what
    actually guarantees both legs agree, regardless of how each one got
    there."""
    numerator = get_metric(ticker, numerator_metric, fiscal_year, fiscal_period, period_end_date)
    denominator = get_metric(ticker, denominator_metric, fiscal_year, fiscal_period, period_end_date)
    if numerator is None or denominator is None:
        return None
    if numerator["period_end"] != denominator["period_end"]:
        return None
    ratio_pct = numerator["value"] / denominator["value"] * 100
    return {
        "value": round(ratio_pct, 1),
        "unit": "percent",
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
