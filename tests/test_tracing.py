"""
Unit tests for tracing.py's pure/deterministic gating logic --
traced_span()/record_unmet_metric_request()/flush() are all no-ops when
tracing isn't configured, and dispatch to a (mocked) Langfuse client
when it is. The actual Langfuse SDK network calls are live-only,
verified separately via tests/manual/verify_tracing.py, not mocked
here (same carve-out as every other live-only integration in this
project).
"""

from contextlib import contextmanager

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


# ---------------------------------------------------------------------------
# traced_span
# ---------------------------------------------------------------------------
def test_traced_span_yields_none_and_touches_no_client_when_disabled(monkeypatch):
    monkeypatch.setattr(tracing, "TRACING_ENABLED", False)
    monkeypatch.setattr(tracing, "_get_langfuse_client", lambda: (_ for _ in ()).throw(AssertionError("should not be called")))

    with tracing.traced_span("tool", "search_filings", input={"query": "revenue"}) as span:
        assert span is None


def test_traced_span_yields_observation_and_calls_client_when_enabled(monkeypatch):
    fake_client = _FakeClient()
    monkeypatch.setattr(tracing, "TRACING_ENABLED", True)
    monkeypatch.setattr(tracing, "_get_langfuse_client", lambda: fake_client)

    with tracing.traced_span("tool", "search_filings", input={"query": "revenue"}) as span:
        assert span is fake_client._observation
        span.update(output={"count": 1})

    assert fake_client.start_calls == [{"as_type": "tool", "name": "search_filings", "input": {"query": "revenue"}}]
    assert fake_client._observation.update_calls == [{"output": {"count": 1}}]


# ---------------------------------------------------------------------------
# record_unmet_metric_request
# ---------------------------------------------------------------------------
def test_record_unmet_metric_request_noop_when_disabled(monkeypatch):
    monkeypatch.setattr(tracing, "TRACING_ENABLED", False)
    monkeypatch.setattr(tracing, "_get_langfuse_client", lambda: (_ for _ in ()).throw(AssertionError("should not be called")))

    tracing.record_unmet_metric_request("AAPL", "effective_tax_rate", reason="unknown_metric", question="what is AAPL's tax rate?")


def test_record_unmet_metric_request_records_unknown_metric_when_enabled(monkeypatch):
    fake_client = _FakeClient()
    monkeypatch.setattr(tracing, "TRACING_ENABLED", True)
    monkeypatch.setattr(tracing, "_get_langfuse_client", lambda: fake_client)

    tracing.record_unmet_metric_request("AAPL", "effective_tax_rate", reason="unknown_metric", question="what is AAPL's tax rate?")

    assert len(fake_client.start_calls) == 1
    call = fake_client.start_calls[0]
    assert call["name"] == "unmet_metric_request"
    assert call["input"] == {
        "ticker": "AAPL",
        "metric": "effective_tax_rate",
        "reason": "unknown_metric",
        "question": "what is AAPL's tax rate?",
    }


def test_record_unmet_metric_request_records_no_data_for_ticker_with_no_question(monkeypatch):
    fake_client = _FakeClient()
    monkeypatch.setattr(tracing, "TRACING_ENABLED", True)
    monkeypatch.setattr(tracing, "_get_langfuse_client", lambda: fake_client)

    tracing.record_unmet_metric_request("PLTR", "inventory_turnover", reason="no_data_for_ticker")

    call = fake_client.start_calls[0]
    assert call["input"] == {"ticker": "PLTR", "metric": "inventory_turnover", "reason": "no_data_for_ticker", "question": None}


# ---------------------------------------------------------------------------
# flush
# ---------------------------------------------------------------------------
def test_flush_noop_when_disabled(monkeypatch):
    monkeypatch.setattr(tracing, "TRACING_ENABLED", False)
    monkeypatch.setattr(tracing, "_get_langfuse_client", lambda: (_ for _ in ()).throw(AssertionError("should not be called")))

    tracing.flush()


def test_flush_calls_client_flush_when_enabled(monkeypatch):
    fake_client = _FakeClient()
    monkeypatch.setattr(tracing, "TRACING_ENABLED", True)
    monkeypatch.setattr(tracing, "_get_langfuse_client", lambda: fake_client)

    tracing.flush()

    assert fake_client.flush_calls == 1
