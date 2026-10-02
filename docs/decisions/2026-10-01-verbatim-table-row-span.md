# Accept a verbatim, position-anchored multi-row table quote

**Date:** 2026-10-01

## Context

The citation gate rejected a word-for-word quote spanning two table rows. In the 2026-10-01 full
run (`20261001T193130Z`), nvda-segment-revenue-comparison-q1fy27 quoted the `Compute & Networking`
and `Graphics` rows of NVDA 10-Q `0001045810-26-000052` chunk 34. Each row alone grounded, but the
two-row text failed `quote_is_grounded`. The retry resubmitted the same quote and the run was
refused. The post-package-1 re-mine counted 3 more retries with the same cause.

Two separate defects were involved:

- **D12a.** That table is transposed: its first row `| Three Months Ended | | | | |` lost its
  colspan. `_classify_row` read it as a group label, so the `Apr 26, 2026 | …` and
  `($ in millions)` rows below it never entered any cell's permitted region.
- **D12b.** A cell's permitted region is the header context, its governing label and its own
  row. A quote that runs across a sibling row covers more than that region, so coverage fails
  even when the text is verbatim.

On 2026-09-13, an unconditional "exact substring of the whole source wins" shortcut was tried for
this same question and reverted before landing, because it reopened the row-splice attack that
region-scoped matching exists to block. This decision revisits that revert. What changed is the
2026-09-28 research note: it defined a narrower rule, R, that anchors the quote by position
instead of by text presence, and prototyped it against the splice cases.

## Decision

- **D12a** (`c4f5d07`): in `extract_table_blocks`, the block's first content row is promoted
  from `label` to `header` when the next row is a `header` and no row in the context it would
  open looks like data: a text label with a number, or any dash value cell.
- **D12b** (`3793629`): `GroundedCell` records its block, row and column. The new
  `verbatim_row_span_grounded(quote, cell)` is OR-ed with `quote_is_grounded` per cell in
  `citations._quote_grounded_in_source`. It accepts when the normalized quote occurs in the
  cell's own block, starts at a row boundary, ends at a cell boundary, and covers the claimed
  row from its first cell through the claimed cell. Any row after the claimed one must be whole,
  and if the span contains any label row, the last one must be the cell's governing label.
- Two smaller coverage-pass fixes from the same re-mine ship alongside and are recorded in their
  commit bodies:
  - `9c72a4e`: a parenthesized answer number is covered by either sign (6 retries).
  - `03e8087`: `10-Qs`/`10-Ks` are stripped as non-claims (1 retry).

## Why

- **Text presence alone is unsafe; position is what makes R safe.** `normalize_for_match`
  collapses a row break and an empty cell to the same text, so the 09-13 raw-slice splice is a
  "substring" of the source. R maps the quote back to row and cell offsets, which rejects a
  splice that starts mid-row, ends inside a number, or borrows a foreign group label.
- **The first-row-only D12a rule was narrowed twice.**
  - The plan's first draft promoted any label before the first data row. The plan review showed
    that reopens the AAPL `0000320193-25-000073` chunk 9 `Level 1:` wrong-group splice.
  - The corpus scan then showed the first-row rule could pull em-dash data rows into the header
    context. The data-row guard closes that, and the code review widened it to dash-only rows.
- **R's end and label rules were tightened in review.** Ending partway through a later row kept
  a single period label, and running on into a later group's label read the value as that
  group's. A foreign label *above* the governing one stays allowed, so a whole multi-group table
  quoted verbatim still grounds for its last group.
- **D3 and D4/D11 were deferred, not adopted.** Both loosen the gate, and none of the 17
  re-mined retries needed either one.

## Files touched

- `src/sec_agent/verification/table_grounding.py`
- `src/sec_agent/agent/citations.py`
- `src/sec_agent/verification/numeric_utils.py`
- `tests/verification/test_table_grounding.py`, `tests/agent/test_citations.py`,
  `tests/verification/test_numeric_utils.py`

## Verification

- **Tests:** 1197 pass after the review fixes; ruff and pyright are clean; diff coverage on the
  critical core is 98%. The new tests use real-corpus
  fixtures (NVDA chunk 34, AAPL chunk 9, MSFT chunk 16) and cover the research note's accept and
  reject list, including the 09-13 splice cases S3–S6 and H2.
- **Corpus scan (D12a):** 278 blocks are promoted. Every promoted first row is a period or table
  title, never a sibling of the labels below it.
- **Offline replay** (`analyze_gate_replay --compare` against a baseline on `b6f0307` code, 628
  runs since 2026-09-19; the same at `03e8087` and after the review fixes):
  - refused 50 → 46: 4 recovered, all nvda-segment-revenue-comparison-q1fy27 multi-row quotes,
    including the 2026-10-01 loss `607e58e8f7f0`;
  - 0 newly refused;
  - 1 check change: the `10-Qs` strip drops an uncovered `10` in a run still refused for an
    unrelated qualitative quote.
- **First-submit re-gate** (the replay checks final submits only): 9 of the 10 targeted
  first-attempt warnings since package 1 clear. The 2 nvda-segment runs that still warn quoted
  the table with its pipes stripped, or quoted a different table than the cited source. Both
  are outside rule R by design.
- **Live spot-check** (Gemini, `03e8087`, 8 runs):
  - 6 of 8 passed (reports `20261002T044529Z`, `044632Z`, `044737Z`), with 0 refusals and 1 citation retry, which correctly rejected a
    whole-table quote cited to the wrong source.
  - Two runs failed for reasons outside the gate:
    - one nvda-segment repeat was a judge "fabricated figures" flake, with no citation warnings;
    - msft-segment was a retrieval miss.

## Related

- Revisits the reverted shortcut in `docs/decisions/2026-09-13-table-grounding-region-scoped-matching.md`.
- Rule R and its test list: `docs/research/2026-09-28-table-quote-grounding.md`.
- Plan: `docs/plans/2026-10-01-gate-rules-package-2.md`. Review:
  `docs/reviews/2026-10-01-gate-rules-package-2.md`.
- The loss run's retry path: `docs/decisions/2026-09-30-citation-retry-own-slot.md`.
