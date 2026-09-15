# `agent.py` v0: tool-calling agent (Week 5)

**Date:** 2026-08-14 (commit `00881ef`, "Week 5 (v0): tool-calling agent,
closing Week 3's company-disambiguation gap")

## Context

`answer.py` is a single-shot pipeline requiring the caller to already
know the ticker — exactly the gap Week 3's residual finding flagged as
out of scope for the retrieval layer.

## Decision

Gave the LLM a callable `search_filings` tool (wrapping
`retrieval.hybrid_search`) via Ollama's OpenAI-style `tools` API — real
tool-calling, not a hand-rolled text-parsing hack. The model decides what
to search, which ticker to restrict to, and whether to search again.
Company name resolution is baked into the system prompt as a static
ticker→name table (five static facts don't justify a round trip).
Citations stay globally numbered across multiple tool calls within one
conversation. `MAX_TOOL_ITERATIONS = 6` as a basic runaway-loop guardrail.

## Why

Verified the actual wire format empirically before writing the loop,
since getting it wrong would fail silently:
`tool_calls[].function.arguments` comes back as an already-parsed dict
(not a JSON string, unlike OpenAI's API), and the tool-result message
only needs `{"role": "tool", "content": ...}`.

The model doesn't reliably fill every schema field — observed calling
`search_filings` with only `ticker`, no `query`, despite `query` being
marked required. `_resolve_search_args()` falls back to the original
question rather than searching on an empty string. The model's own
search query is only trusted on a retry, not the first search against a
company (`searched_tickers`) — added after diagnosing that self-written
first-pass queries were either too vague or, once told to include exact
dates, too literal, in company-dependent ways no single instruction
generalized across.

Manually verified two real scenarios: an unscoped employee-count
question correctly resolved to the right ticker on its own (the direct
fix for Week 3's gap); a comparison question called the tool twice with
consistent citation numbering, but the final answer didn't actually
compare the two companies. The initial hypothesis (pure
synthesis/generation-quality gap) turned out incomplete — the eval
harness's later investigation found this was actually the 4096-token
`num_ctx` truncation bug plus the reranker demotion bug, both concrete,
fixable pipeline bugs. Lesson kept: a single manually-observed failure
with no chunk-level inspection can look like "the model isn't smart
enough" when the real cause is upstream.

## Files touched

`agent.py` (new).

## Verification

Manual scenario verification as described above (no live-model
integration tests yet at this point — that gap is closed by the eval
harness, see `docs/decisions/2026-08-13-eval-harness-scaffolding-and-early-bug-hunts.md`).

## Related

`docs/decisions/2026-08-13-answer-py-prototype-and-retirement.md`
(predecessor), `docs/decisions/2026-08-13-eval-harness-scaffolding-and-early-bug-hunts.md`
(diagnosed the real causes behind this file's own residual finding).
