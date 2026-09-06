"""
Unit tests for tracing.py's pure/deterministic gating and local-logging
logic. traced_span() always yields a usable object and always writes a
local JSONL log line (independent of whether Langfuse is configured);
the Langfuse half is additionally exercised via a fake client. The
actual Langfuse SDK network calls are live-only, verified separately
via tests/manual/verify_tracing.py, not mocked here (same carve-out as
every other live-only integration in this project).
"""

import json
from contextlib import contextmanager
from pathlib import Path

import tracing


class _FakeObservation:
    def __init__(self):
        self.update_calls = []

    def update(self, **kwargs):
        self.update_calls.append(kwargs)


class _FakeClient:
    def __init__(self):
        self.start_calls = []
        self.flush_calls = 0
        self._observation = _FakeObservation()

    @contextmanager
    def start_as_current_observation(self, *, as_type, name, input=None):
        self.start_calls.append({"as_type": as_type, "name": name, "input": input})
        yield self._observation

    def flush(self):
        self.flush_calls += 1


def _read_log_lines(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# traced_span -- Langfuse half
# ---------------------------------------------------------------------------
def test_traced_span_yields_usable_span_and_touches_no_client_when_langfuse_disabled(monkeypatch, tmp_path):
    monkeypatch.setattr(tracing, "TRACING_ENABLED", False)
    monkeypatch.setattr(tracing, "TRACE_LOG_PATH", str(tmp_path / "traces.jsonl"))
    monkeypatch.setattr(
        tracing, "_get_langfuse_client", lambda: (_ for _ in ()).throw(AssertionError("should not be called"))
    )

    with tracing.traced_span("tool", "search_filings", input={"query": "revenue"}) as span:
        assert span is not None
        span.update(output={"count": 1})  # must not raise even with no Langfuse client


def test_traced_span_forwards_update_to_langfuse_client_when_enabled(monkeypatch, tmp_path):
    fake_client = _FakeClient()
    monkeypatch.setattr(tracing, "TRACING_ENABLED", True)
    monkeypatch.setattr(tracing, "TRACE_LOG_PATH", str(tmp_path / "traces.jsonl"))
    monkeypatch.setattr(tracing, "_get_langfuse_client", lambda: fake_client)

    with tracing.traced_span("tool", "search_filings", input={"query": "revenue"}) as span:
        span.update(output={"count": 1})

    assert fake_client.start_calls == [{"as_type": "tool", "name": "search_filings", "input": {"query": "revenue"}}]
    assert fake_client._observation.update_calls == [{"output": {"count": 1}}]


# ---------------------------------------------------------------------------
# traced_span -- local JSONL log (independent of Langfuse)
# ---------------------------------------------------------------------------
def test_traced_span_writes_local_log_line_even_when_langfuse_disabled(monkeypatch, tmp_path):
    log_path = tmp_path / "traces.jsonl"
    monkeypatch.setattr(tracing, "TRACING_ENABLED", False)
    monkeypatch.setattr(tracing, "TRACE_LOG_PATH", str(log_path))

    with tracing.traced_span("tool", "search_filings", input={"query": "revenue"}) as span:
        span.update(output={"count": 1})

    lines = _read_log_lines(log_path)
    assert len(lines) == 1
    assert lines[0]["as_type"] == "tool"
    assert lines[0]["name"] == "search_filings"
    assert lines[0]["input"] == {"query": "revenue"}
    assert lines[0]["output"] == {"count": 1}
    assert lines[0]["is_root"] is True
    assert lines[0]["run_id"]
    assert "duration_ms" in lines[0]


def test_traced_span_duration_uses_monotonic_clock_not_wall_clock(monkeypatch, tmp_path):
    # Found in code review: time.time() (wall clock) can jump backward
    # under a clock adjustment (e.g. an NTP correction on a long-running
    # mcp_server.py process), corrupting duration_ms. Simulates that by
    # freezing time.time() while time.monotonic() keeps advancing
    # normally -- duration_ms must reflect the monotonic delta.
    log_path = tmp_path / "traces.jsonl"
    monkeypatch.setattr(tracing, "TRACING_ENABLED", False)
    monkeypatch.setattr(tracing, "TRACE_LOG_PATH", str(log_path))
    monkeypatch.setattr(tracing.time, "time", lambda: 1000.0)
    real_monotonic = tracing.time.monotonic()
    monotonic_values = iter([real_monotonic, real_monotonic + 5.0])
    monkeypatch.setattr(tracing.time, "monotonic", lambda: next(monotonic_values))

    with tracing.traced_span("tool", "a", input={}):
        pass

    lines = _read_log_lines(log_path)
    assert lines[0]["duration_ms"] == 5000.0


def test_traced_span_does_not_write_local_log_when_trace_log_path_empty(monkeypatch):
    # Found in code review: the original version of this test asserted
    # on an unrelated tmp_path never referenced by TRACE_LOG_PATH ("" in
    # this test), so it passed trivially regardless of whether the
    # early-return guard existed at all. Spying on Path.open() proves
    # the guard actually prevents any file I/O attempt -- tracked via a
    # plain list rather than raising inside the mock, since
    # _write_local_log's own broad `except Exception` would otherwise
    # silently swallow a raised assertion too, making the test pass
    # either way (confirmed live: an earlier version of this fix using
    # `.throw(AssertionError(...))` still passed even with the guard
    # deleted entirely).
    monkeypatch.setattr(tracing, "TRACING_ENABLED", False)
    monkeypatch.setattr(tracing, "TRACE_LOG_PATH", "")
    open_calls = []
    monkeypatch.setattr(Path, "open", lambda self, *a, **k: open_calls.append(self))

    with tracing.traced_span("tool", "search_filings", input={}):
        pass

    assert open_calls == []


def test_write_local_log_only_creates_parent_directory_once(monkeypatch, tmp_path):
    # Found in code review: mkdir(exist_ok=True) is cheap but still a
    # syscall on every single span write -- this locks in that a
    # second write to the same already-ensured directory doesn't
    # re-attempt creating it.
    log_path = tmp_path / "sub" / "traces.jsonl"
    monkeypatch.setattr(tracing, "TRACING_ENABLED", False)
    monkeypatch.setattr(tracing, "TRACE_LOG_PATH", str(log_path))
    monkeypatch.setattr(tracing, "_ensured_log_dir", None)

    mkdir_calls = []
    original_mkdir = Path.mkdir

    def counting_mkdir(self, *args, **kwargs):
        mkdir_calls.append(self)
        return original_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", counting_mkdir)

    with tracing.traced_span("tool", "a", input={}):
        pass
    with tracing.traced_span("tool", "b", input={}):
        pass

    assert len(mkdir_calls) == 1


def test_traced_span_creates_missing_parent_directory(monkeypatch, tmp_path):
    log_path = tmp_path / "nested" / "dir" / "traces.jsonl"
    monkeypatch.setattr(tracing, "TRACING_ENABLED", False)
    monkeypatch.setattr(tracing, "TRACE_LOG_PATH", str(log_path))

    with tracing.traced_span("tool", "search_filings", input={}):
        pass

    assert log_path.exists()


def test_traced_span_local_log_write_failure_does_not_raise(monkeypatch, tmp_path, capsys):
    # A file occupying the path where a directory needs to be created
    # simulates a write failure -- logging must never break the actual
    # call it's wrapping.
    blocking_file = tmp_path / "not_a_directory"
    blocking_file.write_text("x")
    monkeypatch.setattr(tracing, "TRACING_ENABLED", False)
    monkeypatch.setattr(tracing, "TRACE_LOG_PATH", str(blocking_file / "traces.jsonl"))

    with tracing.traced_span("tool", "search_filings", input={}) as span:
        span.update(output={"ok": True})  # must not raise

    assert "tracing" in capsys.readouterr().err.lower()


def test_write_local_log_swallows_non_oserror_failures_too(monkeypatch, tmp_path, capsys):
    # Found in code review: only OSError was caught, but the module's
    # own documented contract is "never raise, ever, logging must never
    # break the real call it wraps" -- a value that fails to serialize
    # (here, default=str's own fallback raising) must not escape either.
    class _Unstringable:
        def __str__(self):
            raise ValueError("boom")

    log_path = tmp_path / "traces.jsonl"
    monkeypatch.setattr(tracing, "TRACING_ENABLED", False)
    monkeypatch.setattr(tracing, "TRACE_LOG_PATH", str(log_path))
    monkeypatch.setattr(tracing, "_ensured_log_dir", None)

    with tracing.traced_span("tool", "a", input={"bad": _Unstringable()}):
        pass  # must not raise

    assert "tracing" in capsys.readouterr().err.lower()


def test_write_local_log_recovers_after_directory_deleted_mid_run(monkeypatch, tmp_path):
    # Found in code review: _ensured_log_dir was never invalidated on a
    # write failure. trace_logs/ is documented as disposable/
    # regenerable output someone might clean up externally while a
    # long-running process (mcp_server.py) is still writing to it --
    # without invalidating the cache, mkdir() would never be retried
    # and every subsequent trace line would be silently lost until the
    # process restarts, defeating the whole "always-on backup" point.
    import shutil

    log_dir = tmp_path / "sub"
    log_path = log_dir / "traces.jsonl"
    monkeypatch.setattr(tracing, "TRACING_ENABLED", False)
    monkeypatch.setattr(tracing, "TRACE_LOG_PATH", str(log_path))
    monkeypatch.setattr(tracing, "_ensured_log_dir", None)

    with tracing.traced_span("tool", "a", input={}):
        pass
    assert log_path.exists()

    shutil.rmtree(log_dir)

    with tracing.traced_span("tool", "b", input={}):
        pass  # write fails silently (directory gone) -- must not raise
    with tracing.traced_span("tool", "c", input={}):
        pass  # must recover: recreate the directory and resume writing

    assert log_path.exists()
    names = [json.loads(line)["name"] for line in log_path.read_text().splitlines() if line.strip()]
    assert names == ["c"], names  # "a" was lost with the directory; "b" failed; "c" recovered


def test_nested_traced_span_calls_share_one_run_id_and_only_outer_is_root(monkeypatch, tmp_path):
    log_path = tmp_path / "traces.jsonl"
    monkeypatch.setattr(tracing, "TRACING_ENABLED", False)
    monkeypatch.setattr(tracing, "TRACE_LOG_PATH", str(log_path))

    with tracing.traced_span("agent", "run_agent", input={"question": "q"}):
        with tracing.traced_span("tool", "search_filings", input={}):
            pass

    lines = _read_log_lines(log_path)
    assert len(lines) == 2
    tool_line, agent_line = lines[0], lines[1]  # inner span's finally fires first
    assert tool_line["name"] == "search_filings" and tool_line["is_root"] is False
    assert agent_line["name"] == "run_agent" and agent_line["is_root"] is True
    assert tool_line["run_id"] == agent_line["run_id"]


def test_two_independent_top_level_traced_spans_get_different_run_ids(monkeypatch, tmp_path):
    log_path = tmp_path / "traces.jsonl"
    monkeypatch.setattr(tracing, "TRACING_ENABLED", False)
    monkeypatch.setattr(tracing, "TRACE_LOG_PATH", str(log_path))

    with tracing.traced_span("agent", "run_agent", input={}):
        pass
    with tracing.traced_span("agent", "run_agent", input={}):
        pass

    lines = _read_log_lines(log_path)
    assert lines[0]["run_id"] != lines[1]["run_id"]
    assert lines[0]["is_root"] is True and lines[1]["is_root"] is True


# ---------------------------------------------------------------------------
# record_unmet_metric_request
# ---------------------------------------------------------------------------
def test_record_unmet_metric_request_writes_local_log_even_when_langfuse_disabled(monkeypatch, tmp_path):
    log_path = tmp_path / "traces.jsonl"
    monkeypatch.setattr(tracing, "TRACING_ENABLED", False)
    monkeypatch.setattr(tracing, "TRACE_LOG_PATH", str(log_path))

    tracing.record_unmet_metric_request("AAPL", "effective_tax_rate", reason="unknown_metric", question="q?")

    lines = _read_log_lines(log_path)
    assert len(lines) == 1
    assert lines[0]["name"] == "unmet_metric_request"
    assert lines[0]["input"] == {
        "ticker": "AAPL",
        "metric": "effective_tax_rate",
        "reason": "unknown_metric",
        "question": "q?",
    }


def test_record_unmet_metric_request_noop_when_both_langfuse_and_local_log_disabled(monkeypatch):
    # See test_traced_span_does_not_write_local_log_when_trace_log_path_empty
    # above for why this tracks calls via a list rather than raising
    # inside the mock or asserting on an unrelated tmp_path.
    monkeypatch.setattr(tracing, "TRACING_ENABLED", False)
    monkeypatch.setattr(tracing, "TRACE_LOG_PATH", "")
    open_calls = []
    monkeypatch.setattr(Path, "open", lambda self, *a, **k: open_calls.append(self))

    tracing.record_unmet_metric_request("AAPL", "effective_tax_rate", reason="unknown_metric")

    assert open_calls == []


def test_record_unmet_metric_request_records_unknown_metric_when_langfuse_enabled(monkeypatch, tmp_path):
    fake_client = _FakeClient()
    monkeypatch.setattr(tracing, "TRACING_ENABLED", True)
    monkeypatch.setattr(tracing, "TRACE_LOG_PATH", str(tmp_path / "traces.jsonl"))
    monkeypatch.setattr(tracing, "_get_langfuse_client", lambda: fake_client)

    tracing.record_unmet_metric_request("AAPL", "effective_tax_rate", reason="unknown_metric", question="q?")

    assert len(fake_client.start_calls) == 1
    call = fake_client.start_calls[0]
    assert call["name"] == "unmet_metric_request"
    assert call["input"] == {
        "ticker": "AAPL",
        "metric": "effective_tax_rate",
        "reason": "unknown_metric",
        "question": "q?",
    }


def test_record_unmet_metric_request_records_no_data_for_ticker_with_no_question_when_langfuse_enabled(
    monkeypatch, tmp_path
):
    # Found in code review: rewriting this test file for local-log
    # coverage accidentally dropped the only test exercising the
    # reason="no_data_for_ticker" branch and the question=None default
    # together on the Langfuse-enabled path -- both are real, used
    # call sites in agent.py (e.g. the plain-metric/yoy_growth/
    # multi-year-average no-data branches).
    fake_client = _FakeClient()
    monkeypatch.setattr(tracing, "TRACING_ENABLED", True)
    monkeypatch.setattr(tracing, "TRACE_LOG_PATH", str(tmp_path / "traces.jsonl"))
    monkeypatch.setattr(tracing, "_get_langfuse_client", lambda: fake_client)

    tracing.record_unmet_metric_request("PLTR", "inventory_turnover", reason="no_data_for_ticker")

    call = fake_client.start_calls[0]
    assert call["input"] == {
        "ticker": "PLTR",
        "metric": "inventory_turnover",
        "reason": "no_data_for_ticker",
        "question": None,
    }


# ---------------------------------------------------------------------------
# log_event -- local-only debug events, no Langfuse counterpart at all
# ---------------------------------------------------------------------------
def test_log_event_writes_category_and_fields_with_no_run_id_when_standalone(monkeypatch, tmp_path):
    log_path = tmp_path / "traces.jsonl"
    monkeypatch.setattr(tracing, "TRACE_LOG_PATH", str(log_path))

    tracing.log_event("llm_retry", backend="ollama", attempt=1)

    lines = _read_log_lines(log_path)
    assert len(lines) == 1
    assert lines[0]["category"] == "llm_retry"
    assert lines[0]["backend"] == "ollama"
    assert lines[0]["attempt"] == 1
    assert lines[0]["run_id"] is None


def test_log_event_tags_run_id_when_called_inside_an_open_traced_span(monkeypatch, tmp_path):
    log_path = tmp_path / "traces.jsonl"
    monkeypatch.setattr(tracing, "TRACING_ENABLED", False)
    monkeypatch.setattr(tracing, "TRACE_LOG_PATH", str(log_path))

    with tracing.traced_span("agent", "run_agent", input={}):
        tracing.log_event("citation_retry", backend="gemini", warnings=["..."])

    lines = _read_log_lines(log_path)
    event_line = next(line for line in lines if line["category"] == "citation_retry")
    span_line = next(line for line in lines if line.get("name") == "run_agent")
    assert event_line["run_id"] == span_line["run_id"]
    assert event_line["warnings"] == ["..."]


def test_log_event_never_touches_langfuse_client(monkeypatch, tmp_path):
    monkeypatch.setattr(tracing, "TRACING_ENABLED", True)
    monkeypatch.setattr(tracing, "TRACE_LOG_PATH", str(tmp_path / "traces.jsonl"))
    monkeypatch.setattr(
        tracing, "_get_langfuse_client", lambda: (_ for _ in ()).throw(AssertionError("should not be called"))
    )

    tracing.log_event("rate_limited", client_ip="127.0.0.1")


# ---------------------------------------------------------------------------
# flush
# ---------------------------------------------------------------------------
def test_flush_noop_when_disabled(monkeypatch):
    monkeypatch.setattr(tracing, "TRACING_ENABLED", False)
    monkeypatch.setattr(
        tracing, "_get_langfuse_client", lambda: (_ for _ in ()).throw(AssertionError("should not be called"))
    )

    tracing.flush()


def test_flush_calls_client_flush_when_enabled(monkeypatch):
    fake_client = _FakeClient()
    monkeypatch.setattr(tracing, "TRACING_ENABLED", True)
    monkeypatch.setattr(tracing, "_get_langfuse_client", lambda: fake_client)

    tracing.flush()

    assert fake_client.flush_calls == 1
