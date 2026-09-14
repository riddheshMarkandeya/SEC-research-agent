# Review: table-grounding region-scoped redesign (regression fix)

Plan: `docs/plans/2026-09-13-table-grounding-region-scoped-matching.md` —
full diagnosis of two real regressions a live 47-question eval baseline
found in the original (2026-09-12) `table_grounding.py`, and the design
for the fix. Full TDD throughout; full suite green at every step
(622 → 631).

## Pass 1 — correctness and CLAUDE.md compliance (self, medium effort)

1. **[Verified, no fix needed] `text_coverage` extraction is a pure
   refactor.** Moving `_quote_matches`'s core SequenceMatcher logic into
   `numeric_utils.text_coverage` (so `table_grounding.py` can share it
   without a circular import) was verified behavior-preserving: full
   suite green before and after, with no test expectations changed for
   any `_quote_matches` test.
2. **[Fixed] Duplicated candidate-generation logic.** An early version of
   `_region_number_candidates` re-implemented `_cell_value_candidates`'s
   exact loop instead of calling it. Refactored to `_region_number_candidates`
   delegating to `_cell_value_candidates` plus a `normalize()` call —
   removes the duplication with no behavior change (verified: full suite
   still green).
3. **[Fixed, found during self-review, not by the second pass] Pure
   coverage without an anchor floor is exploitable via scattered-digit
   coincidence.** Before finalizing the design, tested it directly
   against the real MSFT fixture rather than assuming coverage alone was
   safe: a wrong claimed value (`$35,013`, Productivity's real revenue)
   scored 94% coverage against Intelligent Cloud's own permitted region
   (which contains no `$35,013` at all), purely from `difflib.
   SequenceMatcher` finding scattered, non-contiguous digit fragments
   shared with `$34,681`/`$26,751`/etc. Reintroducing the old
   `_quote_matches`-style anchor floor would have reopened the original
   short-label false negative this whole module exists to fix (a real
   short label's longest contiguous match is well under any anchor floor
   large enough to matter). Fixed instead with a separate, targeted
   number-presence check: every number-shaped token in the quote must
   equal a real number found somewhere in the region, using a TIGHT
   (near-exact) tolerance — not the loose 1%-relative tolerance
   `locate_value()` uses to find candidate cells, which would have
   recreated the same vacuity Regression B already showed (two real,
   distinct values within 1% of each other must not be treated as
   interchangeable at this layer). Added
   `test_rejects_a_value_not_actually_present_anywhere_in_the_region`.

## Pass 2 — architecture, design, performance, refactoring (fresh subagent, no memory of the implementation session)

**Verdict: found one HIGH-severity real regression, independently
verified before accepting it — not a formality.** The subagent was
explicitly briefed to be skeptical, since this is the second redesign of
this module in two days and the first one shipped with real bugs found
by a live eval run.

1. **[Fixed, HIGH] Removing the per-column period-header defense
   silently widened an accepted tradeoff further than the plan claimed,
   and reopened a case the ORIGINAL (2026-09-12) design correctly
   rejected.** The subagent extracted yesterday's committed
   `table_grounding.py` (`git show da8af5c:table_grounding.py`) and ran
   it against the exact fixture already in this repo's test suite: a
   quote asserting the FULL, plausible-sounding wrong period phrase
   (`"Three Months EndedMarch 31, 2026 Productivity and Business
   Processes Revenue $102,149"` — $102,149M is actually the NINE-month
   figure) was correctly REJECTED by yesterday's design
   (`quote_is_grounded → False`), but ACCEPTED by today's redesign as
   first implemented. Independently re-verified myself (not taken on
   trust) by running both versions side by side:
   ```
   OLD (yesterday committed) result: False   OLD cell period_header: 2026
   NEW (today redesign, before this fix) result: True
   ```
   The plan's own written justification ("already inert on this exact
   table") was drawn from a different, colspan-broken scenario, not the
   actual test fixture used to validate the redesign — a real reasoning
   error, not just an oversight in wording. The subagent also found the
   identical mechanism on NVIDIA's segment table (a quote attributing
   Compute & Networking's real $74,550M revenue to "Graphics" alone),
   independently confirmed:
   ```
   OLD Graphics-mislabel result: False
   NEW Graphics-mislabel result: True
   ```
   **Fix**: `quote_is_grounded` gained a third check — a quote may not
   cherry-pick ONE label out of a multi-column header/label row
   (`Compute & Networking | Graphics | Total`; `Three Months
   EndedMarch 31, | Nine Months EndedMarch 31,`) while omitting that
   row's OTHER labels. A quote reproducing such a row WHOLESALE (all its
   labels — the real CRM/NVIDIA regressions this redesign fixes) is
   unaffected; a quote citing only one label alongside a value that
   actually belongs to a sibling column is rejected. This required
   tracking, per `GroundedCell`, the distinct-token sets of every
   multi-cell row in the table's leading header run
   (`multi_cell_context_tokens`). Two existing tests from this same
   session's earlier (incorrect) reasoning were reverted back to
   expecting rejection (`test_rejects_a_quote_cherry_picking_one_year_
   from_the_header_row`, the `test_agent.py` wrong-period-prefix test),
   and two new end-to-end regression tests were added for the exact
   cases the subagent found
   (`test_verify_claims_rejects_a_full_wrong_period_phrase_not_just_a_
   bare_year`, `test_verify_claims_rejects_nvidia_graphics_mislabel_of_
   computes_value`). A third, more conservative side effect was accepted
   deliberately rather than special-cased: a bare period token with NO
   label at all (`"2026 34681"`) is now also rejected, since the cherry-
   pick check cannot tell "the model happened to name the objectively
   correct one of several period tokens" from "the model named the
   wrong one" without the same unreliable per-column mapping this
   redesign removed for good reason — documented in
   `test_quote_is_grounded_rejects_a_bare_year_with_no_label_at_all`.
