# Review: structured-claims citation verification redesign

Plan: `docs/plans/2026-09-10-structured-claims-citation-verification.md`.
Two-pass review per CLAUDE.md step 7, run after implementation + live
smoke-testing were complete and the full suite was green (557 tests at
the time both passes ran).

## Pass 1 — correctness and CLAUDE.md compliance (`/code-review`, medium effort)

1. **[Fixed] `_verify_one_claim`'s own quote-length gate duplicated (and
   drifted from) `_quote_matches`'s.** `_verify_one_claim` ran its own
   `len(_normalize_for_match(quote)) < _QUOTE_MIN_CHARS` check before
   ever calling `_quote_matches`, so it never picked up the
   `_BARE_NUMBER_MIN_DIGITS` bare-digit exception added to
   `_quote_matches` during live smoke-testing earlier the same day — a
   valid bare XBRL-number quote (e.g. `"391035000000"`, 12 chars but 12
   digits) would still be wrongly rejected as `quote_too_short` one
   layer up from where the original bug was fixed, reproducing the
   exact false positive that fix was meant to close. The existing
   regression test (`test_quote_matches_accepts_a_long_bare_xbrl_number_quote`)
   called `_quote_matches` directly and never exercised this path.
   **Fix**: extracted a shared `_quote_is_long_enough(quote_norm)`
   helper (agent.py), used by both `_quote_matches` and
   `_verify_one_claim`. Added
   `test_verify_claims_accepts_a_long_bare_xbrl_number_quote_end_to_end`,
   which goes through `verify_claims()` (the actual entry point every
   caller uses) rather than `_quote_matches` in isolation — confirmed
   red before the fix, green after.
2. **[Addressed by this doc / already in progress]** No
   `PROJECT_CONTEXT.md` changelog entry existed yet for this
   Substantial-tier change at the time of review (only the
   `docs/plans/` file existed). Landed alongside this review file, per
   CLAUDE.md step 6.

## Pass 2 — architecture, design, performance, refactoring (fresh subagent, no memory of the implementation session)

Verdict: **clean bill of health** on architecture fit — no violations
of the backend-agnostic `state`-opacity invariant, capability gating
correctly uses policy sets (`_FORCED_SUBMIT_BACKENDS`, mirroring the
existing `_CITATION_RETRY_BACKENDS` idiom) rather than branching on
backend name, `AgentResult`'s 5th field follows the same NamedTuple
growth pattern as prior fields, and the loop restructure was traced by
hand through every branch (pure submission, mixed submission at/under
budget, forced follow-up, retry, budget exhaustion) with no bugs found.
No real performance concern at realistic filing-chunk sizes (~3000
chars) — `difflib`'s cost is bounded by the (short) quote length, and
the fallback only runs after a cheap substring-match miss.

Three findings, all minor:

1. **[Fixed] Misattributed `autojunk` mechanism in `_quote_matches`'s
   docstring, AND the dedicated regression test for it didn't actually
   exercise the mechanism.** The docstring justified `autojunk=False`
   by pointing at the ~3000-char *source* chunk, but
   `difflib.SequenceMatcher`'s autojunk heuristic is keyed off
   `len(b)` — the *quote* (`quote_norm`, the third positional arg in
   `_quote_matches`'s call), not the source. Checked directly against
   CPython's `SequenceMatcher.__chain_b` source, then confirmed
   empirically: `test_quote_matches_autojunk_false_regression`'s
   original quote was only ~91 normalized characters (under the 200
   threshold), so autojunk was never actually triggered by that test —
   `autojunk=True` and `autojunk=False` produced byte-identical
   results, verified by direct computation. **Fix**: rewrote the
   docstring to correctly attribute the mechanism to the quote's
   length, and replaced the test with a real >=200-character quote
   built from short repeated clauses (so common words legitimately
   exceed the ~1%-of-length popularity threshold) paired with a source
   containing several small word-level differences — confirmed by
   direct calculation that `autojunk=True` collapses coverage to
   ~0.65 (would fail the 0.90 threshold) while `autojunk=False` gives
   ~0.93 (correctly passes), i.e. the new test actually flips the
   real `_quote_matches()` boolean result if the flag is ever
   accidentally dropped, unlike the one it replaced.
2. **[Fixed] `submit_answer` handling had no `traced_span`, unlike
   every other tool dispatch.** The most consequential call in the
   loop (the one that decides pass/refuse) was invisible to Langfuse
   and had only a local-only `log_event` on the retry/refusal path —
   CLAUDE.md's logging section calls for visibility "at decision
   points" precisely like this one. **Fix**: wrapped the
   validate/verify block in `_run_agent_impl` with
   `traced_span("tool", "submit_answer", input=args)`, updating
   `output={"warning_count", "checks"}` before the retry/finalize
   branches — matches the existing pattern in `_dispatch_tool_call`.
3. **[Deferred to BACKLOG, not fixed]** The structured-claims code is
   split into two non-contiguous regions in `agent.py`, with the
   ~320-line untouched prose-verification cluster sandwiched between
   the shared primitives (`_normalize_for_match`/`_quote_matches`/
   `_number_candidates`) and `_verify_one_claim`/`verify_claims`.
   Pure readability/organization, no behavior implication — reordering
   ~320 lines for a cosmetic-only change was judged not worth the
   diff risk right now (CLAUDE.md's anti-scope-creep principle); left
   as an optional future cleanup if this file is touched again for a
   related reason.

## Post-review live re-measurement finding (not from either formal pass)

Running the actual 41-question baseline campaign after both review
passes surfaced one more real bug, caught by inspecting the gate's
false positives directly rather than by either review pass: **the
comma-separated multi-source citation bracket bug already tracked in
BACKLOG.md for the old prose fallback path (`_CITATION_MARKER`'s
`\[(\d+)\]` not matching `[1, 3, 5]`) also affected the NEW structured
path's coverage cross-check** — `verify_claims()` stripped single-index
brackets before scanning `answer_text` for numbers, but a multi-index
bracket like `[1, 3, 5]` or `[1, 17]` survived untouched, so its bare
digits were extracted as spurious `uncovered_number` claims. This
accounted for 2 of the 5 gate false positives in the first full
baseline re-run. **Fixed** with a separate `_ANY_CITATION_BRACKET`
pattern used only by `verify_claims`'s coverage check (not
`_CITATION_MARKER` itself, which the old prose pipeline's
marker-by-marker walk can't have widened without also changing its
per-index-capture logic). See `PROJECT_CONTEXT.md`'s entry for this
work for the full before/after numbers.

## Review-loop status

Two rounds completed (the two required passes); the second round (this
document's "Post-review" finding, found afterward via live
measurement rather than a review pass) surfaced one more real, now-fixed
bug. No further review round is planned before landing — the fix was
narrow and re-covered by the full suite (558 passing) — but the
remaining open BACKLOG items from this session (`nvda-cost-of-revenue-fy2026`'s
non-reproduced `quote_not_found`, `msft-cash-to-assets-fy2025`'s
missing self-computed-value claim, `nvda-gross-margin-fy26`'s redundant
duplicate claim) are flagged for a decision once they're confirmed to
recur, not iterated on blind.
