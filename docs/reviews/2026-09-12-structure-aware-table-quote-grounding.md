# Review: structure-aware table quote grounding (`table_grounding.py`)

Plan: `docs/plans/2026-09-12-structure-aware-table-quote-grounding.md` —
full investigation, design reasoning, and measured evidence for why a
threshold-tuning fix to `_quote_matches`'s anchor floor was rejected in
favor of parsing table structure. Full TDD throughout (`table_grounding.py`
written test-first against real filing text); full suite green at every
step (601 → 622).

## Pass 1 — correctness and CLAUDE.md compliance (self, medium effort)

1. **[Fixed] The structural check was stricter than the flat-text check
   it replaced, on genuine reformatting.** The first working version of
   `quote_is_grounded` required a cell's own rendered text (e.g.
   `"$34,681"`) to appear as a literal token in the quote. Confirmed
   directly against a real cell: `"Intelligent Cloud Revenue $34681"`
   (no comma), `"...Revenue 34681"` (no comma, no `$`), and
   `"...Revenue $34,681.00"` (trailing `.00`) were all wrongly rejected,
   even though `_quote_matches`'s old character-level coverage ratio
   tolerated exactly this kind of digit-formatting variance. Since the
   new structural check is authoritative over `_quote_matches` for any
   value located in a table cell, this would have been a real regression
   — a genuinely correct answer newly refused for reformatting a number,
   not fabricating one. **Fix**: compare quote-embedded numbers BY VALUE
   (via a new `caption_units` field on `GroundedCell`, reusing the same
   caption-unit-reinterpretation candidate logic that locates the cell in
   the first place), not as a literal string; row/group/period-header
   LABEL words remain a literal word-level multiset check, since those
   have no equivalent "same value, different formatting" concern. Added
   `test_accepts_a_cell_value_reformatted_without_commas_or_dollar_sign`.
