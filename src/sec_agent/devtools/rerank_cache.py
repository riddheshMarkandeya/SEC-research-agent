"""
A persistent cache of cross-encoder scores for the replay tools
(analyze_gate_replay, retrieval_replay). Never used by production retrieval.

Each entry is one whole predict call, keyed by its exact ordered list of
(query, window) pairs. CrossEncoder.predict sorts pairs by length and
batches them, so a pair's float32 score can depend on which other pairs
share the call; keying on the whole call makes a hit return exactly what
that call would have computed. A change to retrieval that alters a pool or
its windowing produces different pairs, which miss, so the cache can't go
stale that way.

The file lives in var/rerank_cache/, named by a hash of everything else
that sets a score: the model name and Hugging Face revision, max sequence
length, activation, device and dtype, and the sentence-transformers and
torch versions. A change to any of them starts a fresh file. A local model
path whose weights change has no revision, so it is not detected: delete
var/rerank_cache/ or pass --no-rerank-cache. Deleting the directory is
always safe.

A cache failure never fails a replay: it prints one [rerank_cache] line to
stderr and the run carries on uncached.
"""

import hashlib
import json
import sqlite3
import sys
from collections.abc import Sequence
from pathlib import Path

import numpy as np

from sec_agent import config


class ScoreStore:
    """One SQLite file of call key -> JSON list of scores. float32 scores
    widen to float64 exactly, and JSON round-trips a float64 exactly."""

    def __init__(self, path: Path, conn: sqlite3.Connection):
        self.path = path
        self._conn = conn

    def get(self, key: bytes, count: int) -> list[float] | None:
        """The count scores stored under key, or None. ValueError for a
        corrupt row (bad JSON, or the wrong number of scores)."""
        row = self._conn.execute("SELECT scores FROM calls WHERE key = ?", (key,)).fetchone()
        if row is None:
            return None
        scores = json.loads(row[0])
        if len(scores) != count:
            raise ValueError(f"a cached row has {len(scores)} scores for {count} pairs")
        return scores

    def put(self, key: bytes, scores: list[float]) -> None:
        self._conn.execute("INSERT OR IGNORE INTO calls (key, scores) VALUES (?, ?)", (key, json.dumps(scores)))
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()


def cache_path(cache_dir: Path, identity_parts: list) -> Path:
    digest = hashlib.sha256(json.dumps([str(p) for p in identity_parts]).encode("utf-8")).hexdigest()
    return cache_dir / f"{digest[:16]}.sqlite"


def open_store(path: Path) -> ScoreStore | None:
    """The store at path, or None (with one stderr warning) when it can't be
    opened, so the replay runs uncached instead of failing."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE IF NOT EXISTS calls (key BLOB PRIMARY KEY, scores TEXT NOT NULL)")
        conn.commit()
    except (sqlite3.Error, OSError) as e:
        print(f"[rerank_cache] disabled: {e}", file=sys.stderr)
        return None
    return ScoreStore(path, conn)


def call_key(pairs: Sequence[tuple[str, str]]) -> bytes:
    return hashlib.sha256(json.dumps([list(p) for p in pairs]).encode("utf-8")).digest()


class CachedReranker:
    """Wraps a CrossEncoder, serving whole predict calls from a ScoreStore."""

    def __init__(self, model, store: ScoreStore | None, path: Path):
        self.model = model
        self.store = store
        self.path = str(path)
        self.hits = 0
        self.misses = 0
        # Without a store from the start, every call goes straight to the model.
        self.disabled: str | None = None if store is not None else "at open"

    def __getattr__(self, name):
        # Only reached for names not set in __init__, e.g. .tokenizer.
        return getattr(self.model, name)

    def predict(self, pairs, **kwargs):
        if kwargs or self.store is None:
            # Options such as batch_size can change the scores, and the key
            # doesn't cover them.
            return self.model.predict(pairs, **kwargs)
        key = call_key(pairs)
        try:
            scores = self.store.get(key, len(pairs))
        except (sqlite3.Error, ValueError) as e:
            self._disable(e)
            return self.model.predict(pairs)
        if scores is not None:
            self.hits += 1
            # float32 like the model's own result; float32 -> float64 -> float32 is exact.
            return np.asarray(scores, dtype=np.float32)
        result = self.model.predict(pairs)
        self.misses += 1
        try:
            self.store.put(key, result.tolist())
        except sqlite3.Error as e:
            self._disable(e)
        return result

    def _disable(self, error: Exception) -> None:
        # A replay must not see a cache failure as a difference or an abort,
        # so the rest of the run goes uncached instead.
        print(f"[rerank_cache] disabled mid-run: {error}", file=sys.stderr)
        self.disabled = f"mid-run: {error}"
        self.store = None


def stats(reranker: CachedReranker | None) -> dict | None:
    if reranker is None:
        return None
    return {"path": reranker.path, "hits": reranker.hits, "misses": reranker.misses, "disabled": reranker.disabled}


def summary_line(cache_stats: dict | None) -> str:
    if cache_stats is None:
        return "rerank cache: off"
    line = f"rerank cache: {cache_stats['hits']} hits, {cache_stats['misses']} misses ({cache_stats['path']})"
    return f"{line}, disabled {cache_stats['disabled']}" if cache_stats["disabled"] else line


def install(enabled: bool) -> CachedReranker | None:  # pragma: no cover -- loads the real cross-encoder, live-only
    """Puts a CachedReranker in place of retrieval's cross-encoder singleton
    for the rest of the process. None when disabled; when the store can't be
    opened, a CachedReranker that runs uncached and reports "at open"."""
    if not enabled:
        return None
    import sentence_transformers
    import torch

    from sec_agent.retrieval import retrieval

    if isinstance(retrieval._rerank_model, CachedReranker):
        return retrieval._rerank_model
    model = retrieval._get_rerank_model()
    hf_model = model.model
    assert hf_model is not None  # typed optional, but CrossEncoder's constructor always loads it
    identity = [
        config.RERANK_MODEL_NAME, getattr(hf_model.config, "_commit_hash", None), model.max_seq_length,
        repr(model.activation_fn), model.device, hf_model.dtype, sentence_transformers.__version__,
        torch.__version__,
    ]
    path = cache_path(config.VAR_DIR / "rerank_cache", identity)
    reranker = CachedReranker(model, open_store(path), path)
    retrieval._rerank_model = reranker
    if reranker.store is not None:
        print(f"[rerank_cache] using {reranker.path}", file=sys.stderr)
    return reranker
