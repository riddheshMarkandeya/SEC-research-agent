# XBRL tag check on the phase 2 shortlist

Date: 2026-10-08
Ticket: XBRL tag check on the shortlist (phase 2 map)
Feeds: Fact-tool adaptation policy; v2 question writing (which questions the fact tools answer, refuse or get wrong).

Method: R2 (`2026-10-07-sector-xbrl-reporting.md`) listed tags from `companyfacts`. This check ran the real lookup path instead: `xbrl_facts.get_metric`, `is_metric_tagged` and `_resolved_fiscal_year` for every `DEFAULT_METRIC_TAGS` metric on the 7 new tickers (JPM, BAC, TGT, WMT, XOM, JNJ, CAT). `load_companies` and `CACHE_DIR` were patched in memory (CIKs as in R2's Sources, XOM = 34088), so `companies.json` and the repo cache were untouched. SEC `companyconcept` and `submissions` only, no Gemini quota. Run on 2026-10-08 from a scratchpad script (not kept).

## 1. Findings first

1. **Stale tags answer "latest" questions with years-old values.** For a stale tag, `is_metric_tagged` is True, so the "metric not tagged" path never fires, and `get_metric` with no period returns the last entry ever filed. Observed: JPM cash 2018-12-31, BAC cash 2020-09-30, TGT cash 2017-04-29, TGT gross profit 2018-02-03, XOM revenue 2023-06-30, XOM inventory 2012-06-30, JNJ operating income 2015-03-29, CAT gross profit 2020-12-31. A fiscal-year query for a current year returns None (correct fallback to search); only the no-period path is wrong.
2. **The no-period path accepts non-10-K/10-Q forms.** `get_metric("CAT", "net_income")` returns 8,884M from a DEF 14A (end 2025-12-31, fiscal_year None). Correction to R2: CAT `NetIncomeLoss` does have 10-K entries, but the last is FY2010; FY2025 net income is only in `ProfitLoss` (8,882M). A FY2025 query returns None.
3. **TGT fiscal years are off by one for annual queries, and annual and quarterly labels disagree.** `get_metric("TGT", "revenue", 2025)` returns the year ending 2025-02-01 (106,566M), which Target calls fiscal 2024. Quarters use the raw `fy` (start-year): `Q2 FY2026` is the quarter ending 2026-08-01, in Target's fiscal 2026, while `FY2026` annual is the year ending 2026-01-31 (Target's fiscal 2025). WMT is consistent (annual FY2026 = year ending 2026-01-31; latest 10-Q is `fy=2027 Q2`, ending 2026-07-31).
4. **One JNJ year is unreachable by fiscal-year label.** Years ending 2023-01-01 (JNJ fiscal 2022) and 2023-12-31 (fiscal 2023) both resolve to 2023, and `_pick_entry`'s max(end) picks the later, so `FY2023` returns 85,159M and JNJ fiscal 2022 can only be reached by `period_end_date`. `FY2021` returns the year ending 2021-01-03 (JNJ fiscal 2020), `FY2022` the year ending 2022-01-02 (fiscal 2021).
5. **XOM's Q2 2026 facts are only under the new CIK.** The EDGAR filing index lists the 2026-08-03 10-Q (accession 0000034088-26-000093) under both 34088 and 2115436, so text ingest via 34088 gets it. Its XBRL facts are attributed only to 2115436: under 34088, the latest `Assets` entry is the 2026-05-04 10-Q (end 2026-03-31). The fact tools pinned to 34088 stop at Q1 2026.
6. **Confident wrong-scale value: JNJ R&D.** `get_metric("JNJ", "rd_expense", 2025)` returns 109M (R2 open question 4, still untraced).
7. **BAC entity name is cosmetic.** `companyconcept` also reports `entityName` "BofA Finance LLC" for CIK 70858, but the data is Bank of America's (FY2025 assets 3,411,738M), and no code reads `entityName` (grep of `src/`). No action needed.

## 2. Per-ticker results (FY = latest 10-K)

"Absent" = 404; "stale" = last 10-K value ends before 2025-06-01. Values in millions.

| Ticker | Works for latest FY | Absent | Stale (last 10-K FY end) |
|---|---|---|---|
| JPM | net_income 57,048; total_assets 4,424,900 | revenue, gross_profit, cost_of_revenue, rd_expense, operating_income, inventory | cash (2018) |
| BAC | net_income 30,509; total_assets 3,411,738 | same as JPM | cash (2019) |
| TGT | revenue 104,780; net_income 3,705; operating_income 5,117; total_assets 59,490; inventory 12,304 (all labelled FY2026, Target's fiscal 2025) | cost_of_revenue, rd_expense | gross_profit (2018); cash (no 10-K entry, last 10-Q 2017) |
| WMT | revenue 706,413; cost_of_revenue 535,395; net_income 21,893; operating_income 29,825; total_assets 284,668; cash 10,727; inventory 58,851 | gross_profit, rd_expense | none |
| XOM | rd_expense 1,200; net_income 28,844; total_assets 448,980; cash 10,681 | gross_profit, cost_of_revenue, operating_income | revenue (2021); inventory (2011) |
| JNJ | revenue 94,193; gross_profit 63,937; rd_expense 109 (suspect); net_income 26,804; total_assets 199,210; cash 19,709; inventory 14,191 | cost_of_revenue | operating_income (2014) |
| CAT | cost_of_revenue 44,752; rd_expense 2,148; operating_income 11,151; total_assets 98,585; cash 9,980; inventory 18,135 | revenue | gross_profit (2020); net_income (2010) |

## 3. Inferences

- Findings 1-4 are silent wrong answers, not refusals: the tool returns a cited number for the wrong period or a stale one. They are the strongest v2 questions if left unfixed, and the strongest case for fixing first if v2 is meant to measure the agent rather than the tool. That trade-off is the Fact-tool adaptation policy ticket.
- Finding 1 and 2 have one shared shape: the no-period path has neither a recency bound nor a form filter.
- Findings 3 and 4 both come from the end-year rule in `_resolved_fiscal_year`, which only fits companies that name a year by its end date (R2 finding 3).

## 4. Sources

- `https://data.sec.gov/api/xbrl/companyconcept/CIK<CIK>/us-gaap/<tag>.json` for the 7 tickers × 9 default tags, plus `Assets` for CIK 0002115436.
- `https://data.sec.gov/submissions/CIK0000034088.json` and `CIK0002115436.json` (10-K/10-Q filing lists).
- Repo: `src/sec_agent/sources/xbrl_facts.py` (`get_metric`, `_latest_entry`, `_resolved_fiscal_year`, `_pick_entry`, `is_metric_tagged`).

checked: 7 tickers × 9 metrics via get_metric (latest FY and no-period), 9 stale cases via no-period and is_metric_tagged, TGT/WMT/JNJ fiscal-year lookups, XOM CIK split in XBRL and submissions, entityName use in src/.
