# Package 2: gate rules (D12 verbatim table row span, paren-gloss coverage, 10-Qs strip)

Date: 2026-10-01. Tier: **Substantial**. It changes the citation gate (critical core: `agent/citations.py`,
`verification/table_grounding.py`, `verification/numeric_utils.py`) and revisits a recorded
decision. The work is code-only: no model-visible text changes, so the prompt fingerprint stays
the same and no panel run is needed. The final check follows the map's "code-only gate change"
row: an offline replay plus a targeted live spot-check.

## Context

Package 2 of `docs/plans/2026-09-28-agent-improvement-map.md` was "gate D4/D11, D3, then D12 a
and b". Gate D9 said to re-decide those items after package 1's refusal re-mine. The re-mine
covered the panel ×3 (`20260930T205234Z`, `205532Z`, `205927Z`) and the full run
`20261001T193130Z`. Those runs fired 17 citation retries and 1 final refusal:

| Cause | Retries | Questions |
|---|---|---|
| Parenthetical gloss `"$44.06 billion ($44,062,000,000)"`: the restatement parses as an accounting negative, so `uncovered_number` fires | 6 | aapl-msft-total-assets-comparison ×3, nvda-revenue-two-quarter-comparison ×2, aapl-cash-equivalents-q3fy2026 |
| Multi-row verbatim table quote rejected (D12) | 3, **plus the one loss** | nvda-segment-revenue-comparison-q1fy27 |
| `"Form 10-Qs"` (plural) isn't stripped by `_NON_CLAIM_PATTERN`, so a bare `10` is uncovered | 1 | nvda-rd-expense-q4fy26-refusal |
| Other (`quote_too_short`, `quote_not_found` on thousands, `[26]`, sign or omitted claims) | 7 | not gate false positives under any candidate rule |

D3 (a verified quote covers its numbers) and D4/D11 (placeholder values become qualitative)
match none of the 17. Both loosen the gate.

**User decisions (2026-10-01):**
- Scope: D12a, D12b, the paren-gloss fix and the 10-Qs fix. D3 and D4/D11 move to the BACKLOG
  Watch list. Trigger: a re-mine shows a placeholder or quote-number refusal again.
- D12 approved as the research note's rule R. This revisits the 2026-09-13 revert of the "exact
  substring" shortcut.
- Paren fix: **either sign**, in the coverage pass only.
- Commit the pending map/harness-plan doc edits first, as their own commit.

## Decision / Design

Rule R from `docs/research/2026-09-28-table-quote-grounding.md` for D12b, the first-row-only header reclassification for D12a, and either-sign coverage for paren-wrapped answer numbers. Details per step below.

## Scope / Out of scope

Out: D3 (verified quote covers its numbers) and D4/D11 (placeholder claim values as qualitative), deferred to the BACKLOG Watch list by the user on 2026-10-01 because none of the 17 post-package-1 retries matches them. Out: the 1% tolerance policy (G2) and the eval grader's own number parsing.

## Files and steps


### 0. Housekeeping
- Commit the pending edits to `docs/plans/2026-09-28-agent-improvement-map.md` and
  `docs/plans/2026-09-30-retrieval-gold-rank-harness.md` as a docs commit.
- Copy this plan to `docs/plans/2026-10-01-gate-rules-package-2.md`, from the
  `docs/plans/TEMPLATE.md` shape, with its `PROJECT_INDEX.md` line.
- Baseline replay on master: `python -m sec_agent.devtools.analyze_gate_replay --out
  <scratchpad>/base.json` (about 18 minutes, so run it in the background while step 1 is built).

### 1. D12a: header-row classification (`table_grounding.py`)
- Problem: `_classify_row` reads NVDA chunk 34's leading `| Three Months Ended | | | | |` as a
  group label (`0001045810-26-000052`). `_leading_header_context` stops there, so the
  `Apr 26, 2026 | …` and `($ in millions)` rows never enter any permitted region.
