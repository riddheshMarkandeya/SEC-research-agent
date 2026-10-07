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

import itertools
import json

import pytest
import requests

from sec_agent.sources import edgar_ingest
from sec_agent.sources.companies import CompanyInfo


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
            "BAD": {"name": "Bad", "cik": "0000000001", "fiscal_year_end_month": 12},
            "GOOD": {"name": "Good", "cik": "0000000002", "fiscal_year_end_month": 12},
        },
    )

    def fake_get_filing_list(cik, fiscal_year_end_month):
        if cik == "0000000001":
            raise requests.exceptions.ConnectionError("SEC unreachable")
        return edgar_ingest.FilingSelection(
            filings=[{
                "form": "10-K",
                "accessionNumber": "0000000002-26-000001",
                "filingDate": "2026-01-01",
                "primaryDocument": "good-20260101.htm",
                "reportDate": "2025-12-31",
            }],
            pages=1,
            skipped_bad_row=0,
        )

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
            "BAD": {"name": "Bad", "cik": "0000000001", "fiscal_year_end_month": 12},
            "GOOD": {"name": "Good", "cik": "0000000002", "fiscal_year_end_month": 12},
        },
    )

    def fake_get_filing_list(cik, fiscal_year_end_month):
        if cik == "0000000001":
            raise exception
        return edgar_ingest.FilingSelection(
            filings=[{
                "form": "10-K",
                "accessionNumber": "0000000002-26-000001",
                "filingDate": "2026-01-01",
                "primaryDocument": "good-20260101.htm",
                "reportDate": "2025-12-31",
            }],
            pages=1,
            skipped_bad_row=0,
        )

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


# ---------------------------------------------------------------------------
# Filing selection: fiscal-year cutoff, submissions paging
# ---------------------------------------------------------------------------
_COLUMNS = ("form", "accessionNumber", "filingDate", "primaryDocument", "reportDate")


_ACCESSIONS = itertools.count(1000)


def _acc(n):
    return f"0000000001-24-{n:06d}"


def _page(n):
    return f"CIK0000000001-submissions-{n:03d}.json"


def _row(form, report_date, filing_date="2026-01-01", accession=None):
    return {
        "form": form,
        "accessionNumber": accession or _acc(next(_ACCESSIONS)),
        "filingDate": filing_date,
        "primaryDocument": "doc.htm",
        "reportDate": report_date,
    }


def _block(rows):
    """Rows back into the submissions API's column-array shape."""
    block = {key: [r[key] for r in rows] for key in _COLUMNS}
    block["acceptanceDateTime"] = ["x"] * len(rows)  # extra columns are ignored
    return block


def test_rows_turns_column_arrays_into_row_dicts():
    rows = [_row("10-K", "2025-09-27"), _row("8-K", "")]
    assert edgar_ingest._rows(_block(rows)) == rows


def test_rows_of_empty_block_is_empty():
    assert edgar_ingest._rows(_block([])) == []


@pytest.mark.parametrize(
    "year_end_month, report_dates, kept",
    [
        # AAPL: FY2024 runs Oct 2023 - Sep 2024.
        (9, ["2024-09-28", "2023-12-30", "2023-09-30"], ["2024-09-28", "2023-12-30"]),
        # NVDA/CRM: the quarter ended 2023-04-30 is already FY2024.
        (1, ["2023-04-30", "2023-01-31"], ["2023-04-30"]),
        # MSFT: FY2024 runs Jul 2023 - Jun 2024.
        (6, ["2023-09-30", "2023-06-30"], ["2023-09-30"]),
        (12, ["2024-03-31", "2023-12-31"], ["2024-03-31"]),
    ],
)
def test_select_filings_cutoff_by_fiscal_year_end_month(year_end_month, report_dates, kept):
    rows = [_row("10-Q", report_date) for report_date in report_dates]
    selection = edgar_ingest.select_filings(rows, year_end_month, 2024)
    assert [r["reportDate"] for r in selection.filings] == kept


