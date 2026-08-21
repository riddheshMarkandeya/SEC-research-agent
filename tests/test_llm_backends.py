"""
Unit tests for llm_backends.py. Covers the pure response-normalization
logic (raw Ollama/Gemini wire format -> ModelTurn) with fixture-shaped
fake data -- no live Ollama/Gemini calls, same principle as
test_eval_harness.py's mocked grade_judged() test.
"""

from llm_backends import _ollama_message_to_turn, _gemini_response_to_turn


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


class _FakeFunctionCall:
    def __init__(self, name, args):
        self.name = name
        self.args = args


class _FakePart:
    def __init__(self, function_call=None):
        self.function_call = function_call


class _FakeCandidate:
    def __init__(self, parts):
        self.content = type("_C", (), {"parts": parts})()


class _FakeGeminiResponse:
    def __init__(self, parts, text=None):
        self.candidates = [_FakeCandidate(parts)]
        self.text = text


def test_gemini_response_to_turn_with_tool_calls():
    fc = _FakeFunctionCall("search_filings", {"query": "revenue", "ticker": "AAPL"})
    resp = _FakeGeminiResponse(parts=[_FakePart(function_call=fc)])

    turn = _gemini_response_to_turn(resp)

    assert turn.tool_calls == [{"name": "search_filings", "args": {"query": "revenue", "ticker": "AAPL"}}]


def test_gemini_response_to_turn_final_answer_no_tool_calls():
    resp = _FakeGeminiResponse(parts=[], text="The answer is 42 [1].")

    turn = _gemini_response_to_turn(resp)

    assert turn.tool_calls == []
    assert turn.text == "The answer is 42 [1]."


def test_gemini_response_to_turn_multiple_tool_calls_preserve_order():
    resp = _FakeGeminiResponse(
        parts=[
            _FakePart(function_call=_FakeFunctionCall("search_filings", {"ticker": "AAPL"})),
            _FakePart(function_call=_FakeFunctionCall("search_filings", {"ticker": "MSFT"})),
        ]
    )

    turn = _gemini_response_to_turn(resp)

    assert [c["args"]["ticker"] for c in turn.tool_calls] == ["AAPL", "MSFT"]
