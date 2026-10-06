"""
Citation verification for the agent's answers: checks that each cited
number and quote in a submit_answer payload is grounded in the source it
cites (verify_claims), and the eval harness's per-value check
(value_is_citation_verified).
"""

import re
from typing import NamedTuple

from sec_agent.verification.numeric_utils import (
    QUOTE_COVERAGE_THRESHOLD,
    UNIT_MULTIPLIERS,
    extract_numbers,
    extract_numbers_with_paren_flag,
    normalize,
    normalize_for_match,
    text_coverage,
)
from sec_agent.prompts import agent_messages as msg
from sec_agent.verification.table_grounding import (
    extract_table_blocks,
    locate_value,
    quote_is_grounded,
    verbatim_row_span_grounded,
)
from sec_agent.agent.tool_results import citation_header

_CITATION_MARKER = re.compile(r"\[(\d+)\]")
_CITATION_WINDOW_CHARS = 150


# Broader than _CITATION_MARKER on purpose: matches a comma-separated
# multi-source bracket like "[1, 3, 5]" too, not just a single-index
# "[1]". _CITATION_MARKER can't just be widened to cover this --
# _iter_citation_claims (the eval grader's walk) goes marker-by-marker via
# finditer() and reads group(1) as ONE index, so widening it would break
# that per-index logic, not just the pattern.
# This one exists solely for verify_claims()'s coverage check, which
# only needs to strip citation-marker-SHAPED text before scanning for
# numbers -- it never reads the indices out (a bracket's own bare digits
# would otherwise be extracted as spurious uncovered-number claims).
_ANY_CITATION_BRACKET = re.compile(r"\[\s*\d+(?:\s*,\s*\d+)*\s*\]")


# Text that looks number-shaped but isn't a claim to verify -- stripped
# from the claim window before extraction, not from numeric_utils.py's
# shared extract_numbers() itself, since grade_numeric() doesn't have
# this false-positive problem (it only needs ONE number in the whole
# answer to match, so spurious extras there are harmless noise, not
# wrong verdicts) and stripping this there could hide a genuine
# date/form-shaped ground-truth value in some future question type.
# Four patterns, each found live rather than anticipated up front -- see
# docs/decisions/2026-08-17-citation-verification-pass.md (dates, bare
# years, 10-K/10-Q) and docs/decisions/2026-09-10-structured-claims-citation-verification.md
# (Note N, N-year/N-day) for the corpus evidence behind each:
#   - Dates ("June 27, 2026" -> 27, 2026), the single biggest noise
#     source on a real multi-sentence answer.
#   - Bare year-like numbers ("fiscal Q3 2025" -> the 2025 survives the
#     date pattern above since it's not glued to a month name) -- a
#     standalone 1900-2099 number next to a citation is virtually always
#     a period label, not a numeric claim.
#   - "10-K"/"10-Q", and the plurals "10-Ks"/"10-Qs" (the only two form
#     types this project ingests, see
#     edgar_ingest.py's FORM_TYPES) -- "10" isn't glued to a preceding
#     letter (there's a space before it), so the digit-glued-to-letter
#     fix in numeric_utils.py doesn't catch it.
#   - "Note 1"/"Note 12" (a footnote/financial-statement-note reference)
#     and "3-year"/"5-day" (an ordinal/count phrase, often echoing the
#     question's own wording, e.g. "3-year average operating margin") --
#     a bare `1` or `3` from either shape sitting near a real citation
#     would otherwise be treated as its own spurious claim.
_NON_CLAIM_PATTERN = re.compile(
    r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+\d{1,2},?\s+\d{4}\b|\b\d{4}-\d{2}-\d{2}\b|\b(?:19|20)\d{2}\b|\b10-[KQ]s?\b"
    r"|\bNote\s+\d+\b|\b\d+[\s-](?:year|month|day)s?\b",
    re.IGNORECASE,
)


