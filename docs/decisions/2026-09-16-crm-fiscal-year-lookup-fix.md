# Fix CRM's off-by-one annual fiscal-year tagging in xbrl_facts

**Date:** 2026-09-16

## Context

`BACKLOG.md`'s next-highest-priority open item after the final-turn-
safety-net fix: `get_financial_fact(ticker="CRM", metric="operating_margin"/
"gross_margin", fiscal_year=2026, fiscal_period="FY")` returned `None`,
while the same fact via `period_end_date="2026-01-31"` returned the real
value (20.1%/77.7%). This was the mechanical reason a per-company
ranking path loses CRM specifically, and the thing the final-turn-
safety-net fix's own residual-risk note named as the precondition for
its grounded-but-incomplete risk to become reachable.

## Decision

In `xbrl_facts.py`, `_pick_entry` and `get_metric` now derive an annual
(`fp="FY"`) entry's fiscal year from its own **end date's calendar
year** instead of trusting the raw `fy` tag, via a new
`_resolved_fiscal_year(entry)` helper used at both call sites. Quarterly
matching is untouched.

## Why

**Root cause** (confirmed against real cached data in
`xbrl_cache/CRM_*.json`/`NVDA_*.json`, per-filing — an independent plan
review caught the first draft overstating this before implementation):
Salesforce's most recent 10-K (filed 2026-03-02, period ending
2026-01-31) self-tags its annual entry `fy: 2025`, one year behind its
own "fiscal year 2026" label. This is **not** a CRM-only or
recent-filings-only quirk: CRM's 2015-2025 filings are all correctly
tagged, but its 2010-2014 filings mismatch the same way — and NVDA has
the identical pattern in its own 2011-2014 filings. It's a general "a
filer's raw `fy` tag on a given filing can't always be trusted"
property, currently reachable only through CRM because CRM's most
recent filing has it and nobody queries NVDA's 12-year-old data.

**Chosen fix over two rejected alternatives** (real fork, presented to
the user via `AskUserQuestion`): matching on the end date's calendar
year holds for all 5 tracked companies (each names its fiscal year
after the year its period ends in) and is a no-op for the 4 companies
whose raw `fy` was already correct — and, unlike special-casing CRM,
also closes NVDA's identical latent quirk in its own old filings.
Rejected: special-casing CRM's known offset (doesn't generalize, reads
as an unexplained hack later); deriving an end-date window from
`companies.json`'s `fiscal_year_end_month` (bigger surface area, would
touch the currently-correct quarterly path, re-purposes a field whose
only prior use was reverted).

**A second, necessary fix found while designing this**: `get_metric()`'s
return dict returned the same unreliable raw `fy` regardless of how the
entry was actually matched. `formulas.get_yoy_growth()` anchors on that
returned value to request the prior period as `fiscal_year - 1` (by
design, to avoid its own date arithmetic). Fixing only `_pick_entry`
would have turned CRM's annual `get_yoy_growth` from a clean `None`
failure today into a silent wrong answer: comparing the real FY2026
value against the real FY2024 value (a 2-year gap) instead of FY2025,
since the returned (still-wrong) `fiscal_year: 2025` would compute
`2025 - 1 = 2024`. `_resolved_fiscal_year()` is applied at both call
sites specifically so this stays self-consistent.

**A third fix, caught by an independent review of the plan itself**
before any code was written: broadening the annual match from an exact
raw `fy` tag to "any entry whose end date falls in this calendar year"
widens the candidate pool, and CRM's own historical data has real cases
of one `end` date reported under 2-3 different raw `fy` tags across
separate filings with materially different (restated) values (e.g.
`end: "2017-01-31"` appears under `fy: 2017`, `2018`, and `2019`, the
last restated). The original `_pick_entry`'s `max(candidates, key=lambda
e: e["end"])` didn't disambiguate same-`end` ties at all. Fixed by
extending the sort key to `(e["end"], e.get("filed") or "")`, mirroring
`_pick_entry_by_end_date`'s own already-established "most-recently-
filed wins" convention for the identical situation.

## Files touched

- `xbrl_facts.py` — new `_resolved_fiscal_year()` helper; `_pick_entry` matches on it instead of the raw `fy` tag, and its final tiebreak now includes `filed`; `get_metric`'s return dict and docstring.
- `tests/test_xbrl_facts.py` — new CRM-shaped fixtures (`CRM_OPERATING_INCOME_ENTRIES`, `CRM_RESTATED_TIE_ENTRIES`) and 6 new tests.
- `tests/test_formulas.py` — new CRM-shaped fixtures and 1 new test exercising the fix through the ratio-combining layer.
- `tests/manual/verify_crm_fiscal_year_lookup.py` — new live-data repro script.

## Verification

- Full unit test suite: 676 passing (up from 669), including the 7 new tests.
- `ruff`/`pyright` scoped to changed lines: `xbrl_facts.py` and the new manual script are fully clean; new test lines fixed by hand where flagged (added `assert ... is not None` guards); pre-existing baseline violations in both test files (documented E501 single-line-fixture-dict style, and this project's already-tracked `reportOptionalSubscript` test-file baseline) left untouched on lines this change didn't add or modify.
- Manual live-repro script (`tests/manual/verify_crm_fiscal_year_lookup.py`), run against the real cached CRM data: reproduced the bug before the fix (`[BUG]` on the `fiscal_year=2026` lookup for `operating_income`/`operating_margin`/`gross_margin`, and via the `call_get_financial_fact` tool entry point); confirmed fixed after (`[FIXED]` on all four checks, including the `get_yoy_growth` self-consistency check — chaining now correctly lands on CRM's real FY2025 revenue, $37.895B, not FY2024).
- Live eval spot-check (`eval_harness.py --backend gemini`, the 3 ranking questions): **3/3 passed**, all with a citation marker and zero unverified citations. `five-company-operating-margin-ranking-fy2025` (the exact question the bug report cited) now correctly identifies Salesforce at 20.1%. `five-company-gross-margin-ranking-fy2025` correctly identifies Palantir at 82.4% (not affected by this bug, but confirms no regression). `five-company-net-margin-ranking-fy2025` correctly identifies NVIDIA at 55.6%.

## Related

Closes `BACKLOG.md`'s CRM fiscal-year-lookup item, referenced from
`docs/decisions/2026-09-16-final-turn-safety-net.md`'s residual-risk
note. One new backlog item filed from this fix's own review process
(see `BACKLOG.md`'s "From the 2026-09-16 crm-fiscal-year-lookup-fix"
section): the historical pre-2015 CRM/NVDA restated-value tiebreak isn't
exhaustively audited beyond the currently-reachable current-year case.
Separately, the still-open, untouched 3+-company `compare_financial_metric`
routing item (`BACKLOG.md`, from the 2026-09-14 fix) is unaffected by
this fix: CRM's data is now resolvable when queried directly, but that
doesn't change whether the model chooses to call `compare_financial_metric`
at all for a ranking question.
