# Review: Comment audit Round 3 (self + fresh subagent)

Plan: `docs/plans/2026-09-15-comment-audit-round3.md`. Pointer-fixed 14
blocks in `xbrl_facts.py` and 6 in `numeric_utils.py`, plus wrote one
new decision file. Baseline: 634 passed.

## Pass 1 — correctness and compliance (self, medium effort)

Every pointer added was verified by reading the target
`docs/decisions/*.md` file first. The new
`docs/decisions/2026-09-15-xbrl-tag-selection-methodology.md` was
written from a careful read of the original removed comment block.
Full diff read plus the programmatic tokenize-based check (reused from
Round 2) confirmed byte-identical code in both files. Full pytest
suite: 634 passed. No findings.

## Pass 2 — architecture/design/refactor (fresh subagent, no memory of the implementation session)

1. **Broken/premature index and backlog pointers — real, but a
   sequencing artifact, not a design flaw.** The subagent ran while
   `docs/plans/2026-09-15-comment-audit-round3.md`,
   `docs/decisions/2026-09-15-comment-audit-round3.md`, and this review
   file were still being written — `PROJECT_INDEX.md`/`BACKLOG.md`
   already referenced them, and the new xbrl decision file's own
   "Related" section pointed at the not-yet-written round decision
   file. All three now exist as of this file landing. **[Fixed]** by
   completing this round's own documentation step, not by changing the
   pointers.
2. **Information loss in `numeric_utils.py`'s `NUMBER_PATTERN`
   comment — real, moderate severity.** The original comment explained
   why `sign` needs its OWN `(?<!\d)` lookbehind (not just relying on
   the digit group's) — a hyphen-joined ISO date ("2024-01-25") and a
   hyphenated range ("10-15 percent") would otherwise have their second
   half misread as negative. This reasoning was dropped entirely during
   the trim, and — confirmed by the reviewer reading
   `docs/decisions/2026-09-11-negative-number-support.md` in full — no
   decision file documents it either. A future maintainer "simplifying"
   the lookbehind placement could silently reintroduce that bug with
   nothing warning them off, even though
   `test_extract_numbers_iso_date_stays_positive_not_misread_as_negative`/
   `test_extract_numbers_hyphenated_range_stays_positive` would still
   catch it in CI. Exactly the class of "algorithmic why" this round's
   own standard says must survive a trim. **[Fixed]**: restored the
   ISO-date/hyphenated-range reasoning directly in the comment (it has
   no other home to point to), keeping the rest of the trim intact.
3. **Weak pointer — minor.** `normalize_for_match()`'s docstring cited
   `docs/decisions/2026-09-12-structure-aware-table-quote-grounding.md`
   for "why this lives here rather than in agent.py," but that
   decision file's own "Files touched" section never lists
   `numeric_utils.py` or mentions the function move — the specific
   claim wasn't actually where the pointer said it was, even though the
   causal story is thematically correct and same-dated. **[Fixed]**:
   repointed to the actual source of that specific claim,
   `docs/plans/2026-09-12-structure-aware-table-quote-grounding.md`'s
   "New module: table_grounding.py" section, which states it directly
   ("the same reasoning that produced numeric_utils.py").
4. **Everything else — PASS.** The new decision file is a faithful,
   complete extraction of the original comment (the CRM-test discovery
   story, all five follow-on metrics, the InventoryNet business-model
   distinction, nothing added or distorted). ~12 other pointers
   spot-checked all resolve to files that accurately cover the claimed
   content. No stale `PROJECT_CONTEXT.md` references remain in either
   file. Every changed line in both `.py` files sits inside a comment
   or docstring — no logic/code lines touched.

## Fixes applied

- Restored the ISO-date/hyphenated-range reasoning behind `sign`'s own
  lookbehind placement in `numeric_utils.py`'s `NUMBER_PATTERN` comment.
- Repointed `normalize_for_match()`'s docstring to the plan doc section
  that actually states the claim, instead of the decision file that
  doesn't.
- Completed this round's own plan/decision/review trio, closing the
  dangling pointers finding #1 identified.
- Re-ran the programmatic comment-only-diff check and the full pytest
  suite after applying fixes: still comment-only in both files, still
  634 passed.

## Outcome

Two real findings (#2, #3), both fixed the same pass; finding #1
resolved by completing the round's documentation step. Finding #4
confirmed clean, no action needed. No second review round needed — both
fixes were small, targeted, and verified immediately.
