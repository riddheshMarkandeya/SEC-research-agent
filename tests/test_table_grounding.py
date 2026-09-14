"""
Unit tests for table_grounding.py -- structure-aware quote verification
for values that live in a markdown table.

Two design generations are covered by this file's history:

- 2026-09-12: replaced _quote_matches's flat coverage/anchor-floor check
  (which depended only on segment-label LENGTH) with a per-cell
  word-vocabulary allowlist (row label + group label + period header +
  the cell's own value).
- 2026-09-13: that word-vocabulary design was itself found to regress on
  a live 47-question eval baseline -- a genuinely faithful, byte-for-byte
  quote of an entire table row with MULTIPLE independently-claimed values
  (CRM's Current/Noncurrent/Total in one row; NVIDIA's multi-line
  caption+header+data quote) was wrongly refused, because the allowed
  vocabulary excluded sibling-column content by design. Replaced with a
  region-scoped redesign: match the quote (via numeric_utils.text_coverage,
  the same primitive _quote_matches uses for prose) against a small
  "permitted region" built from the cell's own VERBATIM source context
  (the table's leading caption/header rows + its own governing group
  label + its own data row), plus a separate check that every number the
  quote states is a real value found somewhere in that region (needed
  because pure coverage alone can be fooled by a wrong value whose digits
  scatter-match against OTHER real numbers in the same region -- found
  live re-verifying this exact redesign, see quote_is_grounded's own
  docstring). See docs/plans/2026-09-12-structure-aware-table-quote-
  grounding.md and docs/plans/2026-09-13-table-grounding-region-scoped-
  matching.md for the full investigations.

Fixtures below are REAL filing text (not paraphrased), extracted from
the actual chunks/*/*.jsonl files this project indexes, confirmed
against the real source during each investigation, not typed from
memory.
"""

from table_grounding import extract_table_blocks, locate_value, quote_is_grounded


# ---------------------------------------------------------------------------
# Real MSFT segment table, Q3 FY2026 10-Q (0001193125-26-191507). Three
# segment groups (label-only header row) each with 4 metric rows (Revenue/
# Cost of revenue/Operating expenses/Operating income), 4 value columns
# (3-month FY26, 3-month FY25, 9-month FY26, 9-month FY25). This is the
# exact real bug: "Intelligent Cloud" (18 normalized chars) and "More
# Personal Computing" (24) fall under _quote_matches's old 30-char anchor
# floor; "Productivity and Business Processes" (36) does not -- the
# original false negative depended only on this accident of label length.
# ---------------------------------------------------------------------------
MSFT_SEGMENT_CHUNK = """Segment revenue, cost of revenue, operating expenses, and operating income were as follows during the periods presented:

<TABLE>
| (In millions) | Three Months EndedMarch 31, | Nine Months EndedMarch 31, |  |  |
| --- | --- | --- | --- | --- |
| 2026 | 2025 | 2026 | 2025 |  |
| Productivity and Business Processes |  |  |  |  |
| Revenue | $35,013 | $29,944 | $102,149 | $87,698 |
| Cost of revenue | 6,197 | 5,517 | 18,028 | 16,380 |
| Operating expenses | 7,843 | 7,048 | 22,142 | 20,538 |
| Operating income | $20,973 | $17,379 | $61,979 | $50,780 |
| Intelligent Cloud |  |  |  |  |
| Revenue | $34,681 | $26,751 | $98,485 | $76,387 |
| Cost of revenue | 15,120 | 10,307 | 41,000 | 28,326 |
| Operating expenses | 5,808 | 5,349 | 16,468 | 15,612 |
| Operating income | $13,753 | $11,095 | $41,017 | $32,449 |
| More Personal Computing |  |  |  |  |
| Revenue | $13,192 | $13,371 | $41,198 | $41,198 |
| Cost of revenue | 5,511 | 6,095 | 17,821 | 19,111 |
| Operating expenses | 4,009 | 3,750 | 11,739 | 11,111 |
| Operating income | $3,672 | $3,526 | $11,638 | $10,976 |
| Total |  |  |  |  |
| Revenue | $82,886 | $70,066 | $241,832 | $205,283 |
| Cost of revenue | 26,828 | 21,919 | 76,849 | 63,817 |
| Operating expenses | 17,660 | 16,147 | 50,349 | 47,261 |
| Operating income | $38,398 | $32,000 | $114,634 | $94,205 |
</TABLE>"""

