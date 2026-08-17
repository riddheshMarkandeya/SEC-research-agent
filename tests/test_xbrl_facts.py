"""
Tests for xbrl_facts.py's period-entry disambiguation, since that's the
part with real bug risk (mirrors the retrieval-period-matching pitfalls
elsewhere in this project) -- everything else is thin plumbing around
verified-real fixture data captured from SEC's own companyconcept API.
"""

from xbrl_facts import _pick_entry, get_gross_margin, get_metric, fetch_concept, resolve_fiscal_period

# Trimmed, real entries from NVDA's GrossProfit companyconcept response
# (CIK0001045810, fetched 2026-08-16) -- one filing (FY2026 10-K)
# re-reports THREE fiscal years' worth of the same concept, all sharing
# fy=2026/fp="FY", distinguished only by `end`.
NVDA_GROSS_PROFIT_ENTRIES = [
    {"start": "2023-01-30", "end": "2024-01-28", "val": 44301000000, "accn": "0001045810-26-000021", "fy": 2026, "fp": "FY", "form": "10-K", "filed": "2026-02-25"},
    {"start": "2024-01-29", "end": "2025-01-26", "val": 97858000000, "accn": "0001045810-26-000021", "fy": 2026, "fp": "FY", "form": "10-K", "filed": "2026-02-25"},
    {"start": "2025-01-27", "end": "2026-01-25", "val": 153463000000, "accn": "0001045810-26-000021", "fy": 2026, "fp": "FY", "form": "10-K", "filed": "2026-02-25"},
]

# Trimmed, real entries from MSFT's ResearchAndDevelopmentExpense
# companyconcept response (CIK0000789019, fetched 2026-08-16) -- one
# filing (Q3 FY26 10-Q) reports FOUR entries under the same fy=2026/
# fp="Q3": the current quarter, the prior-year comparative quarter (same
# ~90-day duration, earlier end), and two 9-month year-to-date figures
# (same end date as the quarter, but ~270-day duration).
MSFT_RD_EXPENSE_ENTRIES = [
    {"start": "2024-07-01", "end": "2025-03-31", "val": 23659000000, "accn": "0001193125-26-191507", "fy": 2026, "fp": "Q3", "form": "10-Q"},
    {"start": "2025-01-01", "end": "2025-03-31", "val": 8198000000, "accn": "0001193125-26-191507", "fy": 2026, "fp": "Q3", "form": "10-Q"},
    {"start": "2025-07-01", "end": "2026-03-31", "val": 25565000000, "accn": "0001193125-26-191507", "fy": 2026, "fp": "Q3", "form": "10-Q"},
    {"start": "2026-01-01", "end": "2026-03-31", "val": 8915000000, "accn": "0001193125-26-191507", "fy": 2026, "fp": "Q3", "form": "10-Q"},
]


def test_resolve_fiscal_period_nvda_q1_fy2027_from_calendar_date():
    # NVDA's own 10-Q says this exact date is "the first quarter of
    # fiscal year 2027" (fiscal_year_end_month=1) -- the real bug this
    # fixes: the calendar year (2026) is NOT the fiscal year here.
    fy, fp = resolve_fiscal_period("NVDA", "2026-04-26")
    assert (fy, fp) == (2027, "Q1")


def test_resolve_fiscal_period_crm_q1_fy2027_from_calendar_date():
    fy, fp = resolve_fiscal_period("CRM", "2026-04-30")
    assert (fy, fp) == (2027, "Q1")


def test_resolve_fiscal_period_pltr_calendar_year_company_matches_directly():
    # PLTR's fiscal_year_end_month=12, so fiscal year == calendar year --
    # a case where the naive calendar-year guess the model was making
    # happens to be right, which is exactly why the bug went unnoticed
    # until a January-fiscal-year-end company was tested.
    fy, fp = resolve_fiscal_period("PLTR", "2025-12-31")
    assert (fy, fp) == (2025, "Q4")


def test_get_metric_with_empty_string_period_end_date_falls_back_to_fiscal_args(monkeypatch):
    # Live-observed model behavior: for a question with no specific
    # calendar date ("total revenue for 2025"), the model called this
    # with period_end_date="" instead of omitting it, which used to
    # crash date.fromisoformat with an unhandled ValueError. An empty
    # string must be treated as "not provided", falling back to
    # whatever fiscal_year/fiscal_period were also passed.
    monkeypatch.setattr(
        "xbrl_facts.fetch_concept",
        lambda ticker, tag: {"units": {"USD": NVDA_GROSS_PROFIT_ENTRIES}},
    )
    result = get_metric("NVDA", "gross_profit", fiscal_year=2026, fiscal_period="FY", period_end_date="")
    assert result["value"] == 153463000000


def test_get_metric_with_malformed_period_end_date_returns_none_not_crash(monkeypatch):
    monkeypatch.setattr(
        "xbrl_facts.fetch_concept",
        lambda ticker, tag: {"units": {"USD": NVDA_GROSS_PROFIT_ENTRIES}},
    )
    assert get_metric("NVDA", "gross_profit", period_end_date="2025") is None