def test_select_filings_keeps_only_10k_and_10q():
    rows = [_row("10-K/A", "2024-12-31"), _row("8-K", "2024-12-31"), _row("10-Q", "2024-09-30")]
    selection = edgar_ingest.select_filings(rows, 12, 2024)
    assert [r["form"] for r in selection.filings] == ["10-Q"]


def test_select_filings_skips_empty_and_malformed_dates_and_logs_them(monkeypatch):
    events = []
    monkeypatch.setattr(edgar_ingest, "log_event", lambda category, **fields: events.append((category, fields)))
    rows = [_row("10-Q", "", accession=_acc(1)), _row("10-K", "2024-13-45", accession=_acc(2)),
            _row("10-Q", "2024-09-30", accession=_acc(3))]

    selection = edgar_ingest.select_filings(rows, 12, 2024)

    assert [r["accessionNumber"] for r in selection.filings] == [_acc(3)]
    assert selection.skipped_bad_row == 2
    assert [(c, f["accession"]) for c, f in events] == [("ingest_row_skipped", _acc(1)), ("ingest_row_skipped", _acc(2))]
    assert all(f["reason"] == "bad_report_date" for _, f in events)
    assert events[1][1]["report_date"] == "2024-13-45"  # the rejected value is in the log


def test_select_filings_skips_an_accession_outside_secs_format_and_logs_it(monkeypatch):
    # It becomes a file name, so a path separator or ".." must never get through.
    events = []
    monkeypatch.setattr(edgar_ingest, "log_event", lambda category, **fields: events.append((category, fields)))
    rows = [_row("10-Q", "2024-09-30", accession=r"..\evil"), _row("10-Q", "2024-06-30", accession="0000000001/24")]

    selection = edgar_ingest.select_filings(rows, 12, 2024)

    assert selection.filings == []
    assert selection.skipped_bad_row == 2
    assert [f["reason"] for _, f in events] == ["bad_accession", "bad_accession"]


def test_select_filings_skips_null_values_rather_than_failing_the_company(monkeypatch):
    events = []
    monkeypatch.setattr(edgar_ingest, "log_event", lambda category, **fields: events.append((category, fields)))
    rows = [_row("10-Q", "2024-09-30"), _row("10-Q", None), _row("10-Q", "2024-06-30"), _row("10-K", "2024-12-31")]
    rows[2]["accessionNumber"] = None
    rows[3]["filingDate"] = None

    selection = edgar_ingest.select_filings(rows, 12, 2024)

    assert len(selection.filings) == 1 and selection.skipped_bad_row == 3
    assert [f["reason"] for _, f in events] == ["non_string_field"] * 3


def test_select_filings_skips_a_malformed_filing_date_which_would_misjudge_the_oldest_row(monkeypatch):
    # Kept, the "" filingDate would sort as the oldest row, and its FY2023
    # reportDate would stop paging though the newest row is still FY2024.
    events = []
    monkeypatch.setattr(edgar_ingest, "log_event", lambda category, **fields: events.append((category, fields)))
    rows = [_row("10-K", "2023-12-31", filing_date=""), _row("10-Q", "2024-03-31", filing_date="2024-05-01")]

    selection = edgar_ingest.select_filings(rows, 12, 2024)

    assert selection.filings == [rows[1]]
    assert selection.need_older is True
    assert [(f["reason"], f["filing_date"]) for _, f in events] == [("bad_filing_date", "")]


@pytest.mark.parametrize("field", ["filingDate", "reportDate"])
def test_select_filings_skips_a_non_canonical_date_that_would_sort_wrongly(monkeypatch, field):
    # fromisoformat takes 20240630, but as a string it sorts after 2024-12-31.
    events = []
    monkeypatch.setattr(edgar_ingest, "log_event", lambda category, **fields: events.append((category, fields)))
    row = {**_row("10-Q", "2024-06-30", filing_date="2024-08-01"), field: "20240630"}

    assert edgar_ingest.select_filings([row], 12, 2024).filings == []
    expected = "bad_filing_date" if field == "filingDate" else "bad_report_date"
    assert [f["reason"] for _, f in events] == [expected]


