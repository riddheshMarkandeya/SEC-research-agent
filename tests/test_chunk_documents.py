"""
Unit tests for chunk_documents.py. Covers only the pure, deterministic
functions (string/list transforms) — process_filing()/main() do file I/O
and aren't unit-tested here; that's exercised by actually running the
script (see PROJECT_CONTEXT.md's "Verified working" section).
"""

from chunk_documents import (
    MAX_CHUNK_CHARS,
    OVERLAP_CHARS,
    TARGET_CHUNK_CHARS,
    chunk_blocks,
    clean_row,
    is_exhibit_index_table,
    reconstruct_document,
    split_by_sentences,
    split_into_blocks,
    split_prose_block,
    strip_leading_metadata,
    table_to_markdown,
)


# ---------------------------------------------------------------------------
# clean_row
# ---------------------------------------------------------------------------
def test_clean_row_merges_dollar_sign_with_following_value():
    assert clean_row(["Americas", "$", "45,781", "", "", ""]) == ["Americas", "$45,781"]


def test_clean_row_merges_percent_sign_with_preceding_value():
    assert clean_row(["Growth", "20", "%"]) == ["Growth", "20%"]


def test_clean_row_drops_all_empty_cells():
    assert clean_row(["", "  ", ""]) == []


def test_clean_row_passthrough_when_nothing_to_merge():
    assert clean_row(["Segment", "Revenue", "12345"]) == ["Segment", "Revenue", "12345"]


def test_clean_row_trailing_lone_dollar_sign_not_dropped():
    # No value follows the "$", so the merge condition can't fire —
    # it should still come through as its own cell, not vanish.
    assert clean_row(["Total", "$"]) == ["Total", "$"]


# ---------------------------------------------------------------------------
# table_to_markdown
# ---------------------------------------------------------------------------
def test_table_to_markdown_basic_shape():
    table = {"table_index": 0, "rows": [["Segment", "Revenue"], ["Americas", "$45,781"]]}
    md = table_to_markdown(table)
    lines = md.split("\n")
    assert lines[0] == "| Segment | Revenue |"
    assert lines[1] == "| --- | --- |"
    assert lines[2] == "| Americas | $45,781 |"


def test_table_to_markdown_pads_ragged_rows():
    table = {"table_index": 0, "rows": [["A", "B", "C"], ["1", "2"]]}
    md = table_to_markdown(table)
    body_row = md.split("\n")[2]
    # Second row is short a column — should be padded with an empty cell,
    # not raise or silently misalign the table.
    assert body_row == "| 1 | 2 |  |"


def test_table_to_markdown_empty_rows_returns_empty_string():
    assert table_to_markdown({"table_index": 0, "rows": [[], [""]]}) == ""


# ---------------------------------------------------------------------------
# strip_leading_metadata
# ---------------------------------------------------------------------------
def test_strip_leading_metadata_keeps_united_states_line():
    text = "junk before the header\nUNITED STATES\nSECURITIES AND EXCHANGE COMMISSION\nreal content"
    result = strip_leading_metadata(text)
    assert "junk before the header" not in result
    assert "UNITED STATES" in result
    assert result.endswith("real content")


def test_strip_leading_metadata_no_united_states_nearby():
    text = "some unrelated junk\nSECURITIES AND EXCHANGE COMMISSION\nreal content"
    result = strip_leading_metadata(text)
    assert "some unrelated junk" not in result
    assert result.startswith("SECURITIES AND EXCHANGE COMMISSION")


def test_strip_leading_metadata_anchor_absent_returns_unchanged():
    text = "just some plain filing text with no boilerplate anchor"
    assert strip_leading_metadata(text) == text


def test_strip_leading_metadata_one_newline_before_united_states():
    # "UNITED STATES" is the very first line -- only one newline (its own
    # trailing one) exists anywhere before the anchor, unlike the happy-
    # path test above which has a junk line ahead of it too. review §6:
    # the nested rfind() used to return -1 here, and text[-1:] silently
    # slices from the END of the string instead of the start, truncating
    # the whole document down to its last character.
    text = "UNITED STATES\nSECURITIES AND EXCHANGE COMMISSION\nreal content"
    result = strip_leading_metadata(text)
    assert result.startswith("UNITED STATES")
    assert result.endswith("real content")


