# Phase 2 build 4, batch 4: cross-period questions (P1–P8)

## Context

BACKLOG line 61, "Phase 2 build 4: write the v2 questions". Batches 1–3 (31 questions) are
committed on branch `phase2-build4-v2-questions` (`07afc37`). Batch 4 fills slots P1–P8
(cross-period), as allocated in `docs/plans/2026-10-12-phase2-build4-v2-questions.md` (§ Slots).
It follows the conventions of `docs/plans/2026-10-13-phase2-build4-batch3.md`.

The map (`docs/plans/2026-10-07-data-expansion-phase2-map.md`) scopes cross-period to what
FY2024+ filings show: up to 3 fiscal years, or a 10-Q against the prior 10-K. The grader checks
entity only, with no period parser, so each question is worded so that swapping the periods
changes the answer's sign. Fiscal-label traps use `forbidden_values`.

**User decision (2026-10-13): P3 printed, P8 computed.** P3 (TGT) and P8 (CAT) are text-only
gaps, so no fact tool covers them, and "2 steps, no calculate" only works where the filing
prints the change. P3 asks for Target's printed comparable sales change. P8 asks for CAT's
backlog increase between the 10-K and the latest 10-Q, which needs `calculate`.

**Constraints (unchanged from batches 1–3).**
- Draft from the chunk files (`C:/riddhesh/projects/SEC research agent/var/chunks/<T>/`), never
  through the agent's tools.
- Every input at the scale and decimals the filing prints.
- No agent run on a draft question. No judge calls, so no Gemini quota spent.
- v1 files untouched. Ids prefixed `v2-`, all five v2 tags on every question.
- The gate passes `--gold eval/retrieval_gold_v2.jsonl` explicitly.

