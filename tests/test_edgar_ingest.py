"""
Unit tests for edgar_ingest.py's get_filing_url() -- the only pure,
deterministic logic in this module (everything else is a live SEC
fetch). Covers the (ticker, accession) -> real EDGAR filing URL lookup
built for mcp_server.py's `source` blocks (Week 6): given an already-
ingested filing's _meta.json (which already stores `cik` and
`primaryDocument`, written by this same module), construct the exact
URL fetch_filing_html() would have fetched -- no new network calls.
"""

import json

import requests

import edgar_ingest


def _write_meta(tmp_path, ticker, accession, cik, primary_document):
    ticker_dir = tmp_path / ticker
    ticker_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "form": "10-K",
        "accessionNumber": accession,
        "filingDate": "2025-10-31",
        "primaryDocument": primary_document,
        "reportDate": "2025-09-27",
        "ticker": ticker,
        "cik": cik,
    }
    (ticker_dir / f"{accession}_meta.json").write_text(json.dumps(meta), encoding="utf-8")


def test_get_filing_url_builds_real_edgar_url(monkeypatch, tmp_path):
    monkeypatch.setattr(edgar_ingest, "OUTPUT_DIR", tmp_path)
    _write_meta(tmp_path, "AAPL", "0000320193-25-000079", "0000320193", "aapl-20250927.htm")

    url = edgar_ingest.get_filing_url("AAPL", "0000320193-25-000079")

    assert url == "https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/aapl-20250927.htm"


def test_get_filing_url_strips_leading_zeros_from_cik(monkeypatch, tmp_path):
    monkeypatch.setattr(edgar_ingest, "OUTPUT_DIR", tmp_path)
    _write_meta(tmp_path, "NVDA", "0001045810-26-000021", "0001045810", "nvda-20260125.htm")

    url = edgar_ingest.get_filing_url("NVDA", "0001045810-26-000021")

    assert "/data/1045810/" in url
    assert "/data/0001045810/" not in url


def test_get_filing_url_returns_none_when_meta_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(edgar_ingest, "OUTPUT_DIR", tmp_path)

    url = edgar_ingest.get_filing_url("AAPL", "0000000000-00-000000")

    assert url is None


def test_fetch_filing_html_url_matches_get_filing_url(monkeypatch, tmp_path):
    """Both functions must build the identical URL from the same
    (cik, accession, primary_doc) -- get_filing_url() exists specifically
    to reconstruct, after the fact, the exact URL fetch_filing_html()
    already used to fetch this filing during ingestion. If these two
    ever drift apart, an MCP citation's sec_url could point at a
    different document than the one actually indexed."""
    monkeypatch.setattr(edgar_ingest, "OUTPUT_DIR", tmp_path)
    cik, accession, primary_doc = "0000789019", "0001193125-26-323660", "msft-20250630.htm"
    _write_meta(tmp_path, "MSFT", accession, cik, primary_doc)

    looked_up = edgar_ingest.get_filing_url("MSFT", accession)
    fetched_from = edgar_ingest._filing_document_url(cik, accession, primary_doc)

    assert looked_up == fetched_from


def test_main_continues_to_next_company_when_get_filing_list_fails(monkeypatch, tmp_path):
    """get_filing_list(cik) (review §7) used to be unguarded, unlike the
    per-filing loop right below it -- one company's network failure
    aborted ingestion for every subsequent company too. get_filing_list
    and fetch_filing_html/parse_filing are the live SEC boundary and are
    mocked here so this test exercises main()'s own deterministic
    resilience logic, not a real network call."""
    monkeypatch.setattr(edgar_ingest, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(edgar_ingest, "REQUEST_DELAY_SECONDS", 0)
    monkeypatch.setattr(
        edgar_ingest,
        "load_companies",
        lambda: {
            "BAD": {"cik": "0000000001"},
            "GOOD": {"cik": "0000000002"},
        },
    )

    def fake_get_filing_list(cik):
        if cik == "0000000001":
            raise requests.exceptions.ConnectionError("SEC unreachable")
        return [{
            "form": "10-K",
            "accessionNumber": "0000000002-26-000001",
            "filingDate": "2026-01-01",
            "primaryDocument": "good-20260101.htm",
            "reportDate": "2025-12-31",
        }]

    monkeypatch.setattr(edgar_ingest, "get_filing_list", fake_get_filing_list)
    monkeypatch.setattr(edgar_ingest, "fetch_filing_html", lambda cik, accession, primary_doc: "<html></html>")
    monkeypatch.setattr(edgar_ingest, "parse_filing", lambda html: ("some text", []))

    edgar_ingest.main()  # must not raise despite BAD's get_filing_list failure

    assert not (tmp_path / "BAD" / "0000000002-26-000001_meta.json").exists()
    assert (tmp_path / "GOOD" / "0000000002-26-000001_meta.json").exists()


def _assert_main_survives_get_filing_list_failure(monkeypatch, tmp_path, exception):
    """Shared body for the malformed-response resilience tests below --
    code review on the §7 fix flagged that catching only
    requests.RequestException was narrower than get_filing_list()'s real
    failure surface (it can also raise ValueError/json.JSONDecodeError
    on a malformed body, or KeyError/TypeError on an unexpected
    submissions schema), which is why main() now uses a broad, commented
    `except Exception` there instead -- these tests each raise a
    different one of those types to confirm none of them still slip
    through and abort the whole run."""
    monkeypatch.setattr(edgar_ingest, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(edgar_ingest, "REQUEST_DELAY_SECONDS", 0)
    monkeypatch.setattr(
        edgar_ingest,
        "load_companies",
        lambda: {
            "BAD": {"cik": "0000000001"},
            "GOOD": {"cik": "0000000002"},
        },
    )

    def fake_get_filing_list(cik):
        if cik == "0000000001":
            raise exception
        return [{
            "form": "10-K",
            "accessionNumber": "0000000002-26-000001",
            "filingDate": "2026-01-01",
            "primaryDocument": "good-20260101.htm",
            "reportDate": "2025-12-31",
        }]

    monkeypatch.setattr(edgar_ingest, "get_filing_list", fake_get_filing_list)
    monkeypatch.setattr(edgar_ingest, "fetch_filing_html", lambda cik, accession, primary_doc: "<html></html>")
    monkeypatch.setattr(edgar_ingest, "parse_filing", lambda html: ("some text", []))

    edgar_ingest.main()  # must not raise despite BAD's failure

    assert not (tmp_path / "BAD" / "0000000002-26-000001_meta.json").exists()
    assert (tmp_path / "GOOD" / "0000000002-26-000001_meta.json").exists()


def test_main_continues_to_next_company_when_get_filing_list_hits_malformed_json(monkeypatch, tmp_path):
    _assert_main_survives_get_filing_list_failure(monkeypatch, tmp_path, ValueError("Expecting value"))


def test_main_continues_to_next_company_when_get_filing_list_hits_unexpected_schema(monkeypatch, tmp_path):
    _assert_main_survives_get_filing_list_failure(monkeypatch, tmp_path, KeyError("filings"))
