# Swappable LLM backend (Ollama / Gemini) — design

> Status: approved by user, section-by-section, 2026-08-20. Ready for
> an implementation plan (writing-plans skill).

## Motivation

`spike_gemini_eval.py` (Week 5l/5u) proved two things: (1) Gemini
fixes the `msft-segment-revenue-comparison-q3fy2026` bug that
`qwen2.5:7b-instruct` couldn't be talked out of (self-consistency
anchoring on its own invented `segment` tool argument — see
`PROJECT_CONTEXT.md`'s Week 5u section), and (2) it does so with the
exact same system prompt, tool schemas, and retrieval — i.e. the fix
is model capability, not architecture. But the spike is a throwaway
script that duplicates `agent.py`'s tool-dispatch branching
(get_financial_fact / compare_financial_metric / search_filings)
almost verbatim, differing only in wire format. That duplication is
exactly the kind of two-copies-of-the-same-logic risk this project has
already hit and fixed twice (`companies.py`'s `COMPANIES` dict,
`config.py`'s scattered constants) — this design fixes it the same
way, by extracting the one piece that was actually duplicated (tool
dispatch) into a single shared implementation, with only the
backend-specific wire format varying.

This unblocks item 2 in `PROJECT_CONTEXT.md`'s Next Steps: re-testing
"local vs. cloud" properly across the full eval suite now that the
Week 5r/5t/5u fixes have landed, and later revisiting the Week 5j
citation-retry loop against a model capable of acting on corrective
feedback (explicitly out of scope for *this* design — see below).

## Out of scope

- **Citation-retry loop revisit** (Week 5j) — separate follow-up once
  this backend abstraction exists to test it against Gemini.
- **Graph DB / HNSW tuning** — discussed and parked/ruled out
  separately (see `PROJECT_CONTEXT.md` Next Steps item 3), unrelated
  to this design.
- **Dual-backend compare mode** in `eval_harness.py` — one backend per
  invocation, matching today's spike usage; compare two runs by
  diffing two `eval_results/*.json` files, same as existing Ollama-only
  regression checks.
- **A general N-backend plugin system** — this builds exactly the two
  backends there's real evidence for (Ollama, Gemini). The registry
  shape (see below) makes adding a third mechanically simple later,
  but nothing here is built speculatively for a hypothetical third.

## Architecture

### New file: `llm_backends.py`

- `ModelTurn` — `NamedTuple(tool_calls: list[dict], text: str | None)`.
  The normalized shape both backends produce. Each `tool_calls` entry
  is `{"name": str, "args": dict}` — deliberately no `call_id` field,
  since neither backend's tool-result-feedback API needs one (verified
  against both real wire formats in the spike and in `agent.py`'s
  existing Ollama comment: "no `tool_call_id` required, unlike
  OpenAI's API").
- `BACKENDS: dict[str, tuple[Callable, Callable]]` — registry mapping
  `"ollama"` / `"gemini"` to `(start_fn, send_tool_results_fn)` pairs.
  `run_agent()` looks up its pair by name; a third backend later means
  one new registry entry, not a change to the loop.
- `_ollama_start(question) -> (state, ModelTurn)` / `_ollama_send(state, results) -> ModelTurn`
  — today's `_call_ollama()` request logic, moved here unchanged
  (same `OLLAMA_URL`, `num_ctx: 8192`, `temperature: 0.1`). `state` is
  the `messages` list; `start` seeds system+user turns and makes the
  first call; `send` appends `{"role": "tool", "content": ...}` per
  result and calls again.
- `_gemini_start(question) -> (state, ModelTurn)` / `_gemini_send(state, results) -> ModelTurn`
  — today's `spike_gemini_eval.py` logic, moved here unchanged (client
  init via `config.GEMINI_API_KEY`, `_to_gemini_tool` schema
  conversion, 429/503 retry-with-linear-backoff). `state` is the
  `google.genai` `chat` object; `start` creates the chat session with
  `system_instruction=SYSTEM_PROMPT` and sends the question; `send`
  builds `Part.from_function_response(...)` per result and sends those.
- Imports tool schemas (`FACT_TOOL_SCHEMA`, `COMPARE_TOOL_SCHEMA`,
  `SEARCH_TOOL_SCHEMA`) and `SYSTEM_PROMPT` from `agent.py` for the
  Gemini conversion — `agent.py` remains the one place tool *meaning*
  is defined; `llm_backends.py` only handles wire format.
- If `backend="gemini"` requested but `config.GEMINI_API_KEY` is
  unset, `_gemini_start` raises immediately with a clear message,
  rather than failing several calls deep inside the SDK.

### `agent.py` changes

