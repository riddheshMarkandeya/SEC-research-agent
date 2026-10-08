"""
Live verification of edgar_ingest's filing selection against the real SEC
submissions API, which no unit test can reach: which 10-K and 10-Q
filings each company gets, grouped by fiscal year, and how many
submissions pages were read to find them.

Every company should reach back to FY2024, with at least the counts in
EXPECTED_COUNTS (recorded 2026-10-06 for the first five, 2026-10-08 for the
rest; each new filing adds one), and CRM's FY2024 Q1 10-Q (period
2023-04-30) should be found on an older page: [GREEN]. A ticker with no
recorded count is [RED], so a newly added company can't pass unchecked.

Informational, like this project's other verify_*.py scripts: it prints a
verdict per company rather than exiting non-zero. About 40 SEC requests,
one per submissions page read.

Usage (from the repo root):
    python tests/manual/verify_filing_selection.py
"""

from collections import Counter
from datetime import date

from sec_agent.sources import edgar_ingest
from sec_agent.sources.companies import load_companies
from sec_agent.sources.period_labels import fiscal_year_label

EXPECTED_COUNTS = {
    "AAPL": 11, "MSFT": 12, "NVDA": 14, "CRM": 14, "PLTR": 10,
    "JPM": 10, "BAC": 10, "XOM": 10, "CAT": 10, "JNJ": 10, "TGT": 14, "WMT": 14,
}
CRM_FY2024_Q1_REPORT_DATE = "2023-04-30"


def main() -> None:
    all_green = True
    for ticker, info in load_companies().items():
        fyem = info["fiscal_year_end_month"]
        print(f"\n=== {ticker} (FYE month {fyem}) ===")
        selection = edgar_ingest.get_filing_list(info["cik"], fyem)
        filings = selection.filings
        print(f"  pages read: {selection.pages}, rows skipped as malformed: {selection.skipped_bad_row}")
        by_year = Counter(fiscal_year_label(fyem, date.fromisoformat(f["reportDate"])) for f in filings)
        forms = Counter(f["form"] for f in filings)
        print(f"  {len(filings)} filings, forms {dict(forms)}, by fiscal year {dict(sorted(by_year.items()))}")
        for f in sorted(filings, key=lambda f: f["reportDate"]):
            print(f"    {f['form']:5} period {f['reportDate']} filed {f['filingDate']} {f['accessionNumber']}")

        problems = []
        if 2024 not in by_year:
            problems.append("no FY2024 filing")
        if min(by_year, default=9999) < 2024:
            problems.append(f"a filing before FY2024 ({min(by_year)})")
        if len({f["accessionNumber"] for f in filings}) != len(filings):
            problems.append("a filing selected twice")
        if ticker not in EXPECTED_COUNTS:
            problems.append("no expected count recorded for this ticker")
        elif len(filings) < EXPECTED_COUNTS[ticker]:
            problems.append(f"count {len(filings)} < expected {EXPECTED_COUNTS[ticker]}")
        if ticker == "CRM" and not any(f["reportDate"] == CRM_FY2024_Q1_REPORT_DATE for f in filings):
            problems.append(f"CRM FY2024 Q1 10-Q ({CRM_FY2024_Q1_REPORT_DATE}) missing: older page not read")
        if problems:
            all_green = False
            print(f"  [RED] {'; '.join(problems)}")
        else:
            print("  [GREEN]")
    print(f"\nOverall: {'GREEN' if all_green else 'RED'}")


if __name__ == "__main__":
    main()
