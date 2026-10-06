"""
Live verification of rerank_cache.py against the real cross-encoder: the
cached scores must be bit-identical to what the model computes, which a
fake model in the unit tests can't show.

It records the real (query, window) pairs of a few searches' predict
calls, then, with a fresh SQLite file in a temp directory:
  1. a cold CachedReranker call vs a plain predict on the same pairs
     (max abs diff, expected 0.0);
  2. a warm call vs the cold one (max abs diff 0.0, no model call);
  3. diagnostic only: each call's pairs scored as two separate calls vs
     one. A nonzero diff means a pair's score depends on its batch-mates,
     so a pair-level key would not have been bit-exact.

Exits 1 when check 1 or 2 fails.

Usage (from the repo root):
    python tests/manual/verify_rerank_cache.py
"""

import sys
import tempfile
from pathlib import Path

import numpy as np

from sec_agent.devtools import rerank_cache
from sec_agent.retrieval import retrieval

QUERIES = [
    ("NVIDIA revenue for the first quarter of fiscal 2026", "NVDA"),
    ("Microsoft segment revenue three months ended March 31, 2026", "MSFT"),
    ("Apple risk factors related to artificial intelligence", "AAPL"),
]


class _Spy:
    """Forwards to the real model and keeps each predict call's pairs."""

    def __init__(self, model):
        self.model = model
        self.calls: list[list[tuple[str, str]]] = []

    def predict(self, pairs, **kwargs):
        self.calls.append(list(pairs))
        return self.model.predict(pairs, **kwargs)

    def __getattr__(self, name):
        return getattr(self.model, name)


def _record_calls(model) -> list[list[tuple[str, str]]]:
    recorder = _Spy(model)
    retrieval._rerank_model = recorder
    try:
        for query, ticker in QUERIES:
            retrieval.search_details(query, ticker=ticker)
    finally:
        retrieval._rerank_model = model
    return recorder.calls


def _max_diff(a, b) -> float:
    return float(np.max(np.abs(np.asarray(a, dtype=np.float64) - np.asarray(b, dtype=np.float64))))


def _check_call(i: int, pairs: list, model, cached, counting) -> list[str]:
    plain = model.predict(pairs)
    cold = cached.predict(pairs)
    before = len(counting.calls)
    warm = cached.predict(pairs)
    warm_model_calls = len(counting.calls) - before
    half = len(pairs) // 2
    split = np.concatenate([model.predict(pairs[:half]), model.predict(pairs[half:])]) if half else plain
    cold_diff, warm_diff, split_diff = _max_diff(plain, cold), _max_diff(cold, warm), _max_diff(plain, split)
    print(
        f"call {i}: {len(pairs)} pairs; cold vs plain {cold_diff}; warm vs cold {warm_diff} "
        f"({warm_model_calls} model calls); split vs one call {split_diff}"
    )
    problems = []
    if cold_diff != 0.0:
        problems.append(f"call {i}: cold cached scores differ from plain predict by {cold_diff}")
    if warm_diff != 0.0 or warm_model_calls:
        problems.append(f"call {i}: warm diff {warm_diff}, {warm_model_calls} model calls")
    return problems


def main() -> int:
    model = retrieval._get_rerank_model()
    calls = _record_calls(model)
    print(f"recorded {len(calls)} predict calls")
    with tempfile.TemporaryDirectory() as tmp:
        store = rerank_cache.open_store(Path(tmp) / "verify.sqlite")
        if store is None:
            print("FAIL: could not open a temp store")
            return 1
        counting = _Spy(model)
        cached = rerank_cache.CachedReranker(counting, store, store.path)
        problems = []
        for i, pairs in enumerate(calls, start=1):
            problems += _check_call(i, pairs, model, cached, counting)
        print(f"stats: {rerank_cache.stats(cached)}")
        store.close()
    for problem in problems:
        print(f"FAIL: {problem}")
    print("OK" if not problems else f"{len(problems)} failure(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
