# Comparison-reasoning bug root-caused: local-model capability limit

**Date:** 2026-08-20 (commit `6f3a8ee`, "Root-cause the MSFT segment
comparison bug: local-model limit, confirmed")

## Context

Investigated the "correct numbers, wrong conclusion" bug left open by
`docs/decisions/2026-08-19-table-chunk-rescue-in-reranking.md`, via
three controlled, single-variable tests rather than blind re-runs.

## Decision

Root cause: **self-consistency anchoring**, not arithmetic or
formatting. Test 1 (one clean chunk, no % columns, nothing else in
context): 2/2 correct — rules out a raw number-comparison failure. Test
2 (the real 5-chunk search result, no other history): 1/3 wrong — worse
than test 1. Test 3 (the full real conversation, including the model's
own 3 earlier rejected per-segment `get_financial_fact` calls): 3/3
wrong, once hallucinating an unrelated NVIDIA sentence. The model asks
about "Intelligent Cloud" by name in its own second tool call; by the
final answer it reconfirms that segment regardless of the retrieved
numbers, even while correctly transcribing the number that disproves it.

## Why

Two candidate fixes were considered, neither implemented. System-prompt
strengthening (tried live 3x): zero effect — the model still invented
all 3 per-segment calls every run. Sanitizing rejected calls out of
message history (proposed, not built): correctly pushed back on — it
would rewrite what the model actually attempted, destroying the one
source of ground truth (`--verbose` output) a future debugging session
would need.

**Decisive test**: same question, same scaffolding, swapped to Gemini
(`spike_gemini_eval.py`) instead of local Ollama — 3/3 correct. Gemini
never attempted a per-segment call at all, went straight to
`search_filings`, retrieved and cited the same table chunk the
retrieval fix surfaces, and named the correct segment every time. This
is conclusive, not just suggestive: the retrieval fix is model-agnostic,
and the remaining failure is a genuine capability ceiling of
`qwen2.5:7b-instruct` — it invents a parameter no model needed to
invent, then can't be talked out of anchoring on it. Not worth more
prompt/history engineering on the local-model path; the real lever is
the swappable-backend work already on the roadmap.

## Files touched

None (an investigation, no code change).

## Verification

The three controlled single-variable tests plus the Gemini comparison,
as described above.

## Related

`docs/decisions/2026-08-18-gemini-cloud-model-spike.md` (the original
spike this reuses), `docs/plans/2026-08-20-swappable-llm-backend-design.md`
and `docs/plans/2026-08-20-swappable-llm-backend.md` (the roadmap item
this confirms is worth building).
