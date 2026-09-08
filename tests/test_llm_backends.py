"""
Unit tests for llm_backends.py. Covers the pure response-normalization
logic (raw Ollama/Gemini wire format -> ModelTurn) with fixture-shaped
fake data -- no live Ollama/Gemini calls, same principle as
test_eval_harness.py's mocked grade_judged() test.
"""

from types import SimpleNamespace

import requests

from google.genai import errors as genai_errors

from llm_backends import ollama_call, _ollama_message_to_turn, _gemini_response_to_turn, _get_gemini_client, _send_with_retry


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


# ---------------------------------------------------------------------------
# ollama_call retry/backoff (Week 7 guardrails) -- pure control-flow, mocks
# requests.post/time.sleep rather than a live Ollama server, same principle
# as the fixture-shaped ModelTurn tests above.
# ---------------------------------------------------------------------------
class _FakeOllamaResponse:
    def raise_for_status(self):
        pass

    def json(self):
        return {"message": {"role": "assistant", "content": "ok"}}


def test_ollama_call_retries_on_connection_error_then_succeeds(monkeypatch):
    monkeypatch.setattr("llm_backends.time.sleep", lambda s: None)
    log_calls = []
    monkeypatch.setattr("llm_backends.log_event", lambda category, **fields: log_calls.append((category, fields)))
    attempts = []

    def fake_post(*args, **kwargs):
        attempts.append(1)
        if len(attempts) < 2:
            raise requests.exceptions.ConnectionError("connection refused")
        return _FakeOllamaResponse()

    monkeypatch.setattr("llm_backends.requests.post", fake_post)

    message = ollama_call({"messages": [], "tool_schemas": []})

    assert message == {"role": "assistant", "content": "ok"}
    assert len(attempts) == 2
    # Week 7 guardrails follow-up: every retry attempt is logged locally
    # (tracing.log_event), not just printed under --verbose -- see
    # PROJECT_CONTEXT.md's "local-only debug events" section.
    assert len(log_calls) == 1
    category, fields = log_calls[0]
    assert category == "llm_retry"
    assert fields["backend"] == "ollama"
    assert fields["attempt"] == 1
    assert fields["exhausted"] is False


def test_ollama_call_retries_on_connect_timeout_then_succeeds(monkeypatch):
    # ConnectTimeout (requests.exceptions.ConnectTimeout is a
    # ConnectionError subclass) means the server never accepted the
    # connection -- same "not up yet" signal as a plain ConnectionError,
    # so it should retry just like one.
    monkeypatch.setattr("llm_backends.time.sleep", lambda s: None)
    attempts = []

    def fake_post(*args, **kwargs):
        attempts.append(1)
        if len(attempts) < 2:
            raise requests.exceptions.ConnectTimeout("still starting up")
        return _FakeOllamaResponse()

    monkeypatch.setattr("llm_backends.requests.post", fake_post)

    message = ollama_call({"messages": [], "tool_schemas": []})

    assert message == {"role": "assistant", "content": "ok"}
    assert len(attempts) == 2


def test_ollama_call_does_not_retry_on_read_timeout(monkeypatch):
    # Regression guard (found in code review, 2026-08-26): a
    # ReadTimeout means the server accepted the connection and was
    # generating, just slower than the 240s budget -- this project's
    # own CPU-only setup is already documented to take 60-70s+ per
    # question, so this is plausibly a genuinely slow answer, not a
    # stalled server. Retrying it would silently turn one 240s timeout
    # into up to 3, i.e. a ~12-minute hang indistinguishable from the
    # process being stuck -- worse than just failing once, so this must
    # propagate immediately, not retry.
    monkeypatch.setattr("llm_backends.time.sleep", lambda s: None)
    attempts = []

    def fake_post(*args, **kwargs):
        attempts.append(1)
        raise requests.exceptions.ReadTimeout("generation took too long")

    monkeypatch.setattr("llm_backends.requests.post", fake_post)
    log_calls = []
    monkeypatch.setattr("llm_backends.log_event", lambda category, **fields: log_calls.append((category, fields)))

    try:
        ollama_call({"messages": [], "tool_schemas": []})
        assert False, "expected ReadTimeout"
    except requests.exceptions.ReadTimeout:
        pass

    assert len(attempts) == 1
    # A ReadTimeout never reaches the ConnectionError except block, so
    # it's not a "retry" at all -- nothing should be logged for it.
    assert log_calls == []


def test_ollama_call_raises_after_exhausting_attempts(monkeypatch):
    monkeypatch.setattr("llm_backends.time.sleep", lambda s: None)
    log_calls = []
    monkeypatch.setattr("llm_backends.log_event", lambda category, **fields: log_calls.append((category, fields)))

    def fake_post(*args, **kwargs):
        raise requests.exceptions.ConnectionError("connection refused")

    monkeypatch.setattr("llm_backends.requests.post", fake_post)

    try:
        ollama_call({"messages": [], "tool_schemas": []})
        assert False, "expected ConnectionError"
    except requests.exceptions.ConnectionError:
        pass

    assert [fields["attempt"] for _, fields in log_calls] == [1, 2, 3]
    assert [fields["exhausted"] for _, fields in log_calls] == [False, False, True]