# The identities in a percent formula ("a ÷ b − 1"; "(a ÷ b) − 1" and
# "(a ÷ b × 100) − 100", which parse as negatives after ")"; "× 100")
# aren't figures any filing states, so the model's own write-up of a
# percent calculation would otherwise be withheld for them. They count
# only when that calculation actually ran, never from the answer's
# wording, and only as exact unitless values. The accepted cost: on such a
# turn, a bare 1, −1, 100 or −100 anywhere in the answer is covered too.
_PERCENT_IDENTITY_CONSTANTS = {"percent_change": (1.0, -1.0, 100.0, -100.0), "percent_of": (100.0,)}


def _template_marker(template: str) -> str:
    """The longest literal run of an expression template, which identifies
    the operation in its rendering whatever order the placeholders are in."""
    return max(re.split(r"\{[^}]*\}", template), key=len).strip()


# calculate's own rendering (not the model's) says which operation ran.
_PERCENT_OPERATION_MARKERS = {
    "percent_change": _template_marker(msg.CALCULATION_PERCENT_CHANGE_EXPRESSION),
    "percent_of": _template_marker(msg.CALCULATION_PERCENT_OF_EXPRESSION),
}


def _percent_identity_values(calculated_expressions: list[str]) -> set[float]:
    """The identity values granted by every percent calculation among
    calculate's rendered expressions, for an exact match on a unitless
    answer number."""
    return {
        v
        for operation, marker in _PERCENT_OPERATION_MARKERS.items()
        if any(marker in expression for expression in calculated_expressions)
        for v in _PERCENT_IDENTITY_CONSTANTS[operation]
    }


# ---------------------------------------------------------------------------
# Structured-claims quote grounding -- verifies a submit_answer claim's
# `quote` genuinely appears in its cited source chunk, allowing for
# reformatting/paraphrase but not fabrication. See
# docs/decisions/2026-09-10-structured-claims-citation-verification.md
# for the full design reasoning behind every choice below.
# ---------------------------------------------------------------------------
_QUOTE_MIN_CHARS = 15  # a 2-character quote like "$5" would match almost any source trivially


# Lives in numeric_utils.QUOTE_COVERAGE_THRESHOLD, alongside
# text_coverage(), so table_grounding.py's region-scoped check can share
# the identical threshold. Kept as an alias, not a second constant, since
# every existing call site in this module refers to it by this name. See
# docs/decisions/2026-09-13-table-grounding-region-scoped-matching.md.
_QUOTE_COVERAGE_THRESHOLD = QUOTE_COVERAGE_THRESHOLD


_QUOTE_ANCHOR_CHARS = 30  # a real quote's whole span usually appears as one long contiguous match


# A bare-number quote (no surrounding prose -- e.g. quoting an XBRL fact's
# raw value directly, "391035000000") needs a different length bar than
# prose: DIGIT count, not character count, is what makes a number
# specific enough to trust -- a 12-character bare number is under
# _QUOTE_MIN_CHARS (15) despite being an unambiguous, correct quote,
# and a 6+ digit number is astronomically unlikely to match by
# coincidence even though it's short as text. See
# docs/decisions/2026-09-10-structured-claims-citation-verification.md.
_BARE_NUMBER_MIN_DIGITS = 6


# Lives in numeric_utils.normalize_for_match so table_grounding.py can
# share the exact same implementation without a circular import
# (table_grounding is imported BY citations.py, so it can't import back
# from it). Kept as an alias, not re-exported under a new name, since
# every existing call site and test in this module refers to it as
# `_normalize_for_match`.
_normalize_for_match = normalize_for_match


def _quote_is_long_enough(quote_norm: str) -> bool:
    """Shared length gate for a normalized quote, used by both
    _quote_matches() and _verify_one_claim()'s own pre-check -- both
    call sites must share this exactly, not each run their own plain
    len(quote_norm) < _QUOTE_MIN_CHARS check, or one could silently miss
    the digit-count exception below and reproduce the exact bare-XBRL-
    number false positive that exception exists to fix. See
    _BARE_NUMBER_MIN_DIGITS's own comment for why a short-as-text bare
    number can still be long/specific enough to trust."""
    digit_count = sum(ch.isdigit() for ch in quote_norm)
    return len(quote_norm) >= _QUOTE_MIN_CHARS or digit_count >= _BARE_NUMBER_MIN_DIGITS


