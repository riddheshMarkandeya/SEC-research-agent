# Sector-specific XBRL reporting: what breaks when we leave tech

Date: 2026-10-07
Ticket: R2 Sector-specific reporting
Feeds: which sectors/tickers to add (10-12 companies, incl. a same-sector look-alike pair) and which eval questions stress the XBRL tools.

Method: read the tool code, then pulled SEC `companyfacts` JSON on 2026-10-07 for 21 tickers (list in `checked:` at the end) with `User-Agent: SEC research agent riddhesh2307@gmail.com`, about 2 requests/sec. Downloaded JSON was treated as data only. "Latest FY" below is the fiscal year in each company's most recent 10-K, i.e. FY2025 (Dec-end) or fiscal 2025/2026 (Jan-end retailers) and Costco FY2026 (10-K filed 2026-10-07). Evidence for every table cell is `https://data.sec.gov/api/xbrl/companyfacts/CIK<10-digit>.json` for the ticker's CIK (CIKs in Sources). "Absent" means the tag is not in that company's us-gaap facts at all; "stale" means present but no 10-K value ending after 2025-06-01 (the same trap the code already documents for `Revenues` at `src/sec_agent/sources/xbrl_facts.py:37-45` and `devtools/discover_tags.py:40-45`).

## 1. Findings first

