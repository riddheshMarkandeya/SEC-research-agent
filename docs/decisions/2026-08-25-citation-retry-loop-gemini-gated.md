# Citation-verification retry loop, v2 — rebuilt against Gemini, gated

**Date:** 2026-08-25

## Context

The v1 retry loop (see
`docs/decisions/2026-08-18-citation-retry-loop-v1-tried-reverted.md`) was
reverted because `qwen2.5:7b-instruct` couldn't reliably act on
corrective feedback. Revisited once the swappable-backend work
(`863bf03`) made Gemini available. Full design:
`docs/plans/2026-08-24-citation-retry-loop-design.md`.

## Decision

Rebuilt against the new backend interface (`llm_backends.py` gained
`send_followup()`). Live-tested 7 times against Gemini: the
misattribution reproduced twice, the retry fired both times, fixed it
once but not the other — critically, neither retry attempt gave up or
fabricated a number, unlike every Ollama failure mode found in v1.
Gated to Gemini only (`_CITATION_RETRY_BACKENDS = {"gemini"}`) despite
Ollama showing no regression on this run's baseline — the user's
explicit call, weighing v1's documented history against one clean
Ollama re-run.

## Why

See the plan doc for full design reasoning. A real bug found in the
mandated independent review pass (not live testing): if the retry fired
on the second-to-last iteration and the follow-up made a NEW tool call,
`run_agent()` hit the iteration cap and discarded an already-produced,
merely-warned answer for the generic timeout message. Fixed by
preserving the pre-retry `(answer, warnings)` pair.

## Files touched

`llm_backends.py` (`send_followup`), `agent.py`
(`_should_retry_for_citations`, `_format_citation_retry_message`).

## Verification

Full-suite re-runs both backends: Gemini 26/27 (same as pre-change
baseline), Ollama 21/27 vs pre-change 20/27 (one flip FAIL→PASS, zero
PASS→FAIL). See `docs/plans/2026-08-24-citation-retry-loop-design.md`
for the complete design and acceptance criteria.

## Related

`docs/decisions/2026-08-18-citation-retry-loop-v1-tried-reverted.md`
(predecessor), `docs/plans/2026-08-24-citation-retry-loop-design.md`.