def _quote_matches(quote: str, source: str) -> bool:
    """True if `quote` is genuinely present in `source`, allowing for
    reformatting/paraphrase but not fabrication.

    A quote shorter than _QUOTE_MIN_CHARS (normalized) is rejected
    outright -- too short to tell a real match from a coincidence.

    Exact-substring match (after normalization) is the fast path.
    Otherwise falls back to a COVERAGE ratio via difflib.SequenceMatcher
    -- deliberately NOT .ratio(), which scores a short quote against a
    much longer chunk near zero even on exact containment (ratio is
    symmetric -- 2*matches/(len(a)+len(b)) -- but "is the quote IN the
    source" is not a symmetric relationship: it cares only how much of
    the QUOTE is covered, not how much of the source is). Coverage is
    the sum of matched-block lengths divided by the quote's own length.

    `autojunk=False` is mandatory, not a style choice: SequenceMatcher's
    autojunk heuristic is keyed off len(b) -- here, the QUOTE
    (quote_norm is passed as the third/`b` argument below, source_norm
    as the second/`a`), not the source chunk. Once a quote reaches 200+
    normalized characters, autojunk treats any character appearing in
    more than ~1% of IT as "popular" junk excluded from the initial
    anchor search -- effectively every common letter in ordinary prose
    -- and match quality collapses silently (no error, just a wrong low
    score) whenever the quote also isn't a clean exact substring of the
    source. Covered by a dedicated regression test (which actually
    exercises this by building a 200+ character QUOTE, not just a long
    source -- an earlier version of that test got this backwards), not
    assumed to stay correct.

    The `longest`-contiguous-block floor guards the coverage metric's one
    real weakness: get_matching_blocks() finds a common SUBSEQUENCE, not
    a single contiguous match, so a fabricated quote assembled from words
    scattered across the source could otherwise accumulate high coverage
    from many small, unrelated fragments. Requiring one long contiguous
    run makes that construction much harder to pass by accident.

    Length gate accepts EITHER _QUOTE_MIN_CHARS of prose OR
    _BARE_NUMBER_MIN_DIGITS of digits -- see that constant's own comment
    for why a short-as-text bare number can still be long/specific
    enough to trust (e.g. a bare XBRL value like "391035000000" is 12
    characters, under 15, but is exactly the kind of quote this exists
    to accept, not reject).

    The actual coverage/anchor computation is numeric_utils.text_coverage
    (lives there so table_grounding.py can share the identical logic
    against a narrower region, without a circular import back to this
    module -- see
    docs/decisions/2026-09-13-table-grounding-region-scoped-matching.md)
    -- this function is now just that primitive plus the
    length gate and this module's own anchor-floor threshold."""
    quote_norm = _normalize_for_match(quote)
    if not _quote_is_long_enough(quote_norm):
        return False
    exact, coverage, longest = text_coverage(quote, source)
    if exact:
        return True
    return coverage >= _QUOTE_COVERAGE_THRESHOLD and longest >= min(_QUOTE_ANCHOR_CHARS, len(quote_norm))


def number_candidates(text: str, *, unit_source: str | None = None) -> list[tuple[str, float]]:
    """Every (category, comparable_number) `text` could plausibly
    support -- not just each number under its own immediately-adjacent
    unit, but also each bare/raw number reinterpreted under any unit
    word mentioned ANYWHERE in `unit_source` (defaulting to `text`
    itself, which is byte-for-byte the original, single-argument
    behavior this generalizes -- see below).

    SEC filing tables routinely state a unit once in a caption
    ("Remaining performance obligation consisted of the following (in
    billions):") and leave the actual cell values bare ("$72.4"), so a
    per-cell extract_numbers() reads $72.4 as 72.4 raw, not 72.4
    billion, and a correct claim would be refused.
    This only ADDS candidate interpretations (a raw number can still
    also match as raw) -- it never removes a way for a genuine mismatch
    to be caught.

    `unit_source` is what lets the structured-claims verifier check a claim's short
    `quote` (which usually won't itself restate a caption-only unit)
    against its cited chunk's full text as the place the caption lives,
    without requiring the model to have copied the caption into the
    quote. The eval grader's walk (_iter_citation_claims below) calls
    this with a single argument, so unit_source defaults to `text`."""
    source = text if unit_source is None else unit_source
    numbers = extract_numbers(text)
    candidates = [normalize(v, u) for v, u in numbers]
    source_lower = source.lower()
    for caption_unit in UNIT_MULTIPLIERS:
        if caption_unit in source_lower:
            candidates.extend(normalize(v, caption_unit) for v, u in numbers if u == "raw")
    return candidates