**Conventions (batch 3's, carried over).**
- **Derivation** on every derived value, inputs anchored (`part` → gold rows). `expected_value`
  is the calculate tool's own rounded result: 1 decimal for `percent_change`/`percent_of`,
  2 for `divide`. The checker's exact-result and rounded-exact conditions apply.
- **`needs_calculate: false`** means a fact-tool shortcut exists (`get_yoy_growth`,
  `get_multi_year_average`) or the answer is printed. **`true`** means neither (checked by grep).
- **No negative answers** (`grading.value_matcher` compares signed values): growth where the
  metric rose, so a period swap gives a negative and fails.
- **Restated figures:** the question names the filing it reads from; the superseded value's
  result goes in the as-printed table as a trap candidate.
- **`forbidden_values`** only where check 7 stays quiet and a correct answer has no reason to
  state the value. Every trap candidate goes in the as-printed table.
- **Gold rows:** one own-period row per input part. Where a later annual filing prints the same
  value in its comparative column, add that row too (`own_period: false`). An input whose own
  filing prints a different (pre-restatement) value gets no row from that filing (as N3).
- Chunk references are `chunk_index` values.

## Batch 4 slots (from the chunk files and companyfacts, 2026-10-13; step 2 pins anchors)

Millions unless noted.

| Slot | Id (draft) | Question gist | Derivation | Expected | Filing, chunk_index | Calc / shortcut |
|---|---|---|---|---|---|---|
| P1 | `v2-jpm-net-income-growth-q2-2026` | % growth in net income, Q2 2026 vs Q2 2025 (three months) | `percent_change`(21,155, 14,987) | 41.2% (exact 41.156) | JPM 10-Q `0001628280-26-054343` #8 (table), #9 (prose "up 41%"); Q2 2025 10-Q `0000019617-25-000615` | no: `get_yoy_growth(net_income, fiscal_year=2026, fiscal_period="Q2")` (companyfacts 21,155 / 14,987); the printed 41 is inside the band |
| P2 | `v2-bac-total-assets-growth-2025` | % growth in total assets, year-end 2025 vs year-end 2024, to one decimal | `percent_change`(3,411,738, 3,261,299) | 4.6% (exact 4.6129) | BAC 10-K `0000070858-26-000157` | no: `get_yoy_growth(total_assets)` gives 4.6 from the 2024 10-K's 3,261,519 too |
| P3 | `v2-tgt-comparable-sales-q2-2026` | Target's comparable sales change, second quarter of fiscal 2026 (three months ended Aug 1, 2026) | none (printed) | 3.8% | TGT 10-Q `0000027419-26-000042` #22 (prose), #26 (table) | no: printed. Gap: comparable sales aren't in XBRL |
| P4 | `v2-wmt-avg-net-income-fy2024-fy2026` | average annual consolidated net income attributable to Walmart, fiscal 2024 through fiscal 2026 | `divide`(`add`(`add`(15,511, 19,436), 21,893), 3 constant) | 18,946.67 | WMT 10-K `0000104169-26-000055` (all three columns); FY2025 `0000104169-25-000021`, FY2024 `0000104169-24-000056` own rows | no: `get_multi_year_average(net_income, 2024, 2026)` |
| P5 | `v2-wmt-operating-income-growth-fy2025` | % growth in operating income, fiscal 2025 vs fiscal 2024 | `percent_change`(29,348, 27,012) | 8.6% (exact 8.6480) | WMT 10-K `0000104169-25-000021`; comparative in FY2026 10-K | no: `get_yoy_growth(operating_income, 2025)` |
| P6 | `v2-jnj-sales-growth-fy2023` | % growth in sales to customers, fiscal 2023 vs fiscal 2022 (ended Jan 1, 2023), as reported in the fiscal 2024 annual report | `percent_change`(85,159, 79,990) | 6.5% (exact 6.4621) | JNJ 10-K `0000200406-25-000038` #149 ("Worldwide \| $88,821 \| 85,159 \| 79,990 \| 4.3% \| 6.5"), also #88 ("Sales to customers \| $88,821 \| 85,159 \| 79,990"); 85,159 also in FY2025 10-K | no: the answer is printed ("an increase of 6.5% in 2023", #56; #149). `get_yoy_growth(revenue, 2023)` returns 8.2 (label collision, below); measured, not fixed |
| P7 | `v2-xom-total-assets-growth-h1-2026` | % change in total assets from Dec 31, 2025 to Jun 30, 2026 | `percent_change`(464,482, 448,980) | 3.5% (exact 3.4527) | XOM 10-Q `0000034088-26-000093` ("Total Assets \| 464,482 \| 448,980"); 2025 10-K `0000034088-26-000045` #132 | **yes**: `get_yoy_growth` compares June 30, 2026 with June 30, 2025, not with the prior year-end; no other shortcut, not printed |
| P8 | `v2-cat-backlog-increase-h1-2026` | increase in firm order backlog from Dec 31, 2025 to Jun 30, 2026 | `subtract`(72.1 billion, 51.2 billion) | 20.9 billion | CAT 10-Q `0000018230-26-000046` ("…approximately $72.1 billion, about $9.4 billion higher than the first quarter of 2026"); 10-K `0000018230-26-000008` #16 ("…approximately $51.2 billion at December 31, 2025 and $30.0 billion at December 31, 2024") | **yes**: text-only inputs. Gap: backlog isn't in XBRL |

Slot notes:
- **Shape mix.** Quarter vs prior-year quarter (P1, P3), year-end vs year-end (P2), three-year
  average (P4), annual growth (P5, P6), 10-Q vs prior 10-K (P7, P8). Spread across FY2023–2026
  periods, all printed in FY2024+ filings.
- **Trap candidates** (as-printed table; `forbidden_values` only if check 7 is quiet):
  - P1: the six-month growth, printed beside as 27 (37,649 vs 29,630); the sequential reading
    (vs Q1 2026's 16,494) gives 28.3. The printed "41" for the quarter lies inside the ±0.412
    band, so it's not a trap.
  - P2: the printed integer change "5" (outside the band, ±0.05 by the floor), hence "to one
    decimal"; and the printed dollar change $150,439 million.
  - P3: the six-month 4.7% and the prior-year quarter's (1.9)%, both printed beside: no
    `forbidden_values`.
  - P5 (fiscal-label): fiscal 2026 growth 1.6% (29,825 vs 29,348, which is N5's answer and the
    calendar-2025 reading of "2025"). A `forbidden_values` candidate. Also fiscal 2024's 32.2%.
  - P4: consolidated net income including noncontrolling interests (16,270 / 20,157 / 22,270)
    averages 19,566; the wording "attributable to Walmart" excludes it.
  - P6 (fiscal-label): the fact tool's 8.2 (below) is the `forbidden_values` candidate: positive,
    plausible, printed nowhere. Fiscal 2024's 4.3% is printed beside the answer (#56, #149), so
    it's recorded but not forbidden. The pre-Kenvue fiscal 2022 figure, 94,943 (FY2022 10-K, not
    ingested), gives −10.3.
  - P7: the dollar change 15,502 million. The exact 3.4527 sits only 0.0027 inside the band
    [3.45, 3.55] (the 0.05 floor), so an agent that truncates to 3.4 fails; that's a rounding
    error, not a wording problem. A two-decimal "3.45" lands on the lower edge and passes (the
    float difference is 0.0499…, within the inclusive limit).
  - P8: the printed sequential rise $9.4 billion (in the answer's own gold chunk, so no
    `forbidden_values`), and 2025's annual rise, 21.2 billion.
- **P6's fact-tool route** (plan reviewer's replay of `_pick_entry`, `xbrl_facts.py:244-288`):
  an annual entry's fiscal year is its end year, and the latest end wins. So "current" fiscal
  2023 is 85,159, but "prior" fiscal 2022 resolves to fiscal **2021** (ended 2022-01-02;
  restated 78,740 from the FY2023 10-K, printed in no ingested chunk), giving 8.2 (8.1521). This
  is the map's fiscal-year-fix acceptance test; build 5 fixes it. Step 2 re-runs the replay.
