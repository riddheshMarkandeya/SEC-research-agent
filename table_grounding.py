"""
Structure-aware quote grounding for values that live in a markdown table
(2026-09-12). Used by agent._verify_one_claim() as a REPLACEMENT for
_quote_matches's flat-text anchor floor whenever a claim's value can be
located in a parsed table cell; _quote_matches remains the path for
prose (see docs/plans/2026-09-12-structure-aware-table-quote-grounding.md
for the full investigation and design reasoning).

Why a flat string-similarity check can't do this job: verifying a claim
about a table cell needs three coordinates -- which row-group (segment),
which metric row, which column (period) -- and a coverage/anchor-length
metric over normalized TEXT carries none of them. Confirmed live on the
real MSFT segment table this module was built against: the reported bug
(a genuine, correctly-reformatted quote of a short segment label rejected
purely because the label was under the old 30-character anchor floor)
cannot be fixed by tuning that floor, because after normalization a
markdown row boundary ("...|\\n|...") and an empty table cell ("| |")
collapse to the exact same string -- any locality-based relaxation of the
floor that's loose enough to accept the real bug is also loose enough to
let a value be spliced onto an unrelated adjacent row's label. Parsing
the table into rows/columns and checking row-group/row-label/column
alignment directly closes both the false negative and that bypass by
construction, not by threshold-tuning.

Split into its own module rather than added to agent.py (already 2372
lines) for the same reason numeric_utils.py exists as its own module
(see that module's docstring): independently testable, no dependency on
agent.py's tool-calling machinery, and importing FROM agent.py here
would be circular (agent.py imports this module).
"""

import re
from collections import Counter
from dataclasses import dataclass

from numeric_utils import UNIT_MULTIPLIERS, NUMBER_PATTERN, extract_numbers, normalize, normalize_for_match

_TABLE_BLOCK = re.compile(r"<TABLE>(.*?)</TABLE>", re.DOTALL)
_TABLE_ROW = re.compile(r"^[ \t]*\|(.*)\|[ \t]*$")
_SEPARATOR_CELL = re.compile(r"^-+$")


@dataclass(frozen=True)
class GroundedCell:
    """One numeric table cell that matches a claimed (value, unit),
    carrying just enough of its own row/column context to check whether
    a quote genuinely supports THIS cell specifically -- not some other
    cell elsewhere in the table that happens to hold the same number.

    `value`/`unit` are the CALLER's queried values (i.e. the claim being
    checked), not a re-derived interpretation of the cell's own raw
    text -- there's exactly one located cell per claim per call site, so
    there's no ambiguity to preserve by keeping the cell's own
    parse-level (value, unit) around too."""

    value: float
    unit: str
    cell_text: str
    row_label: str
    group_label: str | None
    period_header: str | None
    caption_units: frozenset[str]


