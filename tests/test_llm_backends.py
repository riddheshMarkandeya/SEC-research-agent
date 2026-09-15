"""
Unit tests for llm_backends.py. Covers the pure response-normalization
logic (raw Ollama/Gemini wire format -> ModelTurn) with fixture-shaped
fake data -- no live Ollama/Gemini calls, same principle as
test_eval_harness.py's mocked grade_judged() test.
"""

from types import SimpleNamespace

import pytest
import requests

from google.genai import errors as genai_errors, types

from llm_backends import (
    complete,
    ollama_call,
    _gemini_send,
    _gemini_send_followup,
    _gemini_start,
    _ollama_message_to_turn,
    _ollama_send,
    _ollama_send_followup,
    _gemini_response_to_turn,
    _get_gemini_client,
    _send_with_retry,
    _to_gemini_tool,
)


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


# ---------------------------------------------------------------------------
# _to_gemini_tool -- regression coverage: Gemini's Schema type (a
# stricter OpenAPI 3.0 subset than Ollama's OpenAI-style wire format)
# doesn't support "additionalProperties" at all -- every tool-calling
# request failed with a 400 INVALID_ARGUMENT until this was stripped.
# See docs/decisions/2026-09-09-schema-driven-arg-validation.md.
# ---------------------------------------------------------------------------
def _search_filings_like_schema():
    return {
        "type": "function",
        "function": {
            "name": "search_filings",
            "description": "desc",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    }


def test_to_gemini_tool_strips_additional_properties():
    # tool.parameters is a google.genai.types.Schema (pydantic), not a
    # dict -- it has its own additional_properties field (unlike the REST
    # backend, which rejects it as "Unknown name"), which stays at its
    # default None as long as the source dict never sets it, matching
    # how a field the SDK's own request builder would otherwise omit.
    tool = _to_gemini_tool(_search_filings_like_schema())
    assert tool.parameters.additional_properties is None


def test_to_gemini_tool_preserves_everything_else():
    tool = _to_gemini_tool(_search_filings_like_schema())
    assert tool.name == "search_filings"
    assert tool.description == "desc"
    assert tool.parameters.required == ["query"]
    assert set(tool.parameters.properties) == {"query"}


def _nested_array_schema():
    # Shaped like the planned submit_answer tool: an array-of-objects
    # property whose ITEM schema also carries additionalProperties, one
    # level deeper than any of the 3 existing tools ever needed. See
    # docs/decisions/2026-09-10-structured-claims-citation-verification.md.
    return {
        "type": "function",
        "function": {
            "name": "submit_answer",
            "description": "desc",
            "parameters": {
                "type": "object",
                "properties": {
                    "claims": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"value": {"type": "number"}},
                            "required": ["value"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["claims"],
                "additionalProperties": False,
            },
        },
    }


def test_to_gemini_tool_strips_additional_properties_recursively():
    # A single top-level dict comprehension (`{k: v for k, v in
    # fn["parameters"].items() if k != "additionalProperties"}`) would
    # leave a NESTED additionalProperties (inside an array property's
    # item schema) unstripped, reproducing the same 400 INVALID_ARGUMENT
    # one level deeper. See
    # docs/decisions/2026-09-10-structured-claims-citation-verification.md.
    tool = _to_gemini_tool(_nested_array_schema())
    assert tool.parameters.additional_properties is None
    assert tool.parameters.properties["claims"].items.additional_properties is None


# ---------------------------------------------------------------------------
# Response-shape validation: both _ollama_message_to_turn and
# _gemini_response_to_turn used to index straight into the raw response
# (c["function"]["name"], resp.candidates[0]) with no shape check,
# crashing with a bare KeyError/IndexError before a tool call ever
# reached agent.py's own boundary validation. See
# docs/decisions/2026-09-09-schema-driven-arg-validation.md.
# ---------------------------------------------------------------------------
def test_ollama_message_to_turn_raises_on_tool_call_missing_function_key(monkeypatch):
    calls = []
    monkeypatch.setattr("llm_backends.log_event", lambda category, **fields: calls.append((category, fields)))
    message = {"role": "assistant", "content": "", "tool_calls": [{"not_function": {}}]}

    try:
        _ollama_message_to_turn(message)
        assert False, "expected RuntimeError"
    except RuntimeError as e:
        assert "ollama" in str(e)
    assert calls[0][1]["backend"] == "ollama"


def test_ollama_message_to_turn_raises_on_non_dict_arguments(monkeypatch):
    monkeypatch.setattr("llm_backends.log_event", lambda *a, **k: None)
    message = {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"function": {"name": "search_filings", "arguments": "not-a-dict"}}],
    }

    try:
        _ollama_message_to_turn(message)
        assert False, "expected RuntimeError"
    except RuntimeError:
        pass