def _iter_citation_claims(answer_text: str, all_results: list[dict]):
    """Shared walk over every numeric claim found near a citation marker
    in `answer_text` — yields (citation_index, claimed_value,
    claimed_unit, verified) for each one, where `verified` is whether
    the claim's own cited source text actually contains a matching
    number. value_is_citation_verified() consumes it to check whether a
    single target value's claims are ever verified.

    For each citation marker, only the text since the previous citation
    marker (capped at _CITATION_WINDOW_CHARS) is checked, so a claim
    isn't accidentally "verified" by a number attributed to an earlier
    citation elsewhere in the same sentence. Known limitation: an answer
    that shows multi-step derivation work *between* a claim and its
    citation (e.g. a LaTeX-style calculation block) can still smuggle
    the correct intermediate numbers into that window and dodge
    detection — this is a best-effort heuristic, not an exhaustive
    grounding check."""
    window_start = 0
    for match in _CITATION_MARKER.finditer(answer_text):
        n = int(match.group(1))
        window = answer_text[max(window_start, match.start() - _CITATION_WINDOW_CHARS) : match.start()]
        window_start = match.end()
        if not (1 <= n <= len(all_results)):
            continue

        claimed = extract_numbers(_NON_CLAIM_PATTERN.sub("", window))
        if not claimed:
            continue

        source_normalized = number_candidates(all_results[n - 1]["text"])
        for value, unit in claimed:
            category, norm = normalize(value, unit)
            tolerance = max(0.01 * abs(norm), 0.05)
            verified = any(c == category and abs(sn - norm) <= tolerance for c, sn in source_normalized)
            yield n, value, unit, verified


CitationWarning = NamedTuple(
    "CitationWarning",
    [
        ("check", str),  # which verify_claims()/submission check produced it, e.g. "quote_not_found"
        ("citation_index", int | None),  # the [n] this warning is about, or None when it isn't about one
        ("value", float | None),  # None for a qualitative claim, which has no real value to report
        ("unit", str | None),  # None for a qualitative claim, which has no real unit to report
        ("message", str),  # the text shown to the model on a retry and embedded in a refusal
        ("quote", str | None),  # the claimed quote text for a quote-grounding check; None otherwise
    ],
)


def value_is_citation_verified(value: float, unit: str, answer_text: str, all_results: list[dict]) -> bool:
    """Whether `value` is properly grounded everywhere it's cited in
    `answer_text`, used by eval_harness.py to check ONE specific expected
    value.

    Built for eval_harness.py's grade_numeric()/grade_comparison(): they
    only check whether the expected value appears somewhere in the
    answer text, which can't tell a correctly-cited answer from one that
    states the right number but attaches it to the wrong source -- the
    wrong-chunk-citation case is a silent misgrounding this check wires
    into what decides pass/fail for the specific value a question is
    graded on.

    Returns True if `value` is never attached to a citation at all
    (nothing to contradict a plain-text match), or if AT LEAST ONE of
    its citations is properly grounded — a redundant second, wrong
    citation for an otherwise-correct value shouldn't fail the check.
    Returns False only if every citation attached to it fails
    verification."""
    target_category, target_norm = normalize(value, unit)
    tolerance = max(0.01 * abs(target_norm), 0.05)

    matches = []
    for _, claimed_value, claimed_unit, verified in _iter_citation_claims(answer_text, all_results):
        category, norm = normalize(claimed_value, claimed_unit)
        if category == target_category and abs(norm - target_norm) <= tolerance:
            matches.append(verified)
    return True if not matches else any(matches)


