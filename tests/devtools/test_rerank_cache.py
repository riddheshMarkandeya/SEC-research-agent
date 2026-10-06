import sqlite3

import numpy as np
import pytest

from sec_agent.devtools import rerank_cache as rc


class FakeModel:
    """Scores a pair by its total length, so expected values are literals."""

    tokenizer = "the-tokenizer"

    def __init__(self):
        self.calls = []

    def predict(self, pairs, **kwargs):
        self.calls.append((list(pairs), kwargs))
        return np.asarray([float(len(q) + len(w)) for q, w in pairs], dtype=np.float32)


@pytest.fixture
def store(tmp_path):
    s = rc.open_store(tmp_path / "scores.sqlite")
    assert s is not None
    yield s
    s.close()


PAIRS = [("revenue", "abc"), ("revenue", "a")]


def test_a_miss_is_predicted_and_stored_and_a_repeat_is_a_hit_without_a_model_call(store):
    model = FakeModel()
    cached = rc.CachedReranker(model, store, store.path)

    first = cached.predict(PAIRS)
    second = cached.predict(PAIRS)

    assert first.tolist() == [10.0, 8.0]
    assert second.tolist() == [10.0, 8.0]
    assert len(model.calls) == 1
    assert (cached.hits, cached.misses) == (1, 1)


def test_a_hit_has_the_models_float32_dtype(store):
    cached = rc.CachedReranker(FakeModel(), store, store.path)
    cached.predict(PAIRS)

    assert cached.predict(PAIRS).dtype == np.float32


@pytest.mark.parametrize("row", ["not json", "[10.0]"])
def test_a_corrupt_or_wrong_length_row_warns_and_serves_the_model_uncached(tmp_path, capsys, row):
    path = tmp_path / "scores.sqlite"
    s = rc.open_store(path)
    assert s is not None
    conn = sqlite3.connect(path)
    conn.execute("INSERT INTO calls (key, scores) VALUES (?, ?)", (rc.call_key(PAIRS), row))
    conn.commit()
    conn.close()
    model = FakeModel()
    cached = rc.CachedReranker(model, s, path)

    result = cached.predict(PAIRS)
    s.close()

    assert result.tolist() == [10.0, 8.0]
    assert len(model.calls) == 1
    assert capsys.readouterr().err.startswith("[rerank_cache] disabled mid-run: ")
    assert (cached.hits, cached.misses, cached.store) == (0, 0, None)


def test_without_a_store_every_call_goes_to_the_model_and_stats_say_disabled_at_open(tmp_path):
    model = FakeModel()
    cached = rc.CachedReranker(model, None, tmp_path / "x.sqlite")

    cached.predict(PAIRS)
    cached.predict(PAIRS)

    assert len(model.calls) == 2
    assert rc.stats(cached) == {"path": str(tmp_path / "x.sqlite"), "hits": 0, "misses": 0, "disabled": "at open"}


@pytest.mark.parametrize("other", [list(reversed(PAIRS)), [("revenue", "abc")], [("revenue", "abd"), ("revenue", "a")]])
def test_a_different_pair_order_or_content_misses(store, other):
    model = FakeModel()
    cached = rc.CachedReranker(model, store, store.path)
    cached.predict(PAIRS)

    cached.predict(other)

    assert len(model.calls) == 2
    assert (cached.hits, cached.misses) == (0, 2)


def test_predict_kwargs_bypass_the_cache(store):
    model = FakeModel()
    cached = rc.CachedReranker(model, store, store.path)
    cached.predict(PAIRS)

    result = cached.predict(PAIRS, batch_size=4)

    assert result.tolist() == [10.0, 8.0]
    assert model.calls[-1] == (PAIRS, {"batch_size": 4})
    assert (cached.hits, cached.misses) == (0, 1)


def test_a_second_store_on_the_same_file_sees_the_first_ones_scores(tmp_path):
    path = tmp_path / "scores.sqlite"
    first = rc.open_store(path)
    assert first is not None
    rc.CachedReranker(FakeModel(), first, first.path).predict(PAIRS)
    first.close()

    second = rc.open_store(path)
    assert second is not None
    model = FakeModel()
    result = rc.CachedReranker(model, second, second.path).predict(PAIRS)
    second.close()

    assert result.tolist() == [10.0, 8.0]
    assert model.calls == []


