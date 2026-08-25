"""
Tests for formulas.py's derived metrics (margins, return_on_assets/
asset_turnover/cash_to_assets, multi-year averages, YoY growth). Moved
out of test_xbrl_facts.py alongside the formula-registry split -- see
formulas.py's own docstring for why. Underlying period-entry
disambiguation is exercised via test_xbrl_facts.py; these tests focus on
the ratio/growth computation itself.

Monkeypatch targets: fetch_concept() stays defined in xbrl_facts.py, so
patches on it stay "xbrl_facts.fetch_concept" even when exercised
through a formulas.py function -- get_metric() (also still in
xbrl_facts.py) resolves that name in its OWN module's namespace
regardless of caller. But get_frame/get_gross_margin/get_operating_margin/
get_net_margin are called via formulas.py's own bare names (imported or
defined there), so patches on those must target "formulas.X", not
"xbrl_facts.X" -- the same import-time-binding gotcha already documented
for agent.py's RATIO_METRIC_FUNCTIONS.
"""

from formulas import (
    get_asset_turnover,
    get_cash_to_assets,
    get_gross_margin,
    get_gross_margin_all_companies,
    get_multi_year_average,
    get_net_margin,
    get_net_margin_all_companies,
    get_operating_margin,
    get_operating_margin_all_companies,
    get_return_on_assets,
    get_yoy_growth,
)

# Trimmed, real entries from NVDA's GrossProfit companyconcept response
# (CIK0001045810, fetched 2026-08-16) -- one filing (FY2026 10-K)
# re-reports THREE fiscal years' worth of the same concept, all sharing
# fy=2026/fp="FY", distinguished only by `end`.
NVDA_GROSS_PROFIT_ENTRIES = [
    {"start": "2023-01-30", "end": "2024-01-28", "val": 44301000000, "accn": "0001045810-26-000021", "fy": 2026, "fp": "FY", "form": "10-K", "filed": "2026-02-25"},
    {"start": "2024-01-29", "end": "2025-01-26", "val": 97858000000, "accn": "0001045810-26-000021", "fy": 2026, "fp": "FY", "form": "10-K", "filed": "2026-02-25"},
    {"start": "2025-01-27", "end": "2026-01-25", "val": 153463000000, "accn": "0001045810-26-000021", "fy": 2026, "fp": "FY", "form": "10-K", "filed": "2026-02-25"},
]


# ---------------------------------------------------------------------------
# get_gross_margin / get_operating_margin / get_net_margin
# ---------------------------------------------------------------------------
def test_get_gross_margin_with_empty_string_period_end_date_falls_back_to_fiscal_args(monkeypatch):
    revenue_entries = [
        {"start": "2025-01-27", "end": "2026-01-25", "val": 215938000000, "accn": "x", "fy": 2026, "fp": "FY", "form": "10-K"},
    ]

    def fake_fetch(ticker, tag):
        return {"units": {"USD": NVDA_GROSS_PROFIT_ENTRIES if tag == "GrossProfit" else revenue_entries}}

    monkeypatch.setattr("xbrl_facts.fetch_concept", fake_fetch)
    result = get_gross_margin("NVDA", fiscal_year=2026, fiscal_period="FY", period_end_date="")
    assert result["value"] == 71.1


def test_get_gross_margin_computes_ratio_from_two_metrics(monkeypatch):
    revenue_entries = [
        {"start": "2025-01-27", "end": "2026-01-25", "val": 215938000000, "accn": "x", "fy": 2026, "fp": "FY", "form": "10-K"},
    ]

    def fake_fetch(ticker, tag):
        return {"units": {"USD": NVDA_GROSS_PROFIT_ENTRIES if tag == "GrossProfit" else revenue_entries}}

    monkeypatch.setattr("xbrl_facts.fetch_concept", fake_fetch)
    result = get_gross_margin("NVDA", fiscal_year=2026, fiscal_period="FY")
    assert result["value"] == 71.1
    assert result["unit"] == "percent"


