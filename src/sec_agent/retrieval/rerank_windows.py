"""
Windowed (MaxP) cross-encoder scoring. The reranker reads 512 tokens,
query included, and many financial-table chunks are longer, so the row a
question needs is often cut off. Each chunk is split into windows on line
boundaries and scored by its best window. A window that starts inside a
table repeats the table's caption and first rows, because without them a
bare row of numbers can't be matched to the question (measured: dropping
the carried header loses most of the windowing's gain).
"""

from collections.abc import Callable

# Leaves room for the query inside the reranker's 512-token limit.
# Deliberately not tuned: the evaluation set is small enough to overfit.
RERANK_WINDOW_TOKENS = 380

# Table rows carried into a window that starts inside the table, after the
# caption line and the "<TABLE>" marker.
_HEADER_ROWS = 3


def split_windows(text: str, count_tokens: Callable[[str], int], window: int = RERANK_WINDOW_TOKENS) -> list[str]:
    """Split `text` into windows of at most `window` tokens (a line costs its
    tokens plus one for the newline), breaking only between lines. A single
    line longer than `window` becomes its own window; the reranker
    truncates it. A window starting inside a table opens with the table's
    header: the last non-blank line before "<TABLE>" (its caption), the
    marker and the next three lines, unless the window's first line is one
    of those."""
    lines = text.split("\n")
    header: list[str] = []
    in_table = False
    caption = ""
    windows: list[str] = []
    current: list[str] = []
    current_len = 0
    for i, line in enumerate(lines):
        if line.strip() == "<TABLE>":
            in_table = True
            header = ([caption] if caption.strip() else []) + [line] + lines[i + 1 : i + 1 + _HEADER_ROWS]
        elif line.strip() == "</TABLE>":
            in_table = False
        cost = count_tokens(line) + 1
        if current and current_len + cost > window:
            windows.append("\n".join(current))
            prefix = header if in_table and line not in header else []
            current = list(prefix)
            current_len = sum(count_tokens(h) + 1 for h in prefix)
        current.append(line)
        current_len += cost
        if line.strip():
            caption = line
    if current:
        windows.append("\n".join(current))
    return windows


def max_per_owner(owner: list[int], scores: list[float], n: int) -> list[float]:
    """Each of n chunks' best window score, where owner[i] is the chunk
    window i came from. Every chunk has at least one window."""
    best = [float("-inf")] * n
    for chunk, score in zip(owner, scores, strict=True):
        best[chunk] = max(best[chunk], score)
    return best
