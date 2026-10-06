"""
LLM backend layer: normalizes a backend's tool-calling wire format into
one shape (ModelTurn) so agent.py drives a single loop through the
BACKENDS 3-callable protocol. Gemini is the only backend; the protocol
is kept so another cloud backend can plug in without touching the loop.

Deliberately takes system_prompt/tool_schemas as parameters rather than
importing them from agent.py -- agent.py needs `from llm_backends import
BACKENDS`, so the reverse import would be circular. agent.py remains the
only place tool *meaning* is defined; this module only ever sees opaque
strings/dicts.
"""

import time
from typing import Callable, NamedTuple

import jsonschema

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from sec_agent.config import GEMINI_API_KEY, GEMINI_MODEL_NAME
from sec_agent.tracing import log_event


# Normalized shape every backend produces. tool_calls entries are
# {"name": str, "args": dict} -- no call_id field, since Gemini's
# tool-result feedback (`Part.from_function_response(name=...,
# response=...)`) matches results by name, not by id.
ModelTurn = NamedTuple("ModelTurn", [("tool_calls", list[dict]), ("text", str | None)])

# The normalized ModelTurn.tool_calls shape documented above -- the
# JSON-native boundary every backend converges on, and exactly what
# dispatch.py's dispatch_tool_call indexes into (call["name"]/call["args"]).
# Validated at the end of _gemini_response_to_turn so a malformed
# turn fails loudly here, with the backend name attached, rather than as
# a confusing KeyError three layers away inside dispatch.py.
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
    turn silently propagate into dispatch.py's dispatch_tool_call."""
    error = next(_NORMALIZED_TOOL_CALLS_VALIDATOR.iter_errors(tool_calls), None)
    if error is None:
        return
    log_event("llm_response_malformed", backend=backend, error=error.message, tool_calls=tool_calls)
    raise RuntimeError(f"{backend} produced a malformed tool call: {error.message}")


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
    """The agent's tool schemas (prompts.agent_tools) are plain,
    lowercase JSON-schema dicts (OpenAI wire-format style) --
    Gemini's SDK accepts most of that shape directly for `parameters`
    (verified live in the original spike), so this just unwraps the
    {"function": {...}} envelope rather than re-describing each tool a
    second time.

    "additionalProperties" is the one exception, stripped here (via
    _strip_additional_properties(), recursively -- see that function's
    own docstring) before handing the dict to Gemini's SDK: Gemini's
    Schema type (a stricter OpenAPI 3.0 subset) doesn't support that
    keyword at all. agent.py's/mcp_server.py's runtime
    `validate_tool_args()` still sees the real, unmodified dict --
    this only narrows what's advertised to Gemini's stricter dialect,
    not what's enforced at the boundary."""
    fields = _gemini_declaration_fields(schema)
    # google-genai's own pydantic model coerces a plain dict into a Schema at
    # runtime (verified live, per this function's docstring) -- its type stub
    # only advertises the stricter `Schema | None`, not the dict shorthand.
    return types.FunctionDeclaration(**fields)  # pyright: ignore[reportArgumentType]


def _gemini_declaration_fields(schema: dict) -> dict:
    """The plain name/description/parameters data _to_gemini_tool() hands
    to the SDK -- kept separate so the model-input snapshot can record
    exactly what this project sends, independent of the SDK's own
    pydantic representation."""
    fn = schema["function"]
    return {
        "name": fn["name"],
        "description": fn["description"],
        "parameters": _strip_additional_properties(fn["parameters"]),
    }


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
            # Local-only debug event (not sent to Langfuse), so a run of
            # rate-limit retries is diagnosable after the fact -- only for
            # the retryable-error path, not every ClientError/ServerError.
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
                function_calling_config=types.FunctionCallingConfig(
                    mode=types.FunctionCallingConfigMode.ANY, allowed_function_names=[force_tool]
                )
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
    """Sends a plain corrective/follow-up message rather than a tool
    result -- for turns where the model replied in text, so there's no
    tool call to attach a result to (agent.py's forced submit_answer
    follow-up). chat.send_message
    already accepts a plain string (the same call _gemini_start makes
    for the original question), so this reuses _send_with_retry's
    429/503 backoff directly rather than adding a second copy."""
    resp = _send_with_retry(state["chat"], text, config=_forced_config(state["config"], force_tool))
    return _gemini_response_to_turn(resp)


BACKENDS: dict[str, tuple[Callable, Callable, Callable]] = {
    "gemini": (_gemini_start, _gemini_send, _gemini_send_followup),
}


def require_backend(backend: str) -> None:
    """Raises ValueError naming the valid backends. Callers check up
    front so a stale name (e.g. a leftover DEFAULT_BACKEND in .env) stops
    a run with a clear message instead of failing on every call."""
    if backend not in BACKENDS:
        raise ValueError(f"Unknown backend {backend!r}; valid backends: {', '.join(BACKENDS)}")


def complete(backend: str, system_prompt: str, user_prompt: str, temperature: float = 0.0) -> str:
    """One-shot, tool-free completion, used by eval_harness.py's
    grade_judged() to honor --judge-backend.

    Deliberately NOT threaded through the BACKENDS 3-callable
    tool-calling protocol above: this function's only caller never calls
    tools and never takes a second turn, and specifically needs
    temperature 0.0 for grading determinism -- _gemini_start hardcodes
    0.1 for generation, and widening that protocol's signature just to
    carry a temperature only this caller wants would be a bigger, riskier
    change than this function.

    Creates a single-turn chat with NO tools= (unlike _gemini_start) and
    reuses _send_with_retry()'s existing 429/503 backoff rather than
    switching to client.models.generate_content, which would require
    making that retry helper accept an arbitrary callable instead of a
    chat object. Response normalization goes through
    _gemini_response_to_turn() too rather than reading `resp.text`
    directly -- that function is what guards the
    empty-candidates/safety-filtered case (with its own log_event) that a
    bare `resp.text` access would otherwise handle silently and
    inconsistently with every other Gemini call site. tool_calls will
    always be `[]` here (no tools were ever offered), so its `text` field
    is exactly `resp.text`."""
    require_backend(backend)
    # Gemini is the only registered backend; a second one needs its own
    # branch here, or the judge would silently run on Gemini.
    client = _get_gemini_client()
    chat = client.chats.create(
        model=GEMINI_MODEL_NAME,
        config=types.GenerateContentConfig(system_instruction=system_prompt, temperature=temperature),
    )
    resp = _send_with_retry(chat, user_prompt)
    turn = _gemini_response_to_turn(resp)
    return (turn.text or "").strip()