- Rule: **only the block's first non-blank, non-separator row** is reclassified from `label` to
  `header`, and only when the next such row is a `header` row. A single cell followed by more
  header rows is a period header that lost its colspan.
  - Why only the first row: a broader rule ("any label before the first data row") reclassifies
    612 rows across the corpus. Any row with an em-dash cell classifies as `header`, so the
    first `data` row often comes deep into the body. That broad rule reopens a wrong-group
    splice: AAPL `0000320193-25-000073` chunk 9, where `Level 1:` becomes table-wide context
    and the quote `"Level 1: U.S. Treasury securities | 15,775"` (a `Level 2(1):` value)
    passes. The first-row rule gives 338 cases. The reviewer's simulation rejected the splice
    again under it and found no harmful hits (PLTR chunk 237 and NVDA chunk 25 are benign).
  - It goes in a block-level pass in `extract_table_blocks`, since `_classify_row` sees one row
    at a time. `_classify_row` stays pure.
- **Side effects to check:**
  - NVDA chunk 34's `Apr 26, 2026 | Apr 27, 2025 | …` row joins `multi_cell_context_tokens`, so
    a quote that names one period alone is rejected as a cherry-pick. That's by design.
  - Elsewhere the wider leading context can pull in a real data row that is misclassified as
    `header` because of em-dash cells. Example: AAPL chunk 9's `Cash | $26,686 | $— …`. Its
    tokens then join the cherry-pick sets, so any quote containing "Cash" fails (fail-closed,
    but a flip).
  - It also widens the region behind the latent coverage-inflation Watch item (BACKLOG, the
    `header_context` line).
- **Corpus scan** (scratch script, offline; record its output in the review file): over
  `var/chunks/*/*.jsonl`, for every block the rule changes, list the reclassified row and the
  leading-context size and cherry-pick token sets before and after. Gate step 1 on two things:
  the AAPL chunk 9 and MSFT `0001193125-26-191507` chunk 16 cases behave as in the tests below,
  and no reclassified row is a real group label over data.
- Tests (`tests/verification/test_table_grounding.py`, red first):
  - Add the fixture `NVDA_SEGMENT_TRANSPOSED_CHUNK`, verbatim from chunk_index 34. Its `$74,550`
    cell has `group_label=None`, and the permitted region includes the period row and the
    `($ in millions)` row.
  - Add the real negative fixture AAPL chunk 9. `Level 1:` stays a label, and the splice quote
    above is rejected. (No existing fixture starts with a group label, so this guard is new.)
  - Add the real negative fixture MSFT chunk 16. `Changes in Fair Value Recorded in Net Income`
    stays the group label of `Total equity investments`.
  - Every existing test passes unchanged.

### 2. D12b: position-anchored verbatim span (`table_grounding.py`)
- `GroundedCell` gains its position: a block reference (or block index) plus row and column
  indexes. `locate_value` fills them in.
- New public helper `verbatim_row_span_grounded(quote, cell)` in `table_grounding.py`. It is
  OR-ed per cell in `citations._quote_grounded_in_source`:
  `any(quote_is_grounded(q, c) or verbatim_row_span_grounded(q, c) for c in cells)`.
  `quote_is_grounded` stays untouched. The helper accepts when **all** of these hold:
  1. `normalize_for_match(quote)`, with outer spaces stripped, occurs in the cell's own block,
     normalized row by row and joined with single spaces, with row and cell offsets recorded.
     Every occurrence is tried.
  2. The occurrence starts at a row boundary: the row's leading `|`, or its first cell's text.
  3. It ends at a cell boundary: just after a cell's text, or just after the pipe that follows.
  4. It covers the claimed row from its first cell through the claimed cell.
  5. If the cell has a governing group label and the span contains any label row, the span
     includes that governing label row.
- The downstream `value_not_in_quote` check is unchanged and still runs.
- Tests: the research note's full list (`docs/research/2026-09-28-table-quote-grounding.md`,
  "Tests to add"):
  - accept N1–N3, N4 (the real traced 2-row quote, which is also the 2026-10-01 loss), N8, and
    MSFT A1/A2;
  - reject S3, S4, S5, S6, H2, N6 and N7, plus the two-block case;
  - every existing test passes unchanged.
- Reuse: `normalize_for_match` and `_split_row`. The prototype was scratch-only, so it's
  rebuilt here test-first.

