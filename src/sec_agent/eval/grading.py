"""
Grading helpers for the v2 question types: the `text` matcher, the judge
criteria filled in for refusal and clarify questions, and company
attribution, which takes a claimed value's company from the ticker of the
source the claim cites rather than from the answer's prose. Pure
functions, so every rule is testable offline and re-gradable from stored
runs.
"""

import re
from collections.abc import Callable

from sec_agent.agent.calculate import calculation_operand_indices
from sec_agent.agent.citations import ANY_CITATION_BRACKET
from sec_agent.prompts.agent_messages import CALCULATION_PLACEHOLDER
from sec_agent.prompts.judge_criteria import CLARIFY_CRITERIA, QUESTION_DETAIL, REFUSAL_CRITERIA
from sec_agent.sources.companies import COMPANIES
from sec_agent.verification.numeric_utils import match_tolerance, normalize

_MONTHS = {
    m: i
    for i, names in enumerate(
        (
            ("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"), ("may",),
            ("jun", "june"), ("jul", "july"), ("aug", "august"), ("sep", "sept", "september"),
            ("oct", "october"), ("nov", "november"), ("dec", "december"),
        ),
        start=1,
    )
    for m in names
}
_MONTH_NAMES = "|".join(sorted(_MONTHS, key=len, reverse=True))
_ORDINAL = r"(?:st|nd|rd|th)?"
_WORD_DATE = re.compile(r"\b(" + _MONTH_NAMES + r")\.?\s+(\d{1,2})" + _ORDINAL + r",?\s+(\d{4})\b", re.I)
# The lookbehind keeps a decimal's fraction ("5.25 June 2024") from reading as a day.
_DAY_FIRST_DATE = re.compile(
    r"(?<!\d[.,])\b(\d{1,2})" + _ORDINAL + r"\s+(" + _MONTH_NAMES + r")\.?,?\s+(\d{4})\b", re.I
)
_SLASH_DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")


def _iso_date(year: str, month: int, day: str) -> str:
    return f"{year}-{month:02d}-{int(day):02d}"


def normalize_text(text: str) -> str:
    """Dates as ISO, then lowercase words separated by single spaces with
    punctuation dropped, padded with a space at each end for whole-word
    containment checks."""
    text = _WORD_DATE.sub(lambda m: _iso_date(m.group(3), _MONTHS[m.group(1).lower()], m.group(2)), text)
    text = _DAY_FIRST_DATE.sub(lambda m: _iso_date(m.group(3), _MONTHS[m.group(2).lower()], m.group(1)), text)
    text = _SLASH_DATE.sub(lambda m: _iso_date(m.group(3), int(m.group(1)), m.group(2)), text)
    words = re.sub(r"[^0-9a-z]+", " ", text.lower()).split()
    return f" {' '.join(words)} "


def text_matches(answer: str, accepted: list[str]) -> bool:
    """Whether any accepted variant appears in the answer as whole words,
    ignoring case, punctuation and date format."""
    normalized = normalize_text(ANY_CITATION_BRACKET.sub(" ", answer))
    return any(normalize_text(variant) in normalized for variant in accepted)


def judge_criteria_for(q: dict) -> str:
    """The judge criteria for a refusal or clarify question: its kind's
    template, plus the question's own `criteria` detail when it has one.
    Templates are filled by keyword, never pre-formatted, since question
    text can itself contain braces."""
    if q["type"] == "refusal":
        criteria = REFUSAL_CRITERIA[q["refusal_kind"]]
    else:
        criteria = CLARIFY_CRITERIA.format(readings="; ".join(q["readings"]))
    if q.get("criteria"):
        criteria += QUESTION_DETAIL.format(criteria=q["criteria"])
    return criteria


