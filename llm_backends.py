"""
Swappable LLM backend layer: normalizes Ollama's and Gemini's different
tool-calling wire formats into one shape (ModelTurn) so agent.py can
drive a single shared loop regardless of which backend answers. See
docs/decisions/2026-08-20-swappable-llm-backend.md.

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
# checked BEFORE _ollama_message_to_turn indexes into it -- a genuine
# JSON-native boundary (response.json() is already a plain dict),
# unlike Gemini's raw response below. See
# docs/decisions/2026-09-09-schema-driven-arg-validation.md.
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
    slower than the 240s budget -- this project's own CPU-only setup
    already takes 60-70s+ per question, so a ReadTimeout is plausibly a
    genuinely slow answer, not a stalled server. Retrying that would
    silently turn one 240s timeout into up to three (~12 minutes),
    indistinguishable from a hang -- worse than just failing once. See
    docs/decisions/2026-08-26-week7-citation-hard-gate-ollama-retry.md."""
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
                    # (~3000 chars each). See
                    # docs/decisions/2026-08-14-agent-v0-tool-calling.md.
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
            # Local-only debug event -- not sent to Langfuse, just kept
            # so a flaky local Ollama server is diagnosable after the
            # fact instead of only visible in a scrolled-away --verbose
            # terminal. See
            # docs/decisions/2026-09-05-local-only-debug-events.md.
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


def _ollama_send(state: dict, results: list[dict], *, force_tool: str | None = None) -> ModelTurn:
    """`force_tool` is accepted for interface uniformity with the Gemini
    side (agent.py calls both through the same BACKENDS 3-callable
    protocol, so it shouldn't need a backend-specific branch just to know
    whether forcing is possible) but has NO effect here -- confirmed
    2026-09-10 that neither Ollama's native /api/chat nor its
    OpenAI-compatible endpoint support a tool_choice/tool_config
    equivalent at all (Ollama issues #8421, #11171)."""
    for r in results:
        state["messages"].append({"role": "tool", "content": r["content"]})
    message = ollama_call(state)
    state["messages"].append(message)
    return _ollama_message_to_turn(message)


def _ollama_send_followup(state: dict, text: str, *, force_tool: str | None = None) -> ModelTurn:
    """Sends a plain corrective/follow-up message, as opposed to a tool
    result -- needed for the citation-verification retry (agent.py's
    run_agent()), which fires only after the model has already stopped
    calling tools and produced a final answer, so there's no tool call
    to attach a result to. Symmetric with _ollama_send, just a "user"
    role message instead of a "tool" one. See _ollama_send's docstring
    for why `force_tool` is accepted but ignored."""
    state["messages"].append({"role": "user", "content": text})
    message = ollama_call(state)
    state["messages"].append(message)
    return _ollama_message_to_turn(message)


RETRY_DELAY_SECONDS = 15  # free-tier rate limits are generous but not infinite
RETRY_ATTEMPTS = 4

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


def _strip_additional_properties(value):
    """Recursively removes "additionalProperties" keys from a JSON-schema
    dict, at any nesting depth -- descends into "properties" (each
    property's own sub-schema) and "items" (an array's item schema),
    the only two places JSON Schema nests another schema.

    Descends recursively (not just top-level) since `submit_answer`'s
    `claims` array needs `additionalProperties: false` on its ITEM
    schema, one level deeper than any of the other 3 tools need. See
    docs/decisions/2026-09-10-structured-claims-citation-verification.md."""
    if isinstance(value, dict):
        return {
            k: _strip_additional_properties(v)
            for k, v in value.items()
            if k != "additionalProperties"
        }
    if isinstance(value, list):
        return [_strip_additional_properties(v) for v in value]
    return value


def _to_gemini_tool(schema: dict) -> types.FunctionDeclaration:
    """agent.py's tool schemas are plain, lowercase JSON-schema dicts
    (OpenAI/Ollama wire-format style) -- Gemini's SDK accepts most of
    that shape directly for `parameters` (verified live in the original
    spike), so this just unwraps the {"function": {...}} envelope rather
    than re-describing each tool a second time.

    "additionalProperties" is the one exception, stripped here (via
    _strip_additional_properties(), recursively -- see that function's
    own docstring) before handing the dict to Gemini's SDK: Gemini's
    Schema type (a stricter OpenAPI 3.0 subset) doesn't support that
    keyword at all -- unlike Ollama, which tolerates it fine. Ollama's
    own wire format and agent.py's/mcp_server.py's runtime
    `validate_tool_args()` both still see the real, unmodified dict --
    this only narrows what's advertised to Gemini's stricter dialect,
    not what's enforced at the boundary. See
    docs/decisions/2026-09-09-schema-driven-arg-validation.md."""
    fn = schema["function"]
    parameters = _strip_additional_properties(fn["parameters"])
    return types.FunctionDeclaration(name=fn["name"], description=fn["description"], parameters=parameters)


def _send_with_retry(chat, message, config=None):
    """Retries on transient errors -- free-tier rate limits (429) and
    plain server overload (503, "experiencing high demand"), both found
    live during the original spike -- with a short linear backoff.

    `config` (2026-09-10, added for the forced-tool-choice turn -- see
    _forced_config()) is always passed straight through, including when
    it's None: the real SDK's own Chat.send_message signature already
    defaults `config=None` and treats that identically to the caller
    omitting it entirely (`method_config = config if config else
    self._config`, confirmed by reading the installed SDK's source), so
    there's no behavior difference to guard here -- just less branching."""
    for attempt in range(RETRY_ATTEMPTS):
        try:
            return chat.send_message(message, config=config)
        except (genai_errors.ClientError, genai_errors.ServerError) as e:
            code = getattr(e, "code", None)
            if code not in (429, 503):
                raise
            # Local-only debug event, same reasoning as ollama_call's
            # matching log_event above -- only for the retryable-error
            # path, not every ClientError/ServerError.
            log_event(
                "llm_retry",
                backend="gemini",
                attempt=attempt + 1,
                max_attempts=RETRY_ATTEMPTS,
                status_code=code,
                exhausted=attempt == RETRY_ATTEMPTS - 1,
            )
            if attempt == RETRY_ATTEMPTS - 1:
                raise
            time.sleep(RETRY_DELAY_SECONDS * (attempt + 1))