def _quote_grounded_in_source(value: float, unit: str, quote: str, source_text: str) -> bool:
    """Whether `quote` genuinely supports a claimed (value, unit) against
    `source_text` -- table-aware where possible, falling back to the
    flat-text _quote_matches() otherwise.

    If the claimed value can be located in a parsed table cell in
    `source_text`, that structural check is AUTHORITATIVE: it decides
    the outcome, with no fallback to _quote_matches() even if the
    structural check fails -- a deliberate design choice, not a default.
    _quote_matches's flat coverage/anchor-floor check accepts several
    real misattributions on this exact table shape whenever a segment
    label happens to be long enough (wrong fiscal period, a 10x-inflated
    value, a nine-month figure misquoted as a quarterly one), so letting
    it rescue a structural rejection would silently reopen exactly the
    holes this module closes.

    `quote_is_grounded()` matches against a tightly-scoped per-cell
    region (the table's own leading caption/header rows, plus the cell's
    own governing group label, plus the cell's own data row -- see
    table_grounding.GroundedCell) rather than a fixed word-vocabulary
    list, so a genuinely faithful multi-value row quote (e.g. a table row
    stating Current/Noncurrent/Total together) isn't wrongly refused for
    citing sibling-column content, while still rejecting the row-splice/
    cross-segment-steal attacks this module exists to block (verified
    directly by tests, not assumed).

    A quote that copies several consecutive rows word for word (the
    claimed row plus its neighbors) fails that one-row region, so each
    cell also accepts it through verbatim_row_span_grounded(), which
    anchors the quote to row and cell boundaries in the table itself.

    If the value isn't in any table cell (no table in this source, or a
    genuinely prose-stated value), that's not evidence of anything --
    it falls through to the ordinary flat-text check unchanged."""
    cells = locate_value(extract_table_blocks(source_text), value, unit)
    if cells:
        return any(quote_is_grounded(quote, cell) or verbatim_row_span_grounded(quote, cell) for cell in cells)
    return _quote_matches(quote, source_text)


_ClaimQuote = NamedTuple("_ClaimQuote", [("raw", str), ("grounding", str)])
# Bundles a claim's model-echoed quote with its header-stripped
# counterpart into one value, so _verify_numeric_claim/
# _verify_qualitative_claim (which need both -- grounding checks run
# against `.grounding`, any returned CitationWarning records `.raw`)
# take one parameter instead of two, keeping both under this project's
# ruff PLR0913 argument-count limit.


def _strip_citation_header(quote: str, n: int, meta: dict) -> str:
    """A model's quote for a submit_answer claim sometimes includes the
    numbered citation header format_results_block() displays directly
    above result [n]'s own text (e.g. "[1] NVDA 10-Q
    (reportDate=2026-04-26)"), even though that header is never part of
    the underlying source text (all_results[n-1]["text"]) the quote is
    grounded against -- it's added only when results are rendered for
    the model to read. A quote that includes it can never reach the 90%
    coverage _quote_matches() requires, however genuinely the rest of
    it matches, so it's stripped here before any grounding check runs.

    Reconstructs the exact header from this claim's OWN citation index
    and metadata (via citation_header, not a generic regex), and only
    strips an exact match of it, or of it without its leading "[n] "
    (models echo both forms). A header naming a different ticker, form
    or reportDate is never stripped. The unprefixed form is shared by
    every result from the same filing, which is harmless: the rest of
    the quote must still ground against result [n]'s own text. Any
    other reformatted/case-folded copy of a real header is deliberately
    left alone rather than guessed at."""
    header = citation_header(n, meta)
    stripped = quote.lstrip()
    for candidate in (header, header.removeprefix(f"[{n}] ")):
        if stripped.startswith(candidate):
            return stripped.removeprefix(candidate).lstrip()
    return quote