def test_gemini_response_to_turn_raises_on_empty_candidates(monkeypatch):
    calls = []
    monkeypatch.setattr("llm_backends.log_event", lambda category, **fields: calls.append((category, fields)))
    resp = SimpleNamespace(candidates=[], text=None)

    try:
        _gemini_response_to_turn(resp)
        assert False, "expected RuntimeError"
    except RuntimeError as e:
        assert "candidates" in str(e)
    assert calls[0][1]["backend"] == "gemini"


def test_gemini_response_to_turn_raises_on_non_string_function_name(monkeypatch):
    # dict(fc.args or {}) already guarantees "args" is a real dict by the
    # time it's built, so a malformed name is the one residual risk the
    # shared normalized-shape check catches on this path.
    monkeypatch.setattr("llm_backends.log_event", lambda *a, **k: None)
    fc = SimpleNamespace(name=None, args={"ticker": "AAPL"})
    part = SimpleNamespace(function_call=fc)
    resp = SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part]))], text=None)

    try:
        _gemini_response_to_turn(resp)
        assert False, "expected RuntimeError"
    except RuntimeError:
        pass


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
# ollama_call retry/backoff -- pure control-flow, mocks
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
    # Every retry attempt is logged locally (tracing.log_event), not
    # just printed under --verbose -- see
    # docs/decisions/2026-09-05-local-only-debug-events.md.
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
    # A ReadTimeout means the server accepted the connection and was
    # generating, just slower than the 240s budget -- this project's
    # own CPU-only setup is already documented to take 60-70s+ per
    # question, so this is plausibly a genuinely slow answer, not a
    # stalled server. Retrying it would silently turn one 240s timeout
    # into up to 3, i.e. a ~12-minute hang indistinguishable from the
    # process being stuck -- worse than just failing once, so this must
    # propagate immediately, not retry. See
    # docs/decisions/2026-08-26-week7-citation-hard-gate-ollama-retry.md.
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
# principle as ollama_call above, plus local-only llm_retry logging
# (this function had no dedicated tests before now).
# ---------------------------------------------------------------------------
def _fake_gemini_error(code):
    return genai_errors.ClientError(code, {"message": "error"})


class _FakeChat:
    def __init__(self, responses):
        self._responses = iter(responses)
        # Records every config _send_with_retry actually passed through,
        # in order, so tests can assert on it directly instead of only
        # on the response -- for the forced-tool-config work, see
        # docs/decisions/2026-09-10-structured-claims-citation-verification.md.
        self.configs_received = []

    def send_message(self, message, config=None):
        self.configs_received.append(config)
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


def test_send_with_retry_passes_config_through_when_given(monkeypatch):
    # _send_with_retry has an optional `config` param so a
    # forced-tool-choice turn (see _gemini_send/_gemini_send_followup
    # below) can override the chat's default AUTO-mode config. Passing
    # `config=` explicitly is safe even when it's None -- the real SDK's
    # own Chat.send_message signature already defaults `config=None` and
    # treats it identically to omitting it (`method_config = config if
    # config else self._config`, verified against the installed SDK).
    monkeypatch.setattr("llm_backends.log_event", lambda *a, **k: None)
    chat = _FakeChat(["ok"])
    fake_config = object()

    result = _send_with_retry(chat, "question", config=fake_config)

    assert result == "ok"
    assert chat.configs_received == [fake_config]


