# `answer.py` v0 prototype, and its 2026-08-25 retirement

**Date:** 2026-08-13 build (commit `6197108`, Week 3); retired 2026-08-25
(commit `c21cb5a`, "Retire answer.py (Week 3 prototype), superseded by
agent.py")

## Context

The first end-to-end answer pipeline, built to prove out
`hybrid_search()` plus a "cite everything or refuse" LLM prompt before
the agent-with-tools architecture existed.

## Decision

Retrieves via `hybrid_search()`, feeds numbered excerpts to
`qwen2.5:7b-instruct` via Ollama, prints the answer plus a citation key.
Chose to pull a stronger 7B model rather than default to the smaller
`qwen3.5:4b` already on hand — a weaker model's instruction-following on
strict citation formatting would have made it hard to tell, in Week 4's
evals, whether a failure was retrieval or model-capability. Explicitly a
v0 prototype: grounding was enforced only by prompt instruction, no
output parsing verified every claim actually carried a marker or matched
its source.

## Why

Spot-checked both success and refusal paths: correctly cited only the
one relevant CRM chunk of 5 retrieved; correctly refused to fabricate a
2019 PLTR dividend figure. A residual finding, not a bug: the employee-
count query still didn't reliably surface the right chunk in an
*unfiltered* top-5 across all 5 companies, even after hybrid search +
reranking, though filtered to the correct ticker it ranked #1 — meaning
retrieval itself was sound, what was missing was *company
disambiguation*, squarely a Week 5 agent-layer responsibility.

**Retirement (2026-08-25)**: `agent.py` was by then a strict superset —
no functional code imported `answer.py` (only comments/docs referenced
it; `eval_harness.py` had already switched to `agent.run_agent()` back
in Week 5) — so removal was a pure deletion, not a migration. Removed
`answer.py` and its dedicated test file; updated stale mentions in
`config.py`, `requirements.txt`, `.env.example` (comments only).

## Files touched

`answer.py` (new, then deleted), `tests/test_answer.py` (new, then
deleted), `config.py`/`requirements.txt`/`.env.example` (comment
updates at retirement).

## Verification

Manual spot-checks at build time. At retirement: full suite 253 passed
(down from 258, the 5 tests that existed only to cover this file), no
other regressions.

## Related

`docs/decisions/2026-08-14-agent-v0-tool-calling.md` (the successor that
closes the company-disambiguation gap this file's own residual finding
named).