def test_get_gross_margin_returns_none_if_either_metric_missing(monkeypatch):
    monkeypatch.setattr("xbrl_facts.fetch_concept", lambda ticker, tag: None)
    assert get_gross_margin("NVDA", fiscal_year=2026, fiscal_period="FY") is None


def test_get_operating_margin_computes_ratio_from_two_metrics(monkeypatch):
    revenue_entries = [
        {"start": "2025-01-27", "end": "2026-01-25", "val": 400000000, "accn": "x", "fy": 2026, "fp": "FY", "form": "10-K"},
    ]
    operating_income_entries = [
        {"start": "2025-01-27", "end": "2026-01-25", "val": 100000000, "accn": "y", "fy": 2026, "fp": "FY", "form": "10-K"},
    ]

    def fake_fetch(ticker, tag):
        return {"units": {"USD": operating_income_entries if tag == "OperatingIncomeLoss" else revenue_entries}}

    monkeypatch.setattr("xbrl_facts.fetch_concept", fake_fetch)
    result = get_operating_margin("NVDA", fiscal_year=2026, fiscal_period="FY")
    assert result["value"] == 25.0
    assert result["unit"] == "percent"


def test_get_operating_margin_returns_none_if_either_metric_missing(monkeypatch):
    monkeypatch.setattr("xbrl_facts.fetch_concept", lambda ticker, tag: None)
    assert get_operating_margin("NVDA", fiscal_year=2026, fiscal_period="FY") is None


def test_get_net_margin_computes_ratio_from_two_metrics(monkeypatch):
    revenue_entries = [
        {"start": "2025-01-27", "end": "2026-01-25", "val": 400000000, "accn": "x", "fy": 2026, "fp": "FY", "form": "10-K"},
    ]
    net_income_entries = [
        {"start": "2025-01-27", "end": "2026-01-25", "val": 50000000, "accn": "z", "fy": 2026, "fp": "FY", "form": "10-K"},
    ]

    def fake_fetch(ticker, tag):
        return {"units": {"USD": net_income_entries if tag == "NetIncomeLoss" else revenue_entries}}

    monkeypatch.setattr("xbrl_facts.fetch_concept", fake_fetch)
    result = get_net_margin("NVDA", fiscal_year=2026, fiscal_period="FY")
    assert result["value"] == 12.5
    assert result["unit"] == "percent"


def test_get_net_margin_returns_none_if_either_metric_missing(monkeypatch):
    monkeypatch.setattr("xbrl_facts.fetch_concept", lambda ticker, tag: None)
    assert get_net_margin("NVDA", fiscal_year=2026, fiscal_period="FY") is None


# ---------------------------------------------------------------------------
# get_return_on_assets / get_asset_turnover / get_cash_to_assets (Week 5w) --
# the first ratios in this module combining a DURATION income-statement
# metric with an INSTANT balance-sheet metric (or two instant metrics),
# rather than two duration metrics like every margin above. Real,
# verified figures from AAPL/NVDA/MSFT's actual filings, not synthetic.
# ---------------------------------------------------------------------------
def test_get_return_on_assets_computes_ratio_from_duration_and_instant_metric(monkeypatch):
    net_income_entries = [
        {"start": "2024-09-28", "end": "2025-09-27", "val": 112010000000, "accn": "x", "fy": 2025, "fp": "FY", "form": "10-K", "filed": "2025-10-31"},
    ]
    total_assets_entries = [
        {"end": "2025-09-27", "val": 359241000000, "accn": "x", "fy": 2025, "fp": "FY", "form": "10-K", "filed": "2025-10-31"},
    ]

    def fake_fetch(ticker, tag):
        return {"units": {"USD": net_income_entries if tag == "NetIncomeLoss" else total_assets_entries}}

    monkeypatch.setattr("xbrl_facts.fetch_concept", fake_fetch)
    result = get_return_on_assets("AAPL", fiscal_year=2025, fiscal_period="FY")
    assert result["value"] == 31.2
    assert result["unit"] == "percent"


