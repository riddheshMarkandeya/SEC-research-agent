"""
One-time (re-runnable) verification: cross-checks period_labels.py's
computed fiscal year/quarter for every already-ingested filing against
that filing's OWN self-description of its reporting period, found by
searching the raw ingested text.

Why this exists: period_labels.py assumes each company's fiscal-year-end
month (companies.json's fiscal_year_end_month) is constant. That's true
for all 5 companies today, but it's an assumption, not a guarantee — a
company can change its fiscal year end (via a transition-period filing),
and if that ever happened without companies.json being updated,
period_labels.py would silently compute a confidently WRONG period label
and bake it into the retrieval index, which is worse than no label at
all. This script is the safeguard: instead of trusting the assumption,
it checks it against ~25 independent, real data points (what each
filing says about itself) every time it's run — e.g. after adding a new
company or ingesting new filings.

Two checks per filing, both deliberately narrow to avoid false
mismatches from a filing's own backward/comparative references to OTHER
periods (which are common — MD&A prose is full of "X compared to Y"
year-over-year discussion, and risk factors sometimes mention unrelated
historical quarters, e.g. "we incurred losses through the third quarter
of 2022"). An earlier, naive version of this script that searched the
whole document for any "Nth quarter of YYYY" mention produced 11 false
mismatches, all traced to exactly this kind of noise — a lesson worth
keeping: the fix was to require the *comparative* construction ("the Nth
quarter of fiscal year Y compared to/with the Nth quarter of fiscal year
Y-1"), which only appears when a filing is describing ITS OWN period
against the prior year, not a random reference to some other quarter.

  - 10-Q: search (anchored past the leading XBRL taxonomy junk that
    chunk_documents.py also strips, via the same "SECURITIES AND
    EXCHANGE COMMISSION" boilerplate anchor) for "Nth quarter of [fiscal
    year] Y compared to/with the Nth quarter of [fiscal year] Y-1" — the
    first-mentioned (Y, quarter) is unambiguously the filing's own
    current period, and the Y-1 requirement filters out unrelated
    mentions of other quarters.
  - 10-K: search the same anchored region for "for the (quarterly
    period|fiscal year) ended DATE" and compare DATE to reportDate.

Usage:
    python verify_period_labels.py
"""

import json
import re
from datetime import date, datetime
from pathlib import Path

from period_labels import fiscal_quarter, fiscal_year_label

DATA_DIR = Path("./data")
ANCHOR = "SECURITIES AND EXCHANGE COMMISSION"

ORDINAL_TO_NUMBER = {"first": 1, "second": 2, "third": 3, "fourth": 4}

# Requires the comparative "compared to/with the same quarter last year"
# construction -- this is what makes the match trustworthy as a
# self-description rather than an unrelated mention. See module
# docstring for why a plain "Nth quarter of YYYY" search wasn't enough.
COMPARATIVE_QUARTER_PATTERN = re.compile(
    r"(first|second|third|fourth)\s+quarter\s+of\s+(?:fiscal\s+year\s+)?(\d{4})\s+compared\s+(?:to|with)\s+"
    r"the\s+(?:first|second|third|fourth)\s+quarter\s+of\s+(?:fiscal\s+year\s+)?(\d{4})",
    re.IGNORECASE,
)
ANNUAL_PATTERN = re.compile(
    # Cover-page period declarations sometimes have a line break between
    # the day number and the comma (an artifact of how the original HTML
    # table/paragraph structure got converted to text), so the day and
    # comma are separated by \s* rather than assumed adjacent.
    r"for\s+the\s+fiscal\s+year\s+ended\s+([A-Za-z]+\s+\d{1,2}\s*,\s+\d{4})",
    re.IGNORECASE,
)


def _load_companies_with_fy_end() -> dict:
    with open("companies.json", encoding="utf-8") as f:
        return json.load(f)


def verify() -> tuple[int, int, list[str]]:
    companies = _load_companies_with_fy_end()
    checked = 0
    confirmed = 0
    problems = []

    for meta_path in sorted(DATA_DIR.glob("*/*_meta.json")):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        ticker = meta["ticker"]
        form = meta["form"]
        report_date = date.fromisoformat(meta["reportDate"])
        fy_end_month = companies[ticker]["fiscal_year_end_month"]
        text_path = meta_path.with_name(meta_path.name.replace("_meta.json", "_text.txt"))
        text = text_path.read_text(encoding="utf-8")
        anchor_pos = text.find(ANCHOR)
        searchable = text[anchor_pos:] if anchor_pos != -1 else text

        if form == "10-Q":
            computed_q = fiscal_quarter(fy_end_month, report_date)
            computed_fy = fiscal_year_label(fy_end_month, report_date)
            match = COMPARATIVE_QUARTER_PATTERN.search(searchable)
            checked += 1
            if not match:
                problems.append(f"{ticker} {meta['accessionNumber']}: no self-description found (inconclusive)")
                continue
            stated_q = ORDINAL_TO_NUMBER[match.group(1).lower()]
            stated_fy = int(match.group(2))
            prior_fy = int(match.group(3))
            if prior_fy != stated_fy - 1:
                problems.append(
                    f"{ticker} {meta['accessionNumber']}: matched non-YoY comparison "
                    f"(FY{stated_fy} vs FY{prior_fy}) -- skipping, inconclusive"
                )
                continue
            if (stated_q, stated_fy) == (computed_q, computed_fy):
                confirmed += 1
            else:
                problems.append(
                    f"{ticker} {meta['accessionNumber']}: filing says Q{stated_q} FY{stated_fy}, "
                    f"we computed Q{computed_q} FY{computed_fy} -- MISMATCH"
                )
        elif form == "10-K":
            checked += 1
            # A filing states "for the fiscal year ended DATE" multiple
            # times -- once for its own current period, and often again
            # as a backward reference to the PRIOR year's 10-K (e.g. "our
            # Annual Report... for the fiscal year ended January 26,
            # 2025"), which can appear earlier in the document than the
            # genuine current-period declaration. Taking only the first
            # match produced 3 false "MISMATCH"es, every one off by
            # exactly one year in the same direction -- checking for
            # membership across ALL matches instead of assuming the
            # first one is authoritative fixed all 3.
            all_dates = {
                datetime.strptime(re.sub(r"\s*,\s*", ", ", re.sub(r"\s+", " ", m.group(1))), "%B %d, %Y").date()
                for m in ANNUAL_PATTERN.finditer(searchable)
            }
            if not all_dates:
                problems.append(f"{ticker} {meta['accessionNumber']}: no self-description found (inconclusive)")
                continue
            if report_date in all_dates:
                confirmed += 1
            else:
                problems.append(
                    f"{ticker} {meta['accessionNumber']}: filing states fiscal year(s) ended {sorted(all_dates)}, "
                    f"none match our reportDate metadata {report_date} -- MISMATCH"
                )

    return checked, confirmed, problems


def main():
    checked, confirmed, problems = verify()
    print(f"Checked {checked} filings, {confirmed} confirmed against their own self-description.\n")
    mismatches = [p for p in problems if "MISMATCH" in p]
    inconclusive = [p for p in problems if "MISMATCH" not in p]
    if mismatches:
        print(f"MISMATCHES ({len(mismatches)}) -- fiscal_year_end_month may be wrong:")
        for p in mismatches:
            print(f"  {p}")
    if inconclusive:
        print(f"\nInconclusive ({len(inconclusive)}) -- no reliable self-description found, not a red flag:")
        for p in inconclusive:
            print(f"  {p}")
    if not mismatches:
        print("No mismatches found.")


if __name__ == "__main__":
    main()
