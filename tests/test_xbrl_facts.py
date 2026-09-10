"""
Tests for xbrl_facts.py's period-entry disambiguation, since that's the
part with real bug risk (mirrors the retrieval-period-matching pitfalls
elsewhere in this project) -- everything else is thin plumbing around
verified-real fixture data captured from SEC's own companyconcept API.
"""

from xbrl_facts import (
    _duration_days,
    _latest_entry,
    _pick_entry,
    _pick_entry_by_end_date,
    fetch_concept,
    get_frame,
    get_metric,
    get_metric_all_companies,
    is_metric_tagged,
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

# Real entries from NVDA's Assets companyconcept response (CIK0001045810,
# fetched 2026-08-19) -- an "instant" (point-in-time balance) concept,
# unlike the two duration fixtures above: no "start" key at all. The
# Q1 FY27 10-Q's own balance sheet reports both the current quarter
# (Apr 26, 2026) AND a prior-fiscal-year-end comparative column (Jan 25,
# 2026, same value the 10-K itself reported) under its own fy=2027/fp=Q1
# label -- the same "one filing re-reports comparative data under its
# own label" pattern the duration fixtures already exercise, just for
# an instant concept.
NVDA_ASSETS_ENTRIES = [
    {"end": "2026-01-25", "val": 206803000000, "accn": "0001045810-26-000021", "fy": 2026, "fp": "FY", "form": "10-K", "filed": "2026-02-25"},
    {"end": "2026-01-25", "val": 206803000000, "accn": "0001045810-26-000052", "fy": 2027, "fp": "Q1", "form": "10-Q", "filed": "2026-05-20"},
    {"end": "2026-04-26", "val": 259474000000, "accn": "0001045810-26-000052", "fy": 2027, "fp": "Q1", "form": "10-Q", "filed": "2026-05-20"},
]


# ---------------------------------------------------------------------------
# _duration_days / instant-fact handling -- balance-sheet items (Assets,
# CashAndCashEquivalentsAtCarryingValue) are XBRL "instant" concepts with
# no `start`, unlike every metric this module supported before them
# (revenue, income, expenses, all "duration" concepts). Regression cases:
# nvda-total-assets-q1fy27, aapl-cash-equivalents-q3fy2026 -- adding
# these metrics crashed _duration_days with TypeError until this fix.
# ---------------------------------------------------------------------------
def test_duration_days_returns_none_for_instant_entry_without_start():
    assert _duration_days({"end": "2026-04-26", "val": 1}) is None


def test_pick_entry_matches_instant_entry_by_fy_fp_form_without_duration():
    # Both entries share end=2026-01-25, but only one has fy=2026/fp=FY/
    # form=10-K -- fy/fp/form matching alone is already unambiguous for
    # instant facts, no duration bucket needed.
    entry = _pick_entry(NVDA_ASSETS_ENTRIES, fiscal_year=2026, fiscal_period="FY")
    assert entry["val"] == 206803000000
    assert entry["accn"] == "0001045810-26-000021"


def test_pick_entry_by_end_date_matches_instant_entry_and_breaks_tie_toward_most_recent_filed():
    # Two entries share end=2026-01-25 (the 10-K's own figure, and the
    # following quarter's 10-Q restating it as a comparative) -- with no
    # duration to bucket by, the most-recently-filed one wins, same
    # tiebreak principle as the duration-fact case.
    entry = _pick_entry_by_end_date(NVDA_ASSETS_ENTRIES, "2026-01-25")
    assert entry["val"] == 206803000000
    assert entry["accn"] == "0001045810-26-000052"


def test_latest_entry_handles_instant_entries_without_crashing():
    entry = _latest_entry(NVDA_ASSETS_ENTRIES)
    assert entry["end"] == "2026-04-26"
    assert entry["val"] == 259474000000


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
        "fiscal_year": 2026,
        "fiscal_period": "Q3",
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
        "fiscal_year": 2026,
        "fiscal_period": "FY",
    }


def test_get_metric_resolves_total_assets_to_the_assets_tag(monkeypatch):
    # Regression case: nvda-total-assets-q1fy27. total_assets wasn't in
    # DEFAULT_METRIC_TAGS at all, so the model had no structured path
    # and fell back to search_filings, which can't find the balance
    # sheet table for this query -- confirmed the "Assets" tag is clean
    # (no per-company override needed) for all 5 companies before adding it.
    entries = [
        {"end": "2026-04-26", "val": 259474000000, "accn": "x", "fy": 2027, "fp": "Q1", "form": "10-Q", "filed": "2026-05-20"},
    ]

    def fake_fetch(ticker, tag):
        assert tag == "Assets"
        return {"units": {"USD": entries}}

    monkeypatch.setattr("xbrl_facts.fetch_concept", fake_fetch)
    result = get_metric("NVDA", "total_assets", fiscal_year=2027, fiscal_period="Q1")
    assert result["value"] == 259474000000