def test_send_with_retry_defaults_config_to_none(monkeypatch):
    monkeypatch.setattr("llm_backends.log_event", lambda *a, **k: None)
    chat = _FakeChat(["ok"])

    _send_with_retry(chat, "question")

    assert chat.configs_received == [None]


# ---------------------------------------------------------------------------
# Gemini state shape + forced tool choice. See
# docs/decisions/2026-09-10-citation-gate-measurement-instrumentation.md
# and docs/decisions/2026-09-10-structured-claims-citation-verification.md.
# _gemini_start's state must carry its own `config` alongside the `chat`
# object (previously just the bare chat) because a forced turn needs to
# re-supply the WHOLE GenerateContentConfig, not just tool_config --
# Chat.send_message(config=...) replaces the chat's config wholesale
# rather than merging (confirmed by reading google/genai/chats.py's
# actual source: `method_config = config if config else self._config`).
# ---------------------------------------------------------------------------
def test_gemini_start_state_carries_chat_and_config(monkeypatch):
    fake_response = SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=[]))], text="ok")
    fake_chat = _FakeChat([fake_response])
    captured_create_kwargs = {}

    def fake_create(**kwargs):
        captured_create_kwargs.update(kwargs)
        return fake_chat

    monkeypatch.setattr(
        "llm_backends._get_gemini_client",
        lambda: SimpleNamespace(chats=SimpleNamespace(create=fake_create)),
    )

    state, turn = _gemini_start("What was Apple's revenue?", "system prompt", [])

    assert state["chat"] is fake_chat
    assert state["config"] is captured_create_kwargs["config"]
    assert state["config"].system_instruction == "system prompt"
    assert state["config"].temperature == 0.1


def test_gemini_send_does_not_force_when_force_tool_is_none():
    chat = _FakeChat([SimpleNamespace(candidates=[], text=None)])
    base_config = types.GenerateContentConfig(tools=[], system_instruction="sys", temperature=0.1)
    state = {"chat": chat, "config": base_config}

    try:
        _gemini_send(state, [{"name": "search_filings", "content": "..."}])
    except RuntimeError:
        pass  # empty candidates -- irrelevant to this test, only the config passed matters

    assert chat.configs_received == [base_config]


def test_gemini_send_forces_tool_choice_while_preserving_base_config():
    chat = _FakeChat([SimpleNamespace(candidates=[], text=None)])
    base_config = types.GenerateContentConfig(tools=["fake-tools"], system_instruction="sys", temperature=0.1)
    state = {"chat": chat, "config": base_config}

    try:
        _gemini_send(state, [{"name": "search_filings", "content": "..."}], force_tool="submit_answer")
    except RuntimeError:
        pass

    assert len(chat.configs_received) == 1
    forced = chat.configs_received[0]
    assert forced is not base_config  # a NEW config, base_config itself untouched
    assert forced.tools == ["fake-tools"]
    assert forced.system_instruction == "sys"
    assert forced.temperature == 0.1
    assert forced.tool_config.function_calling_config.mode == types.FunctionCallingConfigMode.ANY
    assert forced.tool_config.function_calling_config.allowed_function_names == ["submit_answer"]
    # base_config itself must be untouched -- model_copy(), not mutation.
    assert base_config.tool_config is None


def test_gemini_send_followup_forces_tool_choice_while_preserving_base_config():
    chat = _FakeChat([SimpleNamespace(candidates=[], text=None)])
    base_config = types.GenerateContentConfig(tools=["fake-tools"], system_instruction="sys", temperature=0.1)
    state = {"chat": chat, "config": base_config}

    try:
        _gemini_send_followup(state, "please resubmit", force_tool="submit_answer")
    except RuntimeError:
        pass

    forced = chat.configs_received[0]
    assert forced.tool_config.function_calling_config.allowed_function_names == ["submit_answer"]
    assert forced.tools == ["fake-tools"]


