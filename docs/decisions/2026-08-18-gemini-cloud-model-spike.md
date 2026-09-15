# Cloud-model spike: Gemini free tier (throwaway)

**Date:** 2026-08-18 (no dedicated commit — a deliberately uncommitted
throwaway spike script, dated via the surrounding same-day sections:
after the formula registry, commit `583c27a`, before the Q4-refusal fix,
commit `a055f1a`)

## Context

Tested whether `qwen2.5:7b-instruct`'s capability was the bottleneck
behind the session's recurring citation-misattribution and
comparison-question flakiness, by running the exact same system prompt,
tool schemas, and tool-dispatch logic (imported from `agent.py`, not
copied) against Google Gemini's free tier instead of local Ollama.

## Decision

Spike script `spike_gemini_eval.py`, deliberately uncommitted. Model:
`gemini-flash-lite-latest` (free tier) — `gemini-2.5-flash` 404'd, the
`gemini-flash-latest` alias resolved to `gemini-3.7-flash` whose free
tier is only 20 requests/day, too restrictive for this eval's multi-call
tool loops.

## Why

**Result: 19/21 passed, 20/21 cited.** Critically, all three
comparison-type questions passed cleanly — the single most persistently
flaky category on the local model all session — and both
previously-diagnosed misattribution cases
(`aapl-employees-fy25`, `crm-revenue-q1fy27`) passed with zero citation
warnings, confirming Gemini picks the right chunk out of the same 5
retrieved results the local model gets wrong. Two failures, both
different in character: `pltr-dividend-2019-refusal` failed on a
stricter grading-criteria technicality; `nvda-rd-expense-q4fy26-refusal`
failed by not addressing the question at all — root-caused independent
of the model (see the Q4-refusal decision file).

**Conclusion**: strong evidence the session's recurring
citation-misattribution/comparison flakiness was a
`qwen2.5:7b-instruct` capability ceiling, not a retrieval or
system-design problem — a free-tier cloud model closed nearly all the
gaps with zero retrieval changes. This argued against building query
rewriting next and gave real evidence before pursuing stricter citation
checks.

## Files touched

`spike_gemini_eval.py` (uncommitted, not tracked in `requirements.txt`).

## Verification

21-question eval run against Gemini, compared directly to the same-day
local-model baseline.

## Related

`docs/decisions/2026-08-20-comparison-reasoning-model-capability-limit.md`
(the decisive confirming test), swappable-backend work
(`docs/plans/2026-08-20-swappable-llm-backend-design.md`,
`docs/plans/2026-08-20-swappable-llm-backend.md`) that formalized this
into `llm_backends.py`.