def test_get_return_on_assets_returns_none_if_either_metric_missing(monkeypatch):
    monkeypatch.setattr("xbrl_facts.fetch_concept", lambda ticker, tag: None)
    assert get_return_on_assets("AAPL", fiscal_year=2025, fiscal_period="FY") is None


def test_get_asset_turnover_computes_raw_ratio_not_percent(monkeypatch):
    # Asset turnover is conventionally a decimal ratio ("1.04x"), not a
    # percentage -- found live (2026-08-25): a real Gemini answer stated
    # "approximately 1.04", and the eval question's own expected_unit
    # had to be corrected from "percent" to "raw" for exactly this
    # reason (normalize() treats them as different, never-cross-matching
    # categories). The first non-percent ratio in this module.
    revenue_entries = [
        {"start": "2025-01-27", "end": "2026-01-25", "val": 215938000000, "accn": "x", "fy": 2026, "fp": "FY", "form": "10-K", "filed": "2026-02-25"},
    ]
    total_assets_entries = [
        {"end": "2026-01-25", "val": 206803000000, "accn": "x", "fy": 2026, "fp": "FY", "form": "10-K", "filed": "2026-02-25"},
    ]

    def fake_fetch(ticker, tag):
        return {"units": {"USD": revenue_entries if tag == "Revenues" else total_assets_entries}}

    monkeypatch.setattr("xbrl_facts.fetch_concept", fake_fetch)
    result = get_asset_turnover("NVDA", fiscal_year=2026, fiscal_period="FY")
    assert result["value"] == 1.04
    assert result["unit"] == "raw"


def test_get_asset_turnover_returns_none_if_either_metric_missing(monkeypatch):
    monkeypatch.setattr("xbrl_facts.fetch_concept", lambda ticker, tag: None)
    assert get_asset_turnover("NVDA", fiscal_year=2026, fiscal_period="FY") is None


def test_get_cash_to_assets_computes_ratio_from_two_instant_metrics(monkeypatch):
    cash_entries = [
        {"end": "2025-06-30", "val": 30242000000, "accn": "x", "fy": 2025, "fp": "FY", "form": "10-K", "filed": "2025-07-30"},
    ]
    total_assets_entries = [
        {"end": "2025-06-30", "val": 619003000000, "accn": "x", "fy": 2025, "fp": "FY", "form": "10-K", "filed": "2025-07-30"},
    ]

    def fake_fetch(ticker, tag):
        return {
            "units": {
                "USD": cash_entries if tag == "CashAndCashEquivalentsAtCarryingValue" else total_assets_entries
            }
        }

    monkeypatch.setattr("xbrl_facts.fetch_concept", fake_fetch)
    result = get_cash_to_assets("MSFT", fiscal_year=2025, fiscal_period="FY")
    assert result["value"] == 4.9
    assert result["unit"] == "percent"


def test_get_cash_to_assets_returns_none_if_either_metric_missing(monkeypatch):
    monkeypatch.setattr("xbrl_facts.fetch_concept", lambda ticker, tag: None)
    assert get_cash_to_assets("MSFT", fiscal_year=2025, fiscal_period="FY") is None


# ---------------------------------------------------------------------------
# get_yoy_growth
# ---------------------------------------------------------------------------
def test_get_yoy_growth_computes_percent_change_from_prior_year(monkeypatch):
    entries = [
        {"start": "2025-01-27", "end": "2026-01-25", "val": 220000000, "accn": "x", "fy": 2026, "fp": "FY", "form": "10-K"},
        {"start": "2024-01-29", "end": "2025-01-26", "val": 200000000, "accn": "y", "fy": 2025, "fp": "FY", "form": "10-K"},
    ]
    monkeypatch.setattr("xbrl_facts.fetch_concept", lambda ticker, tag: {"units": {"USD": entries}})
    result = get_yoy_growth("NVDA", "revenue", fiscal_year=2026, fiscal_period="FY")
    assert result["value"] == 10.0
    assert result["unit"] == "percent"