def _verify_one_claim(claim: dict, all_results: list[dict]) -> "CitationWarning | None":
    """Checks one submit_answer claim against its own cited source, then
    dispatches to _verify_numeric_claim or _verify_qualitative_claim
    depending on whether the claim states a real value. A claim
    supplying only one of value/unit (a malformed shape no schema
    validation catches, since both left `required` would forbid the
    legitimate qualitative case) gets its own warning here rather than
    crashing either branch on a missing key."""
    n = claim["citation_index"]
    value, unit, quote = claim.get("value"), claim.get("unit"), claim["quote"]
    if not (1 <= n <= len(all_results)):
        return CitationWarning(
            check="citation_out_of_range",
            citation_index=n,
            value=value,
            unit=unit,
            message=msg.CITATION_OUT_OF_RANGE_TEMPLATE.format(n=n, result_count=len(all_results)),
            quote=None,
        )
    if (value is None) != (unit is None):
        return CitationWarning(
            check="malformed_claim",
            citation_index=n,
            value=value,
            unit=unit,
            message=msg.MALFORMED_CLAIM_TEMPLATE.format(n=n),
            quote=None,
        )
    source_text = all_results[n - 1]["text"]
    grounding_quote = _strip_citation_header(quote, n, all_results[n - 1]["metadata"])
    quote_pair = _ClaimQuote(raw=quote, grounding=grounding_quote)
    if value is None:
        return _verify_qualitative_claim(n, quote_pair, source_text)
    assert unit is not None  # the (value is None) != (unit is None) check above already ruled this out
    return _verify_numeric_claim(n, value, unit, quote_pair, source_text)


def _verify_numeric_claim(
    n: int, value: float, unit: str, quote: "_ClaimQuote", source_text: str
) -> "CitationWarning | None":
    """Checks a claim already known to state a real (value, unit): quote
    long enough to mean anything, quote genuinely present in that source
    (_quote_grounded_in_source -- see its own docstring for the
    table-aware/flat-text split), and the claimed value actually
    attributable to that quote specifically (via number_candidates,
    using the FULL source chunk as unit_source so a caption-only unit
    still resolves -- see that function's own docstring). Returns None
    when all three pass. Checked in this order deliberately: each later
    check assumes the earlier ones already held.

    `quote.grounding` (the model's quote, with any leading citation-
    header echo already stripped by the caller) is what every check
    below runs against; `quote.raw` (the model's raw, unmodified text)
    is what gets recorded on any returned CitationWarning instead, so a
    header-echo pattern stays visible for future debugging even when
    grounding still fails for some unrelated reason -- silently
    swapping in the cleaned-up version would erase the exact signal
    this stripping logic exists to surface in the first place."""
    if not _quote_is_long_enough(_normalize_for_match(quote.grounding)):
        return CitationWarning(
            check="quote_too_short",
            citation_index=n,
            value=value,
            unit=unit,
            message=msg.NUMERIC_QUOTE_TOO_SHORT_TEMPLATE.format(n=n, value=value, unit=unit, quote=quote.raw),
            quote=quote.raw,
        )
    if not _quote_grounded_in_source(value, unit, quote.grounding, source_text):
        return CitationWarning(
            check="quote_not_found",
            citation_index=n,
            value=value,
            unit=unit,
            message=msg.QUOTE_NOT_FOUND_TEMPLATE.format(n=n, value=value, unit=unit),
            quote=quote.raw,
        )
    category, norm = normalize(value, unit)
    tolerance = max(0.01 * abs(norm), 0.05)
    quote_candidates = number_candidates(quote.grounding, unit_source=source_text)
    if not any(c == category and abs(v - norm) <= tolerance for c, v in quote_candidates):
        return CitationWarning(
            check="value_not_in_quote",
            citation_index=n,
            value=value,
            unit=unit,
            message=msg.VALUE_NOT_IN_QUOTE_TEMPLATE.format(n=n, value=value, unit=unit),
            quote=quote.raw,
        )
    return None


