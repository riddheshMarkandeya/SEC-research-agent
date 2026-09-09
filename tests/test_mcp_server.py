"""
Unit tests for mcp_server.py's pure logic: source-block construction
and the text-fragment excerpt used to deep-link search_filings
citations (Week 6). The actual MCP protocol/HTTP wiring (Server,
streamable_http_app) is live-only -- exercised by a manual verification
script against a real running server, documented in PROJECT_CONTEXT.md,
not mocked into unit tests here (same carve-out as hybrid_search/
Ollama/Gemini elsewhere in this project). main()'s own shutdown-flush
control flow (below) is the one exception -- it's deterministic once
uvicorn.run/build_app/flush are mocked, even though what it wraps is
live-only.
"""

import pytest

import mcp_server


# ---------------------------------------------------------------------------
# _text_fragment_excerpt
# ---------------------------------------------------------------------------
def test_text_fragment_excerpt_returns_short_text_unchanged():
    text = "Apple's revenue increased due to strong iPhone sales."
    assert mcp_server._text_fragment_excerpt(text) == text


def test_text_fragment_excerpt_truncates_long_text_at_word_boundary():
    text = "word " * 40  # 200 chars, well past the 100-char default
    excerpt = mcp_server._text_fragment_excerpt(text)
    assert len(excerpt) <= 100
    assert not excerpt.endswith("wor")  # never cuts mid-word
    assert text.startswith(excerpt)


def test_text_fragment_excerpt_strips_leading_whitespace():
    assert mcp_server._text_fragment_excerpt("   Revenue grew.") == "Revenue grew."


def test_text_fragment_excerpt_none_for_empty_text():
    assert mcp_server._text_fragment_excerpt("") is None
    assert mcp_server._text_fragment_excerpt("   ") is None


def test_text_fragment_excerpt_none_when_excerpt_contains_table_marker():
    text = "<TABLE>\n1 | 2 | 3\n</TABLE>"
    assert mcp_server._text_fragment_excerpt(text) is None


def test_text_fragment_excerpt_kept_when_table_marker_is_past_the_excerpt():
    # A chunk that's mostly prose with a table further in should still
    # get an excerpt from its (table-free) opening -- the whole-chunk
    # `contains_table` flag would wrongly suppress this case.
    text = "A" * 90 + " then a table follows <TABLE>1|2</TABLE>"
    excerpt = mcp_server._text_fragment_excerpt(text)
    assert excerpt is not None
    assert "<TABLE>" not in excerpt


# ---------------------------------------------------------------------------
# _chunk_source
# ---------------------------------------------------------------------------
def _chunk_metadata(**overrides):
    meta = {
        "ticker": "AAPL",
        "form": "10-K",
        "reportDate": "2025-09-27",
        "filingDate": "2025-10-31",
        "accessionNumber": "0000320193-25-000079",
    }
    meta.update(overrides)
    return meta


def test_chunk_source_includes_text_fragment_when_url_and_excerpt_available(monkeypatch):
    monkeypatch.setattr(mcp_server, "get_filing_url", lambda ticker, accession: "https://example.com/filing.htm")

    source = mcp_server._chunk_source(_chunk_metadata(), "iPhone net sales increased year over year.")

    assert source["ticker"] == "AAPL"
    assert source["sec_url"].startswith("https://example.com/filing.htm#:~:text=")
    assert "iPhone" in source["sec_url"]


def test_chunk_source_omits_fragment_when_excerpt_is_table_only(monkeypatch):
    monkeypatch.setattr(mcp_server, "get_filing_url", lambda ticker, accession: "https://example.com/filing.htm")

    source = mcp_server._chunk_source(_chunk_metadata(), "<TABLE>1|2|3</TABLE>")

    assert source["sec_url"] == "https://example.com/filing.htm"


def test_chunk_source_omits_sec_url_when_filing_url_unavailable(monkeypatch):
    monkeypatch.setattr(mcp_server, "get_filing_url", lambda ticker, accession: None)

    source = mcp_server._chunk_source(_chunk_metadata(), "Some chunk text.")

    assert "sec_url" not in source


# ---------------------------------------------------------------------------
# _fact_source
# ---------------------------------------------------------------------------
def test_fact_source_includes_form_and_filed_when_present(monkeypatch):
    monkeypatch.setattr(mcp_server, "get_filing_url", lambda ticker, accession: "https://example.com/f.htm")
    fact = {"period_end": "2025-09-27", "accession": "0000320193-25-000079", "form": "10-K", "filed": "2025-10-31"}

    source = mcp_server._fact_source("AAPL", fact)

    assert source["form"] == "10-K"
    assert source["filed"] == "2025-10-31"
    assert source["sec_url"] == "https://example.com/f.htm"


