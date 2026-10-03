"""
Which filings a search query names by period. A query that names a
period ("the quarter ended April 27, 2025", "Q1 fiscal 2026", "FY26") is
searched only within those filings' chunks, so other periods' near-identical
tables can't crowd the candidate pool. Pure: the caller supplies the filing
list and each company's fiscal-year-end month.
"""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date

from sec_agent.sources.period_labels import fiscal_quarter, fiscal_year_label

_MONTHS = {
    name: number
    for number, name in enumerate(
        ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
         "november", "december"],
        start=1,
    )
}
_DATE_RE = re.compile(r"\b(" + "|".join(_MONTHS) + r")\s+(\d{1,2}),?\s+(\d{4})", re.I)
_FY_RE = re.compile(r"\b(?:fiscal(?:\s+year)?|fy)\s*'?(\d{4}|\d{2})\b", re.I)
_QUARTER_RE = re.compile(r"\b(?:q([1-4])|(first|second|third|fourth)\s+(?:fiscal\s+)?quarter)\b", re.I)
_ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4}
_TWO_DIGIT_YEAR_LIMIT = 100  # "FY26" names fiscal 2026

# A 10-Q's period end and the date a query names for it can differ by a few
# days (a 52/53-week fiscal calendar ends on a weekday, not a month end).
_DATE_TOLERANCE_DAYS = 7

Filing = tuple[str, str, str]  # (ticker, form, reportDate)


@dataclass(frozen=True)
class Scope:
    """report_dates: the matched filings' report dates, sorted; empty when
    none matched. reason: "dates" when some matched; "no_match" when the
    query names a period no filing has; "no_date" when it names none.
    invalid_dates: explicit dates that aren't real calendar dates, skipped."""

    report_dates: tuple[str, ...]
    reason: str
    invalid_dates: tuple[str, ...]


def filing_list(metadatas: Iterable[Mapping], ticker: str | None) -> list[Filing]:
    """One (ticker, form, reportDate) per filing, in first-seen order,
    limited to `ticker` when one is given. A ticker'd search must match
    dates against its own company's filings only: another company's report
    date within the tolerance would otherwise scope the query to a filing
    the ticker filter then excludes."""
    seen: dict[Filing, None] = {}
    for m in metadatas:
        if ticker is None or m["ticker"] == ticker:
            seen[(m["ticker"], m["form"], m["reportDate"])] = None
    return list(seen)


def _explicit_dates(query: str, filings: list[Filing]) -> tuple[set[str], bool, list[str]]:
    """Report dates within the tolerance of any "Month D, YYYY" in the
    query, whether any real date was named, and the named dates that aren't
    real calendar dates (query text is untrusted: "September 31")."""
    dates: set[str] = set()
    named = False
    invalid = []
    for match in _DATE_RE.finditer(query):
        month, day, year = match.groups()
        try:
            target = date(int(year), _MONTHS[month.lower()], int(day))
        except ValueError:
            invalid.append(match.group(0))
            continue
        named = True
        for _, _, report_date in filings:
            if abs((date.fromisoformat(report_date) - target).days) <= _DATE_TOLERANCE_DAYS:
                dates.add(report_date)
    return dates, named, invalid


def _fiscal_dates(
    query: str, filings: list[Filing], fiscal_year_end_months: Mapping[str, int]
) -> tuple[set[str], bool]:
    """Report dates of the first fiscal year the query names: its annual
    report, or with a quarter named too, that quarter's report. Only the
    first year and quarter count, and whether a year was named at all. A
    filing whose company has no fiscal-year end is skipped: its fiscal
    periods can't be told."""
    fy_match = _FY_RE.search(query)
    if not fy_match:
        return set(), False
    fiscal_year = int(fy_match.group(1))
    if fiscal_year < _TWO_DIGIT_YEAR_LIMIT:
        fiscal_year += 2000
    quarter = None
    q_match = _QUARTER_RE.search(query)
    if q_match:
        quarter = int(q_match.group(1)) if q_match.group(1) else _ORDINALS[q_match.group(2).lower()]
    dates = set()
    for ticker, form, report_date in filings:
        end_month = fiscal_year_end_months.get(ticker)
        if end_month is None:
            continue
        d = date.fromisoformat(report_date)
        if fiscal_year_label(end_month, d) != fiscal_year:
            continue
        if (quarter is None and form == "10-K") or (quarter is not None and fiscal_quarter(end_month, d) == quarter):
            dates.add(report_date)
    return dates, True


def query_report_dates(
    query: str, filings: list[Filing], fiscal_year_end_months: Mapping[str, int]
) -> Scope:
    """The filings `query` names: explicit dates first, and only when none of
    them matches a filing, the first fiscal year (and quarter) it names."""
    dates, named_date, invalid = _explicit_dates(query, filings)
    named_year = False
    if not dates:
        dates, named_year = _fiscal_dates(query, filings, fiscal_year_end_months)
    if dates:
        reason = "dates"
    else:
        reason = "no_match" if named_date or named_year else "no_date"
    return Scope(tuple(sorted(dates)), reason, tuple(invalid))
