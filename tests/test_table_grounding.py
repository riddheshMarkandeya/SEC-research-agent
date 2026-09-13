"""
Unit tests for table_grounding.py -- structure-aware quote verification
for values that live in a markdown table, added 2026-09-12 to replace
_quote_matches's flat-text anchor floor for table sources. See
docs/plans/2026-09-12-structure-aware-table-quote-grounding.md for the
full design and the measured evidence behind it: a flat coverage/anchor
check depends only on label LENGTH (a false negative on short segment
labels like "Intelligent Cloud"), and loosening it with source-side
locality alone opens a real end-to-end bypass (a quote can splice a
value from one table row onto an unrelated adjacent row's label, since
a markdown row boundary and an empty cell normalize to the identical
string). Verifying row-group/row-label/column alignment structurally,
rather than tuning a string-similarity threshold, is the only fix that
closes both problems at once.

Fixtures below are REAL filing text (not paraphrased), extracted via
chunk_documents.table_to_markdown() from the actual data/*_tables.json
files and confirmed to match the real chunk text in
chunks/MSFT/0001193125-26-191507_chunks.jsonl -- captured this way
during the investigation that produced this module, not typed from
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
# when there's no group label to find, and as the real-world repro for the
# "bridge across the markdown separator row" attack an adversarial review
# found against a naive locality-based fix (a quote pulling FY2023's value
# under a header token belonging to FY2025 must still be rejected).
AAPL_SEGMENT_CHUNK = """The following table shows net sales by reportable segment for 2025, 2024 and 2023 (dollars in millions):

<TABLE>
| 2025 | Change | 2024 | Change | 2023 |  |
| --- | --- | --- | --- | --- | --- |
| Americas | $178,353 | 7% | $167,045 | 3% | $162,560 |
| Europe | 111,032 | 10% | 101,328 | 7% | 94,294 |
| Greater China | 64,377 | (4)% | 66,952 | (8)% | 72,559 |
| Total net sales | $416,161 | 6% | $391,035 | 2% | $383,285 |
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


def test_accepts_a_cell_value_reformatted_without_commas_or_dollar_sign():
    # Found in this fix's own review (2026-09-12): an earlier version
    # required the cell's own rendered text to appear as a literal
    # token, which is STRICTER than _quote_matches's old flat-text
    # coverage check ever was (that one tolerated exactly this kind of
    # digit-formatting variance via its coverage ratio) -- a model
    # restating "$34,681" as "$34681", "34681", or "$34,681.00" must
    # still ground, not newly refuse a genuinely correct answer.
    cells = _cell(MSFT_SEGMENT_CHUNK, 34681.0, "million")
    cell = next(c for c in cells if c.group_label == "Intelligent Cloud")
    assert quote_is_grounded("Intelligent Cloud Revenue $34681", cell) is True
    assert quote_is_grounded("Intelligent Cloud Revenue 34681", cell) is True
    assert quote_is_grounded("Intelligent Cloud Revenue $34,681.00", cell) is True


def test_accepts_reformatted_quote_under_the_short_more_personal_computing_label():
    cells = _cell(MSFT_SEGMENT_CHUNK, 13192.0, "million")
    cell = next(c for c in cells if c.group_label == "More Personal Computing")
    assert quote_is_grounded("More Personal Computing\nRevenue $13,192", cell) is True


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


# ---------------------------------------------------------------------------
# Reject: value spliced across a row boundary. A markdown row break
# ("...|\n|...") and an empty cell ("| |") normalize to the identical
# string, so a naive locality-based fix (accept a split match when the
# gap between fragments is only table punctuation) cannot tell "the label
# and value genuinely on the same logical row" from "the tail of the row
# above, glued onto the next row's label" -- confirmed live: patching that
# fix into _verify_one_claim let a $50,780 (Productivity & Business
# Processes' own 9-month FY2025 operating income) claim be "grounded" by a
# quote that names Intelligent Cloud and its unrelated $34,681 revenue.
# ---------------------------------------------------------------------------
def test_rejects_a_value_spliced_across_a_row_boundary():
    cells = _cell(MSFT_SEGMENT_CHUNK, 50780.0, "million")
    cell = next(c for c in cells if c.group_label == "Productivity and Business Processes")
    assert quote_is_grounded("$50,780 Intelligent Cloud Revenue $34,681", cell) is False
    assert quote_is_grounded("$50,780 Intelligent Cloud", cell) is False


# ---------------------------------------------------------------------------
# Reject: fabricated values never resolve to any cell in the first place,
# so they can't be "grounded" by anything -- this is what actually
# forecloses the value-insertion holes (a 10x digit insertion, an inserted
# minus sign) that a flat coverage-ratio check's 10% slack let through.
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


# ---------------------------------------------------------------------------
# Reject: the quote states the adjacent prior-year sibling column's value,
# not the claimed value's own column -- the claimed value is 34,681 (3mo
# FY26), but the quote's number is 26,751 (3mo FY25, same row). Own-cell
# text, not "any number in the row," is what must be present.
# ---------------------------------------------------------------------------
def test_rejects_a_quote_naming_the_sibling_columns_value():
    cells = _cell(MSFT_SEGMENT_CHUNK, 34681.0, "million")
    cell = next(c for c in cells if c.group_label == "Intelligent Cloud")
    assert quote_is_grounded("Intelligent Cloud\nRevenue $26,751", cell) is False


