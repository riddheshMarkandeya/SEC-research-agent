"""
Shared numeric extraction/normalization, used by both eval_harness.py's
numeric grading and citations.py's citation-verification pass.

Split out from eval_harness.py rather than having citations.py import
from it -- eval_harness.py already imports agent.run_agent, which
reaches citations.py through submission.py, so importing back from
eval_harness.py would be circular.
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
# The leading digit group is intentionally `\d+`, not `\d{1,3}` — a
# capped group fragments a long, comma-less digit run (e.g. raw XBRL
# float formatting like "109417000000.0") into multiple wrong pieces.
# `(?<!\w)` immediately before it rejects a number glued to a preceding
# letter/digit ("Q3" would otherwise match as "3").
#
# Negative-number support: `sign` (a bare leading "-", or the real
# Unicode MINUS SIGN U+2212) and `open_paren`/`close_paren` (the real
# SEC-filing accounting convention of wrapping a negative in parentheses,
# e.g. "$(1,234)"). `sign` is gated by its OWN `(?<!\d)` lookbehind
# (checked immediately before it, not just before the digit group) so a
# hyphen glued directly to a PRECEDING digit is never read as this
# number's sign -- needed for a hyphen-joined ISO date ("2024-01-25")
# and a hyphenated range ("10-15 percent"), where the second half would
# otherwise misread as negative.
#
# `sign` matching alone is NOT sufficient to tell a genuine negation from
# a SPACED "-" used as a subtraction operator (e.g. "223,000 - 166,000",
# or "17.9% − 20%" with the model's own computed-value disclosure) --
# that disambiguation needs the Python-level
# `_is_negative()`/`_preceded_by_number()` below, since a regex
# lookbehind can't skip variable-width whitespace to check what's really
# before the sign. Don't try to "simplify" this into a regex-only check;
# it can't express that distinction.
#
# The parenthesized case has two carve-outs, both suppressing a false
# negative-sign read on real, evidenced corpus boilerplate rather than a
# hypothetical: a bare year in parens (`_BARE_YEAR_STRING`, e.g.
# COSO-framework citation years) and a bare 1-2 digit reference/footnote
# marker glued to a preceding word (`_looks_like_reference_number()`,
# e.g. "Registrant (1)", "Total debt securities (1)").
#
# Whitespace before the digit group is shaped for linear time, since
# untrusted answer text passes through here. Two plain `\s*` slots around
# an optional sign/"$" could split one whitespace run many ways, retried
# from every offset in the run: cubic in its length. So each run is
# consumed possessively (`*+`/`++`, never given back), only from its first
# character (`(?<!\s)`) or right after "(", and the second slot exists
# only after a sign or "$". Starting mid-run then fails at once. The
# empty branch of the leading group still lets a match start right at a
# sign/"$"/digit, e.g. "6" in "5   6", whose whitespace the previous
# match's trailing `\s*` already consumed.
NUMBER_PATTERN = re.compile(
    r"(?:(?P<open_paren>\()\s*+|(?<!\s)\s++)?(?<!\d)(?:(?P<sign>[-−])\$?\s*+|\$\s*+)?"
    r"(?<!\w)(?P<digits>\d+(?:,\d{3})*(?:\.\d+)?)"
    r"(?P<close_paren>\))?\s*(?P<unit>billion|million|thousand|percent)?\s*(?P<pct>%)?",
    re.IGNORECASE,
)

UNIT_MULTIPLIERS = {"thousand": 1e3, "million": 1e6, "billion": 1e9}

_BARE_YEAR_STRING = re.compile(r"(?:19|20)\d{2}")

_MAX_REFERENCE_MARKER_DIGITS = 2  # footnote markers run "(1)".."(99)", never longer


def _looks_like_reference_number(text: str, open_paren_pos: int, digits: str, followed_by_unit_or_pct: bool) -> bool:
    """Whether a parenthesized number is a footnote/reference marker
    ("Registrant (1)", "Total debt securities (1)") rather than a negative:
    a 1-2 digit whole number with no unit or "%" after it, following a word.
    `open_paren_pos` is `match.start("open_paren")` -- only meaningful when
    the caller has already confirmed the parens wrap the number."""
    if len(digits) > _MAX_REFERENCE_MARKER_DIGITS or "." in digits or followed_by_unit_or_pct:
        return False
    end = _end_before_space(text, open_paren_pos)
    return end > 0 and text[end - 1].isalpha()


def _end_before_space(text: str, pos: int) -> int:
    """`len(text[:pos].rstrip())`, without copying the prefix: these checks
    run once per match, so a copy each time is quadratic in the text length."""
    while pos > 0 and text[pos - 1].isspace():
        pos -= 1
    return pos


# The full set of a rendered number's possible trailing characters --
# a bare digit ("223,000"), "%" ("17.9%"), or one of NUMBER_PATTERN's own
# unit words ("20 million") -- used by _preceded_by_number() below to
# recognize "17.9% − 20%" as a subtraction (the minuend ends in "%", not
# a digit) as well as "223,000 - 166,000" (ends in a bare digit). Kept in
# sync with NUMBER_PATTERN's own `unit` alternation, not re-derived from
# UNIT_MULTIPLIERS, since "percent" isn't a scale multiplier but IS a
# valid trailing word here.
_NUMBER_ENDING_WORDS = ("billion", "million", "thousand", "percent")

# "raw" isn't a NUMBER_PATTERN unit, but calculate's rendered expression
# prints it after a unitless operand and models copy that text verbatim
# ("619,003,000,000 raw − 359,241,000,000 raw"). Only "<digit> raw" counts:
# a bare suffix match would flip a real negative after "draw"/"withdraw",
# and "raw" as an adjective ("a raw −3.1% basis") precedes a real sign.
_RAW_UNIT_WORD = "raw"

_LONGEST_ENDING_WORD = max(len(word) for word in (*_NUMBER_ENDING_WORDS, _RAW_UNIT_WORD))


def _preceded_by_number(text: str, pos: int) -> bool:
    """True if the text immediately before position `pos` (skipping
    whitespace) looks like the end of an already-complete rendered
    number -- see NUMBER_PATTERN's own comment for why this is what tells
    a spaced subtraction operator ("223,000 - 166,000", "17.9% − 20%")
    apart from a genuine negative sign: a real negation is preceded by a
    word, punctuation, an opening paren, or nothing at all, never by
    another number's own trailing digit/percent-sign/unit-word."""
    end = _end_before_space(text, pos)
    if end == 0:
        return False
    if text[end - 1].isdigit() or text[end - 1] == "%":
        return True
    # Lowercasing maps each character on its own and never shortens it, so
    # lowering just the last few characters yields the same ending.
    lowered_tail = text[max(0, end - _LONGEST_ENDING_WORD) : end].lower()
    if lowered_tail.endswith(_RAW_UNIT_WORD):
        operand_end = end - len(_RAW_UNIT_WORD)
        if operand_end == 0 or not text[operand_end - 1].isspace():
            return False
        number_end = _end_before_space(text, operand_end)
        return number_end > 0 and text[number_end - 1].isdigit()
    return lowered_tail.endswith(_NUMBER_ENDING_WORDS)


