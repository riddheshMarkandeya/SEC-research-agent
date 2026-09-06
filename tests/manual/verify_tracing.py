"""
One-time (re-runnable) live verification for tracing.py (Week 7
guardrails, Langfuse tracing).

Why this exists: tracing.py's own gating logic (TRACING_ENABLED,
traced_span's no-op branch, record_unmet_metric_request's payload,
local JSONL logging) is pure/deterministic and fully unit-tested
(tests/test_tracing.py) -- but the actual Langfuse SDK network calls
are live-only, per this project's TDD carve-out. This script runs a
real run_agent() question and a real unmet-metric-request case, then
reads them back from Langfuse's own observations API AND from the
local TRACE_LOG_PATH JSONL file to confirm both actually landed with
the expected shape (not just that no exception was raised locally).

Requires real LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY in .env -- prints
a message and exits cleanly if tracing isn't configured, since there'd
be nothing to verify on the Langfuse side (the local log's own
independence from Langfuse is checked separately, see
check_local_log_independent_of_langfuse() below).

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
from config import LANGFUSE_BASE_URL, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, TRACE_LOG_PATH


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


def _read_local_log_lines(marker):
    path = Path(TRACE_LOG_PATH)
    if not path.exists():
        return []
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [line for line in lines if marker in json.dumps(line)]


def check_local_log_matches_the_same_run(marker):
    # Only the top-level "run_agent" span's own input contains the
    # marker (it's stamped into the free-text question) -- a nested
    # tool call's args (ticker/metric/etc) never do, so this locates
    # the run via the agent line's marker match, then groups every
    # local log line sharing that run_id, not by re-searching for the
    # marker in each line's own input.
    print(f"\n[local log] checking {TRACE_LOG_PATH} for marker={marker!r}")
    marked_lines = _read_local_log_lines(marker)
    agent_lines = [line for line in marked_lines if line["name"] == "run_agent"]
    assert len(agent_lines) == 1, agent_lines
    assert agent_lines[0]["is_root"] is True, agent_lines[0]

    run_id = agent_lines[0]["run_id"]
    path = Path(TRACE_LOG_PATH)
    all_lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    tool_lines = [line for line in all_lines if line["run_id"] == run_id and line["as_type"] == "tool"]
    assert len(tool_lines) > 0, "expected at least one local tool span sharing the agent span's run_id"
    print(f"  [OK] local log has 1 root 'run_agent' line + {len(tool_lines)} tool line(s), same run_id")


def check_local_log_independent_of_langfuse():
    """Proves the local log doesn't depend on Langfuse being
    configured -- temporarily flips TRACING_ENABLED off in-process
    (same effect as unsetting LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY)
    and confirms record_unmet_metric_request() still writes a local log
    line. A separate, simpler check already confirmed this via a real
    subprocess with the env vars actually unset (see PROJECT_CONTEXT.md);
    this one re-confirms it stays true after any future tracing.py
    change, without needing a second process."""
    print("\n[local log] checking it still works with Langfuse forced off")
    marker = f"verify-tracing-nolangfuse-{uuid.uuid4().hex[:8]}"
    original = tracing.TRACING_ENABLED
    tracing.TRACING_ENABLED = False
    try:
        result = call_get_financial_fact({"ticker": "AAPL", "metric": f"not_a_real_metric_{marker}"})
        assert result is None
    finally:
        tracing.TRACING_ENABLED = original

    lines = _read_local_log_lines(marker)
    assert len(lines) == 1, lines
    assert lines[0]["name"] == "unmet_metric_request"
    print("  [OK] local log line written even with TRACING_ENABLED forced False")


def main():
    if not tracing.TRACING_ENABLED:
        print("LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY not set -- skipping Langfuse checks.")
        check_local_log_independent_of_langfuse()
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

    check_local_log_matches_the_same_run(marker)

    print("\n[unmet_metric_request] asking for a metric this project doesn't support")
    fake_metric = f"not_a_real_metric_{marker}"
    result = call_get_financial_fact({"ticker": "AAPL", "metric": fake_metric})
    assert result is None
    tracing.flush()

    obs2, obs2_input = _wait_for_observation(client, "unmet_metric_request", marker)
    assert obs2 is not None, "unmet_metric_request event did not appear in Langfuse within the poll window"
    assert obs2_input["reason"] == "unknown_metric", obs2_input
    print(f"  [OK] unmet_metric_request event found, reason={obs2_input['reason']!r}, metric={obs2_input['metric']!r}")

    check_local_log_independent_of_langfuse()

    print("\nAll checks passed.")


if __name__ == "__main__":
    main()
