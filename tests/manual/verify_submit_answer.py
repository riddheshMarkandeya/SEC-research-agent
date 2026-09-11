"""
Live verification of the submit_answer tool + forced-tool-choice mechanism
(2026-09-10), run BEFORE the agent loop is restructured to depend on it --
see docs/plans/2026-09-10-structured-claims-citation-verification.md.
Exactly the CLAUDE.md live-code carve-out: whether Gemini's forcing
mechanism and Ollama's real-world tool-calling behavior work as designed
can only be answered by an actual API call, not a mock.

Drives llm_backends.py's low-level start/send functions directly (not
agent.run_agent(), which doesn't know about submit_answer until the loop
rewrite lands) to answer three open questions empirically:
  1. Does Gemini spontaneously choose submit_answer under AUTO mode,
     simply offered as one of 4 tools, once it's done searching?
  2. If not, does forcing (ANY + allowed_function_names=["submit_answer"])
     actually produce a submit_answer call on a real live turn?
  3. What does Ollama (qwen2.5:7b-instruct, no forcing possible at all --
     confirmed during design research) actually do when offered the same
     4 tools -- call submit_answer correctly, emit tool-call-shaped JSON
     as plain text, or just answer in ordinary prose?

Informational, not a hard assert-and-exit-1 gate (same spirit as
verify_retrieval.py/verify_period_labels.py) -- "which of three behaviors
did the model exhibit" is exactly the kind of thing this script exists to
observe and report, not something to fail loudly over.

Usage (from the repo root):
    python tests/manual/verify_submit_answer.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from agent import (
    COMPARE_TOOL_SCHEMA,
    FACT_TOOL_SCHEMA,
    SEARCH_TOOL_SCHEMA,
    SUBMIT_TOOL_SCHEMA,
    SYSTEM_PROMPT,
    _dispatch_tool_call,
)
from config import GEMINI_API_KEY
from llm_backends import BACKENDS

TOOLS = [SEARCH_TOOL_SCHEMA, FACT_TOOL_SCHEMA, COMPARE_TOOL_SCHEMA, SUBMIT_TOOL_SCHEMA]
QUESTION = "What was Apple's total revenue for fiscal year 2025?"
MAX_TURNS = 5


def _run_auto_loop(backend: str):
    """Runs the real search/answer loop under AUTO mode (every backend
    offered all 4 tools, no forcing) using genuine tool dispatch, up to
    MAX_TURNS. Returns ("submit_answer", args) if the model called it
    spontaneously, ("text", text, state, send_followup) if it replied in
    plain text instead (state/send_followup returned so a Gemini caller
    can go on to try forcing), or ("exhausted", None, None, None)."""
    start, send_tool_results, send_followup = BACKENDS[backend]
    state, turn = start(QUESTION, SYSTEM_PROMPT, TOOLS)
    all_results = []
    searched_tickers = set()

    for i in range(MAX_TURNS):
        tool_names = [c["name"] for c in turn.tool_calls]
        print(f"  [{backend}] turn {i}: tool_calls={tool_names!r} text={turn.text!r}")

        submit_calls = [c for c in turn.tool_calls if c["name"] == "submit_answer"]
        if submit_calls:
            return "submit_answer", submit_calls[0]["args"], state, send_followup
        if not turn.tool_calls:
            return "text", turn.text, state, send_followup

        results = [
            {"name": c["name"], "content": _dispatch_tool_call(c, QUESTION, all_results, searched_tickers, False)}
            for c in turn.tool_calls
        ]
        turn = send_tool_results(state, results)

    return "exhausted", None, state, send_followup


def check_gemini():
    print("\n[1+2] Gemini: spontaneous submit_answer under AUTO, else forced ANY mode")
    outcome, payload, state, send_followup = _run_auto_loop("gemini")

    if outcome == "submit_answer":
        print("  [OK] Gemini called submit_answer spontaneously under AUTO -- no forcing needed")
        print(f"  args: {json.dumps(payload, indent=2)[:800]}")
        return

    if outcome == "exhausted":
        print(f"  [PROBLEM] no final answer within {MAX_TURNS} turns -- cannot test forcing")
        return

    print(f"  model replied in plain text instead: {payload!r}")
    print("  forcing ANY + allowed_function_names=['submit_answer']...")
    forced_turn = send_followup(state, "Please provide your final answer now.", force_tool="submit_answer")
    forced_names = [c["name"] for c in forced_turn.tool_calls]
    print(f"  forced turn tool_calls: {forced_names!r} text={forced_turn.text!r}")

    if forced_names == ["submit_answer"]:
        print("  [OK] forced ANY mode produced exactly one submit_answer call")
        print(f"  args: {json.dumps(forced_turn.tool_calls[0]['args'], indent=2)[:800]}")
    else:
        print("  [PROBLEM] forcing did not produce a submit_answer call -- see design fork in the plan doc")


def check_gemini_forcing_directly():
    # check_gemini() above only exercises forcing when the model happens
    # NOT to call submit_answer spontaneously -- which may never happen in
    # practice, leaving the one genuinely novel SDK mechanism in this
    # whole change (tool_config + FunctionCallingConfig(mode="ANY"),
    # never used anywhere in this codebase before) never actually
    # exercised live. Force it unconditionally after exactly one search
    # turn instead of waiting to see what the model would have done.
    #
    # submit_answer MUST be in the tools list from the start here, same
    # as real usage (the design never offers it late) -- confirmed live
    # that Gemini rejects allowed_function_names containing anything not
    # already in the turn's own declared tools: "`allowed_function_names`
    # should be a subset of the provided `function_declarations` names."
    # An earlier version of this script tried forcing a tool that had
    # never been declared and hit exactly this 400, which is a real
    # constraint worth having hit once, not a bug in the design (which
    # never does this) -- documented here so it isn't rediscovered later.
    print("\n[2b] Gemini: forcing mechanism exercised directly (not left to chance)")
    start, send_tool_results, send_followup = BACKENDS["gemini"]
    state, turn = start(QUESTION, SYSTEM_PROMPT, TOOLS)
    all_results = []
    searched_tickers = set()

    print(f"  [gemini] turn 0: tool_calls={[c['name'] for c in turn.tool_calls]!r}")
    if turn.tool_calls and turn.tool_calls[0]["name"] == "submit_answer":
        # Can't cleanly force from here: turn 0's submit_answer call is a
        # dangling, unanswered function call in the chat history, and
        # send_followup sends a plain "user" turn -- a dangling call
        # followed by a bare user message is exactly the malformed-history
        # shape the retry design (docs/plans, section on delivering
        # feedback as a tool result) exists to avoid. Skip forcing here;
        # check_gemini() above already confirmed spontaneous calling works.
        print("  model called submit_answer on turn 0 already -- skipping the forced-path exercise")
        print("  (can't force from a dangling unanswered call without first responding to it)")
        return
    if turn.tool_calls:
        results = [
            {"name": c["name"], "content": _dispatch_tool_call(c, QUESTION, all_results, searched_tickers, False)}
            for c in turn.tool_calls
        ]
        turn = send_tool_results(state, results)
        print(f"  [gemini] turn 1: tool_calls={[c['name'] for c in turn.tool_calls]!r}")
        if turn.tool_calls and turn.tool_calls[0]["name"] == "submit_answer":
            print("  model called submit_answer on turn 1 already -- skipping the forced-path exercise")
            return

    print("  forcing ANY + allowed_function_names=['submit_answer'] regardless of what the model would do next...")
    forced_turn = send_followup(state, "Please provide your final answer now.", force_tool="submit_answer")
    forced_names = [c["name"] for c in forced_turn.tool_calls]
    print(f"  forced turn tool_calls: {forced_names!r} text={forced_turn.text!r}")

    if forced_names == ["submit_answer"]:
        print("  [OK] forced ANY mode produced exactly one submit_answer call")
        print(f"  args: {json.dumps(forced_turn.tool_calls[0]['args'], indent=2)[:800]}")
    else:
        print("  [PROBLEM] forcing did not produce a submit_answer call -- see design fork in the plan doc")


def check_ollama():
    print("\n[3] Ollama: real-world behavior when offered submit_answer (no forcing possible)")
    outcome, payload, _state, _send_followup = _run_auto_loop("ollama")

    if outcome == "submit_answer":
        print("  Ollama called submit_answer correctly.")
        print(f"  args: {json.dumps(payload, indent=2)[:800]}")
    elif outcome == "text":
        # Distinguish "plain prose" from "tool-call-shaped JSON leaked as
        # text" (the documented qwen2.5 failure mode, ollama#7051) --
        # informational only, both fall back to the prose checker either way.
        looks_like_tool_json = payload is not None and '"name"' in payload and '"arguments"' in payload
        if looks_like_tool_json:
            print("  Ollama emitted tool-call-shaped JSON as plain text (documented qwen2.5 failure mode).")
        else:
            print("  Ollama answered in ordinary prose, ignoring submit_answer.")
        print(f"  text: {payload!r}")
        print("  Either way, this falls back to the existing prose checker -- expected, not a bug.")
    else:
        print(f"  [INFO] no final answer within {MAX_TURNS} turns.")


def main():
    if not GEMINI_API_KEY:
        print("GEMINI_API_KEY not set -- skipping Gemini checks (see .env.example).")
    else:
        check_gemini()
        check_gemini_forcing_directly()

    check_ollama()
    print("\nDone. Record what each backend actually did in PROJECT_CONTEXT.md before proceeding with the loop rewrite.")


if __name__ == "__main__":
    main()
