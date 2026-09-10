# Review: uncited-claim detection, get_frame() ordering fix, verify_retrieval.py (2026-09-09/10)

Reviewing the change described in `docs/plans/2026-09-09-citation-gap-frame-ordering-retrieval-verify.md`.

## Pass 1: `/code-review` (medium effort) — correctness/compliance

One real, confirmed, high-severity bug in `_iter_uncited_claims()`
(`agent.py`):

**The "no sentence break" check alone doesn't determine which SPECIFIC
claim a marker attaches to.** The design at that point checked "is
there a marker within `_CITATION_WINDOW_CHARS` of this claim, in either
direction, with no sentence-ending punctuation between them" — but a
marker sitting between TWO claims in the same comma-joined sentence
(one it genuinely cites, one it doesn't) would wrongly "cover" both,
since neither has a sentence break relative to the marker. Reproduced
live: `verify_citations("Microsoft's cash was $20 billion [1],
representing approximately 4.0% of total assets.", [...])` returned
`[]` — the self-computed, uncited 4.0% (the exact
msft-cash-to-assets-fy2025 shape this feature exists to catch) slipped
through entirely, merely because it was comma-joined rather than
period-joined to the citation for the OTHER figure in the sentence.

**Fix**: redesigned so each marker attaches to **at most one** claim —
the nearest reachable claim immediately before it (the dominant `"$X
[1]."` convention), or, only if none is reachable, the nearest reachable
claim immediately after it (the `"Per source [1], $X"` convention).
Never both directions, and never more than the one nearest claim on
whichever side it attaches to. Reachability itself (window distance +
no sentence boundary, with the trailing-marker exception) is unchanged
from before — still needed on top of the one-claim-per-marker rule,
since without it a marker would wrongly attach across sentence
boundaries (the original msft-cash-to-assets false negative this
function was built to fix in the first place).

Two new regression tests added (`tests/test_agent.py`): a comma-joined
second uncited claim after a real citation (`"$20 billion [1],
representing approximately 4.0%..."`), and the mirror case for a
leading marker (`"Per the 10-Q filing [1], revenue was $X and margin
improved to 42%."`) — both now correctly flag only the genuinely uncited
second claim. Full suite: 456 passed after the fix (was 454 before this
pass; the extra 2 are the new regression tests).

All other angles the reviewer checked came back clean: `xbrl_facts.py`'s
tag-conflict handling, cross-file callers of `extract_numbers`/
`verify_citations`, the citation-marker-digit span exclusion, dedup-key
changes, and general reuse/simplification/efficiency/CLAUDE.md
conventions.

## Pass 2: architecture/design (fresh subagent)

Findings from a subagent with no memory of the implementation session,
given the diff and plan context cold.

1. **[Fixed] `_iter_uncited_claims()`'s docstring was disproportionate to
   the codebase's style** — ~65 lines re-narrating the full rejected-
   design history that already lives in the plan/review docs, versus
   ~18 lines for the comparable sibling `_iter_citation_claims()`.
   Trimmed to state the current contract concisely (one-claim-per-marker
   rule, reachability definition) with a pointer to the plan/review docs
   for the "why not simpler" history, instead of re-deriving it inline.
2. **[Fixed] Unnecessary `max()`/`min()` calls in the marker-attachment
   loop.** `claims` is built by walking `extract_numbers_with_spans()`
   via `finditer()`, so it's already in left-to-right position order —
   `before[-1]`/`after[0]` give the same nearest-claim result without
   the extra scan and lambda. Applied as a one-line simplification
   alongside the docstring trim.
3. **Performance (nested scan over markers × claims): explicitly
   assessed and left as-is.** Negligible at this codebase's actual
   scale (LLM answer text, a handful of markers/claims, run once per
   final answer) — a position-sorted single-pass algorithm would trade
   a few list comprehensions for pointer bookkeeping that's harder to
   verify against the attachment rule, for no real benefit here.
4. **Structural split into two functions: not warranted.** The
   reachability logic and the marker-attachment loop are already
   visually separated via the `_reachable` nested helper; the docstring
   (addressed by #1) was the actual readability problem, not the code
   shape.
5. **`agent.py` vs `xbrl_facts.py` logging consistency: confirmed fine,
   not a new finding.** These aren't parallel patterns that diverged —
   `agent.py` doesn't need a new `log_event` call because the existing
   `citation_retry` log call already logs whatever `verify_citations()`
   returns, uncited-claim warnings included, for free; `xbrl_facts.py`
   had no equivalent pre-existing logging surface for `get_frame()`, so
   the new explicit `log_event("xbrl_tag_conflict", ...)` was the only
   way to make that decision point visible.
6. **`tests/manual/verify_retrieval.py`: matches sibling conventions
   well** (checked against `verify_period_labels.py`/`verify_tracing.py`)
   — the `sys.path.insert` shim, module-docstring rationale,
   checked/confirmed/problems reporting, and clean-skip-on-missing-setup
   pattern are all present and idiomatic. No inconsistency found.

Full suite after fixes: 456 passed. Full text of the architecture
subagent's response is preserved in this session's transcript.

## Pass 3: `/code-review`, multi-angle (round 2 on the fix)

A broader multi-angle pass (8 parallel finder angles: correctness A/B/C,
reuse, simplification, efficiency, altitude, conventions) surfaced
several more real, distinct issues — the design from Pass 1 fixed the
comma-joined false negative, but the "at most one claim per marker"
rule it introduced turned out to be too restrictive for a different,
equally common pattern:

1. **[Fixed] "At most one claim per marker" broke legitimate multi-claim
   citations.** `verify_citations("Revenue grew from $10 million to $12
   million, a 20% increase [1].", [source with 10 and 12 but not 20])`
   wrongly flagged the genuinely-grounded $10M and $12M as uncited,
   because the marker attached only to its single nearest claim (20%).
   Redesigned again: each marker now attaches to **every** reachable
   claim on its chosen side (backward preferred, else forward), not
   just the nearest one — `_iter_citation_claims()` still independently
   verifies each covered claim's accuracy, so the genuinely-wrong 20%
   is still caught, just without also falsely flagging the correct 10
   and 12. Two new tests added (`test_verify_citations_covers_every_
   reachable_claim_sharing_one_trailing_citation`, and the leading-
   marker counterpart `test_verify_citations_leading_marker_covers_
   every_reachable_claim_that_follows_it`, which replaces a Pass-1 test
   whose "only the nearest claim" premise no longer held).
2. **[Fixed] `xbrl_facts.py`: a same-tag duplicate entry (e.g. an
   amended filing under one tag) was mislabeled as a cross-tag
   `xbrl_tag_conflict`.** Now only logged when the two entries'
   tags actually differ.
3. **[Fixed] `agent.py`: two `any()` comprehensions filtering `claims`
   by `non_claim_spans` and `marker_spans` separately** merged into one
   `excluded_spans` list (simplification angle).
4. **Reuse-angle findings, left as-is deliberately**: `verify_citations`'s
   two claim-processing loops share a near-identical dedup-and-append
   shape: not extracted into a helper, per this project's own
   established convention of not abstracting until a 3rd occurrence
   needs the same shape (see `formulas.py`'s still-unextracted
   zero-denominator-guard duplication, `BACKLOG.md`). Similarly,
   `_iter_citation_claims`/`_iter_uncited_claims` filter `_NON_CLAIM_PATTERN`
   via two different techniques (string substitution vs. span exclusion)
   for a structural reason, not an oversight: the former needs a
   re-extractable substring, the latter needs positions in the
   untouched original text.
5. **Efficiency angle: no findings.** Explicitly assessed the nested
   markers×claims scan and the duplicated `_CITATION_MARKER.finditer()`
   call between the two functions — both negligible at this codebase's
   real scale (LLM answer text, single-digit markers/claims, run once
   per final answer, dwarfed by the surrounding network/LLM round-trip).
6. **Cross-file tracer: no findings.** Every consumer of `verify_citations()`,
   `get_frame()`, and `extract_numbers`/`extract_numbers_with_spans`
   checked and confirmed unaffected by the new warning shape/return
   values.

Full suite after fixes: 459 passed.

## Pass 4: `/code-review`, multi-angle (round 3 on the fix)

Another multi-angle pass, since round 2's fixes were themselves new
surface area:

1. **[Fixed] `_SENTENCE_BREAK` regex backtracking bug.** The pattern
   `r"[.!?]\s+(?![\[a-z])"` let the greedy `\s+` backtrack to a SHORTER
   whitespace match whenever the maximal one failed the lookahead, so
   `"billion.  [1]"` (two spaces) still registered a false break — the
   exact false-refusal bug the lookahead exists to prevent, just
   triggered by extra whitespace instead of an abbreviation. Rewritten
   as `r"[.!?](?=\s)(?!\s*[\[a-z])"`, moving the whitespace check inside
   lookaheads (which don't backtrack the outer match) so it's immune to
   how much whitespace actually follows.
2. **[Fixed] `xbrl_facts.py`: alphabetical tag tiebreak was arbitrary,
   ignoring an already-known correct answer.** `get_frame()` already
   computes each ticker's own correct tag via `_tag_for(ticker, metric)`
   (it's what builds `tags_in_play` itself); a ticker whose own tag
   happened to sort second alphabetically would silently keep a WRONG
   value from a different tag that incidentally also reported its CIK.
   Now the ticker's own designated tag always wins, with alphabetical
   order only as a fallback tiebreak when neither colliding tag is the
   ticker's own.
3. **[Fixed] Cross-loop duplicate warnings.** A claim near a marker
   under `_iter_citation_claims`'s flat character-distance window, but
   NOT reachable under `_iter_uncited_claims`'s sentence-aware definition
   (a real, if narrow, disagreement between the two functions' notions
   of "near"), could get flagged by both — same value, two different
   messages. Fixed via a shared `seen_values` dedup set the citation-
   claims loop populates and the uncited-claims loop checks.
4. **[Fixed, in the SAME round] Regression in fix #3**: the naive fix
   (dedup key = value+unit alone, dropping the citation index) also
   collapsed two genuinely different, independently-broken citations
   that happen to share a value (`"$99M [1]... $99M [2]."`, neither
   source containing 99) into a single warning, silently dropping that
   `[2]` is broken too. Fixed with two separate dedup sets:
   `seen_citation_keys` (index + value, precise, citation-claims' own
   within-loop dedup) and `seen_values` (value-only, populated by
   citation-claims, checked by uncited-claims for the cross-loop case).
5. Accepted, documented, not fixed: a genuine new sentence that happens
   to start with a lowercase word is treated as not a break (a
   consequence of the abbreviation-period exception) — a false
   NEGATIVE, not the false POSITIVE the exception exists to prevent,
   and rare in real prose. Locked in with
   `test_verify_citations_accepts_missing_a_break_for_a_lowercase_starting_sentence`
   so a future "fix" doesn't reintroduce the abbreviation bug instead.
   An out-of-range citation marker (`[5]` with only 1 real source) is
   pre-existing, deliberately-tested behavior (`test_verify_citations_
   ignores_out_of_range_citation_index`, predates this change) —
   left unchanged for consistency, not relitigated.

Full suite after fixes: 464 passed.

## Pass 5: `/code-review` (round 4) + fresh architecture subagent (final gate)

- **`/code-review` round 4**: one real, minor finding — `xbrl_facts.py`'s
  tag-override condition (`tag == designated_tag and winning_tag[ticker]
  != designated_tag`) had a logically dead second clause (always true
  given the same-tag-duplicate branch already ran first). Simplified to
  `tag == designated_tag` alone.
- **Fresh architecture subagent, told the full round 1-4 history**: read
  `_iter_uncited_claims`/`_SENTENCE_BREAK`/`verify_citations` and
  `get_frame()` end-to-end, traced several adversarial inputs beyond
  what's tested (multi-claim collisions, 3-way tag collisions in both
  processing orders) live against the working tree — found no new code
  bug. Flagged that this review doc and `PROJECT_CONTEXT.md`/
  `BACKLOG.md` hadn't yet been updated to reflect the final ("every
  reachable claim") design — expected, since those doc-finalization
  steps were still pending at that point in the session, not a code gap.

Full suite: 464 passed. No new issues in round 5 beyond the one dead-code
cleanup and the (expected, now-addressed) documentation gap — stopping
here per CLAUDE.md's two-clean-rounds guidance, applied loosely given
how many real, distinct, increasingly narrow issues the earlier rounds
had already surfaced and fixed.