2. **[Filed to BACKLOG.md, not fixed — latent, unevidenced] The
   `_classify_row` parenthesization heuristic could misclassify a real,
   named SEC convention.** The subagent scanned the entire local corpus
   (all 5 tickers) for every real parenthesized single-cell table row —
   all 15 occurrences are genuine captions or signature-block titles,
   none are resettable group labels, so the heuristic holds against
   today's evidence. A constructed ASC 852 Predecessor/Successor
   fixture (ordinary in bankruptcy/fresh-start-reporting filings, not
   present for any of this project's 5 tracked tickers) would
   misclassify both period labels as permanent headers, letting a
   quote's Predecessor-period label leak onto a Successor-period value.
   Consistent with this project's practice of not chasing unevidenced
   hypotheticals (see `numeric_utils.py`'s own precedent on a similar
   bare-year carve-out) — tracked, not fixed speculatively.
3. **[Filed to BACKLOG.md, not fixed — no concrete exploit found] No
   defense against similar-but-not-identical label substitution across
   groups/blocks; missing test coverage for multiple `<TABLE>` blocks.**
   Confirmed NOT exploitable in any of the 4 real fixtures (their labels
   are sufficiently distinct); confirmed no actual cross-block state
   leak (each block's `header_context`/`group_label`/`caption_units` are
   correctly recomputed independently in `locate_value`'s own loop) — the
   risk is fuzzy-matching tolerance, not a structural bug. The missing
   test coverage itself was real and is now fixed:
   `test_two_table_blocks_in_one_chunk_do_not_leak_context_between_them`
   added directly (see Pass 1 item 1's sibling fix above — this one
   landed as a direct test addition, not a design change, since the
   subagent's own testing already confirmed the mechanism is sound).
4. **[Filed to BACKLOG.md, not fixed — measured but never crossed
   threshold] Header size can measurably inflate a fabricated quote's
   coverage score.** With a synthetic header growing from 0 to 60 extra
   caption lines, a fabricated quote reusing header vocabulary moved
   from 25% to 88% coverage, plateauing there — never reaching the 90%
   acceptance line in the subagent's own testing. Same underlying
   mechanism as findings 1-2 (unconditional shared `header_context`),
   just not proven to cross the line on any real or constructed fixture.
   Recorded as a latent, low-severity watch item.
5. **[Filed to BACKLOG.md, not fixed — fails safe] A data row with a
   blank first cell (a wrapped/continuation label) misclassifies as
   "header" and silently drops out of `locate_value`'s consideration.**
   The subagent's own assessment: this fails safe (falls through to the
   ordinary flat-text `_quote_matches` path, not a false accept), just a
   silent structural-coverage gap worth a fixture/test if it recurs.

**Attacks the subagent tried and explicitly disproved** (per its own
skepticism-first brief): splicing an adjacent same-group data row into a
quote; appending the next group's label after a value; a second,
previously-untested near-1%-tolerance duplicate cell pair (Cost of
revenue: $5,517 vs $5,511, ~0.11% apart) — correctly rejected via the
tight-tolerance number check; a rounded restatement (`"$34.7 billion"`
for a `$34,681` million cell) — rejected, and assessed as the right call
given the system prompt requires verbatim quoting; percent-vs-scale
category confusion — no cross-category false match constructible,
`normalize()` keeps the two categories fully separate.

## Outcome

The HIGH finding's fix (cherry-pick check) landed with 2 new unit tests
(`tests/test_table_grounding.py`: 20 → 21, two existing tests corrected
back to their proper expectation) and 2 new end-to-end regression tests
in `tests/test_agent.py`. The multi-block test-coverage gap was closed
directly. Full suite green throughout (622 → 631). `BACKLOG.md` updated
with the four remaining lower-severity findings (parenthesization edge
case, similar-label substitution + the now-closed test gap, header-size
coverage inflation, blank-first-cell continuation rows), each tagged per
this project's convention. Live spot-checks confirmed both original
target regressions (`crm-rpo-fy26`, `nvda-segment-revenue-comparison-
q1fy27`) now pass, and the originally-reported bug
(`msft-three-segments-revenue-q3fy2026`) still passes.