# ---------------------------------------------------------------------------
# Ollama's *_send* functions accept force_tool for interface uniformity
# with Gemini's (agent.py calls both through the same BACKENDS protocol)
# but it has zero effect -- Ollama has no tool_choice/tool_config
# equivalent at all (confirmed: neither its native /api/chat nor its
# OpenAI-compatible endpoint support tool_choice). See
# docs/decisions/2026-09-10-structured-claims-citation-verification.md.
# ---------------------------------------------------------------------------
def test_ollama_send_accepts_and_ignores_force_tool(monkeypatch):
    monkeypatch.setattr("llm_backends.requests.post", lambda *a, **k: _FakeOllamaResponse())
    state = {"messages": [], "tool_schemas": []}

    turn = _ollama_send(state, [{"name": "search_filings", "content": "..."}], force_tool="submit_answer")

    assert turn.text == "ok"


def test_ollama_send_followup_accepts_and_ignores_force_tool(monkeypatch):
    monkeypatch.setattr("llm_backends.requests.post", lambda *a, **k: _FakeOllamaResponse())
    state = {"messages": [], "tool_schemas": []}

    turn = _ollama_send_followup(state, "please resubmit", force_tool="submit_answer")

    assert turn.text == "ok"


# ---------------------------------------------------------------------------
# complete() -- one-shot, tool-free completion for eval_harness.py's
# grade_judged() to honor --judge-backend. Deliberately separate from
# the BACKENDS 3-callable tool-calling protocol: its only
# caller never calls tools, never takes a second turn, and needs
# temperature 0.0, which the tool-calling path hardcodes to 0.1 (see
# _gemini_start above). Only the Ollama branch is unit-tested here (pure
# control flow via a mocked ollama_call, same principle as every other
# test in this file); the Gemini branch is live-only, verified via
# tests/manual/ instead per CLAUDE.md's TDD carve-out for live-only code.
# ---------------------------------------------------------------------------
def test_complete_ollama_passes_temperature_and_no_tool_schemas(monkeypatch):
    captured_state = {}

    def fake_ollama_call(state):
        captured_state.update(state)
        return {"role": "assistant", "content": "PASS\nLooks right."}

    monkeypatch.setattr("llm_backends.ollama_call", fake_ollama_call)

    result = complete("ollama", "system prompt", "user prompt")

    assert result == "PASS\nLooks right."
    assert captured_state["tool_schemas"] == []
    assert captured_state["temperature"] == 0.0
    assert captured_state["messages"] == [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "user prompt"},
    ]


def test_complete_ollama_honors_a_non_default_temperature(monkeypatch):
    captured_state = {}

    def fake_ollama_call(state):
        captured_state.update(state)
        return {"role": "assistant", "content": "ok"}

    monkeypatch.setattr("llm_backends.ollama_call", fake_ollama_call)

    complete("ollama", "system prompt", "user prompt", temperature=0.1)

    assert captured_state["temperature"] == 0.1


def test_complete_raises_on_unknown_backend():
    with pytest.raises(ValueError):
        complete("unknown-backend", "system prompt", "user prompt")


def test_complete_gemini_raises_on_empty_candidates(monkeypatch):
    # complete()'s Gemini branch must go through _gemini_response_to_turn()
    # rather than reading resp.text directly -- this is what makes a
    # safety-filtered/empty response raise the same informative
    # RuntimeError (with the same log_event) every other Gemini call
    # site already gets, instead of silently returning "". See
    # docs/decisions/2026-09-10-citation-gate-measurement-instrumentation.md.
    fake_chat = _FakeChat([SimpleNamespace(candidates=[], text=None)])
    monkeypatch.setattr(
        "llm_backends._get_gemini_client",
        lambda: SimpleNamespace(chats=SimpleNamespace(create=lambda **kwargs: fake_chat)),
    )
    log_calls = []
    monkeypatch.setattr("llm_backends.log_event", lambda category, **fields: log_calls.append((category, fields)))

    with pytest.raises(RuntimeError):
        complete("gemini", "system prompt", "user prompt")

    assert log_calls and log_calls[0][0] == "llm_response_malformed"
    assert log_calls[0][1]["backend"] == "gemini"