- `run_agent(question, backend="ollama", verbose=False)` gains the
  `backend` parameter and becomes the single shared loop:

  ```python
  start, send_tool_results = BACKENDS[backend]
  state, turn = start(question)
  all_results: list[dict] = []
  searched_tickers: set[str | None] = set()

  for _ in range(MAX_TOOL_ITERATIONS):
      if not turn.tool_calls:
          return turn.text, all_results, verify_citations(turn.text, all_results)
      results = [
          {"name": c["name"], "content": _dispatch_tool_call(c, question, all_results, searched_tickers, verbose)}
          for c in turn.tool_calls
      ]
      turn = send_tool_results(state, results)

  return ("I wasn't able to finish answering within the allotted number of searches. "
          "Try asking a more specific or narrower question.", all_results, [])
  ```

- `_dispatch_tool_call(call, question, all_results, searched_tickers, verbose) -> str`
  — the get_financial_fact / compare_financial_metric / search_filings
  branching extracted once from the current `run_agent` body (and
  identical to what `spike_gemini_eval.py` duplicates today), mutating
  `all_results` / `searched_tickers` in place, returning the tool
  response content string. This is the piece that existed twice before
  this design; now it exists exactly once, used by both backends.
- `main()` gains `--backend {ollama,gemini}`, default
  `config.DEFAULT_BACKEND`.

### `config.py` additions

```python
DEFAULT_BACKEND = os.getenv("DEFAULT_BACKEND", "ollama")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL_NAME", "gemini-flash-lite-latest")
```

`.env.example` documents both new keys (`GEMINI_API_KEY` with a note
that it's free-tier via aistudio.google.com, no credit card;
`DEFAULT_BACKEND=ollama`).

### `eval_harness.py` changes

- `main()` gains `--backend {ollama,gemini}` (default
  `config.DEFAULT_BACKEND`), threaded into `run_agent()` calls.
- Each run's output JSON (`eval_results/<timestamp>.json`) gains a
  top-level `"backend"` field recording which one produced it — two
  result files are otherwise indistinguishable except by memory of
  which run was which.

### Retiring `spike_gemini_eval.py`

Deleted once `agent.py --backend gemini` and
`eval_harness.py --backend gemini` cover everything it did.
`requirements.txt` gains `google-genai`, promoted from a spike-only
`pip install` note to a real dependency.

## Error handling

- Gemini's 429 (rate limit) / 503 (server overload) retry-with-linear-backoff,
  found live during the spike, moves into `_gemini_send`/`_gemini_start`
  unchanged — backend-specific, stays out of the shared loop.
- Boundary validation already inside the tool-dispatch branches
  (rejecting an invented argument like `segment`, treating an empty
  `period_end_date` as "not provided", etc.) is backend-agnostic by
  construction once it lives in `_dispatch_tool_call` — it operates on
  the normalized `{"name", "args"}` shape, so both backends get this
  protection for free instead of only Ollama today.
- Missing `GEMINI_API_KEY` fails fast at `_gemini_start()`, not deep
  inside the SDK on first use.

## Testing

Matches this project's established scope discipline (pure/deterministic
logic is unit tested; live model/network calls are exercised by manual
runs, not mocked into unit tests):

- `tests/test_llm_backends.py` (new): response-normalization tests for
  both backends using fixture-shaped fake responses — e.g. an
  Ollama-style `message` dict with `tool_calls` → correct `ModelTurn`;
  a Gemini-style `parts` list with `function_call`s → correct
  `ModelTurn`. No live Ollama/Gemini calls, same principle as the
  existing `grade_judged()` response-parsing test (mocked
  `requests.post`).
- `tests/test_agent.py`: `_dispatch_tool_call` gets direct unit tests
  now that it's a standalone function — previously only reachable by
  exercising the whole `run_agent()` loop live.
- Existing tests that mock `_call_ollama` / exercise `run_agent()` get
  updated for the new `backend` parameter and the loop's new shape.
  `verify_citations()` / `value_is_citation_verified()` are untouched
  — they only ever consumed `all_results`, never cared which backend
  produced it.
- **Manual live verification** (not unit-tested, same as
  `generate_answer()`/real Ollama calls today): `agent.py "question"
  --backend gemini` on a few known-good questions, then a full
  `eval_harness.py --backend gemini` run to compare against the
  existing Ollama baseline in `eval_results/`. This is also the actual
  point of building this — re-testing whether the Week 5r/5t/5u fixes
  generalize to Gemini or whether it still outperforms on the same
  questions (Next Steps item 2a).

## Migration checklist

1. Add `llm_backends.py` with `ModelTurn`, `BACKENDS`, both backend
   function pairs.
2. Extract `_dispatch_tool_call` in `agent.py`; rewrite `run_agent()`
   as the shared loop; add `--backend` to `main()`.
3. Add `DEFAULT_BACKEND` / `GEMINI_API_KEY` / `GEMINI_MODEL_NAME` to
   `config.py` and `.env.example`.
4. Add `--backend` to `eval_harness.py`; add `"backend"` field to
   result JSON.
5. Add `google-genai` to `requirements.txt`; delete
   `spike_gemini_eval.py`.
6. Write/update tests (`test_llm_backends.py`, `test_agent.py`,
   existing `run_agent()`-related tests).
7. Manual live verification: a few `--backend gemini` single-question
   runs, then a full `eval_harness.py --backend gemini` run compared
   against the current Ollama baseline.
