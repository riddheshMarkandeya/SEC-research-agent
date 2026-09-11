"""
Swappable LLM backend layer (Week 5v / Next Steps item 2).
------------------------------------------------------------
This module was created to eliminate duplication: both Ollama (HTTP API)
and Gemini (google-genai SDK) have different wire formats for tool calling.
Normalizing both into one shape (ModelTurn) lets agent.py drive a single
shared loop regardless of which backend answers -- see
docs/plans/2026-08-20-swappable-llm-backend-design.md.

Deliberately takes system_prompt/tool_schemas as parameters rather than
importing them from agent.py -- agent.py needs `from llm_backends import
BACKENDS`, so the reverse import would be circular. agent.py remains the
only place tool *meaning* is defined; this module only ever sees opaque
strings/dicts.
"""

import time
from typing import Callable, NamedTuple

import jsonschema
import requests

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from config import GEMINI_API_KEY, GEMINI_MODEL_NAME, OLLAMA_MODEL_NAME, OLLAMA_URL
from tracing import log_event


# Normalized shape both backends produce. tool_calls entries are
# {"name": str, "args": dict} -- no call_id field, since neither
# backend's tool-result-feedback API needs one (Ollama: `{"role":
# "tool", "content": ...}` with no id; Gemini:
# `Part.from_function_response(name=..., response=...)`, also no id).
ModelTurn = NamedTuple("ModelTurn", [("tool_calls", list[dict]), ("text", str | None)])

# Ollama's raw wire-format tool_calls shape (response.json()["message"]["tool_calls"]),
# checked BEFORE _ollama_message_to_turn indexes into it -- found during
# the 2026-09-09 schema-validator redesign: c["function"]["name"]/
# c["function"]["arguments"] crashed with a bare KeyError on a malformed
# entry, before the tool call ever reached agent.py's own boundary
# validation. A genuine JSON-native boundary (response.json() is already
# a plain dict), unlike Gemini's raw response below.
_OLLAMA_RAW_TOOL_CALLS_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "function": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "arguments": {"type": "object"},
                },
                "required": ["name", "arguments"],
            },
        },
        "required": ["function"],
    },
}
_OLLAMA_RAW_TOOL_CALLS_VALIDATOR = jsonschema.Draft202012Validator(_OLLAMA_RAW_TOOL_CALLS_SCHEMA)

# The normalized ModelTurn.tool_calls shape documented above -- the one
# truly shared, JSON-native boundary both backends converge on, and
# exactly what agent.py's _dispatch_tool_call actually indexes into
# (call["name"]/call["args"]). Validated at the end of both
# _ollama_message_to_turn and _gemini_response_to_turn so a malformed
# turn fails loudly here, with the backend name attached, rather than as
# a confusing KeyError three layers away inside agent.py.
_NORMALIZED_TOOL_CALLS_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {"name": {"type": "string"}, "args": {"type": "object"}},
        "required": ["name", "args"],
        "additionalProperties": False,
    },
}
_NORMALIZED_TOOL_CALLS_VALIDATOR = jsonschema.Draft202012Validator(_NORMALIZED_TOOL_CALLS_SCHEMA)


def _validate_tool_calls(backend: str, tool_calls: list[dict]) -> None:
    """Raises RuntimeError (after logging) if tool_calls doesn't match
    the normalized {"name": str, "args": dict} shape ModelTurn's own
    docstring documents. This is a wire-format bug, not a recoverable
    per-request situation -- fail loudly rather than let a malformed
    turn silently propagate into agent.py's dispatch."""
    error = next(_NORMALIZED_TOOL_CALLS_VALIDATOR.iter_errors(tool_calls), None)
    if error is None:
        return
    log_event("llm_response_malformed", backend=backend, error=error.message, tool_calls=tool_calls)
    raise RuntimeError(f"{backend} produced a malformed tool call: {error.message}")


def _ollama_message_to_turn(message: dict) -> ModelTurn:
    tool_calls = message.get("tool_calls") or []
    error = next(_OLLAMA_RAW_TOOL_CALLS_VALIDATOR.iter_errors(tool_calls), None)
    if error is not None:
        log_event("llm_response_malformed", backend="ollama", error=error.message, tool_calls=tool_calls)
        raise RuntimeError(f"ollama produced a malformed tool_calls shape: {error.message}")
    normalized = [{"name": c["function"]["name"], "args": c["function"]["arguments"]} for c in tool_calls]
    _validate_tool_calls("ollama", normalized)
    return ModelTurn(tool_calls=normalized, text=message.get("content"))