def test_get_metric_resolves_cash_and_equivalents_to_the_cash_tag(monkeypatch):
    # Regression case: aapl-cash-equivalents-q3fy2026. Retrieval COULD
    # find the right chunk for this one, but citation attribution still
    # failed -- routing it through the structured tool (like every other
    # DEFAULT_METRIC_TAGS metric) sidesteps attribution risk entirely
    # instead of trying to make unstructured citation more reliable.
    entries = [
        {"end": "2026-06-27", "val": 39544000000, "accn": "x", "fy": 2026, "fp": "Q3", "form": "10-Q", "filed": "2026-07-31"},
    ]

    def fake_fetch(ticker, tag):
        assert tag == "CashAndCashEquivalentsAtCarryingValue"
        return {"units": {"USD": entries}}

    monkeypatch.setattr("xbrl_facts.fetch_concept", fake_fetch)
    result = get_metric("AAPL", "cash_and_equivalents", fiscal_year=2026, fiscal_period="Q3")
    assert result["value"] == 39544000000


def test_get_metric_resolves_inventory_to_the_inventorynet_tag(monkeypatch):
    # Regression case: pltr-inventory-turnover-fy2025-refusal. Palantir
    # genuinely never tags InventoryNet at all (confirmed via
    # fetch_concept 404) -- verified the tag is clean (no per-company
    # override needed) for the 3 companies that DO tag it before adding.
    entries = [
        {"end": "2026-04-26", "val": 25797000000, "accn": "x", "fy": 2027, "fp": "Q1", "form": "10-Q", "filed": "2026-05-20"},
    ]

    def fake_fetch(ticker, tag):
        assert tag == "InventoryNet"
        return {"units": {"USD": entries}}

    monkeypatch.setattr("xbrl_facts.fetch_concept", fake_fetch)
    result = get_metric("NVDA", "inventory", fiscal_year=2027, fiscal_period="Q1")
    assert result["value"] == 25797000000


def test_is_metric_tagged_true_when_concept_has_data(monkeypatch):
    monkeypatch.setattr("xbrl_facts.fetch_concept", lambda ticker, tag: {"units": {"USD": []}})
    assert is_metric_tagged("NVDA", "inventory") is True


def test_is_metric_tagged_false_when_concept_never_tagged(monkeypatch):
    # PLTR's real behavior: fetch_concept returns None on a 404, distinct
    # from get_metric() returning None for a specific period that just
    # isn't available -- this is what lets _format_no_fact_message()
    # distinguish the two cases and explain the right one.
    monkeypatch.setattr("xbrl_facts.fetch_concept", lambda ticker, tag: None)
    assert is_metric_tagged("PLTR", "inventory") is False


def test_get_metric_exposes_the_matched_entrys_own_fiscal_year_and_period(monkeypatch):
    # Read off the matched entry's OWN fy/fp fields -- no independent
    # computation -- for get_yoy_growth() to anchor on later without
    # doing any date arithmetic itself.
    monkeypatch.setattr(
        "xbrl_facts.fetch_concept",
        lambda ticker, tag: {"units": {"USD": MSFT_RD_EXPENSE_ENTRIES}},
    )
    result = get_metric("MSFT", "rd_expense", period_end_date="2026-03-31")
    assert result["fiscal_year"] == 2026
    assert result["fiscal_period"] == "Q3"


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


