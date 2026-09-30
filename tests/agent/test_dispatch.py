"""
Unit tests for dispatch.py: search-argument resolution, run_search, and
_dispatch_tool_call's routing, validation and result numbering for each
tool.
"""

from sec_agent.agent.dispatch import (
    CHUNKS_PER_SEARCH,
    _dispatch_tool_call,
    _resolve_search_args,
    run_search,
)
from sec_agent.prompts.agent_messages import (
    SEARCH_INVALID_ARGS_MESSAGE,
)
from tests.agent.helpers import _fake_result, _valid_calculate_args, capture_events


# ---------------------------------------------------------------------------
# _resolve_search_args
# ---------------------------------------------------------------------------
def test_resolve_search_args_uses_model_query_on_retry_against_same_ticker():
    # "CRM" is already in searched_tickers, so this counts as a retry —
    # the model's own query is trusted.
    query, ticker = _resolve_search_args(
        {"query": "RPO", "ticker": "CRM"}, fallback_query="fallback", searched_tickers={"CRM"}
    )
    assert query == "RPO"
    assert ticker == "CRM"


def test_resolve_search_args_ignores_model_query_on_first_search_against_a_ticker():
    # This is the regression case: testing showed the model's own
    # first-pass query text (too vague or too literal, depending on how
    # that company's filings happen to phrase things) was the direct
    # cause of two eval failures. The first search against a not-yet-
    # searched ticker must use the original question regardless of what
    # query the model supplied, even when it supplied a "reasonable"
    # looking one.
    query, ticker = _resolve_search_args(
        {"query": "effective tax rate Q4 2025", "ticker": "MSFT"},
        fallback_query="original question",
        searched_tickers=set(),
    )
    assert query == "original question"
    assert ticker == "MSFT"


def test_resolve_search_args_falls_back_when_query_missing_even_on_retry():
    # This is the real behavior observed from qwen2.5:7b-instruct: it
    # sometimes calls the tool with only `ticker`, no `query`, despite
    # `query` being schema-required.
    query, ticker = _resolve_search_args(
        {"ticker": "CRM"}, fallback_query="original question", searched_tickers={"CRM"}
    )
    assert query == "original question"
    assert ticker == "CRM"


def test_resolve_search_args_ticker_is_none_when_absent():
    query, ticker = _resolve_search_args(
        {"query": "something"}, fallback_query="fallback", searched_tickers={"something-else"}
    )
    assert ticker is None


def test_resolve_search_args_empty_args_falls_back_entirely():
    query, ticker = _resolve_search_args({}, fallback_query="original question", searched_tickers=set())
    assert query == "original question"
    assert ticker is None


# ---------------------------------------------------------------------------
# _dispatch_tool_call
# ---------------------------------------------------------------------------
def test_dispatch_tool_call_get_financial_fact_appends_result(monkeypatch):
    fact = {
        "value": 71.1,
        "unit": "percent",
        "form": "10-K",
        "filed": "2026-06-20",
        "period_end": "2026-03-31",
        "accession": "0001234567-26-000123",
    }
    monkeypatch.setattr("sec_agent.agent.dispatch.call_get_financial_fact", lambda args, question=None: fact)
    all_results = []
    call = {"name": "get_financial_fact", "args": {"ticker": "NVDA", "metric": "gross_margin"}}

    content = _dispatch_tool_call(call, "q", all_results, set(), verbose=False)

    assert len(all_results) == 1
    assert all_results[0]["metadata"]["ticker"] == "NVDA"
    assert "[1]" in content


def test_dispatch_tool_call_get_financial_fact_none_uses_no_fact_message(monkeypatch):
    monkeypatch.setattr("sec_agent.agent.dispatch.call_get_financial_fact", lambda args, question=None: None)
    monkeypatch.setattr("sec_agent.agent.dispatch._format_no_fact_message", lambda args: "NO FACT MESSAGE")
    all_results = []
    call = {"name": "get_financial_fact", "args": {"ticker": "NVDA", "metric": "gross_margin"}}

    content = _dispatch_tool_call(call, "q", all_results, set(), verbose=False)

    assert all_results == []
    assert content == "NO FACT MESSAGE"