def test_get_yoy_growth_works_with_period_end_date_input(monkeypatch):
    # No date arithmetic: given a calendar period_end_date, the prior
    # period is found via the CURRENT entry's own fy label minus one --
    # not by computing "one year before" as a calendar date -- exactly
    # the trust-the-data principle xbrl_facts._pick_entry_by_end_date()
    # relies on.
    entries = [
        {"start": "2026-01-26", "end": "2026-04-26", "val": 220000000, "accn": "x", "fy": 2027, "fp": "Q1", "form": "10-Q"},
        {"start": "2025-01-28", "end": "2025-04-27", "val": 200000000, "accn": "y", "fy": 2026, "fp": "Q1", "form": "10-Q"},
    ]
    monkeypatch.setattr("xbrl_facts.fetch_concept", lambda ticker, tag: {"units": {"USD": entries}})
    result = get_yoy_growth("NVDA", "revenue", period_end_date="2026-04-26")
    assert result["value"] == 10.0


def test_get_yoy_growth_returns_none_when_current_period_unavailable(monkeypatch):
    monkeypatch.setattr("xbrl_facts.fetch_concept", lambda ticker, tag: None)
    assert get_yoy_growth("NVDA", "revenue", fiscal_year=2026, fiscal_period="FY") is None


def test_get_yoy_growth_returns_none_when_prior_year_unavailable(monkeypatch):
    entries = [
        {"start": "2025-01-27", "end": "2026-01-25", "val": 220000000, "accn": "x", "fy": 2026, "fp": "FY", "form": "10-K"},
    ]
    monkeypatch.setattr("xbrl_facts.fetch_concept", lambda ticker, tag: {"units": {"USD": entries}})
    assert get_yoy_growth("NVDA", "revenue", fiscal_year=2026, fiscal_period="FY") is None


def test_get_yoy_growth_returns_none_when_prior_value_is_zero(monkeypatch):
    entries = [
        {"start": "2025-01-27", "end": "2026-01-25", "val": 220000000, "accn": "x", "fy": 2026, "fp": "FY", "form": "10-K"},
        {"start": "2024-01-29", "end": "2025-01-26", "val": 0, "accn": "y", "fy": 2025, "fp": "FY", "form": "10-K"},
    ]
    monkeypatch.setattr("xbrl_facts.fetch_concept", lambda ticker, tag: {"units": {"USD": entries}})
    assert get_yoy_growth("NVDA", "revenue", fiscal_year=2026, fiscal_period="FY") is None


# ---------------------------------------------------------------------------
# get_multi_year_average -- regression case: aapl-3yr-avg-operating-margin-
# fy2023-fy2025. With no deterministic tool for an N-year average, the
# model reached for self-computation on its own (once landing close via
# 3 separate get_financial_fact calls averaged in its own reasoning text,
# a rule-3 violation the citation-verification gate correctly caught;
# once misparsing the whole request as a Q4-specific one instead).
# Supports both margin ratios (formulas.get_operating_margin, etc.) and
# raw tagged metrics (xbrl_facts.get_metric) uniformly, unlike
# get_yoy_growth() which is deliberately scoped to raw metrics only --
# the actual failing question needs a margin average, so this can't
# exclude margins the way yoy_growth does.
# ---------------------------------------------------------------------------
def test_get_multi_year_average_averages_margin_across_years(monkeypatch):
    # Real AAPL operating margin values (verified via get_metric() before
    # this formula existed): 29.82%, 31.51%, 31.97% for FY2023-FY2025.
    per_year = {
        2023: {"value": 29.8, "unit": "percent", "period_end": "2023-09-30", "form": "10-K", "accession": "a23", "filed": "2023-11-03", "frame": None},
        2024: {"value": 31.5, "unit": "percent", "period_end": "2024-09-28", "form": "10-K", "accession": "a24", "filed": "2024-11-01", "frame": None},
        2025: {"value": 32.0, "unit": "percent", "period_end": "2025-09-27", "form": "10-K", "accession": "a25", "filed": "2025-10-31", "frame": "CY2025"},
    }
    monkeypatch.setattr(
        "formulas.get_operating_margin",
        lambda ticker, fiscal_year, fiscal_period: per_year[fiscal_year],
    )
    result = get_multi_year_average("AAPL", "operating_margin", 2023, 2025)
    assert result["value"] == round((29.8 + 31.5 + 32.0) / 3, 1)
    assert result["unit"] == "percent"
    # Metadata comes from the most recent (end_fiscal_year) year, not an
    # arbitrary one -- fiscal years are monotonic, so the last one fetched
    # in the range is always the most recent, no separate comparison needed.
    assert result["period_end"] == "2025-09-27"
    assert result["accession"] == "a25"