- **P6's gold.** The answer is printed in #56 (prose) and #149 (table), so the input anchors use
  #149, putting the printed 6.5 in a gold chunk; #88 gets a row too.
- **Own-period rows that can't exist** (the gold-row rule's exception, stated): P6's inputs have
  no ingested own-period filing (FY2022 and FY2023 10-Ks aren't ingested), so both parts get
  `own_period: false` rows only. P2's 3,261,299 likewise: its own-period filing prints
  3,261,519. The gate doesn't read `own_period`; only `retrieval_replay` does.
- **P4** reuses net income, not operating income: N5 and P5 already use WMT operating income.
  The tool's `divide` rounds to 2 decimals; `get_multi_year_average` returns the raw average.
- **Restatement checks.** P2's 2024 total assets: the 2024 10-K prints 3,261,519, the 2025 10-K
  3,261,299; both give 4.6, so the question needn't name a filing. P6's fiscal 2022 sales are the
  restated continuing-operations figure, so the question names the fiscal 2024 annual report.
- **Allocation changes** (stated, per the allocation's rule):
  - P3: steps 2 → 1 (a printed change), source text → both (prose #22 and table #26).
  - P8: `needs_calculate` no → yes (user decision). Calc count 9 → 10.
  - Category, type and trap counts are unchanged.

## Out of scope

- Any agent or judge run.
- Checker changes: none is expected. If the gate exposes a checker gap, stop and raise it with
  the user (batch 3's pattern) rather than working around it.
- Build 5's fact-tool fixes (P6's label collision is measured, not fixed).
- The `--gold` default. Batches 5–6.

## Steps

1. Save this plan as `docs/plans/2026-10-13-phase2-build4-batch4.md` with its
   `PROJECT_INDEX.md` line. Same branch.
2. Corpus read (read-only, offline):
   - pin each input's verbatim anchor and `chunk_index`, including the comparative rows in later
     annual filings and P1's Q2 2025 10-Q row;
   - re-grep each expected value and its rounded and exact variants in the company's chunks: a
     `needs_calculate: true` answer must not be printed;
   - grep each `forbidden_values` candidate in the answer's gold chunks (check 7's scope);
   - trace P6's `get_yoy_growth(revenue, 2023)` pick from the cached companyfacts and record it.
3. Draft the 8 questions into `eval/eval_questions_v2.jsonl` and their anchors into
   `eval/retrieval_gold_v2.jsonl`, in the batch 3 field order.
4. Write the as-printed table into the repo plan: one row per input, plus each derivation's
   exact and tool-rounded result, and each trap candidate.
5. Run the gate:
   `PYTHONPATH=src python -m sec_agent.devtools.check_questions --questions eval/eval_questions_v2.jsonl --gold eval/retrieval_gold_v2.jsonl --chunks-dir "C:/riddhesh/projects/SEC research agent/var/chunks" --xbrl-cache-dir "C:/riddhesh/projects/SEC research agent/var/xbrl_cache"`
   on all 39 v2 questions. It must exit 0. Read every WARN and INFO line (XBRL INFO lines by eye:
   P3 gets none, since percent parts are skipped; any P8 match at billion scale is coincidental).
   Set a tolerance only where the script reports one is needed.
6. `ruff check .`, `pyright .`, `pytest --cov=. --cov-report=term-missing -q` (expected: no code
   diff, so a sanity run).
7. Give the user the `/compact` line. Then `independent-review-pass` on `07afc37..` plus the
   working tree, classified by the diff; Review log in the repo plan. A `docs/reviews/` file only
   if the review is Substantial or a finding is deferred or disputed. Then the user reviews the
   wording and spot-checks values (at least one per category: one of P1–P8, plus the fiscal-label
   pair).
8. After approval:
   - BACKLOG build 4 line: batches 1–4 done, next is batch 5 (C1–C9);
   - allocation table: P1–P8 get their ids and the P3/P8 changes; tallies updated (calc 10,
     `needs_calculate` list gains P8);
   - commit only when the user asks.

## Verification

- `check_questions` exits 0 on 39 v2 questions; every derivation's INFO line shows its exact
  result inside its band.
- The full suite, ruff and pyright are clean.
- `eval/eval_questions.jsonl`, `eval/retrieval_gold.jsonl` and `src/` have no diff.
- The as-printed table is complete for every input and trap candidate in batch 4.

## Plan review

Plan-reviewer (opus), 2026-10-13, 1 round. Every finding was folded in:

1. **High.** P6's predicted fact-tool result was wrong: `_pick_entry` resolves fiscal 2022 to
   fiscal 2021 (78,740), so the tool returns 8.2, not −10.3. Slot notes corrected; 8.2 becomes
   the `forbidden_values` candidate.
2. **High.** P6's answer (6.5%) and its proposed 4.3% trap are printed together (#56, #149).
   4.3 dropped as a forbidden value; inputs anchored on #149 so the printed answer sits in a gold
   chunk; the shortcut column says "printed".
3. **Med.** P6 (and P2's 2024 input) can't have own-period rows. Stated as the gold-row rule's
   exception.
4. **Low.** P1's shortcut needs `fiscal_year=2026`, or it drifts to the latest quarter. Fixed;
   the prose "up 41%" (#9) and the sequential 28.3 trap added.
5. **Low.** P8's 10-K chunk is #16, not #15. Fixed.
6. **Low.** P3 gets no XBRL INFO line (percent parts are skipped). Step 5 corrected.
7. **Low.** P7's no-shortcut reason now rests on the tool's period logic, not the stale cache;
   the 3.4 truncation risk is noted.
8. **Low.** P4's noncontrolling-interest trap (19,566) added.

Confirmed fine by the reviewer: P1, P2, P4, P5 shortcuts against companyfacts; P4's nested
derivation with a constant divisor; P5's 1.6 trap is quiet under check 7; P3's printed figures;
P7/P8 answers printed nowhere; every exact result inside its band, and every period swap flips
the sign.

## As-printed table

Every input in batch 4, beside the filing text it comes from (checked by hand against the chunk
files, 2026-10-13), then each derivation's exact and tool-rounded result and its trap
candidates. "Exact" is the checker's INFO line (`check_questions`, 2026-10-13). Fact-tool
results are an offline replay of `formulas.get_yoy_growth` / `get_multi_year_average` over the
cached companyfacts, with the network blocked.

| Question | Field | Value | Printed as (filing, chunk_index) |
|---|---|---|---|
| `v2-jpm-net-income-growth-q2-2026` | `net-income-q2-2026` | 21,155 million | "Net income \| 21,155 \| 14,987 \| 41 \| 37,649 \| 29,630 \| 27" (JPM 10-Q `0001628280-26-054343` #8); also income statement #145 "Net income \| $21,155 \| $14,987 \| $37,649 \| $29,630" |
| | `net-income-q2-2025` | 14,987 million | "Net income \| 14,987 \| 18,149 \| (17) \| 29,630 \| 31,568 \| (6)" (JPM 10-Q `0000019617-25-000615` #8); comparative in the 2026 10-Q #8 |
| | result | 41.2 (exact 41.156) | fact tool: `get_yoy_growth(net_income, fiscal_year=2026, fiscal_period="Q2")` = 41.2. Printed: "41" (#8), "net income of $21.2 billion, up 41%" (#9), both inside the +/-0.412 band |
| | trap | 27 | six-month change, printed beside in #8 (37,649 vs 29,630). Outside the band; not forbidden (printed in a gold chunk) |
| | trap | 28.3 | sequential reading vs Q1 2026's 16,494 (#4: "Net income \| $21,155 \| $16,494 \| …") → 28.259 |
| `v2-bac-total-assets-growth-2025` | `total-assets-2025` | 3,411,738 million | "Total assets \| $3,411,738 \| $3,261,299" (BAC 10-K `0000070858-26-000157` #238; also #87, and #90 with the change) |
| | `total-assets-2024` | 3,261,299 million | same rows, 2024 column (restated). The 2024 10-K (`0000070858-25-000139` #84, #88, #235) prints 3,261,519 |
| | result | 4.6 (exact 4.6129) | fact tool: `get_yoy_growth(total_assets, fiscal_year=2025)` = 4.6. Without `fiscal_year` it returns 1.7 (latest 10-Q, June 30, 2026 vs 2025). 3,261,519 also gives 4.6 (4.6058) |
| | trap | 5 | printed integer change: "Total assets \| $3,411,738 \| $3,261,299 \| $150,439 \| 5" (#90), outside the +/-0.05 band, hence "to one decimal" |
| | trap | 150,439 million | printed dollar change (#90); a different unit category |
| `v2-tgt-comparable-sales-q2-2026` | `value` | 3.8 percent | "Comparable sales change \| 3.8% \| (1.9)% \| 4.7% \| (2.8)%" (TGT 10-Q `0000027419-26-000042` #26); "A comparable sales increase of 3.8 percent" (#22) |
| | trap | 4.7, (1.9) | six-month change and prior-year quarter, printed beside (#26): no `forbidden_values`. Gap: comparable sales aren't in XBRL |
| `v2-wmt-avg-net-income-fy2024-fy2026` | `net-income-fy2026` | 21,893 million | "Consolidated net income attributable to Walmart \| $21,893 \| $19,436 \| $15,511" (WMT 10-K `0000104169-26-000055` #117, #137) |
| | `net-income-fy2025` | 19,436 million | "… \| $19,436 \| $15,511 \| $11,680" (WMT 10-K `0000104169-25-000021` #120, #139); comparative in the fiscal 2026 10-K |
| | `net-income-fy2024` | 15,511 million | "… \| $15,511 \| $11,680 \| $13,673" (WMT 10-K `0000104169-24-000056` #121, #122, #141); comparatives in the fiscal 2025 and 2026 10-Ks |
| | constant | 3 | years averaged, stated in the question |
| | result | 18,946.67 (exact 18,946.667) | fact tool: `get_multi_year_average(net_income, 2024, 2026)` = 18,946,666,666.67 USD (raw average) |
| | trap | 19,565.67 | consolidated net income incl. noncontrolling interests: "Consolidated net income \| 22,270 \| 20,157 \| 16,270" (fiscal 2026 10-K #117); outside the +/-189 band |
| `v2-wmt-operating-income-growth-fy2025` | `operating-income-fy2025` | 29,348 million | "Operating income \| 29,348 \| 27,012 \| 20,428" (WMT 10-K `0000104169-25-000021` #94, #120, #168); comparative "Operating income \| 29,825 \| 29,348 \| 27,012" (fiscal 2026 10-K #91, #117, #165) |
| | `operating-income-fy2024` | 27,012 million | "Operating income \| 27,012 \| 20,428 \| 25,942" (WMT 10-K `0000104169-24-000056` #121); comparatives in the fiscal 2025 and 2026 10-Ks |
| | result | 8.6 (exact 8.6480) | fact tool: `get_yoy_growth(operating_income, fiscal_year=2025)` = 8.6. Not printed (grep "8.6%") |
| | trap (forbidden) | 1.6 | fiscal 2026 growth (29,825 vs 29,348 → 1.6253), N5's answer and the calendar-2025 reading. Printed in no gold chunk as a percent; check 7's WARN is the fiscal 2022 diluted EPS "1.62" / "$1.63" in #121 (see Review log) |
| | trap | 32.2 | fiscal 2024 growth (27,012 vs 20,428 → 32.230) |
| `v2-jnj-sales-growth-fy2023` | `sales-fy2023` | 85,159 million | "Worldwide \| $88,821 \| 85,159 \| 79,990 \| 4.3% \| 6.5" (JNJ 10-K `0000200406-25-000038` #149); "Sales to customers \| $88,821 \| 85,159 \| 79,990" (#88); "Sales to customers \| $94,193 \| 88,821 \| 85,159" (fiscal 2025 10-K `0000200406-26-000016` #89, also #148) |
| | `sales-fy2022` | 79,990 million | same fiscal 2024 10-K rows (#149, #88), restated for continuing operations |
| | result | 6.5 (exact 6.4621) | printed: "an increase of 6.5% in 2023" (#56) and the #149 row |
| | trap (forbidden) | 8.2 | fact tool: `get_yoy_growth(revenue, fiscal_year=2023)` = 8.2. Replay: fiscal 2023 → 85,159 (end 2023-12-31); fiscal 2022 → 78,740 (end 2022-01-02, frame CY2021, FY2023 10-K `0000200406-24-000013`), i.e. fiscal 2021 → 8.1521. In no gold chunk (grep "8.1", "8.2") |
| | trap | 4.3 | fiscal 2024 growth, printed beside (#56, #149): recorded, not forbidden |
| | trap | −10.3 | pre-Kenvue fiscal 2022 sales 94,943 (FY2022 10-K, not ingested) |
| `v2-xom-total-assets-growth-h1-2026` | `total-assets-q2-2026` | 464,482 million | "Total Assets \| 464,482 \| 448,980" (XOM 10-Q `0000034088-26-000093` #5) |
| | `total-assets-2025` | 448,980 million | "Total Assets \| 448,980 \| 453,475" (XOM 10-K `0000034088-26-000045` #132; also "Total assets \| 448,980 \| 453,475 \| 376,317" #57, #59); comparative in the 10-Q #5 |
| | result | 3.5 (exact 3.4527) | not printed: grep "3.45", "3.5%", "3.5 percent" finds only "3.452% notes due 2051" (2024 and 2025 10-Ks, debt table) and "13.5 percent" debt-to-capital lines. No shortcut: `get_yoy_growth(total_assets, 2026, "Q2")` compares with June 30, 2025 (and the cached companyfacts stop at Q1 2026, so it returns None) |
| | trap | 15,502 million | dollar change; "$15.5 billion" in the 10-Q (#46) is depreciation, not this change |
| | risk | 3.4 | truncation fails: 3.4527 is 0.047 inside the +/-0.05 band |
| `v2-cat-backlog-increase-h1-2026` | `backlog-q2-2026` | 72.1 billion | "the dollar amount of backlog believed to be firm was approximately $72.1 billion, about $9.4 billion higher than the first quarter of 2026" (CAT 10-Q `0000018230-26-000046` #101) |
| | `backlog-2025` | 51.2 billion | "The dollar amount of backlog believed to be firm was approximately $51.2 billion at December 31, 2025 and $30.0 billion at December 31, 2024" (CAT 10-K `0000018230-26-000008` #16) |
| | result | 20.9 (exact 20.9) | not printed as a dollar figure: "20.9" in CAT chunks is only operating margin or tax rate percent (e.g. 10-Q #64, #74, #102; Q1 10-Q #29). The Q1 10-Q route agrees: $62.7 billion, "about $11.5 billion higher than the fourth quarter of 2025" (`0000018230-26-000021` #84), so 11.5 + 9.4 = 20.9 |
| | trap | 9.4 billion | printed sequential rise, in the answer's gold chunk (#101): not forbidden |
| | trap | 21.2 billion | 2025's annual rise (51.2 − 30.0), printed inputs in #16; outside the +/-0.209 band |

## Review log

**Gate (step 5), 2026-10-13.** `check_questions` on 39 v2 questions: exit 0, 0 errors, 1 WARN.
Every batch 4 derivation's exact result is inside its band (INFO lines above); P3 has no INFO
line, as expected; P7 and P8 draw no printed-answer finding. The WARN: P5's forbidden 1.6 percent
"is printed in gold chunk `0000104169-24-000056#121`". The only match there is the fiscal 2022
diluted EPS ("1.62", "$1.63"). `figure_matches` compares bare numbers for a percent unit, whereas
the grader's `value_matcher` never matches a percent against a per-share amount, so this is a
check 7 false positive (a checker gap). Raised with the user per Out of scope. Decision
(2026-10-13): option (a), keep `forbidden_values: [1.6 percent]` and accept the WARN as a known
false positive. The trap is the real fiscal-label misreading, and the checker fix (unit-aware
check 7 for percent traps) is a BACKLOG item, not this batch's scope.

ruff: 0 errors. pyright: 0 errors. pytest: 1669 passed, total coverage 97%. No diff in
`src/`, `eval/eval_questions.jsonl` or `eval/retrieval_gold.jsonl`.

**Independent review.** Classified **Standard** by the diff: 36 JSONL lines plus docs, no `src/`,
no blast-radius path (`eval/*.jsonl` is data; the rule covers `src/sec_agent/eval/**`). The
JSONL drives grading, so it counts as code for the floor. BACKLOG tags build 4 Substantial, but
each batch is reviewed by its own diff, as batch 3 was.

**Round 1** (snapshot `e44fc54`; diff `07afc37..` plus the working tree): `/code-review medium`,
arch-reviewer (sonnet), security-reviewer.

- Security: no findings.
- Arch 1 / code review 7. Slot-row exact results typed 6.4620 (P6) and 3.4528 (P7); the arithmetic
  and the as-printed table give 6.4621 and 3.4527. **[Fixed]**
- Arch 2. `forbidden_values` sits between `expected_unit` and `derivation`, with no earlier v2
  row to match. **[Verified, no fix needed]** That was the intended order (Context, step 3).
  Key order has no effect on loading.
- Arch 3. Review log had no review entry. **[Fixed]** (this entry)
- Code review 1 and 4. P6 (6.5% printed in #56 and #149) and P1 (41 printed in #8 and "up 41%" in
  #9, inside the ±0.412 band) are tagged steps 2 / table. By P3's reclassification they would
  be printed one-step lookups. **[Verified, no fix needed]** The allocation defines "steps 2, no
  calculate" for a two-period change as a fact-tool shortcut or a printed change (Context). P1,
  P2, P4, P5 and P6 are all allocated that way. P3 moved to steps 1 because comparable sales
  change is one printed metric, not a change between two read periods. P1's printed 41 was
  already recorded as inside the band (slot notes). Raised for the user's wording review.
- Code review 2. P6 has no gold row for prose #56. **[Verified, no fix needed]** Gold rows anchor
  derivation input parts, and #56 shows neither input (`check_questions` rejects a row whose
  anchor doesn't show its part). The printed answer is already in gold chunk #149.
- Code review 3 and 6. P7's lower band edge. The exact 3.4527 is 0.0027 inside [3.45, 3.55], not
  0.047; a two-decimal "3.45" passes only at the inclusive edge. **[Fixed]** The slot note is
  corrected. Expected stays 3.5, the calculate tool's own 1-decimal result (the convention),
  and the gate reports no tolerance needed.
- Code review 5. P3's "fiscal 2026" is Target's start-year name, where the project's end-year
  label would be FY2027 Q2, yet its trap is none. **[Verified, no fix needed]** The question
  uses the filing's own naming and states the date ("the three months ended August 1, 2026"),
  so it's unambiguous. A fiscal-label tag would change the allocation's trap counts. Target's
  naming is build 5's `period_labels` item.
- Code review 8. P6's FY2025 comparative row for `sales-fy2023` came after the `sales-fy2022`
  rows. **[Fixed]** Regrouped by part, rows 73–77.
- Code review 9. P4 is steps 2, though its derivation has three operations. **[Verified, no fix
  needed]** The allocation gives P4 steps 2 with the `get_multi_year_average` shortcut, the
  same shortcut basis as P1/P2/P5.

Fixes change only plan wording and gold row order, with no content change, so they're nits and
open no round 2. The gate re-run after the fixes still exits 0: 39 questions, 0 errors, 1 WARN
(P5's known false positive). **Review closed: 1 round, 4 fixed, 6 verified no fix, 0 deferred,
0 disputed.**
