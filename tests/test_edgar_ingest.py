"""
Unit tests for edgar_ingest.py's pure, deterministic logic --
get_filing_url() and parse_filing() (everything else in this module is
a live SEC fetch). get_filing_url() covers the (ticker, accession) ->
real EDGAR filing URL lookup built for mcp_server.py's `source` blocks
(Week 6): given an already-ingested filing's _meta.json (which already
stores `cik` and `primaryDocument`, written by this same module),
construct the exact URL fetch_filing_html() would have fetched -- no
new network calls. parse_filing() (review §13) takes raw HTML strings
and returns (text, tables) with no I/O or global state, so it's tested
directly with inline HTML literals, no fixtures needed -- it had zero
test coverage before this despite being pure, unlike every other
finding in this project's TDD-scope rule.
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

    assert url is not None
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


# ---------------------------------------------------------------------------
# parse_filing (review §13)
# ---------------------------------------------------------------------------
def test_parse_filing_extracts_simple_table_and_leaves_marker():
    html = "<html><body><p>Revenue grew.</p><table><tr><td>Revenue</td><td>100</td></tr></table></body></html>"
    text, tables = edgar_ingest.parse_filing(html)
    assert tables == [{"table_index": 0, "rows": [["Revenue", "100"]]}]
    assert "[TABLE_0]" in text
    assert "Revenue grew." in text


def test_parse_filing_multiple_tables_indices_align_with_markers():
    html = (
        "<html><body>"
        "<table><tr><td>A</td></tr></table>"
        "<p>middle</p>"
        "<table><tr><td>B</td></tr></table>"
        "</body></html>"
    )
    text, tables = edgar_ingest.parse_filing(html)
    assert [t["table_index"] for t in tables] == [0, 1]
    assert "[TABLE_0]" in text
    assert "[TABLE_1]" in text
    assert text.index("[TABLE_0]") < text.index("middle") < text.index("[TABLE_1]")


def test_parse_filing_drops_empty_layout_table_without_marker():
    html = "<html><body><table><tr><td></td><td>  </td></tr></table><p>real content</p></body></html>"
    text, tables = edgar_ingest.parse_filing(html)
    assert tables == []
    assert "[TABLE_0]" not in text
    assert "real content" in text


def test_parse_filing_skips_entirely_empty_rows_within_table():
    html = (
        "<html><body><table>"
        "<tr><td>Revenue</td><td>100</td></tr>"
        "<tr><td></td><td></td></tr>"
        "<tr><td>Costs</td><td>50</td></tr>"
        "</table></body></html>"
    )
    _, tables = edgar_ingest.parse_filing(html)
    assert tables == [{"table_index": 0, "rows": [["Revenue", "100"], ["Costs", "50"]]}]


def test_parse_filing_collapses_internal_whitespace_in_cell_text():
    html = "<html><body><table><tr><td>Revenue\n\t 100</td></tr></table></body></html>"
    _, tables = edgar_ingest.parse_filing(html)
    assert tables[0]["rows"] == [["Revenue 100"]]


def test_parse_filing_collapses_excess_blank_lines_in_prose():
    html = "<html><body><p>first</p>\n\n\n\n\n<p>second</p></body></html>"
    text, _ = edgar_ingest.parse_filing(html)
    assert "\n\n\n" not in text
    assert "first" in text and "second" in text


def test_parse_filing_strips_header_footer_noise_lines():
    html = "<html><body><p>Apple Inc. | Q3 2026 Form 10-Q | 13</p><p>real content here</p></body></html>"
    text, _ = edgar_ingest.parse_filing(html)
    assert "Form 10-Q" not in text
    assert "real content here" in text


def test_parse_filing_strips_header_footer_noise_at_document_edges():
    # Found in code review (round 2, 2026-09-10) while writing the tests
    # above: text.strip() runs BEFORE the header/footer-stripping block,
    # so removing a noise line sitting at the very start or end of the
    # document left a stray leading/trailing newline behind -- the block
    # had no second .strip() of its own to clean up after itself.
    html = "<html><body><p>Apple Inc. | Q3 2026 Form 10-Q | 13</p><p>real content here</p></body></html>"
    text, _ = edgar_ingest.parse_filing(html)
    assert text == text.strip()
    assert text == "real content here"


def test_parse_filing_does_not_strip_prose_with_single_pipe():
    html = "<html><body><p>Segment A | Segment B combined revenue grew this quarter.</p></body></html>"
    text, _ = edgar_ingest.parse_filing(html)
    assert "Segment A | Segment B combined revenue grew this quarter." in text


def test_parse_filing_returns_empty_tables_list_when_no_tables_present():
    html = "<html><body><p>Just prose, no tables here.</p></body></html>"
    text, tables = edgar_ingest.parse_filing(html)
    assert tables == []
    assert "Just prose, no tables here." in text


def test_parse_filing_strips_leading_and_trailing_whitespace():
    html = "<html><body>\n\n  <p>content</p>  \n\n</body></html>"
    text, _ = edgar_ingest.parse_filing(html)
    assert text == text.strip()
    assert text.startswith("content")