@pytest.mark.parametrize("document", ["", "../other.htm", "sub/doc.htm", ".hidden"])
def test_select_filings_skips_a_primary_document_that_isnt_a_plain_file_name(monkeypatch, document):
    # An empty name would fetch the filing's directory listing and save it as the filing.
    events = []
    monkeypatch.setattr(edgar_ingest, "log_event", lambda category, **fields: events.append((category, fields)))
    row = {**_row("10-Q", "2024-09-30"), "primaryDocument": document}

    assert edgar_ingest.select_filings([row], 12, 2024).filings == []
    assert [(f["reason"], f["primary_document"]) for _, f in events] == [("bad_primary_document", document)]


def test_accession_check_takes_ascii_digits_only():
    assert edgar_ingest._ACCESSION_PATTERN.fullmatch("0000000001-24-000001")
    assert not edgar_ingest._ACCESSION_PATTERN.fullmatch(chr(0xFF10) * 10 + "-24-000001")  # fullwidth zeros


def test_rows_refuses_columns_of_unequal_length():
    block = _block([_row("10-K", "2025-09-27"), _row("10-Q", "2025-06-28")])
    block["reportDate"].pop()
    with pytest.raises(ValueError):
        edgar_ingest._rows(block)


def test_select_filings_needs_older_page_when_oldest_filed_row_is_inside_cutoff():
    # Filing-date order decides "oldest", not report date.
    rows = [_row("10-Q", "2024-06-30", filing_date="2024-08-01"),
            _row("10-Q", "2024-03-31", filing_date="2024-05-01")]
    assert edgar_ingest.select_filings(rows, 12, 2024).need_older is True


def test_select_filings_stops_when_oldest_filed_row_is_before_cutoff():
    rows = [_row("10-Q", "2024-03-31", filing_date="2024-05-01"),
            _row("10-K", "2023-12-31", filing_date="2024-02-01")]
    assert edgar_ingest.select_filings(rows, 12, 2024).need_older is False


def test_select_filings_page_with_no_10k_or_10q_rows_needs_older():
    rows = [_row("8-K", ""), _row("4", "")]
    selection = edgar_ingest.select_filings(rows, 12, 2024)
    assert selection.filings == []
    assert selection.need_older is True


def test_collect_filings_reads_older_pages_until_cutoff_reached():
    recent = _block([_row("10-Q", "2024-06-30", filing_date="2024-08-01", accession=_acc(11))])
    pages = {
        _page(1): _block([_row("10-Q", "2024-03-31", filing_date="2024-05-01", accession=_acc(21)),
                           _row("10-K", "2023-12-31", filing_date="2024-02-01", accession=_acc(22))]),
        _page(2): _block([_row("10-Q", "2023-09-30", filing_date="2023-11-01", accession=_acc(23))]),
    }
    fetched = []

    def fetch_page(name):
        fetched.append(name)
        return pages[name]

    older = [{"name": _page(2), "filingTo": "2023-12-31"}, {"name": _page(1), "filingTo": "2024-06-30"}]
    result = edgar_ingest.collect_filings(recent, older, fetch_page, 12, 2024)

    assert fetched == [_page(1)]  # newest older page first; p2 never needed
    assert [f["accessionNumber"] for f in result.filings] == [_acc(11), _acc(21)]
    assert result.pages == 2


def test_collect_filings_does_not_page_when_recent_reaches_cutoff():
    recent = _block([_row("10-Q", "2024-03-31", filing_date="2024-05-01"),
                     _row("10-K", "2023-12-31", filing_date="2024-02-01")])

    def fetch_page(name):
        raise AssertionError("no older page should be fetched")

    result = edgar_ingest.collect_filings(recent, [{"name": _page(1), "filingTo": "2023-01-01"}], fetch_page, 12, 2024)
    assert result.pages == 1
    assert len(result.filings) == 1


