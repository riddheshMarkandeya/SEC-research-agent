# `discover_tags.py`: dev-time XBRL tag discovery

**Date:** 2026-08-19 (commit `101f6ee`, "Add discover_tags.py: dev-time
XBRL tag discovery via companyfacts")

## Context

Every entry in `DEFAULT_METRIC_TAGS` so far got added the same way: an
eval question fails, then a manual guess-and-check against
`companyconcept` confirms which tag to use — that loop only surfaces a
missing metric *after* something breaks.

## Decision

Wraps SEC's `companyfacts` endpoint (every tag a company has ever
reported, ~3.8MB for AAPL). `fetch_company_facts(ticker)` caches the full
payload; `list_tags(ticker, keyword=..., recent_only=..., taxonomy=...)`
filters it — by substring and/or to tags with at least one entry in the
last ~400 days (the same staleness trap already documented for
`Revenues`). Also runnable as a CLI. Deliberately NOT wired into
`agent.py` or any runtime path — a research tool run by hand before
writing/debugging an eval question.

## Why

Turns "discover by failure" into "browse up front."

## Files touched

`discover_tags.py` (new).

## Verification

Live-verified against real data: `discover_tags.py PLTR --keyword
inventory` returns 0 tags (independently confirming Palantir has no
inventory concept); `discover_tags.py AAPL --keyword inventory
--recent-only` returns 3 (`InventoryNet` plus breakdowns not previously
known about). 7 new tests, 209/209 full suite.

## Related

`docs/decisions/2026-08-19-fixing-6-accumulated-eval-findings.md` (the
work this tool was built to accelerate).