def test_fact_source_omits_form_and_filed_when_absent(monkeypatch):
    # compare_financial_metric's cross-company facts (via get_frame())
    # carry no form/filed -- see xbrl_facts.get_frame()'s own return shape.
    monkeypatch.setattr(mcp_server, "get_filing_url", lambda ticker, accession: "https://example.com/f.htm")
    fact = {"period_end": "2026-01-25", "accession": "0001045810-26-000021"}

    source = mcp_server._fact_source("NVDA", fact)

    assert "form" not in source
    assert "filed" not in source
    assert source["ticker"] == "NVDA"
    assert source["accession"] == "0001045810-26-000021"


def test_fact_source_omits_sec_url_when_filing_url_unavailable(monkeypatch):
    monkeypatch.setattr(mcp_server, "get_filing_url", lambda ticker, accession: None)
    fact = {"period_end": "2025-09-27", "accession": "0000320193-25-000079"}

    source = mcp_server._fact_source("AAPL", fact)

    assert "sec_url" not in source


# ---------------------------------------------------------------------------
# Tool-call orchestration (search_filings / get_financial_fact / compare_financial_metric)
# ---------------------------------------------------------------------------
def test_search_filings_wraps_each_result_with_source(monkeypatch):
    fake_results = [
        {"text": "First chunk.", "metadata": _chunk_metadata(chunk_index=0)},
        {"text": "Second chunk.", "metadata": _chunk_metadata(chunk_index=1)},
    ]
    monkeypatch.setattr(mcp_server, "hybrid_search", lambda query, ticker, top_k: fake_results)
    monkeypatch.setattr(mcp_server, "get_filing_url", lambda ticker, accession: "https://example.com/f.htm")

    out = mcp_server._search_filings({"query": "revenue", "ticker": "AAPL"})

    assert len(out) == 2
    assert out[0]["text"] == "First chunk."
    assert out[0]["source"]["ticker"] == "AAPL"


