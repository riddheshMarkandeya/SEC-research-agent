"""
Tests for xbrl_facts.py's period-entry disambiguation, since that's the
part with real bug risk (mirrors the retrieval-period-matching pitfalls
elsewhere in this project) -- everything else is thin plumbing around
verified-real fixture data captured from SEC's own companyconcept API.
"""

from xbrl_facts import (
    _latest_entry,
    _pick_entry,
    _pick_entry_by_end_date,
    get_frame,
    get_gross_margin,
    get_gross_margin_all_companies,
    get_metric,
    get_metric_all_companies,
    fetch_concept,
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


def test_pick_entry_by_end_date_ignores_wrong_fy_fp_labels_entirely():
    # Reproduces the shape of the real NVDA bug (a January-fiscal-year-end
    # company's calendar-year-vs-fiscal-year mismatch) at the entry-
    # selection layer directly: an entry mislabeled with the "wrong but
    # valid" fy/fp a naive calendar-year guess would produce sits right
    # next to the correct one. Matching on `end` alone must pick the
    # right entry regardless of either one's fy/fp label -- there's no
    # computed label in the selection path at all to get wrong.
    entries = [
        {"start": "2025-01-28", "end": "2025-04-27", "val": 111, "accn": "prior-year-quarter", "fy": 2026, "fp": "Q1", "form": "10-Q", "filed": "2025-05-20"},
        {"start": "2026-01-26", "end": "2026-04-26", "val": 222, "accn": "correct-quarter", "fy": 2027, "fp": "Q1", "form": "10-Q", "filed": "2026-05-20"},
    ]
    entry = _pick_entry_by_end_date(entries, "2026-04-26")
    assert entry["val"] == 222
    assert entry["accn"] == "correct-quarter"


def test_pick_entry_by_end_date_prefers_quarter_over_annual_at_same_end_date():
    entries = [
        {"start": "2025-01-27", "end": "2026-01-25", "val": 999, "accn": "annual", "fy": 2026, "fp": "FY", "form": "10-K", "filed": "2026-02-25"},
        {"start": "2025-11-01", "end": "2026-01-25", "val": 111, "accn": "quarter", "fy": 2026, "fp": "Q4", "form": "10-Q", "filed": "2026-02-20"},
    ]
    entry = _pick_entry_by_end_date(entries, "2026-01-25")
    assert entry["val"] == 111
    assert entry["accn"] == "quarter"


def test_pick_entry_by_end_date_falls_back_to_annual_when_no_quarter_exists():
    # The common case for these companies: a fiscal-year-end date usually
    # has only an annual-duration entry (Q4 isn't separately tagged).
    entries = [
        {"start": "2025-01-27", "end": "2026-01-25", "val": 999, "accn": "annual", "fy": 2026, "fp": "FY", "form": "10-K", "filed": "2026-02-25"},
    ]
    entry = _pick_entry_by_end_date(entries, "2026-01-25")
    assert entry["val"] == 999


def test_pick_entry_by_end_date_breaks_ties_toward_most_recently_filed():
    entries = [
        {"start": "2025-01-01", "end": "2025-03-31", "val": 100, "accn": "original", "fy": 2025, "fp": "Q1", "form": "10-Q", "filed": "2025-05-01"},
        {"start": "2025-01-01", "end": "2025-03-31", "val": 105, "accn": "restated", "fy": 2026, "fp": "Q1", "form": "10-Q", "filed": "2026-02-15"},
    ]
    entry = _pick_entry_by_end_date(entries, "2025-03-31")
    assert entry["accn"] == "restated"


def test_pick_entry_by_end_date_returns_none_when_no_entry_matches():
    assert _pick_entry_by_end_date(NVDA_GROSS_PROFIT_ENTRIES, "2099-01-01") is None


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


def test_get_metric_with_fiscal_year_end_calendar_date_returns_annual_value(monkeypatch):
    # A real latent bug the old resolve_fiscal_period()-based approach
    # had: for NVDA (fiscal_year_end_month=1), passing its FY2026 end
    # date "2026-01-25" as period_end_date computed fiscal_period="Q4"
    # (fiscal-quarter arithmetic has no "FY" case, only Q1-Q4), which
    # then searched for a 10-Q-shaped quarterly entry that doesn't exist
    # -- silently returning None for a perfectly valid annual-figure
    # question phrased with a calendar date instead of "fiscal year
    # 2026". Matching directly on `end` sidesteps this entirely.
    monkeypatch.setattr(
        "xbrl_facts.fetch_concept",
        lambda ticker, tag: {"units": {"USD": NVDA_GROSS_PROFIT_ENTRIES}},
    )
    result = get_metric("NVDA", "gross_profit", period_end_date="2026-01-25")
    assert result["value"] == 153463000000


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
        "frame": None,
    }


