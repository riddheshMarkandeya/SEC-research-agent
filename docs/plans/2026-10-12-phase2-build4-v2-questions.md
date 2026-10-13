# Phase 2 build 4, batch 1: suite allocation + judge-graded questions

## Context

BACKLOG line 61, "Phase 2 build 4: write the v2 questions" (about 56 questions in 7 categories).
The frozen map (`docs/plans/2026-10-07-data-expansion-phase2-map.md`) sets the mix and the
authoring process. Build 3b (committed `9d97184`) provides the gate:
`check_questions` must pass on every batch before the user reviews it. Build 4 spans sessions,
so this plan does three things. It fixes the suite allocation, so later batches fill set slots.
It plans batch 1 in full. It lists the later batches; each gets its own short plan.

**User decisions (this session):**
- Batch 1 = the judge-graded questions: the refusal/trap category plus the `clarify` questions
  of the ambiguous category. The judge sanity pass runs on this batch's own questions.
- v2 gold anchors go in a **separate file**, `eval/retrieval_gold_v2.jsonl`. This revisits
  build 3b's plan (check 8 assumed one shared gold file). What changed:
  `retrieval_replay.check_base` refuses a `--compare` base whose gold hash differs, so
  appending v2 rows would invalidate every v1 replay base (630/981). The id-collision check
  stays; it's harmless.
- Worktree: keep this one. Build 4 gets its own branch, cut here from `9d97184`. Build 3b is
  still unmerged, so merging build 4 later brings it along, unless the user merges 3b first.

**Constraints.**
- Draft from the chunk files (`C:/riddhesh/projects/SEC research agent/var/chunks/<TICKER>/`)
  and the filings, never through the agent's tools. The agent never runs on a draft question.
- **Every number is entered at the scale and decimals the filing prints.** This covers
  `expected_value`, derivation inputs and `forbidden_values`. If the filing prints "$1.2
  billion", enter 1.2 billion, not 1,200 million. The rounding spread trusts the authored
  precision, and no code checks it, so step 5 checks it by hand.
- Gemini quota: the judge sanity pass is the only live step, about 10–20 judge calls. First
  check `eval/eval_results/` for reports since the last reset (`live-eval-verification.md`).
- Changing a judge template is a fingerprinted prompt change and is out of scope here (below).

## Design

### Suite allocation (`docs/plans/2026-10-12-phase2-build4-v2-questions.md`)

The repo plan holds a table with one row per slot (about 56):
- slot id
- category
- grading `type`
- trap
- companies
- `steps` and `needs_calculate`
- `answer_source`
- batch number

It's built from the map's mix:
- **Categories:** extraction 7, numerical reasoning 10 (about 4 compound), cross-period 8,
  cross-company 9, text/footnote 8, refusal/trap 8, ambiguous about 6.
- **Companies:** tech 5 (3 cross-company, 2 hard single-company). Each of the 7 new companies
  gets 5–7.
- **Cross-company:** 2 JPM/BAC, 2 TGT/WMT, 3 cross-sector (at least 2 tech vs a new company),
  2 rank-of-3+.
- **Fiscal-label:** 3–4 questions (TGT, WMT, JNJ).
- **No-data gaps:** about 6–8 questions where XBRL lacks the figure but the filing text has it.
- **Calculator:** about 8 `needs_calculate`.
- **Judged:** at most about 3 `judged`.
- **No-data refusals:** the pre-FY2024 pair, plus a "filed but not ingested" question if one
  exists. XOM's 2026-08-03 10-Q is checked against `var/chunks/XOM`.

Batch order after batch 1: by category, with the user re-confirming each batch's plan.

### Batch 1 contents (about 12 questions)

Ids are prefixed `v2-`, so they can't collide with v1's.

