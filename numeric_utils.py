"""
Shared numeric extraction/normalization, used by both eval_harness.py's
numeric grading and agent.py's citation-verification pass.

Split out from eval_harness.py rather than having agent.py import from
it (or vice versa) -- eval_harness.py already imports agent.run_agent,
so agent.py importing back from eval_harness.py would be circular.
"""

import difflib
import re
import unicodedata

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
#
# Negative-number support (2026-09-11, found missing entirely during a
# hand-rolled-complexity review): two signals, `sign` (a bare leading
# "-") and `open_paren`/`close_paren` (the accounting convention of
# wrapping a negative in parentheses, e.g. "$(1,234)"). Design grounded
# in the real ./chunks/*/*.jsonl corpus, not guessed -- grepped it before
# writing this: the actual format SEC filings use is a bare parenthesized
# number with the unit stated separately in a table caption ("(433)",
# "$(1,122)", "(2.5)%", "(237)%"), never a unit word glued INSIDE the
# parens -- so `close_paren` only needs to sit directly after the digit
# group, with `unit`/`pct` still free to match afterward (handles both
# "(433)" and "(433) thousand").
#
# `sign` is gated by `(?<!\d)` (checked immediately before it, not just
# before the digit group) so a hyphen glued directly to a PRECEDING digit
# is never read as this number's sign -- traced by hand against two real
# shapes: a hyphen-joined ISO date ("2024-01-25") and a hyphenated range
# ("10-15 percent"). Without this, the second half of either would
# misread as negative (a failed match attempt at the hyphen's own
# position just makes finditer retry starting one character later,
# landing past the digit instead of using it as a sign -- same retry
# mechanics as the existing letter-glued lookbehind above).
#
# That regex-level guard alone isn't enough, found live 2026-09-12 (the
# first real eval run after shipping this): a SPACED hyphen used as a
# subtraction operator ("223,000 - 166,000") has whitespace, not a digit,
# immediately before it, so `(?<!\d)` passes and the second operand was
# misread as negative -- this broke an otherwise-fully-correct answer's
# citation verification the very first time a model wrote its own
# computed-value disclosure using "-" for subtraction (system prompt rule
# 9 asks the model to show its `calculate` work inline; the model is free
# to choose "-" over the word "subtract"). No regex-only fix exists here
# (Python's `re` lookbehind can't skip variable-width whitespace), so
# `_is_negative()` below re-checks this at the Python level: after the
# regex says `sign` matched, look backward past any whitespace and
# confirm the nearest real character still isn't a digit (see
# `_preceded_by_number()`) -- a genuine negation is preceded by a word,
# punctuation, or nothing at all; a subtraction's minuend is a number.
#
# `sign` also matches U+2212 (the proper Unicode MINUS SIGN), not just
# ASCII hyphen-minus -- found the same live run, same root cause (a
# model's own rule-9 disclosure prose, this time "17.9% - 20% = -2.1%"
# rendered with the real minus-sign glyph). Confirmed
# `unicodedata.normalize("NFKC", ...)` does NOT fold U+2212 to ASCII "-"
# (they aren't compatibility-equivalent characters), so this codebase's
# existing NFKC-based quote normalization (agent._normalize_for_match)
# could never have caught this either -- it needed its own fix here.
#
# The parenthesized case ALSO needs two carve-outs, both found live
# against the real corpus (one during the original design, one flagged by
# code review and confirmed the same way before fixing it):
#
# 1. Bare years (`_BARE_YEAR_STRING`): "(2013)"/"(2025)"-style bare year
#    references are common boilerplate (COSO framework citations in every
#    10-K's internal-controls section; exhibit-index references) -- a
#    naive "any (NUM) is negative" rule would turn these into spurious
#    negative-year candidates. Matches only a comma-less, decimal-less
#    4-digit 19xx/20xx string, since a real dollar figure in that range is
#    always comma-grouped in SEC tables (>= 1000 always gets a thousands
#    separator) -- so this can't accidentally suppress a genuine negative
#    dollar amount. (Residual, accepted limitation: a real charge stated
#    as an exact, comma-less 4-digit 19xx/20xx figure -- e.g. "Impairment
#    charge (2010)" meaning -$2010 -- would also be read as positive.
#    Genuinely ambiguous with no available disambiguating signal even to
#    a human reading the isolated text, and unlike the footnote-marker
#    case below, no real occurrence of this shape was found in the actual
#    corpus -- not fixed further, per this project's practice of fixing
#    what's evidenced rather than chasing every hypothetical.)
# 2. Bare reference markers (`_looks_like_reference_number`): found in
#    code review, confirmed live against real corpus text -- a bare 1-2
#    digit parenthesized number is common filing boilerplate having
#    nothing to do with a negative value ("Mark whether the Registrant
#    (1) has filed... and (2) has been..." appears on literally every
#    10-K's cover page in this project's corpus; footnote markers glued
#    to a table row's own LABEL, e.g. "Total debt securities (1)", are
#    the same shape).
#
#    An earlier version of this guard fired on digit-count alone (<=2
#    digits, no comma/decimal, no adjacent unit/percent) -- a second
#    architecture-review pass caught, and live corpus grepping then
#    CONFIRMED AT SCALE (554 occurrences across the whole corpus, not a
#    one-off), that this was wrong: a short comma-less negative value is
#    the NORMAL shape for a table cell whose unit is stated once in the
#    table's own caption, not per-cell (e.g. a comprehensive-income
#    statement's small translation-adjustment line items, "| (73) | (86)
#    | (87) |"). Gating on digit count alone suppressed far more real
#    negatives than it correctly excluded markers -- a regression worse
#    than the false positive it was meant to fix.
#
#    The actual distinguishing signal, found by comparing both real
#    shapes side by side: a footnote/reference marker is always GLUED to
#    a preceding WORD ("Registrant (1)", "securities (1)", nothing but a
#    space between the two); a real table-cell value always starts fresh
#    -- right after a "|" delimiter, a newline, another number, or a
#    currency symbol, never directly after a letter. So the guard now
#    requires ALL THREE: short (<=2 digits, no comma/decimal), NOT
#    immediately followed by a unit word or "%" (a real percent this
#    small does occur, "(4)%", and is never a marker -- a marker is never
#    followed by "%"), AND the nearest non-whitespace character before
#    the "(" is alphabetic. All three together correctly separate every
#    real occurrence of both shapes found in the corpus.
NUMBER_PATTERN = re.compile(
    r"(?P<open_paren>\()?\s*(?<!\d)(?P<sign>[-−])?\$?\s*(?<!\w)(?P<digits>\d+(?:,\d{3})*(?:\.\d+)?)"
    r"(?P<close_paren>\))?\s*(?P<unit>billion|million|thousand|percent)?\s*(?P<pct>%)?",
    re.IGNORECASE,
)