def test_get_frame_resolves_tag_collision_deterministically_and_logs_it(monkeypatch):
    # review §15: if two distinct tags both report data for the SAME
    # ticker in the same frame (a company mid-transition between two
    # GAAP tags could plausibly show up in both tags' frame responses,
    # even though companies.json only maps it to one "current" tag), the
    # merge used to silently depend on Python's set iteration order --
    # untestable before, since tags_in_play was an unordered set.
    # tags_in_play is now sorted, so "AaaTag" (alphabetically first)
    # deterministically wins over "ZzzTag" regardless of hash order, and
    # the conflict itself is logged instead of silently discarded.
    aaa_response = {"data": [{"accn": "a", "cik": 320193, "end": "2026-03-28", "val": 100.0}]}
    zzz_response = {"data": [{"accn": "z", "cik": 320193, "end": "2026-03-28", "val": 200.0}]}

    monkeypatch.setattr(
        "xbrl_facts.fetch_frame", lambda tag, frame: aaa_response if tag == "AaaTag" else zzz_response
    )
    monkeypatch.setattr("xbrl_facts._tag_for", lambda ticker, metric: "AaaTag" if ticker == "AAPL" else "ZzzTag")
    calls = []
    monkeypatch.setattr("xbrl_facts.log_event", lambda category, **fields: calls.append((category, fields)))

    result = get_frame("revenue", "CY2026Q1")

    assert result["AAPL"]["value"] == 100.0
    assert len(calls) == 1
    category, fields = calls[0]
    assert category == "xbrl_tag_conflict"
    assert fields["ticker"] == "AAPL"
    assert fields["winning_tag"] == "AaaTag"
    assert fields["winning_value"] == 100.0
    assert fields["discarded_tag"] == "ZzzTag"
    assert fields["discarded_value"] == 200.0


def test_get_frame_does_not_log_a_conflict_for_a_same_tag_duplicate_entry(monkeypatch):
    # Found in code review: two entries for the same ticker within ONE
    # tag's own data list (e.g. an amended/restated filing appearing
    # twice under a different accession) isn't a cross-tag disagreement
    # and must not be mislabeled as one -- first-entry-wins, silently,
    # matching this same-tag case's pre-existing (unlogged) behavior.
    duplicate_response = {
        "data": [
            {"accn": "original", "cik": 320193, "end": "2026-03-28", "val": 100.0},
            {"accn": "amended", "cik": 320193, "end": "2026-03-28", "val": 105.0},
        ]
    }
    monkeypatch.setattr("xbrl_facts.fetch_frame", lambda tag, frame: duplicate_response)
    monkeypatch.setattr("xbrl_facts._tag_for", lambda ticker, metric: "SameTag")
    calls = []
    monkeypatch.setattr("xbrl_facts.log_event", lambda category, **fields: calls.append((category, fields)))

    result = get_frame("revenue", "CY2026Q1")

    assert result["AAPL"]["value"] == 100.0
    assert calls == []


def test_get_frame_prefers_tickers_own_designated_tag_over_alphabetical_order(monkeypatch):
    # Found in code review: a plain alphabetical-sort tie-break is
    # arbitrary, not principled -- get_frame() already has the
    # objectively correct answer for a given ticker available via
    # _tag_for(ticker, metric) (it's what built tags_in_play in the
    # first place) and was ignoring it. Without this, a ticker whose own
    # designated tag happens to sort SECOND would silently keep a wrong
    # value from a different tag that incidentally also reports its CIK
    # (e.g. a company mid-transition between two GAAP tags), forever,
    # regardless of which is actually correct.
    aaa_response = {"data": [{"accn": "wrong", "cik": 320193, "end": "2026-03-28", "val": 999.0}]}
    zzz_response = {"data": [{"accn": "right", "cik": 320193, "end": "2026-03-28", "val": 100.0}]}

    monkeypatch.setattr(
        "xbrl_facts.fetch_frame", lambda tag, frame: aaa_response if tag == "AaaTag" else zzz_response
    )
    # AAPL's own designated tag is "ZzzTag" -- the one that sorts SECOND.
    monkeypatch.setattr("xbrl_facts._tag_for", lambda ticker, metric: "ZzzTag" if ticker == "AAPL" else "AaaTag")
    calls = []
    monkeypatch.setattr("xbrl_facts.log_event", lambda category, **fields: calls.append((category, fields)))

    result = get_frame("revenue", "CY2026Q1")

    assert result["AAPL"]["value"] == 100.0
    assert len(calls) == 1
    category, fields = calls[0]
    assert category == "xbrl_tag_conflict"
    assert fields["winning_tag"] == "ZzzTag"
    assert fields["discarded_tag"] == "AaaTag"


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


