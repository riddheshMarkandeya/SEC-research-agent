# Fix orphaned-table-fragment chunking bug found in the 44/47 baseline

## Context

The 44/47 full eval baseline (`eval/eval_results/20260917T213518Z.json`,
following the same-day judge hypothetical-date fix) had one remaining
numeric-type failure: `nvda-inventory-turnover-fy2026`. Live
reproduction traced the root cause to `chunk_documents.py`'s
`chunk_blocks()`, not to the citation-verification code that surfaced
it. `chunk_blocks()` carries a 200-char (`OVERLAP_CHARS`) raw-character
slice of the just-flushed chunk forward as "overlap" context for the
next chunk. When that slice lands inside a `<TABLE>...</TABLE>` block
(past its own open tag), the carried-forward fragment contains an
orphaned `</TABLE>` with no matching `<TABLE>` — invisible to
`table_grounding.py`'s paired-tag regex (`extract_table_blocks()`).
Reproduced live against NVIDIA's real FY2026 10-K: the "Total
inventories = $21,403 million" row became invisible in its own chunk,
and `locate_value()` instead matched a different, coincidentally close
real cell ("Total accrued and other current liabilities = $21,352M",
0.24% off, within `locate_value`'s 1% tolerance) — causing a correct
answer to be citation-gate-refused. This can recur for any table whose
markdown crosses within 200 chars of a 2000-char (`TARGET_CHUNK_CHARS`)
chunk boundary, across the whole indexed corpus.

Two other baseline failures (`pltr-dividend-2019-refusal`,
`nvda-rd-expense-q4fy26-refusal`) were investigated in parallel and
assessed as judge over-strictness rather than a real agent gap — both
answers satisfy their question's own written grading criteria, and a
structurally identical passing question uses the same unforced phrasing
in the same run. No code change was made for these two.

## Decision / Design

In `chunk_blocks()`, before keeping the raw-sliced overlap tail, check
whether it contains more `</TABLE>` than `<TABLE>` occurrences — the
only way a slice of `current` (which only ever holds complete atomic
blocks) can be unbalanced. If so, keep only what follows the orphaned
close tag rather than dropping the whole tail or carrying the corrupt
fragment forward.

A first draft used `tail.rfind("</TABLE>")` (last occurrence). An
independent code-review pass (two finder agents, converging
independently) found this over-strips: when a fully self-contained
second table also falls within the same tail (after the true orphan),
`rfind` lands on that second table's own valid close tag and discards
it too. The corrected version uses `tail.find("</TABLE>")` (first
occurrence) instead, backed by a proof that there is always at most one
orphaned close tag per tail, and it is always the first `</TABLE>`
substring in it — tables never nest or overlap, so any table fully
contained in the tail must open only after the orphan's table has
already closed. `find` therefore strips exactly the orphan and nothing
else.

## Files and steps

1. Add two failing regression tests to `tests/test_chunk_documents.py`
   reproducing the single-table orphan case (both the pure-drop and the
   trailing-prose-preserved sub-cases) — confirmed red against the
   pre-fix code.
2. Implement the fix in `chunk_blocks()` + extend its existing
   docstring (which already documents the related
   `current_is_only_overlap` invariant in the same self-contained
   style).
3. Confirm all 6 pre-existing `chunk_blocks` tests pass unchanged
   (traced by hand against the new branch before implementing).
4. Independent plan review (before implementation) and code review
   (after) — see the paired review file.
5. Re-run `chunk_documents.py` against the existing `./data` (no need
   to re-run `edgar_ingest.py`) and `index_chunks.py` to rebuild the
   Chroma store from the corrected chunks.
6. Add `chunk_documents.py` to both `.claude/rules/live-eval-
   verification.md` and `.claude/rules/plan-review-blast-radius.md` —
   corpus-wide code that every live citation-grounding check reads
   from, per the same reasoning already applied to `retrieval.py`/
   `numeric_utils.py`.

## Testing and verification

`chunk_blocks()` is pure/deterministic (no I/O), so full red-green TDD
applies directly — not the live-code manual-repro-script carve-out.
Beyond unit tests, `.claude/rules/live-eval-verification.md` requires a
live spot-check for any `chunk_documents.py` change (a corpus-wide
reshape, not visible to unit tests alone): a direct real-data
inspection of the previously-orphaned NVDA chunk, a full-corpus scan
for any remaining unbalanced-tag chunk, and a live eval re-run of the
target question. See the paired review file for what each of these
actually found.

## Addendum

Execution deviated from this plan in two ways, both recorded in full in
the paired review and decision files rather than rewritten here:

1. The code-review pass (step 4) found the `rfind`-vs-`find` bug above
   after the corpus had already been rebuilt once with the `rfind`
   version — the corpus was rebuilt a second time with the corrected
   fix, and a third regression test was added proving the corrected
   behavior (a fully self-contained second table in the same tail
   survives the fix).
2. The full 47-question Gemini baseline re-run planned as final
   confirmation hit Gemini's free-tier daily quota (already exhausted
   by six earlier baseline runs the same day, before this task even
   started) — the run is invalid per `.claude/rules/live-eval-
   verification.md`'s own existing guidance and was not used for any
   before/after comparison. A targeted retry and an Ollama-backend
   substitute spot-check were both tried; neither produced a valid
   Gemini confirmation (Ollama failed the target question for an
   unrelated, pre-existing reason — see the review file). The full
   baseline re-run is deferred to a follow-up once quota resets.
