"""
Unit tests for answer.py. Covers format_context/format_citation_key —
pure string formatting. generate_answer() calls a live Ollama server, so
it's exercised by manual runs (python answer.py "...") documented in
PROJECT_CONTEXT.md, not here.
"""

from answer import format_citation_key, format_context


def _fake_result(ticker="AAPL", form="10-K", reportDate="2025-09-27",
                  filingDate="2025-10-31", accessionNumber="0000320193-25-000079",
                  chunk_index=11, text="Some chunk text."):
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


# ---------------------------------------------------------------------------
# format_context — what the LLM actually sees
# ---------------------------------------------------------------------------
def test_format_context_numbers_from_one():
    results = [_fake_result(text="First chunk."), _fake_result(text="Second chunk.")]
    context = format_context(results)
    assert "[1] AAPL 10-K (reportDate=2025-09-27)" in context
    assert "First chunk." in context
    assert "[2] AAPL 10-K (reportDate=2025-09-27)" in context
    assert "Second chunk." in context


def test_format_context_empty_results_returns_empty_string():
    assert format_context([]) == ""


def test_format_context_preserves_full_chunk_text():
    results = [_fake_result(text="A very specific figure: $72.4 billion.")]
    assert "$72.4 billion" in format_context(results)


# ---------------------------------------------------------------------------
# format_citation_key — what the human uses to verify sources afterward
# ---------------------------------------------------------------------------
def test_format_citation_key_includes_all_traceability_fields():
    results = [_fake_result()]
    key = format_citation_key(results)
    assert "[1]" in key
    assert "AAPL" in key
    assert "10-K" in key
    assert "filed 2025-10-31" in key
    assert "reportDate=2025-09-27" in key
    assert "accession=0000320193-25-000079" in key
    assert "chunk=11" in key


def test_format_citation_key_matches_format_context_numbering():
    results = [_fake_result(ticker="CRM"), _fake_result(ticker="MSFT")]
    context = format_context(results)
    key = format_citation_key(results)
    # The same [n] index must point at the same source in both — this is
    # the whole mechanism the LLM's citations rely on being trustworthy.
    assert "[1] CRM" in context and "[1] CRM" in key
    assert "[2] MSFT" in context and "[2] MSFT" in key
