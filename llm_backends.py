"""
Swappable LLM backend layer (Week 5v / Next Steps item 2).
------------------------------------------------------------
This module was created to eliminate duplication: both Ollama (HTTP API)
and Gemini (google-genai SDK) have different wire formats for tool calling.
Normalizing both into one shape (ModelTurn) lets agent.py drive a single
shared loop regardless of which backend answers -- see
docs/superpowers/specs/2026-08-20-swappable-llm-backend-design.md.

Deliberately takes system_prompt/tool_schemas as parameters rather than
importing them from agent.py -- agent.py needs `from llm_backends import
BACKENDS`, so the reverse import would be circular. agent.py remains the
only place tool *meaning* is defined; this module only ever sees opaque
strings/dicts.
"""

import time
from typing import Callable, NamedTuple

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


def _ollama_message_to_turn(message: dict) -> ModelTurn:
    tool_calls = message.get("tool_calls") or []
    normalized = [{"name": c["function"]["name"], "args": c["function"]["arguments"]} for c in tool_calls]
    return ModelTurn(tool_calls=normalized, text=message.get("content"))


OLLAMA_RETRY_DELAY_SECONDS = 3  # local server startup/model-load stalls, not rate limits
OLLAMA_RETRY_ATTEMPTS = 3


def _ollama_call(state: dict) -> dict:
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
                    "options": {"temperature": 0.1, "num_ctx": 8192},
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
    message = _ollama_call(state)
    state["messages"].append(message)
    return state, _ollama_message_to_turn(message)


def _ollama_send(state: dict, results: list[dict]) -> ModelTurn:
    for r in results:
        state["messages"].append({"role": "tool", "content": r["content"]})
    message = _ollama_call(state)
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
    message = _ollama_call(state)
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
    (OpenAI/Ollama wire-format style) -- Gemini's SDK accepts that
    shape directly for `parameters` (verified live in the original
    spike), so this just unwraps the {"function": {...}} envelope
    rather than re-describing each tool a second time."""
    fn = schema["function"]
    return types.FunctionDeclaration(name=fn["name"], description=fn["description"], parameters=fn["parameters"])


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
            # as _ollama_call's matching log_event above -- only for the
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
    parts = resp.candidates[0].content.parts or []
    function_calls = [p.function_call for p in parts if p.function_call]
    tool_calls = [{"name": fc.name, "args": dict(fc.args or {})} for fc in function_calls]
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
