"""
Tests for discover_tags.py -- a dev-time discovery aid over SEC's
companyfacts API (every tag a company has ever reported, in one
response), distinct from xbrl_facts.py's runtime companyconcept path
(fetch_concept, one tag per call). Built to replace "discover a new
metric tag one eval failure at a time" with "list what's actually
available up front."
"""

from datetime import date, timedelta

from discover_tags import fetch_company_facts, list_tags

RECENT_END = (date.today() - timedelta(days=30)).isoformat()
STALE_END = (date.today() - timedelta(days=1000)).isoformat()

FAKE_COMPANY_FACTS = {
    "facts": {
        "dei": {
            "EntityCommonStockSharesOutstanding": {
                "units": {"shares": [{"end": RECENT_END, "val": 1}]}
            },
        },
        "us-gaap": {
            "InventoryNet": {
                "units": {"USD": [{"end": RECENT_END, "val": 1}]}
            },
            "AccountsPayableCurrent": {
                "units": {"USD": [{"end": STALE_END, "val": 2}]}
            },
            "Revenues": {
                "units": {"USD": [{"end": STALE_END, "val": 3}]}
            },
        },
    }
}


def test_list_tags_returns_all_us_gaap_tags_by_default(monkeypatch):
    monkeypatch.setattr("discover_tags.fetch_company_facts", lambda ticker: FAKE_COMPANY_FACTS)
    assert list_tags("AAPL") == ["AccountsPayableCurrent", "InventoryNet", "Revenues"]


def test_list_tags_filters_by_keyword_case_insensitive(monkeypatch):
    monkeypatch.setattr("discover_tags.fetch_company_facts", lambda ticker: FAKE_COMPANY_FACTS)
    assert list_tags("AAPL", keyword="inventory") == ["InventoryNet"]


def test_list_tags_recent_only_excludes_tags_with_no_entry_in_the_last_year(monkeypatch):
    monkeypatch.setattr("discover_tags.fetch_company_facts", lambda ticker: FAKE_COMPANY_FACTS)
    # InventoryNet has a recent entry; AccountsPayableCurrent and Revenues
    # only have entries from ~1000 days ago -- same staleness pitfall
    # documented in xbrl_facts.py's DEFAULT_METRIC_TAGS comment (a tag
    # existing at all doesn't mean the company still reports it).
    assert list_tags("AAPL", recent_only=True) == ["InventoryNet"]


def test_list_tags_reads_a_different_taxonomy_when_given(monkeypatch):
    monkeypatch.setattr("discover_tags.fetch_company_facts", lambda ticker: FAKE_COMPANY_FACTS)
    assert list_tags("AAPL", taxonomy="dei") == ["EntityCommonStockSharesOutstanding"]


def test_list_tags_returns_empty_for_unknown_taxonomy(monkeypatch):
    monkeypatch.setattr("discover_tags.fetch_company_facts", lambda ticker: FAKE_COMPANY_FACTS)
    assert list_tags("AAPL", taxonomy="ifrs-full") == []


def test_fetch_company_facts_caches_to_disk_and_skips_refetch(monkeypatch, tmp_path):
    import discover_tags

    monkeypatch.setattr(discover_tags, "CACHE_DIR", tmp_path)
    calls = []

    class _FakeResponse:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"facts": {"us-gaap": {}}}

    def fake_get(url, headers):
        calls.append(url)
        return _FakeResponse()

    monkeypatch.setattr(discover_tags.requests, "get", fake_get)
    monkeypatch.setattr(discover_tags.time, "sleep", lambda s: None)

    fetch_company_facts("NVDA")
    fetch_company_facts("NVDA")

    assert len(calls) == 1  # second call served from disk cache


def test_fetch_company_facts_uses_the_tickers_cik_in_the_url(monkeypatch, tmp_path):
    import discover_tags

    monkeypatch.setattr(discover_tags, "CACHE_DIR", tmp_path)
    calls = []

    class _FakeResponse:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"facts": {"us-gaap": {}}}

    def fake_get(url, headers):
        calls.append(url)
        return _FakeResponse()

    monkeypatch.setattr(discover_tags.requests, "get", fake_get)
    monkeypatch.setattr(discover_tags.time, "sleep", lambda s: None)

    fetch_company_facts("NVDA")

    assert calls == ["https://data.sec.gov/api/xbrl/companyfacts/CIK0001045810.json"]
