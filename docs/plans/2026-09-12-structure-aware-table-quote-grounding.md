# Structure-aware table quote grounding

## Context

`BACKLOG.md:73` tracks a `[bug, Med, Standard]` false positive in
`_quote_matches`'s 30-char contiguous-anchor floor, diagnosed live on
`msft-three-segments-revenue-q3fy2026`. The entry proposes "a scale-aware
anchor floor (e.g. proportional to quote length)".

**Investigation on 2026-09-12 showed that framing is wrong, and the item
needs re-scoping from Standard to Substantial.** Measured evidence, all
against the real chunk
`chunks/MSFT/0001193125-26-191507_chunks.jsonl`:

1. **The reported false negative.** The model quotes
   `"Intelligent Cloud\nRevenue $34,681"` — faithful to the source. The
   segment name is a label-only table row with empty cells, so after
   normalization `| | | | | | ` sits between "cloud" and "revenue". The
   match splits into 3 blocks (18, 8, 7); coverage is 1.000 but `longest`
   is 18 < 30. Rejected. Whether a claim passes depends only on **label
   length**: `Productivity and Business Processes` (36) passes,
   `Intelligent Cloud` (18) and `More Personal Computing` (24) fail.

2. **Threshold/character-class tuning cannot fix it.** A gap-content
   locality rule (accept a split match when gaps hold only table
   punctuation) passes the real case and 6 fabrication attacks, then
   fails on row splicing: `|\n|` and `| |` normalize to the *same*
   string, so a quote can jump rows. Verified end-to-end through
   `_verify_one_claim`:
   `quote="$50,780 Intelligent Cloud Revenue $34,681"` →
   today `CitationWarning(quote_not_found)`, patched `None` (accepted).
   `$50,780` is Productivity & Business Processes' nine-month FY2025
   operating income. The row/cell information needed to catch this is
   destroyed by `_normalize_for_match` before the check runs.

3. **The anchor floor is not protecting what it appears to.** These pass
   **today**, unmodified, because the 36-char label alone clears the
   anchor and coverage's 10% slack absorbs an inserted digit:
   - `2025 Productivity and Business Processes Revenue $35,013` (FY2026 value)
   - `Productivity and Business Processes Revenue $135,013` (10× overstatement)
   - `Productivity and Business Processes Revenue $102,149` (nine-month as quarter)

4. **A locality fix would be under-inclusive by 3/4.** It only reaches
   the row adjacent to the label. `Cost of revenue` (15),
   `Operating expenses` (18), `Operating income` (16) are all under 30
   chars, so segment-level cost/expense/income quotes keep refusing under
   every variant tested.

Root cause: a flat-text similarity metric is being asked to verify a
**structured** claim. Verifying a table value needs three coordinates —
row-group, metric row, column — and string comparison carries none.

**Outcome intended**: table-bearing sources get verified against table
structure, fixing the false negatives across all metric rows and closing
the row-splice and digit-insert holes by construction.

## Decisions already taken

- **Authoritative for table sources.** If the claimed value is located in
  a parsed grid cell, the structural verdict decides; the fuzzy anchor
  path may not rescue it.
- **The anchor path stays for prose.** It is the only fuzzy route for
  non-table chunks and 6 of the 8 existing `_quote_matches` tests depend
  on it. What is removed is its ability to override a structural
  rejection on a table source.

## Approach

### Key simplification

A full-row verbatim quote (`| Revenue | $34,681 | $26,751 | ... |`) is an
**exact substring** of the source, so it returns `True` on
`_quote_matches`'s existing fast path before any new code runs. The
structural path therefore only ever sees quotes that are *not* exact
substrings — reformatted or spliced ones. This means the allowed-context
set can be tight (own cell only, not the whole row) without breaking the
common legitimate case.

### New module: `table_grounding.py`

`agent.py` is already 2372 lines; this parses and reasons about table
structure and is independently testable, so it goes in its own module —
the same reasoning that produced `numeric_utils.py` (see its module
docstring). Reuse `numeric_utils.normalize` and the existing
`max(0.01*abs(norm), 0.05)` tolerance for all value comparison; do not
re-derive either.

Parse from the **chunk text at runtime** (`all_results[n-1]["text"]`),
which already contains the pipe-table rows spliced in by
`reconstruct_document`. No need to reach back to `data/*_tables.json`.

1. `extract_table_blocks(text)` — consecutive lines matching
   `^\s*\|.*\|\s*$` form a block; split each on `|`, strip cells, drop
   separator rows (all cells `---`/empty).
2. Classify rows: **label-only** (exactly one non-empty, non-numeric cell
   → a group header like `Intelligent Cloud`); **data** (non-numeric
   first cell + ≥1 numeric cell); **header** (period/year cells).
3. `locate_value(blocks, value, unit)` → every cell whose number matches
   the claimed value within tolerance, as `(block, row, col)`.
4. `quote_is_grounded(quote, cell)` — build the cell's allowed context:
   its own cell text, its row's label cell, the nearest preceding
   label-only row above it, and **its own column's** header. Subtract all
   of those from the normalized quote; accept iff only punctuation and
   whitespace remain.