def _source_tickers(index: object, all_results: list[dict], seen: set[int]) -> set[str]:
    """The companies behind source `index` (1-based): its own ticker, or
    for a calculate result the union over its two operands. `seen` stops
    a cycle; a non-integer index (a bool is an int, so True would pass
    for 1) or one outside the results has no company."""
    if not isinstance(index, int) or isinstance(index, bool):
        return set()
    if not 1 <= index <= len(all_results) or index in seen:
        return set()
    seen.add(index)
    source = all_results[index - 1]
    if source["metadata"].get("chunk_index") == "calculated":
        operands = calculation_operand_indices(source)
        return set().union(*(_source_tickers(i, all_results, seen) for i in operands or ()))
    ticker = source["metadata"].get("ticker")
    return {ticker} if ticker and ticker != CALCULATION_PLACEHOLDER else set()


def claim_attributions(claims: list[dict], all_results: list[dict]) -> list[dict]:
    """One {citation_index, value, unit, quote, tickers} per numeric claim,
    where `tickers` (sorted) are the companies behind the source the claim
    cites: one for a filing source, both for a cross-company calculation,
    none for a source with no ticker or an index outside the results. A
    claim without both a value and a unit is qualitative or malformed and
    is skipped: the withheld and replay paths see claims the gate never
    accepted."""
    attributions = []
    for claim in claims:
        if claim.get("value") is None or claim.get("unit") is None:
            continue
        index = claim.get("citation_index")
        attributions.append(
            {
                "citation_index": index,
                "value": claim["value"],
                "unit": claim["unit"],
                "quote": claim.get("quote"),
                "tickers": sorted(_source_tickers(index, all_results, set())),
            }
        )
    return attributions


def value_matcher(expected_value: float, expected_unit: str, tolerance: float | None) -> Callable[[float, str], bool]:
    """The graders' value-match rule: a (value, unit) matches the expected
    one when it's in the same unit category (a percent never matches a
    dollar amount) and within the relative `tolerance` of it."""
    expected_category, expected_norm = normalize(expected_value, expected_unit)
    limit = match_tolerance(expected_norm, tolerance)

    def matches(value: float, unit: str) -> bool:
        category, norm = normalize(value, unit)
        return category == expected_category and abs(norm - expected_norm) <= limit

    return matches


def _claimed_for(
    companies: set[str], value: float, unit: str, attributions: list[dict], tolerance: float | None
) -> bool:
    """Whether some attribution claims (value, unit) from exactly `companies`."""
    matches = value_matcher(value, unit, tolerance)
    return any(set(a["tickers"]) == companies and matches(a["value"], a["unit"]) for a in attributions)


def entry_companies(entry: dict, question_tickers: list[str]) -> set[str]:
    """The companies a claim of an expected entry's value must come from:
    its own `companies` list, else its label when that is exactly a
    ticker, else the question's (a period or segment label). Labels are
    never parsed further; an entry that needs another set names it."""
    if "companies" in entry:
        return set(entry["companies"])
    return {entry["ticker"]} if entry["ticker"] in COMPANIES else set(question_tickers)


def misattributed(
    expected: list[dict], attributions: list[dict], tolerance: float | None, question_tickers: list[str]
) -> list[str]:
    """The `expected` entries no claim states from exactly their
    companies (see entry_companies): a gap between two banks must cite a
    calculation over both, and a bank's own figure a source of its own."""
    failed = []
    for entry in expected:
        companies = entry_companies(entry, question_tickers)
        if not _claimed_for(companies, entry["expected_value"], entry["expected_unit"], attributions, tolerance):
            failed.append(f"{entry['ticker']} ({entry['expected_value']} {entry['expected_unit']})")
    return failed


def forbidden_hits(
    forbidden: list[dict], attributions: list[dict], default_ticker: str | None, tolerance: float | None
) -> list[str]:
    """The trap values a claim attributes to the company they're charged
    to (the entry's own ticker, else the question's) alone. A claim of
    unknown or mixed companies never hits."""
    hits = []
    for trap in forbidden:
        ticker = trap.get("ticker", default_ticker)
        if ticker is not None and _claimed_for({ticker}, trap["value"], trap["unit"], attributions, tolerance):
            hits.append(f"{ticker} ({trap['value']} {trap['unit']})")
    return hits
