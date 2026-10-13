# Phase 2 build 4, batch 3: numerical-reasoning questions (N1–N10)

## Context

BACKLOG line 61, "Phase 2 build 4: write the v2 questions". Batches 1–2 (21 questions) are
committed on branch `phase2-build4-v2-questions` (`b4138e4`). Batch 3 fills slots N1–N10
(numerical reasoning), as allocated in `docs/plans/2026-10-12-phase2-build4-v2-questions.md`
(§ Slots). It follows the conventions of `docs/plans/2026-10-13-phase2-build4-batch2.md`.

**User decision (2026-10-13): fix a checker gap first.** `check_derivations`
(`src/sec_agent/devtools/check_questions.py`) checks two things today:
- the `calculate` tool's *rounded* result against `expected_value`;
- the input rounding spread against the band width.

It never checks where the *exact* result lands. With an intermediate rounding, an agent that
does the arithmetic correctly without the tool can fail, and the checker still passes the
question. The fix (design below) closes that gap. No v2 question has a derivation yet, so no
existing question can regress.

**Constraints (unchanged from batches 1–2).**
- Draft from the chunk files (`C:/riddhesh/projects/SEC research agent/var/chunks/<T>/`), never
  through the agent's tools.
- Every input at the scale and decimals the filing prints.
- No agent run on a draft question. No judge calls, so no Gemini quota spent.
- v1 files untouched. Ids prefixed `v2-`, all five v2 tags on every question.
- The gate passes `--gold eval/retrieval_gold_v2.jsonl` explicitly. The `--gold` default is a
  BACKLOG item.

**Conventions for this category.**
- **Derivation.** Every question carries a `derivation` with anchored inputs (`part` → gold
  rows), so the checker recomputes it. `expected_value` is the calculate tool's own rounded
  result: 1 decimal for `percent_of`/`percent_change`, 2 for `divide`.
- **`needs_calculate: true`:** no fact-tool shortcut exists. The value is not a
  `formulas.RATIO_DEFINITIONS` ratio, not a `get_yoy_growth` of a tagged metric, and not printed
  in the filing (checked by grep).
- **`needs_calculate: false`** (N3, N5, N7, N9): a shortcut exists, either `get_yoy_growth` on a
  tagged metric or a registered ratio whose definition matches the question's wording.
- **No negative answers.** The grader compares signed values (`grading.value_matcher`), so every
  question is worded to have a positive answer: growth where the metric rose, "by how many
  points did X exceed Y".
- **Questions define their ratios** where the filing's own definition differs:
  - ROA here uses year-end total assets, as the fact tool does;
  - per-barrel uses daily production × 365;
  - JPM figures are on the reported basis, not managed.
- **Restated figures.** A question whose input was restated names the filing it reads from:
  "as reported in its 2025 annual report". The superseded value's result goes in the
  as-printed table as a trap candidate.
- **`forbidden_values`:** batch 2's rule. Use one only where check 7 stays quiet. Every trap
  candidate is recorded in the as-printed table.
- **Gold rows:** one own-period row per input part. Where the next annual filing prints the same
  value in its comparative column, add that row too (`own_period: false`).
- **Chunk references** below are `chunk_index` values (a grep line number is one more).

## Batch 3 slots (from the chunk files 2026-10-13; figures confirmed by the plan reviewer; step 2 pins anchors)