def test_collect_filings_stops_at_last_page_and_sums_bad_dates():
    recent = _block([_row("10-Q", "", accession=_acc(31)), _row("10-Q", "2024-06-30", filing_date="2024-08-01")])
    pages = {_page(1): _block([_row("8-K", "")])}

    result = edgar_ingest.collect_filings(recent, [{"name": _page(1), "filingTo": "2024-01-01"}],
                                          pages.__getitem__, 12, 2024)

    assert result.pages == 2  # both read, then no pages left
    assert len(result.filings) == 1
    assert result.skipped_bad_row == 1


def test_page_url_accepts_secs_page_names_and_refuses_anything_else():
    assert edgar_ingest._page_url(_page(1)) == f"https://data.sec.gov/submissions/{_page(1)}"
    for name in ("../other.json", "CIK0000000001-submissions-001.json/../x", ""):
        with pytest.raises(ValueError, match="page name"):
            edgar_ingest._page_url(name)


# ---------------------------------------------------------------------------
# Skip already-ingested filings, per-ticker ingestion
# ---------------------------------------------------------------------------
def _write_filing_files(out_dir, accession, which=("meta", "text", "tables")):
    out_dir.mkdir(parents=True, exist_ok=True)
    suffixes = {"meta": "_meta.json", "text": "_text.txt", "tables": "_tables.json"}
    for key in which:
        (out_dir / f"{accession}{suffixes[key]}").write_text("x", encoding="utf-8")


def test_already_ingested_true_only_when_all_three_files_exist(tmp_path):
    _write_filing_files(tmp_path, "acc")
    assert edgar_ingest._already_ingested(tmp_path, "acc") is True


def test_already_ingested_false_when_any_file_missing(tmp_path):
    for missing in ("meta", "text", "tables"):
        out_dir = tmp_path / missing
        _write_filing_files(out_dir, "acc", which=[k for k in ("meta", "text", "tables") if k != missing])
        assert edgar_ingest._already_ingested(out_dir, "acc") is False


_ACME: CompanyInfo = {"name": "Acme", "cik": "0000000009", "fiscal_year_end_month": 12}


def _setup_ingest_ticker(monkeypatch, filings, fail_accessions=()):
    monkeypatch.setattr(edgar_ingest, "REQUEST_DELAY_SECONDS", 0)
    events = []
    monkeypatch.setattr(edgar_ingest, "log_event", lambda category, **fields: events.append((category, fields)))
    monkeypatch.setattr(
        edgar_ingest, "get_filing_list",
        lambda cik, fyem: edgar_ingest.FilingSelection(filings=filings, pages=2, skipped_bad_row=1),
    )
    fetched = []

    def fake_fetch(cik, accession, primary_doc):
        fetched.append(accession)
        if accession in fail_accessions:
            raise requests.exceptions.HTTPError("503")
        return "<html></html>"

    monkeypatch.setattr(edgar_ingest, "fetch_filing_html", fake_fetch)
    monkeypatch.setattr(edgar_ingest, "parse_filing", lambda html: ("some text", [{"table_index": 0, "rows": [["a"]]}]))
    return events, fetched


def test_ingest_ticker_skips_present_saves_new_and_logs_counts(monkeypatch, tmp_path):
    out_dir = tmp_path / "ACME"
    _write_filing_files(out_dir, "old-1")
    filings = [_row("10-Q", "2024-06-30", accession="new-1"), _row("10-K", "2023-12-31", accession="old-1")]
    events, fetched = _setup_ingest_ticker(monkeypatch, filings)

    counts = edgar_ingest._ingest_ticker("ACME", _ACME, out_dir)

    assert fetched == ["new-1"]
    assert (out_dir / "old-1_meta.json").read_text(encoding="utf-8") == "x"  # untouched
    meta = json.loads((out_dir / "new-1_meta.json").read_text(encoding="utf-8"))
    assert meta["ticker"] == "ACME" and meta["num_tables"] == 1
    assert counts == {"selected": 2, "skipped_present": 1, "saved": 1, "failed": 0}
    list_event = next(f for c, f in events if c == "ingest_filing_list")
    assert list_event == {"ticker": "ACME", "pages": 2, "selected": 2, "skipped_present": 1, "skipped_bad_row": 1}


