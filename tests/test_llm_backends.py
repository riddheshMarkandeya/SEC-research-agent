"""
Unit tests for llm_backends.py. Covers the pure response-normalization
logic (raw Gemini wire format -> ModelTurn) with fixture-shaped
fake data -- no live Gemini calls, same principle as
test_eval_harness.py's mocked grade_judged() test.
"""

from types import SimpleNamespace
from typing import Any, cast

import pytest

from google.genai import errors as genai_errors, types

from llm_backends import (
    complete,
    _gemini_send,
    _gemini_send_followup,
    _gemini_start,
    _gemini_response_to_turn,
    _get_gemini_client,
    _send_with_retry,
    _gemini_declaration_fields,
    _to_gemini_tool,
)

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
# stricter OpenAPI 3.0 subset than the OpenAI-style tool schemas)
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
    assert tool.parameters is not None
    assert tool.parameters.additional_properties is None


def test_to_gemini_tool_preserves_everything_else():
    tool = _to_gemini_tool(_search_filings_like_schema())
    assert tool.name == "search_filings"
    assert tool.description == "desc"
    assert tool.parameters is not None
    assert tool.parameters.required == ["query"]
    assert tool.parameters.properties is not None
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
    assert tool.parameters is not None
    assert tool.parameters.additional_properties is None
    assert tool.parameters.properties is not None
    claims_schema = tool.parameters.properties["claims"]
    assert claims_schema.items is not None
    assert claims_schema.items.additional_properties is None



def test_gemini_declaration_fields_is_the_plain_data_to_gemini_tool_sends():
    # The model-input snapshot records these plain fields rather than the
    # SDK's pydantic dump, so a library upgrade that only adds default
    # fields can't change what the snapshot (and the prompt fingerprint)
    # says Gemini receives.
    fields = _gemini_declaration_fields(_nested_array_schema())
    assert fields == {
        "name": "submit_answer",
        "description": "desc",
        "parameters": {
            "type": "object",
            "properties": {
                "claims": {
                    "type": "array",
                    "items": {"type": "object", "properties": {"value": {"type": "number"}}, "required": ["value"]},
                },
            },
            "required": ["claims"],
        },
    }
    tool = _to_gemini_tool(_nested_array_schema())
    assert (tool.name, tool.description) == (fields["name"], fields["description"])

# ---------------------------------------------------------------------------
# Response-shape validation: _gemini_response_to_turn used to index
# straight into the raw response (resp.candidates[0]) with no shape check,
# crashing with a bare KeyError/IndexError before a tool call ever
# reached agent.py's own boundary validation. See
# docs/decisions/2026-09-09-schema-driven-arg-validation.md.
# ---------------------------------------------------------------------------
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
# _send_with_retry (Gemini) retry/backoff -- pure control flow with a
# fake chat and a stubbed time.sleep, plus local-only llm_retry logging
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
    base_config = types.GenerateContentConfig(tools=cast(Any, ["fake-tools"]), system_instruction="sys", temperature=0.1)
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
    base_config = types.GenerateContentConfig(tools=cast(Any, ["fake-tools"]), system_instruction="sys", temperature=0.1)
    state = {"chat": chat, "config": base_config}

    try:
        _gemini_send_followup(state, "please resubmit", force_tool="submit_answer")
    except RuntimeError:
        pass

    forced = chat.configs_received[0]
    assert forced.tool_config.function_calling_config.allowed_function_names == ["submit_answer"]
    assert forced.tools == ["fake-tools"]


# ---------------------------------------------------------------------------
# complete() -- one-shot, tool-free completion for eval_harness.py's
# grade_judged() to honor --judge-backend. Deliberately separate from
# the BACKENDS 3-callable tool-calling protocol: its only
# caller never calls tools, never takes a second turn, and needs
# temperature 0.0, which the tool-calling path hardcodes to 0.1 (see
# _gemini_start above). Unit-tested with a fake Gemini client; the real
# round trip is verified via tests/manual/verify_complete.py.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("temperature", [0.0, 0.1])
def test_complete_gemini_passes_temperature_and_no_tools(monkeypatch, temperature):
    fake_chat = _FakeChat(
        [SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=[]))], text="  PASS  ")]
    )
    created = {}

    def fake_create(**kwargs):
        created.update(kwargs)
        return fake_chat

    monkeypatch.setattr(
        "llm_backends._get_gemini_client", lambda: SimpleNamespace(chats=SimpleNamespace(create=fake_create))
    )

    result = complete("gemini", "system prompt", "user prompt", temperature=temperature)

    assert result == "PASS"
    config = created["config"]
    assert config.temperature == temperature
    assert config.system_instruction == "system prompt"
    assert not config.tools


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