def test_strip_leading_metadata_no_newline_before_united_states():
    # Zero newlines anywhere before the anchor -- "UNITED STATES" and the
    # anchor are effectively on the same unbroken run of text. Same -1
    # landmine as the one-newline case above, just via the OUTER rfind
    # failing this time instead of not existing to call at all.
    text = "UNITED STATESSECURITIES AND EXCHANGE COMMISSION\nreal content"
    result = strip_leading_metadata(text)
    assert result.startswith("UNITED STATES")
    assert result.endswith("real content")


# ---------------------------------------------------------------------------
# reconstruct_document
# ---------------------------------------------------------------------------
def test_reconstruct_document_splices_table_markdown_at_marker():
    text = "Intro sentence.\n[TABLE_0]\nOutro sentence."
    tables = [{"table_index": 0, "rows": [["A", "B"], ["1", "2"]]}]
    result = reconstruct_document(text, tables)
    assert "[TABLE_0]" not in result
    assert "<TABLE>" in result and "</TABLE>" in result
    assert "| A | B |" in result
    assert "Intro sentence." in result and "Outro sentence." in result


def test_reconstruct_document_marker_with_missing_table_dropped_silently():
    text = "Before.\n[TABLE_5]\nAfter."
    result = reconstruct_document(text, tables=[])
    assert "[TABLE_5]" not in result
    assert "<TABLE>" not in result
    assert "Before." in result and "After." in result


# ---------------------------------------------------------------------------
# split_by_sentences
# ---------------------------------------------------------------------------
def test_split_by_sentences_splits_on_sentence_boundaries():
    text = "First sentence. Second sentence. Third sentence."
    result = split_by_sentences(text, max_chars=1000)
    assert result == ["First sentence.", "Second sentence.", "Third sentence."]


def test_split_by_sentences_hard_slices_when_no_boundaries_at_all():
    text = "x" * 25  # no '.', '!', or '?' anywhere
    result = split_by_sentences(text, max_chars=10)
    assert result == ["x" * 10, "x" * 10, "x" * 5]


def test_split_by_sentences_hard_slices_an_oversized_single_sentence():
    text = "a" * 20 + "."  # one "sentence" that's still too long on its own
    result = split_by_sentences(text, max_chars=10)
    assert all(len(piece) <= 10 for piece in result)
    assert "".join(result) == text


# ---------------------------------------------------------------------------
# split_prose_block
# ---------------------------------------------------------------------------
def test_split_prose_block_short_text_passes_through_unchanged():
    text = "Short paragraph, well under the limit."
    assert split_prose_block(text, max_chars=1000) == [text]


def test_split_prose_block_falls_back_to_line_splitting():
    # No blank-line breaks (that's split_into_blocks' job), but there ARE
    # single-newline breaks — e.g. NVDA's Risk Factors formatting.
    lines = ["Line one is here.", "Line two is here.", "Line three is here."]
    text = "\n".join(lines)
    result = split_prose_block(text, max_chars=len(text) - 1)
    assert result == lines


def test_split_prose_block_falls_back_to_hard_slicing_with_no_breaks_at_all():
    text = "x" * 50  # no newlines, no sentence punctuation
    result = split_prose_block(text, max_chars=20)
    assert all(len(piece) <= 20 for piece in result)
    assert "".join(result) == text


# ---------------------------------------------------------------------------
# is_exhibit_index_table — regression test for the header-collapse bug
# ---------------------------------------------------------------------------
def test_is_exhibit_index_table_detects_normally_spaced_header():
    md = "| Exhibit Number | Incorporated by Reference |\n| --- | --- |\n| 3.1 | ... |"
    assert is_exhibit_index_table(md) is True


def test_is_exhibit_index_table_detects_collapsed_colspan_header():
    # This exact shape (space lost between "Exhibit" and "Number" from a
    # colspan header cell) is the real bug found and fixed this project —
    # 15 of 25 filings' exhibit tables leaked through before this fix.
    md = "| ExhibitNumber | ProvidedHerewith | Incorporated by Reference |\n| --- | --- |"
    assert is_exhibit_index_table(md) is True


def test_is_exhibit_index_table_detects_collapsed_filing_date_variant():
    md = "| ExhibitNo. | ExhibitDescription | Form | FilingDate |\n| --- | --- |"
    assert is_exhibit_index_table(md) is True