OLLAMA_RETRY_DELAY_SECONDS = 3  # local server startup/model-load stalls, not rate limits
OLLAMA_RETRY_ATTEMPTS = 3


def ollama_call(state: dict) -> dict:
    """Retries only on ConnectionError (including ConnectTimeout, a
    ConnectionError subclass for a stalled connect phase) -- a local
    `ollama serve` still starting up, or a large model still loading
    into memory on first use, both plausible for a local HTTP server
    (as opposed to Gemini's 429/503 retry in _send_with_retry below,
    tuned for free-tier rate limits, not local startup stalls) -- with
    a short linear backoff.

    Deliberately does NOT retry a plain ReadTimeout: that means the
    connection was accepted and Ollama was already generating, just
    slower than the 240s budget -- this project's own CPU-only setup is
    documented to already take 60-70s+ per question (see memory/
    PROJECT_CONTEXT.md), so a ReadTimeout is plausibly a genuinely slow
    answer, not a stalled server. Retrying that would silently turn one
    240s timeout into up to three (~12 minutes), indistinguishable from
    a hang -- worse than just failing once. Found in code review
    (2026-08-26) before this ever shipped."""
    for attempt in range(OLLAMA_RETRY_ATTEMPTS):
        try:
            response = requests.post(
                OLLAMA_URL,
                json={
                    "model": OLLAMA_MODEL_NAME,
                    "messages": state["messages"],
                    "tools": state["tool_schemas"],
                    "stream": False,
                    # Ollama defaults to a 4096-token context window regardless
                    # of what the model actually supports -- dangerously small
                    # here, since a single search returns up to 5 chunks
                    # (~3000 chars each). See PROJECT_CONTEXT.md's agent.py
                    # section for how this was found (a comparison question
                    # silently truncating context, caught via `ollama ps`).
                    # temperature defaults to 0.1 (agent generation) but is
                    # overridable via state["temperature"] -- eval_harness.py's
                    # grade_judged() reuses this function and wants 0.0 for
                    # stricter, more deterministic grading.
                    "options": {"temperature": state.get("temperature", 0.1), "num_ctx": 8192},
                },
                # (connect timeout, read timeout) -- split so a stalled
                # connect phase fails fast into the retry loop instead of
                # sharing the full 240s generation budget.
                timeout=(10, 240),
            )
            response.raise_for_status()
            return response.json()["message"]
        except requests.exceptions.ConnectionError as e:
            # Local-only debug event (Week 7 follow-up) -- not sent to
            # Langfuse, just kept so a flaky local Ollama server is
            # diagnosable after the fact instead of only visible in a
            # scrolled-away --verbose terminal.
            log_event(
                "llm_retry",
                backend="ollama",
                attempt=attempt + 1,
                max_attempts=OLLAMA_RETRY_ATTEMPTS,
                error=str(e),
                exhausted=attempt == OLLAMA_RETRY_ATTEMPTS - 1,
            )
            if attempt == OLLAMA_RETRY_ATTEMPTS - 1:
                raise
            time.sleep(OLLAMA_RETRY_DELAY_SECONDS * (attempt + 1))


def _ollama_start(question: str, system_prompt: str, tool_schemas: list[dict]) -> tuple[dict, ModelTurn]:
    state = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": question},
        ],
        "tool_schemas": tool_schemas,
    }
    message = ollama_call(state)
    state["messages"].append(message)
    return state, _ollama_message_to_turn(message)


def _ollama_send(state: dict, results: list[dict]) -> ModelTurn:
    for r in results:
        state["messages"].append({"role": "tool", "content": r["content"]})
    message = ollama_call(state)
    state["messages"].append(message)
    return _ollama_message_to_turn(message)


