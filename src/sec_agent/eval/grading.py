"""
Grading helpers for the v2 question types: the `text` matcher and the
judge criteria filled in for refusal and clarify questions. Pure
functions, so every rule is testable offline and the text matcher is
re-gradable from stored runs.
"""

import re

from sec_agent.agent.citations import ANY_CITATION_BRACKET
from sec_agent.prompts.judge_criteria import CLARIFY_CRITERIA, QUESTION_DETAIL, REFUSAL_CRITERIA

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
