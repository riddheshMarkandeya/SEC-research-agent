"""Unit tests for rerank_windows: splitting a chunk into cross-encoder-sized
windows, and scoring a chunk by its best window. Token counts come from a
fake counter (one token per word), so window sizes are worked by hand."""

from sec_agent.retrieval.rerank_windows import max_per_owner, split_windows


def words(text: str) -> int:
    return len(text.split())


def test_short_text_is_one_window():
    assert split_windows("one two\nthree", words, window=10) == ["one two\nthree"]


def test_splits_on_line_boundaries_counting_one_extra_token_per_line():
    # Each line costs 3 + 1 = 4 tokens; a 9-token window holds two lines.
    text = "a b c\nd e f\ng h i\nj k l"
    assert split_windows(text, words, window=9) == ["a b c\nd e f", "g h i\nj k l"]


def test_a_single_overlong_line_is_its_own_window():
    text = "short\n" + " ".join(["w"] * 20) + "\nshort"
    assert split_windows(text, words, window=5) == ["short", " ".join(["w"] * 20), "short"]


def test_a_window_starting_inside_a_table_carries_the_caption_and_header():
    text = "\n".join(
        ["Revenue by segment", "<TABLE>", "| Segment | 2026 |", "| --- | --- |", "| Unit | $ |",
         "| Cloud | $ 10 |", "| Devices | $ 20 |", "</TABLE>"]
    )
    header = "Revenue by segment\n<TABLE>\n| Segment | 2026 |\n| --- | --- |\n| Unit | $ |"
    # Costs: caption 4, "<TABLE>" 2, the three header rows 6 each (24 in
    # all), data rows 7, "</TABLE>" 2. A 36-token window fills at "| Cloud |"
    # (31); "| Devices |" starts the next one, which re-carries the 24-token
    # header and still fits "</TABLE>".
    windows = split_windows(text, words, window=36)
    assert windows == [header + "\n| Cloud | $ 10 |", header + "\n| Devices | $ 20 |\n</TABLE>"]


def test_no_header_is_carried_outside_a_table():
    text = "\n".join(["Caption", "<TABLE>", "| a |", "</TABLE>", "prose one two", "prose three four"])
    windows = split_windows(text, words, window=8)
    assert all(not w.startswith("Caption") for w in windows[1:])
    assert windows[-1] == "prose three four"


def test_the_caption_is_the_last_non_blank_line_before_the_table():
    text = "\n".join(["Revenue by segment", "", "<TABLE>", "| a | b |", "| c | d |", "| e | f |", "| g | h |", "</TABLE>"])
    windows = split_windows(text, words, window=14)
    # A window that starts on one of the carried header rows gets no prefix
    # (the row would otherwise appear twice).
    assert windows[1] == "| c | d |\n| e | f |"
    assert windows[2] == "Revenue by segment\n<TABLE>\n| a | b |\n| c | d |\n| e | f |\n| g | h |"


def test_max_per_owner_takes_each_chunks_best_window():
    assert max_per_owner([0, 0, 1, 2, 2, 2], [0.1, 0.7, -3.0, 0.2, 0.9, 0.4], 3) == [0.7, -3.0, 0.9]