| Slot | Type / kind | Trap | Notes |
|---|---|---|---|
| out-of-corpus | refusal / `not_covered` | out-of-corpus | an uncovered ticker (allowed by check 5) |
| future period ×2 | refusal / `not_yet_filed` | future-period | periods ending at least a year from now (a 2028 quarter; fiscal 2028), so they can't be filed or ingested before the v2 baseline. Each has an expiry date in the allocation table |
| never disclosed ×2 | refusal / `never_disclosed` | not-disclosed | plausible for the sector; `absence_terms` with spelling variants. Also absent from the company's companyfacts tags, so no fact tool returns it |
| false premise | refusal / `false_premise` | false-premise | `criteria` names the premise and the correct figure; gold rows anchor that figure |
| look-alike swap | refusal / `false_premise` | look-alike | e.g. BAC's segment name asked of JPM. **No `forbidden_values`**: attribution follows the cited source's ticker, so a correct answer that cites BAC's figure while explaining the swap would fail. `criteria` covers the swap |
| pre-FY2024, text-only | refusal / `not_covered` | none | a pre-FY2024 figure that only the filing text held, never XBRL. The agent's fact tools must not return it (checked in step 2) |
| filed, not ingested | refusal / `not_covered` | none | only if step 2 finds one (e.g. XOM's 2026-08-03 10-Q); otherwise "none exists" goes in the allocation table |
| clarify ×3 | clarify | none | margin variant, segment vs geography, and no period on a flow item; `readings` ≥ 2, anchored per reading |

Every question carries the five v2 tags. The questions skew to the 7 new companies.

**Moved out of batch 1: the answerable pre-FY2024 twin.** An XBRL-only figure has no verbatim
anchor in an ingested chunk: only FY2024+ filings are ingested. Its `value` part would have no
gold rows, so the gate errors. The map wants this half to measure the fact tools' reach. So it
needs an XBRL-sourced gold form, which is a checker/schema design fork. That fork goes in the
allocation table as an open slot, decided in its batch's plan.

**Trap and premise figures.** No gold rows for trap values: replay would score the distractor
chunk as a hit. Their anchors go in the as-printed table only, as do numbers written inside
`criteria` prose.

### Checker change: gold rows on refusal and clarify questions

Today `_part_list` (`src/sec_agent/devtools/check_questions.py:167`) returns `[]` for these
types, so any gold row on them is an "unexpected part" error. The false premise's correct
figure and the clarify readings then couldn't be anchored, either for the user's spot-check or
for retrieval replay.

Change: treat `refusal` and `clarify` like `judged`. Return `None`, so their hand-labelled
rows get the chunk-match check only. Gold rows stay optional for them: a pure refusal has
nothing to anchor.

What that skips, for the record: the "anchor shows the figure" check, the own-company check and
the XBRL INFO line. These figures are checked by step 5's as-printed table and the user's
spot-check instead.

Tests:
- Replace `test_a_refusal_has_no_gold_parts` (`tests/devtools/test_check_questions.py:422`),
  which asserts the old behaviour.
- Add red tests: a refusal and a clarify question, each with a hand-labelled row, pass.

Docs: update the `_part_list` docstring, and `check_id_collision`'s docstring and message
(`check_questions.py:545-549`), which say gold rows are shared between the files.

### Judge sanity pass: `tests/manual/verify_v2_judge_templates.py`

This follows `tests/manual/verify_pltr_dividend_criteria.py`.
- **Cases.** For each of the 5 templates (4 refusal kinds + clarify), the script picks one
  batch-1 question. It sends hand-written answers through
  `eval_harness.grade_judged(q["question"], answer, grading.judge_criteria_for(q))`, written in
  the agent's real style (`[n]` markers):
  - `not_covered`, `not_yet_filed`, `never_disclosed`:
    - known-good, expected PASS;
    - a refusal giving another kind's reason, expected FAIL.
  - `false_premise` has no wrong-reason clause, so its bad case is an answer that accepts the
    premise, expected FAIL.
  - clarify:
    - an answer that asks which reading is meant, expected PASS;
    - an answer that gives every reading, labelled, expected PASS;
    - an answer that gives one reading unlabelled, expected FAIL.
  - Negative controls on each refusal template, expected FAIL: the agent's canned citation-gate
    refusal text and its turns-exhausted text, loaded from stored reports as in
    `verify_pltr_dividend_criteria.py`.
- **Runs.** Each case runs twice (stability), about 26 calls. Print
  `config.GEMINI_MODEL_NAME`.
- **Inputs and output.** It reads the v2 file. Exit 1 on any unexpected verdict, printing the
  judge's reason.
- **On a misjudgement.** Stop. The batch's questions don't count until the template is fixed
  under its own plan: a prompt change, fingerprinted, v2 first. Record the misjudgement as a
  BACKLOG item and tell the user.
- **Coverage.** The script is a manual repro and isn't measured by coverage.

## Steps

1. `git checkout -b phase2-build4-v2-questions` (from `9d97184`). Copy this plan to
   `docs/plans/2026-10-12-phase2-build4-v2-questions.md` and add its `PROJECT_INDEX.md` line.
2. Read the corpus for slot facts:
   - each company's latest filing and report date (from chunk metadata);
   - whether XOM's 2026-08-03 10-Q is ingested;
   - candidate never-disclosed metrics: absent from the chunk text **and** from the company's
     companyfacts tags (XBRL cache);
   - BAC/JPM segment names;
   - a pre-FY2024 text-only figure that the agent's mapped fact tools don't return.

   Then write the allocation table into the repo plan, with an expiry date on each
   time-sensitive question.
3. Checker change (TDD): red tests, then make `_part_list` return `None` for
   refusal/clarify, then green.
4. Draft batch 1 into `eval/eval_questions_v2.jsonl` and its anchors into
   `eval/retrieval_gold_v2.jsonl`. Each anchor is a short verbatim string from the chunk file.
5. **As-printed check (by hand, per number).** For every `expected_value`, derivation input,
   `forbidden_values` entry and number written in `criteria`, put its anchor text beside it and confirm the scale word and the
   decimal count match what's printed. Record it as a table in the repo plan's batch 1
   section.
6. Gate (from this worktree):
   ```
   PYTHONPATH=src python -m sec_agent.devtools.check_questions --questions eval/eval_questions_v2.jsonl --gold eval/retrieval_gold_v2.jsonl --chunks-dir "C:/riddhesh/projects/SEC research agent/var/chunks" --xbrl-cache-dir "C:/riddhesh/projects/SEC research agent/var/xbrl_cache"
   ```
   It must exit 0. Read every WARN and INFO line; the XBRL INFO lines are checked by eye.
7. Quota check, then `PYTHONPATH=src python tests/manual/verify_v2_judge_templates.py`. It
   must show all expected verdicts.
8. Run `ruff check .`, `pyright .` and `pytest --cov=. --cov-report=term-missing -q`, then check
   diff coverage of the checker change (80%).
9. Review:
   - `independent-review-pass` by the actual diff: code review of the checker change and the
     verify script; arch-reviewer on the docs and plan conformance.
   - Then the user reviews every question's wording and trap design, and spot-checks gold
     values (the map requires every false-premise and look-alike trap).
   - Write `docs/reviews/2026-10-12-phase2-build4-batch1.md` (Substantial), with its
     `PROJECT_INDEX.md` line (the pre-commit hook blocks without it).
10. After approval:
    - Update the BACKLOG build 4 line: batch 1 done, judge sanity pass done; next is batch 2.
    - Commit, only when the user asks.

## Verification

- `check_questions` exits 0 on the batch with both v2 files.
- The checker's unit tests are green, and the full suite, ruff and pyright are clean.
- The judge sanity script passes on all 5 templates × good/bad × 2 runs.
- The as-printed table is complete for every number in the batch.
- v1 is untouched: `eval/eval_questions.jsonl` and `eval/retrieval_gold.jsonl` have no diff.

## Out of scope

- Judge template wording changes. Found misjudgements become their own plan.
- Batches 2+: each gets its own plan.
- Build 5 (fact-tool fixes).
- Any agent run on v2 questions.
- An automatic as-printed check: it needs `figure_matches` to report scale, and the 3b review
  deferred that.

## Suite allocation

Written in step 2 (2026-10-12) from the chunk files and companyfacts. Later batches fill these
slots; a batch plan may swap a slot's company or metric but keeps the category, type and trap
counts, or says why not.

### Corpus facts behind it

- **Latest ingested filing per company** (chunk metadata `filingDate` / form / `reportDate`):
  AAPL 2026-07-31 10-Q 2026-06-27; BAC 2026-07-31 10-Q 2026-06-30; CAT 2026-08-05 10-Q
  2026-06-30; CRM 2026-08-27 10-Q 2026-07-31; JNJ 2026-07-23 10-Q 2026-06-28; JPM 2026-08-06
  10-Q 2026-06-30; MSFT 2026-07-29 10-K 2026-06-30; NVDA 2026-08-26 10-Q 2026-07-26; PLTR
  2026-08-04 10-Q 2026-06-30; TGT 2026-08-28 10-Q 2026-08-01; WMT 2026-08-28 10-Q 2026-07-31;
  XOM 2026-08-03 10-Q 2026-06-30.
- **Filed but not ingested: none exists.** XOM's 2026-08-03 10-Q is ingested
  (`0000034088-26-000093`). No company's latest 10-Q/10-K in companyfacts is newer than its
  ingested one, and the next filings (Q3 10-Qs, AAPL's FY2026 10-K) are due from late October.
  A later batch can add the slot if one is filed and not ingested before the v2 baseline.
- **XOM companyfacts lag:** freshly fetched today, XOM's companyfacts stops at the 2026-05-04
  10-Q. The XBRL INFO line can't confirm a figure from XOM's 2026-08-03 10-Q.
- **Never-disclosed candidates** (absent from every chunk of the company and from its
  companyfacts tag names): XOM breakeven oil price (`breakeven`, `break even`); BAC Net
  Promoter Score (`net promoter`, `promoter score`, `NPS`). Rejected: TGT sales per square foot
  (absent, but derivable from net sales and retail square feet, so a computed answer is
  defensible); Walmart+ member count (a term short enough to search, "Walmart+ members",
  substring-matches "Walmart+ membership").
- **Segment names:** BAC: Consumer Banking, Global Wealth & Investment Management (GWIM),
  Global Banking, Global Markets. JPM: Consumer & Community Banking, Commercial & Investment
  Bank, Asset & Wealth Management (AWM). CAT renamed Energy & Transportation to Power & Energy
  in its FY2025 10-K.
- **Pre-FY2024 text-only figure:** CAT's order backlog at the end of 2020. Backlog is in no
  companyfacts tag name, isn't a mapped fact-tool metric, and no ingested chunk gives a 2019–2021
  backlog figure (earliest: Q4 2023 in the 2024-03-31 10-Q).

### Arithmetic note (company cap)

The map's "7 new companies get about 5–6 each, at most 7" predates the ambiguous category
(about 50 → 56 questions). Of 56 slots, 9 are cross-company, 2 tech single-company and 1
out-of-corpus, leaving 44 single-company slots for the 7 new companies: 6–7 each, so the cap is
read per single-company slot. Cross-company appearances come on top (2–3 each). Raised for the
user at batch 1 review.

### Slots

Steps: 1 / 2 / 3 (3 = 3+). Calc = `needs_calculate`. Gap = XBRL lacks the figure, the text has
it. Types `numeric` / `comparison` / `text` / `judged` / `refusal` / `clarify`.

| Slot | Category | Type | Trap | Companies | Steps | Calc | Source | Gap | Batch | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| R1 | refusal-trap | refusal `not_covered` | out-of-corpus | COST | 1 | no | text | | 1 | `v2-cost-net-sales-fy2025` |
| R2 | refusal-trap | refusal `not_yet_filed` | future-period | WMT | 1 | no | text | | 1 | `v2-wmt-revenue-fy2029`; expires 2029-01-31 (fiscal 2029 ends) |
| R3 | refusal-trap | refusal `not_yet_filed` | future-period | JNJ | 1 | no | text | | 1 | `v2-jnj-sales-q2-2028`; expires 2028-07-02 (fiscal Q2 2028 ends) |
| R4 | refusal-trap | refusal `never_disclosed` | not-disclosed | XOM | 1 | no | text | | 1 | `v2-xom-breakeven-price` |
| R5 | refusal-trap | refusal `never_disclosed` | not-disclosed | BAC | 1 | no | text | | 1 | `v2-bac-net-promoter-score` |
| R6 | refusal-trap | refusal `false_premise` | false-premise | CAT | 1 | no | text | | 1 | `v2-cat-dividend-cut-2025` |
| R7 | refusal-trap | refusal `false_premise` | look-alike | JPM | 1 | no | table | | 1 | `v2-jpm-gwim-net-income-2025` |
| R8 | refusal-trap | refusal `not_covered` | none | CAT | 1 | no | text | | 1 | `v2-cat-backlog-2020`; pre-FY2024 text-only half of the pair |
| A1 | ambiguous | clarify | none | TGT | 1 | no | both | | 1 | `v2-tgt-margin-fy2025`; margin variant |
| A2 | ambiguous | clarify | none | CAT | 1 | no | table | | 1 | `v2-cat-largest-source-2025`; segment vs geography |
| A3 | ambiguous | clarify | none | BAC | 1 | no | text | | 1 | `v2-bac-net-income-no-period`; flow item, no period. Anchors pinned to the latest 10-K/10-Q; re-anchor when BAC's Q3 2026 10-Q is ingested |
| A4 | ambiguous | numeric + `accepted` period | none | JNJ | 1 | no | table | | 2 | `v2-jnj-cash-latest`; balance-sheet item, no period: answer the latest and name it. Re-anchor when JNJ's Q3 2026 10-Q is ingested |
| A5 | ambiguous | numeric + `accepted` period | none | XOM | 1 | no | table | | 2 | `v2-xom-net-income-last-quarter`; relative time ("last quarter"); re-anchor when XOM's Q3 2026 10-Q is ingested |
| A6 | ambiguous | numeric + `accepted` period | fiscal-label | TGT | 1 | no | table | | 2 | `v2-tgt-net-sales-2025`; calendar vs fiscal year; the fiscal reading is the default |
| E1 | extraction | numeric | none | JPM | 1 | no | table | yes | 2 | `v2-jpm-cet1-2025`; a regulatory ratio |
| E2 | extraction | numeric | none | BAC | 1 | no | table | | 2 | `v2-bac-total-deposits-2025` |
| E3 | extraction | numeric | fiscal-label | TGT | 1 | no | table | | 2 | `v2-tgt-operating-income-fy2024` |
| E4 | extraction | numeric | fiscal-label | WMT | 1 | no | table | | 2 | `v2-wmt-total-revenues-fy2026` |
| E5 | extraction | numeric | none | XOM | 1 | no | table | yes | 2 | `v2-xom-production-2025`; an operating figure |
| E6 | extraction | numeric | none | JNJ | 1 | no | table | | 2 | `v2-jnj-innovative-medicine-sales-2025` |
| E7 | extraction | numeric (`xbrl_source`) | none | CAT | 1 | no | table | | 2 | `v2-cat-operating-profit-2020`; pre-FY2024 answerable twin of R8: CAT 2020 operating profit, XBRL-only, checked against companyfacts, no gold rows |
| N1 | numerical-reasoning | numeric | none | JPM | 2 | yes | table | | 3 | |
| N2 | numerical-reasoning | numeric | none | JPM | 3 | yes | both | | 3 | compound; sector ratio (e.g. bank efficiency ratio) |
| N3 | numerical-reasoning | numeric | none | BAC | 2 | no | table | | 3 | |
| N4 | numerical-reasoning | numeric | none | TGT | 2 | yes | table | | 3 | |
| N5 | numerical-reasoning | numeric | none | WMT | 2 | no | table | | 3 | |
| N6 | numerical-reasoning | numeric | none | XOM | 3 | yes | both | yes | 3 | compound |
| N7 | numerical-reasoning | numeric | none | XOM | 2 | no | table | | 3 | |
| N8 | numerical-reasoning | numeric | none | JNJ | 3 | yes | table | yes | 3 | compound |
| N9 | numerical-reasoning | numeric | none | JNJ | 2 | no | table | | 3 | |
| N10 | numerical-reasoning | numeric | none | AAPL | 3 | yes | table | | 3 | compound; tech single-company (hard) |
| P1 | cross-period | numeric | none | JPM | 2 | no | table | | 4 | |
| P2 | cross-period | numeric | none | BAC | 2 | no | table | | 4 | |
| P3 | cross-period | numeric | none | TGT | 2 | no | text | yes | 4 | e.g. comparable sales change |
| P4 | cross-period | numeric | none | WMT | 2 | no | table | | 4 | |
| P5 | cross-period | numeric | fiscal-label | WMT | 2 | no | table | | 4 | |
| P6 | cross-period | numeric | fiscal-label | JNJ | 2 | no | table | | 4 | |
| P7 | cross-period | numeric | none | XOM | 2 | yes | table | | 4 | |
| P8 | cross-period | numeric | none | CAT | 2 | no | text | yes | 4 | e.g. backlog change |
| C1 | cross-company | comparison | look-alike | JPM, BAC | 2 | yes | table | | 5 | a gap between the two banks |
| C2 | cross-company | comparison | look-alike | JPM, BAC | 2 | no | table | | 5 | |
| C3 | cross-company | comparison | look-alike | TGT, WMT | 2 | yes | table | | 5 | |
| C4 | cross-company | comparison | fiscal-label | TGT, WMT | 2 | no | table | | 5 | opposite fiscal-year naming |
| C5 | cross-company | comparison | none | MSFT, XOM | 2 | no | table | | 5 | tech vs new |
| C6 | cross-company | comparison | none | NVDA, CAT | 2 | no | table | | 5 | tech vs new |
| C7 | cross-company | comparison | none | JNJ, XOM | 2 | no | table | | 5 | cross-sector, non-tech |
| C8 | cross-company | comparison | none | XOM, CAT, JNJ | 3 | no | table | | 5 | rank-of-3+ |
| C9 | cross-company | comparison | none | AAPL, MSFT, WMT | 3 | no | table | | 5 | rank-of-3+, tech |
| T1 | text-footnote | text | none | JPM | 1 | no | text | | 6 | |
| T2 | text-footnote | text | none | BAC | 1 | no | text | yes | 6 | |
| T3 | text-footnote | text | none | TGT | 1 | no | text | | 6 | |
| T4 | text-footnote | text | none | WMT | 1 | no | text | yes | 6 | |
| T5 | text-footnote | judged | none | XOM | 1 | no | text | | 6 | |
| T6 | text-footnote | judged | none | JNJ | 1 | no | text | | 6 | e.g. a litigation note |
| T7 | text-footnote | text | none | CAT | 1 | no | text | | 6 | |
| T8 | text-footnote | text | none | CRM | 1 | no | text | | 6 | tech single-company (hard) |

**Tallies.** Categories: refusal-trap 8, ambiguous 6, extraction 7, numerical reasoning 10 (4
compound), cross-period 8, cross-company 9, text/footnote 8 = 56. Single-company slots: JPM 6,
BAC 6, TGT 6, WMT 6, XOM 7, JNJ 7, CAT 6 (44), tech 2, COST 1. Cross-company appearances: JPM 2,
BAC 2, TGT 2, WMT 3, XOM 3, JNJ 2, CAT 2; tech 3 slots (C5, C6, C9), so tech 5 in all.
Fiscal-label 4 (E3, E4, P5, P6) plus A6 and C4. Gaps 8 (E1, E5, N6, N8, P3, P8, T2, T4). `needs_calculate` 9 (N1, N2, N4, N6, N8, N10, P7, C1, C3). `judged` 2.

**Batches.** 1: R1–R8, A1–A3 (11). 2: E1–E7, A4–A6 (10, two open forks). 3: N1–N10. 4:
P1–P8. 5: C1–C9. 6: T1–T8. Each later batch re-confirms its plan with the user.

### Batch 1 as-printed check (step 5)

Batch 1 has no `expected_value`, derivation or `forbidden_values`. Every number it states
is in `criteria` prose:

| Question | Number as written | Printed in the filing | Scale and decimals match |
|---|---|---|---|
| `v2-cat-dividend-cut-2025` | seven percent | "approved a seven percent increase in the quarterly dividend" (`0000018230-25-000040`) | yes, in words as printed |
| `v2-cat-dividend-cut-2025` | $1.51 per share | "to $1.51 per share" (same) | yes |
| `v2-jpm-gwim-net-income-2025` | $6,522 million | "6,522" in the AWM 2025 column, table headed "(in millions, except ratios)" (`0001628280-26-008131`) | yes, millions, no decimals |
| `v2-wmt-revenue-fy2029` | January 31, 2029 | not a filing figure: Walmart's fiscal year ends January 31 (fiscal 2026's 10-K `reportDate` is 2026-01-31) | n/a (a date) |

The clarify readings and the other refusals carry no numbers. Their gold anchors (TGT 27.9% /
4.9, CAT 32,201 / $36,609 million, BAC $30.5 billion / $9.1 billion) are verbatim chunk text
and aren't graded.

Gate (step 6), 2026-10-12: 11 questions checked, 0 errors, 0 warnings; exit 0. INFO lines:
both XOM absence terms and all three BAC absence terms are in none of the company's chunks (811
XOM chunks over 10 filings, 2,649 BAC chunks over 10 filings) and in no other company's. No XBRL
INFO lines: refusal and clarify gold rows get the chunk-match check only.