def test_ollama_call_succeeds_first_try_without_sleeping(monkeypatch):
    sleeps = []
    monkeypatch.setattr("llm_backends.time.sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr("llm_backends.requests.post", lambda *a, **k: _FakeOllamaResponse())

    message = ollama_call({"messages": [], "tool_schemas": []})

    assert message == {"role": "assistant", "content": "ok"}
    assert sleeps == []


def test_ollama_call_defaults_to_temperature_0_1_when_not_specified(monkeypatch):
    # ollama_call is now shared between agent.py's generation path
    # (temperature 0.1) and eval_harness.py's grade_judged() (wants 0.0,
    # stricter grading) -- a state dict with no "temperature" key must
    # keep today's default so the 3 existing generation call sites are
    # unaffected.
    requests_made = []
    monkeypatch.setattr(
        "llm_backends.requests.post", lambda *a, json, **k: requests_made.append(json) or _FakeOllamaResponse()
    )

    ollama_call({"messages": [], "tool_schemas": []})

    assert requests_made[0]["options"]["temperature"] == 0.1


def test_ollama_call_uses_temperature_from_state_when_given(monkeypatch):
    requests_made = []
    monkeypatch.setattr(
        "llm_backends.requests.post", lambda *a, json, **k: requests_made.append(json) or _FakeOllamaResponse()
    )

    ollama_call({"messages": [], "tool_schemas": [], "temperature": 0.0})

    assert requests_made[0]["options"]["temperature"] == 0.0


# ---------------------------------------------------------------------------
# _send_with_retry (Gemini) retry/backoff -- same pure control-flow
# principle as ollama_call above, plus the new Week 7 local-only
# llm_retry logging (this function had no dedicated tests before now).
# ---------------------------------------------------------------------------
def _fake_gemini_error(code):
    return genai_errors.ClientError(code, {"message": "error"})


class _FakeChat:
    def __init__(self, responses):
        self._responses = iter(responses)

    def send_message(self, message):
        item = next(self._responses)
        if isinstance(item, Exception):
            raise item
        return item


def test_send_with_retry_retries_on_429_then_succeeds(monkeypatch):
    monkeypatch.setattr("llm_backends.time.sleep", lambda s: None)
    log_calls = []
    monkeypatch.setattr("llm_backends.log_event", lambda category, **fields: log_calls.append((category, fields)))
    chat = _FakeChat([_fake_gemini_error(429), "ok"])

    result = _send_with_retry(chat, "question")

    assert result == "ok"
    assert len(log_calls) == 1
    category, fields = log_calls[0]
    assert category == "llm_retry"
    assert fields == {"backend": "gemini", "attempt": 1, "max_attempts": 4, "status_code": 429, "exhausted": False}


def test_send_with_retry_retries_on_503_then_succeeds(monkeypatch):
    monkeypatch.setattr("llm_backends.time.sleep", lambda s: None)
    monkeypatch.setattr("llm_backends.log_event", lambda *a, **k: None)
    chat = _FakeChat([_fake_gemini_error(503), "ok"])

    result = _send_with_retry(chat, "question")

    assert result == "ok"


def test_send_with_retry_does_not_retry_on_non_retryable_error(monkeypatch):
    log_calls = []
    monkeypatch.setattr("llm_backends.log_event", lambda category, **fields: log_calls.append((category, fields)))
    chat = _FakeChat([_fake_gemini_error(400)])

    try:
        _send_with_retry(chat, "question")
        assert False, "expected ClientError"
    except genai_errors.ClientError as e:
        assert e.code == 400

    # Not a retryable code -- must not be logged as a retry attempt.
    assert log_calls == []


def test_send_with_retry_raises_after_exhausting_attempts(monkeypatch):
    monkeypatch.setattr("llm_backends.time.sleep", lambda s: None)
    log_calls = []
    monkeypatch.setattr("llm_backends.log_event", lambda category, **fields: log_calls.append((category, fields)))
    chat = _FakeChat([_fake_gemini_error(429)] * 4)

    try:
        _send_with_retry(chat, "question")
        assert False, "expected ClientError"
    except genai_errors.ClientError:
        pass

    assert [fields["attempt"] for _, fields in log_calls] == [1, 2, 3, 4]
    assert [fields["exhausted"] for _, fields in log_calls] == [False, False, False, True]


def test_send_with_retry_succeeds_first_try_without_sleeping(monkeypatch):
    sleeps = []
    monkeypatch.setattr("llm_backends.time.sleep", lambda s: sleeps.append(s))
    log_calls = []
    monkeypatch.setattr("llm_backends.log_event", lambda category, **fields: log_calls.append((category, fields)))
    chat = _FakeChat(["ok"])

    result = _send_with_retry(chat, "question")

    assert result == "ok"
    assert sleeps == []
    assert log_calls == []
