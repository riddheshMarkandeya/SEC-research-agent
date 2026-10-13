# Phase 2 build 4, batch 2: extraction + period-named ambiguous questions

## Context

BACKLOG line 61, "Phase 2 build 4: write the v2 questions". The suite allocation is in
`docs/plans/2026-10-12-phase2-build4-v2-questions.md` (§ Suite allocation). Batch 1 (11
judge-graded questions) was committed at `48ef952` on branch `phase2-build4-v2-questions`.
Batch 2 = slots E1–E7 (extraction) and A4–A6 (ambiguous, answered with the period named): 10
questions. The allocation left two forks open for this batch's plan. The user chose the
recommended answer for both on 2026-10-13:

- **Fork 1, period check on A4–A6: no code change.** `_grade_by_type`
  (`src/sec_agent/eval/eval_harness.py`) already grades a `numeric` question that also
  carries `accepted`: the value must match, then one `accepted` variant must appear
  (`grading.text_matches`, which normalizes dates to ISO). Build 3a built it for these slots;
  the map says "graded `numeric` plus the `text` matcher on the period". The checker doesn't
  anchor the `accepted` variants. That stays: variants like "Q2 2026" are deliberately not the
  filing's wording, and the value's gold row already pins the filing (`report_date`). The
  variants go in the as-printed table instead (step 5).
- **Fork 2, E7 (XBRL-only pre-FY2024 figure): a new optional `xbrl_source` field** on a
  numeric question. The checker verifies the figure against companyfacts instead of a chunk
  anchor. No gold row, so retrieval replay skips it (`retrieval_replay.py` already skips
  questions without gold). Rejected: an XBRL form of gold row (replay reads every gold row and
  would need changing too) and swapping E7 for an in-corpus figure (drops the fact-tool-reach
  half of the pre-FY2024 pair the map asks for).
- **Batch 1's review record is open:** its Review log says "Not started" and
  `docs/reviews/2026-10-12-phase2-build4-batch1.md` was never written. This batch's review
  covers batch 1's code too (one review file for both).

