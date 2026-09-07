# Swappable LLM Backend (Ollama / Gemini) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let `agent.py` and `eval_harness.py` run the exact same tool-calling agent against either Ollama (local) or Gemini (cloud, free tier) via a `--backend` flag, eliminating the tool-dispatch duplication between `agent.py` and the throwaway `spike_gemini_eval.py`.

**Architecture:** A new `llm_backends.py` normalizes both SDKs' wire formats into one `ModelTurn` shape (`tool_calls`, `text`). `agent.py`'s `run_agent()` becomes a single loop that looks up a `(start, send_tool_results)` function pair from `llm_backends.BACKENDS[backend]` and dispatches tool calls through one shared `_dispatch_tool_call()` — previously duplicated verbatim between `agent.py` and the spike.

**Tech Stack:** Python, `requests` (Ollama's HTTP API), `google-genai` (Gemini SDK), `pytest`.

**Spec:** `docs/plans/2026-08-20-swappable-llm-backend-design.md`

## Global Constraints

- Full `pytest` suite must pass before every commit (pre-commit hook enforces this — a failing suite blocks the commit outright).
- No classes anywhere in this codebase — match the existing all-function style (verified: zero `class` definitions in any `.py` file today).
- Test scope follows existing project convention: only pure/deterministic logic is unit tested. Live Ollama/Gemini/network calls are exercised by manual runs, documented in the task, not mocked into unit tests (see `tests/test_agent.py`'s and `tests/test_eval_harness.py`'s own docstrings for this exact policy already in place).
- All file writes use `encoding="utf-8"` if the file is new (Windows defaults to cp1252 and this project has been bitten by that before) — not applicable to any file this plan touches directly, noted for completeness.
- `.env`/`config.py`/`.env.example` follow the existing pattern exactly: every new setting needs a fallback in `config.py` so nothing breaks without a `.env` file.

## Note: one deviation from the spec's literal wording

The spec says `llm_backends.py` "imports tool schemas... and SYSTEM_PROMPT from `agent.py`." Implementing that literally creates a circular import: `agent.py` needs `from llm_backends import BACKENDS` (for `run_agent()`), and `llm_backends.py` would need `from agent import SYSTEM_PROMPT, FACT_TOOL_SCHEMA, ...` — but those names are defined in `agent.py` *after* its own top-level imports run, so Python would fail with "cannot import name from partially initialized module."

**Fix, decided during planning:** `llm_backends.py` takes `system_prompt` and `tool_schemas` as explicit parameters to `start()`, passed in by `agent.py`'s `run_agent()`, instead of importing them. This keeps the spec's actual intent intact — `agent.py` still owns *what the tools mean*, `llm_backends.py` still only handles wire format — while avoiding the cycle. `llm_backends.py` ends up with zero import from `agent.py` at all, which is cleaner than the spec's literal wording, not a compromise of it.

---

### Task 1: `llm_backends.py` — Ollama backend + `ModelTurn`

**Files:**
- Create: `llm_backends.py`
- Modify: `answer.py:72` (stale comment), `eval_harness.py:160` (stale comment)
- Test: `tests/test_llm_backends.py` (new)

**Interfaces:**
- Produces: `ModelTurn` (NamedTuple: `tool_calls: list[dict]`, `text: str | None`), `BACKENDS: dict[str, tuple[Callable, Callable]]` (starts with just `"ollama"`), `_ollama_start(question: str, system_prompt: str, tool_schemas: list[dict]) -> tuple[dict, ModelTurn]`, `_ollama_send(state: dict, results: list[dict]) -> ModelTurn`. `results` entries are `{"name": str, "content": str}`.

- [ ] **Step 1: Write the failing normalization tests**

Create `tests/test_llm_backends.py`:

```python
"""
Unit tests for llm_backends.py. Covers the pure response-normalization
logic (raw Ollama/Gemini wire format -> ModelTurn) with fixture-shaped
fake data -- no live Ollama/Gemini calls, same principle as
test_eval_harness.py's mocked grade_judged() test.
"""

from llm_backends import _ollama_message_to_turn


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_llm_backends.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'llm_backends'`

- [ ] **Step 3: Create `llm_backends.py` with `ModelTurn` and the Ollama backend**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_llm_backends.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Fix the two stale `_call_ollama` comment references**

In `answer.py`, the comment at line 72 currently reads:
```python
            # See agent.py's _call_ollama for why this is set explicitly —
```
Change to:
```python
            # See llm_backends.py's _ollama_call for why this is set explicitly —
```

In `eval_harness.py`, the comment at line 160 currently reads:
```python
            # See agent.py's _call_ollama for why num_ctx is set explicitly
```
Change to:
```python
            # See llm_backends.py's _ollama_call for why num_ctx is set explicitly
```

(`_call_ollama` moves out of `agent.py` entirely in Task 3 below — these comments would otherwise point at a function that no longer exists there.)

- [ ] **Step 6: Run the full suite**

Run: `pytest`
Expected: PASS (217 tests: the existing 214 plus this task's 3 new ones)

- [ ] **Step 7: Commit**

```bash
git add llm_backends.py tests/test_llm_backends.py answer.py eval_harness.py
git commit -m "Add llm_backends.py with ModelTurn + Ollama backend

Normalizes Ollama's tool-call wire format into one shape a shared
agent loop can consume regardless of backend -- first step of the
swappable-backend design (see docs/superpowers/specs/2026-08-20-
swappable-llm-backend-design.md). agent.py isn't wired to this yet;
that's Task 3."
```

---

### Task 2: `agent.py` — extract `_dispatch_tool_call()`

**Files:**
- Modify: `agent.py:731-774` (the `for call in tool_calls:` loop body inside `run_agent()`)
- Test: `tests/test_agent.py`

**Interfaces:**
- Consumes: nothing new (reuses `_call_get_financial_fact`, `_format_no_fact_message`, `_fact_as_result`, `_format_results_block`, `_call_compare_financial_metric`, `_format_no_comparison_message`, `_comparison_as_results`, `_resolve_search_args`, `hybrid_search`, `CHUNKS_PER_SEARCH` — all already defined in `agent.py`).
- Produces: `_dispatch_tool_call(call: dict, question: str, all_results: list[dict], searched_tickers: set[str | None], verbose: bool) -> str`, where `call` is `{"name": str, "args": dict}` (the `ModelTurn.tool_calls` entry shape from Task 1). Mutates `all_results`/`searched_tickers` in place; returns the tool-response content string.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_agent.py` (add `_dispatch_tool_call` to the existing `from agent import (...)` block at the top of the file):

```python
# ---------------------------------------------------------------------------
# _dispatch_tool_call
# ---------------------------------------------------------------------------
def test_dispatch_tool_call_get_financial_fact_appends_result(monkeypatch):
    fact = {
        "value": 71.1,
        "unit": "percent",
        "form": "10-K",
        "filed": "2026-06-20",
        "period_end": "2026-03-31",
        "accession": "0001234567-26-000123",
    }
    monkeypatch.setattr("agent._call_get_financial_fact", lambda args: fact)
    all_results = []
    call = {"name": "get_financial_fact", "args": {"ticker": "NVDA", "metric": "gross_margin"}}

    content = _dispatch_tool_call(call, "q", all_results, set(), verbose=False)

    assert len(all_results) == 1
    assert all_results[0]["metadata"]["ticker"] == "NVDA"
    assert "[1]" in content


def test_dispatch_tool_call_get_financial_fact_none_uses_no_fact_message(monkeypatch):
    monkeypatch.setattr("agent._call_get_financial_fact", lambda args: None)
    monkeypatch.setattr("agent._format_no_fact_message", lambda args: "NO FACT MESSAGE")
    all_results = []
    call = {"name": "get_financial_fact", "args": {"ticker": "NVDA", "metric": "gross_margin"}}

    content = _dispatch_tool_call(call, "q", all_results, set(), verbose=False)

    assert all_results == []
    assert content == "NO FACT MESSAGE"


def test_dispatch_tool_call_compare_financial_metric_appends_results(monkeypatch):
    data = {
        "AAPL": {
            "value": 40.0,
            "unit": "percent",
            "form": "10-K",
            "filed": "2026-06-20",
            "period_end": "2026-03-31",
            "accession": "acc-1",
        }
    }
    monkeypatch.setattr("agent._call_compare_financial_metric", lambda args: data)
    all_results = []
    call = {"name": "compare_financial_metric", "args": {"metric": "gross_margin"}}

    content = _dispatch_tool_call(call, "q", all_results, set(), verbose=False)

    assert len(all_results) == 1
    assert "[1]" in content


def test_dispatch_tool_call_compare_financial_metric_empty_uses_no_comparison_message(monkeypatch):
    monkeypatch.setattr("agent._call_compare_financial_metric", lambda args: {})
    monkeypatch.setattr("agent._format_no_comparison_message", lambda args: "NO COMPARISON MESSAGE")
    all_results = []
    call = {"name": "compare_financial_metric", "args": {"metric": "gross_margin"}}

    content = _dispatch_tool_call(call, "q", all_results, set(), verbose=False)

    assert content == "NO COMPARISON MESSAGE"


def test_dispatch_tool_call_search_filings_uses_resolved_query_and_tracks_ticker(monkeypatch):
    fake_results = [
        {
            "text": "chunk text",
            "metadata": {
                "ticker": "AAPL",
                "form": "10-K",
                "filingDate": "2026-01-01",
                "reportDate": "2025-12-31",
                "accessionNumber": "acc-1",
                "chunk_index": 0,
            },
        }
    ]
    captured = {}

    def fake_hybrid_search(query, ticker, top_k):
        captured["query"] = query
        captured["ticker"] = ticker
        return fake_results

    monkeypatch.setattr("agent.hybrid_search", fake_hybrid_search)
    all_results = []
    searched_tickers = set()
    # ticker not yet in searched_tickers -> _resolve_search_args ignores
    # the model's own query and uses the fallback question instead
    call = {"name": "search_filings", "args": {"query": "employees", "ticker": "AAPL"}}

    content = _dispatch_tool_call(call, "how many employees", all_results, searched_tickers, verbose=False)

    assert captured["query"] == "how many employees"
    assert captured["ticker"] == "AAPL"
    assert all_results == fake_results
    assert "AAPL" in searched_tickers
    assert "[1]" in content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_agent.py -k dispatch_tool_call -v`
Expected: FAIL with `ImportError: cannot import name '_dispatch_tool_call'`

- [ ] **Step 3: Extract `_dispatch_tool_call` in `agent.py`**

Add this function right before `run_agent()` (currently at `agent.py:693`):

```python
def _dispatch_tool_call(
    call: dict, question: str, all_results: list[dict], searched_tickers: set[str | None], verbose: bool
) -> str:
    """Runs one normalized tool call ({"name", "args"} -- the
    ModelTurn.tool_calls shape from llm_backends.py) against the right
    tool, mutating all_results/searched_tickers in place, and returns
    the content string to send back to the model. Backend-agnostic by
    construction: it only ever sees the normalized shape, never
    Ollama's or Gemini's raw wire format, so the boundary validation
    inside _call_get_financial_fact/_call_compare_financial_metric
    (e.g. rejecting an invented `segment` argument) now protects both
    backends automatically instead of needing a second copy."""
    name = call["name"]
    args = call["args"]

    if name == "get_financial_fact":
        if verbose:
            print(f"  [tool call] get_financial_fact({args!r})")
        fact = _call_get_financial_fact(args)
        if fact is None:
            return _format_no_fact_message(args)
        start_index = len(all_results) + 1
        result = _fact_as_result(fact, args)
        all_results.append(result)
        return _format_results_block([result], start_index)

    if name == "compare_financial_metric":
        if verbose:
            print(f"  [tool call] compare_financial_metric({args!r})")
        data = _call_compare_financial_metric(args)
        if not data:
            return _format_no_comparison_message(args)
        start_index = len(all_results) + 1
        results = _comparison_as_results(data, args.get("metric", ""))
        all_results.extend(results)
        return _format_results_block(results, start_index)

    query, ticker = _resolve_search_args(args, fallback_query=question, searched_tickers=searched_tickers)
    searched_tickers.add(ticker)
    if verbose:
        print(f"  [tool call] search_filings(query={query!r}, ticker={ticker!r})")
    results = hybrid_search(query, ticker=ticker, top_k=CHUNKS_PER_SEARCH)
    start_index = len(all_results) + 1
    all_results.extend(results)
    return _format_results_block(results, start_index)
```

Then replace `run_agent()`'s `for call in tool_calls:` loop body (the block that currently has three inline branches, `agent.py:731-774`) with:

```python
        for call in tool_calls:
            content = _dispatch_tool_call(
                {"name": call["function"]["name"], "args": call["function"]["arguments"]},
                question,
                all_results,
                searched_tickers,
                verbose,
            )
            messages.append({"role": "tool", "content": content})
```

This is a transitional shim (`run_agent()` still calls `_call_ollama` directly and hasn't adopted `ModelTurn`/`BACKENDS` yet — that's Task 3). The only change here is that the three inline branches now go through the new shared function.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_agent.py -k dispatch_tool_call -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Run the full suite**

Run: `pytest`
Expected: PASS (222 tests)

- [ ] **Step 6: Manual regression check**

Run: `python agent.py "How many full-time employees does Apple have?"`
Expected: same-shaped answer with a `[1]`-style citation and a `Sources:` section as before this change (this refactor is behavior-preserving — if the answer looks structurally different, something in the extraction broke).

- [ ] **Step 7: Commit**

```bash
git add agent.py tests/test_agent.py
git commit -m "Extract _dispatch_tool_call from run_agent()'s inline branching

The get_financial_fact/compare_financial_metric/search_filings
dispatch logic was about to be needed by a second backend (Gemini) --
pulling it into its own function now, independently unit-tested, is
what makes Task 3's backend-agnostic loop possible without duplicating
this logic the way spike_gemini_eval.py did."
```

---

### Task 3: `agent.py` — rewire `run_agent()` to the shared loop

**Files:**
- Modify: `agent.py` (imports, `run_agent()`, `main()`; removes `_call_ollama`)
- Modify: `config.py` (add `DEFAULT_BACKEND`)
- Modify: `.env.example` (document `DEFAULT_BACKEND`)

**Interfaces:**
- Consumes: `llm_backends.BACKENDS`, `llm_backends.ModelTurn` (from Task 1); `_dispatch_tool_call` (from Task 2); `config.DEFAULT_BACKEND` (new, this task).
- Produces: `run_agent(question: str, backend: str = "ollama", verbose: bool = False) -> tuple[str, list[dict], list[str]]` (same return shape as before — only the new `backend` parameter is added).

- [ ] **Step 1: Add `DEFAULT_BACKEND` to `config.py`**

Add after the `OLLAMA_MODEL_NAME` line (`config.py:39`):

```python
# Which LLM backend agent.py/eval_harness.py use when --backend isn't
# passed explicitly (llm_backends.py's BACKENDS dict has the full list).
DEFAULT_BACKEND = os.getenv("DEFAULT_BACKEND", "ollama")
```

Add to `.env.example`, after the `OLLAMA_MODEL_NAME` line:

```
# Which LLM backend agent.py/eval_harness.py use by default (see
# llm_backends.py's BACKENDS dict for the full list: ollama, gemini).
DEFAULT_BACKEND=ollama
```

- [ ] **Step 2: Rewrite `run_agent()` and remove `_call_ollama`**

In `agent.py`, remove the `_call_ollama` function entirely (currently lines 667-690) and replace `run_agent()`'s body (currently lines 693-781, including the Task-2-updated loop) with:

```python
def run_agent(question: str, backend: str = "ollama", verbose: bool = False) -> tuple[str, list[dict], list[str]]:
    """Run the tool-calling loop until the model produces a final answer
    (no more tool calls) or MAX_TOOL_ITERATIONS is hit. `backend`
    selects which LLM answers (see llm_backends.BACKENDS) -- the loop
    itself, and every tool-dispatch branch inside _dispatch_tool_call,
    is identical regardless of which one is chosen. Returns the answer
    text, every chunk retrieved across all tool calls (in the same
    global [n] order the model was shown them in — this is what lets
    the printed citation key line up with the model's citations), and
    any citation-verification warnings from verify_citations().

    Known simplification: no deduplication if two tool calls happen to
    surface the same chunk (e.g. two related queries against the same
    company). Fine for now — a duplicate citation is cosmetic, not a
    correctness problem — but worth revisiting if it gets noisy.

    No self-correction retry on an unverified citation — tried and
    reverted, see PROJECT_CONTEXT.md's "citation-verification retry
    loop" section for why (qwen2.5:7b-instruct couldn't reliably use the
    corrective feedback). citation_warnings is still returned below and
    still worth surfacing/tracing — the model just isn't trusted to act
    on it itself yet. Revisiting this against Gemini is a separate
    follow-up, not part of this function."""
    start, send_tool_results = BACKENDS[backend]
    tool_schemas = [FACT_TOOL_SCHEMA, COMPARE_TOOL_SCHEMA, SEARCH_TOOL_SCHEMA]
    state, turn = start(question, SYSTEM_PROMPT, tool_schemas)
    all_results: list[dict] = []
    searched_tickers: set[str | None] = set()

    for _ in range(MAX_TOOL_ITERATIONS):
        if not turn.tool_calls:
            answer = turn.text or ""
            return answer, all_results, verify_citations(answer, all_results)

        results = [
            {"name": c["name"], "content": _dispatch_tool_call(c, question, all_results, searched_tickers, verbose)}
            for c in turn.tool_calls
        ]
        turn = send_tool_results(state, results)

    return (
        "I wasn't able to finish answering within the allotted number of searches. "
        "Try asking a more specific or narrower question.",
        all_results,
        [],
    )
```

- [ ] **Step 3: Update imports**

At the top of `agent.py`:
- Remove `import requests` (line 32 — no longer used now that `_call_ollama` is gone; confirm with `grep -n "requests\." agent.py` before removing, it should show no remaining matches).
- Remove `from config import OLLAMA_MODEL_NAME, OLLAMA_URL` (line 35 — no longer used in `agent.py`; both now live only in `llm_backends.py`).
- Add `from llm_backends import BACKENDS`.

- [ ] **Step 4: Add `--backend` to `main()`**

Replace `agent.py`'s `main()` (currently lines 784-800):

```python
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question", help="question to answer")
    parser.add_argument(
        "--backend", choices=list(BACKENDS), default=DEFAULT_BACKEND, help="which LLM backend to use"
    )
    parser.add_argument("--verbose", action="store_true", help="print each tool call as it happens")
    args = parser.parse_args()

    answer, results, citation_warnings = run_agent(args.question, backend=args.backend, verbose=args.verbose)

    print(f"\nQ: {args.question}\n")
    print(answer)
    if results:
        print("\nSources:")
        print(_format_citation_key(results))
    if citation_warnings:
        print("\nCitation warnings:")
        for w in citation_warnings:
            print(f"  {w}")
```

Add `DEFAULT_BACKEND` to the existing `from config import ...` line near the top of `agent.py` (there is no such line yet after Step 3 removed the old one — add `from config import DEFAULT_BACKEND`).

- [ ] **Step 5: Run the full suite**

Run: `pytest`
Expected: PASS (222 tests — nothing added or removed in this task, `run_agent()` itself isn't unit tested per `tests/test_agent.py`'s own documented scope)

- [ ] **Step 6: Manual regression check against the pre-refactor baseline**

Run: `python agent.py "How many full-time employees does Apple have?" --backend ollama`
Expected: same-shaped answer as Task 2's manual check — this confirms the full rewrite (not just the dispatch extraction) preserved behavior for the one backend that exists so far.

Run: `python agent.py "some question" --backend gemini` (without `GEMINI_API_KEY` set, or with it unset in this environment)
Expected: a clear `RuntimeError`/`KeyError` — either `BACKENDS["gemini"]` raising `KeyError: 'gemini'` (expected, since Task 4 hasn't registered it yet) or, once Task 4 lands, the explicit "GEMINI_API_KEY is not set" error from `_gemini_start` rather than a confusing SDK failure. At this point in the plan, `KeyError: 'gemini'` is the correct, expected outcome.

- [ ] **Step 7: Commit**

```bash
git add agent.py config.py .env.example
git commit -m "Rewire run_agent() to the shared llm_backends loop

run_agent() now takes a backend parameter and drives the loop via
llm_backends.BACKENDS[backend] instead of calling Ollama directly.
Only 'ollama' is registered so far (Task 4 adds gemini) -- this task
is the load-bearing rewrite, kept separate from the Gemini backend
itself so it can be verified in isolation against the known-working
Ollama path first."
```

---

### Task 4: `llm_backends.py` — Gemini backend

**Files:**
- Modify: `llm_backends.py`
- Modify: `config.py` (add `GEMINI_API_KEY`, `GEMINI_MODEL_NAME`)
- Modify: `.env.example` (document both)
- Modify: `requirements.txt` (add `google-genai`)
- Test: `tests/test_llm_backends.py`

**Interfaces:**
- Produces: `_gemini_start(question: str, system_prompt: str, tool_schemas: list[dict]) -> tuple[object, ModelTurn]`, `_gemini_send(state: object, results: list[dict]) -> ModelTurn` (registered into `BACKENDS["gemini"]`). Same `results` shape as the Ollama backend: `{"name": str, "content": str}`.

- [ ] **Step 1: Add config + dependency**

In `config.py`, after the `DEFAULT_BACKEND` line added in Task 3:

```python
# Gemini (free tier, api key from aistudio.google.com) -- llm_backends.py.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL_NAME", "gemini-flash-lite-latest")
```

In `.env.example`, after the `DEFAULT_BACKEND` line added in Task 3:

```
# Gemini backend (--backend gemini) -- free tier via aistudio.google.com,
# no credit card required. Only needed if you actually use --backend gemini.
GEMINI_API_KEY=
GEMINI_MODEL_NAME=gemini-flash-lite-latest
```

In `requirements.txt`, add after the existing `chromadb==1.5.9` line:

```
# Gemini backend (llm_backends.py, --backend gemini) -- optional cloud
# alternative to local Ollama.
google-genai==2.18.1
```

Run: `pip install google-genai==2.18.1` (or `pip install -r requirements.txt`) if not already installed in this environment.

- [ ] **Step 2: Write the failing normalization tests**

Add to `tests/test_llm_backends.py`:

```python
from llm_backends import _gemini_response_to_turn


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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_llm_backends.py -k gemini -v`
Expected: FAIL with `ImportError: cannot import name '_gemini_response_to_turn'`

- [ ] **Step 4: Add the Gemini backend to `llm_backends.py`**

Add near the top, alongside the existing imports:

```python
import time

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from config import GEMINI_API_KEY, GEMINI_MODEL_NAME
```

Add after the Ollama backend functions, before the `BACKENDS` dict:

```python
RETRY_DELAY_SECONDS = 15  # free-tier rate limits are generous but not infinite


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
            if code not in (429, 503) or attempt == 3:
                raise
            time.sleep(RETRY_DELAY_SECONDS * (attempt + 1))


def _gemini_response_to_turn(resp) -> ModelTurn:
    parts = resp.candidates[0].content.parts or []
    function_calls = [p.function_call for p in parts if p.function_call]
    tool_calls = [{"name": fc.name, "args": dict(fc.args or {})} for fc in function_calls]
    return ModelTurn(tool_calls=tool_calls, text=resp.text if not tool_calls else None)


def _gemini_start(question: str, system_prompt: str, tool_schemas: list[dict]) -> tuple[object, ModelTurn]:
    if not GEMINI_API_KEY:
        raise RuntimeError(
            "GEMINI_API_KEY is not set (see .env.example) -- required for --backend gemini. "
            "Get a free-tier key at aistudio.google.com, no credit card needed."
        )
    client = genai.Client(api_key=GEMINI_API_KEY)
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
```

Register it in `BACKENDS`:

```python
BACKENDS: dict[str, tuple[Callable, Callable]] = {
    "ollama": (_ollama_start, _ollama_send),
    "gemini": (_gemini_start, _gemini_send),
}
```

(This replaces the single-entry dict from Task 1 — same variable, now with both entries.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_llm_backends.py -v`
Expected: PASS (6 tests: 3 Ollama + 3 Gemini)

- [ ] **Step 6: Run the full suite**

Run: `pytest`
Expected: PASS (225 tests)

- [ ] **Step 7: Commit**

```bash
git add llm_backends.py config.py .env.example requirements.txt
git commit -m "Add Gemini backend to llm_backends.py

Registers 'gemini' in BACKENDS alongside 'ollama' -- agent.py --backend
gemini now works end-to-end. Client is created fresh inside
_gemini_start() rather than at module import time (the original spike
created it at import time, which meant even --backend ollama users
would need GEMINI_API_KEY set just to import the module -- fixed here
by deferring creation until the backend is actually selected)."
```

---

### Task 5: `eval_harness.py` — `--backend` flag + result provenance

**Files:**
- Modify: `eval_harness.py`
- Test: `tests/test_eval_harness.py`

**Interfaces:**
- Consumes: `run_agent(question, backend=..., verbose=...)` (from Task 3).
- Produces: `run_eval(questions_path, ids=None, include_skipped=False, backend="ollama") -> list[dict]` (new `backend` parameter, otherwise unchanged), `save_report(results: list[dict], backend: str) -> Path` (signature change — now takes `backend`; writes `{"backend": ..., "results": [...]}` instead of a bare list).

- [ ] **Step 1: Write the failing test for `save_report`'s new shape**

Add to `tests/test_eval_harness.py` (add `save_report` to the existing `from eval_harness import (...)` block, and `import eval_harness` for the `monkeypatch.setattr` target):

```python
# ---------------------------------------------------------------------------
# save_report — writes {"backend", "results"}, not a bare list
# ---------------------------------------------------------------------------
def test_save_report_writes_backend_and_results(monkeypatch, tmp_path):
    monkeypatch.setattr(eval_harness, "RESULTS_DIR", tmp_path)
    results = [{"id": "q1", "passed": True}]

    out_path = save_report(results, backend="gemini")

    with out_path.open(encoding="utf-8") as f:
        saved = json.load(f)
    assert saved == {"backend": "gemini", "results": results}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_eval_harness.py -k save_report -v`
Expected: FAIL (either `TypeError: save_report() got an unexpected keyword argument 'backend'`, or an assertion mismatch since today's `save_report` writes a bare list)

- [ ] **Step 3: Update `run_eval()`, `save_report()`, and `main()`**

In `eval_harness.py`, replace `run_eval()` (currently `eval_harness.py:211-252`) — only the signature and the `run_agent()` call change, the grading/results-building logic below them is unchanged from today:

```python
def run_eval(
    questions_path: Path, ids: list[str] | None = None, include_skipped: bool = False, backend: str = "ollama"
) -> list[dict]:
    questions = load_questions(questions_path)
    questions = _select_questions(questions, ids, include_skipped)
    results = []

    for q in questions:
        print(f"[{q['id']}] {q['question']}")
        answer_text, retrieved, citation_warnings = run_agent(q["question"], backend=backend)
        has_citation = bool(CITATION_PATTERN.search(answer_text))

        if q["type"] == "numeric":
            passed, detail = grade_numeric(answer_text, q["expected_value"], q["expected_unit"], retrieved)
        elif q["type"] == "comparison":
            passed, detail = grade_comparison(answer_text, q["expected"], retrieved)
        elif q["type"] == "judged":
            passed, detail = grade_judged(q["question"], answer_text, q["criteria"])
        else:
            raise ValueError(f"Unknown question type: {q['type']!r} in question {q['id']!r}")

        status = "PASS" if passed else "FAIL"
        print(f"  -> {status} ({detail})")
        if not has_citation:
            print("  -> WARNING: answer has no [n] citation marker at all")
        for w in citation_warnings:
            print(f"  -> CITATION WARNING: {w}")

        results.append(
            {
                "id": q["id"],
                "ticker": q.get("ticker") or q.get("tickers"),
                "question": q["question"],
                "type": q["type"],
                "passed": passed,
                "detail": detail,
                "has_citation": has_citation,
                "citation_warnings": citation_warnings,
                "answer": answer_text,
                "n_chunks_retrieved": len(retrieved),
            }
        )

    return results
```

Change `save_report` (currently `eval_harness.py:273-279`):

```python
def save_report(results: list[dict], backend: str) -> Path:
    RESULTS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = RESULTS_DIR / f"{timestamp}.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump({"backend": backend, "results": results}, f, indent=2)
    return out_path
```

Update `main()` (currently `eval_harness.py:282-303`):

```python
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", type=Path, default=QUESTIONS_PATH)
    parser.add_argument(
        "--ids",
        type=str,
        default=None,
        help="comma-separated question IDs to run (default: all, minus any skip: true questions)",
    )
    parser.add_argument(
        "--include-skipped",
        action="store_true",
        help="also run questions marked skip: true (ignored if --ids is given)",
    )
    parser.add_argument(
        "--backend", choices=list(BACKENDS), default=DEFAULT_BACKEND, help="which LLM backend to use"
    )
    args = parser.parse_args()

    ids = [i.strip() for i in args.ids.split(",")] if args.ids else None
    results = run_eval(args.questions, ids=ids, include_skipped=args.include_skipped, backend=args.backend)
    print_summary(results)
    out_path = save_report(results, backend=args.backend)
    print(f"\nFull report saved to {out_path}")
```

Add to the imports near the top of `eval_harness.py`:

```python
# OLLAMA_MODEL_NAME/OLLAMA_URL used directly by grade_judged() (the judge always runs on
# Ollama, regardless of --backend); DEFAULT_BACKEND used by main().
from config import DEFAULT_BACKEND, OLLAMA_MODEL_NAME, OLLAMA_URL
from llm_backends import BACKENDS
```

(this replaces the existing `from config import OLLAMA_MODEL_NAME, OLLAMA_URL` line)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_eval_harness.py -k save_report -v`
Expected: PASS

- [ ] **Step 5: Run the full suite**

Run: `pytest`
Expected: PASS (226 tests)

- [ ] **Step 6: Commit**

```bash
git add eval_harness.py tests/test_eval_harness.py
git commit -m "Add --backend to eval_harness.py; record it in eval_results

save_report() now writes {\"backend\": ..., \"results\": [...]} instead
of a bare list -- two result files were otherwise indistinguishable
except by remembering which run was which. Nothing else in the repo
parses eval_results/*.json programmatically (checked), so this shape
change is safe."
```

---

### Task 6: Retire `spike_gemini_eval.py`

**Files:**
- Delete: `spike_gemini_eval.py`

**Interfaces:**
- Consumes: nothing (this task only removes a file).
- Produces: nothing.

- [ ] **Step 1: Confirm nothing else references it**

Run: `grep -rln "spike_gemini_eval" *.py tests/*.py`
Expected: only `spike_gemini_eval.py` itself (confirmed during planning — re-verify here since Tasks 1-5 may have touched imports).

- [ ] **Step 2: Delete the file**

```bash
git rm spike_gemini_eval.py
```

- [ ] **Step 3: Run the full suite**

Run: `pytest`
Expected: PASS (226 tests — deleting this file removes nothing pytest collects, since it was never imported by any test)

- [ ] **Step 4: Commit**

```bash
git commit -m "Retire spike_gemini_eval.py, superseded by --backend gemini

agent.py --backend gemini and eval_harness.py --backend gemini now
cover everything this throwaway script did, without the tool-dispatch
duplication it required."
```

---

### Task 7: Manual live verification

**Files:** none (no code changes — this task is the actual point of the feature: confirming Gemini works end-to-end and re-testing whether the Week 5r/5t/5u fixes generalize, per Next Steps item 2a in `PROJECT_CONTEXT.md`).

**Interfaces:** none.

- [ ] **Step 1: Set up Gemini credentials**

Add a real `GEMINI_API_KEY` to your local `.env` (free tier, aistudio.google.com, no credit card) if not already present from earlier spike testing.

- [ ] **Step 2: Single-question sanity checks**

Run each of these and confirm a clean answer with citations, no crash:

```bash
python agent.py "How many full-time employees does Apple have?" --backend gemini
python agent.py "Compare Apple's and Microsoft's effective tax rates." --backend gemini --verbose
python agent.py "Which segment had higher revenue for Microsoft in Q3 FY2026, Intelligent Cloud or Productivity and Business Processes?" --backend gemini --verbose
```

The third question is the exact motivating case from Week 5u
(`msft-segment-revenue-comparison-q3fy2026`) — confirm it now answers
correctly (Productivity and Business Processes, $35,013M) without
inventing a `segment` tool argument, matching the spike's earlier 3/3
result.

- [ ] **Step 3: Full eval suite on Gemini**

```bash
python eval_harness.py --backend gemini
```

Record the resulting `eval_results/<timestamp>.json` pass count.

- [ ] **Step 4: Compare against the current Ollama baseline**

```bash
python eval_harness.py --backend ollama
```

Diff the two `eval_results/*.json` pass/fail lists question-by-question. Update `PROJECT_CONTEXT.md`'s Next Steps section with the outcome: which questions flip, whether Gemini's advantage is confined to the segment-comparison-shaped bug or generalizes further, and whether this changes the priority of item 2b (revisiting the Week 5j citation-retry loop against Gemini).

- [ ] **Step 5: No commit for this task alone**

The `eval_results/*.json` files this produces and the `PROJECT_CONTEXT.md` update belong together in one commit once Step 4's findings are written up — follow the same discipline as every other eval-result commit in this project's history (results + narrative together, not results alone).