def test_get_multi_year_average_averages_return_on_assets_across_years(monkeypatch):
    # Regression guard: adding return_on_assets/asset_turnover/
    # cash_to_assets to agent.py's RATIO_METRIC_FUNCTIONS makes them pass
    # _call_get_financial_fact's boundary check, so a multi-year-average
    # request combined with one of these names now reaches
    # get_multi_year_average() -- which would otherwise crash inside
    # get_metric()'s tag lookup (_tag_for() raises ValueError for any
    # name that isn't a raw GAAP tag) the same way an unsupported metric
    # crashed once before (see xbrl_facts.py's own history). _get_annual_value()
    # needs an explicit branch for each of these three, same as it
    # already has for the three margins.
    per_year = {
        2024: {"value": 25.0, "unit": "percent", "period_end": "2024-09-28", "form": "10-K", "accession": "a24", "filed": "2024-11-01", "frame": None},
        2025: {"value": 31.2, "unit": "percent", "period_end": "2025-09-27", "form": "10-K", "accession": "a25", "filed": "2025-10-31", "frame": "CY2025"},
    }
    monkeypatch.setattr(
        "formulas.get_return_on_assets",
        lambda ticker, fiscal_year, fiscal_period: per_year[fiscal_year],
    )
    result = get_multi_year_average("AAPL", "return_on_assets", 2024, 2025)
    assert result["value"] == round((25.0 + 31.2) / 2, 1)
    assert result["unit"] == "percent"


def test_get_multi_year_average_averages_asset_turnover_across_years(monkeypatch):
    # "raw" isn't special-cased in get_multi_year_average()'s rounding
    # (only "percent" is) -- same as an averaged raw-dollar metric, the
    # average comes back exact/unrounded, not re-rounded to 2 decimals
    # the way a single get_asset_turnover() call would round its own
    # output. No current eval question needs this average, so this test
    # exists only to confirm the crash-prevention dispatch branch
    # resolves correctly, not to assert a new rounding rule.
    per_year = {
        2025: {"value": 0.97, "unit": "raw", "period_end": "2025-01-26", "form": "10-K", "accession": "a25", "filed": "2025-02-26", "frame": None},
        2026: {"value": 1.04, "unit": "raw", "period_end": "2026-01-25", "form": "10-K", "accession": "a26", "filed": "2026-02-25", "frame": None},
    }
    monkeypatch.setattr(
        "formulas.get_asset_turnover",
        lambda ticker, fiscal_year, fiscal_period: per_year[fiscal_year],
    )
    result = get_multi_year_average("NVDA", "asset_turnover", 2025, 2026)
    assert result["value"] == (0.97 + 1.04) / 2
    assert result["unit"] == "raw"


def test_get_multi_year_average_averages_cash_to_assets_across_years(monkeypatch):
    per_year = {
        2024: {"value": 5.5, "unit": "percent", "period_end": "2024-06-30", "form": "10-K", "accession": "a24", "filed": "2024-07-30", "frame": None},
        2025: {"value": 4.9, "unit": "percent", "period_end": "2025-06-30", "form": "10-K", "accession": "a25", "filed": "2025-07-30", "frame": None},
    }
    monkeypatch.setattr(
        "formulas.get_cash_to_assets",
        lambda ticker, fiscal_year, fiscal_period: per_year[fiscal_year],
    )
    result = get_multi_year_average("MSFT", "cash_to_assets", 2024, 2025)
    assert result["value"] == round((5.5 + 4.9) / 2, 1)
    assert result["unit"] == "percent"