def test_is_exhibit_index_table_false_for_ordinary_financial_table():
    md = "| Segment | Net Sales | Growth |\n| --- | --- | --- |\n| Americas | $45,781 | 10% |"
    assert is_exhibit_index_table(md) is False


def test_is_exhibit_index_table_requires_both_signals():
    # Only one half of the signal present — should not trigger a false positive.
    md = "| Filing Date | Description |\n| --- | --- |\n| 1/1/2025 | Annual report |"
    assert is_exhibit_index_table(md) is False


# ---------------------------------------------------------------------------
# split_into_blocks
# ---------------------------------------------------------------------------
def test_split_into_blocks_separates_prose_and_table():
    document = "Intro paragraph.\n\n<TABLE>\n| A | B |\n| --- | --- |\n</TABLE>\n\nOutro paragraph."
    blocks = split_into_blocks(document)
    assert "Intro paragraph." in blocks
    assert "Outro paragraph." in blocks
    assert any(b.startswith("<TABLE>") for b in blocks)


def test_split_into_blocks_drops_exhibit_index_table():
    document = (
        "Some prose.\n\n"
        "<TABLE>\n| Exhibit Number | Incorporated by Reference |\n| --- | --- |\n</TABLE>\n\n"
        "More prose."
    )
    blocks = split_into_blocks(document)
    assert not any("<TABLE>" in b for b in blocks)
    assert "Some prose." in blocks and "More prose." in blocks


def test_split_into_blocks_splits_oversized_paragraph():
    document = "x" * (MAX_CHUNK_CHARS + 500)  # single paragraph, no blank lines, no tables
    blocks = split_into_blocks(document)
    assert len(blocks) > 1
    assert all(len(b) <= MAX_CHUNK_CHARS for b in blocks)


# ---------------------------------------------------------------------------
# chunk_blocks
# ---------------------------------------------------------------------------
def test_chunk_blocks_accumulates_until_target_then_flushes_with_overlap():
    block1 = "A" * 1000
    block2 = "B" * 1000
    block3 = "C" * 100
    chunks = chunk_blocks([block1, block2, block3])

    assert len(chunks) == 2
    assert chunks[0].startswith(block1)
    assert chunks[0].endswith(block2)
    # second chunk should open with the carried-forward overlap tail from block2
    assert chunks[1].startswith("B" * OVERLAP_CHARS)
    assert chunks[1].endswith(block3)


def test_chunk_blocks_keeps_oversized_table_block_whole():
    oversized_table = "<TABLE>\n" + ("X" * (MAX_CHUNK_CHARS + 2000)) + "\n</TABLE>"
    chunks = chunk_blocks([oversized_table])
    assert chunks == [oversized_table]
    assert len(chunks[0]) > MAX_CHUNK_CHARS  # confirms it was NOT split


def test_chunk_blocks_drops_leftover_overlap_only_tail():
    # First block exactly hits TARGET_CHUNK_CHARS so it flushes immediately,
    # leaving current = last OVERLAP_CHARS chars of it (pure carried-over
    # context, no unique content of its own).
    block1 = "A" * TARGET_CHUNK_CHARS
    # Second block is big enough that appending it to the overlap tail
    # would overflow MAX_CHUNK_CHARS, forcing the overlap-only tail to be
    # evaluated on its own for the drop-vs-keep decision.
    block2 = "B" * (MAX_CHUNK_CHARS - OVERLAP_CHARS - 1)

    chunks = chunk_blocks([block1, block2])

    assert len(chunks) == 2
    assert chunks[0] == block1
    # If the overlap tail had been kept, chunks[1] would start with "A"s.
    assert chunks[1] == block2
    assert not chunks[1].startswith("A")


def test_chunk_blocks_drops_leftover_overlap_only_tail_at_end_of_document():
    # block1 exactly hits TARGET_CHUNK_CHARS, so it flushes mid-loop and
    # leaves current = the last OVERLAP_CHARS chars of it. With no block
    # after it, that stale overlap tail used to be emitted as its own
    # malformed final "chunk" (review §5) -- pure duplicate content of
    # chunks[0]'s own tail, with no unique content of its own.
    block1 = "A" * TARGET_CHUNK_CHARS

    chunks = chunk_blocks([block1])

    assert chunks == [block1]