def test_retrieval_still_has_the_model_singleton_install_replaces():
    # install swaps this private global; a rename would silently turn the cache off.
    from sec_agent.retrieval import retrieval

    assert hasattr(retrieval, "_rerank_model")
    assert callable(retrieval._get_rerank_model)


def test_other_attributes_forward_to_the_model(store):
    assert rc.CachedReranker(FakeModel(), store, store.path).tokenizer == "the-tokenizer"


IDENTITY = ["cross-encoder/x", 512, "5.0.0", "2.9.0"]


def test_cache_path_is_a_sqlite_file_in_the_dir_named_by_the_identity(tmp_path):
    path = rc.cache_path(tmp_path, IDENTITY)

    assert path.parent == tmp_path
    assert path.suffix == ".sqlite"
    assert path == rc.cache_path(tmp_path, list(IDENTITY))


@pytest.mark.parametrize("i", range(len(IDENTITY)))
def test_cache_path_changes_with_each_identity_part(tmp_path, i):
    changed = list(IDENTITY)
    changed[i] = f"{changed[i]}-changed"

    assert rc.cache_path(tmp_path, changed) != rc.cache_path(tmp_path, IDENTITY)


def test_open_store_creates_missing_directories(tmp_path):
    s = rc.open_store(tmp_path / "a" / "b" / "scores.sqlite")

    assert s is not None
    s.close()


def test_open_store_on_an_unopenable_path_warns_and_returns_none(tmp_path, capsys):
    blocker = tmp_path / "a-file"
    blocker.write_text("not a directory")

    assert rc.open_store(blocker / "scores.sqlite") is None
    assert capsys.readouterr().err.startswith("[rerank_cache] disabled: ")


class BrokenStore(rc.ScoreStore):
    def __init__(self, path, fail_on):
        self.path = path
        self.fail_on = fail_on
        self.used = 0

    def get(self, key, count):
        self.used += 1
        if self.fail_on == "get":
            raise sqlite3.OperationalError("database is locked")
        return None

    def put(self, key, scores):
        self.used += 1
        raise sqlite3.OperationalError("disk I/O error")


@pytest.mark.parametrize("fail_on", ["get", "put"])
def test_a_store_error_mid_run_warns_once_and_serves_every_later_call_uncached(tmp_path, capsys, fail_on):
    model = FakeModel()
    broken = BrokenStore(tmp_path / "x.sqlite", fail_on)
    cached = rc.CachedReranker(model, broken, broken.path)

    first = cached.predict(PAIRS)
    used = broken.used
    second = cached.predict(PAIRS)

    assert first.tolist() == second.tolist() == [10.0, 8.0]
    assert len(model.calls) == 2
    assert broken.used == used
    err = capsys.readouterr().err
    assert err.count("[rerank_cache] disabled mid-run: ") == 1
    stats = rc.stats(cached)
    assert stats is not None
    assert stats["disabled"]
    assert stats["path"] == str(tmp_path / "x.sqlite")


def test_stats_reports_path_and_counts_and_none_without_a_reranker(store):
    cached = rc.CachedReranker(FakeModel(), store, store.path)
    cached.predict(PAIRS)
    cached.predict(PAIRS)

    assert rc.stats(cached) == {"path": str(store.path), "hits": 1, "misses": 1, "disabled": None}
    assert rc.stats(None) is None


@pytest.mark.parametrize("stats, line", [
    (None, "rerank cache: off"),
    ({"path": "p", "hits": 3, "misses": 1, "disabled": None}, "rerank cache: 3 hits, 1 misses (p)"),
    ({"path": "p", "hits": 3, "misses": 1, "disabled": "mid-run: locked"},
     "rerank cache: 3 hits, 1 misses (p), disabled mid-run: locked"),
])
def test_summary_line(stats, line):
    assert rc.summary_line(stats) == line