UNIT_MULTIPLIERS = {"thousand": 1e3, "million": 1e6, "billion": 1e9}

_BARE_YEAR_STRING = re.compile(r"(?:19|20)\d{2}")


def _looks_like_reference_number(text: str, open_paren_pos: int, digits: str, followed_by_unit_or_pct: bool) -> bool:
    """See NUMBER_PATTERN's own comment (carve-out 2) for the real-corpus
    evidence behind all three conditions here. `open_paren_pos` is
    `match.start("open_paren")` -- only meaningful when the caller has
    already confirmed the parens wrap the number."""
    if len(digits) > 2 or "." in digits or followed_by_unit_or_pct:
        return False
    preceding = text[:open_paren_pos].rstrip()
    return bool(preceding) and preceding[-1].isalpha()


# The full set of a rendered number's possible trailing characters --
# a bare digit ("223,000"), "%" ("17.9%"), or one of NUMBER_PATTERN's own
# unit words ("20 million") -- used by _preceded_by_number() below to
# recognize "17.9% − 20%" as a subtraction (the minuend ends in "%", not
# a digit) as well as "223,000 - 166,000" (ends in a bare digit). Kept in
# sync with NUMBER_PATTERN's own `unit` alternation, not re-derived from
# UNIT_MULTIPLIERS, since "percent" isn't a scale multiplier but IS a
# valid trailing word here.
_NUMBER_ENDING_WORDS = ("billion", "million", "thousand", "percent")