# Real AAPL geographic-segment table, FY2025 10-K (0000320193-25-000079).
# No label-only group-header row at all -- every row is its own top-level
# label ("Americas", "Europe", ...). Used to confirm grounding still works
# when there's no group label to find.
AAPL_SEGMENT_CHUNK = """The following table shows net sales by reportable segment for 2025, 2024 and 2023 (dollars in millions):

<TABLE>
| 2025 | Change | 2024 | Change | 2023 |  |
| --- | --- | --- | --- | --- | --- |
| Americas | $178,353 | 7% | $167,045 | 3% | $162,560 |
| Europe | 111,032 | 10% | 101,328 | 7% | 94,294 |
| Greater China | 64,377 | (4)% | 66,952 | (8)% | 72,559 |
| Total net sales | $416,161 | 6% | $391,035 | 2% | $383,285 |
</TABLE>"""

# Real CRM remaining-performance-obligation table, FY2026 Q3 10-Q
# (0001108524-26-000060). No group label; ONE row holds THREE genuinely
# different metrics (Current/Noncurrent/Total) for the same date -- the
# real regression this redesign fixes: the model quotes this entire row
# verbatim for each of the 3 independent claims, and a per-cell
# vocabulary check that excludes sibling-column content wrongly refuses
# all three.
CRM_RPO_CHUNK = """Remaining performance obligation consisted of the following (in billions):

<TABLE>
| Current | Noncurrent | Total |  |
| --- | --- | --- | --- |
| As of January 31, 2026 (1) | $35.1 | $37.3 | $72.4 |
| As of January 31, 2025 | $30.2 | $33.2 | $63.4 |
</TABLE>"""

# Real NVIDIA segment table, Q1 FY2027 10-Q (0001045810-26-000052). Two
# single-cell rows BEFORE the first data row -- "(In millions)" (a
# permanent, whole-table caption, parenthesized) and "Three Months Ended
# Apr 26, 2026" (a resettable, per-period group label, NOT parenthesized)
# -- confirms _classify_row's parenthesization signal, and that the
# SECOND period's rows (under "Three Months Ended Apr 27, 2025") get that
# period's own label, not the stale first one. The model's real quote
# here spans the column-header row, the separator row, the caption row,
# the period-label row, AND the data row, all verbatim.
NVDA_SEGMENT_CHUNK = """The table below presents details of our reportable segments.

<TABLE>
| Compute & Networking | Graphics | Total |  |
| --- | --- | --- | --- |
| (In millions) |  |  |  |
| Three Months Ended Apr 26, 2026 |  |  |  |
| Revenue | $74,550 | $7,065 | $81,615 |
| Other segment items (1) | 21,215 | 4,124 | 25,339 |
| Operating income | $53,335 | $2,941 | $56,276 |
| Three Months Ended Apr 27, 2025 |  |  |  |
| Revenue | $39,589 | $4,473 | $44,062 |
| Other segment items (1) | 17,535 | 2,833 | 20,368 |
| Operating income | $22,054 | $1,640 | $23,694 |
</TABLE>"""


def _cell(chunk_text, value, unit):
    blocks = extract_table_blocks(chunk_text)
    cells = locate_value(blocks, value, unit)
    assert cells, f"expected to locate {value} ({unit}) in the table, found nothing"
    return cells


# ---------------------------------------------------------------------------
# Accept: the real reported bug, both short labels
# ---------------------------------------------------------------------------
def test_accepts_reformatted_quote_under_the_short_intelligent_cloud_label():
    cells = _cell(MSFT_SEGMENT_CHUNK, 34681.0, "million")
    assert any(c.row_label == "Revenue" and c.group_label == "Intelligent Cloud" for c in cells)
    cell = next(c for c in cells if c.group_label == "Intelligent Cloud")
    assert quote_is_grounded("Intelligent Cloud\nRevenue $34,681", cell) is True