def test_search_filings_empty_query_returns_no_results(monkeypatch):
    monkeypatch.setattr(mcp_server, "hybrid_search", lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not be called")))

    assert mcp_server._search_filings({"ticker": "AAPL"}) == []


def test_get_financial_fact_wraps_value_with_source(monkeypatch):
    monkeypatch.setattr(
        mcp_server, "call_get_financial_fact", lambda args: {"value": 416161, "unit": "million", "period_end": "2025-09-27", "accession": "0000320193-25-000079"}
    )
    monkeypatch.setattr(mcp_server, "get_filing_url", lambda ticker, accession: "https://example.com/f.htm")

    out = mcp_server._get_financial_fact({"ticker": "AAPL", "metric": "revenue"})

    assert out == {
        "value": 416161,
        "unit": "million",
        "source": {
            "ticker": "AAPL",
            "period_end": "2025-09-27",
            "accession": "0000320193-25-000079",
            "sec_url": "https://example.com/f.htm",
        },
    }


def test_get_financial_fact_returns_error_dict_when_not_found(monkeypatch):
    monkeypatch.setattr(mcp_server, "call_get_financial_fact", lambda args: None)

    out = mcp_server._get_financial_fact({"ticker": "AAPL", "metric": "revenue"})

    assert "error" in out


def test_compare_financial_metric_wraps_each_company_with_source(monkeypatch):
    monkeypatch.setattr(
        mcp_server,
        "call_compare_financial_metric",
        lambda args: {
            "AAPL": {"value": 46.9, "unit": "percent", "period_end": "2025-09-27", "accession": "0000320193-25-000079"},
            "PLTR": {"value": 82.4, "unit": "percent", "period_end": "2025-12-31", "accession": "0001321655-26-000011"},
        },
    )
    monkeypatch.setattr(mcp_server, "get_filing_url", lambda ticker, accession: f"https://example.com/{ticker}.htm")

    out = mcp_server._compare_financial_metric({"anchor_ticker": "AAPL", "metric": "gross_margin"})

    assert set(out.keys()) == {"AAPL", "PLTR"}
    assert out["PLTR"]["value"] == 82.4
    assert out["PLTR"]["source"]["sec_url"] == "https://example.com/PLTR.htm"


def test_compare_financial_metric_returns_error_dict_when_empty(monkeypatch):
    monkeypatch.setattr(mcp_server, "call_compare_financial_metric", lambda args: {})

    out = mcp_server._compare_financial_metric({"anchor_ticker": "AAPL", "metric": "gross_margin"})

    assert "error" in out


# ---------------------------------------------------------------------------
# _is_authorized (Week 7 guardrails: mcp_server.py auth)
# ---------------------------------------------------------------------------
def test_is_authorized_allows_everything_when_no_token_configured():
    assert mcp_server._is_authorized(None, "") is True
    assert mcp_server._is_authorized("Bearer whatever", "") is True


def test_is_authorized_accepts_correct_bearer_header():
    assert mcp_server._is_authorized("Bearer secret123", "secret123") is True


def test_is_authorized_rejects_missing_header_when_token_configured():
    assert mcp_server._is_authorized(None, "secret123") is False


def test_is_authorized_rejects_wrong_token():
    assert mcp_server._is_authorized("Bearer wrong", "secret123") is False


def test_is_authorized_rejects_header_missing_bearer_prefix():
    assert mcp_server._is_authorized("secret123", "secret123") is False


# ---------------------------------------------------------------------------
# _RateLimiter (Week 7 guardrails: mcp_server.py rate limiting)
# ---------------------------------------------------------------------------
def test_rate_limiter_allows_up_to_max_requests_within_window():
    limiter = mcp_server._RateLimiter(max_requests=2, window_seconds=60)

    assert limiter.allow("key", now=0.0) is True
    assert limiter.allow("key", now=1.0) is True


def test_rate_limiter_blocks_request_beyond_max_within_window():
    limiter = mcp_server._RateLimiter(max_requests=2, window_seconds=60)
    limiter.allow("key", now=0.0)
    limiter.allow("key", now=1.0)

    assert limiter.allow("key", now=2.0) is False


def test_rate_limiter_allows_again_once_window_elapses():
    limiter = mcp_server._RateLimiter(max_requests=1, window_seconds=60)
    limiter.allow("key", now=0.0)
    assert limiter.allow("key", now=30.0) is False

    assert limiter.allow("key", now=60.0) is True


def test_rate_limiter_tracks_keys_independently():
    limiter = mcp_server._RateLimiter(max_requests=1, window_seconds=60)
    limiter.allow("key-a", now=0.0)

    assert limiter.allow("key-b", now=0.0) is True


def test_rate_limiter_disabled_when_max_requests_is_zero():
    limiter = mcp_server._RateLimiter(max_requests=0, window_seconds=60)

    for i in range(10):
        assert limiter.allow("key", now=float(i)) is True


def test_rate_limiter_prunes_expired_windows_to_avoid_unbounded_growth():
    # A long-running server keyed by client IP (the no-auth default)
    # would otherwise keep one dict entry per distinct caller forever,
    # even long after that caller's window expired and it never
    # reconnects -- an unbounded memory leak. Found in code review.
    limiter = mcp_server._RateLimiter(max_requests=5, window_seconds=60)
    limiter.allow("key-a", now=0.0)
    limiter.allow("key-b", now=0.0)
    assert len(limiter._windows) == 2

    limiter.allow("key-c", now=100.0)  # key-a/key-b's windows are long expired by now

    assert len(limiter._windows) == 1
    assert "key-c" in limiter._windows


# ---------------------------------------------------------------------------
# main() -- flush() on shutdown
# ---------------------------------------------------------------------------
def test_main_calls_flush_after_uvicorn_run_returns(monkeypatch):
    # review §11: main() never called tracing.flush() on shutdown, so
    # not-yet-flushed Langfuse observations could be lost on a normal
    # restart/redeploy (uvicorn.run() returns cleanly, no exception, on
    # both SIGINT and SIGTERM -- confirmed in uvicorn's own source).
    calls = []
    monkeypatch.setattr(mcp_server, "build_app", lambda host: "fake-app")
    monkeypatch.setattr(mcp_server.uvicorn, "run", lambda app, host, port: calls.append(("run", app, host, port)))
    monkeypatch.setattr(mcp_server, "flush", lambda: calls.append(("flush",)))

    mcp_server.main.callback(host="127.0.0.1", port=8765)

    assert calls == [("run", "fake-app", "127.0.0.1", 8765), ("flush",)]


def test_main_calls_flush_even_when_uvicorn_run_raises(monkeypatch):
    calls = []
    monkeypatch.setattr(mcp_server, "build_app", lambda host: "fake-app")

    def raising_run(app, host, port):
        raise RuntimeError("boom")

    monkeypatch.setattr(mcp_server.uvicorn, "run", raising_run)
    monkeypatch.setattr(mcp_server, "flush", lambda: calls.append("flush"))

    with pytest.raises(RuntimeError):
        mcp_server.main.callback(host="127.0.0.1", port=8765)

    assert calls == ["flush"]
