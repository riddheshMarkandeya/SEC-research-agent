# Cross-company comparison via SEC's `frames` API (`compare_financial_metric`)

**Date:** 2026-08-17 (commit `46f4099`, "Add compare_financial_metric
tool via SEC's frames API")

## Context

A second agent tool was needed to get one metric for all five covered
companies at once, for the same period, instead of the model calling
`get_financial_fact` five times.

## Decision

`fetch_frame()`/`get_frame()` call SEC's `frames` API
(`data.sec.gov/api/xbrl/frames/us-gaap/{tag}/USD/{frame}.json`) and
filter the whole-market response down to the 5 covered CIKs. The frame
label is never computed independently — it's read off an anchor
company's own already-resolved fact (`get_metric()` now returns the
SEC-assigned `frame` directly), then `get_metric_all_companies()`/
`get_gross_margin_all_companies()` use that same frame to fetch every
covered company's value for the same bucket.

## Why

First design considered computing a `"CY{year}Q{quarter}"` label from a
raw calendar date with ordinary quarter math. Checked against real data
before writing any of it: NVIDIA's quarter ending April 26 is assigned
frame `CY2026Q1` by SEC, not the naively-expected `CY2026Q2` — SEC's own
bucketing tolerates a wider window to accommodate non-calendar fiscal
years. Guessing that window would have reproduced the exact period-
matching bug class already fought twice in this file.

`get_frame()` merges across every distinct tag in play for a metric, not
just one — since NVDA uses `Revenues` while the other four use the ASC
606 tag, a single-tag frames query would silently omit NVDA.

A real gap found via a live natural-language test: asking "which company
had the highest gross margin in their most recent quarter" gave the
model no anchor date, so `compare_financial_metric` used to silently
return nothing. Fixed with `_latest_entry()`: with no period given at
all, `get_metric()` falls back to the single most-recently-reported
entry, breaking ties toward the shorter duration. A related, genuinely
expected (not a bug) characteristic: anchoring on a company that's filed
a more recent quarter than its peers gives partial coverage — surfaced
honestly via system-prompt rule 7, requiring the model to explicitly
name which companies were/weren't covered.

## Files touched

`xbrl_facts.py` (`fetch_frame`, `get_frame`, `get_metric_all_companies`,
`get_gross_margin_all_companies`, `_latest_entry`), `agent.py`
(new tool + rule 7).

## Verification

Real-data checks for all 5 companies each sourced from whichever tag it
actually uses; live checks of the anchor-relative partial-coverage
behavior against real filed-date asymmetries (AAPL/MSFT vs NVDA/CRM).

## Related

`docs/decisions/2026-09-07-fix-get-metric-all-companies-instant-metrics.md`
(a later redesign of the instant-metric half of this path).