def test_latest_entry_picks_max_end_date():
    entry = _latest_entry(NVDA_GROSS_PROFIT_ENTRIES)
    assert entry["end"] == "2026-01-25"
    assert entry["val"] == 153463000000


def test_latest_entry_breaks_ties_toward_shorter_duration():
    # MSFT_RD_EXPENSE_ENTRIES has two entries sharing the same max end
    # date (2026-03-31): a 9-month year-to-date figure and the 3-month
    # quarter itself. "Most recent quarter" should mean the quarter,
    # not the longer cumulative figure that happens to end the same day.
    entry = _latest_entry(MSFT_RD_EXPENSE_ENTRIES)
    assert entry["end"] == "2026-03-31"
    assert entry["val"] == 8915000000


def test_latest_entry_empty_list_returns_none():
    assert _latest_entry([]) is None


def test_get_metric_with_no_period_given_returns_latest(monkeypatch):
    # Real, live-found gap: a cross-company comparison question asked
    # for "their most recent quarter" -- no calendar date or fiscal
    # label to give get_metric(), so the model called the comparison
    # tool with no period at all, which used to silently return nothing
    # (fiscal_year=None never matched anything in _pick_entry) and the
    # model abandoned the whole comparison rather than retrying.
    monkeypatch.setattr(
        "xbrl_facts.fetch_concept",
        lambda ticker, tag: {"units": {"USD": NVDA_GROSS_PROFIT_ENTRIES}},
    )
    result = get_metric("NVDA", "gross_profit")
    assert result["value"] == 153463000000
    assert result["period_end"] == "2026-01-25"


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
        "frame": None,
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


# ---------------------------------------------------------------------------
# frames — get_frame / get_metric_all_companies
# ---------------------------------------------------------------------------
# Trimmed, real entries from the GrossProfit CY2026Q1 frames response
# (fetched 2026-08-17), filtered to our 5 covered CIKs. Confirms the
# frames endpoint really does return meaningfully different period
# boundaries per company (AAPL ends 2026-03-28, NVDA ends 2026-04-26)
# all bucketed under the same nominal frame -- not four separate calls.
GROSS_PROFIT_CY2026Q1_FRAME = {
    "data": [
        {"accn": "0000320193-26-000013", "cik": 320193, "entityName": "Apple Inc.", "start": "2025-12-28", "end": "2026-03-28", "val": 54781000000},
        {"accn": "0001193125-26-191507", "cik": 789019, "entityName": "MICROSOFT CORPORATION", "start": "2026-01-01", "end": "2026-03-31", "val": 56058000000},
        {"accn": "0001045810-26-000052", "cik": 1045810, "entityName": "NVIDIA CORP", "start": "2026-01-26", "end": "2026-04-26", "val": 61157000000},
        {"accn": "0001108524-26-000127", "cik": 1108524, "entityName": "Salesforce, Inc.", "start": "2026-02-01", "end": "2026-04-30", "val": 8563000000},
        {"accn": "0001321655-26-000028", "cik": 1321655, "entityName": "Palantir Technologies Inc.", "start": "2026-01-01", "end": "2026-03-31", "val": 1416785000},
        # A non-covered filer, to confirm it gets filtered out.
        {"accn": "0000012345-26-000001", "cik": 999999999, "entityName": "SOME OTHER COMPANY", "start": "2026-01-01", "end": "2026-03-31", "val": 1000000},
    ]
}


def test_get_frame_filters_to_covered_companies_only(monkeypatch):
    monkeypatch.setattr("xbrl_facts.fetch_frame", lambda tag, frame: GROSS_PROFIT_CY2026Q1_FRAME)
    result = get_frame("gross_profit", "CY2026Q1")
    assert set(result.keys()) == {"AAPL", "MSFT", "NVDA", "CRM", "PLTR"}
    assert result["NVDA"]["value"] == 61157000000
    assert result["NVDA"]["period_end"] == "2026-04-26"
    assert result["AAPL"]["period_end"] == "2026-03-28"  # different from NVDA's, same frame


