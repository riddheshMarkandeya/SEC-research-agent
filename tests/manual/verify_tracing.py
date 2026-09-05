"""
One-time (re-runnable) live verification for tracing.py (Week 7
guardrails, Langfuse tracing).

Why this exists: tracing.py's own gating logic (TRACING_ENABLED,
traced_span's no-op branch, record_unmet_metric_request's payload) is
pure/deterministic and fully unit-tested (tests/test_tracing.py) -- but
the actual Langfuse SDK network calls are live-only, per this project's
TDD carve-out. This script runs a real run_agent() question and a real
unmet-metric-request case, then reads them back from Langfuse's own
observations API to confirm they actually landed with the expected
shape (not just that no exception was raised locally).

Requires real LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY in .env -- prints
a message and exits cleanly if tracing isn't configured, since there'd
be nothing to verify.

Usage (from the repo root):
    python tests/manual/verify_tracing.py
"""

import json
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import tracing
from agent import call_get_financial_fact, run_agent
from config import LANGFUSE_BASE_URL, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY


def _client():
    from langfuse import Langfuse

    return Langfuse(public_key=LANGFUSE_PUBLIC_KEY, secret_key=LANGFUSE_SECRET_KEY, base_url=LANGFUSE_BASE_URL)


def _wait_for_observation(client, name, marker, attempts=10, delay=2.0):
    """Polls Langfuse's observations API for an observation with this
    name whose input contains `marker` (a unique string stamped into
    this run's question/args) -- ingestion is asynchronous even after
    flush(), so a short poll is more robust than a single immediate
    read. The v2 observations endpoint always returns input/output as
    raw JSON strings (parse_io_as_json was removed), so this parses
    them itself rather than indexing a string as if it were a dict."""
    for _ in range(attempts):
        res = client.api.observations.get_many(name=name, limit=10, fields="core,io,metadata")
        for obs in res.data:
            if obs.input and marker in obs.input:
                return obs, json.loads(obs.input)
        time.sleep(delay)
    return None, None


def main():
    if not tracing.TRACING_ENABLED:
        print("LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY not set -- nothing to verify. Add them to .env first.")
        return

    client = _client()
    marker = f"verify-tracing-{uuid.uuid4().hex[:8]}"

    print(f"[run_agent] asking a real question (backend=gemini), marker={marker!r}")
    question = f"What was Apple's revenue for fiscal year 2025? ({marker})"
    answer, results, warnings = run_agent(question, backend="gemini")
    print(f"  answer: {answer[:120]}...")
    tracing.flush()

    obs, _ = _wait_for_observation(client, "run_agent", marker)
    assert obs is not None, "run_agent span did not appear in Langfuse within the poll window"
    assert obs.type == "AGENT", obs.type
    print(f"  [OK] run_agent span found in Langfuse (id={obs.id}, type={obs.type})")

    tool_obs = client.api.observations.get_many(trace_id=obs.trace_id, type="TOOL", limit=10)
    assert len(tool_obs.data) > 0, "expected at least one nested tool span under the run_agent trace"
    print(f"  [OK] {len(tool_obs.data)} nested tool span(s) found under the same trace")

    print("\n[unmet_metric_request] asking for a metric this project doesn't support")
    fake_metric = f"not_a_real_metric_{marker}"
    result = call_get_financial_fact({"ticker": "AAPL", "metric": fake_metric})
    assert result is None
    tracing.flush()

    obs2, obs2_input = _wait_for_observation(client, "unmet_metric_request", marker)
    assert obs2 is not None, "unmet_metric_request event did not appear in Langfuse within the poll window"
    assert obs2_input["reason"] == "unknown_metric", obs2_input
    print(f"  [OK] unmet_metric_request event found, reason={obs2_input['reason']!r}, metric={obs2_input['metric']!r}")

    print("\nAll checks passed.")


if __name__ == "__main__":
    main()
