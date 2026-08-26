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

Usage (from the repo root):
    python tests/manual/verify_period_labels.py
"""

import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from period_labels import fiscal_quarter, fiscal_year_label
from xbrl_facts import _ANNUAL_DURATION_DAYS, _duration_days, _tag_for, fetch_concept

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


def verify_against_xbrl() -> tuple[int, int, list[str]]:
    """A second, independent cross-check on the same assumption verify()
    checks above, but against SEC's own structured XBRL data instead of
    filing prose -- a stronger signal, not a replacement: every
    10-K-form companyconcept entry's own `end` date IS that company's
    fiscal year end for that year, straight from SEC, with no regex, no
    dependency on a specific comparative-quarter phrasing appearing in
    the text, and no "inconclusive" case the way verify() has when no
    self-description is found. Complements verify() rather than
    replacing it -- that check also separately validates reportDate
    metadata correctness, a concern this one doesn't cover, and this one
    only covers companies/years we have cached or fetchable XBRL data
    for.

    Uses whichever tag "gross_profit" resolves to per company --
    xbrl_facts.py's own DEFAULT_METRIC_TAGS comment already confirms all
    5 covered companies tag GrossProfit directly through their latest
    filings (unlike "revenue", which needs a per-company override), so
    it needs no override handling here; any similarly well-covered
    metric would do.

    Found live, not anticipated: filtering on `form == "10-K"` alone
    isn't enough -- SEC's older (pre-~2020) XBRL data has real quality
    issues where clearly quarter-length entries (e.g. NVDA's
    2009-04-26/07-26/10-25, ~90 days apart) are tagged with form="10-K"
    instead of "10-Q", producing spurious mismatches across all 5
    companies on the first run of this function. The same
    _ANNUAL_DURATION_DAYS duration filter xbrl_facts.py's own
    _pick_entry() already relies on for exactly this kind of
    disambiguation fixes it here too -- restricting to genuinely
    year-length entries, not just ones labeled "10-K"."""
    companies = _load_companies_with_fy_end()
    checked = 0
    confirmed = 0
    problems = []

    for ticker, info in companies.items():
        fy_end_month = info["fiscal_year_end_month"]
        tag = _tag_for(ticker, "gross_profit")
        data = fetch_concept(ticker, tag)
        if data is None:
            problems.append(f"{ticker}: no {tag} data available (inconclusive)")
            continue
        annual_ends = {
            e["end"]
            for e in data.get("units", {}).get("USD", [])
            if e.get("form") == "10-K" and _ANNUAL_DURATION_DAYS[0] <= _duration_days(e) <= _ANNUAL_DURATION_DAYS[1]
        }
        if not annual_ends:
            problems.append(f"{ticker}: no 10-K entries found for {tag} (inconclusive)")
            continue
        checked += 1
        mismatches = sorted(end for end in annual_ends if date.fromisoformat(end).month != fy_end_month)
        if not mismatches:
            confirmed += 1
        else:
            problems.append(
                f"{ticker}: fiscal_year_end_month={fy_end_month} but {tag}'s 10-K entries include "
                f"end date(s) {mismatches} which don't fall in that month -- MISMATCH"
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

    print("\n" + "-" * 60)
    x_checked, x_confirmed, x_problems = verify_against_xbrl()
    print(f"\nChecked {x_checked} companies, {x_confirmed} confirmed against their own XBRL 10-K data.\n")
    x_mismatches = [p for p in x_problems if "MISMATCH" in p]
    x_inconclusive = [p for p in x_problems if "MISMATCH" not in p]
    if x_mismatches:
        print(f"MISMATCHES ({len(x_mismatches)}) -- fiscal_year_end_month may be wrong:")
        for p in x_mismatches:
            print(f"  {p}")
    if x_inconclusive:
        print(f"\nInconclusive ({len(x_inconclusive)}) -- no XBRL data available, not a red flag:")
        for p in x_inconclusive:
            print(f"  {p}")
    if not x_mismatches:
        print("No mismatches found.")


if __name__ == "__main__":
    main()