# ---------------------------------------------------------------------------
# Reject: wrong column header token. $35,013 is Productivity & Business
# Processes' THREE-MONTH FY2026 revenue (column header "2026"); a quote
# prefixing it with "2025" (the sibling column's header) must not verify,
# even though "2025" genuinely appears elsewhere in the same table.
# ---------------------------------------------------------------------------
def test_rejects_a_quote_with_the_wrong_periods_header_token():
    cells = _cell(MSFT_SEGMENT_CHUNK, 35013.0, "million")
    cell = next(c for c in cells if c.group_label == "Productivity and Business Processes")
    assert cell.period_header == "2026"
    assert quote_is_grounded("2025 Productivity and Business Processes Revenue $35,013", cell) is False


# ---------------------------------------------------------------------------
# Reject: bridging the markdown "| --- |" separator row. Found by an
# adversarial review of an earlier locality-based candidate fix: since '-'
# was treated as filler, a quote could splice FY2023's value onto the
# FY2025 header token across the separator row. This module never treats
# the separator row as data or as a header at all, so the hole doesn't
# exist to begin with -- but it's regression-tested directly since it's
# real filing text, not a synthetic case.
# ---------------------------------------------------------------------------
def test_rejects_a_quote_bridging_the_separator_row_to_the_wrong_year():
    cells = _cell(AAPL_SEGMENT_CHUNK, 178353.0, "million")
    cell = next(c for c in cells if c.row_label == "Americas")
    assert cell.period_header == "2025"
    assert quote_is_grounded("2023 Americas $178,353", cell) is False


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
# _period_header_index: the column-shift correction must be computed per
# ROW, not cached once per table from an arbitrary "sample" row. Found in
# this fix's own architecture review (2026-09-12): an earlier version
# cached the block's FIRST data row's own trailing-empty-cell count as a
# block-wide constant. A newly-disclosed segment with no prior-year
# comparative (a real, plausible SEC-filing shape -- the row reports only
# ONE period, so clean_row strips the missing trailing columns entirely,
# leaving that row shorter before table_to_markdown pads it back out)
# would then poison the period-header mapping for EVERY OTHER row in the
# same block, silently returning a wrong-but-in-bounds column instead of
# None. Recomputing the shift from whichever row owns the cell being
# checked closes this by construction.
# ---------------------------------------------------------------------------
_SPARSE_FIRST_ROW_CHUNK = """Segment info, in millions.

<TABLE>
| 2026 | 2025 | 2026 | 2025 |  |
| New Segment (no prior-year comparative) | $500 |  |  |  |
| Revenue | $34,681 | $26,751 | $98,485 | $76,387 |
</TABLE>"""


def test_period_header_is_computed_per_row_not_from_a_cached_sample_row():
    cells = _cell(_SPARSE_FIRST_ROW_CHUNK, 34681.0, "million")
    cell = next(c for c in cells if c.row_label == "Revenue")
    # The FIRST data row ("New Segment...") has only 1 of 4 value columns
    # filled, so table_to_markdown pads it out with 3 TRAILING empties --
    # very different from the "Revenue" row's own 0. A block-wide shift
    # cached from that first row would misattribute $34,681 (the 3-month
    # FY2026 column) to "2025" instead of "2026".
    assert cell.period_header == "2026"


# ---------------------------------------------------------------------------
# quote_is_grounded's accepted edge cases -- documented explicitly per the
# architecture review (2026-09-12), not left implicit.
# ---------------------------------------------------------------------------
def test_quote_is_grounded_accepts_a_content_free_quote_of_just_header_and_value():
    # quote_is_grounded alone doesn't REQUIRE the row/group label words to
    # appear at all -- a quote of just the period header plus the bare
    # value ("2026 34681", no "Intelligent Cloud"/"Revenue" at all) passes
    # this function on its own. Not exploitable as a misattribution today:
    # locate_value() has already narrowed to the ONE cell whose value
    # matches the CLAIM within tolerance before this ever runs, so a
    # content-free quote can't smuggle in a wrong cell -- it just doesn't
    # (and structurally can't) make any claim this function would reject.
    cells = _cell(MSFT_SEGMENT_CHUNK, 34681.0, "million")
    cell = next(c for c in cells if c.group_label == "Intelligent Cloud")
    assert quote_is_grounded("2026 34681", cell) is True


def test_accepts_a_data_row_whose_group_label_row_is_missing_from_the_block():
    # Mirrors test_accepts_a_row_with_no_group_label_row_above_it (AAPL)
    # but for a table shape that NORMALLY has group labels -- proving the
    # "no group label seen yet" code path (group_label stays None until a
    # label row is encountered) isn't just exercised by AAPL's own
    # naturally-flat layout. chunk_blocks() never actually splits a
    # <TABLE> block mid-table (tables are always kept atomic), so this
    # can't arise from chunking in practice -- but the underlying
    # structural case (a data row with nothing but header rows above it)
    # is real and worth pinning directly rather than only indirectly.
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