## Plan review

Plan-reviewer (opus), 1 round. Every finding was folded in:

1. **High.** The answerable pre-FY2024 twin has no ingested anchor, so the gate would fail.
   Moved out of batch 1 as an open slot needing an XBRL-gold design.
2. **Med-high.** `not_yet_filed` periods would go stale by November. Fixed: periods at least a
   year out, with expiry dates.
3. **Med.** `forbidden_values` with `ticker: BAC` on the look-alike refusal fails correct
   answers. Dropped; `criteria` covers the swap.
4. **Med.** `None` skips the figure, own-company and XBRL checks. Stated in the plan. No gold
   rows for trap values. `criteria` numbers join the as-printed table.
5. **Med.** The judge sanity design was thin. Added: the accepted-premise bad case, both clarify
   pass routes, the canned gate and turns-exhausted texts as negative controls, the agent-style
   `[n]` markers and the model name.
6. **Low-med.** The existing test asserts the old behaviour. It's replaced explicitly.
7. **Low.** The id-collision docstring and message say "shared". Updated.
8. **Low.** The review file had no index line, and the not-ingested slot wasn't placed. Both
   fixed.
9. **Low.** Never-disclosed candidates are also checked against companyfacts tags.

## Review log

This batch's code was reviewed together with batch 2's. See
`docs/reviews/2026-10-13-phase2-build4-batches1-2.md` and the Review log in
`docs/plans/2026-10-13-phase2-build4-batch2.md`.