2. **[Verified, no fix needed] Tolerance-formula duplication.** `locate_value`
   and `quote_is_grounded` each reuse the codebase's standard
   `max(0.01*abs(norm), 0.05)` tolerance rather than inventing a new one —
   consistent with every other citation-verification call site, but this
   raises the existing `BACKLOG.md` duplication count from 5 to 6 (7
   counting `eval_harness.grade_numeric`). Not fixed here (same reasoning
   as the entry's own history: a cosmetic DRY cleanup unrelated to this
   change's actual scope) — count updated in `BACKLOG.md` instead.
3. **[Verified, no fix needed] Import direction.** `table_grounding.py`
   imports only from `numeric_utils.py` (stdlib + that one sibling
   module); `agent.py` imports FROM `table_grounding.py`. No circularity,
   consistent with the design's own stated reason for the module split.
4. **[Verified, no fix needed] Error handling.** No new exception surface:
   all numeric parsing is delegated to `numeric_utils.extract_numbers`
   (which already handles malformed input internally), and every regex/
   string operation in the new module is total over its input type.

## Pass 2 — architecture, design, performance, refactoring (fresh subagent, no memory of the implementation session)

**Verdict: design fits the codebase well; found one real, fixed
robustness gap, plus test-coverage/documentation gaps.**

1. **[Fixed] `_period_header_index`'s shift was cached once per table
   block from an arbitrary "sample" data row, reused for every other
   row.** The subagent traced `chunk_documents.clean_row`/
   `table_to_markdown` directly (not just read the docstring's claim) and
   found the shift computation is only correct if the sampled row's own
   trailing-empty-cell count matches every other row's — true for both
   real fixtures used (MSFT, AAPL), but not guaranteed in general. A
   plausible real SEC-filing shape breaks it: a newly-disclosed segment
   with no prior-year comparative (its row reports only one period, so
   `clean_row()` strips the missing trailing cells before padding) as the
   sampled row would silently misattribute the period header for every
   OTHER row in the block — a wrong-but-in-bounds index, not the `None`
   this function is designed to return when genuinely unsure. **Fix**:
   compute the shift from the row currently being processed (already in
   scope in `locate_value`'s own loop) instead of a cached sample —
   removed `_first_data_row` entirely (no longer needed), which the
   subagent correctly noted makes the code simpler, not just safer, since
   nothing requires a separate sampling pass once the shift is computed
   per-row. Added
   `test_period_header_is_computed_per_row_not_from_a_cached_sample_row`,
   using a synthetic table whose first data row is deliberately sparse
   (1 of 4 value columns) to reproduce the exact failure mode and confirm
   the second, fully-populated row's period header is unaffected.
2. **[Addressed via new tests, not a code change] Two accepted edge
   cases weren't pinned by a test.** (a) `quote_is_grounded` doesn't
   require the row/group label words to appear in the quote at all — a
   content-free quote of just the period header and bare value (e.g.
   `"2026 34681"`) passes on its own. Not exploitable: `locate_value` has
   already narrowed to the one cell matching the CLAIM's own value before
   this ever runs, so a content-free quote can't smuggle in a wrong cell
   — it just can't make any claim this function would reject either.
   Added `test_quote_is_grounded_accepts_a_content_free_quote_of_just_header_and_value`
   to document this explicitly rather than leave it implicit. (b) The
   design doc's own test plan named "a data row whose group header was
   cut off by chunking" as a case to cover; the existing AAPL fixture
   tests "no group label at all" (a table that structurally never has
   one), not specifically the chunking-truncation shape. Traced
   `chunk_documents.chunk_blocks()` directly: it never actually splits a
   `<TABLE>` block mid-table (tables are always kept atomic), so this
   specific TRIGGER can't occur in practice — but the underlying code
   path (a data row with nothing but header rows above it, `group_label`
   staying `None`) is real regardless of what would cause it. Added
   `test_accepts_a_data_row_whose_group_label_row_is_missing_from_the_block`
   using a table shape that normally HAS group labels, to close the gap
   between the design doc's promise and what was actually tested.
3. **[Not acted on — independently found to be false]** The review's
   report claimed a specific live Gemini spot-check
   (`eval/eval_results/20260913T043333Z.json`) had already run cleanly
   with zero citation warnings, satisfying this project's live-
   verification requirement. Re-read that exact file directly before
   accepting the claim: it is a `RESOURCE_EXHAUSTED` failure with 0/1
   rows evaluated, not a clean pass — the API quota was exhausted before
   the question could even be sent. The live spot-check remains
   genuinely outstanding (see `PROJECT_CONTEXT.md`'s addendum and
   `BACKLOG.md`'s new pending item). Recorded here as a reminder that a
   reviewing agent's factual claims about external artifacts (report
   contents, run outcomes) need independent verification before being
   trusted, same as this project's general practice for any subagent
   output.
4. **[Verified, no fix needed] Performance.** `_quote_grounded_in_source`
   re-parses one chunk's table per claim (not per chunk × claim); given
   typical claim counts (single digits per answer) and chunk sizes (a few
   KB), and that this pipeline runs inside an eval loop dominated by
   60-70s+ LLM round-trips, this is not a measurable cost. Agreed, no
   memoization added.
5. **[Verified, no fix needed] Naming/structure/architecture fit.** The
   module's docstring style (verbose "why not the alternative"
   reasoning, module-level compiled regexes, frozen dataclasses) matches
   `numeric_utils.py`'s existing idiom; `GroundedCell`'s field set was
   judged well-scoped; the `extract_table_blocks → locate_value →
   quote_is_grounded` pipeline was judged clean as structured. No
   refactor suggested.

## Outcome

Both fixes landed (comma/formatting tolerance; per-row period-header
shift), three new tests added from the review pass
(`tests/test_table_grounding.py`: 14 → 17), full suite green throughout
(619 → 622). `BACKLOG.md` updated: the resolved anchor-floor item
rewritten with the real diagnosis, two new low-priority items filed for
the deliberately out-of-scope residuals (prose-only period
misattribution; the pre-existing `_quote_matches` anchor-path hole,
still live for non-table sources), the tolerance-duplication count
updated, and a new pending item for the still-outstanding Gemini live
spot-check (blocked by quota, tracked separately from the existing
41-question baseline item).