def test_dispatch_tool_call_calculate_appends_result():
    all_results = [
        _fake_result(text="R&D expense was $34,550 million."),
        _fake_result(text="Gross profit was $195,201 million."),
    ]
    call = {"name": "calculate", "args": _valid_calculate_args()}

    content = _dispatch_tool_call(call, "q", all_results, set(), verbose=False)

    assert len(all_results) == 3
    assert all_results[2]["metadata"]["chunk_index"] == "calculated"
    assert "[3]" in content
    assert "17.7" in content


def test_dispatch_tool_call_calculate_failure_uses_error_message_no_mutation():
    all_results = [_fake_result(text="R&D expense was $34,550 million.")]
    # citation_index_b=5 is out of range against a 1-result all_results.
    call = {"name": "calculate", "args": _valid_calculate_args(citation_index_b=5)}

    content = _dispatch_tool_call(call, "q", all_results, set(), verbose=False)

    assert len(all_results) == 1  # unchanged -- no phantom entry on failure
    assert "5" in content


def test_dispatch_tool_call_compare_financial_metric_appends_results(monkeypatch):
    data = {
        "AAPL": {
            "value": 40.0,
            "unit": "percent",
            "form": "10-K",
            "filed": "2026-06-20",
            "period_end": "2026-03-31",
            "accession": "acc-1",
        }
    }
    monkeypatch.setattr("sec_agent.agent.dispatch.call_compare_financial_metric", lambda args, question=None: data)
    all_results = []
    call = {"name": "compare_financial_metric", "args": {"metric": "gross_margin"}}

    content = _dispatch_tool_call(call, "q", all_results, set(), verbose=False)

    assert len(all_results) == 1
    assert "[1]" in content


def test_dispatch_tool_call_compare_financial_metric_empty_uses_no_comparison_message(monkeypatch):
    monkeypatch.setattr("sec_agent.agent.dispatch.call_compare_financial_metric", lambda args, question=None: {})
    monkeypatch.setattr("sec_agent.agent.dispatch._format_no_comparison_message", lambda args: "NO COMPARISON MESSAGE")
    all_results = []
    call = {"name": "compare_financial_metric", "args": {"metric": "gross_margin"}}

    content = _dispatch_tool_call(call, "q", all_results, set(), verbose=False)

    assert content == "NO COMPARISON MESSAGE"


def test_dispatch_tool_call_search_filings_uses_resolved_query_and_tracks_ticker(monkeypatch):
    fake_results = [
        {
            "text": "chunk text",
            "metadata": {
                "ticker": "AAPL",
                "form": "10-K",
                "filingDate": "2026-01-01",
                "reportDate": "2025-12-31",
                "accessionNumber": "acc-1",
                "chunk_index": 0,
            },
        }
    ]
    captured = {}

    def fake_hybrid_search(query, ticker, top_k):
        captured["query"] = query
        captured["ticker"] = ticker
        return fake_results

    monkeypatch.setattr("sec_agent.agent.dispatch.hybrid_search", fake_hybrid_search)
    all_results = []
    searched_tickers = set()
    # ticker not yet in searched_tickers -> _resolve_search_args ignores
    # the model's own query and uses the fallback question instead
    call = {"name": "search_filings", "args": {"query": "employees", "ticker": "AAPL"}}

    content = _dispatch_tool_call(call, "how many employees", all_results, searched_tickers, verbose=False)

    assert captured["query"] == "how many employees"
    assert captured["ticker"] == "AAPL"
    assert all_results == fake_results
    assert "AAPL" in searched_tickers
    assert "[1]" in content


def test_dispatch_tool_call_search_filings_rejects_unrecognized_ticker(monkeypatch):
    # review §12: unlike call_get_financial_fact/call_compare_financial_metric,
    # search_filings never validated a provided ticker -- a hallucinated
    # ticker silently fell through to hybrid_search with no rejection or
    # telemetry signal, unlike every other schema-violation case in this
    # module.
    monkeypatch.setattr(
        "sec_agent.agent.dispatch.hybrid_search", lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not be called"))
    )
    calls = []
    capture_events(monkeypatch, calls)
    all_results = []
    call = {"name": "search_filings", "args": {"query": "revenue", "ticker": "NOTREAL"}}

    content = _dispatch_tool_call(call, "q", all_results, set(), verbose=False)

    assert "NOTREAL" in content
    assert all_results == []
    assert len(calls) == 1
    category, fields = calls[0]
    assert category == "tool_call_rejected"
    assert fields["reason"] == "ticker_not_in_enum"