1. Revenue is the least portable metric. `revenue` is hard-wired to `RevenueFromContractWithCustomerExcludingAssessedTax`. Of 21 tickers checked, it is the live tag for only 7 (WMT, COST, HD, TGT, HON, CVX, JNJ). It is absent for all 5 financials, PLD, CAT, MRK, LLY, UNH (10 tickers); stale for O, GE, PFE, XOM. The per-ticker override map exists (`xbrl_facts.py:61-63`), but there is no fallback chain, so every new company needs an override and a miss is a hard "no fact".
2. Margin and cost metrics mostly do not exist outside retail/industrial/pharma. `gross_profit` is live for only HD, HON, JNJ; `cost_of_revenue` (`CostOfRevenue`) is live for only WMT, HD, CAT. `operating_income` is absent for all banks, PGR, XOM, CVX, PFE, MRK, LLY. Gross-margin or operating-margin questions for banks, insurers, REITs and energy are structurally unanswerable from the default tags.
3. The fiscal-year resolver is wrong for some non-calendar companies. `_resolved_fiscal_year` (`xbrl_facts.py:170-190`) labels every annual entry with its end-date's calendar year, on the assumption (stated in its docstring, lines 172-175) that every tracked company names its fiscal year after the year it ends in. Verified against SEC's own `fy` tag on each year's original 10-K:
   - HD: FYE 2026-02-01 is `fy=2025` (HD's "fiscal 2025"); end-year rule gives 2026, off by one. Same for TGT (FYE 2026-01-31, `fy=2025`).
   - WMT: FYE 2026-01-31 is `fy=2026`; end-year rule is correct. So HD/TGT and WMT use opposite conventions, and one rule cannot serve both.
   - JNJ: 52/53-week year ending 2022-01-02 is `fy=2021`, and 2023-01-01 is `fy=2022`; the end-year rule gives 2022 and 2023. From 2023-12-31 on the labels agree.
   - Costco: FYE 2023-09-03 is `fy=2023` (end-year rule correct).
4. Ticker-to-CIK can silently point at an empty entity. SEC's `company_tickers.json` now maps XOM to CIK 2115436 ("ExxonMobil Holdings Corp"), whose companyfacts holds only 10-Q facts for 2025 and 2026 and no 10-K FY values. All Exxon Mobil 10-K history is under CIK 34088. A registry that copies the CIK from `company_tickers.json` would get XOM wrong; it must be pinned by hand and re-checked after the next 10-K.
5. Right-looking wrong tags exist. CAT's `CostOfGoodsAndServicesSold` is 49 million for FY2025 (a sliver), while its cost of sales is in `CostOfRevenue` (44,752 million). CAT's `NetIncomeLoss` has no 10-K entries (only DEF 14A) because the income statement uses `ProfitLoss` (8,882 million) and `NetIncomeLossAvailableToCommonStockholdersBasic` (8,884 million). UNH's `CostOfGoodsAndServicesSold` (50,655 million) is only its product costs, not its medical costs. A tool that returns a non-null value from these without a sector check will answer confidently and wrongly.
6. Sector headline metrics are not XBRL concepts in `companyfacts`. Scans of the full us-gaap fact list (keyword searches below) found no tag for FFO/AFFO, same-store or comparable sales, combined ratio, loss ratio, net interest margin, CET1 ratio, or oil and gas production volumes for the companies checked. Whether they sit in custom extension tags is unknown (open question 1). The practical consequence: those questions can only be answered from filing text, which is the retrieval path, not the XBRL path.

## 2. What our tools assume (path:line)

- `src/sec_agent/sources/xbrl_facts.py:50-60`: `DEFAULT_METRIC_TAGS` has 9 metrics, each a single us-gaap tag: `revenue`=`RevenueFromContractWithCustomerExcludingAssessedTax`, `gross_profit`=`GrossProfit`, `cost_of_revenue`=`CostOfRevenue`, `rd_expense`=`ResearchAndDevelopmentExpense`, `net_income`=`NetIncomeLoss`, `operating_income`=`OperatingIncomeLoss`, `total_assets`=`Assets`, `cash_and_equivalents`=`CashAndCashEquivalentsAtCarryingValue`, `inventory`=`InventoryNet`.
- `xbrl_facts.py:61-63`: `METRIC_TAG_OVERRIDES` has one entry (NVDA revenue -> `Revenues`). No ordered fallback list exists; `_tag_for` (`:103-108`) returns exactly one tag or raises `ValueError` for an unknown metric name.
- `xbrl_facts.py:73`: `INSTANT_METRICS` = {total_assets, cash_and_equivalents, inventory}; anything new that is a balance (loans, deposits, reserves) must be added here by hand.
- `xbrl_facts.py:86-87`: annual duration window 350-380 days; quarter window 80-100 days. `_pick_entry` (`:193-232`) also requires `form == "10-K"` for FY and `"10-Q"` for quarters, so a tag whose FY value is only attached to another form (CAT `NetIncomeLoss`, finding 5) returns nothing.
- `xbrl_facts.py:170-190`: annual fiscal year = end-date year; non-annual uses raw SEC `fy`.
- `xbrl_facts.py:369-470` (`fetch_frame`, `get_frame`): cross-company comparison merges every distinct tag in play per metric and keys frames by CIK from the registry; a bank "revenue" frame query would compare unlike concepts.
- `src/sec_agent/devtools/discover_tags.py:48-99`: pulls `companyfacts` per ticker and lists tags, with `recent_only` (400-day cutoff, `:45`) to catch stale tags. It looks up the CIK from the company registry (`:58-59`), so finding 4 applies. It lists the `us-gaap` taxonomy by default; the namespace list per company is `dei`, `us-gaap`, plus `srt`/`invest`/`ffd`/`ecd` for some, and no company-prefixed extension namespace appeared for any ticker checked (observed, not documented).
- `src/sec_agent/sources/companies.py:26-40`: the registry stores `cik` and `fiscal_year_end_month` per ticker. Month alone cannot express a 52/53-week year ending on the Saturday or Sunday nearest a month end (finding 3).

## 3. Per-sector table

Values are the latest FY from companyfacts. "Rev tag" is the tag actually carrying the headline revenue. Tags in the "missing vs tech" column are among the 9 default tags and are absent or stale for that company.

| Sector | Ticker | Rev tag (latest FY value) | Cost / margin | Sector headline metrics available as us-gaap tags | Default tags missing or stale | FY-end quirk |
|---|---|---|---|---|---|---|
| Bank | JPM | `Revenues` = `RevenuesNetOfInterestExpense` 182,447M | none; `NoninterestExpense` 95,640M | `InterestIncomeExpenseNet` 95,443M; `ProvisionForLoanLeaseAndOtherLosses` 14,212M; `NoninterestIncome` 87,004M; `Deposits` 2,559,320M; `InterestExpenseDeposits` | revenue, gross_profit, cost_of_revenue, rd, operating_income, inventory absent; cash stale | Dec 31 |
| Bank | BAC | `Revenues` 113,097M | none; `NoninterestExpense` 69,727M | `InterestIncomeExpenseNet` 60,096M; `NoninterestIncome` 53,001M; `Deposits` 2,018,729M; provision: not under `ProvisionForLoanLeaseAndOtherLosses` (last FY 2019); closest live tag found `FinancingReceivableExcludingAccruedInterestCreditLossExpenseReversal` 5,595M | same as JPM; `entityName` in companyfacts reads "BofA Finance LLC" for the BAC CIK | Dec 31 |
| Bank | WFC | no `Revenues`; `RevenuesNetOfInterestExpense` 83,699M | none; `NoninterestExpense` 54,842M | `InterestIncomeExpenseNet` 47,484M; `ProvisionForLoanLeaseAndOtherLosses` 3,658M; `NoninterestIncome` 36,215M; `Deposits` 1,426,207M | revenue, gross_profit, cost_of_revenue, rd, operating_income, cash, inventory absent | Dec 31 |
| Insurer | PGR | `Revenues` 87,671M | none; `BenefitsLossesAndExpenses` 73,448M | `PremiumsEarnedNet` 81,661M; `CededPremiumsEarned`; `CededPremiumsWritten`; `InterestAndDividendIncomeOperating` 3,583M | revenue, gross_profit, cost_of_revenue, rd, operating_income, cash, inventory absent | Dec 31 |
| Insurer | TRV | `Revenues` 48,828M | none; `BenefitsLossesAndExpenses` 41,032M | `PremiumsEarnedNet` 43,914M; `DirectPremiumsEarned` 45,042M; `DeferredPolicyAcquisitionCosts` 3,518M; `LiabilityForClaimsAndClaimsAdjustmentExpense` 65,737M | as PGR; `OperatingIncomeLoss` stale (last 2015) | Dec 31 |
| REIT | PLD | `Revenues` 8,790M | no COGS; `OperatingExpenses` is reported negative (-2,280,683,000) | `OperatingIncomeLoss` 4,358M; `ProfitLoss` 3,565M (vs `NetIncomeLoss` 3,328M, the stockholder share); `LessorOperatingLeasePaymentsToBeReceived*` | revenue, gross_profit, cost_of_revenue, rd, inventory absent | Dec 31 |
| REIT | O | `Revenues` 5,749M (`RevenueFromContract...` stale since 2018); `LeaseIncome` 5,437M | `CostsAndExpenses` 4,786M; no operating income tag | `LeaseIncome`; `DirectCostsOfLeasedAndRentedPropertyOrEquipment` 429M; `srt:SECScheduleIIIRealEstateNumberOfUnits` 15,512 | revenue (stale), gross_profit, cost_of_revenue, rd, operating_income, inventory absent | Dec 31 |
| Retail | WMT | `RevenueFromContract...` 706,413M and `Revenues` 713,163M (differ; total includes membership and other income) | `CostOfRevenue` 535,395M; `GrossProfit` absent | `InventoryNet` 58,851M; `OperatingIncomeLoss` 29,825M | gross_profit, rd absent | FYE Jan 31; `fy` = end year (FYE 2026-01-31 is `fy=2026`) |
| Retail | COST | `RevenueFromContract...` 303,154M (FY2026); `Revenues` last FY2025 | `CostOfGoodsAndServicesSold` 264,279M; `GrossProfit` stale (2019); `CostOfRevenue` absent | `OperatingIncomeLoss` 11,685M; `InventoryNet` 19,324M | gross_profit (stale), cost_of_revenue, rd absent | 52/53 weeks ending Sunday nearest Aug 31 (2023-09-03, 370 days; 2026-08-30); `fy` = end year; Q1-Q3 are 83 days |
| Retail | HD | `RevenueFromContract...` 164,683M | `CostOfRevenue` 109,818M; `GrossProfit` 54,865M | `OperatingIncomeLoss` 20,890M | rd absent | FYE Sunday nearest Jan 31 (2025-02-02, 370 days; 2026-02-01); `fy` = start year (FYE 2026-02-01 is `fy=2025`) |
| Retail | TGT | `RevenueFromContract...` 104,780M | `CostOfGoodsAndServicesSold` 75,511M; `GrossProfit` stale (2018) | `OperatingIncomeLoss` 5,117M | gross_profit (stale), cost_of_revenue, rd absent; cash stale (2017) | FYE Saturday nearest Jan 31 (2024-02-03; 2026-01-31); `fy` = start year |
| Industrial | CAT | `Revenues` 67,589M (`RevenueFromContract...` absent) | `CostOfRevenue` 44,752M; `GrossProfit` stale (2020); `CostOfGoodsAndServicesSold` 49M (a trap) | `OperatingIncomeLoss` 11,151M; `ProfitLoss` 8,882M; `ResearchAndDevelopmentExpense` 2,148M | revenue, gross_profit (stale), net_income (10-K entries absent) | Dec 31 |
| Industrial | HON | `RevenueFromContract...` 37,442M | `CostOfGoodsAndServicesSold` 23,613M; `GrossProfit` live | `OperatingIncomeLoss` 8,127M; `ResearchAndDevelopmentExpense` 1,812M | cost_of_revenue absent | Dec 31 |
| Industrial | GE | `Revenues` 45,855M (`RevenueFromContract...` last value 2024Q4 only) | `CostOfGoodsAndServicesSold` stops at 2024Q4; `GrossProfit` stale (2016) | `ResearchAndDevelopmentExpense` 1,580M; `CostsAndExpenses` 37,342M | revenue (stale), gross_profit, operating_income (stale 2014), cash (stale 2017) | Dec 31 |
| Energy | XOM (CIK 34088) | `Revenues` 332,238M (`RevenueFromContract...` stale since 2023) | no COGS tag live; `CostsAndExpenses` 290,970M | `IncomeLossFromContinuingOperationsBeforeIncomeTaxes...` 41,268M; `ResearchAndDevelopmentExpense` 1,200M | revenue (stale), gross_profit, cost_of_revenue, operating_income absent; inventory stale (2012). Ticker maps to a different CIK (finding 4) | Dec 31 |
| Energy | CVX | `RevenueFromContract...` 184,432M and `Revenues` 189,031M | `CostOfGoodsAndServicesSold` 108,214M; `CostsAndExpenses` 169,288M | `PaymentsToAcquireOilAndGasPropertyAndEquipment` 16,830M | gross_profit, cost_of_revenue, operating_income absent; cash stale (2023) | Dec 31 |
| Pharma | JNJ | `RevenueFromContract...` 94,193M | `CostOfGoodsAndServicesSold` 30,256M; `GrossProfit` 63,937M | `ResearchAndDevelopmentExpense` 109M (a stub: JNJ's R&D line is larger; value not traced) | cost_of_revenue absent; operating_income stale (2015) | 52/53 weeks; FYE 2022-01-02, 2023-01-01, 2025-12-28; early `fy` = start year |
| Pharma | PFE | `Revenues` 62,579M (`RevenueFromContract...` last FY 2023) | `CostOfGoodsAndServicesSold` 16,067M | `ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost` 10,437M | revenue (stale), gross_profit, rd (different tag), operating_income absent | Dec 31 |
| Pharma | MRK | `Revenues` 65,011M | `CostOfGoodsAndServicesSold` 16,382M | `ResearchAndDevelopmentExpense` 15,789M | revenue, gross_profit, cost_of_revenue, operating_income absent | Dec 31 |
| Pharma | LLY | `Revenues` 65,179M | `CostOfGoodsAndServicesSold` 11,052M | `ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost` 13,337M | revenue, gross_profit, cost_of_revenue, rd (stale), operating_income absent | Dec 31 |
| Managed care | UNH | `Revenues` 447,567M | `CostOfGoodsAndServicesSold` 50,655M is product cost only; `PolicyholderBenefitsAndClaimsIncurredNet` 313,995M (plausibly medical costs; not tied to a filing line here) | `PremiumsEarnedNet` 352,229M; `OperatingIncomeLoss` 18,964M; `IncreaseDecreaseInHealthCareInsuranceLiabilities` 5,824M | revenue, gross_profit, cost_of_revenue, rd absent | Dec 31 |

All 21 tickers have live `NetIncomeLoss` (except CAT, above), `EarningsPerShareDiluted` and `Assets` tags, so net income, EPS and total assets port cleanly; EPS is not in the default metric map, so it is not currently exposed.

## 4. Per-sector notes

Banks (JPM, BAC, WFC). The income statement is organized as interest income, interest expense, net interest income, provision for credit losses, noninterest income and expense; there is no cost of revenue, gross profit or operating income concept in use. The same line has different names: JPM and BAC report a `Revenues` total, WFC reports `RevenuesNetOfInterestExpense`. The provision line moved: JPM and WFC still use `ProvisionForLoanLeaseAndOtherLosses`, but BAC's last FY value for that tag is 2019 and it also last used `ProvisionForLoanAndLeaseLosses` in 2019; a candidate replacement is the allowance-roll-forward tag `FinancingReceivableExcludingAccruedInterestCreditLossExpenseReversal`, which may be only the loan component (open question 2). Cash: JPM and BAC have no live `CashAndCashEquivalentsAtCarryingValue`; JPM has `CashAndDueFromBanks` 21,742M and `CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents` 343,338M. Balance sheet headliners (deposits, loans via `FinancingReceivable...`) are instants and would need `INSTANT_METRICS` entries. Scale also matters for numeric-grounding code: JPM assets are 4.4 trillion (4,424,900,000,000).

Insurers (PGR, TRV). Revenue is `Revenues`; the core operating line is `PremiumsEarnedNet`. Costs are one aggregate (`BenefitsLossesAndExpenses`), so there is no gross margin or operating income. Combined ratio and loss ratio were not found as us-gaap tags (keyword scans "Combined", "Underwriting", "Claim" on PGR and TRV returned only dollar concepts such as `LiabilityForClaimsAndClaimsAdjustmentExpense`).

REITs (PLD, O). No cost of revenue; revenue is `Revenues`; Realty Income's rental income is also in `LeaseIncome`. REIT net income has two candidates (`NetIncomeLoss` is stockholders' share, `ProfitLoss` includes noncontrolling interests: PLD 3,328M vs 3,565M), a pick-the-right-one trap. `OperatingExpenses` is stored as a negative number for PLD, which would break a sign assumption. FFO, AFFO and same-store NOI were not found as us-gaap tags (keyword scans "FundsFrom", "FFO", "Occupan", "SameStore" returned nothing). The `srt:SECScheduleIIIRealEstateNumberOfUnits` fact is in the `srt` namespace, so a tool pinned to `us-gaap` URLs would not see it.

Retailers (WMT, COST, HD, TGT). Most similar to tech on the income statement: revenue, cost, inventory exist. Differences: (a) two revenue totals at WMT (net sales vs total revenues); COST's `Revenues` stopped after FY2025 while `RevenueFromContract...` continues; (b) `GrossProfit` is not reported by WMT, COST, TGT, so gross margin must be computed from revenue minus cost, and the cost tag differs (`CostOfRevenue` vs `CostOfGoodsAndServicesSold`); (c) fiscal-year naming (finding 3) and 52/53-week lengths. Quarter windows work: Costco's quarters are 83 days, within the 80-100 window; Q4 is not a 10-Q period and is, as for tech, not directly tagged. Comparable-store sales were not found as a tag (keyword scans "Comparable", "Store" on WMT and HD returned nothing relevant).

Industrials (CAT, HON, GE). Closest to the tech assumptions, and the best test of the tag logic because each lands differently: CAT is the 'right tag exists but is hidden' case (net income under `ProfitLoss`, `CostOfGoodsAndServicesSold` trap), HON is the tidy case, GE is the structural-change case (revenue tag changed after the 2024 spin-offs; several default tags stale). CAT and GE also have large financing segments, so a consolidated revenue includes financial-services revenue.

Energy (XOM, CVX). No `OperatingIncomeLoss`, no gross profit, no cost-of-revenue tag at XOM; CVX has `CostOfGoodsAndServicesSold` for purchased crude and products only. Production volumes (barrels per day) and proved reserves were not found as us-gaap tags; keyword scans "Reserve|Barrel|Production|OilAndGas" on XOM and CVX returned only accounting items (e.g. `CapitalizedExploratoryWellCostAdditionsPendingDeterminationOfProvedReserves`, `PaymentsToAcquireOilAndGasPropertyAndEquipment`). XOM also has the CIK-split problem (finding 4).

Healthcare/pharma (JNJ, PFE, MRK, LLY, UNH). Pharma has gross profit or cost of goods but rarely a live `OperatingIncomeLoss`. R&D uses three different tags across four companies (`ResearchAndDevelopmentExpense` at MRK/JNJ, `...ExcludingAcquiredInProcessCost` at PFE/LLY), so `rd_expense` returns nothing for PFE and LLY without overrides. JNJ's 109M under `ResearchAndDevelopmentExpense` is far below its reported R&D scale, which suggests the tag holds a sub-item (not verified against the filing; open question 4). UNH is an insurer-like income statement (premiums, medical costs) with a fiscal year of Dec 31; its "medical care ratio" was not found as a tag.

## 5. Sector headline metrics: XBRL vs filing text

Status legend: "no tag found" means a keyword scan of the company's full us-gaap facts returned nothing (companyfacts excludes extension namespaces as far as observed). The GAAP/non-GAAP labels are from general knowledge of how these companies present the measures, NOT verified in the filings this session.

| Metric | Sector | Found as us-gaap tag? | Likely where it lives (unverified) |
|---|---|---|---|
| Net interest income, provision, noninterest income/expense | Banks | yes | income statement |
| Net interest margin, efficiency ratio, CET1 / Tier 1 ratios | Banks | no tag found for JPM ("Tier", "CapitalRatio", "NetInterestMargin", "Efficiency") | MD&A tables; regulatory-capital note |
| Premiums earned, losses and expenses | Insurers | yes | income statement |
| Combined ratio, loss ratio, premiums written (net) | Insurers | combined/loss ratio no; `CededPremiumsWritten`/`DirectPremiumsWritten` yes | MD&A; segment discussion; usually non-GAAP or statutory |
| FFO, AFFO, same-store NOI, occupancy | REITs | no | supplemental package, MD&A; non-GAAP |
| Comparable-store sales, traffic, ticket | Retailers | no | MD&A / earnings release; operating KPI |
| Store count | Retailers | no for WMT, HD | Item 1/2 text |
| Oil and gas production volumes, proved reserves | Energy | no | Item 1/2 and supplemental oil and gas disclosures (text and tables) |
| Segment revenue / operating profit | Industrial, pharma | partly (via dimensions; `companyfacts` flattens dimensions away and may omit them) | segment note |
| Medical care ratio | Managed care | no | MD&A |

## 6. Inferences (not stated by a source)

Which sectors stress the tools most, in order:
1. Banks: five of nine default metrics do not exist, revenue needs a per-ticker override, the provision tag changed at BAC, and balance-sheet headliners are instants not yet in `INSTANT_METRICS`. Highest stress with only 2-3 new override entries needed, so a good eval of "does the agent refuse or say the metric does not exist" rather than hallucinate a gross margin.
2. Insurers and energy: no operating income and no gross profit; the headline ratios (combined ratio, production) are text-only, so these test the XBRL-to-retrieval handoff and the refusal path.
3. Retailers with mixed fiscal-year conventions (HD or TGT alongside WMT or COST): the only sector where an existing rule produces a silent wrong-year answer (finding 3). This is the highest correctness risk per unit of work.
4. REITs: sign and net-income-attribution traps, FFO text-only.
5. Pharma: R&D tag variance and JNJ's 52/53-week labels.
6. Industrials: lowest stress, but CAT and GE are good stale-tag and hidden-tag tests.

Candidate set (the 5 existing tech names plus 6-7 new ones, 11-12 total). A suggested core that covers every distinct failure with the fewest companies:

- Banks: JPM and BAC as the look-alike pair. Same business and same Dec 31 year-end, but different provision tags (live at JPM, stale since 2019 at BAC) and different revenue naming consistency; WFC is a third-party-check option. Adds the same-sector comparison "which bank had higher net interest income" where the pair must be answered with the same tag.
- Retail: HD and WMT (or TGT and WMT) as the contrasting look-alike pair for fiscal-year convention (HD `fy` = start year, WMT `fy` = end year, both FYE late Jan/early Feb). COST adds a Sept FYE and a 53-week year.
- Insurer: PGR (or TRV). One is enough unless a look-alike pair is wanted; PGR vs TRV also differ on `OperatingIncomeLoss` (absent vs stale).
- REIT: PLD or O (O's `RevenueFromContract...` stale vs PLD's absent is the sole difference seen).
- Energy: XOM (for the CIK problem) and CVX as a second.
- Pharma: JNJ (52/53-week year, gross profit tag) plus MRK (R&D tag).
- Industrial: CAT (hidden net income tag) is the more informative of CAT/HON/GE.

Eval question types that would stress the tools (each maps to a verified break above):
- "What was JPM's gross margin?" / "Operating income for XOM?" - expect refusal or a note that the concept does not exist, not a fabricated number.
- "HD revenue for fiscal 2025" vs "WMT revenue for fiscal 2026" - same date window, opposite labels.
- "JNJ net income for fiscal 2021" (FYE 2022-01-02).
- "CAT net income" (tag hidden in `ProfitLoss`), "UNH cost of revenue" (product-only trap), "PLD net income" (attributable vs total).
- "BAC provision for credit losses" (stale tag).
- "XOM revenue for 2025" (CIK split).
- Cross-sector comparison "which company had the highest revenue" via `get_frame` (unlike concepts, and absent tags drop out silently).
- Text-only metrics: "FFO for Prologis", "comparable sales for Walmart", "combined ratio for Progressive", "Chevron production in barrels per day" - answers must come from retrieval with a citation, or be refused.

## 7. Open questions

1. Do the sector companies publish headline metrics as company-extension tags that `companyfacts` omits? Observed: no extension namespace appeared in any of the 21 payloads. Not checked against SEC's documentation or a filing's instance document.
2. What is BAC's income-statement "provision for credit losses" tag in the FY2025 10-K, and is `FinancingReceivableExcludingAccruedInterestCreditLossExpenseReversal` (5,595M) the full line or only the loan component? Needs the Financial Report or R-file for the filing.
3. Which tag does COST use for gross-profit-like items, and why did `Revenues` stop after FY2025 while FY2026 10-K was just filed? (The FY2026 10-K was filed 2026-10-07; check whether it changed tagging.)
4. JNJ `ResearchAndDevelopmentExpense` = 109M: which line is that in the filing?
5. After XOM's next 10-K, will annual facts appear under CIK 2115436 or stay under 34088? Re-check before relying on either.
6. Does the SEC `fy` tag follow a documented rule, or the company's own labeling? Observed: start-year for HD/TGT/JNJ(2021-22), end-year for WMT/COST. A safer resolver may need either the filing's own `fy` for FY entries or a per-ticker convention in the registry; deciding that is outside this ticket.
7. Whether segment/dimension data (UNH segments, CAT segments, REIT property types) is retrievable through `companyfacts` at all; not tested.
8. The statements in section 5 that FFO, comparable sales, combined ratio and NIM are non-GAAP or text-only measures are not yet confirmed against the companies' 10-K text.

## 8. Sources

All fetched 2026-10-07 (companyfacts JSON saved only to the session scratchpad):

- `https://www.sec.gov/files/company_tickers.json` (ticker -> CIK; XOM maps to 2115436).
- `https://data.sec.gov/api/xbrl/companyfacts/CIK<CIK>.json` for: JPM 0000019617, BAC 0000070858, WFC 0000072971, PGR 0000080661, TRV 0000086312, PLD 0001045609, O 0000726728, WMT 0000104169, COST 0000909832, HD 0000354950, TGT 0000027419, CAT 0000018230, HON 0000773840, GE 0000040545, XOM (new) 0002115436, XOM (old) 0000034088, CVX 0000093410, JNJ 0000200406, PFE 0000078003, MRK 0000310158, LLY 0000059478, UNH 0000731766.
- Repo files: `src/sec_agent/sources/xbrl_facts.py`, `src/sec_agent/devtools/discover_tags.py`, `src/sec_agent/sources/companies.py` (cited by line above).
- Not consulted: FASB us-gaap taxonomy pages and the companies' own filings; sections 4-5 statements about how metrics are presented (non-GAAP, MD&A) rest on general knowledge and remain unverified (open question 8).