def test_get_frame_merges_across_distinct_tags_for_divergent_metrics(monkeypatch):
    # "revenue" uses a different tag for NVDA than the other four (see
    # DEFAULT_METRIC_TAGS/METRIC_TAG_OVERRIDES) -- a single-tag frames
    # query would silently omit NVDA. Simulate two distinct frame
    # responses, one per tag, and confirm both contribute companies.
    nvda_only = {"data": [{"accn": "x", "cik": 1045810, "end": "2026-04-26", "val": 81615000000}]}
    everyone_else = {
        "data": [
            {"accn": "y", "cik": 320193, "end": "2026-03-28", "val": 95400000000},
            {"accn": "z", "cik": 789019, "end": "2026-03-31", "val": 70066000000},
        ]
    }

    def fake_fetch_frame(tag, frame):
        return nvda_only if tag == "Revenues" else everyone_else

    monkeypatch.setattr("xbrl_facts.fetch_frame", fake_fetch_frame)
    result = get_frame("revenue", "CY2026Q1")
    assert "NVDA" in result
    assert "AAPL" in result
    assert "MSFT" in result


def test_get_frame_skips_tags_with_no_frame_data(monkeypatch):
    monkeypatch.setattr("xbrl_facts.fetch_frame", lambda tag, frame: None)
    assert get_frame("gross_profit", "CY2026Q1") == {}


def test_get_metric_all_companies_anchors_on_the_given_tickers_frame(monkeypatch):
    monkeypatch.setattr(
        "xbrl_facts.get_metric",
        lambda ticker, metric, fiscal_year, fiscal_period, period_end_date: {
            "value": 61157000000,
            "unit": "USD",
            "period_end": "2026-04-26",
            "form": "10-Q",
            "accession": "x",
            "filed": "2026-05-20",
            "frame": "CY2026Q1",
        },
    )
    # get_frame is mocked directly here (not fetch_frame), so this just
    # checks get_metric_all_companies calls it with the anchor's own
    # SEC-assigned frame, not a self-computed one.
    calls = []
    monkeypatch.setattr(
        "xbrl_facts.get_frame",
        lambda metric, frame: calls.append((metric, frame)) or {},
    )
    get_metric_all_companies("NVDA", "gross_profit", fiscal_year=2026, fiscal_period="Q1")
    assert calls == [("gross_profit", "CY2026Q1")]


def test_get_metric_all_companies_returns_empty_when_anchor_unavailable(monkeypatch):
    monkeypatch.setattr(
        "xbrl_facts.get_metric",
        lambda ticker, metric, fiscal_year, fiscal_period, period_end_date: None,
    )
    assert get_metric_all_companies("NVDA", "gross_profit", fiscal_year=2026, fiscal_period="Q1") == {}


def test_get_metric_all_companies_returns_empty_when_anchor_has_no_frame(monkeypatch):
    monkeypatch.setattr(
        "xbrl_facts.get_metric",
        lambda ticker, metric, fiscal_year, fiscal_period, period_end_date: {
            "value": 1,
            "unit": "USD",
            "period_end": "2026-04-26",
            "form": "10-Q",
            "accession": "x",
            "filed": None,
            "frame": None,
        },
    )
    assert get_metric_all_companies("NVDA", "gross_profit", fiscal_year=2026, fiscal_period="Q1") == {}


def test_get_gross_margin_all_companies_computes_ratio_per_company(monkeypatch):
    monkeypatch.setattr(
        "xbrl_facts.get_gross_margin",
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

    monkeypatch.setattr("xbrl_facts.get_frame", fake_get_frame)
    result = get_gross_margin_all_companies("NVDA", period_end_date="2026-04-26")
    assert result == {
        "NVDA": {"value": 74.9, "unit": "percent", "period_end": "2026-04-26", "accession": "a"}
    }


def test_get_gross_margin_all_companies_excludes_company_with_mismatched_period_end(monkeypatch):
    monkeypatch.setattr(
        "xbrl_facts.get_gross_margin",
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

    monkeypatch.setattr("xbrl_facts.get_frame", fake_get_frame)
    result = get_gross_margin_all_companies("NVDA", period_end_date="2026-04-26")
    assert set(result.keys()) == {"NVDA"}


def test_get_gross_margin_all_companies_returns_empty_when_anchor_unavailable(monkeypatch):
    monkeypatch.setattr(
        "xbrl_facts.get_gross_margin",
        lambda ticker, fiscal_year, fiscal_period, period_end_date: None,
    )
    assert get_gross_margin_all_companies("NVDA", period_end_date="2026-04-26") == {}