def _ollama_send_followup(state: dict, text: str) -> ModelTurn:
    """Sends a plain corrective/follow-up message, as opposed to a tool
    result -- needed for the citation-verification retry (agent.py's
    run_agent()), which fires only after the model has already stopped
    calling tools and produced a final answer, so there's no tool call
    to attach a result to. Symmetric with _ollama_send, just a "user"
    role message instead of a "tool" one."""
    state["messages"].append({"role": "user", "content": text})
    message = ollama_call(state)
    state["messages"].append(message)
    return _ollama_message_to_turn(message)


RETRY_DELAY_SECONDS = 15  # free-tier rate limits are generous but not infinite

# Module-level Gemini client cache (lazy-initialized on first use).
# Kept alive across calls to prevent garbage collection of the underlying
# httpx transport (google-genai's ApiClient.__del__ closes it when collected).
_gemini_client: genai.Client | None = None


def _get_gemini_client() -> genai.Client:
    """Lazily creates and caches the Gemini API client on first call.
    Subsequent calls return the same instance. Only checks GEMINI_API_KEY
    when actually used (--backend gemini selected), not at import time."""
    global _gemini_client
    if _gemini_client is None:
        if not GEMINI_API_KEY:
            raise RuntimeError(
                "GEMINI_API_KEY is not set (see .env.example) -- required for --backend gemini. "
                "Get a free-tier key at aistudio.google.com, no credit card needed."
            )
        _gemini_client = genai.Client(api_key=GEMINI_API_KEY)
    return _gemini_client


def _to_gemini_tool(schema: dict) -> types.FunctionDeclaration:
    """agent.py's tool schemas are plain, lowercase JSON-schema dicts
    (OpenAI/Ollama wire-format style) -- Gemini's SDK accepts most of
    that shape directly for `parameters` (verified live in the original
    spike), so this just unwraps the {"function": {...}} envelope rather
    than re-describing each tool a second time.

    "additionalProperties" is the one exception, stripped here before
    handing the dict to Gemini's SDK: Gemini's Schema type (a stricter
    OpenAPI 3.0 subset) doesn't support that keyword at all -- unlike
    Ollama, which tolerates it fine -- and passing it through made
    EVERY tool-calling request on this backend fail with a live 400
    INVALID_ARGUMENT ("Unknown name additional_properties"), found via a
    live Gemini spot-check eval run immediately after the 2026-09-09
    schema-validator redesign added `additionalProperties: false` to
    every *_TOOL_SCHEMA. Ollama's own wire format and
    agent.py's/mcp_server.py's runtime `validate_tool_args()` both still
    see the real, unmodified dict -- this only narrows what's advertised
    to Gemini's stricter dialect, not what's enforced at the boundary."""
    fn = schema["function"]
    parameters = {k: v for k, v in fn["parameters"].items() if k != "additionalProperties"}
    return types.FunctionDeclaration(name=fn["name"], description=fn["description"], parameters=parameters)


def _send_with_retry(chat, message):
    """Retries on transient errors -- free-tier rate limits (429) and
    plain server overload (503, "experiencing high demand"), both found
    live during the original spike -- with a short linear backoff."""
    for attempt in range(4):
        try:
            return chat.send_message(message)
        except (genai_errors.ClientError, genai_errors.ServerError) as e:
            code = getattr(e, "code", None)
            if code not in (429, 503):
                raise
            # Local-only debug event (Week 7 follow-up), same reasoning
            # as ollama_call's matching log_event above -- only for the
            # retryable-error path, not every ClientError/ServerError.
            log_event(
                "llm_retry",
                backend="gemini",
                attempt=attempt + 1,
                max_attempts=4,
                status_code=code,
                exhausted=attempt == 3,
            )
            if attempt == 3:
                raise
            time.sleep(RETRY_DELAY_SECONDS * (attempt + 1))


def _gemini_response_to_turn(resp) -> ModelTurn:
    """resp is a google-genai SDK object, not a JSON dict -- jsonschema
    doesn't apply directly without first converting it, unwarranted
    ceremony for the one field that actually needs a check here.
    `candidates` can legitimately be empty (e.g. a safety-filtered
    response), which used to raise a bare IndexError on
    resp.candidates[0] before this guard existed (found during the
    2026-09-09 schema-validator redesign) -- a plain guard clause instead,
    deliberately not jsonschema-based, unlike the normalized-output check
    below."""
    if not resp.candidates:
        log_event("llm_response_malformed", backend="gemini", error="no candidates in response")
        raise RuntimeError("Gemini response has no candidates (likely blocked by safety filters, or empty)")
    parts = resp.candidates[0].content.parts or []
    function_calls = [p.function_call for p in parts if p.function_call]
    tool_calls = [{"name": fc.name, "args": dict(fc.args or {})} for fc in function_calls]
    _validate_tool_calls("gemini", tool_calls)
    return ModelTurn(tool_calls=tool_calls, text=resp.text if not tool_calls else None)


