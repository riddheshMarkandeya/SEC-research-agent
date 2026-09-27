# Strip the citation header echoed without its "[n] " prefix

**Date:** 2026-09-27

## Context

`_strip_citation_header` removes the citation header the model sometimes copies into a claim
quote, because that header is never part of the source text the quote is grounded against. The
2026-09-19 fix stripped only the exact `[n] TICKER FORM (reportDate=…)` header and deliberately
left reformatted copies alone, since none had been seen live.

One reformatted copy is now proven live: the header without its `[n] ` prefix. It caused both
NVDA drops in the WP8 full run (`nvda-revenue-fy26` run `d00cb8964070`, withheld with
`gate_withheld_would_have_passed: True`; `nvda-gross-margin-fy26` run `b8d0368b4dda`). The
traces hold 29 distinct submit-span quotes containing `reportDate=`: 17 unprefixed (one
space-separated instead of `\n`) and 12 prefixed, all at the start of the quote, all matching
their cited result's metadata, across 9 days from 09-11 to 09-27.

## Decision

Revisits the 09-19 exact-match-only decision for this one variant. The function now strips the
exact header, or the exact header minus its leading `[n] `, both rebuilt from the claim's own
citation index and metadata. Case-folded or otherwise reworded copies are still left alone: there
is still no live evidence for them. Code commit `022e851`.

## Why

- **Bounded loosening of a trust gate.** The bare header is still reconstructed exactly, so a
  header naming a different ticker, form or reportDate is never stripped. It is shared by every
  chunk of the same filing, which is harmless: the remainder of the quote must still ground
  against result [n]'s own text, and the grounding check itself is unchanged.
- **Only fix point.** `_verify_one_claim` is the only reader of the quote, so retries, the
  budget-exhausted path and qualitative claims all get the fix.
- **Prefix coupling kept as a literal.** `agent.py` hard-codes the `[{n}] ` prefix rather than
  splitting `CITATION_HEADER_TEMPLATE` into parts. Splitting would change the fingerprinted
  prompt constants for no model-visible change. The template's comment states that the prefix
  must stay a prefix, and the unprefixed-strip test (a hand-written literal header) fails if it
  moves.
- **No fingerprint change.** The `prompts/` edit is a comment only; agent fingerprint stays
  `7aec53939ce3`. Before/after comparisons for this fix must use explicit mode.

## Files touched

`agent.py` (`_strip_citation_header`), `prompts/agent_messages.py` (comment above
`CITATION_HEADER_TEMPLATE`), `tests/test_agent.py`.

## Verification

- TDD: 6 new test cases (unprefixed header with `\n` and space separators; unprefixed header for
  another form or reportDate left alone; `verify_claims` end to end on the real WP8 claim shapes,
  `215.938 billion` and `71.1 percent`). The 4 positive cases failed before the fix; the 2
  negative ones guard the boundary. Suite 969 passed; ruff 0,
  pyright 0; diff coverage agent.py 97.4% (uncovered lines are from earlier commits),
  prompts 100%; model-input snapshot unchanged.
- Live spot-check on `022e851` (clean tree), `eval_harness.py --backend gemini --ids
  nvda-revenue-fy26,nvda-gross-margin-fy26` ×3: reports `20260927T203017Z`, `20260927T203045Z`,
  `20260927T203112Z`, **6/6 passed** (WP8 report `20260927T071935Z`: 0/2). Explicit-mode compare
  vs WP8: both questions `improved`.
- Trace read-back (`trace_query.py records --kind submit_answer … --since 2026-09-27T20:29`):
  none of the 6 submit spans echoed the header in any form, and all had empty `checks`. So the
  live runs show no regression but didn't exercise the new path. The header echo depends on the
  sampled run. The evidence that the fix works is the unit tests on the real WP8 claim shapes.
- The gross-margin "4.5 billion" prose answer from WP8 did not recur in these runs.

## Related

- Revisits: `docs/decisions/2026-09-19-citation-header-in-quote-fix.md`
- Found by: `docs/decisions/2026-09-27-wp8-final-run.md`
- Review: `docs/reviews/2026-09-27-unprefixed-citation-header-strip.md`
