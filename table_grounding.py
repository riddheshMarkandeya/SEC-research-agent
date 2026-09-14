"""
Structure-aware quote grounding for values that live in a markdown table
(2026-09-12, redesigned 2026-09-13). Used by agent._verify_one_claim() as
a REPLACEMENT for _quote_matches's flat-text anchor floor whenever a
claim's value can be located in a parsed table cell; _quote_matches
remains the path for prose (see
docs/plans/2026-09-12-structure-aware-table-quote-grounding.md for the
original investigation, and
docs/plans/2026-09-13-table-grounding-region-scoped-matching.md for the
redesign below).

Why a flat string-similarity check over the WHOLE source can't do this
job: verifying a claim about a table cell needs to tell a genuine,
possibly multi-value disclosure ("Current $35.1, Noncurrent $37.3, Total
$72.4" -- all real, all in the same row) apart from a value spliced onto
an unrelated adjacent row/group's label (a markdown row boundary and an
empty table cell normalize to the identical string, so naive locality
tricks can't tell them apart -- see the first plan doc for the measured
proof). The fix here is neither a length-based heuristic nor a fixed
word-vocabulary allowlist (both were tried; both broke on real filings --
see the second plan doc's diagnosis) -- it's SCOPE: build a small,
precisely-bounded "permitted region" for the cell actually being verified
(the table's own leading caption/header rows -- which describe the WHOLE
table, not one group -- plus the cell's OWN governing group label, if
any, plus the cell's OWN data row, all as their real VERBATIM source
text) and reuse the exact same coverage/exact-substring matching
`_quote_matches` already uses (numeric_utils.text_coverage), just against
that narrow region instead of the whole chunk. A genuine multi-value row
quote naturally hits the exact-substring fast path within its own small
region; a quote that reaches into a DIFFERENT row or group has nothing to
match there at all, since that content was never included in the region
to begin with -- the exclusion is structural, not threshold-tuned.

Split into its own module rather than added to agent.py (already 2000+
lines) for the same reason numeric_utils.py exists as its own module
(see that module's docstring): independently testable, no dependency on
agent.py's tool-calling machinery, and importing FROM agent.py here would
be circular (agent.py imports this module).
"""

import re
from dataclasses import dataclass

from numeric_utils import (
    QUOTE_COVERAGE_THRESHOLD,
    UNIT_MULTIPLIERS,
    NUMBER_PATTERN,
    extract_numbers,
    normalize,
    normalize_for_match,
    text_coverage,
)

_TABLE_BLOCK = re.compile(r"<TABLE>(.*?)</TABLE>", re.DOTALL)
_TABLE_ROW = re.compile(r"^[ \t]*\|(.*)\|[ \t]*$")
_SEPARATOR_CELL = re.compile(r"^-+$")


@dataclass(frozen=True)
class GroundedCell:
    """One numeric table cell located for a claimed (value, unit),
    carrying its own row/group/table context as VERBATIM source text --
    not a reconstruction from parsed cells -- so a quote can be checked
    against exactly what the filing actually says.

    `permitted_region` is what quote_is_grounded() actually matches
    against: the table's own leading caption/header rows (shared, table-
    wide context -- e.g. "(In millions)", a period-header row) followed
    by this cell's own governing group-label row (if any, e.g.
    "Intelligent Cloud") followed by this cell's own data row, each as
    real source text, in their real source ORDER. Deliberately excludes
    every OTHER row and every OTHER group: that's what makes a quote
    reaching into a different row/group have nothing to match, rather
    than relying on a threshold to catch it after the fact.

    `cell_text`/`row_label`/`group_label` are kept as parsed, human-
    readable strings for introspection/debugging/tests. `caption_units`
    is the table's own stated scale words (e.g. "million"), needed so
    quote_is_grounded()'s number check can reinterpret a bare quote
    number the same way locate_value() reinterprets bare cell numbers --
    see _cell_value_candidates()'s own docstring. `multi_cell_context_tokens`
    is the table's own multi-column header rows' own distinct cell
    texts (e.g. {"Compute & Networking", "Graphics", "Total"}), used by
    quote_is_grounded()'s cherry-pick check -- see that function's own
    docstring for why this exists."""

    cell_text: str
    row_label: str
    group_label: str | None
    permitted_region: str
    caption_units: frozenset[str]
    multi_cell_context_tokens: list[frozenset[str]]