### 3. Paren-gloss coverage (`numeric_utils.py`, `citations.py`)
- Problem: `verify_claims` strips brackets and non-claims, then `extract_numbers`. A
  paren-wrapped `($44,062,000,000)` comes out as −44,062,000,000, and no claim covers it.
  Reproduced offline on runs `44723e36b383` and `bbba6355c0de`.
- Change: a new sibling function in `numeric_utils` (for example `extract_numbers_with_paren_flag`)
  reports, per number, whether its negative sign came **only** from accounting parentheses. It
  shares the loop with `extract_numbers_with_spans` through a private helper.
  `extract_numbers_with_spans` keeps its 4-tuple shape, which tests assert exactly. In
  `verify_claims`' coverage
  loop, such a number counts as covered if its value **or its absolute value** is covered (by a
  claim, the question or a calculate operand).
  - Hyphen and minus-sign negatives stay strict.
  - Sources, claim quotes, `_number_candidates` and the eval grader are unchanged.
- Accepted cost (user-approved): an answer writing `($5) million` for a loss passes with a +5
  claim. Note it in the `verify_claims` docstring, next to the existing exemptions.
- Tests:
  - `test_numeric_utils.py`:
    - the paren flag is true for `($1,234)` and for a bare `(1)` (today's reference-marker
      carve-out needs a preceding letter);
    - it is false for `-1,234`, `(2024)` and `Registrant (1)`.
  - `tests/agent/test_citations.py`: the real gloss answer from `44723e36b383` passes, a
    hyphen-negative uncovered number still warns, and a paren number whose absolute value isn't
    claimed still warns.