def _verify_qualitative_claim(n: int, quote: "_ClaimQuote", source_text: str) -> "CitationWarning | None":
    """Checks a claim with no real value to ground (a citation marker
    supporting a purely qualitative fact, e.g. a risk-factor bullet):
    quote long enough to mean anything, and quote genuinely present in
    the cited source -- via _quote_matches() directly, not
    _quote_grounded_in_source(), since there's no value to locate a
    specific table cell for. No value-in-quote check at all, since
    there's no value to verify. This is a real grounding check, not a
    rubber stamp: a fabricated qualitative citation (a quote that isn't
    actually in the cited source) is caught here, which it silently
    wouldn't have been under the older `claims: []` fallback for a fully
    qualitative answer.

    `quote.grounding`/`quote.raw` split: see _verify_numeric_claim's own
    docstring -- same reasoning, checks run against the header-stripped
    `quote.grounding`, but the model's raw `quote.raw` is what's
    recorded on any returned CitationWarning."""
    if not _quote_is_long_enough(_normalize_for_match(quote.grounding)):
        return CitationWarning(
            check="quote_too_short",
            citation_index=n,
            value=None,
            unit=None,
            message=msg.QUALITATIVE_QUOTE_TOO_SHORT_TEMPLATE.format(n=n, quote=quote.raw),
            quote=quote.raw,
        )
    if not _quote_matches(quote.grounding, source_text):
        return CitationWarning(
            check="qualitative_quote_not_found",
            citation_index=n,
            value=None,
            unit=None,
            message=msg.QUALITATIVE_QUOTE_NOT_FOUND_TEMPLATE.format(n=n),
            quote=quote.raw,
        )
    return None