| Slot | Id (draft) | Question gist | Derivation (millions unless noted) | Expected | Filing, chunk_index |
|---|---|---|---|---|---|
| N1 | `v2-jpm-nii-share-2025` | net interest income as a % of total net revenue, 2025, reported basis | `percent_of`(95,443, 182,447) | 52.3% | JPM 10-K `0001628280-26-008131` #105/#111 |
| N2 | `v2-jpm-expense-vs-revenue-growth-2025` | by how many percentage points 2025 noninterest-expense growth exceeded total-net-revenue growth, computed from the dollar amounts to one decimal | `subtract`(`percent_change`(95,640, 91,797), `percent_change`(182,447, 177,556)) = 4.2 − 2.8 | 1.4 pts (exact 1.43) | same, #105/#111 |
| N3 | `v2-bac-net-income-growth-2025` | % growth in net income, 2025 vs 2024, as reported in BAC's 2025 annual report | `percent_change`(30,509, 26,973) | 13.1% | BAC 10-K `0000070858-26-000157` #87/#97 |
| N4 | `v2-tgt-capex-share-of-ocf-fy2025` | capital expenditures as a % of cash provided by operating activities, fiscal 2025 | `percent_of`(3,727, 6,562) | 56.8% | TGT 10-K `0000027419-26-000016` #92 |
| N5 | `v2-wmt-operating-income-growth-fy2026` | % growth in operating income, fiscal 2026 | `percent_change`(29,825, 29,348) | 1.6% (exact 1.63) | WMT 10-K `0000104169-26-000055` #91/#117 |
| N6 | `v2-xom-upstream-earnings-per-boe-2025` | Upstream earnings (U.S. GAAP) per oil-equivalent barrel produced in 2025 (daily production × 365) | `divide`(21,354 million, `multiply`(4,736 thousand, 365 constant)) | 12.35 (raw $) | XOM 10-K `0000034088-26-000045` #63/#86 (earnings), #87/#88 (production) |
| N7 | `v2-xom-roa-2024` | 2024 net income attributable to ExxonMobil as a % of year-end 2024 total assets | `percent_of`(33,680, 453,475) | 7.4% | XOM FY2024 10-K (step 2 pins it); comparative rows in FY2025 10-K #57/#131 |
| N8 | `v2-jnj-oncology-share-change-2025` | by how many points Innovative Medicine's Oncology franchise grew as a share of Innovative Medicine sales, 2024→2025 | `subtract`(`percent_of`(25,380, 60,401), `percent_of`(20,781, 56,964)) = 42.0 − 36.5 | 5.5 pts (exact 5.54) | JNJ 10-K `0000200406-26-000016` #59 |
| N9 | `v2-jnj-net-margin-2025` | net earnings as a % of sales to customers, 2025 | `percent_of`(26,804, 94,193) | 28.5% | same, #89 |
| N10 | `v2-aapl-services-sales-share-change-fy2025` | by how many points Services' share of total net sales rose, fiscal 2024→2025 | `subtract`(`percent_of`(109,158, 416,161), `percent_of`(96,169, 391,035)) = 26.2 − 24.6 | 1.6 pts (exact 1.64) | AAPL 10-K `0000320193-25-000079` #60 (also #51/#52) |

Slot notes:
- **No-shortcut slots** (N1, N2, N4, N6, N8, N10):
  - JPM prints its "overhead ratio" and "pre-provision profit", so N1/N2 avoid both;
    "operating leverage" isn't printed.
  - JPM chunk 104 prints the year-over-year changes as integers (4, 3). That route gives 1, so
    N2's wording asks for the dollar-amount computation, and 1 is recorded as a trap candidate.
  - XOM #35 prints production *costs* per barrel, not earnings.
  - JPM chunk 125 also prints managed-basis figures, which give 51.7; that's why N1 names the
    reported basis.
- **Shortcut slots:**
  - N3: `get_yoy_growth(net_income)`. BAC restated 2024 net income: its FY2024 10-K prints
    27,132, the FY2025 10-K prints 26,973. `_pick_entry` prefers the latest filing, so the fact
    tool agrees with the wording. Mixing the two filings gives 12.4%, a trap candidate. This
    replaces the earlier FY2024 draft (2.5% vs 2.3%, two defensible answers).
  - N5: `get_yoy_growth(operating_income)`.
  - N7: `return_on_assets`, year-end definition (XOM NetIncomeLoss 2024 = 33,680,000,000).
  - N9: `net_margin`. JNJ prints R&D and pre-tax margins as a percent of sales, but not net
    margin. Its companyfacts revenue and net income match.
