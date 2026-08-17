"""
Shared numeric extraction/normalization, used by both eval_harness.py's
numeric grading and agent.py's citation-verification pass.

Split out from eval_harness.py rather than having agent.py import from
it (or vice versa) -- eval_harness.py already imports agent.run_agent,
so agent.py importing back from eval_harness.py would be circular.
"""

import re

# Matches an optional "$", a number (with optional thousands-commas and
# decimal point), and an optional trailing unit word or "%". Deliberately
# broad — it's fine to pick up spurious candidates (e.g. a "[1]" citation
# marker parsing as the number 1); callers only need the *correct* value
# to appear somewhere among the candidates, extra noise is harmless.
#
# The leading digit group is `\d+`, not `\d{1,3}` — capping it at 3
# looked reasonable for comma-grouped numbers ("1,234,567" does start
# with 1-3 digits) but silently broke on a bare, comma-less run of many
# digits (e.g. "109417000000.0", exactly what xbrl_facts.py's raw float
# values format as): regex alternation tries branches left-to-right and
# stops at the first one that matches at all, not the longest overall
# match, so `\d{1,3}` would greedily claim just "109" and leave "417",
# "000", "000.0" as separate, wrong candidates instead of one correct
# number. Found this via agent.py's verify_citations() tests failing
# against real XBRL-sourced result text, not by inspection — every
# existing caller up to that point only ever ran this against a model's
# own answer text, which is naturally comma-grouped or unit-suffixed and
# never triggered the bug.
# `(?<!\w)` immediately before the digit group rejects a number glued
# to a preceding letter or digit ("Q3" -> was matching "3", "FY2026" ->
# was matching "026" since a failed lookbehind at one start position
# just makes the regex engine retry the next position inside the same
# digit run — \w excludes digits too, so every retry position inside a
# glued alphanumeric run also fails, correctly rejecting the whole
# token instead of leaking a fragment). A real dollar figure or percent
# is always preceded by whitespace, "$", or start-of-string, never a
# letter, so this doesn't affect genuine matches. Found via
# verify_citations() flagging "Q3" as a spurious claimed value of 3.
NUMBER_PATTERN = re.compile(
    r"\$?\s*(?<!\w)(\d+(?:,\d{3})*(?:\.\d+)?)\s*(billion|million|thousand|percent)?\s*(%)?",
    re.IGNORECASE,
)

UNIT_MULTIPLIERS = {"thousand": 1e3, "million": 1e6, "billion": 1e9}


def extract_numbers(text: str) -> list[tuple[float, str]]:
    """Return every (value, unit) candidate found in text. unit is one of
    'raw', 'thousand', 'million', 'billion', 'percent'."""
    candidates = []
    for match in NUMBER_PATTERN.finditer(text):
        raw_value, unit_word, percent_sign = match.groups()
        try:
            value = float(raw_value.replace(",", ""))
        except ValueError:
            continue
        if percent_sign or (unit_word and unit_word.lower() == "percent"):
            unit = "percent"
        elif unit_word:
            unit = unit_word.lower()
        else:
            unit = "raw"
        candidates.append((value, unit))
    return candidates


def normalize(value: float, unit: str) -> tuple[str, float]:
    """Collapse a (value, unit) into a (category, comparable_number) pair.
    'percent' is its own category since it's not on the same scale as a
    dollar/count figure — 20 (percent) and 20 (raw) are not the same
    claim and must never compare equal."""
    if unit == "percent":
        return "percent", value
    return "scale", value * UNIT_MULTIPLIERS.get(unit, 1.0)
