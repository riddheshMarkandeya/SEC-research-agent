# Review: citation-header-in-quote fix

Plan: `docs/plans/2026-09-19-citation-header-in-quote-fix.md`. Fix to
`agent.py`'s structured-claims citation-verification path; full suite
before this diff: 707 passing (after the prior session's flaky-eval
three-fix work).

## Plan review (independent subagent, before implementation)

Confirmed `_format_results_block`'s exact header format and that
extracting a shared `_citation_header` helper is a byte-identical
refactor; confirmed the insertion point in `_verify_one_claim` is
correct (after the range/malformed-claim checks, before dispatch);
directly executed the proposed fix against the real failing data and
confirmed all 3 claims from `nvda-crm-revenue-comparison`'s baseline
row ground correctly (the plan's own first draft had undercounted this
as "both" instead of all 3 — corrected before approval); confirmed
every `all_results`-producing function always populates
`ticker`/`form`/`reportDate`, so no `KeyError` risk; found, via direct
execution, that a case-folded header echo would NOT be caught by the
exact-match design — the plan's Scope section overstated the fix as
"fully and deterministically" closing the gap, softened to name this
limitation explicitly before approval, with a new `BACKLOG.md` item
added to the plan's own documentation step.

## Code review (independent, after implementation — `/code-review medium`)

Five finder angles run in parallel.

- `[Fixed]` **Simplification**: `stripped[len(header):].lstrip("\n").lstrip()`
  called `.lstrip()` twice for no behavioral difference (the bare
  `.lstrip()` alone already subsumes `.lstrip("\n")`), and manual
  `startswith` + index-slice reimplemented `str.removeprefix` (stdlib,
  available on this project's target Python). Collapsed to
  `stripped.removeprefix(header).lstrip()`.
- `[Fixed — real regression against the prior session's Fix B]`
  **Raw-quote loss**: `_verify_one_claim` reassigned `quote` to the
  header-stripped value before it reached
  `_verify_numeric_claim`/`_verify_qualitative_claim`, so any resulting
  `CitationWarning.quote`/`.message` showed the *cleaned* quote, not
  what the model actually wrote — erasing the exact header-echo signal
  for any claim where grounding still failed for an unrelated reason.
  Fixed by introducing `_ClaimQuote(raw, grounding)`: grounding checks
  run against `.grounding`, every `CitationWarning` now records `.raw`.
  A new regression test
  (`test_verify_claims_records_the_raw_header_included_quote_when_grounding_still_fails`)
  constructs a claim with a genuinely wrong value (999, header still
  present) and confirms the resulting warning's `.quote` field still
  shows the header-included raw text.
- `[Verified, no fix needed]` A related observation (the length gate
  now runs on the stripped quote, so a header-padded-but-genuinely-
  too-short quote correctly reports `quote_too_short` instead of
  falling through to `quote_not_found`) was confirmed by the same
  finder to be a behavior *improvement*, not a regression — no code
  change, noted here for the record.
- `[Verified, no fix needed]` Three findings (doubled header echo,
  case/whitespace-varied echo, prose framing before the header) all
  restate the plan's own already-documented, deliberately-accepted
  exact-match-only limitation. `BACKLOG.md` item broadened to name all
  three shapes explicitly rather than only the case/whitespace variant
  originally planned.
- `[Verified, no fix needed]` Altitude and cross-file tracer angles:
  confirmed the fix sits at the one call site dominating both
  consumers of `_quote_matches` (no unfixed sibling path), confirmed
  the prose-fallback path (`collect_citation_warnings`) is structurally
  immune (no model-echoed `quote` field to leak a header into), and
  confirmed no stale-quote/double-strip hazard from `claim["quote"]`
  being read in exactly one place.

**Second-order fix required by the raw-quote fix itself**: threading
both quote variants as separate parameters pushed `_verify_numeric_claim`
to 6 positional arguments, tripping this project's `ruff` `PLR0913`
limit (5) — confirmed via direct before/after ruff diff (62 violations
before, 63 immediately after, back to 62 once resolved). This is new
code tripping the limit, not inherited debt, so fixed rather than
deferred, per this project's incremental-improvement policy. The
`_ClaimQuote` bundle already introduced for the raw-quote fix resolved
it as a side effect (5 args: `n, value, unit, quote_pair, source_text`).

## Live verification

- `nvda-crm-revenue-comparison` (the confirmed repro):
  `eval_harness.py --backend gemini --ids nvda-crm-revenue-comparison`
  run 3 times, 3/3 passed
  (`eval/eval_results/20260919T0219{35,49}Z.json`,
  `20260919T022004Z.json`).
- `msft-segment-revenue-comparison-q3fy2026` (secondary, not-guaranteed
  check): run 3 times, failed all 3 for 3 different reasons
  (`eval/eval_results/20260919T022{051,124,158}Z.json`) — one via a
  judge-strictness disagreement, one via a genuine `quote_not_found` on
  an unrelated value, one via `uncovered_number`. Judged-type questions
  don't get `citation_warning_details` populated at all
  (`eval_harness.py`'s own pre-existing, unrelated scoping choice), so
  there's no way to confirm or rule out this fix's relevance to any of
  the 3 failures from the saved reports. Treated as expected,
  chronic pre-existing flakiness per the plan's own stated expectation
  going in — not evidence against the fix.
- Direct-execution sanity check post-refactor (after the `_ClaimQuote`
  change): re-confirmed both that the real bug case still grounds
  cleanly and that a genuinely-wrong-value claim with the header still
  present now correctly shows the raw (header-included) quote in its
  warning.

## Outcome

Shipped: `_citation_header`/`_strip_citation_header`/`_ClaimQuote`,
`_format_results_block` refactored to the shared helper,
`_verify_one_claim`/`_verify_numeric_claim`/`_verify_qualitative_claim`
updated. 5 new tests plus 1 pre-existing test re-confirmed unchanged.
Full suite: 707 passing. `ruff`/`pyright` scoped to changed files: back
to the exact pre-existing baseline (62 ruff violations, 0 pyright
errors on `agent.py`) after the two review-driven fixes above.

Still open, filed to `BACKLOG.md`: the exact-match-only limitation
(doubled header, case/whitespace variance, or prose framing before the
header all defeat the strip) — revisit only if one of these shapes is
observed live, per this project's practice of not chasing unevidenced
hypotheticals.

Review loop closed after one round (code-review skill), no second
round needed — this diff's two real findings were both fixed and
directly re-verified (tests + ruff/pyright diff + a direct-execution
sanity check) in the same pass, and no new issue surfaced from that
verification.