**Constraints (unchanged from batch 1's plan).** Draft from the chunk files and filings, never
through the agent. Every number at the scale and decimals the filing prints. No agent run on a
draft question. No judge calls in this batch (no judged/refusal/clarify questions), so no
Gemini quota is spent. v1 files untouched.

`src/sec_agent/eval/questions.py` is in the critical core (`plan-review-blast-radius.md`
`paths:` → 90% diff-coverage bar).

## Decision / Design

### `xbrl_source` (schema: `src/sec_agent/eval/questions.py`)

```json
"xbrl_source": {"tag": "us-gaap:OperatingIncomeLoss", "accession": "0000018230-21-000063",
                "start": "2020-01-01", "end": "2020-12-31"}
```
- Object, closed: `tag` (required, `pattern` `^[\w-]+:\w+$`), `accession` (required),
  `end` (required, `pattern` `^\d{4}-\d{2}-\d{2}$`), `start` (optional, same pattern; absent
  for an instant fact). `format` isn't enforced by the validator, hence `pattern`.
- Numeric only: add to `_TYPE_ONLY_FIELDS`.
- Not with `derivation` (a derived value has anchored inputs instead) and not with
  `expected_unit: percent` (XBRL stores ratios as fractions). Both are Python checks beside
  `_check_type_only_fields`, naming `$.xbrl_source`, per the module's convention that schema
  combinator errors don't name the field.
- Comment on the field: the figure is in XBRL only (no ingested chunk prints it), so the
  checker verifies it against companyfacts and it has no gold rows.
- Harness grading is unchanged: the fact tool's result is a source, so `grade_numeric`'s
  citation check should work as for XBRL-answered v1 questions (verified in step 2).
- E7's `answer_source: "table"` describes the filing (an income-statement figure), not the
  retrieval path: the agent can reach it only through the fact tool.

### Checker (`src/sec_agent/devtools/check_questions.py`)

- `_part_list`: a numeric question with `xbrl_source` has no anchored part (returns `[]`), so
  `check_anchors` errors on any gold row given to it and `check_xbrl` skips it.
- New `check_xbrl_source` (check 9, added to `CHECKS` and the module docstring's list and
  authoring checklist):
  - company = `single_ticker(question)`; None (a multi-company question) → ERROR;
  - facts unreadable (`ctx.facts` returns a string) → **ERROR** (unlike check 3's WARN: this is
    the figure's only verification, so the gate can't pass unverified);
  - no fact in `accession` with that `taxonomy:tag`, `end`, and `start` (or, with no `start`,
    a fact that has none) → ERROR naming them;
  - a fact whose unit's category differs from `expected_unit`'s (USD vs shares, via
    `normalize`) doesn't count as a match;
  - a fact found but no value within printed precision of `expected_value` → ERROR listing the
    values found;
  - match → INFO with the fact (as check 3 prints it);
  - the figure printed in any of the company's own chunks (`figure_matches`) → WARN: an
    ingested anchor exists, so it isn't XBRL-only; give it a gold row instead.
- Reuse: extract the printed-precision arithmetic from `_xbrl_matches` into one helper both
  call; reuse `_iter_facts`/`ctx.facts` indexing by accession and
  `retrieval_replay.figure_matches`.

### Batch 2 slots (as planned; the shipped ids and figures are in the as-printed table)

| Slot | Id (draft) | Figure | Filing | Notes |
|---|---|---|---|---|
| E1 | `v2-jpm-cet1-2025` | Firm CET1 ratio, Standardized, 2025-12-31 | JPM FY2025 10-K | gap (not in XBRL). Several CET1 tables (Standardized/Advanced, firm/bank subsidiaries): the question names Standardized and the firm; the other columns' values are traps only if check 7 stays quiet |
| E2 | `v2-bac-…` | a FY2025 table item (e.g. net interest income or total deposits) | BAC FY2025 10-K | picked in step 2 |
| E3 | `v2-tgt-…-fy2024` | a Target fiscal 2024 income-statement item (not net sales: A6 uses it) | TGT FY2024 10-K `0000027419-25-000018` | fiscal-label: Target's "fiscal 2024" ends 2025-02-01 |
| E4 | `v2-wmt-revenue-fy2026` | total revenues, fiscal 2026 (ended 2026-01-31) | WMT 10-K `0000104169-26-000055` | fiscal-label: Walmart names the year it ends in |
| E5 | `v2-xom-production-2025` | oil-equivalent production 2025: 4,736 thousand oil-equivalent barrels daily | XOM FY2025 10-K `0000034088-26-000045` | gap. Unit check: the claim enum must hold a fitting unit; if it has none, swap the figure (step 2) |
| E6 | `v2-jnj-…-2025` | a FY2025 segment sales figure (e.g. Innovative Medicine) | JNJ FY2025 10-K | |
| E7 | `v2-cat-operating-profit-2020` | operating profit 2020: $4,553 million | CAT FY2020 10-K `0000018230-21-000063` (XBRL only) | `xbrl_source` `us-gaap:OperatingIncomeLoss`. Confirmed 2026-10-13: "4,553" is in none of CAT's 10 ingested filings. Not CAT revenue: its tag is a build 5 fix |
| A4 | `v2-jnj-cash-latest` | cash and cash equivalents: $20,422 million at 2026-06-28 | JNJ 10-Q `0000200406-26-000153` | no period given → latest; `accepted` names the period. Re-anchor when JNJ's Q3 2026 10-Q is ingested |
| A5 | `v2-xom-net-income-last-quarter` | net income attributable to ExxonMobil, Q2 2026 | XOM 10-Q `0000034088-26-000093` | relative time ("last quarter"), read as the latest reported quarter: Q3 2026 has ended but isn't filed, so an answer saying so and giving Q2 2026 passes; one that only refuses fails the numeric grade (the user confirms this reading at batch review). `accepted` names Q2 2026. Re-anchor when XOM's Q3 2026 10-Q is ingested. XOM companyfacts lags this 10-Q, so no XBRL INFO is expected |
| A6 | `v2-tgt-net-sales-2025` | net sales, fiscal 2025 (ended 2026-01-31) | TGT FY2025 10-K `0000027419-26-000016` | calendar vs fiscal; the fiscal reading is the default; `accepted` = "fiscal 2025" variants and the year-end date |

Rules for all ten: the five v2 tags per the allocation table; `forbidden_values` only where a
fiscal-label or look-alike value would be a real wrong answer **and** check 7 doesn't warn (an
income statement's comparative column sits beside the answer, so most fiscal-label traps go in
the question wording, not `forbidden_values`); ids prefixed `v2-`.

