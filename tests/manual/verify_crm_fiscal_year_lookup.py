"""
Live-data verification of the CRM annual fiscal-year lookup bug
(BACKLOG.md) -- run BEFORE the xbrl_facts.py fix lands, to reproduce the
bug, and again AFTER, to confirm it's gone. See
docs/decisions/2026-09-16-crm-fiscal-year-lookup-fix.md.

Exactly the CLAUDE.md live-code carve-out (xbrl_facts.py is listed
live-only) -- but no new network call is needed here: the bug and its
fix are both about how _pick_entry/get_metric interpret the SEC data
already cached on disk in xbrl_cache/CRM_*.json (fetched once, real).
Whether the raw `fy` tag on a real filing can be trusted is a property
of that real data, not something a synthetic fixture can substitute for
with the same confidence -- confirmed during design that CRM's most
recent 10-K (filed 2026-03-02, period ending 2026-01-31) self-tags
`fy: 2025`, one year behind Salesforce's own "fiscal year 2026" label,
and that the identical pattern appears in CRM's own 2010-2014 filings
and NVDA's own 2011-2014 filings.

Drives `xbrl_facts.get_metric`/`get_ratio` and `agent.call_get_financial_fact`
directly against the real cache (no mocking) for the exact values named
in the bug report:
  1. get_metric('CRM', 'operating_income', fiscal_year=2026, fiscal_period='FY')
  2. get_ratio('CRM', 'operating_margin'/'gross_margin', fiscal_year=2026, fiscal_period='FY')
  3. call_get_financial_fact for the same, the model-facing entry point
Each compared against the already-working period_end_date="2026-01-31"
equivalent, which must keep returning the same value it does today.

Informational, not a hard assert-and-exit-1 gate (same spirit as this
project's other verify_*.py scripts) -- but this one prints an explicit
[BUG]/[FIXED]/[REGRESSION] verdict per case since the expected values are
exact, known numbers (20.1%/77.7%), not a judgment call.

Usage (from the repo root):
    python tests/manual/verify_crm_fiscal_year_lookup.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from agent import call_get_financial_fact
from formulas import get_ratio
from xbrl_facts import get_metric

EXPECTED_OPERATING_MARGIN = 20.1
EXPECTED_GROSS_MARGIN = 77.7
CRM_FY2026_END_DATE = "2026-01-31"


def check_raw_metric():
    print("\n[1] xbrl_facts.get_metric -- raw operating_income")
    by_fiscal_year = get_metric("CRM", "operating_income", fiscal_year=2026, fiscal_period="FY")
    by_end_date = get_metric("CRM", "operating_income", period_end_date=CRM_FY2026_END_DATE)
    print(f"  by fiscal_year=2026: {by_fiscal_year}")
    print(f"  by period_end_date={CRM_FY2026_END_DATE}: {by_end_date}")

    if by_end_date is None:
        print("  [PROBLEM] the ALREADY-WORKING period_end_date path returned None -- cache may be stale/missing")
        return
    if by_fiscal_year is None:
        print("  [BUG] fiscal_year=2026 lookup returns None while period_end_date resolves it")
    elif by_fiscal_year["value"] == by_end_date["value"] and by_fiscal_year.get("fiscal_year") == 2026:
        print("  [FIXED] fiscal_year=2026 lookup now resolves to the same value, fiscal_year echoed back correctly")
    else:
        print(f"  [REGRESSION] fiscal_year=2026 lookup resolved to something unexpected: {by_fiscal_year}")


def check_ratio(metric: str, expected: float):
    print(f"\n[2] formulas.get_ratio -- {metric}")
    by_fiscal_year = get_ratio("CRM", metric, fiscal_year=2026, fiscal_period="FY")
    by_end_date = get_ratio("CRM", metric, period_end_date=CRM_FY2026_END_DATE)
    print(f"  by fiscal_year=2026: {by_fiscal_year}")
    print(f"  by period_end_date={CRM_FY2026_END_DATE}: {by_end_date}")

    if by_fiscal_year is None:
        print(f"  [BUG] fiscal_year=2026 lookup returns None (expected {expected})")
    elif by_fiscal_year["value"] == expected:
        print(f"  [FIXED] fiscal_year=2026 lookup resolves to {expected}, matching the expected value")
    else:
        print(f"  [REGRESSION] fiscal_year=2026 lookup resolved to {by_fiscal_year['value']}, expected {expected}")


def check_agent_tool_entry_point():
    print("\n[3] agent.call_get_financial_fact -- the model-facing entry point")
    for metric, expected in [("operating_margin", EXPECTED_OPERATING_MARGIN), ("gross_margin", EXPECTED_GROSS_MARGIN)]:
        args = {"ticker": "CRM", "metric": metric, "fiscal_year": 2026, "fiscal_period": "FY"}
        result = call_get_financial_fact(args)
        print(f"  {metric}: {result}")
        if result is None:
            print(f"  [BUG] {metric} returns None via the tool entry point (expected {expected})")
        elif result["value"] == expected:
            print(f"  [FIXED] {metric} resolves to {expected} via the tool entry point")
        else:
            print(f"  [REGRESSION] {metric} resolved to {result['value']}, expected {expected}")


def check_yoy_growth_chaining_is_still_correct():
    # The second, non-obvious risk found while designing the fix: fixing
    # ONLY _pick_entry (and not get_metric's returned "fiscal_year" field)
    # would make get_yoy_growth silently compare the wrong two years for
    # CRM, since it anchors its own "prior period" request on the
    # returned fiscal_year value. Confirms the actual shipped fix keeps
    # this self-consistent, not just that the direct lookup works.
    print("\n[4] Real-data check: does get_metric's returned fiscal_year stay self-consistent for chaining?")
    current = get_metric("CRM", "revenue", fiscal_year=2026, fiscal_period="FY")
    if current is None:
        print("  [BUG] can't even get the current period, skipping the chaining check")
        return
    reported_fy = current.get("fiscal_year")
    print(f"  current period (requested fiscal_year=2026): value={current['value']}, reported fy={reported_fy}")
    if reported_fy != 2026:
        print(f"  [BUG] returned fiscal_year is {reported_fy}, not 2026 -- yoy_growth chaining would break")
        return
    prior = get_metric("CRM", "revenue", fiscal_year=reported_fy - 1, fiscal_period="FY")
    print(f"  prior period (fiscal_year={reported_fy - 1}): {prior}")
    if prior is None:
        print("  [INFO] no prior-period data cached to compare against")
    else:
        print(f"  [FIXED] chaining resolves to a real prior-period value ({prior['value']}) at the correct label")


def main():
    check_raw_metric()
    check_ratio("operating_margin", EXPECTED_OPERATING_MARGIN)
    check_ratio("gross_margin", EXPECTED_GROSS_MARGIN)
    check_agent_tool_entry_point()
    check_yoy_growth_chaining_is_still_correct()
    print(
        "\nDone. Before the fix, expect [BUG] on cases 1-3 and possibly 4. "
        "After, expect [FIXED] on all, with the period_end_date-path values unchanged."
    )


if __name__ == "__main__":
    main()