def test_accepts_reformatted_quote_under_the_short_more_personal_computing_label():
    cells = _cell(MSFT_SEGMENT_CHUNK, 13192.0, "million")
    cell = next(c for c in cells if c.group_label == "More Personal Computing")
    assert quote_is_grounded("More Personal Computing\nRevenue $13,192", cell) is True


def test_accepts_a_cell_value_reformatted_without_commas_or_dollar_sign():
    # A model restating "$34,681" as "$34681", "34681", or "$34,681.00"
    # must still ground -- _quote_matches's old flat coverage check
    # already tolerated exactly this kind of digit-formatting variance,
    # and text_coverage() (shared with this module) does too.
    cells = _cell(MSFT_SEGMENT_CHUNK, 34681.0, "million")
    cell = next(c for c in cells if c.group_label == "Intelligent Cloud")
    assert quote_is_grounded("Intelligent Cloud Revenue $34681", cell) is True
    assert quote_is_grounded("Intelligent Cloud Revenue 34681", cell) is True
    assert quote_is_grounded("Intelligent Cloud Revenue $34,681.00", cell) is True


# ---------------------------------------------------------------------------
# Accept: all four metric rows for one group -- a locality-only fix (see
# module docstring) only ever reaches the row immediately adjacent to the
# label, so Cost of revenue/Operating expenses/Operating income would stay
# broken under such a fix. This module fixes all four by construction.
# ---------------------------------------------------------------------------
def test_accepts_all_four_metric_rows_for_the_same_group():
    cases = [
        (34681.0, "Revenue", "$34,681"),
        (15120.0, "Cost of revenue", "15,120"),
        (5808.0, "Operating expenses", "5,808"),
        (13753.0, "Operating income", "$13,753"),
    ]
    for value, metric, rendered in cases:
        cells = _cell(MSFT_SEGMENT_CHUNK, value, "million")
        cell = next(c for c in cells if c.group_label == "Intelligent Cloud" and c.row_label == metric)
        quote = f"Intelligent Cloud\n{metric} {rendered}"
        assert quote_is_grounded(quote, cell) is True, f"{metric} should be grounded"


# ---------------------------------------------------------------------------
# Accept: a data row with no group-label row at all (AAPL geography table)
# ---------------------------------------------------------------------------
def test_accepts_a_row_with_no_group_label_row_above_it():
    cells = _cell(AAPL_SEGMENT_CHUNK, 178353.0, "million")
    cell = next(c for c in cells if c.row_label == "Americas")
    assert cell.group_label is None
    assert quote_is_grounded("Americas $178,353", cell) is True


def test_accepts_a_data_row_whose_group_label_row_is_missing_from_the_block():
    # Mirrors the AAPL case above but for a table shape that NORMALLY has
    # group labels -- proving the "no group label seen yet" code path
    # (group_label stays None until a label row is encountered) isn't
    # just exercised by AAPL's own naturally-flat layout.
    chunk = """Segment info.

<TABLE>
| (In millions) | Three Months EndedMarch 31, | Nine Months EndedMarch 31, |  |  |
| --- | --- | --- | --- | --- |
| 2026 | 2025 | 2026 | 2025 |  |
| Revenue | $34,681 | $26,751 | $98,485 | $76,387 |
</TABLE>"""
    cells = locate_value(extract_table_blocks(chunk), 34681.0, "million")
    cell = next(c for c in cells if c.row_label == "Revenue")
    assert cell.group_label is None
    assert quote_is_grounded("Revenue $34,681", cell) is True


# ---------------------------------------------------------------------------
# Accept: the two real regressions a live 47-question eval baseline found
# in the original word-vocabulary design (2026-09-13). Both are genuinely
# faithful, byte-for-byte quotes of a real table row/rows containing
# MULTIPLE values -- the exact-substring path within the cell's own
# narrow permitted_region is what accepts them, not a vocabulary rule.
# ---------------------------------------------------------------------------
def test_accepts_crm_full_row_verbatim_quote_grounding_all_three_claims():
    quote = "| As of January 31, 2026 (1) | $35.1 | $37.3 | $72.4 |"
    for value in (72.4, 35.1, 37.3):
        cells = _cell(CRM_RPO_CHUNK, value, "billion")
        assert any(quote_is_grounded(quote, cell) for cell in cells), f"{value} should ground"