@dataclass(frozen=True)
class _Row:
    cells: list[str]
    kind: str  # "blank" | "separator" | "label" | "data" | "header"
    raw_text: str


@dataclass(frozen=True)
class TableBlock:
    rows: list[_Row]
    caption_units: frozenset[str]


def _cell_is_numeric(cell: str) -> bool:
    """True if `cell`, taken as a whole, IS a number (optionally
    dollar-prefixed/percent-suffixed/parenthesized-negative) -- as
    opposed to extract_numbers(), which finds numbers embedded anywhere
    in free-form prose. fullmatch is deliberate: "Three Months
    EndedMarch 31," contains a digit (31) but is not, as a whole cell, a
    number -- it must classify as a label/caption, not a value."""
    return bool(cell) and NUMBER_PATTERN.fullmatch(cell) is not None


def _classify_row(cells: list[str]) -> str:
    """Every row a real SEC markdown table produces is one of five
    shapes, told apart purely by which cells are non-empty and whether
    each parses as a number -- no positional/ordering assumption beyond
    "a row's own label, if it has one, is always column 0":

    - blank: every cell empty (a table_to_markdown padding artifact).
    - separator: the "| --- | --- |" rule markdown itself requires.
    - label: exactly one non-empty cell, in column 0, NOT a number, and
      NOT parenthesized -- a group/segment/period header ("Intelligent
      Cloud", "Three Months Ended Apr 26, 2026") governing every data
      row below it until the next label row.
    - data: column 0 is non-empty and not a number (the row's own metric
      name, e.g. "Revenue"), and every OTHER non-empty cell IS a number.
    - header: anything else -- a caption/period-description row that
      mixes non-numeric text across several columns ("(In millions) |
      Three Months EndedMarch 31, | ..."), a bare period-value row
      ("2026 | 2025 | 2026 | 2025") whose own column 0 is itself
      numeric, OR a single non-empty, non-numeric cell that IS
      parenthesized ("(In millions)"). That last case matters: SEC
      filings render a table-wide unit/scale caption as its own single-
      cell row indistinguishably from a genuine group label by cell
      shape alone -- confirmed live 2026-09-13 on NVIDIA's segment
      table, where "(In millions)" (a permanent, whole-table caption)
      and "Three Months Ended Apr 26, 2026" (a resettable, per-period
      group label) are BOTH single-cell rows back to back. Parens are
      the real, observed distinguishing signal across every filing in
      this corpus: a caption is always parenthesized ("(In millions)",
      "(Unaudited)", "(in thousands, except per share data)"); a group/
      segment/period label never is. Classifying a parenthesized single-
      cell row as "header" (permanent, table-wide) rather than "label"
      (resettable, per-group) is what lets locate_value() keep it as
      shared context for EVERY group in the table instead of losing it
      the moment the next real group label appears.

    Never assumed to come first by position -- derived purely
    structurally, so a table with no header row at all (see the AAPL
    fixture in tests/test_table_grounding.py) never manufactures a
    spurious one."""
    non_empty = [(i, c) for i, c in enumerate(cells) if c]
    if not non_empty:
        return "blank"
    if all(_SEPARATOR_CELL.match(c) for _, c in non_empty):
        return "separator"
    first_idx, first_cell = non_empty[0]
    if first_idx == 0 and not _cell_is_numeric(first_cell):
        rest = non_empty[1:]
        if not rest:
            return "label" if not first_cell.startswith("(") else "header"
        if all(_cell_is_numeric(c) for _, c in rest):
            return "data"
    return "header"


def _split_row(line: str) -> list[str] | None:
    match = _TABLE_ROW.match(line)
    if match is None:
        return None
    return [cell.strip() for cell in match.group(1).split("|")]


