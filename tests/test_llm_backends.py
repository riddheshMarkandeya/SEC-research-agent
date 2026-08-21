"""
Unit tests for llm_backends.py. Covers the pure response-normalization
logic (raw Ollama/Gemini wire format -> ModelTurn) with fixture-shaped
fake data -- no live Ollama/Gemini calls, same principle as
test_eval_harness.py's mocked grade_judged() test.
"""

from types import SimpleNamespace

from llm_backends import _ollama_message_to_turn, _gemini_response_to_turn, _get_gemini_client


def test_ollama_message_to_turn_with_tool_calls():
    message = {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {"function": {"name": "search_filings", "arguments": {"query": "revenue", "ticker": "AAPL"}}}
        ],
    }
    turn = _ollama_message_to_turn(message)
    assert turn.tool_calls == [{"name": "search_filings", "args": {"query": "revenue", "ticker": "AAPL"}}]


def test_ollama_message_to_turn_final_answer_no_tool_calls():
    message = {"role": "assistant", "content": "The answer is 42 [1]."}
    turn = _ollama_message_to_turn(message)
    assert turn.tool_calls == []
    assert turn.text == "The answer is 42 [1]."


def test_ollama_message_to_turn_multiple_tool_calls_preserve_order():
    message = {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {"function": {"name": "search_filings", "arguments": {"ticker": "AAPL"}}},
            {"function": {"name": "search_filings", "arguments": {"ticker": "MSFT"}}},
        ],
    }
    turn = _ollama_message_to_turn(message)
    assert [c["args"]["ticker"] for c in turn.tool_calls] == ["AAPL", "MSFT"]


def test_gemini_response_to_turn_with_tool_calls():
    fc = SimpleNamespace(name="search_filings", args={"query": "revenue", "ticker": "AAPL"})
    part = SimpleNamespace(function_call=fc)
    resp = SimpleNamespace(
        candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part]))],
        text=None
    )

    turn = _gemini_response_to_turn(resp)

    assert turn.tool_calls == [{"name": "search_filings", "args": {"query": "revenue", "ticker": "AAPL"}}]


def test_gemini_response_to_turn_final_answer_no_tool_calls():
    resp = SimpleNamespace(
        candidates=[SimpleNamespace(content=SimpleNamespace(parts=[]))],
        text="The answer is 42 [1]."
    )

    turn = _gemini_response_to_turn(resp)

    assert turn.tool_calls == []
    assert turn.text == "The answer is 42 [1]."


def test_gemini_response_to_turn_multiple_tool_calls_preserve_order():
    fc1 = SimpleNamespace(name="search_filings", args={"ticker": "AAPL"})
    fc2 = SimpleNamespace(name="search_filings", args={"ticker": "MSFT"})
    part1 = SimpleNamespace(function_call=fc1)
    part2 = SimpleNamespace(function_call=fc2)
    resp = SimpleNamespace(
        candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part1, part2]))],
        text=None
    )

    turn = _gemini_response_to_turn(resp)

    assert [c["args"]["ticker"] for c in turn.tool_calls] == ["AAPL", "MSFT"]


def test_get_gemini_client_returns_same_instance_across_calls(monkeypatch):
    monkeypatch.setattr("llm_backends._gemini_client", None)
    monkeypatch.setattr("llm_backends.GEMINI_API_KEY", "fake-key-for-testing")

    client1 = _get_gemini_client()
    client2 = _get_gemini_client()

    assert client1 is client2


def test_get_gemini_client_raises_runtime_error_when_key_missing(monkeypatch):
    monkeypatch.setattr("llm_backends._gemini_client", None)
    monkeypatch.setattr("llm_backends.GEMINI_API_KEY", "")

    try:
        _get_gemini_client()
        assert False, "expected RuntimeError"
    except RuntimeError as e:
        assert "GEMINI_API_KEY is not set" in str(e)