## Addendum

**2026-10-12, execution.**
- Steps 1–6 and 8 ran as planned. Batch 1 is 11 questions, not about 12: no filed-but-not-ingested
  filing exists (see Suite allocation). Gate: 0 errors, 0 warnings. Full suite 1636 passed;
  ruff and pyright clean; `check_questions.py` 100% covered.
- `_part_list`'s `elif qtype == "text"` became `else`: with refusal and clarify returning early,
  its fall-through was unreachable and showed as a missed branch.
- The checker's usage example now passes `--gold eval/retrieval_gold_v2.jsonl`: the `--gold`
  default is still v1's file.
- The judge script added a case pair the plan didn't list: the look-alike question
  (`v2-jpm-gwim-net-income-2025`), whose own criteria are the most complex in the batch. A good
  answer and one reporting BAC's GWIM figure ($4,670 million, BAC FY2025 10-K) as JPM's. That
  makes 21 cases × 2 runs = 42 judge calls, not about 26.
- The worktree has no `.env`; the script ran with the main checkout's `.env` loaded into the
  process environment. Judge model: `gemini-3.5-flash-lite`. Quota: no eval report since
  today's reset in any checkout before the run.

**Judge sanity pass: 39/42 as expected. Stopped here, per the plan.** Each misjudgement hit 1 of
2 runs:

