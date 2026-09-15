# Citation-verification retry loop (v1) — tried and reverted

**Date:** 2026-08-18 (commit `62f2d16`, squashed with
`docs/decisions/2026-08-18-per-claim-citation-placement-rule.md`)

## Context

With the eval-gate change showing real, recurring misattribution
(`aapl-employees-fy25`, and a newly-confirmed `crm-revenue-q1fy27`
citing an unrelated dividend-program chunk instead of the actual revenue
chunk), the idea of having `run_agent()` self-correct on its own
unverified citations was revisited with much stronger evidence than
when first deferred.

## Decision

**Tried and reverted.** When the final answer had an unverified citation
and the run hadn't already retried once, feed the model its own draft
answer plus the specific warning strings as a corrective follow-up, and
let it try again — sharing the existing `MAX_TOOL_ITERATIONS` budget.
Built via TDD as two pure helpers, `_should_retry_for_citations()` and
`_format_citation_retry_message()`.

## Why

The mechanism worked exactly as designed (triggered correctly, capped at
one retry, fed back real warnings) but did not reliably improve answer
quality: `aapl-employees-fy25`'s retry gave up entirely instead of
checking already-retrieved chunks; `crm-revenue-q1fy27`'s retry
re-located the correct passage but still mislabeled which citation index
it belonged to. A real, worse regression: the first retry message's
"final attempt" framing pushed the model to fabricate an "estimated" R&D
figure on `nvda-rd-expense-q4fy26-refusal` — a question it had answered
correctly (an honest refusal) before any retry mechanism existed.
Rewording to explicitly permit a refusal outcome and prohibit
inventing/estimating did NOT fully fix it either — the same question,
re-tested, still fabricated an "estimate." Per this project's debugging
discipline (two attempts landing in the same failure mode), this was
brought back for a decision rather than a third wording tweak.

**Decision: reverted.** The retry costs one extra ~60-90s Ollama round
trip on every citation warning without reliably improving the answer on
`qwen2.5:7b-instruct` — not a good trade. The eval-harness gate and
`verify_citations()`/`value_is_citation_verified()` themselves stayed in
place; only the runtime self-correction attempt was removed. Marked for
revisit once working with a more capable model — the design was sound
and cheap to rebuild.

## Files touched

`agent.py` (added then reverted the retry call sites; the pure helper
functions and their tests were kept dormant for future reuse).

## Verification

Live testing against the two confirmed misattribution cases, and the
`nvda-rd-expense-q4fy26-refusal` regression case, as described above.

## Related

`docs/decisions/2026-08-25-citation-retry-loop-gemini-gated.md` (the
successful rebuild, once the swappable Gemini backend existed).
