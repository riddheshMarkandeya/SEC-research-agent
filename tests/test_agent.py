"""
Unit tests for agent.py. Covers the pure helpers only —
_resolve_search_args, _format_results_block, _format_citation_key.
run_agent()/_call_ollama() drive a live tool-calling loop against Ollama,
so they're exercised by manual runs (python agent.py "...") documented
in PROJECT_CONTEXT.md, not here.
"""

from agent import _format_citation_key, _format_results_block, _resolve_search_args


# ---------------------------------------------------------------------------
# _resolve_search_args
# ---------------------------------------------------------------------------
def test_resolve_search_args_uses_provided_query_and_ticker():
    query, ticker = _resolve_search_args({"query": "RPO", "ticker": "CRM"}, fallback_query="fallback")
    assert query == "RPO"
    assert ticker == "CRM"


def test_resolve_search_args_falls_back_when_query_missing():
    # This is the real behavior observed from qwen2.5:7b-instruct: it
    # sometimes calls the tool with only `ticker`, no `query`, despite
    # `query` being schema-required.
    query, ticker = _resolve_search_args({"ticker": "CRM"}, fallback_query="original question")
    assert query == "original question"
    assert ticker == "CRM"


def test_resolve_search_args_ticker_is_none_when_absent():
    query, ticker = _resolve_search_args({"query": "something"}, fallback_query="fallback")
    assert ticker is None


def test_resolve_search_args_empty_args_falls_back_entirely():
    query, ticker = _resolve_search_args({}, fallback_query="original question")
    assert query == "original question"
    assert ticker is None


# ---------------------------------------------------------------------------
# _format_results_block
# ---------------------------------------------------------------------------
def _fake_result(ticker="CRM", form="10-K", reportDate="2026-01-31", text="Some chunk text.",
                  filingDate="2026-03-02", accessionNumber="0001108524-26-000060", chunk_index=95):
    return {
        "text": text,
        "metadata": {
            "ticker": ticker,
            "form": form,
            "reportDate": reportDate,
            "filingDate": filingDate,
            "accessionNumber": accessionNumber,
            "chunk_index": chunk_index,
        },
    }


def test_format_results_block_numbers_from_start_index():
    results = [_fake_result(text="First."), _fake_result(text="Second.")]
    block = _format_results_block(results, start_index=3)
    assert "[3] CRM 10-K (reportDate=2026-01-31)" in block
    assert "First." in block
    assert "[4] CRM 10-K (reportDate=2026-01-31)" in block
    assert "Second." in block


def test_format_results_block_empty_results_returns_placeholder_text():
    block = _format_results_block([], start_index=1)
    assert "no matching filing excerpts" in block.lower()


# ---------------------------------------------------------------------------
# _format_citation_key
# ---------------------------------------------------------------------------
def test_format_citation_key_numbering_stays_consistent_across_simulated_tool_calls():
    # Simulates two tool calls' worth of accumulated results, as run_agent
    # would build up all_results across iterations of the loop.
    first_call_results = [_fake_result(ticker="AAPL")]
    second_call_results = [_fake_result(ticker="MSFT"), _fake_result(ticker="MSFT")]
    all_results = first_call_results + second_call_results

    key = _format_citation_key(all_results)
    lines = key.splitlines()

    assert lines[0].strip().startswith("[1] AAPL")
    assert lines[1].strip().startswith("[2] MSFT")
    assert lines[2].strip().startswith("[3] MSFT")
