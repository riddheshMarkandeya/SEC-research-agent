# Swappable LLM backend: llm_backends.py normalizes Ollama/Gemini into one shared loop

**Date:** 2026-08-20

## Context

`agent.py`'s tool-calling loop and the throwaway `spike_gemini_eval.py`
each drove a full loop against a different SDK, with tool-dispatch
logic duplicated verbatim between them. The spike had already proven
Gemini fixes a real local-model capability-ceiling bug (see
`docs/decisions/2026-08-20-comparison-reasoning-model-capability-limit.md`)
using the same prompt/schema/retrieval — the fix was model capability,
not architecture — but only existed as a disposable script.

## Decision

New `llm_backends.py` normalizes both backends' wire formats into one
`ModelTurn` shape (`tool_calls`, `text`). `agent.py`'s
`_dispatch_tool_call()` extracted once (previously duplicated between
`agent.py` and the spike) and made backend-agnostic. A `BACKENDS`
registry maps `"ollama"`/`"gemini"` to `(start, send)` callable pairs;
`run_agent()` becomes one shared loop looking up its pair by name.
`config.py` gained `DEFAULT_BACKEND`/`GEMINI_API_KEY`/`GEMINI_MODEL_NAME`.
`spike_gemini_eval.py` retired once `--backend gemini` covered
everything it did.

## Why

`llm_backends.py` takes `system_prompt`/`tool_schemas` as explicit
parameters rather than importing them from `agent.py` — a literal
reading of the original design spec would create a circular import
(`agent.py` needs `BACKENDS`; `llm_backends.py` would need names
defined only after `agent.py`'s own top-level imports finish running).
Decided during implementation planning, not the original design: keeps
`agent.py` as the one place tool *meaning* is defined while avoiding
the cycle entirely — `llm_backends.py` ends up with zero import from
`agent.py` at all.

## Files touched

`llm_backends.py` (new), `agent.py` (`_dispatch_tool_call` extracted,
`run_agent()` rewritten, `--backend` flag), `config.py`/`.env.example`
(`DEFAULT_BACKEND`/`GEMINI_API_KEY`/`GEMINI_MODEL_NAME`),
`eval_harness.py` (`--backend` flag, `save_report()`'s output gains a
`backend` field), `requirements.txt` (`google-genai`),
`spike_gemini_eval.py` (deleted), `tests/test_llm_backends.py` (new).

## Verification

Full suite green after each of the implementation plan's 6 tasks
(217 → 226 tests). Manual live verification: `--backend gemini` on 3
known questions including the exact
`msft-segment-revenue-comparison-q3fy2026` motivating case, confirmed
correct without inventing a `segment` argument; full
`eval_harness.py --backend gemini` run compared against the existing
Ollama baseline.

## Related

`docs/plans/2026-08-20-swappable-llm-backend-design.md` (design spec),
`docs/plans/2026-08-20-swappable-llm-backend.md` (task-by-task
implementation plan),
`docs/decisions/2026-08-20-comparison-reasoning-model-capability-limit.md`
(the investigation that motivated this).