**Staleness of "latest" questions (A3 from batch 1, A4, A5).** The Q3 2026 10-Qs (JNJ, XOM,
BAC) are due from late October, likely before the v2 baseline. After that ingest a correct
"latest" answer fails while check 1 still finds the old anchor. Rather than a checker rule
that would need a "latest" marker on the question, add a BACKLOG item triggered by the next
ingest: re-anchor A3/A4/A5 (new figure, `accepted`, gold rows) and re-run the gate. The ingest
is a manual user step, so the trigger is visible. The allocation table's E7, A4–A6 rows lose
their "(open)" marks and get their question ids.

## Out of scope

Any agent or judge run; build 5's fact-tool fixes; checker anchoring of `accepted` variants on
numeric questions; batches 3–6.

## Files and steps

1. Save this plan with its `PROJECT_INDEX.md` line. Same branch.
2. Corpus read (read-only): pin every figure in the slot table to a verbatim chunk anchor,
   choose E2/E3/E6's figures, confirm E5's unit is in `CLAIM_UNITS`, and confirm E7's
   fact-tool reach: `xbrl_facts.get_metric("CAT", "operating_income", fiscal_year=2020)`
   returns 4,553M (a live SEC call, no Gemini quota). If it doesn't, E7 stays (it measures
   reach, and build 5 runs before the baseline) and the result is recorded on build 5's
   BACKLOG item. Also find a v1 question answered from a fact-tool source that passed in the
   latest stored eval report, as evidence that `grade_numeric`'s citation check accepts a
   "$4,553 million [n]" claim against a raw-dollar fact result; if none exists, check
   `_iter_citation_claims` on a hand-built fact result offline.
3. Schema + checker (TDD, red first): schema tests for `xbrl_source` (accepted on numeric;
   rejected on another type, with `derivation`, with an unknown key, without `end`, with a
   malformed `tag`/`end`/`start`, with `expected_unit: percent`, each naming
   `$.xbrl_source`); checker tests (match → INFO; wrong value, no fact, instant vs duration,
   other unit category, unreadable facts, multi-ticker, a gold row → ERROR; printed in an own
   chunk → WARN), via the `fetch_facts` injection.
4. Draft the 10 questions into `eval/eval_questions_v2.jsonl`, anchors into
   `eval/retrieval_gold_v2.jsonl`.
5. As-printed table (below), then the `accepted` seam: `grading.text_matches` on 3–4
   hand-written phrasings per A4–A6 question, widening `accepted` until right-period
   phrasings pass and the wrong one doesn't.
6. Gate: `check_questions` on all 21 v2 questions; exit 0; read every WARN/INFO line.
7. `ruff check .`, `pyright .`, `pytest --cov=. --cov-report=term-missing -q`; diff coverage:
   `questions.py` 90%, `check_questions.py` 80%.
8. Review (`independent-review-pass`) over `18e9ec0..HEAD` plus the working tree, then the
   user reviews batch 2's wording and traps (and batch 1's). Write
   `docs/reviews/2026-10-13-phase2-build4-batches1-2.md` with its index line; batch 1 plan's
   Review log gets a pointer line.
9. After approval: BACKLOG build 4 line → batches 1–2 done, next is batch 3 (N1–N10); add the
   re-anchor-on-next-ingest item (A3/A4/A5). Commit only when the user asks.

## Testing and verification

- `check_questions` exits 0 on all 21 v2 questions; E7 shows the INFO match line and no WARN.
- New schema and checker tests green; full suite, ruff, pyright clean; diff-coverage bars met.
- `eval/eval_questions.jsonl`, `eval/retrieval_gold.jsonl`, `eval_harness.py` and
  `retrieval_replay.py` have no diff.
- As-printed table complete for every number and period variant in batch 2.

## Plan review