def test_ingest_ticker_logs_failed_filing_and_writes_nothing_for_it(monkeypatch, tmp_path):
    out_dir = tmp_path / "ACME"
    filings = [_row("10-Q", "2024-06-30", accession="bad-1"), _row("10-Q", "2024-03-31", accession="ok-1")]
    events, _ = _setup_ingest_ticker(monkeypatch, filings, fail_accessions={"bad-1"})

    counts = edgar_ingest._ingest_ticker("ACME", _ACME, out_dir)

    assert counts == {"selected": 2, "skipped_present": 0, "saved": 1, "failed": 1}
    assert not list(out_dir.glob("bad-1_*"))
    failed = [f for c, f in events if c == "ingest_filing_failed"]
    assert failed == [{"ticker": "ACME", "accession": "bad-1", "error": "HTTPError: 503"}]


def test_ingest_ticker_waits_before_every_request_including_after_a_failure(monkeypatch, tmp_path):
    # A run of failed fetches (SEC rate-limiting, say) must not become a burst.
    filings = [_row("10-Q", "2024-06-30", accession="bad-1"), _row("10-Q", "2024-03-31", accession="bad-2")]
    _setup_ingest_ticker(monkeypatch, filings, fail_accessions={"bad-1", "bad-2"})
    sleeps = []
    monkeypatch.setattr(edgar_ingest.time, "sleep", sleeps.append)

    edgar_ingest._ingest_ticker("ACME", _ACME, tmp_path / "ACME")

    assert len(sleeps) == 3  # the filing list, then each filing


def test_ingest_ticker_returns_none_and_logs_when_filing_list_fails(monkeypatch, tmp_path):
    events = []
    monkeypatch.setattr(edgar_ingest, "log_event", lambda category, **fields: events.append((category, fields)))

    def boom(cik, fyem):
        raise KeyError("filings")

    monkeypatch.setattr(edgar_ingest, "get_filing_list", boom)

    result = edgar_ingest._ingest_ticker("ACME", _ACME, tmp_path / "ACME")

    assert result is None
    assert events == [("ingest_filing_list_failed", {"ticker": "ACME", "error": "KeyError: 'filings'"})]


def test_ingest_ticker_progress_output_encodes_on_a_cp1252_console(monkeypatch, tmp_path, capsys):
    # A Windows console defaults to cp1252; a character outside it makes
    # print() raise mid-run, after some filings are already saved.
    filings = [_row("10-Q", "2024-06-30", accession="bad-1"), _row("10-Q", "2024-03-31", accession="ok-1")]
    _setup_ingest_ticker(monkeypatch, filings, fail_accessions={"bad-1"})
    edgar_ingest._ingest_ticker("ACME", _ACME, tmp_path / "ACME")

    def boom(cik, fyem):
        raise KeyError("filings")

    monkeypatch.setattr(edgar_ingest, "get_filing_list", boom)
    edgar_ingest._ingest_ticker("OTHER", _ACME, tmp_path / "OTHER")

    out = capsys.readouterr().out
    assert "OK Saved" in out and "FAILED:" in out and "FAILED to fetch filing list" in out
    out.encode("cp1252")


def test_save_filing_writes_meta_last(monkeypatch, tmp_path):
    """A crash between files must never leave a meta-only filing: meta goes
    last, so _already_ingested's three-file check and the chunker agree."""
    order = []
    real_write_text = type(tmp_path).write_text

    def spy(self, *args, **kwargs):
        order.append(self.name)
        return real_write_text(self, *args, **kwargs)

    monkeypatch.setattr(type(tmp_path), "write_text", spy)
    edgar_ingest._save_filing(tmp_path, "acc", {"form": "10-Q"}, "text", [])
    assert order[-1] == "acc_meta.json"
    assert len(order) == 3