- **Gaps** (XBRL lacks the figure): N6 (production) and N8 (franchise sales are dimensioned).
- **FY spread:** N7 is FY2024. The rest are FY2025 or fiscal 2026 annual filings.
- **Allocation changes** (stated, per the allocation's rule):
  - N2 and N6 are `answer_source: "table"`, not `"both"`. No prose input has the precision the
    band needs (XOM's "4.7 million" barrels; JPM's billions).
  - N10 changed from Services' share of gross margin to Services' share of net sales. The
    gross-margin version rounds to 2.9 via the tool but 2.8 from exact arithmetic, which no
    clean expected value covers.
  - Category, type, trap, steps and `needs_calculate` counts are unchanged.
- **N8's anchor** is "Total Oncology | $25,380 | $20,781". The smaller "…Oncology | 376 | 317"
  row in chunk 59 is ruled out by the wording.

## Checker change (`check_questions.py`, check 2)

Let `exact` be the unrounded result of the printed inputs, `_compute(derivation, {}, rounded=False)`.
The band is the one around `expected_value` (the default, or the question's `tolerance`).

- **Corner condition, replacing `spread <= band`.** Every input-rounding corner's exact result
  must lie within the band around `expected_norm`: `max |corner − expected_norm| <= band`.
  `rounding_spread` already evaluates every corner. Refactor it into a helper that returns the
  corner results, so both the spread INFO and this condition use them. This covers both the
  offset of the exact result and the input spread, with no symmetry assumption.
- **Rounded-exact condition.** `round(exact, decimals of expected_value)` must lie within the
  band. This is what an agent doing the arithmetic itself reports. Use `retrieval_replay._decimals`.
- **Error wording.**
  - Overflow driven only by input spread keeps today's message: "needs a tolerance (spread …)"
    or "exceeds the tolerance".
  - Overflow driven by offset (the exact or rounded-exact result is outside the band) gets a new
    message, so the author checks `expected_value` before reaching for a tolerance:
    "exact result X (rounds to Y) is outside the band of expected Z: check expected_value, or set
    a tolerance".
- **Skip on recompute error.** If the tool-rounded recompute ERROR has already fired, skip the
  offset conditions and keep only the spread check. A wrong `expected_value` then gives one
  error, not two. Existing tests at `tests/devtools/test_check_questions.py:150` and `:213`
  assert one ERROR and stay as they are.
- **`fits_default`**, which feeds the "tolerance is unneeded" WARN, uses the same corner and
  rounded-exact conditions at the default band.
- **INFO line** adds the exact result.
- **Docstring.** Update the module docstring's check 2 line.
- **Tests (TDD, red first):**
  - the tool-rounded result is in the band but the exact result is out → the offset ERROR;
  - the rounded-exact result is out while the unrounded exact is in → the offset ERROR;
  - the same as either of the above with a sufficient `tolerance` → no ERROR, and no "unneeded"
    WARN;
  - a wrong `expected_value` → exactly one ERROR (the recompute ERROR);
  - an offset-only overflow inside a comparison entry's derivation → ERROR naming the entry;
  - the existing growth tests stay green (offset 0.045 < 0.05, and 2.75 rounds to 2.8).
- **Coverage:** `check_questions.py` at the 80% bar (100% today). `questions.py` is untouched.

## Out of scope

- Any agent or judge run.
- Build 5's fact-tool fixes (N7/N9's shortcuts are measured, not fixed).
- The `--gold` default.
- Batches 4–6.

## Steps

1. Save this plan as `docs/plans/2026-10-13-phase2-build4-batch3.md` with its
   `PROJECT_INDEX.md` line. Same branch.
2. Corpus read (read-only, offline):
   - pin each input's verbatim anchor and `chunk_index`;
   - find XOM's FY2024 10-K accession and anchors;
   - re-grep each expected value and its rounded and exact variants in the company's chunks, to
     confirm that no `needs_calculate: true` answer is printed.
3. Checker change, TDD: red, then green.
4. Draft the 10 questions into `eval/eval_questions_v2.jsonl` and their anchors into
   `eval/retrieval_gold_v2.jsonl`.
5. Write the as-printed table into the repo plan: one row per input, plus each derivation's
   exact and tool-rounded result, and each trap candidate (N2's 1, N3's 12.4, JPM's
   managed-basis 51.7).
6. Run the gate:
   `PYTHONPATH=src python -m sec_agent.devtools.check_questions --questions eval/eval_questions_v2.jsonl --gold eval/retrieval_gold_v2.jsonl --chunks-dir "C:/riddhesh/projects/SEC research agent/var/chunks" --xbrl-cache-dir "C:/riddhesh/projects/SEC research agent/var/xbrl_cache"`
   on all 31 v2 questions. It must exit 0. Read every WARN and INFO line. Set a tolerance only
   where the script reports one is needed.
7. `ruff check .`, `pyright .`, `pytest --cov=. --cov-report=term-missing -q`; diff coverage of
   `check_questions.py` ≥80%.
8. Give the user the `/compact` line. Then `independent-review-pass` on `b4138e4..` plus the
   working tree, classified by the diff; Review log in the repo plan. Write a `docs/reviews/`
   file only if the review is Substantial or a finding is deferred or disputed. Then the user
   reviews the wording and spot-checks values.
9. After approval:
   - BACKLOG build 4 line: batches 1–3 done, next is batch 4 (P1–P8);
   - allocation table: N1–N10 get their ids and the `answer_source` change;
   - commit only when the user asks.

## Verification

- `check_questions` exits 0 on 31 v2 questions. Every derivation's INFO line shows its exact
  result inside its band.
- The new checker tests are green; the full suite, ruff and pyright are clean;
  `check_questions.py` diff coverage is ≥80%.
- `eval/eval_questions.jsonl`, `eval/retrieval_gold.jsonl`, `eval_harness.py` and `grading.py`
  have no diff.
- The as-printed table is complete for every input in batch 3.

## Plan review

Plan-reviewer (opus), 2026-10-13, 1 round. Each finding was folded in:

1. **High.** N3 (BAC FY2024): 2024 net income was restated (27,132 → 26,973), so it had two
   defensible answers and no FY2024-filing anchor. Moved to 2025 growth, worded "as reported in
   the 2025 annual report"; 12.4% recorded as a trap.
2. **Med-high.** An agent reports a rounded exact value, not 2.846. Added the rounded-exact
   condition. N10 was swapped to a metric where the tool and exact arithmetic both round to 1.6.
3. **Med.** Existing tests at `:150`/`:213` would get a second, misleading ERROR. The offset
   check is skipped after a recompute error, and the offset overflow gets its own wording.
4. **Low-med.** Simpler exact condition. Adopted: max over corners |result − expected| ≤ band.
5. **Low-med.** N2's integer % changes are a printed near-shortcut. The wording asks for the
   dollar computation to one decimal; 1 is recorded as a trap.
6. **Low-med.** N1's managed-basis figures. The wording says reported basis; 51.7 is recorded.
7. **Low.** Chunk numbering. Converted to `chunk_index`.
8. **Low.** N10's gross-margin trap. Moot after the swap. The new N10's printed "14%" Services
   growth goes in the as-printed table.
9. **Low.** Test seams. Comparison-entry, single-error and rounded-exact tests added.

Confirmed fine by the reviewer: every figure in the slot table against the chunks; the
arithmetic; N6's `constant` input and raw result; the fact-tool shortcuts for WMT, XOM and JNJ
in companyfacts.

## As-printed table

Every input in batch 3, beside the filing text it comes from (checked by hand against the chunk
files, 2026-10-13), then each derivation's exact and tool-rounded result and its trap
candidates. "Exact" is the checker's INFO line (`check_questions`, 2026-10-13). No batch 3
question has `forbidden_values`: every trap candidate lies outside its question's grading band, so
an answer built on it already fails on value, and a correct answer may name one in passing (N1's
managed basis, N3's restatement), which `forbidden_values` would fail.

| Question | Field | Value | Printed as (filing, chunk_index) |
|---|---|---|---|
| `v2-jpm-nii-share-2025` | `nii-2025` | 95,443 million | "Net interest income \| 95,443 \| 92,583 \| 89,267" (JPM 10-K `0001628280-26-008131` #311, also #111; with % change in #105) |
| | `revenue-2025` | 182,447 million | "Total net revenue \| 182,447 \| 177,556 \| 158,104" (same 10-K #311, #566; with `$` in #111) |
| | result | 52.3 (exact 52.313) | not printed (grep "52.3": only a $52.3 billion surplus, #191) |
| | trap | 51.7 | managed basis: "Net interest income \| 95,443 \| 425 \| 95,868 …", "Total net revenue \| 182,447 \| 3,134 \| 185,581 …" (#125) → 51.658; band of 52.3 is +/-0.523, so 51.7 is outside |
| `v2-jpm-expense-vs-revenue-growth-2025` | `expense-2025` | 95,640 million | "Total noninterest expense \| 95,640 \| 91,797 \| 87,172" (JPM 10-K `0001628280-26-008131` #311) |
| | `expense-2024` | 91,797 million | "Total noninterest expense \| 91,797 \| 87,172 \| 76,140" (JPM 10-K `0000019617-25-000270` #321); comparative in the 2025 10-K #311 |
| | `revenue-2025` | 182,447 million | as N1 |
| | `revenue-2024` | 177,556 million | "Total net revenue \| 177,556 \| 158,104 \| 128,695" (2024 10-K #321); comparative in the 2025 10-K #311 |
| | result | 1.4 (tool 4.2 − 2.8; exact 4.1865 − 2.7546 = 1.4318) | not printed |
| | trap | 1 | the printed integer changes: "Total noninterest expense \| 95,640 \| 91,797 \| 4", "Total net revenue \| 182,447 \| 177,556 \| 3" (#105) |
| `v2-bac-net-income-growth-2025` | `net-income-2025` | 30,509 million | "Net income \| 30,509 \| 26,973 \| 26,305" (BAC 10-K `0000070858-26-000157` #97; also #87, #236) |
| | `net-income-2024` | 26,973 million | same row, 2024 column (restated) |
| | result | 13.1 (exact 13.109) | fact tool: `get_yoy_growth(net_income)` |
| | trap | 12.4 | the 2024 10-K's pre-restatement figure: "Net income \| 27,132 \| 26,515 \| 27,528" (`0000070858-25-000139` #94) → 12.447 |
| `v2-tgt-capex-share-of-ocf-fy2025` | `capex-fy2025` | 3,727 million | "Expenditures for property and equipment \| (3,727) \| (2,891) \| (4,806)" (TGT 10-K `0000027419-26-000016` #92) |
| | `ocf-fy2025` | 6,562 million | "Cash provided by operating activities \| 6,562 \| 7,367 \| 8,621" (same, #92) |
| | result | 56.8 (exact 56.797) | not printed (grep "56.8", "57%") |
| `v2-wmt-operating-income-growth-fy2026` | `operating-income-fy2026` | 29,825 million | "Operating income \| 29,825 \| 29,348 \| 27,012" (WMT 10-K `0000104169-26-000055` #91, #117; with `$` in #86) |
| | `operating-income-fy2025` | 29,348 million | "Operating income \| 29,348 \| 27,012 \| 20,428" (WMT 10-K `0000104169-25-000021` #94, #120); comparative in the fiscal 2026 10-K |
| | result | 1.6 (exact 1.6253) | fact tool: `get_yoy_growth(operating_income)`. Printed nearby but not the answer: "Operating income as a percentage of net sales \| 4.2% \| 4.4%" (#86) |
| `v2-xom-upstream-earnings-per-boe-2025` | `upstream-earnings-2025` | 21,354 million | "Earnings (loss) (U.S. GAAP) \| 5,063 \| 16,291 \| 21,354 …", columns 2025 U.S./Non-U.S./Total (XOM 10-K `0000034088-26-000045` #63); "Total \| 21,354 \| 25,390 \| 21,308" (#86) |
| | `production-2025` | 4,736 thousand | "Oil-equivalent production(1)(thousands of oil-equivalent barrels daily) \| 4,736 \| 4,333 \| 3,738" (same, #88) |
| | constant | 365 | days in the year, stated in the question |
| | result | 12.35 raw (exact 12.353) | not printed (grep "12.35": only TTF $12.39, #109). XBRL gap: both inputs are segment or operating data |
| | prose route | 12.45 | "2025 production of 4.7 million oil-equivalent barrels per day" (#88) → 12.448, inside the +/-0.1235 band, so not a trap |
| `v2-xom-roa-2024` | `net-income-2024` | 33,680 million | "Net income (loss) attributable to ExxonMobil \| 33,680 \| 36,010 \| 55,740" (XOM 10-K `0000034088-25-000010` #59, #62, #135); comparative "… \| 28,844 \| 33,680 \| 36,010" (2025 10-K `0000034088-26-000045` #57, #131) |
| | `total-assets-2024` | 453,475 million | "Total Assets \| 453,475 \| 376,317" (2024 10-K #136); comparative "Total Assets \| 448,980 \| 453,475" (2025 10-K #132) |
| | result | 7.4 (exact 7.4271) | fact tool: `return_on_assets` (year-end assets) |
| | trap | 12.7 | look-alike: return on average capital employed, "Corporate total \| 33,680 \| 36,010 \| 278,102 \| 243,440 \| 12.7 \| 15.0 …" (2024 10-K #57) |
| `v2-jnj-oncology-share-change-2025` | `oncology-2025` | 25,380 million | "Total Oncology \| $25,380 \| $20,781 \| 22.1% …" (JNJ 10-K `0000200406-26-000016` #59) |
| | `im-sales-2025` | 60,401 million | "Total Innovative Medicine Sales \| $60,401 \| 56,964 \| 6.0% …" (same, #59) |
| | `oncology-2024` | 20,781 million | "Total Oncology \| 20,781 \| 17,661 …" (JNJ 10-K `0000200406-25-000038` #58); comparative in the 2025 10-K #59 |
| | `im-sales-2024` | 56,964 million | "Total Innovative Medicine Sales \| $56,964 \| 54,759 …" (2024 10-K #58); comparative in the 2025 10-K #59 |
| | result | 5.5 (tool 42.0 − 36.5; exact 42.019 − 36.481 = 5.5382) | not printed. XBRL gap: franchise sales are dimensioned. The "Other Oncology \| 376 \| 317" row (#59) is a different line. Printed beside: Oncology growth 22.1%, Innovative Medicine growth 6.0% |
| `v2-jnj-net-margin-2025` | `net-earnings-2025` | 26,804 million | "Net earnings \| $26,804 \| 14,066 \| 35,153" (JNJ 10-K `0000200406-26-000016` #89) |
| | `sales-2025` | 94,193 million | "Sales to customers \| $94,193 \| 88,821 \| 85,159" (same, #89) |
| | result | 28.5 (exact 28.456) | fact tool: `net_margin`; not printed |
| `v2-aapl-services-sales-share-change-fy2025` | `services-fy2025` | 109,158 million | "Services \| 109,158 \| 96,169 \| 85,200" (AAPL 10-K `0000320193-25-000079` #60); "Services(1) \| 109,158 \| 14% \| 96,169 \| 13% \| 85,200" (#52) |
| | `net-sales-fy2025` | 416,161 million | "Total net sales \| 416,161 \| 391,035 \| 383,285" (same, #60; with `$` in #68, #86) |
| | `services-fy2024` | 96,169 million | "Services \| 96,169 \| 85,200 \| 78,129" (AAPL 10-K `0000320193-24-000123` #60); comparative in the fiscal 2025 10-K #60 |
| | `net-sales-fy2024` | 391,035 million | "Total net sales \| 391,035 \| 383,285 \| 394,328" (fiscal 2024 10-K #60); comparative in the fiscal 2025 10-K #60 |
| | result | 1.6 (tool 26.2 − 24.6; exact 26.230 − 24.593 = 1.6363) | not printed. Printed beside: Services growth 14% (#52). XBRL: Services sales are dimensioned (no companyfacts match), so N10 is also a gap, which the allocation table didn't mark |

## Review log

Classified **Standard** by the diff: about 185 changed non-doc lines (checker and tests about 170,
plus 45 JSONL lines), and no blast-radius path (`devtools/` isn't listed).

**Round 1** (snapshot `6db0bb7`; diff `b4138e4..` plus the working tree):
`/code-review medium`, arch-reviewer (sonnet), security-reviewer.

- Security: no findings.
- Code review 1. `rounded_exact` used `round()`, which works on the float's binary value and
  rounds ties to even (2.675 → 2.67), not as a person reports it. **[Fixed]** `_round_half_up`
  uses `Decimal(repr(x))` with `ROUND_HALF_UP`, and has a test.
- Code review 2. `_decimals` reads the precision from how `expected_value` is written, so 17
  gives 0 decimals and 4e-05 too. **[Verified, no fix needed]** This is the project's existing
  convention (`retrieval_replay._decimals`, which the spread check already uses): the written
  value sets the precision. Every derived value in v2 is written at the tool's precision, and
  no v2 value prints in scientific notation.
- Code review 3. The exact result printed with `:.5g` drops into scientific notation at million
  scale. **[Fixed]** It now prints 3 more decimals than `expected_value`; rounds-to prints at the
  same decimals as expected.
- Code review 4 / arch nit 1. The offset ERROR said "set a tolerance" even when one was already
  set. **[Fixed]** It now says "widen the tolerance"; a test was added.
- Code review 5. The early return after an offset ERROR hides a spread ERROR. **[Verified, no fix
  needed]** One error per derivation, offset first, is the plan's design. The offset fix
  (correcting `expected_value`) usually moves the corners too, so a spread ERROR shown alongside
  would often be stale. The docstring now says so.
- Code review 6. No test covered the ", reaching X from expected" suffix. **[Fixed]** The
  needs-a-tolerance test asserts it.
- Code review 7. The `check_derivations` docstring promised a corner check that doesn't run
  when the tool's result misses. **[Fixed]** The docstring now says so.
- Code review 8. `fits_default` was computed even after a recompute miss, so a too-tight
  tolerance could get both the recompute ERROR and an "unneeded" WARN. **[Fixed]** It's None
  after a miss; a test was added.
- Arch nit 2. `_check_rounding`'s `recomputes` flag switches behaviour. **[Verified, no fix
  needed]** The reviewer marked it optional. It's readable and within the lint limits.
- Arch nit 3. N6's production anchor was a label fragment. **[Fixed]** It now holds the full row
  text.
- Arch q. N10 is an XBRL gap too (Services sales are dimensioned). **[Fixed in step 9]** The
  allocation table and the BACKLOG line record it.
- Arch risk. The Review log was empty. **[Fixed]** This section.

After the fixes: the gate exits 0 on 31 questions; 1669 passed; ruff and pyright are clean;
`check_questions.py` has 100% diff coverage.

**Round 2** (delta `git diff 6db0bb7`; snapshot `ff2986e`): `/code-review low`, security-reviewer.
The first attempt at both hit a usage limit and was relaunched.

- Security: no findings.
- `/code-review low` returned no findings, but after a single tool call, so the author also read
  the checker delta by hand. Checked: half-up rounding of negatives (away from zero, as a person
  reports); the formatting with 0-decimal expected values; `fits_default` None only after a
  recompute miss. No findings.
- Clean round, so the review is done. Summary: code-review medium + low, arch (sonnet),
  security; 2 rounds, 9 fixed, 3 verified with no fix needed, 0 deferred. No `docs/reviews/`
  file: the review was Standard and nothing was deferred or disputed.