def test_accepts_nvidia_multiline_verbatim_quote_spanning_caption_and_header_rows():
    quote = (
        "| Compute & Networking | Graphics | Total |  |\n"
        "| --- | --- | --- | --- |\n"
        "| (In millions) |  |  |  |\n"
        "| Three Months Ended Apr 26, 2026 |  |  |  |\n"
        "| Revenue | $74,550 | $7,065 | $81,615 |"
    )
    for value in (74550.0, 7065.0):
        cells = _cell(NVDA_SEGMENT_CHUNK, value, "million")
        cell = next(c for c in cells if c.group_label == "Three Months Ended Apr 26, 2026")
        assert quote_is_grounded(quote, cell) is True


def test_nvidia_second_period_gets_its_own_group_label_not_the_first_periods():
    # "(In millions)" (parenthesized -> permanent header, per _classify_row)
    # and "Three Months Ended Apr 26, 2026" (not parenthesized -> a
    # resettable group label) are BOTH single-cell rows before the first
    # data row -- confirms the parenthesization signal correctly tells
    # them apart, and that the second period's data rows get THEIR OWN
    # label, not a stale first-period one.
    cells = _cell(NVDA_SEGMENT_CHUNK, 39589.0, "million")
    cell = next(c for c in cells if c.row_label == "Revenue")
    assert cell.group_label == "Three Months Ended Apr 27, 2025"
    assert quote_is_grounded("Three Months Ended Apr 27, 2025\nRevenue $39,589", cell) is True


# ---------------------------------------------------------------------------
# Accept (deliberate design tradeoff, not a bug): a quote naming a sibling
# column's value from the SAME row. Confirmed already-inert on the real
# table (period_header mapping was never reliable here to begin with, per
# the removed _period_header_index's own findings) and consistent with
# this module's other accepted multi-value-per-row cases above (CRM,
# NVIDIA) -- the permitted region is scoped to the whole ROW, not one
# column, by design. The actual defense against a wrong VALUE is
# quote_is_grounded's number check (see the reject tests below), not
# column-level exclusion.
# ---------------------------------------------------------------------------
def test_accepts_a_quote_naming_the_sibling_columns_value():
    cells = _cell(MSFT_SEGMENT_CHUNK, 34681.0, "million")
    cell = next(c for c in cells if c.group_label == "Intelligent Cloud")
    assert quote_is_grounded("Intelligent Cloud\nRevenue $26,751", cell) is True


def test_rejects_a_quote_cherry_picking_one_year_from_the_header_row():
    # Distinct from the sibling-VALUE test above: this quote names a
    # WRONG-COLUMN's own LABEL ("2023") without the correct one ("2025"),
    # rather than just citing a bare sibling value with no label at all.
    # Found live 2026-09-13 by an independent review of this exact
    # redesign: an earlier version of this function let this through,
    # since "2023" and "$178,353" are both genuinely present SOMEWHERE
    # in the region (the whole point of including header rows wholesale)
    # -- but the yesterday-committed design (before this redesign)
    # correctly rejected this exact case, so accepting it was a real
    # regression, not the same already-accepted tradeoff as citing a
    # bare sibling value. quote_is_grounded's cherry-pick check (some but
    # not all of a multi-column header row's own labels) is what closes
    # this: "2023" is 1 of 4 distinct labels in AAPL's header row
    # ("2025"/"Change"/"2024"/"2023"), so citing it alone is rejected.
    cells = _cell(AAPL_SEGMENT_CHUNK, 178353.0, "million")
    cell = next(c for c in cells if c.row_label == "Americas")
    assert quote_is_grounded("2023 Americas $178,353", cell) is False