def extract_table_blocks(text: str) -> list[TableBlock]:
    """Parse every <TABLE>...</TABLE> block chunk_documents.py's
    reconstruct_document() spliced into `text` back into rows, classified
    by _classify_row(), each keeping its own literal source line as
    `raw_text` (used to build a cell's permitted_region verbatim, not
    reconstructed from parsed cells). Returns [] for prose with no table
    -- callers treat that the same as "value not found in any cell" and
    fall back to the ordinary flat-text quote check.

    Each block's caption_units is derived from the FULL `text` passed
    in, not just the table's own cells: SEC filings routinely state a
    table's unit once, in a prose sentence immediately BEFORE the table
    ("...for 2025, 2024 and 2023 (dollars in millions):"), never
    repeating it inside any cell -- confirmed against the real AAPL
    segment-revenue table this module was built against, whose caption
    lives in the preceding paragraph, not inside its own <TABLE> tags.
    Mirrors agent._number_candidates's own unit_source parameter for the
    identical reason (see that function's docstring)."""
    caption_units = frozenset(cu for cu in UNIT_MULTIPLIERS if cu in text.lower())
    blocks = []
    for match in _TABLE_BLOCK.finditer(text):
        rows = []
        for line in match.group(1).splitlines():
            cells = _split_row(line)
            if cells is None:
                continue
            rows.append(_Row(cells=cells, kind=_classify_row(cells), raw_text=line))
        if rows:
            blocks.append(TableBlock(rows=rows, caption_units=caption_units))
    return blocks


def _leading_header_context(rows: list[_Row]) -> str:
    """Raw, verbatim source text of every row from the start of the
    block up to (but not including) the first label/data row -- the
    table's own shared, whole-table context (captions, column-period
    headers) that applies to every group/row below it, not just the
    first one. Joined in real source order so a quote reproducing this
    context plus its own row hits text_coverage's exact-substring fast
    path directly, the same way a full-row verbatim quote already does.

    Separator/blank rows are included too (harmless boilerplate -- "---"
    carries no misattributable content, and a model that quotes the
    separator row verbatim, as observed live on NVIDIA's segment table,
    should not lose coverage for it)."""
    lines = []
    for row in rows:
        if row.kind in ("label", "data"):
            break
        lines.append(row.raw_text)
    return "\n".join(lines)


def _leading_header_multi_cell_token_sets(rows: list[_Row]) -> list[frozenset[str]]:
    """For each MULTI-CELL row in the leading header run (more than one
    non-empty cell -- column/segment headers, e.g. "Three Months
    EndedMarch 31, | Nine Months EndedMarch 31," or "Compute & Networking
    | Graphics | Total"), the frozenset of its own distinct non-empty
    cell texts. Used by quote_is_grounded's cherry-pick check -- see that
    function's own docstring for the real, live-confirmed misattribution
    this guards against: a quote citing ONE of a multi-column header
    row's own labels (e.g. "Three Months EndedMarch 31,") paired with a
    value that's actually under a DIFFERENT column of that SAME header
    row (the value was really the "Nine Months EndedMarch 31," figure).
    A single-cell header/label row (e.g. "Intelligent Cloud", "(In
    millions)") never appears here -- there's no sibling cell to
    cherry-pick FROM in a row that only has one."""
    token_sets = []
    for row in rows:
        if row.kind in ("label", "data"):
            break
        if row.kind == "header":
            non_empty = [c for c in row.cells if c]
            if len(non_empty) > 1:
                token_sets.append(frozenset(non_empty))
    return token_sets


def _cell_value_candidates(cell_text: str, caption_units: frozenset[str]) -> list[tuple[float, str]]:
    """Every (value, unit) a table cell's bare number could plausibly
    mean -- mirrors agent._number_candidates's own caption-unit
    reinterpretation exactly and for the identical reason: SEC tables
    routinely state a unit once, in prose near the table ("dollars in
    millions"), leaving every cell bare ("$178,353"), so a per-cell
    extract_numbers() alone reads it as a raw count, not millions. This
    only ADDS candidate interpretations -- a genuinely raw value can
    still also match as raw -- so it never suppresses a real mismatch."""
    numbers = extract_numbers(cell_text)
    candidates = list(numbers)
    for value, unit in numbers:
        if unit == "raw":
            candidates.extend((value, caption_unit) for caption_unit in caption_units)
    return candidates


