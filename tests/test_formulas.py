"""
Tests for formulas.py's derived metrics (margins, YoY growth). Moved out
of test_xbrl_facts.py alongside the formula-registry split -- see
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
for agent.py's MARGIN_METRIC_FUNCTIONS.
"""

from formulas import (
    get_gross_margin,
    get_gross_margin_all_companies,
    get_net_margin,
    get_net_margin_all_companies,
    get_operating_margin,
    get_operating_margin_all_companies,
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