Plan-reviewer (opus), 2026-10-13, 1 round. Each finding was folded in:

1. **Med.** A4/A5 (and batch 1's A3) go stale at the Q3 10-Q ingest, silently; A5's "last
   quarter" is arguable today. Re-anchor BACKLOG item on next ingest; A5 reading stated, user
   confirms at batch review. A checker rule was not added: it would need a "latest" marker.
2. **Med.** `accepted` lists untested. Step 5 now runs `text_matches` on hand-written
   phrasings, offline.
3. **Low-med.** `dependentSchemas` gives an unhelpful error. Python check naming the field.
4. **Low.** `xbrl_source` formats unenforced. `pattern`s plus rejection tests.
5. **Low.** Check semantics undefined (company, instant facts, percent, unit category).
   Defined, each with a test.
6. **Low.** E7 fact-tool lookup is a live SEC call, not cached. Reworded.
7. **Low.** E7's `answer_source` ambiguous. Stated.
8. **Low.** Review range wording. Now `18e9ec0..HEAD`.
9. **Low.** Harness citation check on a fact-tool claim unverified. Step 2 verifies it.

Confirmed fine by the reviewer: E7's XBRL fact and its absence from the ingested chunks;
`_part_list` returning `[]`; replay counting no-gold questions as drops; fork 1's grading path;
fiscal year-end dates.

## As-printed table

Every number and period variant in batch 2, beside the filing text it comes from (checked by
hand against the chunk files, 2026-10-13). No batch 2 question has `forbidden_values` or a
number in `criteria`: each candidate trap (JPM Advanced CET1 14.1%, TGT fiscal 2023
operating income $5,707, TGT fiscal 2024 net sales $106,566, XOM six-month net income $18,708) is
printed in the answer's own gold chunk, so check 7 would warn; BAC's average deposits
($1,984,182) overlaps the answer's grading band.

| Question | Field | Value | Printed as (filing, chunk) |
|---|---|---|---|
| `v2-jpm-cet1-2025` | `expected_value` | 14.6 percent | "CET1 capital ratio \| 14.6% \| (c) \| 15.7%", Standardized December 31, 2025 column (JPM 10-K `0001628280-26-008131` #182) |
| `v2-bac-total-deposits-2025` | `expected_value` | 2,018,729 million | "Total deposits \| 2,018,729 \| 1,965,467", "Balance sheet at year end" (BAC 10-K `0000070858-26-000157` #87; same line #238) |
| `v2-tgt-operating-income-fy2024` | `expected_value` | 5,566 million | "Operating income \| 5,566 \| 5,707 \| 3,848", columns 2024/2023/2022 (TGT 10-K `0000027419-25-000018` #84; with `$` in #56, #116); "Operating income \| 5,117 \| 5,566 \| 5,707" (FY2025 10-K `0000027419-26-000016` #90, comparative) |
| `v2-wmt-total-revenues-fy2026` | `expected_value` | 713,163 million | "Total revenues \| 713,163 \| 680,985 \| 648,125", "Fiscal Years Ended January 31, … 2026" (WMT 10-K `0000104169-26-000055` #117) |
| `v2-xom-production-2025` | `expected_value` | 4,736 thousand | "Oil-equivalent production(1)(thousands of oil-equivalent barrels daily) \| 4,736 \| 4,333 \| 3,738" (XOM 10-K `0000034088-26-000045` #88; also #33, #56). Prose: "2025 production of 4.7 million oil-equivalent barrels per day", within the 1% band |
| `v2-jnj-innovative-medicine-sales-2025` | `expected_value` | 60,401 million | "Total Innovative Medicine Sales \| $60,401 \| 56,964" (JNJ 10-K `0000200406-26-000016` #59); segment table #69 "Innovative Medicine \| $22,266 \| 18,919 \| 60,401 \| 56,964" |
| `v2-cat-operating-profit-2020` | `expected_value` | 4,553 million | XBRL only: `us-gaap:OperatingIncomeLoss` = 4553000000 USD, 2020-01-01..2020-12-31, accession `0000018230-21-000063` (FY2020 10-K), companyfacts. Printed in that 10-K (`cat-20201231.htm`, fetched from EDGAR 2026-10-13) as "Operating profit 4,553 8,290 8,293" (2020/2019/2018, in millions); in none of CAT's ingested filings (check 9: no WARN) |
| `v2-jnj-cash-latest` | `expected_value` | 20,422 million | "Cash and cash equivalents (Note 4) \| $20,422 \| 19,709", columns "June 28, 2026 \| December 28, 2025" (JNJ 10-Q `0000200406-26-000153` #9) |
| | `accepted` | June 28, 2026 | the balance-sheet column header |
| | `accepted` | second quarter of 2026 / Q2 2026 / second fiscal quarter of 2026 | not the filing's wording: the 10-Q is for the fiscal second quarter ended June 28, 2026 (`reportDate` 2026-06-28) |
| `v2-xom-net-income-last-quarter` | `expected_value` | 14,525 million | "Net income (loss) attributable to ExxonMobil \| 14,525 \| 7,082 \| 18,708 \| 14,795", columns three months 2026/2025, six months 2026/2025 ended June 30 (XOM 10-Q `0000034088-26-000093` #3) |
| | `accepted` | June 30, 2026 | "Three Months Ended June 30, … 2026" header |
| | `accepted` | second quarter of 2026 / Q2 2026 / 2Q 2026 / 2Q26 / second quarter 2026 | not the filing's wording: the quarter ended June 30, 2026 |
| `v2-tgt-net-sales-2025` | `expected_value` | 104,780 million | "Net sales \| $104,780 \| $106,566 \| $107,412", columns 2025/2024/2023 (TGT 10-K `0000027419-26-000016` #90; also #62, #94) |
| | `accepted` | fiscal 2025 / fiscal year 2025 / 2025 fiscal year / FY2025 / FY 2025 | Target labels the year ended January 31, 2026 "2025" |
| | `accepted` | January 31, 2026 | the fiscal year's end (`reportDate` 2026-01-31) |

**`accepted` seam** (`grading.text_matches`, offline, 2026-10-13). `ok` = the result matches
the intent.

| Question | Phrasing | Intent | Matched |
|---|---|---|---|
| A4 | "As of June 28, 2026, … $20,422 million" | right | yes |
| A4 | "… at the end of the second quarter of 2026" | right | yes |
| A4 | "At the end of Q2 2026 (quarter ended 2026-06-28) …" | right | yes |
| A4 | "… as of 06/28/2026" | right | yes |
| A4 | "… (fiscal second quarter of 2026) …" | right | yes |
| A4 | "As of December 28, 2025, … $19,709 million" | wrong period | no |
| A4 | "J&J had $20,422 million …" (no period) | wrong (period unnamed) | no |
| A5 | "… for the second quarter of 2026 was $14,525 million" | right | yes |
| A5 | "In Q2 2026 (three months ended June 30, 2026) …" | right | yes |
| A5 | "The third quarter of 2026 hasn't been reported yet; the latest is 2Q 2026 …" | right | yes |
| A5 | "For the quarter ended June 30, 2026 …" | right | yes |
| A5 | "… in the second quarter 2026 …" | right | yes |
| A5 | "… for the first quarter of 2026 was $4,183 million" | wrong period | no |
| A5 | "… net income last quarter was $14,525 million" (no period) | wrong (period unnamed) | no |
| A6 | "… for fiscal 2025 …" | right | yes |
| A6 | "In fiscal year 2025 (ended January 31, 2026) …" | right | yes |
| A6 | "For the 2025 fiscal year …" | right | yes |
| A6 | "For the fiscal year ended January 31, 2026 …" | right | yes |
| A6 | "Target's FY2025 net sales …" | right | no at first; yes after adding `FY2025`/`FY 2025` |
| A6 | "Target's FY 2025 net sales …" | right | yes (after widening) |
| A6 | "… for fiscal 2024 were $106,566 million" | wrong period | no |
| A6 | "Target's net sales in 2025 were $104,780 million" (fiscal not named) | wrong (period unnamed) | no |

## Review log

The full findings and their dispositions are in
`docs/reviews/2026-10-13-phase2-build4-batches1-2.md`. This review covers
batches 1 and 2 (`18e9ec0..HEAD` plus the working tree) and was classified
Substantial.

- Round 1: `/code-review` high, `arch-reviewer` (sonnet), `security-reviewer`
  and `/simplify`. Code review found 9 issues: 7 fixed, 1 deferred to
  BACKLOG (`--gold` default), and 1 fixed after the user approved it (R8's
  criterion reworded, with a new judge sanity case; its live re-run is
  owed). The
  arch reviewer found 1 bug, fixed, and its nits were dispositioned.
  Security found nothing. `/simplify` edits were applied, and its skipped
  findings are noted with reasons.
- Round 2 (delta `a3d51db`): `/code-review` low and `security-reviewer`.
  1 issue fixed: the WARN listed facts from the source filing itself. The unit
  filter was re-raised but had already been dropped on purpose. Security found
  nothing.
- Round 3 (the one-line fix): `/code-review` low plus a security check. No
  findings, so the review is closed. After the fix the full suite passes 1659
  tests, `questions.py` and `check_questions.py` are both at 100% coverage,
  ruff and pyright are clean, and the gate reports 21 questions with 0 errors
  and 0 warnings.

## Addendum

**2026-10-13, execution.**
- Steps 1–7 ran as planned. Gate: 21 questions, 0 errors, 0 warnings; E7 shows its INFO line
  (`us-gaap:OperatingIncomeLoss = 4553000000 USD (2020-01-01..2020-12-31, 10-K)`) and no WARN.
  Expected "no XBRL fact matched" INFO lines: E5 (production), E6 (segment sales are
  dimensioned, which companyfacts drops), A5 (XOM companyfacts lag). E1 is a percentage, so
  check 3 skips it. Full suite 1659 passed (1636 + 23 new); ruff and pyright clean;
  `questions.py` and `check_questions.py` 100% covered.
- Slot picks: E2 = BAC total deposits at year end; E3 = TGT fiscal 2024 net earnings; E6 = JNJ
  Innovative Medicine sales.
- E7 fact-tool reach (live SEC call, no Gemini): `get_metric("CAT", "operating_income",
  fiscal_year=2020)` returns 4,553,000,000 USD, but from accession `0000018230-23-000011` (the
  FY2022 10-K's comparative column), not the FY2020 10-K. Same value, so nothing to record on
  build 5's item. The question's `xbrl_source` names the FY2020 10-K's own fact.
- Harness citation check on a fact-tool claim: the stored reports don't keep tool results, so
  it was checked offline instead. `fact_as_result` gives the text
  `operating_income = 4553000000 USD (structured XBRL data, not filing prose)`.
  `grade_numeric` passes "$4,553 million [1]" and "$4.553 billion [1]" against it. It fails the
  same claim cited to a source without the figure (citation unsupported).
- **Unit category, deviation from the design wording.** `normalize` has two categories,
  percent and scale, so it can't tell USD from shares. Check 9 maps a companyfacts unit to
  `normalize`'s categories: `pure` (ratios, stored as fractions) is percent, everything else
  scale. A percent `expected_unit` is already rejected by the schema, so in practice a `pure`
  fact never matches. USD vs shares is not distinguished. The tag and period pin the fact, so
  a same-valued fact in another unit under the same tag and period isn't a real risk.
- Check 9's period match is exact on both `start` and `end`. A gold row given to an XBRL-only
  question is an error: "an XBRL-only figure takes no gold rows" (reworded at `/simplify`).
- The `accepted` seam widened A6 with `FY2025` / `FY 2025`. An answer that names no period
  fails A4–A6 by design (the category's point). For A6 that includes a plain "in 2025", which
  is for the user to confirm at batch review, along with A5's reading.

**2026-10-13, user decisions at batch review.**
- A5 stays as written: "last quarter" means the latest reported quarter (Q2 2026), and an
  answer that only says Q3 isn't filed yet fails the numeric grade. Rewording it, or moving it
  to judge grading, was rejected: the eval runs will show whether this is too strict, rather than
  guessing ahead of them.
- R8's (`v2-cat-backlog-2020`) criterion was reworded so it no longer contradicts E7's 2020 XBRL
  figure. The judge sanity script gained a matching PASS case, and its live re-run is owed.