def test_get_multi_year_average_averages_raw_metric_across_years(monkeypatch):
    per_year = {
        2024: {"value": 383285000000, "unit": "USD", "period_end": "2024-09-28", "form": "10-K", "accession": "a24", "filed": "2024-11-01", "frame": None},
        2025: {"value": 391035000000, "unit": "USD", "period_end": "2025-09-27", "form": "10-K", "accession": "a25", "filed": "2025-10-31", "frame": None},
    }
    monkeypatch.setattr(
        "formulas.get_metric",
        lambda ticker, metric, fiscal_year, fiscal_period: per_year[fiscal_year],
    )
    result = get_multi_year_average("AAPL", "revenue", 2024, 2025)
    # Not rounded -- only percent-unit results are (matching
    # _compute_ratio_metric's own rounding convention); a dollar average
    # stays exact, like get_metric()'s own raw values do.
    assert result["value"] == (383285000000 + 391035000000) / 2
    assert result["unit"] == "USD"


def test_get_multi_year_average_returns_none_if_any_year_missing(monkeypatch):
    def fake_get_metric(ticker, metric, fiscal_year, fiscal_period):
        if fiscal_year == 2024:
            return None
        return {"value": 100, "unit": "USD", "period_end": "2025-09-27", "form": "10-K", "accession": "x", "filed": "2025-10-31", "frame": None}

    monkeypatch.setattr("formulas.get_metric", fake_get_metric)
    assert get_multi_year_average("AAPL", "revenue", 2024, 2025) is None


def test_get_multi_year_average_returns_none_for_single_year_range():
    # A 1-year "average" isn't a meaningful multi-year average -- and
    # this must return None WITHOUT calling get_metric/get_operating_margin
    # at all, checked before any fetching, not after collecting one value.
    assert get_multi_year_average("AAPL", "revenue", 2025, 2025) is None


def test_get_multi_year_average_returns_none_when_start_after_end():
    assert get_multi_year_average("AAPL", "revenue", 2025, 2023) is None


# ---------------------------------------------------------------------------
# get_gross_margin_all_companies / get_operating_margin_all_companies /
# get_net_margin_all_companies
# ---------------------------------------------------------------------------
def test_get_gross_margin_all_companies_computes_ratio_per_company(monkeypatch):
    monkeypatch.setattr(
        "formulas.get_gross_margin",
        lambda ticker, fiscal_year, fiscal_period, period_end_date: {
            "value": 74.9,
            "unit": "percent",
            "period_end": "2026-04-26",
            "form": "10-Q",
            "accession": "x",
            "filed": None,
            "frame": "CY2026Q1",
        },
    )

    def fake_get_frame(metric, frame):
        if metric == "gross_profit":
            return {"NVDA": {"value": 61157000000, "unit": "USD", "period_end": "2026-04-26", "accession": "a"}}
        return {"NVDA": {"value": 81615000000, "unit": "USD", "period_end": "2026-04-26", "accession": "b"}}

    monkeypatch.setattr("formulas.get_frame", fake_get_frame)
    result = get_gross_margin_all_companies("NVDA", period_end_date="2026-04-26")
    assert result == {
        "NVDA": {"value": 74.9, "unit": "percent", "period_end": "2026-04-26", "accession": "a"}
    }