# ---------------------------------------------------------------------------
# Reject: value spliced across a row boundary. A markdown row break
# ("...|\n|...") and an empty cell ("| |") normalize to the identical
# string, so a naive locality-based fix (accept a split match when the
# gap between fragments is only table punctuation) cannot tell "the label
# and value genuinely on the same logical row" from "the tail of the row
# above, glued onto the next row's label" -- confirmed live: an
# unconditional "exact substring of the whole source" shortcut (tried and
# reverted 2026-09-13) let a $50,780 (Productivity & Business Processes'
# own 9-month FY2025 operating income) claim be "grounded" by a quote
# that names Intelligent Cloud and its unrelated $34,681 revenue. This is
# the single most important regression test in this file.
# ---------------------------------------------------------------------------
def test_rejects_a_value_spliced_across_a_row_boundary():
    cells = _cell(MSFT_SEGMENT_CHUNK, 50780.0, "million")
    cell = next(c for c in cells if c.group_label == "Productivity and Business Processes")
    assert quote_is_grounded("$50,780 Intelligent Cloud Revenue $34,681", cell) is False
    assert quote_is_grounded("$50,780 Intelligent Cloud", cell) is False


# ---------------------------------------------------------------------------
# Reject: fabricated values never resolve to any cell in the first place,
# so they can't be "grounded" by anything.
# ---------------------------------------------------------------------------
def test_locate_value_finds_nothing_for_a_fabricated_ten_x_value():
    assert locate_value(extract_table_blocks(MSFT_SEGMENT_CHUNK), 134681.0, "million") == []


def test_locate_value_finds_nothing_for_a_fabricated_sign_flip():
    assert locate_value(extract_table_blocks(MSFT_SEGMENT_CHUNK), -34681.0, "million") == []


# ---------------------------------------------------------------------------
# Reject: cross-group steal -- the claimed value genuinely exists in the
# table, but under a DIFFERENT group than the quote names.
# ---------------------------------------------------------------------------
def test_rejects_a_value_grounded_under_the_wrong_group_label():
    cells = _cell(MSFT_SEGMENT_CHUNK, 35013.0, "million")
    cell = next(c for c in cells if c.group_label == "Productivity and Business Processes")
    assert quote_is_grounded("Intelligent Cloud Revenue $35,013", cell) is False


def test_rejects_cross_segment_steal_via_a_near_tolerance_duplicate_cell():
    # Regression B (found live 2026-09-13, re-running the full eval
    # baseline): Intelligent Cloud's real revenue ($34,681M) and
    # Productivity & Business Processes' real revenue ($35,013M) are
    # ~0.95% apart -- both within the standard 1%-relative tolerance of a
    # $35,013M claim, so locate_value() returns BOTH cells, not just the
    # correct one. A quote naming Intelligent Cloud's label with
    # Productivity's real value must be rejected against the
    # (wrong) Intelligent Cloud cell specifically -- checking this
    # requires comparing against the CELL'S OWN content, not the
    # claim's own asserted value (which would trivially always match).
    cells = locate_value(extract_table_blocks(MSFT_SEGMENT_CHUNK), 35013.0, "million")
    group_labels = {c.group_label for c in cells}
    assert group_labels == {"Productivity and Business Processes", "Intelligent Cloud"}, (
        "expected the 1%-relative tolerance to also catch Intelligent Cloud's $34,681M -- "
        "if this stops being true the regression this test guards against can no longer be "
        "exercised this way"
    )
    intelligent_cloud_cell = next(c for c in cells if c.group_label == "Intelligent Cloud")
    assert intelligent_cloud_cell.cell_text == "$34,681"
    assert quote_is_grounded("Intelligent Cloud Revenue $35,013", intelligent_cloud_cell) is False


def test_rejects_a_value_not_actually_present_anywhere_in_the_region():
    # Found live 2026-09-13, re-verifying this exact redesign before
    # shipping it: pure text coverage alone can be fooled by a WRONG
    # value whose digits happen to scatter-match (via
    # difflib.SequenceMatcher finding non-contiguous fragments) against
    # OTHER real numbers sprinkled through the same permitted region --
    # measured "$35,013" scoring 94% coverage against Intelligent
    # Cloud's own region (which contains no $35,013 at all) purely from
    # shared digits with $34,681/$26,751/etc. quote_is_grounded's
    # separate number-presence check (tight tolerance, not the loose
    # 1%-relative one locate_value uses) is what catches this -- a value
    # with no real match anywhere in the region, however its digits
    # happen to overlap with ones that are, must be rejected even when
    # overall text coverage alone would have passed.
    cells = _cell(MSFT_SEGMENT_CHUNK, 34681.0, "million")
    cell = next(c for c in cells if c.group_label == "Intelligent Cloud")
    assert quote_is_grounded("Intelligent Cloud Revenue $999,999", cell) is False