def _preceded_by_number(text: str, pos: int) -> bool:
    """True if the text immediately before position `pos` (skipping
    whitespace) looks like the end of an already-complete rendered
    number -- see NUMBER_PATTERN's own comment for why this is what tells
    a spaced subtraction operator ("223,000 - 166,000", "17.9% − 20%")
    apart from a genuine negative sign: a real negation is preceded by a
    word, punctuation, an opening paren, or nothing at all, never by
    another number's own trailing digit/percent-sign/unit-word."""
    before = text[:pos].rstrip()
    if not before:
        return False
    if before[-1].isdigit() or before[-1] == "%":
        return True
    return before.lower().endswith(_NUMBER_ENDING_WORDS)


def _is_negative(text: str, match: re.Match, digits: str, unit_word: str | None, percent_sign: str | None) -> bool:
    """Whether one NUMBER_PATTERN match represents a negative value --
    pulled out of extract_numbers_with_spans()'s loop (found in
    architecture review, 2026-09-11) so the base sign/paren rule and both
    carve-outs (bare year, reference number -- see NUMBER_PATTERN's own
    comment for the real-corpus evidence behind each) live in one
    obviously-named place instead of a dense inline conditional."""
    if match.group("sign"):
        return not _preceded_by_number(text, match.start("sign"))
    wrapped_in_parens = bool(match.group("open_paren")) and bool(match.group("close_paren"))
    if not wrapped_in_parens:
        return False
    if _BARE_YEAR_STRING.fullmatch(digits) is not None:
        return False
    followed_by_unit_or_pct = bool(unit_word) or bool(percent_sign)
    if _looks_like_reference_number(text, match.start("open_paren"), digits, followed_by_unit_or_pct):
        return False
    return True


def extract_numbers_with_spans(text: str) -> list[tuple[float, str, int, int]]:
    """Like extract_numbers() below, but also returns each candidate's
    (start, end) character span (of the digit group only, e.g. "72.4" in
    "$72.4 billion") in `text`. Added for agent.py's uncited-numeric-
    claim detection, which needs a claim's position relative to the
    nearest [n] citation marker in the ORIGINAL, unmodified answer text
    -- unlike verify_citations()'s existing marker-anchored check, which
    only ever needs positions relative to an already-sliced window and
    so never needed this."""
    candidates = []
    for match in NUMBER_PATTERN.finditer(text):
        digits = match.group("digits")
        unit_word = match.group("unit")
        percent_sign = match.group("pct")
        try:
            value = float(digits.replace(",", ""))
        except ValueError:
            continue
        if _is_negative(text, match, digits, unit_word, percent_sign):
            value = -value
        if percent_sign or (unit_word and unit_word.lower() == "percent"):
            unit = "percent"
        elif unit_word:
            unit = unit_word.lower()
        else:
            unit = "raw"
        candidates.append((value, unit, match.start("digits"), match.end("digits")))
    return candidates


def extract_numbers(text: str) -> list[tuple[float, str]]:
    """Return every (value, unit) candidate found in text. unit is one of
    'raw', 'thousand', 'million', 'billion', 'percent'."""
    return [(value, unit) for value, unit, _, _ in extract_numbers_with_spans(text)]


def normalize(value: float, unit: str) -> tuple[str, float]:
    """Collapse a (value, unit) into a (category, comparable_number) pair.
    'percent' is its own category since it's not on the same scale as a
    dollar/count figure — 20 (percent) and 20 (raw) are not the same
    claim and must never compare equal."""
    if unit == "percent":
        return "percent", value
    return "scale", value * UNIT_MULTIPLIERS.get(unit, 1.0)


# Shared with agent._QUOTE_COVERAGE_THRESHOLD (an alias for this, not a
# second constant) and table_grounding.py's region-coverage check --
# moved here 2026-09-13 alongside text_coverage() for the same
# circular-import reason. 0.90 is the fraction of a quote's own
# (normalized) characters that must be found in the source/region for a
# non-exact match to still count as genuine.
QUOTE_COVERAGE_THRESHOLD = 0.90


