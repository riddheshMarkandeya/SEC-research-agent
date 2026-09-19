# Fix the citation-header-in-quote grounding bug

## Context

Following the flaky-eval-questions three-fix session (commit `5ac2e8c`),
Fix B (capturing the model's actual claimed quote text in
`CitationWarning`) immediately surfaced a new, previously-invisible
finding on the very next live baseline run: `nvda-crm-revenue-comparison`'s
`quote_not_found`/`value_not_in_quote` refusal on 3 genuinely-correct
values, logged to `BACKLOG.md` as `[bug (latent), Med, Standard]`.

Root-caused precisely: the model's quote for a `get_financial_fact`/
`calculate` result includes `_format_results_block`'s own display-time
citation header (e.g. `"[1] NVDA 10-Q (reportDate=2026-04-26)\n..."`),
which is never part of the underlying `all_results[n-1]["text"]` the
quote is grounded against — it's added only when results are rendered
for the model to read. Confirmed by direct execution against the real
failing data: `text_coverage()` scores the header-included quote at
63% coverage against `source_text`, well under the 90%
(`_QUOTE_COVERAGE_THRESHOLD`) `_quote_matches()` requires.

## Decision / Design

Reconstruct the exact header for a claim's own citation index from its
`all_results` metadata (not a generic regex) and strip it from the
claim's `quote` before any grounding check runs:

1. Extract a shared `_citation_header(i, meta) -> str` helper from
   `_format_results_block`'s existing inline f-string — used by both
   that function and the new stripping logic, so they can't drift
   apart.
2. `_strip_citation_header(quote, n, meta) -> str` reconstructs the
   header and strips it only on an exact match.
3. `_verify_one_claim` calls this once, before dispatching to
   `_verify_numeric_claim`/`_verify_qualitative_claim`.

Verified directly against all 3 real failing claims from the
`nvda-crm-revenue-comparison` baseline row (two `get_financial_fact`
claims, one `calculate`-result claim with placeholder metadata) — all
three ground correctly after stripping.

Deliberately code-only: a prompt-side nudge was considered and set
aside, since the code fix already closes the exact pattern observed
live. Deliberately exact-match-only, not a fuzzy/case-insensitive
match: ties the strip precisely to what this citation actually
displayed, at the cost of not catching a case-folded or reformatted
echo of the header — an accepted, stated limitation, not chased
speculatively per this project's practice.

## Design evolution during code review

Two independent findings from the post-implementation review round
changed the shipped design from the first working version:

- **Raw-quote preservation.** The first version reassigned `quote`
  in-place to the stripped value before it flowed into
  `_verify_numeric_claim`/`_verify_qualitative_claim`, so any resulting
  `CitationWarning` recorded the *cleaned-up* quote, not what the model
  actually wrote — silently erasing the header-echo signal for any
  claim where grounding still failed for some unrelated reason.
  Directly undermines the prior session's Fix B, whose entire purpose
  was preserving that signal. Fixed by threading both the raw and
  header-stripped quote through as a small `_ClaimQuote(raw,
  grounding)` NamedTuple: grounding checks run against `.grounding`,
  every `CitationWarning` records `.raw`.
- **Argument-count fix bundled with the above.** Passing both quote
  variants as separate positional parameters pushed
  `_verify_numeric_claim` to 6 arguments, tripping this project's ruff
  `PLR0913` limit (5) — a violation on new code, not inherited debt, so
  fixed rather than deferred. The `_ClaimQuote` bundle (already needed
  for the raw-quote fix above) resolved this as a side effect.
- A separate simplification finding (redundant double-`.lstrip()` calls,
  and manual index slicing where `str.removeprefix` is the direct
  stdlib match) was also applied.

Three further findings from the same review round were assessed as
restating the plan's already-documented, deliberately-accepted
exact-match-only limitation (a doubled header echo, a case/whitespace-
varied echo, and framing text preceding the header all defeat the exact
match the same way) — no code change, generalized the planned
`BACKLOG.md` follow-up item to cover all three shapes under one entry
instead of the narrower one originally planned.

## Testing and verification

Full red-green TDD (pure functions, not live-only code). Live spot-check
per `.claude/rules/live-eval-verification.md`: `nvda-crm-revenue-comparison`
(the confirmed repro) re-run 3 times against Gemini, 3/3 passed.
`msft-segment-revenue-comparison-q3fy2026` re-run 3 times as a secondary,
not-guaranteed check (not confirmed to share this root cause) — still
failed each time for 3 different reasons, none attributable either way
since judged-type questions don't get `citation_warning_details`
populated in `eval_harness.py`'s own existing scoping; treated as
expected, pre-existing chronic flakiness per the plan's own stated
expectation, not evidence against the fix.