def test_get_gross_margin_with_empty_string_period_end_date_falls_back_to_fiscal_args(monkeypatch):
    revenue_entries = [
        {"start": "2025-01-27", "end": "2026-01-25", "val": 215938000000, "accn": "x", "fy": 2026, "fp": "FY", "form": "10-K"},
    ]

    def fake_fetch(ticker, tag):
        return {"units": {"USD": NVDA_GROSS_PROFIT_ENTRIES if tag == "GrossProfit" else revenue_entries}}

    monkeypatch.setattr("xbrl_facts.fetch_concept", fake_fetch)
    result = get_gross_margin("NVDA", fiscal_year=2026, fiscal_period="FY", period_end_date="")
    assert result["value"] == 71.1


def test_get_metric_with_period_end_date_matches_equivalent_fiscal_call(monkeypatch):
    monkeypatch.setattr(
        "xbrl_facts.fetch_concept",
        lambda ticker, tag: {"units": {"USD": MSFT_RD_EXPENSE_ENTRIES}},
    )
    by_date = get_metric("MSFT", "rd_expense", period_end_date="2026-03-31")
    by_fiscal_label = get_metric("MSFT", "rd_expense", fiscal_year=2026, fiscal_period="Q3")
    assert by_date == by_fiscal_label == {
        "value": 8915000000,
        "unit": "USD",
        "period_end": "2026-03-31",
        "form": "10-Q",
        "accession": "0001193125-26-191507",
        "filed": None,
    }


def test_pick_entry_annual_picks_latest_end_among_comparative_years():
    entry = _pick_entry(NVDA_GROSS_PROFIT_ENTRIES, fiscal_year=2026, fiscal_period="FY")
    assert entry["val"] == 153463000000
    assert entry["end"] == "2026-01-25"


def test_pick_entry_quarterly_excludes_ytd_and_prior_year_comparative():
    entry = _pick_entry(MSFT_RD_EXPENSE_ENTRIES, fiscal_year=2026, fiscal_period="Q3")
    assert entry["val"] == 8915000000
    assert entry["end"] == "2026-03-31"


def test_pick_entry_returns_none_when_fiscal_year_not_present():
    entry = _pick_entry(NVDA_GROSS_PROFIT_ENTRIES, fiscal_year=2030, fiscal_period="FY")
    assert entry is None


def test_pick_entry_returns_none_when_period_kind_mismatches_form():
    # Same fy/fp values but requesting FY against 10-Q-shaped entries
    # (wrong duration/form) shouldn't accidentally match a quarter.
    entry = _pick_entry(MSFT_RD_EXPENSE_ENTRIES, fiscal_year=2026, fiscal_period="FY")
    assert entry is None


def test_get_metric_returns_none_when_concept_not_tagged(monkeypatch):
    monkeypatch.setattr("xbrl_facts.fetch_concept", lambda ticker, tag: None)
    assert get_metric("PLTR", "revenue", fiscal_year=2025, fiscal_period="FY") is None


def test_get_metric_reads_through_fetch_concept(monkeypatch):
    monkeypatch.setattr(
        "xbrl_facts.fetch_concept",
        lambda ticker, tag: {"units": {"USD": NVDA_GROSS_PROFIT_ENTRIES}},
    )
    result = get_metric("NVDA", "gross_profit", fiscal_year=2026, fiscal_period="FY")
    assert result == {
        "value": 153463000000,
        "unit": "USD",
        "period_end": "2026-01-25",
        "form": "10-K",
        "accession": "0001045810-26-000021",
        "filed": "2026-02-25",
    }


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


def test_fetch_concept_caches_to_disk_and_skips_refetch(monkeypatch, tmp_path):
    import xbrl_facts

    monkeypatch.setattr(xbrl_facts, "CACHE_DIR", tmp_path)
    calls = []

    class _FakeResponse:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"units": {"USD": []}}

    def fake_get(url, headers):
        calls.append(url)
        return _FakeResponse()

    monkeypatch.setattr(xbrl_facts.requests, "get", fake_get)
    monkeypatch.setattr(xbrl_facts.time, "sleep", lambda s: None)

    fetch_concept("NVDA", "GrossProfit")
    fetch_concept("NVDA", "GrossProfit")

    assert len(calls) == 1  # second call served from disk cache


def test_fetch_concept_returns_none_on_404(monkeypatch, tmp_path):
    import xbrl_facts

    monkeypatch.setattr(xbrl_facts, "CACHE_DIR", tmp_path)

    class _FakeResponse:
        status_code = 404

        def raise_for_status(self):
            raise AssertionError("should not be called on a 404")

    monkeypatch.setattr(xbrl_facts.requests, "get", lambda url, headers: _FakeResponse())
    monkeypatch.setattr(xbrl_facts.time, "sleep", lambda s: None)

    assert fetch_concept("PLTR", "Revenues") is None