@dataclass(frozen=True)
class _Row:
    cells: list[str]
    kind: str  # "blank" | "separator" | "label" | "data" | "header"


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
    - label: exactly one non-empty cell, in column 0, and it is NOT a
      number -- a group/segment header ("Intelligent Cloud") governing
      every data row below it until the next label row.
    - data: column 0 is non-empty and not a number (the row's own metric
      name, e.g. "Revenue"), and every OTHER non-empty cell IS a number.
    - header: anything else -- a caption/period-description row
      ("(In millions)", "Three Months EndedMarch 31,") or a bare
      period-value row ("2026 | 2025 | 2026 | 2025") whose own column 0
      is itself numeric, or a row that mixes non-numeric text across
      several columns. Never assumed to come first by position --
      derived purely structurally, so a table with no header row at all
      (see the AAPL fixture in tests/test_table_grounding.py) never
      manufactures a spurious one."""
    non_empty = [(i, c) for i, c in enumerate(cells) if c]
    if not non_empty:
        return "blank"
    if all(_SEPARATOR_CELL.match(c) for _, c in non_empty):
        return "separator"
    first_idx, first_cell = non_empty[0]
    if first_idx == 0 and not _cell_is_numeric(first_cell):
        rest = non_empty[1:]
        if not rest:
            return "label"
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
    by _classify_row(). Returns [] for prose with no table -- callers
    treat that the same as "value not found in any cell" and fall back
    to the ordinary flat-text quote check.

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
            rows.append(_Row(cells=cells, kind=_classify_row(cells)))
        if rows:
            blocks.append(TableBlock(rows=rows, caption_units=caption_units))
    return blocks


def _leading_period_header(rows: list[_Row]) -> _Row | None:
    """The LAST header-classified row before the first label/data row --
    that's the one reliably column-aligned with the data rows below it
    (see _period_header_index's own docstring for why: an earlier header
    row describing a multi-column span in one cell, e.g. "Three Months
    EndedMarch 31," covering two year-columns, is a lossy artifact of a
    dropped HTML colspan and is NOT usable for per-column comparison --
    only the row immediately above the data, "2026 | 2025 | 2026 |
    2025", is)."""
    header = None
    for row in rows:
        if row.kind == "header":
            header = row
        elif row.kind in ("separator", "blank"):
            continue
        else:
            break
    return header


def _period_header_index(period_header: _Row, data_row: _Row, col_idx: int) -> int | None:
    """Maps a data row's column index to the matching column in
    `period_header`, correcting for a real, systematic off-by-one: SEC
    filing tables' header rows describe only the VALUE columns (no cell
    for the row-label column), while data rows have an extra leading
    cell holding their own label -- so table_to_markdown's own
    clean_row() (which unconditionally drops every empty cell from each
    row BEFORE padding all rows in a table back to equal width) strips
    a header row's blank leading label-placeholder cell but can't strip
    anything from a data row (whose label cell is never blank). The
    header row ends up left-shifted by exactly the number of leading
    cells data rows have that header rows don't, with the lost width
    made up by EXTRA padding at the end instead of the correct position
    at the start.

    Recovered from the actual padded text (not hardcoded as 1), by
    comparing how much trailing padding each row needed: a row's real
    content length is (total width - its own trailing empty-cell count),
    so the shift is the DIFFERENCE between the header row's and `data_row`'s
    own trailing-empty counts. Confirmed against two real filings (MSFT's
    5-column segment table, AAPL's 6-column geographic table) -- both
    shift by exactly 1, which is what this computes from their real
    padding, not what was assumed going in.

    Deliberately takes `data_row` -- the SPECIFIC row the caller is
    currently checking a cell in -- rather than caching one
    representative data row for a whole table block: an earlier version
    of this function did cache a single block-wide sample, which is
    fragile against a real, plausible SEC-filing shape a code review
    flagged (2026-09-12) -- a table whose FIRST data row happens to have
    a missing/blank value cell (a metric not reported for one period)
    would give a cached sample a trailing-empty count that doesn't match
    every OTHER row's, silently miscomputing the shift -- and therefore
    the period header -- for the entire block. Computing it fresh per
    row is both more correct and simpler: nothing needs a separate
    sampling pass when the row already being processed is right there.

    Returns None (not misaligned) if the mapped index would land outside
    the header row entirely -- callers then treat this cell as having no
    period header to check against, same as a table with no header row
    at all, rather than risk associating it with the wrong column."""

    def _trailing_empty_count(cells: list[str]) -> int:
        n = 0
        for cell in reversed(cells):
            if cell:
                break
            n += 1
        return n

    shift = _trailing_empty_count(period_header.cells) - _trailing_empty_count(data_row.cells)
    header_idx = col_idx - shift
    if 0 <= header_idx < len(period_header.cells):
        return header_idx
    return None


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
    or the chunk may hold no table at all."""
    target_category, target_norm = normalize(value, unit)
    tolerance = max(0.01 * abs(target_norm), 0.05)

    found: list[GroundedCell] = []
    for block in blocks:
        period_header = _leading_period_header(block.rows)

        group_label: str | None = None
        for row in block.rows:
            if row.kind == "label":
                group_label = row.cells[0]
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
                    header_token = None
                    if period_header is not None:
                        header_idx = _period_header_index(period_header, row, col_idx)
                        if header_idx is not None:
                            header_token = period_header.cells[header_idx] or None
                    found.append(GroundedCell(
                        value=value,
                        unit=unit,
                        cell_text=cell_text,
                        row_label=row_label,
                        group_label=group_label,
                        period_header=header_token,
                        caption_units=block.caption_units,
                    ))
                    break  # one match per cell is enough
    return found


def quote_is_grounded(quote: str, cell: GroundedCell) -> bool:
    """True if every word of `quote` (after the same NFKC/casefold/
    whitespace-collapse normalization _quote_matches uses) is accounted
    for by this cell's OWN allowed context -- its own text, its row's
    label, the group label governing it (if any), and its own column's
    period header (if the table has one). Deliberately NOT the whole
    row, NOT sibling columns, and NOT other rows' text: that narrowness
    is what tells a genuine (if reformatted/line-broken/reordered) quote
    of THIS cell apart from one that also incorporates a neighboring
    cell's value or a sibling column's period label, however close by
    in the source those neighbors are.

    Numbers are compared BY VALUE, not as a literal allowed token, so a
    quote restating the cell's own value without its exact comma/dollar-
    sign/decimal formatting ("$34681", "34,681", "$34,681.00" for a cell
    literally rendered "$34,681") still grounds correctly -- found live
    2026-09-12, in this exact fix's own review: an earlier version of
    this function required the cell's cell_text to appear as a literal
    token, which is stricter than _quote_matches's old flat-text
    coverage check ever was (that one tolerated exactly this kind of
    reformatting) and would have caused new false NEGATIVES on a
    perfectly genuine quote purely for using different digit-grouping.
    Reuses _cell_value_candidates with the table's own caption_units so
    a bare reformatted number reinterprets under the table's stated
    scale exactly like the cell that grounded it in the first place (see
    that function's own docstring).

    Word-level (not character-level) multiset containment for the LABEL
    words: the model is free to reorder "group label, then row label,
    then value" however it phrases the sentence, and free to join them
    with any whitespace, but every non-numeric word in its quote must
    come from this cell's own label vocabulary -- with at least as many
    repeats as the quote uses. This is what rejects a row-spliced quote
    (it contains a foreign row's own label, which isn't in this cell's
    allowed bag at all) and a wrong-column quote (a sibling column's own
    period header token isn't in the bag either), without needing the
    source's real character-level layout at all -- see this module's own
    docstring and docs/plans/2026-09-12-structure-aware-table-quote-
    grounding.md for why a character-level/locality-based approach was
    tried first and rejected: it can't distinguish a genuine adjacent
    reformatting from a row-boundary splice, because both look identical
    once whitespace is collapsed. A row-spliced NUMBER (a foreign cell's
    own value) is rejected the same way a foreign label is: it won't
    match this cell's own (value, unit) within tolerance, so it falls
    through to the label-word check and fails there too.

    A quote token that's pure punctuation (no letters or digits at all)
    is skipped outright -- it can't smuggle in a foreign label or value,
    so there's nothing to gain by rejecting it, only false negatives on
    a stray comma/period from unusual quote spacing to lose.

    KNOWN LIMITATION, confirmed live 2026-09-13 (see
    docs/plans/2026-09-13-table-grounding-region-scoped-matching.md):
    comparing against `cell.value`/`cell.unit` (the caller's originally-
    CLAIMED value, not this specific cell's own re-parsed content) is
    vacuous whenever `locate_value()`'s 1%-tolerance returns more than
    one cell for the same claim -- the check ends up comparing the claim
    against itself. Being replaced by the region-scoped redesign; not
    fixed as a standalone patch here since a narrow patch to this single
    function was tried and found to introduce a worse regression
    elsewhere (see that plan's diagnosis)."""
    target_category, target_norm = normalize(cell.value, cell.unit)
    tolerance = max(0.01 * abs(target_norm), 0.05)

    label_parts = [cell.group_label, cell.row_label, cell.period_header]
    allowed_counts = Counter(normalize_for_match(" ".join(p for p in label_parts if p)).split())

    for word in normalize_for_match(quote).split():
        if not any(ch.isalnum() for ch in word):
            continue
        if allowed_counts[word] > 0:
            allowed_counts[word] -= 1
            continue
        candidates = _cell_value_candidates(word, cell.caption_units)
        if any(
            category == target_category and abs(norm - target_norm) <= tolerance
            for category, norm in (normalize(v, u) for v, u in candidates)
        ):
            continue
        return False
    return True