def test_chunk_blocks_keeps_short_final_block_with_genuine_content():
    # An oversized table forces an overflow-reset (current = the table
    # alone, kept whole per test_chunk_blocks_keeps_oversized_table_block_whole
    # above). The short paragraph right after it is genuine, never-before-
    # emitted content -- unlike the overlap-tail case above, it must NOT
    # be dropped just because it's short.
    oversized_table = "<TABLE>\n" + ("X" * (MAX_CHUNK_CHARS + 2000)) + "\n</TABLE>"
    short_final_paragraph = "Z" * (OVERLAP_CHARS - 50)

    chunks = chunk_blocks([oversized_table, short_final_paragraph])

    assert chunks == [oversized_table, short_final_paragraph]


def test_chunk_blocks_keeps_short_genuine_content_closed_out_mid_document():
    # A short first block (never touched by the overlap reset, so
    # current_is_only_overlap is False) gets closed out by the MID-LOOP
    # overflow branch, not the final flush, when the next block is too
    # big to merge with it. Old code would have dropped it here too (its
    # length check couldn't tell this apart from an overlap tail) -- this
    # is the mid-loop counterpart to
    # test_chunk_blocks_keeps_short_final_block_with_genuine_content
    # above, which only covers the same guarantee at the final flush.
    short_first_paragraph = "Y" * (OVERLAP_CHARS - 50)
    oversized_table = "<TABLE>\n" + ("X" * (MAX_CHUNK_CHARS + 2000)) + "\n</TABLE>"

    chunks = chunk_blocks([short_first_paragraph, oversized_table])

    assert chunks == [short_first_paragraph, oversized_table]


def test_chunk_blocks_drops_overlap_that_would_orphan_a_table_close_tag():
    # If the flush point's raw OVERLAP_CHARS-char tail lands inside a
    # table -- past its own <TABLE> open tag but including its
    # </TABLE> close tag -- carrying that slice forward would present
    # extract_table_blocks() with an unmatched </TABLE> in the next
    # chunk, hiding a real table row from downstream grounding. This
    # table is long enough that the last OVERLAP_CHARS chars of the
    # flushed chunk land past its own opening tag.
    prose = "A" * 1683
    table = "<TABLE>\n" + ("X" * 300) + "\n</TABLE>"
    block3 = "C" * 100

    chunks = chunk_blocks([prose, table, block3])

    assert len(chunks) == 2
    assert chunks[0].endswith(table)
    assert chunks[1] == block3
    assert "</TABLE>" not in chunks[1]


def test_chunk_blocks_overlap_keeps_prose_after_orphaned_table_close():
    # Same hazard as the test above, but this time the table closes
    # with room to spare before the tail ends, so genuine prose follows
    # the orphaned </TABLE> within the same OVERLAP_CHARS slice. That
    # prose carries no table state and must survive into the next
    # chunk -- only the unpaired table fragment itself is unsafe to
    # keep.
    prose = "A" * 1746
    table = "<TABLE>\n" + ("X" * 183) + "\n</TABLE>"  # 200 chars
    trailing_prose = "P" * 50
    block4 = "C" * 100

    chunks = chunk_blocks([prose, table, trailing_prose, block4])

    assert len(chunks) == 2
    assert "</TABLE>" not in chunks[1]
    assert "<TABLE>" not in chunks[1]
    assert "P" * 50 in chunks[1]


def test_chunk_blocks_overlap_preserves_complete_table_after_the_orphan():
    # Two tables can both fall within the same OVERLAP_CHARS tail: an
    # orphaned close from the first (whose <TABLE> stayed behind in the
    # flushed chunk) followed by a second, fully self-contained table.
    # The orphan is always the FIRST </TABLE> in the tail -- tables
    # never nest, so anything after it must open fresh within the tail
    # -- so stripping up to the first (not last) </TABLE> removes only
    # the orphan while preserving the second table's genuinely valid,
    # paired content.
    prose = "A" * 1661
    table1 = "<TABLE>\n" + ("X" * 300) + "\n</TABLE>"
    table2 = "<TABLE>\nY\n</TABLE>"
    block4 = "C" * 50

    chunks = chunk_blocks([prose, table1, table2, block4])

    assert len(chunks) == 2
    assert chunks[1] == table2 + "\n\n" + block4