def test_get_metric_all_companies_duration_metric_never_tries_other_companies(monkeypatch):
    # Regression guard (found in code review 2026-09-07): yesterday's
    # shipped fix applied a cross-company frame-borrowing fallback to
    # EVERY metric, including duration ones -- today's redesign removes
    # it for duration metrics too (the same borrowed-window bug applies
    # equally: a different company's own fiscal_year/fiscal_period
    # number represents a different real calendar window). Only the
    # requested ticker should ever be queried for a duration metric,
    # even when its own frame is missing -- never a fallback to another
    # company.
    checked_tickers = []

    def fake_get_metric(ticker, metric, fiscal_year, fiscal_period, period_end_date):
        checked_tickers.append(ticker)
        return {"value": 1, "unit": "USD", "period_end": "2026-04-26", "frame": None}

    monkeypatch.setattr("xbrl_facts.get_metric", fake_get_metric)

    result = get_metric_all_companies("NVDA", "gross_profit", fiscal_year=2026, fiscal_period="Q1")

    assert checked_tickers == ["NVDA"]
    assert result == {}


# ---------------------------------------------------------------------------
# get_metric_all_companies -- instant metrics (total_assets/
# cash_and_equivalents/inventory) take a DIFFERENT path from duration
# metrics (gross_profit etc. above), added 2026-09-07 to replace a
# same-day regression: borrowing another company's SEC-assigned frame
# for an instant concept silently substitutes a DIFFERENT requested
# time window (verified live: anchoring NVDA's own frame-less FY2026
# total_assets against MSFT's frame returned NVDA's Q2 FY2027 balance
# mislabeled as FY2026). Real financial-analysis practice ("calendariza-
# tion") explicitly does not apply calendar-window alignment to balance-
# sheet figures the way it does to income-statement ones -- so instant
# metrics are resolved independently per company instead, no frame, no
# anchor requirement at all. Duration metrics (tested above) are
# unaffected -- calendar-window bucketing via frames is the standard,
# correct technique for THOSE and already works.
# ---------------------------------------------------------------------------
def test_get_metric_all_companies_resolves_instant_metrics_independently_per_company(monkeypatch):
    def fake_get_metric(ticker, metric, fiscal_year, fiscal_period, period_end_date):
        return {
            "AAPL": {"value": 359241000000, "unit": "USD", "period_end": "2025-09-27", "form": "10-K"},
            "MSFT": {"value": 619003000000, "unit": "USD", "period_end": "2025-06-30", "form": "10-K"},
        }.get(ticker)

    monkeypatch.setattr("xbrl_facts.get_metric", fake_get_metric)
    monkeypatch.setattr("xbrl_facts.load_companies", lambda: {"AAPL": {}, "MSFT": {}, "NVDA": {}})

    result = get_metric_all_companies("AAPL", "total_assets", fiscal_year=2025, fiscal_period="FY")

    # Each company's own real (differing) period_end/value, unmodified --
    # no forced shared calendar snapshot.
    assert result["AAPL"]["period_end"] == "2025-09-27"
    assert result["MSFT"]["period_end"] == "2025-06-30"
    assert result["AAPL"]["value"] == 359241000000
    assert result["MSFT"]["value"] == 619003000000


def test_get_metric_all_companies_instant_metric_skips_companies_with_no_data(monkeypatch):
    def fake_get_metric(ticker, metric, fiscal_year, fiscal_period, period_end_date):
        if ticker == "PLTR":
            return None  # Palantir doesn't tag inventory at all
        return {"value": 1, "unit": "USD", "period_end": "2026-01-01", "form": "10-K"}

    monkeypatch.setattr("xbrl_facts.get_metric", fake_get_metric)
    monkeypatch.setattr("xbrl_facts.load_companies", lambda: {"AAPL": {}, "PLTR": {}})

    result = get_metric_all_companies("AAPL", "inventory", fiscal_year=2026, fiscal_period="FY")

    assert set(result.keys()) == {"AAPL"}


def test_get_metric_all_companies_instant_metric_never_calls_get_frame(monkeypatch):
    # Regression guard: instant metrics must never touch the frames API
    # at all, not even as a fallback -- that's the exact mechanism that
    # caused the 2026-09-07 regression.
    monkeypatch.setattr(
        "xbrl_facts.get_metric",
        lambda ticker, metric, fiscal_year, fiscal_period, period_end_date: {
            "value": 1, "unit": "USD", "period_end": "2026-01-01", "form": "10-K",
        },
    )
    calls = []
    monkeypatch.setattr("xbrl_facts.get_frame", lambda metric, frame: calls.append((metric, frame)) or {})
    monkeypatch.setattr("xbrl_facts.load_companies", lambda: {"AAPL": {}, "MSFT": {}})

    get_metric_all_companies("AAPL", "cash_and_equivalents", fiscal_year=2026, fiscal_period="FY")

    assert calls == []

