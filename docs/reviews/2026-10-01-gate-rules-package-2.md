# Review: package 2, gate rules (D12a, D12b rule R, paren either-sign, `10-Qs`)

Plan: `docs/plans/2026-10-01-gate-rules-package-2.md`. Four commits (`c4f5d07`, `3793629`,
`9c72a4e`, `03e8087`) change the citation gate in critical core (`citations.py`,
`table_grounding.py`, `numeric_utils.py`). 1188 tests at `03e8087`. The diff classified as
Substantial, so every pass ran at full depth.

## Round 1

Passes: `/code-review` high, `arch-reviewer` (opus), `security-reviewer`, `/simplify` (four
cleanup agents). Diff `b6f0307..03e8087`; snapshot `HEAD`, since no code was uncommitted.

1. **High** (code-review, arch): `_looks_like_data` treats a row as data only when another
   cell holds a number. A dash-only data row (`Impairment | — | —`) sits below a real first-row
   group label, so the label gets promoted to table-wide header. Its text then enters a later
   group's permitted region. Reproduced with distinct labels: `| Cloud | | |` +
   `Revenue | $34,681` (a Gaming cell) grounded before the fix and is refused after it.
   `[Fixed]`: any dash value cell past column 0 counts as data. Pinned by
   `test_a_dash_only_data_row_keeps_the_first_row_a_label` (3 shapes).
2. **High** (code-review): `_span_covers_cell` accepted a span that ran past the cell's own
   governing label into a later group's label (`… Revenue | $34,681 | $300 | … | Gaming |`), so
   the value read as Gaming's. `[Fixed]`, final form in round 2.
3. **High** (code-review): the end check accepted a span stopping partway through a later row:
   keeping only `Nine Months` of a period header after a Q1 value, or ending on the next data
   row's label. `[Fixed]`: every row after the claimed one must be whole. Pinned by
   `test_rejects_a_span_that_ends_partway_into_a_later_row_or_a_foreign_label`.
4. **Medium** (code-review): `_looks_like_data` also flags a period row with a text first cell
   and year cells (`| Year Ended | 2026 | 2025 |`), so promotion is skipped there.
   `[Verified, no fix needed]`: it fails closed, the same behavior as before D12a, and no
   observed refusal has this shape.
5. **Low** (code-review, efficiency agent): `_block_text` is rebuilt for each matched cell.
   `[Verified, no fix needed]`: it runs only after `quote_is_grounded` fails, at under 1 ms per
   claim.
6. **Low** (code-review): `GroundedCell` stores position plus the precomputed region fields
   derived from it. `[Disputed]`: the plan keeps `quote_is_grounded` untouched, and it reads the
   precomputed fields, while R needs the position. Both are filled once in `locate_value`.
7. **Nit** (code-review, arch): the `_is_negative` docstring named the old loop; the
   `_quote_grounded_in_source` docstring held two `docs/decisions` pointers; `extract_numbers`
   went through two wrappers. `[Fixed]`, all three.
8. **Nit** (arch): the decision file linked this review before it existed, and the plan's rule-5
   deviation wasn't recorded. `[Fixed]`: this file, and the plan's Addendum.
9. **Security**: no issues. Tried: splices across rows and blocks, truncated numbers, sign
   bypass of the either-sign exemption, regex DoS in `10-[KQ]s?`.
10. **`/simplify`**:
    - The reuse pass found nothing.
    - Applied: the `_looks_like_data` one-liner.
    - Skipped, with reasons:
      - `takewhile` rewrite and `text_end` arithmetic: style only.
      - Deriving `group_label_row_index`: it's filled once, in the same loop as the label.
      - Moving the dash rule into `_classify_row`: it changes behavior across the corpus.
      - A region-based alternative to R: the plan chose R.
      - One OR entry point: there's one caller.
      - The paren flag from `_is_negative`: it's read from the final sign, so it can't drift.
      - Trimming the `verify_claims` docstring: the plan requires it to state the cost.

Found while testing finding 1, and outside this diff: `quote_is_grounded` accepts a foreign
label that differs by one letter (`Segment A` over a Segment B cell). `[Deferred → BACKLOG]`
as a latent Watch item.

## Round 2

Delta: `git diff HEAD`. Passes: `/code-review` low, `arch-reviewer` (opus), `security-reviewer`.