def _gemini_response_to_turn(resp) -> ModelTurn:
    """resp is a google-genai SDK object, not a JSON dict -- jsonschema
    doesn't apply directly without first converting it, unwarranted
    ceremony for the one field that actually needs a check here.
    `candidates` can legitimately be empty (e.g. a safety-filtered
    response) -- a plain guard clause here, deliberately not
    jsonschema-based, unlike the normalized-output check below. See
    docs/decisions/2026-09-09-schema-driven-arg-validation.md."""
    if not resp.candidates:
        log_event("llm_response_malformed", backend="gemini", error="no candidates in response")
        raise RuntimeError("Gemini response has no candidates (likely blocked by safety filters, or empty)")
    parts = resp.candidates[0].content.parts or []
    function_calls = [p.function_call for p in parts if p.function_call]
    tool_calls = [{"name": fc.name, "args": dict(fc.args or {})} for fc in function_calls]
    _validate_tool_calls("gemini", tool_calls)
    return ModelTurn(tool_calls=tool_calls, text=resp.text if not tool_calls else None)


def _forced_config(base_config: "types.GenerateContentConfig", force_tool: str | None):
    """Returns `base_config` unchanged when `force_tool` is None (the
    common case -- AUTO mode, free tool choice, exactly today's
    behavior). When given, returns a NEW config with `tool_config` set to
    force exactly that one tool (`mode="ANY"` + `allowed_function_names`
    -- confirmed against the installed SDK to be a hard constraint, not a
    bias: "With mode set to ANY, model will predict a function call from
    the set of function names provided").

    Built from `base_config.model_copy(update=...)` rather than
    constructing a bare `GenerateContentConfig(tool_config=...)`, because
    `Chat.send_message(config=...)` REPLACES the chat's config wholesale
    rather than merging (`method_config = config if config else
    self._config`) -- a bare forced config would silently drop
    `tools`/`system_instruction`/`temperature` on that one turn.
    `model_copy` also leaves `base_config` itself untouched, so the SAME
    base config can be reused on a later un-forced turn. See
    docs/decisions/2026-09-10-structured-claims-citation-verification.md."""
    if force_tool is None:
        return base_config
    return base_config.model_copy(
        update={
            "tool_config": types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(mode="ANY", allowed_function_names=[force_tool])
            )
        }
    )


def _gemini_start(question: str, system_prompt: str, tool_schemas: list[dict]) -> tuple[dict, ModelTurn]:
    client = _get_gemini_client()
    tools = types.Tool(function_declarations=[_to_gemini_tool(s) for s in tool_schemas])
    config = types.GenerateContentConfig(tools=[tools], system_instruction=system_prompt, temperature=0.1)
    chat = client.chats.create(model=GEMINI_MODEL_NAME, config=config)
    resp = _send_with_retry(chat, question)
    # state carries `config` alongside `chat`, not just the bare chat
    # object -- a forced-tool-choice turn (see _forced_config above)
    # needs it back, since send_message(config=...) replaces the chat's
    # config wholesale, so re-supplying the WHOLE config is mandatory.
    # agent.py still treats this as an opaque `state` object.
    return {"chat": chat, "config": config}, _gemini_response_to_turn(resp)


def _gemini_send(state: dict, results: list[dict], *, force_tool: str | None = None) -> ModelTurn:
    parts = [types.Part.from_function_response(name=r["name"], response={"result": r["content"]}) for r in results]
    resp = _send_with_retry(state["chat"], parts, config=_forced_config(state["config"], force_tool))
    return _gemini_response_to_turn(resp)


def _gemini_send_followup(state: dict, text: str, *, force_tool: str | None = None) -> ModelTurn:
    """Gemini counterpart to _ollama_send_followup, above -- see that
    function's docstring for why this is needed. chat.send_message
    already accepts a plain string (the same call _gemini_start makes
    for the original question), so this reuses _send_with_retry's
    429/503 backoff directly rather than adding a second copy."""
    resp = _send_with_retry(state["chat"], text, config=_forced_config(state["config"], force_tool))
    return _gemini_response_to_turn(resp)


BACKENDS: dict[str, tuple[Callable, Callable, Callable]] = {
    "ollama": (_ollama_start, _ollama_send, _ollama_send_followup),
    "gemini": (_gemini_start, _gemini_send, _gemini_send_followup),
}


def complete(backend: str, system_prompt: str, user_prompt: str, temperature: float = 0.0) -> str:
    """One-shot, tool-free completion, used by eval_harness.py's
    grade_judged() to honor --judge-backend. See
    docs/decisions/2026-09-10-citation-gate-measurement-instrumentation.md.

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
    rather than reading `resp.text` directly -- that function is what
    guards the empty-candidates/safety-filtered case (with its own
    log_event) that a bare `resp.text` access would otherwise handle
    silently and inconsistently with every other Gemini call site.
    tool_calls will always be `[]` here (no tools were ever offered), so
    its `text` field is exactly `resp.text`."""
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
