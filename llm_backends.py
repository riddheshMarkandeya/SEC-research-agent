"""
Swappable LLM backend layer (Week 5v / Next Steps item 2).
------------------------------------------------------------
agent.py's run_agent() and the old spike_gemini_eval.py each drove a
full tool-calling loop against a different SDK (Ollama's HTTP API vs.
google-genai's chat session), with the actual tool-dispatch logic
(get_financial_fact / compare_financial_metric / search_filings)
duplicated verbatim between them -- see
docs/superpowers/specs/2026-08-20-swappable-llm-backend-design.md.

This module normalizes both wire formats into one shape (ModelTurn),
so agent.py's run_agent() can drive a single shared loop regardless of
which backend answers. Deliberately takes system_prompt/tool_schemas as
parameters rather than importing them from agent.py -- agent.py needs
`from llm_backends import BACKENDS`, so the reverse import would be
circular. agent.py remains the only place tool *meaning* is defined;
this module only ever sees opaque strings/dicts.
"""

from typing import Callable, NamedTuple

import requests

from config import OLLAMA_MODEL_NAME, OLLAMA_URL


class ModelTurn(NamedTuple):
    """Normalized shape both backends produce. tool_calls entries are
    {"name": str, "args": dict} -- no call_id field, since neither
    backend's tool-result-feedback API needs one (Ollama: `{"role":
    "tool", "content": ...}` with no id; Gemini:
    `Part.from_function_response(name=..., response=...)`, also no id)."""

    tool_calls: list[dict]
    text: str | None


def _ollama_message_to_turn(message: dict) -> ModelTurn:
    tool_calls = message.get("tool_calls") or []
    normalized = [{"name": c["function"]["name"], "args": c["function"]["arguments"]} for c in tool_calls]
    return ModelTurn(tool_calls=normalized, text=message.get("content"))


def _ollama_call(state: dict) -> dict:
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
        timeout=240,
    )
    response.raise_for_status()
    return response.json()["message"]


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


BACKENDS: dict[str, tuple[Callable, Callable]] = {
    "ollama": (_ollama_start, _ollama_send),
}