| Template | Question | Case | Expected | Got | Judge's reason (abridged) |
|---|---|---|---|---|---|
| `not_covered` | `v2-cost-net-sales-fy2025` | stored citation-gate refusal | FAIL | PASS (run 1) | "correctly refused … could not verify it from its sources rather than providing an estimate or a wrong reason" |
| `not_yet_filed` | `v2-wmt-revenue-fy2029` | good refusal | PASS | FAIL (run 2) | argues whether July 31, 2026 is after "the real current date (October 12, 2026)", concedes it isn't, then fails anyway |
| `clarify` | `v2-tgt-margin-fy2025` | both readings, labelled | PASS | FAIL (run 2) | "without … clearly labeling which figure belongs to which specific reading in a structured manner" |

Every other case matched in both runs: all three wrong-reason refusals, the accepted premise,
the look-alike swap, the unlabelled single reading and 7 of 8 negative controls failed; the
other good answers passed. BACKLOG item filed ("The v2 judge templates misjudged 3 of 42
sanity cases"). Batch 1's questions don't count until the templates are fixed under their own
plan and this script re-runs clean.

**2026-10-12, templates fixed.** The template wording and two batch 1 details (COST, CAT) were
reworded, and the script now runs 89 calls (10 per previously misjudged case, 5 per negative the
new wording could loosen, plus a new latest-10-Q-figure negative). Re-run: 89/89 as expected. After review fixes and more cases, run 2 gave 112/113: every
refusal case matched, but `clarify` "every reading labelled" failed 1 of 10. The clarify
example sentence was replaced, and a clarify-only run gave 32/32 (20/20 on that case). Batch 1
is unblocked. Record:
`docs/decisions/2026-10-12-v2-judge-template-wording.md`.