def verify_claims(
    claims: list[dict], all_results: list[dict], question: str, answer_text: str
) -> list["CitationWarning"]:
    """Verifies the structured claims of a submit_answer call
    (SUBMIT_TOOL_SCHEMA) against the sources they cite.

    Two passes: first, each claim is checked independently against its
    own cited source (_verify_one_claim) -- citation index in range,
    quote long enough, and quote genuinely present in that source; a
    claim that also states a real value is additionally checked for
    whether that value is attributable to the specific quote, while a
    qualitative claim (no value/unit -- see _verify_qualitative_claim)
    skips that value check, since there's no value to attribute. Second,
    a COVERAGE cross-check scans `answer_text` for numbers and requires
    each to match some claim's normalized (value, unit) within the same
    1%-relative/0.05-floor tolerance grade_numeric() uses -- this is what
    stops the model from writing an ungrounded number in prose while
    conveniently leaving it out of `claims` to dodge the first pass.
    Qualitative and malformed claims contribute nothing to this pass,
    since neither states a real number to cover.

    A number that also appears in `question` is exempt from the coverage
    check: it's the model repeating what the user asked, not a claim the
    model is asserting (kills "3-year"-shaped noise and date/fiscal-year
    echoes at the source, without needing a claims entry for them) -- an
    accepted tradeoff, see the decision file above. `_NON_CLAIM_PATTERN`
    (dates, bare years, 10-K/10-Q, Note N, N-year/N-day) is stripped from
    both `question` and `answer_text` before extraction, same noise
    filter the eval grader's _iter_citation_claims() relies on.

    A number matching an operand of a `calculate` call that already
    succeeded this turn is also exempt: rule 9 tells the model to show
    a calculate-derived value's computation inline for readability
    (e.g. "computed as $35,695 million ... divided by $109,417 million
    ... = 32.6%"), and those restated operands were already verified
    against a real cited source by `_ground_operand` at calculate-call
    time -- they're not a new, unverified assertion. A successful
    `calculate` call's own `all_results` entry (`chunk_index ==
    "calculated"`, see `calculation_as_result`) already renders both
    operands in directly re-extractable text, so no new state needs to
    be threaded in from the tool-dispatch loop -- `all_results` is
    already this function's own parameter.

    Only the text BEFORE that entry's own "=" is used, deliberately
    excluding the RESULT value that follows it: an earlier version of
    this exemption extracted from the entry's full text, which meant
    the derived value itself (not just its operands) was silently
    exempt from ever needing its own `claims` entry at all -- caught
    live, by direct call, in code review. The result must still earn
    coverage the normal way, same as any other claimed value. Citation-
    bracket text is also stripped before extraction, guarding the same
    hazard `answer_numbers`'s own `_ANY_CITATION_BRACKET` strip below
    exists for -- belt-and-suspenders, since the bracketed "operands
    from results [N] and [M])" text only ever appears after "=" and so
    is already excluded by the split above on today's exact rendering.

    A percent calculation that ran also covers its formula's unitless
    identities (the "1" in "a ÷ b − 1", the "100" in "× 100"), so the
    model's own write-up of it isn't withheld; `_PERCENT_IDENTITY_CONSTANTS`
    lists them and the accepted cost.

    A number whose negative sign comes only from parentheses counts as
    covered by either sign. Models restate a figure in parentheses
    ("$44.06 billion ($44,062,000,000)"), which the accounting convention
    reads as negative, so the gate refused correct answers over their own
    gloss. Accepted cost: an answer writing "($5) million" for a loss
    passes with a +5 claim; the claim's own value is still checked against
    its quote. A "-" or "−" sign stays strict."""
    warnings = [w for w in (_verify_one_claim(c, all_results) for c in claims) if w is not None]

    # Qualitative and malformed claims (see _verify_one_claim) have no
    # real value to normalize -- and no number to be covering anyway.
    claimed_normalized = [
        normalize(c["value"], c["unit"]) for c in claims if c.get("value") is not None and c.get("unit") is not None
    ]
    question_numbers = extract_numbers(_NON_CLAIM_PATTERN.sub("", question))
    # Strip [n]/[n, m, ...] citation markers before extracting --
    # otherwise a bare digit INSIDE a marker (e.g. the "1" in "[1]", or
    # each of 1/3/5 in a multi-source "[1, 3, 5]") is itself picked up as
    # its own spurious uncovered claim. _ANY_CITATION_BRACKET (not
    # _CITATION_MARKER) specifically to also catch the multi-index form
    # -- see that constant's own comment.
    answer_numbers = extract_numbers_with_paren_flag(
        _NON_CLAIM_PATTERN.sub("", _ANY_CITATION_BRACKET.sub("", answer_text))
    )
    # Only the portion before "=" (the two operands) -- everything from
    # "=" onward is the RESULT itself, which must still earn its own
    # claims entry the normal way; see docstring above.
    calculated_expressions = [
        r["text"].split("=", 1)[0] for r in all_results if r["metadata"].get("chunk_index") == "calculated"
    ]
    calculated_candidates: list[tuple[str, float]] = [
        candidate
        for expression in calculated_expressions
        for candidate in number_candidates(_ANY_CITATION_BRACKET.sub("", expression))
    ]
    identity_values = _percent_identity_values(calculated_expressions)

    def _covered(category: str, norm: float, tolerance: float) -> bool:
        if any(c == category and abs(v - norm) <= tolerance for c, v in claimed_normalized):
            return True
        for q_value, q_unit in question_numbers:
            q_category, q_norm = normalize(q_value, q_unit)
            if q_category == category and abs(q_norm - norm) <= tolerance:
                return True
        if any(c == category and abs(v - norm) <= tolerance for c, v in calculated_candidates):
            return True
        return False

    seen_uncovered: set[tuple[str, float]] = set()
    for value, unit, paren_negative in answer_numbers:
        if unit == "raw" and value in identity_values:
            continue
        category, norm = normalize(value, unit)
        tolerance = max(0.01 * abs(norm), 0.05)
        if _covered(category, norm, tolerance) or (paren_negative and _covered(category, -norm, tolerance)):
            continue
        key = (category, norm)
        if key in seen_uncovered:
            continue
        seen_uncovered.add(key)
        warnings.append(
            CitationWarning(
                check="uncovered_number",
                citation_index=None,
                value=value,
                unit=unit,
                message=msg.UNCOVERED_NUMBER_TEMPLATE.format(value=value, unit=unit),
                quote=None,
            )
        )
    return warnings