def locate_value(blocks: list[TableBlock], value: float, unit: str) -> list[GroundedCell]:
    """Every table cell across `blocks` whose own value matches (value,
    unit) within the same 1%-relative/0.05-floor tolerance used
    throughout this codebase's citation verification (see
    numeric_utils.normalize's callers in agent.py and eval_harness.py).
    Returns [] if the value isn't in any cell -- callers treat that as
    "not a table claim" and fall back to the ordinary flat-text quote
    check, since the value may legitimately be stated in prose instead,
    or the chunk may hold no table at all.

    Can return MULTIPLE cells for one claim: two distinct real numbers
    can sit within the standard 1% tolerance of each other (confirmed
    live 2026-09-13 -- a real MSFT segment table has Intelligent Cloud
    revenue $34,681M and Productivity & Business Processes revenue
    $35,013M, a genuine ~0.95% gap). Callers must check EVERY returned
    cell's own permitted_region, never assume the first is the right
    one."""
    target_category, target_norm = normalize(value, unit)
    tolerance = max(0.01 * abs(target_norm), 0.05)

    found: list[GroundedCell] = []
    for block in blocks:
        header_context = _leading_header_context(block.rows)
        multi_cell_context_tokens = _leading_header_multi_cell_token_sets(block.rows)

        group_label: str | None = None
        group_label_raw: str | None = None
        for row in block.rows:
            if row.kind == "label":
                group_label = row.cells[0]
                group_label_raw = row.raw_text
                continue
            if row.kind != "data":
                continue

            row_label = row.cells[0]
            for col_idx, cell_text in enumerate(row.cells):
                if col_idx == 0 or not cell_text or not _cell_is_numeric(cell_text):
                    continue
                for cell_value, cell_unit in _cell_value_candidates(cell_text, block.caption_units):
                    category, norm = normalize(cell_value, cell_unit)
                    if category != target_category or abs(norm - target_norm) > tolerance:
                        continue
                    permitted_region = "\n".join(
                        part for part in (header_context, group_label_raw, row.raw_text) if part
                    )
                    found.append(GroundedCell(
                        cell_text=cell_text,
                        row_label=row_label,
                        group_label=group_label,
                        permitted_region=permitted_region,
                        caption_units=block.caption_units,
                        multi_cell_context_tokens=multi_cell_context_tokens,
                    ))
                    break  # one match per cell is enough
    return found


def _region_number_candidates(region: str, caption_units: frozenset[str]) -> list[tuple[str, float]]:
    """Every (category, comparable_number) any number ANYWHERE in
    `region` could plausibly mean -- built on the same
    _cell_value_candidates() a single cell's text uses, just applied to
    the whole region string and normalized immediately (every caller
    needs the normalized form; unlike locate_value's own use of
    _cell_value_candidates, nothing here needs the raw (value, unit)
    pairs first). Used by quote_is_grounded to check a quote's own
    numbers against every genuine value the region actually contains,
    not just the one cell being verified -- a region can legitimately
    hold several real values (CRM's Current/Noncurrent/Total row;
    MSFT's multiple period columns), and this module doesn't try to
    tell which one the model MEANT to cite, only whether the number it
    wrote down is real content from this cell's own governing context
    at all.

    Returns a plain list, not a set: comparison against a quote's own
    number still needs the same tolerance-based float comparison used
    everywhere else in this codebase (max(0.01*abs(norm), 0.05)), not
    exact tuple/float equality, which is unreliable across independently
    computed floats."""
    return [normalize(v, u) for v, u in _cell_value_candidates(region, caption_units)]