# ---------------------------------------------------------------------------
# A bare period-year token ("2026") is one of TWO distinct year labels in
# MSFT's own header row ("2026 | 2025 | 2026 | 2025"), so quote_is_grounded's
# cherry-pick check now rejects citing it alone, without the sibling
# ("2025") -- deliberately conservative: this rule can't tell "the model
# happened to name the objectively correct period" from "the model named
# the wrong one" (that would need reliable per-column mapping, already
# shown unreliable for a genuinely-spanning header row -- see
# _period_header_index's removal history), so it treats ANY single-token
# citation from a multi-column row as unverifiable rather than risk
# accepting a wrong one. This trades away the narrow, synthetic
# "content-free quote" convenience an earlier version of this test
# documented, in favor of closing the real misattribution this same
# mechanism exists to catch (see test_rejects_a_quote_cherry_picking_
# one_year_from_the_header_row and the two end-to-end regression tests
# in tests/test_agent.py for the real cases that motivated this).
# ---------------------------------------------------------------------------
def test_quote_is_grounded_rejects_a_bare_year_with_no_label_at_all():
    cells = _cell(MSFT_SEGMENT_CHUNK, 34681.0, "million")
    cell = next(c for c in cells if c.group_label == "Intelligent Cloud")
    assert quote_is_grounded("2026 34681", cell) is False


# ---------------------------------------------------------------------------
# extract_table_blocks / locate_value: no table, or no matching cell
# ---------------------------------------------------------------------------
def test_extract_table_blocks_returns_empty_list_for_prose_with_no_table():
    assert extract_table_blocks("Revenue was $100 million in the quarter, up from $90 million.") == []


def test_locate_value_returns_empty_list_when_value_is_only_in_prose_not_the_table():
    # A chunk can hold a table AND prose; a value stated only in the prose
    # part must fall through to the ordinary _quote_matches path rather
    # than being (wrongly) treated as ungrounded-in-a-table.
    chunk = "Total headcount was 228,000 employees.\n\n" + MSFT_SEGMENT_CHUNK
    assert locate_value(extract_table_blocks(chunk), 228000.0, "raw") == []


# ---------------------------------------------------------------------------
# Multiple <TABLE> blocks in one chunk -- a real gap an independent review
# of this redesign found: no existing test exercised this at all. Confirms
# each block's header_context/group_label/caption_units are recomputed
# independently per block (no state leaking from one table into another's
# permitted_region), using two real, distinct fixtures already in this
# file rather than a synthetic one.
# ---------------------------------------------------------------------------
def test_two_table_blocks_in_one_chunk_do_not_leak_context_between_them():
    chunk = MSFT_SEGMENT_CHUNK + "\n\n" + AAPL_SEGMENT_CHUNK
    blocks = extract_table_blocks(chunk)
    assert len(blocks) == 2

    msft_cells = locate_value(blocks, 34681.0, "million")
    ic_cell = next(c for c in msft_cells if c.group_label == "Intelligent Cloud")
    assert "Americas" not in ic_cell.permitted_region
    assert "178,353" not in ic_cell.permitted_region

    aapl_cells = locate_value(blocks, 178353.0, "million")
    americas_cell = next(c for c in aapl_cells if c.row_label == "Americas")
    assert "Intelligent Cloud" not in americas_cell.permitted_region
    assert "34,681" not in americas_cell.permitted_region

    # Each still grounds correctly against its OWN block.
    assert quote_is_grounded("Intelligent Cloud\nRevenue $34,681", ic_cell) is True
    assert quote_is_grounded("Americas $178,353", americas_cell) is True
