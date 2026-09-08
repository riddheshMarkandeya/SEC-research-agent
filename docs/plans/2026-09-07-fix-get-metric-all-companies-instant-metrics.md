# Fix `get_metric_all_companies()` correctly (redesign of yesterday's Fix 4)

## Context

Yesterday's Fix 4 (review finding §4: `compare_financial_metric` returned
`{}` for `total_assets`/`cash_and_equivalents`/`inventory` at the latest
fiscal year) shipped with a real regression, found while researching the
next backlog batch: `get_metric_all_companies()`'s fallback — borrowing
*another* covered company's SEC-assigned `frame` when the requested
ticker's own entry lacked one — silently substitutes a different
requested time window instead of degrading honestly. Live-verified: with
NVDA as the anchor (own FY2026 total_assets = $206.8B, period ending
2026-01-25, no frame), the fallback borrowed MSFT's frame (`CY2026Q2I`,
representing June 2026) and returned NVDA's *Q2 FY2027* balance
($320.3B, period ending 2026-07-26) mislabeled as if it were the
requested FY2026 figure. That's worse than the original bug — a
plausible-looking wrong number instead of an honest empty result.

**Root cause, confirmed via the actual code and via web research into
how this problem is normally solved (not guessed):**
- `formulas.py`'s own `RATIO_DEFINITIONS` comment already documented
  that borrowing a frame doesn't resolve correctly for instant concepts
  — missed on the first pass.
- SEC's own frame-assignment gap on instant facts is confirmed
  intentional/documented SEC API behavior (not a bug in our data),
  confirmed via external sources.
- Real financial-analysis practice ("calendarization") explicitly
  applies calendar-window alignment to *income-statement/cash-flow*
  (duration) figures, and explicitly does **not** apply it to
  balance-sheet (instant) figures — a balance is a snapshot as of one
  date, not a period that can be shifted. Standard practice compares
  each company's own most-recent balance sheet, dates naturally
  differing, not a forced shared snapshot.

This means SEC's frames API (calendar-window bucketing) is the *correct*
mechanism for duration metrics — already working, confirmed via
existing tests, not touched by this fix — and the *wrong* mechanism
entirely for instant metrics, which should never have tried to force a
shared calendar snapshot in the first place.

**Resolved with the user during planning**, after presenting two real
alternatives (split-by-concept-type vs. a closest-date-match-with-
tolerance mechanism): go with the simpler, research-backed design —
split by concept type, no new proximity-matching logic.

## The fix

`xbrl_facts.py`:

- New `INSTANT_METRICS = {"total_assets", "cash_and_equivalents", "inventory"}`
  — declarative, matching this file's existing registry style
  (`DEFAULT_METRIC_TAGS`, `RATIO_DEFINITIONS`). These are the only 3
  metrics tagged to instant (point-in-time) XBRL concepts; everything
  else is duration. `_duration_days()`'s own docstring already confirms
  one concept's entries are consistently all-instant or all-duration,
  never mixed, so a static per-metric classification is valid.
- `get_metric_all_companies()` branches on `metric in INSTANT_METRICS`:
  - **Instant**: no anchor, no frame, no `get_frame()` call at all —
    loop over `load_companies()` and call `get_metric(candidate, metric, fiscal_year, fiscal_period, period_end_date)`
    independently for each covered company, collecting non-`None`
    results. Each company's own real, correctly-resolved `period_end`
    is returned as-is (already surfaced per-company in
    `agent.py`'s `_comparison_as_results()` citation metadata, so a
    reader can already see the dates differ — nothing hidden).
  - **Duration**: unchanged — today's anchor + `get_frame()` logic,
    exactly as before this whole investigation started.

`agent.py`'s `_comparison_as_results()` — small, directly-enabled
follow-on fix, not scope creep: it currently hardcodes
`"form": "XBRL frame data"` for every company, because `get_frame()`'s
return shape never included a `form` field. Under the new design,
instant-metric facts come from `get_metric()` directly and *do* carry a
real `form` (10-K/10-Q). Change to `fact.get("form", "XBRL frame data")`
so instant-metric citations show their real form, while duration-metric
(still frame-sourced) citations keep the existing fallback label
unchanged.

## Tests

`tests/test_xbrl_facts.py`:
- Remove the two tests written for yesterday's now-abandoned
  frame-borrowing fallback (`test_get_metric_all_companies_falls_back_to_another_companys_frame`,
  `test_get_metric_all_companies_still_anchors_on_requested_ticker_first`)
  — they tested a mechanism this plan removes.
- The existing duration-metric tests (`test_get_metric_all_companies_anchors_on_the_given_tickers_frame`,
  `_returns_empty_when_anchor_unavailable`, `_returns_empty_when_anchor_has_no_frame`,
  all using `"gross_profit"`) need no change — confirms the duration
  path is genuinely untouched.
- New tests for the instant path: independent per-company resolution
  returns each company's own real (differing) `period_end`/value
  un-modified; a company with no data for the period is excluded, not
  fatal to the others; `get_frame()` is never called for an instant
  metric (a regression guard against ever reintroducing frame-borrowing
  here).

`tests/test_agent.py`: new test for `_comparison_as_results()` showing a
real `form` value passes through when present, alongside the existing
test confirming the `"XBRL frame data"` fallback still applies when it
isn't.

## Eval coverage gap, found while checking impact on existing questions

Checked every one of the 40 eval questions against this change: **none
need modification** — every question touching `total_assets`/
`cash_and_equivalents`/`inventory` is single-company (routed through
`get_metric`/`get_ratio`, never `get_metric_all_companies`), and the 3
genuine cross-company comparison questions use tax rate/employee
count/revenue, a different code path entirely.

But that also means there is currently **zero eval coverage** for a
cross-company instant-metric comparison — exactly the scenario both the
original bug and the regression lived in, which is why neither the eval
suite nor the earlier self-review caught it. Adding one closes the gap:

- New question `aapl-msft-total-assets-comparison` in
  `eval/eval_questions.jsonl`, `type: "comparison"`, `tickers: ["AAPL", "MSFT"]`:
  "Compare Apple's total assets as of September 27, 2025 to Microsoft's
  total assets as of June 30, 2025." Ground truth verified live against
  the real cached XBRL data (not guessed): AAPL FY2025 = $359,241M
  (period end 2025-09-27, 10-K accession 0000320193-25-000079), MSFT
  FY2025 = $619,003M (period end 2025-06-30, 10-K accession
  0000950170-25-100235). `expected: [{"ticker": "AAPL", "expected_value": 359241, "expected_unit": "million"}, {"ticker": "MSFT", "expected_value": 619003, "expected_unit": "million"}]`.

## Verification

1. Full `pytest` suite green.
2. Live re-run of the exact repro that exposed the regression: confirm
   `get_metric_all_companies("NVDA", "total_assets", fiscal_year=2026, fiscal_period="FY")`
   now returns NVDA's own correct $206.8B/2026-01-25 figure (not
   MSFT's borrowed window), alongside whichever other covered companies
   have their own FY2026 total_assets available.
3. Run the new eval question live (`python eval_harness.py --ids aapl-msft-total-assets-comparison`)
   and confirm it passes against the real agent/retrieval stack, not
   just the unit-level fix.
4. Self-check the diff (Standard-tier fix once designed, per `CLAUDE.md`
   — the design decision was the Substantial part, already resolved).
5. Update `BACKLOG.md`/`PROJECT_CONTEXT.md`: correct the §4 changelog
   entry from yesterday to describe what actually shipped (the
   corrected design, not the reverted one), and only then resume the
   on-hold Medium-priority batch.