### 4. `10-Qs` non-claim strip (`citations.py`)
- `_NON_CLAIM_PATTERN`: change `\b10-[KQ]\b` to `\b10-[KQ]s?\b`. It's shared with
  `_iter_citation_claims` (the eval grader's path), and that's intended.
- Test: the answer text `"standalone Form 10-Qs."` yields no uncovered number.

### 5. Docs (one commit)
- A decision file `docs/decisions/2026-10-01-verbatim-table-row-span.md`, for D12. It revisits
  the 09-13 revert and so passes the ADR gate. Under `Related`, it links the 09-13 decisions and
  the research note.
- Paren and 10-Qs: commit bodies only.
- A review file in `docs/reviews/` (Substantial).
- `PROJECT_INDEX.md` lines.
- Map: package 2 done, D3/D4 deferred with this re-mine as the reason; the gate map's D3/D4
  "needs user OK" are resolved as deferred.
- BACKLOG:
  - delete the `[bug, High]` multi-row item;
  - delete the Watch-list msft-segment-revenue `quote_not_found` line if the replay shows it's
    the same cause, or keep it;
  - add the D3/D4 Watch line;
  - re-check the latent `header_context` coverage-inflation Watch item, since D12a widens the
    header context. Note whether its trigger moved.
  - add an item for the pre-existing `locate_value` hit on chunk 34: `74.9` in the
    percentage-table, read as billions, sits within 1% of 74,550 million.
- Refusal re-mine before package 5 starts (the map's rule).

Commits: 0 docs, 1 D12a, 2 D12b, 3 paren, 4 10-Qs, 6 docs. Each code commit has its own tests,
so `git revert` undoes one rule.

Critical files:
- `src/sec_agent/verification/table_grounding.py`: `_classify_row`, `extract_table_blocks`,
  `GroundedCell`, `locate_value`, `quote_is_grounded`
- `src/sec_agent/agent/citations.py`: `_NON_CLAIM_PATTERN`, `_quote_grounded_in_source`,
  `verify_claims`
- `src/sec_agent/verification/numeric_utils.py`: `_is_negative`, `extract_numbers_with_spans`
- Tests: `tests/verification/test_table_grounding.py`, `tests/verification/test_numeric_utils.py`,
  `tests/agent/test_citations.py`
- Tool: `src/sec_agent/devtools/analyze_gate_replay.py` (used, not changed)

## Testing and verification

- Per step: `ruff check .`, `pyright .`, `pytest --cov=. --cov-report=term-missing -q`, with
  ≥90% on changed critical-core lines.
- Replay: `analyze_gate_replay --qid` slices while iterating. Final full run with
  `--compare <scratchpad>/base.json`. Expected:
  - nvda-segment-revenue-comparison-q1fy27's refusal is recovered and grades correct;
  - **zero** new refusals;
  - every flip is explained, especially D12a cherry-pick flips.
  - The replay re-gates final submits only, so separately re-gate the 17 retried first
    submits offline (scratch script reusing the replay's rebuild) to confirm the 10 targeted
    first-attempt warnings clear.
- Live spot-check (about 60–80 requests): `python -m sec_agent.eval.eval_harness --backend
  gemini --ids` with nvda-segment-revenue-comparison-q1fy27 ×3, aapl-msft-total-assets-comparison,
  nvda-revenue-two-quarter-comparison, aapl-cash-equivalents-q3fy2026,
  nvda-rd-expense-q4fy26-refusal and msft-segment-revenue-comparison-q3fy2026. Check the
  quota state first.
- Then `independent-review-pass` (arch-reviewer on Opus, for critical core). Give the
  `/compact` line at the implementation→review boundary.

## Plan review

`plan-reviewer` (Opus, with escalated critical-core scrutiny), 2026-10-01. Verdict: revise
step 1. Steps 2–4 are sound once the test-spec fixes below are in.

| # | Finding | Disposition |
|---|---|---|
| 1 | High: D12a's "any label before the first data row" reclassifies 612 rows and reopens a wrong-group splice (AAPL chunk 9, `Level 1:`); verified by simulation | **Folded in.** The rule is narrowed to the block's first row (338 cases, splice rejected again in simulation). The case is recorded in step 1. |
| 2 | Medium: the guard test named a fixture that doesn't exist | **Folded in.** New real negative fixtures: AAPL chunk 9 and MSFT chunk 16. |
| 3 | Medium: the wider header context pulls misclassified em-dash data rows into the cherry-pick sets and the coverage region | **Folded in.** The corpus scan reports before/after context and token sets, step 1 is gated on the named cases, and step 6 re-checks the Watch item. |
| 4 | Low: a bare `(1)` is negative today, so the test spec was wrong | **Folded in.** The false case is `Registrant (1)`; a bare `(1)` is true. |
| 5 | Low: extending `extract_numbers_with_spans` breaks exact-shape tests | **Folded in.** It's a sibling function now. |
| 6 | Low: R's placement was left open | **Folded in.** It's a public helper, OR-ed per cell at `citations.py:383`; `quote_is_grounded` stays untouched. |
| — | Note: `locate_value(74550, 'million')` on chunk 34 also hits a percentage-table cell (`74.9` read as billions, within 1%). This predates the plan and isn't made worse. | Add a BACKLOG item in step 6. |

Confirmed by the reviewer: the paren root cause (run `bbba6355c0de`), the `10-Qs` fix, that the
loss run `607e58e8f7f0` is covered by rule R, contiguity under the first-row rule, and the
replay CLI flags.

## Review log

(Filled in during `independent-review-pass`.)

## Addendum

**2026-10-01, step 1 (D12a): the first-row rule needed a data-row guard.** Under the reviewed
first-row rule, the corpus scan (1,338 table blocks) promoted 338 first rows. In many of those
blocks, the context the promotion opened ran through real data rows that classify as `header`
only because they hold em-dash cells. Two examples: AAPL `0000320193-25-000073` chunk 9,
`Cash | $26,686 | $—`, and AAPL `0000320193-26-000006` chunk 13, `Research and development |
(10,887) | —`. Those rows' values then join every lower cell's permitted region and cherry-pick
sets: 311 added token sets held a value-like cell.

The rule now promotes only when no row in the context it would open looks like data (a text
label in column 0 and a number in another cell). Period rows such as `| 2025 | 2024 |` start
with a number, so they still qualify. Results:
- 284 blocks are promoted (244 with data rows).
- The 14 residual value-like token sets are percent-header text, cover pages and a dash-only row.
- Every promoted first row in a block with later labels is a period or table title
  (`Three Months Ended`, `Year Ended`, `Future Amortization Expense`, …), never a sibling of
  those labels.
- The test `test_a_data_row_with_em_dash_cells_keeps_the_first_row_a_label` fails with the guard
  disabled.