def normalize_for_match(text: str) -> str:
    """Collapses cosmetic differences that would otherwise defeat quote
    matching without weakening what's actually being verified: NFKC
    normalization folds curly quotes and other Unicode compatibility
    variants into one canonical form; casefold() is a stronger
    case-insensitive comparison than .lower() for non-ASCII text;
    collapsing whitespace runs handles a quote that wraps differently
    than the source (a mid-sentence line break, doubled spaces from
    table formatting).

    Moved here from agent.py (2026-09-12, alongside adding
    table_grounding.py, which also needs it and cannot import from
    agent.py without a circular import -- the same reason this module
    was split out of eval_harness.py to begin with, see the module
    docstring above) -- agent._normalize_for_match is now a thin alias
    for this function, not a second implementation.

    NOTE: despite what an earlier version of this docstring (and this
    module's own NUMBER_PATTERN comment on U+2212) implied, NFKC does
    NOT fold true Unicode dashes to ASCII '-' -- measured directly: an
    em dash (U+2014), en dash (U+2013), hyphen (U+2010), non-breaking
    hyphen (U+2011, which does fold, but to U+2010, not ASCII '-'), and
    minus sign (U+2212) all pass through NFKC unchanged. Only the
    fullwidth hyphen-minus (U+FF0D) folds to ASCII '-'. The existing
    curly-quote/en-dash regression test for this function
    (test_quote_matches_nfkc_curly_quote_and_en_dash_normalization in
    tests/test_agent.py) in fact passes via the coverage/anchor
    fuzzy-match path, not via any dash folding -- confirmed by direct
    measurement while investigating a 2026-09-12 table-grounding bug,
    not assumed."""
    text = unicodedata.normalize("NFKC", text)
    text = text.casefold()
    return " ".join(text.split())


def text_coverage(quote: str, source: str) -> tuple[bool, float, int]:
    """Core fuzzy-containment primitive shared by agent._quote_matches
    (whole-document prose matching) and table_grounding.quote_is_grounded
    (matching against one cell's own small permitted region) -- extracted
    2026-09-13 for the same reason normalize_for_match() was: both
    modules need the identical SequenceMatcher-based logic, and
    table_grounding.py cannot import it from agent.py (agent.py imports
    table_grounding.py). Returns `(exact, coverage, longest)`:

    - `exact`: True if `quote` (normalized) is an exact substring of
      `source` (normalized) -- the fast path. When True, `coverage` is
      1.0 and `longest` is the full normalized quote length; callers can
      skip their own threshold check entirely.
    - `coverage`: sum of matched-block lengths (via
      difflib.SequenceMatcher) divided by the QUOTE's own normalized
      length -- deliberately NOT `.ratio()`, which scores a short quote
      against a much longer source near zero even on exact containment
      (ratio is symmetric; "is the quote IN the source" is not: it only
      cares how much of the QUOTE is covered, not how much of the source
      is).
    - `longest`: the single longest contiguous matched block's size --
      callers that need an anchor floor (blocking a fabricated quote
      assembled from scattered fragments of a LARGE document) apply
      their own threshold against this; callers matching against an
      already-narrow, single-purpose region (e.g. one table cell's own
      row) may reasonably skip that requirement, since there's little
      "other content" in a small region to scatter-assemble from in the
      first place.

    `autojunk=False` is mandatory, not a style choice: SequenceMatcher's
    autojunk heuristic is keyed off len(b) -- here, the QUOTE (passed as
    the third/`b` argument, source as the second/`a`), not the source.
    Once a quote reaches 200+ normalized characters, autojunk treats any
    character appearing in more than ~1% of IT as "popular" junk excluded
    from the initial anchor search -- effectively every common letter in
    ordinary prose -- and match quality collapses silently (no error,
    just a wrong low score) whenever the quote also isn't a clean exact
    substring of the source. Covered by a dedicated regression test in
    tests/test_agent.py (which actually exercises this by building a
    200+ character QUOTE, not just a long source).

    Does NOT apply any length gate (e.g. a minimum quote length) --
    that's caller-specific policy (agent._quote_is_long_enough has its
    own bare-number-digit-count exception that doesn't belong in a
    shared text-matching primitive), applied by the caller before or
    after calling this."""
    quote_norm = normalize_for_match(quote)
    source_norm = normalize_for_match(source)
    if quote_norm and quote_norm in source_norm:
        return True, 1.0, len(quote_norm)
    if not quote_norm:
        return False, 0.0, 0
    matcher = difflib.SequenceMatcher(None, source_norm, quote_norm, autojunk=False)
    blocks = matcher.get_matching_blocks()
    coverage = sum(b.size for b in blocks) / len(quote_norm)
    longest = max((b.size for b in blocks), default=0)
    return False, coverage, longest