def test_dispatch_tool_call_search_filings_rejects_non_hashable_ticker_without_crashing(monkeypatch):
    # Found in code review (round 2, 2026-09-10): the §12 fix's guard
    # ran AFTER _resolve_search_args(), which already crashes first on
    # `ticker not in searched_tickers` (a set) for a non-hashable ticker
    # like a list -- the exact same unhashable-ticker crash class
    # get_financial_fact/compare_financial_metric were already fixed
    # for on 2026-09-06, just never closed for search_filings.
    monkeypatch.setattr(
        "sec_agent.agent.dispatch.hybrid_search", lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not be called"))
    )
    calls = []
    capture_events(monkeypatch, calls)
    call = {"name": "search_filings", "args": {"query": "revenue", "ticker": ["AAPL"]}}

    content = _dispatch_tool_call(call, "q", [], set(), verbose=False)

    assert len(calls) == 1
    category, fields = calls[0]
    assert category == "tool_call_rejected"
    assert fields["reason"] == "ticker_wrong_type"
    assert "not a recognized company" in content


def test_dispatch_tool_call_search_filings_rejects_other_invalid_args_generically(monkeypatch):
    # Only a bad ticker gets the tailored message; any other schema
    # violation (here an invented `segment` filter) gets the generic one.
    monkeypatch.setattr(
        "sec_agent.agent.dispatch.hybrid_search", lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not be called"))
    )
    capture_events(monkeypatch, [])
    call = {"name": "search_filings", "args": {"query": "revenue", "segment": "cloud"}}

    content = _dispatch_tool_call(call, "q", [], set(), verbose=False)

    assert content == SEARCH_INVALID_ARGS_MESSAGE


def test_dispatch_tool_call_search_filings_allows_no_ticker_filter(monkeypatch):
    # ticker is optional for this tool (a broad, unsure search) -- must
    # NOT be rejected just for being absent.
    monkeypatch.setattr("sec_agent.agent.dispatch.hybrid_search", lambda query, ticker, top_k: [])
    calls = []
    capture_events(monkeypatch, calls)
    call = {"name": "search_filings", "args": {"query": "revenue"}}

    _dispatch_tool_call(call, "q", [], set(), verbose=False)

    assert calls == []


def test_run_search_appends_results_and_numbers_them_after_existing(monkeypatch):
    fake_results = [
        {
            "text": "chunk text",
            "metadata": {
                "ticker": "AAPL",
                "form": "10-K",
                "filingDate": "2025-01-01",
                "reportDate": "2024-12-31",
                "accessionNumber": "acc-1",
                "chunk_index": 0,
            },
        }
    ]
    captured = {}

    def fake_hybrid_search(query, ticker, top_k):
        captured.update(query=query, ticker=ticker, top_k=top_k)
        return fake_results

    monkeypatch.setattr("sec_agent.agent.dispatch.hybrid_search", fake_hybrid_search)
    all_results = [{"text": "earlier"}]

    content, count = run_search("employees", None, all_results)

    assert captured == {"query": "employees", "ticker": None, "top_k": CHUNKS_PER_SEARCH}
    assert count == 1
    assert all_results == [{"text": "earlier"}] + fake_results
    assert "[2]" in content and "[1]" not in content


def test_dispatch_no_data_reply_names_the_converted_year_and_logs_once(monkeypatch):
    events = []
    capture_events(monkeypatch, events)
    monkeypatch.setattr("sec_agent.agent.fact_tools.get_ratio", lambda *a, **k: None)
    call = {"name": "get_financial_fact", "args": {"ticker": "NVDA", "metric": "gross_margin", "fiscal_year": "2025"}}

    content = _dispatch_tool_call(call, "q", [], set(), verbose=False)

    assert "'FY' FY2025" in content
    assert "FY'2025'" not in content
    assert [c for c, _ in events].count("tool_arg_coerced") == 1