def _is_negative(text: str, match: re.Match, digits: str, unit_word: str | None, percent_sign: str | None) -> bool:
    """Whether one NUMBER_PATTERN match represents a negative value --
    pulled out of extract_numbers_with_spans()'s loop so the base
    sign/paren rule and both carve-outs (bare year, reference number --
    see NUMBER_PATTERN's own comment) live in one obviously-named place
    instead of a dense inline conditional. See
    docs/decisions/2026-09-11-negative-number-support.md."""
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
    "$72.4 billion") in `text`. extract_numbers() is the span-free
    projection of this."""
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
# second constant) and table_grounding.py's region-coverage check -- see
# docs/decisions/2026-09-13-table-grounding-region-scoped-matching.md
# for why this lives here rather than in either caller. 0.90 is the
# fraction of a quote's own (normalized) characters that must be found
# in the source/region for a non-exact match to still count as genuine.
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

    citations._normalize_for_match is a thin alias for this function, not
    a second implementation -- lives here rather than in citations.py for the
    same reason numeric_utils.py itself exists (this module's own
    docstring): table_grounding.py needs it too and cannot import from
    citations.py without a circular import.

    NOTE: NFKC does NOT fold true Unicode dashes to ASCII '-' -- an em
    dash (U+2014), en dash (U+2013), hyphen (U+2010), non-breaking hyphen
    (U+2011, which folds, but to U+2010, not ASCII '-'), and minus sign
    (U+2212) all pass through NFKC unchanged; only the fullwidth
    hyphen-minus (U+FF0D) folds to ASCII '-'. The existing curly-quote/
    en-dash regression test for this function
    (test_quote_matches_nfkc_curly_quote_and_en_dash_normalization in
    tests/agent/test_citations.py) passes via the coverage/anchor fuzzy-match path,
    not via any dash folding."""
    text = unicodedata.normalize("NFKC", text)
    text = text.casefold()
    return " ".join(text.split())


def text_coverage(quote: str, source: str) -> tuple[bool, float, int]:
    """Core fuzzy-containment primitive shared by citations._quote_matches
    (whole-document prose matching) and table_grounding.quote_is_grounded
    (matching against one cell's own small permitted region) -- lives
    here rather than in either caller for the same circular-import
    reason as normalize_for_match() above (see
    docs/decisions/2026-09-13-table-grounding-region-scoped-matching.md).
    Returns `(exact, coverage, longest)`:

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
    tests/agent/test_citations.py (which actually exercises this by building a
    200+ character QUOTE, not just a long source).

    Does NOT apply any length gate (e.g. a minimum quote length) --
    that's caller-specific policy (citations._quote_is_long_enough has its
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