Deliberately excluded from the allowed set: other columns' values and
headers. That exclusion is what rejects
`2025 Productivity and Business Processes Revenue $35,013` (the "2025"
token belongs to column 2, not the value's column 1).

### Wiring into `_verify_one_claim` (`agent.py:1655`)

Replace the single `_quote_matches(quote, source_text)` call at
`agent.py:1686` with:

- Locate the claimed value in the source's table blocks.
- **No table, or value not found in any cell** → existing
  `_quote_matches` path unchanged (the value may legitimately be in
  prose, or the chunk may hold no table at all).
- **Value found in ≥1 cell** → accept iff some matching cell satisfies
  `quote_is_grounded`; otherwise emit the warning. No anchor fallback.

Keep the existing `CitationWarning(check="quote_not_found", ...)` shape
rather than adding a check name — `analyze_citation_gate.py` and several
tests key off the current taxonomy, and expanding it is out of scope.

### Chunk-boundary robustness

`chunk_blocks()` can split a table, so a chunk may hold a data row whose
group header row was cut away. When no label-only row precedes a matching
cell, treat the group label as *unknown* and do not require it — verify
against row label, column header and cell text only. Never refuse a claim
because the chunk lacks context the chunker removed.

## Files

- `table_grounding.py` — **new**; parsing + grounding logic above.
- `tests/test_table_grounding.py` — **new**; unit tests for the new module.
- [agent.py](agent.py) — `_verify_one_claim` (1655–1705) call-site swap;
  correct `_normalize_for_match`'s docstring (1208–1220), which claims
  NFKC folds en-dashes to `-`. It does not: measured, U+2014/U+2013/
  U+2010/U+2212 all pass through unchanged and only U+FF0D folds to ASCII
  `-`. `test_quote_matches_nfkc_curly_quote_and_en_dash_normalization`
  passes via coverage, not folding.
- [tests/test_agent.py](tests/test_agent.py) — new `_verify_one_claim`
  regression tests alongside the existing suite at line 3000.
- [BACKLOG.md](BACKLOG.md) — rewrite entry :73 with the real diagnosis;
  add new items for the two findings **not** fixed here (see below).
- [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) — changelog entry.
- `docs/plans/2026-09-12-structure-aware-table-quote-grounding.md` — copy
  of this plan (per CLAUDE.md step 1, before implementation starts).

## Tests (TDD — pure logic, so full red-green)

`table_grounding.py` is deterministic text processing with no network,
model or filesystem dependency, so it takes full TDD, not the live-only
carve-out. Write these first, confirm they fail for the right reason:

Accept:
1. The real bug, both short labels — `Intelligent Cloud` (18) and
   `More Personal Computing` (24) — so the label-length accident cannot
   silently return.
2. All four metric rows for one group: `Revenue`, `Cost of revenue`,
   `Operating expenses`, `Operating income`. This is the coverage a
   locality patch could not reach.
3. A data row whose group header was cut off by chunking.

Reject:
4. Row splice — `"$50,780 Intelligent Cloud Revenue $34,681"`, and the
   25-char `"$50,780 Intelligent Cloud"`.
5. Digit insertion — `"Intelligent Cloud Revenue $134,681"` (matches no
   cell) and inserted sign `"-$34,681"`.
6. Cross-group steal — `"Intelligent Cloud Revenue $35,013"`.
7. Adjacent prior-year column — `"Intelligent Cloud Revenue $26,751"`
   grounding a claim about the current quarter.
8. Wrong column header token — `"2025 Productivity and Business
   Processes Revenue $35,013"`.

Preserve:
9. All 8 existing `_quote_matches` tests unchanged — prose paraphrase,
   NFKC, autojunk regression, bare-XBRL-number, short-quote rejection.
10. Full suite green (currently 601).

## Verification

1. `python -m pytest` — full suite, plus the new module's tests.
2. Re-run the probe scripts in the scratchpad
   (`probe_candidate.py`, `probe_verify_review.py`,
   `probe_preexisting.py`) against the new implementation to confirm the
   attack matrix flips as intended and the three pre-existing
   misattributions in Context §3 are closed.
3. **Live spot-check** (CLAUDE.md requires this for any
   `_verify_one_claim` change):
   `eval_harness.py --backend gemini --ids msft-three-segments-revenue-q3fy2026`
   — must pass cleanly with zero citation warnings, on the modal path
   rather than via the Gemini retry.
4. **Full baseline** `eval_harness.py --backend gemini` (no `--ids`) once
   the daily quota resets — this is a broad change to shared
   verification code, and it simultaneously closes the in-progress
   `BACKLOG.md` item needing one clean 41-question run. Confirm no new
   false negatives on table-heavy questions.
5. Two-pass review per CLAUDE.md step 7, saved to
   `docs/reviews/2026-09-12-structure-aware-table-quote-grounding.md`.

## Known limitations to record, not fix

- **Wrong-column misattribution in prose.** A claim whose value is a real
  cell, quoted with no contradicting period token
  (`Productivity and Business Processes Revenue $102,149`, the nine-month
  figure described in prose as the quarter) stays accepted: the quote
  genuinely supports the value, and the error lives in the answer text.
  Closing it needs a `period` field on the claim schema to check against
  the column header. → new `BACKLOG.md` item.
- **Pre-existing long-label anchor hole on prose sources.** Unchanged
  where the value is not in a grid. → new `BACKLOG.md` item.