def test_get_gross_margin_all_companies_excludes_company_with_mismatched_period_end(monkeypatch):
    monkeypatch.setattr(
        "formulas.get_gross_margin",
        lambda ticker, fiscal_year, fiscal_period, period_end_date: {
            "value": 74.9,
            "unit": "percent",
            "period_end": "2026-04-26",
            "form": "10-Q",
            "accession": "x",
            "filed": None,
            "frame": "CY2026Q1",
        },
    )

    def fake_get_frame(metric, frame):
        if metric == "gross_profit":
            return {
                "NVDA": {"value": 61157000000, "unit": "USD", "period_end": "2026-04-26", "accession": "a"},
                "AAPL": {"value": 54781000000, "unit": "USD", "period_end": "2026-03-28", "accession": "c"},
            }
        # AAPL's revenue frame entry has a DIFFERENT period_end than its
        # gross_profit entry -- the two tags aren't guaranteed to line
        # up per company, only checked.
        return {
            "NVDA": {"value": 81615000000, "unit": "USD", "period_end": "2026-04-26", "accession": "b"},
            "AAPL": {"value": 95400000000, "unit": "USD", "period_end": "2025-12-27", "accession": "d"},
        }

    monkeypatch.setattr("formulas.get_frame", fake_get_frame)
    result = get_gross_margin_all_companies("NVDA", period_end_date="2026-04-26")
    assert set(result.keys()) == {"NVDA"}


def test_get_gross_margin_all_companies_returns_empty_when_anchor_unavailable(monkeypatch):
    monkeypatch.setattr(
        "formulas.get_gross_margin",
        lambda ticker, fiscal_year, fiscal_period, period_end_date: None,
    )
    assert get_gross_margin_all_companies("NVDA", period_end_date="2026-04-26") == {}


def test_get_operating_margin_all_companies_computes_ratio_per_company(monkeypatch):
    monkeypatch.setattr(
        "formulas.get_operating_margin",
        lambda ticker, fiscal_year, fiscal_period, period_end_date: {
            "value": 60.0,
            "unit": "percent",
            "period_end": "2026-04-26",
            "form": "10-Q",
            "accession": "x",
            "filed": None,
            "frame": "CY2026Q1",
        },
    )

    def fake_get_frame(metric, frame):
        if metric == "operating_income":
            return {"NVDA": {"value": 48693000000, "unit": "USD", "period_end": "2026-04-26", "accession": "a"}}
        return {"NVDA": {"value": 81615000000, "unit": "USD", "period_end": "2026-04-26", "accession": "b"}}

    monkeypatch.setattr("formulas.get_frame", fake_get_frame)
    result = get_operating_margin_all_companies("NVDA", period_end_date="2026-04-26")
    assert result == {
        "NVDA": {"value": 59.7, "unit": "percent", "period_end": "2026-04-26", "accession": "a"}
    }


def test_get_operating_margin_all_companies_returns_empty_when_anchor_unavailable(monkeypatch):
    monkeypatch.setattr(
        "formulas.get_operating_margin",
        lambda ticker, fiscal_year, fiscal_period, period_end_date: None,
    )
    assert get_operating_margin_all_companies("NVDA", period_end_date="2026-04-26") == {}


def test_get_net_margin_all_companies_computes_ratio_per_company(monkeypatch):
    monkeypatch.setattr(
        "formulas.get_net_margin",
        lambda ticker, fiscal_year, fiscal_period, period_end_date: {
            "value": 45.0,
            "unit": "percent",
            "period_end": "2026-04-26",
            "form": "10-Q",
            "accession": "x",
            "filed": None,
            "frame": "CY2026Q1",
        },
    )

    def fake_get_frame(metric, frame):
        if metric == "net_income":
            return {"NVDA": {"value": 36000000000, "unit": "USD", "period_end": "2026-04-26", "accession": "a"}}
        return {"NVDA": {"value": 81615000000, "unit": "USD", "period_end": "2026-04-26", "accession": "b"}}

    monkeypatch.setattr("formulas.get_frame", fake_get_frame)
    result = get_net_margin_all_companies("NVDA", period_end_date="2026-04-26")
    assert result == {
        "NVDA": {"value": 44.1, "unit": "percent", "period_end": "2026-04-26", "accession": "a"}
    }


def test_get_net_margin_all_companies_returns_empty_when_anchor_unavailable(monkeypatch):
    monkeypatch.setattr(
        "formulas.get_net_margin",
        lambda ticker, fiscal_year, fiscal_period, period_end_date: None,
    )
    assert get_net_margin_all_companies("NVDA", period_end_date="2026-04-26") == {}