def quote_is_grounded(quote: str, cell: GroundedCell) -> bool:
    """True if `quote` is genuinely present in this cell's own
    `permitted_region` -- the table's shared caption/header context plus
    this cell's own governing group label (if any) plus this cell's own
    data row, nothing else -- AND every number the quote states is a
    real value actually found somewhere in that region -- AND the quote
    doesn't cherry-pick one label out of a multi-column header row while
    omitting that row's other labels.

    Three checks, all required:

    1. Coverage/exact-substring, via numeric_utils.text_coverage (the
       same primitive _quote_matches uses for prose), scoped to the
       narrow region instead of the whole chunk. This is what tolerates
       a quote restating the region's wording without exact comma/
       dollar-sign/decimal formatting, or using an ordinary connective/
       caption word -- exactly like _quote_matches already tolerates for
       prose (an earlier, narrower word-vocabulary-allowlist version of
       this function couldn't recognize its own source verbatim, which
       is what caused the real regressions this redesign fixes -- see
       docs/plans/2026-09-13-table-grounding-region-scoped-matching.md).

    2. Every number-shaped token in `quote` must equal a real number
       found somewhere in the region (by VALUE, tolerant of formatting
       and the table's own caption-unit scale -- not scattered digit
       coincidence). This second check is NOT redundant with coverage:
       found live 2026-09-13, re-testing this exact redesign before
       shipping it -- a WRONG value's digits can still score 90%+
       coverage via difflib.SequenceMatcher finding scattered,
       non-contiguous single-character/short-fragment matches against
       various OTHER real numbers sprinkled through the same region
       (confirmed measured: "$35,013" against Intelligent Cloud's own
       region, which contains no $35,013 at all, scored 94% coverage
       purely from shared digits with $34,681/$26,751/etc). Dropping the
       old anchor-floor requirement (see this function's own history)
       reopened exactly this hole; reintroducing the SAME anchor-floor
       mechanism would in turn reopen the original short-label false
       negative this whole module exists to fix (a genuine short label's
       longest contiguous match, e.g. "intelligent cloud", is well under
       any anchor floor big enough to matter). Checking numbers BY VALUE
       against the region's real content -- not by contiguous-match
       length -- is what closes the scattered-digit hole without
       reopening the length-dependent one: a wrong value simply isn't a
       real number anywhere in the region, however its digits happen to
       overlap with ones that are.

    3. The quote must not cherry-pick ONE cell's own label out of a
       multi-column header row (`cell.multi_cell_context_tokens`) while
       omitting that row's OTHER labels. Found live 2026-09-13 by an
       independent review of this exact redesign, re-verified directly:
       a quote citing "Three Months EndedMarch 31," (one of two period
       phrases in the same header row) alongside a value that's actually
       the OTHER period's ("Nine Months EndedMarch 31,"'s own figure)
       passed checks 1-2 (both phrases and the value are genuinely
       "in the region" -- the whole point of including header rows
       wholesale) -- confirmed against the real MSFT fixture, and the
       yesterday-committed design (before this whole redesign) correctly
       rejected this exact case, so this is a real regression, not a
       pre-existing accepted limitation as an earlier version of this
       docstring claimed. Same mechanism on NVIDIA's segment table: a
       quote citing "Graphics" with Compute & Networking's own real
       value. A quote that reproduces a multi-column row's labels
       WHOLESALE (all of them, e.g. the real NVIDIA/CRM regressions this
       redesign fixes) is unaffected -- cherry-picking is specifically
       "some but not all" of one row's own distinct labels, not "any
       overlap with a multi-column row at all"."""
    exact, coverage, _ = text_coverage(quote, cell.permitted_region)
    if not (exact or coverage >= QUOTE_COVERAGE_THRESHOLD):
        return False

    quote_norm = normalize_for_match(quote)
    for token_set in cell.multi_cell_context_tokens:
        present = [t for t in token_set if normalize_for_match(t) in quote_norm]
        if present and len(present) < len(token_set):
            return False

    region_numbers = _region_number_candidates(cell.permitted_region, cell.caption_units)
    for value, unit in extract_numbers(quote):
        candidates = [(value, unit)]
        if unit == "raw":
            candidates.extend((value, cu) for cu in cell.caption_units)
        found = False
        for v, u in candidates:
            q_category, q_norm = normalize(v, u)
            # Deliberately a TIGHT, near-exact tolerance -- NOT the loose
            # 1%-relative business tolerance locate_value() uses to find
            # candidate CELLS. Reformatting (comma/dollar-sign/decimal
            # removal) never changes the underlying parsed float at all,
            # so no real tolerance is needed for that; using the loose
            # 1% tolerance here instead would recreate Regression B one
            # layer up (found live 2026-09-13: $34,681 and $35,013 are
            # genuinely ~0.95% apart, so the loose tolerance would accept
            # either as "matching" the other, making this check unable to
            # tell two real, DIFFERENT segments' values apart -- exactly
            # what it exists to catch).
            tolerance = max(1e-6 * abs(q_norm), 1e-9)
            if any(
                r_category == q_category and abs(r_norm - q_norm) <= tolerance
                for r_category, r_norm in region_numbers
            ):
                found = True
                break
        if not found:
            return False
    return True
