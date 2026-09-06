"""
Shared pytest fixtures, autouse so every test file gets them without
opting in individually.
"""

import pytest

import tracing


@pytest.fixture(autouse=True)
def _disable_local_trace_log_by_default(monkeypatch):
    """tracing.traced_span() always writes a local JSONL log line
    (tracing.py, 2026-09-05) regardless of whether Langfuse is
    configured -- without this fixture, any test that exercises it
    (most of test_agent.py's/test_mcp_server.py's tests do, indirectly,
    via run_agent()/_dispatch_tool_call()/the mcp_server tool handlers)
    would write real lines to the real TRACE_LOG_PATH on disk. Found
    live: running the suite once left 18 real lines in
    ./trace_logs/traces.jsonl. tests/test_tracing.py's own tests
    already point TRACE_LOG_PATH at a pytest tmp_path themselves, which
    simply overrides this default within those tests."""
    monkeypatch.setattr(tracing, "TRACE_LOG_PATH", "")