def _gemini_start(question: str, system_prompt: str, tool_schemas: list[dict]) -> tuple[object, ModelTurn]:
    client = _get_gemini_client()
    tools = types.Tool(function_declarations=[_to_gemini_tool(s) for s in tool_schemas])
    chat = client.chats.create(
        model=GEMINI_MODEL_NAME,
        config=types.GenerateContentConfig(tools=[tools], system_instruction=system_prompt, temperature=0.1),
    )
    resp = _send_with_retry(chat, question)
    return chat, _gemini_response_to_turn(resp)


def _gemini_send(state: object, results: list[dict]) -> ModelTurn:
    parts = [types.Part.from_function_response(name=r["name"], response={"result": r["content"]}) for r in results]
    resp = _send_with_retry(state, parts)
    return _gemini_response_to_turn(resp)


def _gemini_send_followup(state: object, text: str) -> ModelTurn:
    """Gemini counterpart to _ollama_send_followup, above -- see that
    function's docstring for why this is needed. chat.send_message
    already accepts a plain string (the same call _gemini_start makes
    for the original question), so this reuses _send_with_retry's
    429/503 backoff directly rather than adding a second copy."""
    resp = _send_with_retry(state, text)
    return _gemini_response_to_turn(resp)


BACKENDS: dict[str, tuple[Callable, Callable, Callable]] = {
    "ollama": (_ollama_start, _ollama_send, _ollama_send_followup),
    "gemini": (_gemini_start, _gemini_send, _gemini_send_followup),
}


def complete(backend: str, system_prompt: str, user_prompt: str, temperature: float = 0.0) -> str:
    """One-shot, tool-free completion -- added 2026-09-10 for
    eval_harness.py's grade_judged() to honor --judge-backend (see
    docs/plans/2026-09-10-citation-gate-measurement-instrumentation.md).

    Deliberately NOT threaded through the BACKENDS 3-callable
    tool-calling protocol above: this function's only caller never calls
    tools and never takes a second turn, and specifically needs
    temperature 0.0 for grading determinism -- _gemini_start hardcodes
    0.1 for generation, and widening that protocol's signature (and
    every one of its 6 implementations) just to carry a temperature only
    this caller wants would be a bigger, riskier change than this
    function.

    Ollama branch reuses ollama_call() directly, so its existing
    retry/backoff/logging apply unchanged. Gemini branch creates a
    single-turn chat with NO tools= (unlike _gemini_start) and reuses
    _send_with_retry()'s existing 429/503 backoff rather than switching
    to client.models.generate_content, which would require making that
    retry helper accept an arbitrary callable instead of a chat object.
    Response normalization goes through _gemini_response_to_turn() too
    (found missing in code review, 2026-09-10) rather than reading
    `resp.text` directly -- that function is what guards the empty-
    candidates/safety-filtered case (with its own log_event) that a bare
    `resp.text` access would otherwise handle silently and
    inconsistently with every other Gemini call site. tool_calls will
    always be `[]` here (no tools were ever offered), so its `text`
    field is exactly `resp.text`."""
    if backend == "ollama":
        state = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "tool_schemas": [],
            "temperature": temperature,
        }
        message = ollama_call(state)
        return (message.get("content") or "").strip()
    if backend == "gemini":
        client = _get_gemini_client()
        chat = client.chats.create(
            model=GEMINI_MODEL_NAME,
            config=types.GenerateContentConfig(system_instruction=system_prompt, temperature=temperature),
        )
        resp = _send_with_retry(chat, user_prompt)
        turn = _gemini_response_to_turn(resp)
        return (turn.text or "").strip()
    raise ValueError(f"Unknown backend: {backend!r}")