1. **Medium** (arch): the round-1 label fix refused *every* label row but the governing one,
   including an earlier group's label above it. That is stricter than plan rule 5 and the
   research note, and it would refuse a whole multi-group table quoted verbatim, a shape the
   model really produces (run `a70784aa9376`). `[Fixed]`: the last label row in the span must
   be the cell's governing label. Pinned by
   `test_accepts_a_span_with_an_earlier_group_above_the_cells_own_label` and
   `test_rejects_the_same_span_for_a_cell_above_a_later_groups_label`.
2. **Risk** (arch): the plan's Addendum still described the old guard and scan counts.
   `[Fixed]`: new Addendum entry, re-scan 278 promoted, 13 residual.
3. **Nit** (arch): a test-file path pointer left in the `_quote_grounded_in_source` docstring;
   "em-dash" where the pattern takes any dash. `[Fixed]`.
4. **Low** (code-review): `cells[0]` on an empty row. `[Verified, no fix needed]`: `_split_row`
   uses `str.split`, which always returns at least one cell.
5. **Security**: no issues.

## Round 3

Delta: the narrowed label rule in `_span_covers_cell` and its two tests. Passes: `/code-review`
low, `arch-reviewer` (opus), `security-reviewer`.

- Arch and security: no issues. Both checked that `group_label_row_index` is the last label
  before the cell's row, so `labels[-1] == governing` holds exactly when no label in the span
  follows the cell's row. They also checked that an ungoverned cell refuses any label.
- Code-review low repeated round 2's `cells[0]` point, already dispositioned. It also asked
  whether an unlabelled dash row should count as data. It should, and a test pins it. The
  docstring now says so, a wording-only nit.

## Live verification

- **Corpus scan** (D12a, 1,338 table blocks): 278 first rows promoted, 243 of them in blocks
  with data rows. 13 residual value-like cherry-pick token sets, all percent-header text or
  cover pages. Every promoted first row in a block with later labels is a period or table
  title.
- **Offline replay**: `analyze_gate_replay --compare` against a `b6f0307` baseline, 628 runs
  since 2026-09-19. Identical at `03e8087` and after the round-1 fixes:
  - refused 50 → 46;
  - 4 recovered, all nvda-segment-revenue-comparison-q1fy27 (`64769e1d98af`,
    `a8eb95071453`, `8dab6760e457`, and the 2026-10-01 loss `607e58e8f7f0`);
  - 0 newly refused;
  - 1 check change: `8ff8fba364d8` loses `uncovered_number` `10` through the `10-Qs` strip and
    stays refused on a qualitative quote;
  - 0 tool drift; 18 drifted runs, none changing verdict.
  The final label rule lies between the two replayed rules, so its outcome is the same.
- **First-submit re-gate** (the replay checks final submits only): 9 of the 10 targeted
  warnings since package 1 clear:
  - paren ×6;
  - D12 `607e58e8f7f0`;
  - `10-Qs` `6b208b525a77`.
  Two nvda-segment runs still warn. `8af160058051` stripped the table's pipes, and
  `c90ca4178f4c` cited a different table's chunk. Both are correctly outside R.
- **Live spot-check** (Gemini, `03e8087`; reports `20261002T044529Z`, `044632Z`, `044737Z`):
  6 of 8 passed, with 0 refusals. The one citation retry (`a70784aa9376`) correctly rejected a
  whole-table quote cited to the wrong source. The two failures fall outside the gate: an
  nvda-segment judge "fabricated figures" flake on correct, warning-free figures, and a
  msft-segment retrieval miss. The review fixes only tighten R or widen the D12a guard, so
  they're re-verified offline rather than live.

## Outcome

Shipped: D12a with the widened data-row guard, rule R with whole-later-rows and last-label
checks, paren either-sign coverage, and the `10-Qs` strip. 1197 tests; ruff and pyright clean;
diff coverage on the critical core 98%. Three rounds; the review closed clean, with no
escalation. Open in `BACKLOG.md`:
- the D3/D4 deferral `[feature, Low, Standard]`;
- the `74.9` percentage-cell collision `[bug (latent), Low, Standard]`;
- the single-letter label tolerance `[bug (latent), Low, Standard]`;
- the `header_context` inflation item, with its trigger unchanged.

This replay also serves as package 2's refusal re-mine before package 5.
