"""
Observability (Week 7 guardrails, last sub-item, extended 2026-09-05
with a local backup): traces agent runs and tool calls to Langfuse,
plus a specific "unmet metric/ratio request" signal for the
ratio-formula-registration work's own requirement (see
PROJECT_CONTEXT.md, 2026-08-28 addendum) -- there was no
logging/telemetry anywhere for "a metric/ratio was requested and
unavailable," so "let evidence decide" for new financial-ratio formulas
was 100% manual until now.

Every span/event is ALSO always written to a local JSONL file
(TRACE_LOG_PATH), independent of whether Langfuse is configured --
Langfuse Cloud's free tier caps at 50k observations/month with only
30-day retention, and TRACING_ENABLED=False (no account configured)
would otherwise mean zero observability rather than degraded
observability. The local log is the always-on baseline; Langfuse is
the optional cloud/dashboard layer on top of it.

Isolated into its own module so agent.py/mcp_server.py never import the
langfuse SDK directly -- every call site there just calls
traced_span()/record_unmet_metric_request()/flush(). TRACING_ENABLED
gates the Langfuse half explicitly (same pattern
llm_backends._get_gemini_client() already uses for GEMINI_API_KEY)
rather than relying on the SDK's own behavior when unconfigured, which
Langfuse's docs don't fully document either way.
"""

import json
import sys
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from config import LANGFUSE_BASE_URL, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, TRACE_LOG_PATH

TRACING_ENABLED = bool(LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY)

_client = None

# Groups every span belonging to one top-level traced_span() call (e.g.
# one run_agent() invocation, or one direct MCP tool call) under a
# shared run_id in the local log, without threading an id through every
# function signature -- the same mechanism OTel already uses under the
# hood for Langfuse's own nesting, reimplemented locally so the JSONL
# log preserves it too.
_current_run_id: ContextVar[str | None] = ContextVar("_current_run_id", default=None)


def _get_langfuse_client():
    """Lazily creates and caches the Langfuse client on first use --
    only ever called when TRACING_ENABLED is True. Imports the langfuse
    SDK here, not at module level, so nothing outside this module needs
    it installed to import tracing.py (it's only actually needed when
    tracing is configured)."""
    global _client
    if _client is None:
        from langfuse import Langfuse

        _client = Langfuse(public_key=LANGFUSE_PUBLIC_KEY, secret_key=LANGFUSE_SECRET_KEY, base_url=LANGFUSE_BASE_URL)
    return _client


_ensured_log_dir: Path | None = None


def _write_local_log(record: dict) -> None:
    """Appends one JSON line to TRACE_LOG_PATH. Best-effort: a write
    failure is printed to stderr and swallowed, never raised -- logging
    must never break the actual call it's wrapping (same treatment
    Langfuse's own SDK gives its own errors). Only calls mkdir() when
    the target directory has changed since the last successful write
    (_ensured_log_dir) -- this runs on every traced_span() exit, i.e.
    every tool call and every run_agent() call, so re-verifying an
    already-created directory on every single write is wasted I/O.
    Found in code review."""
    global _ensured_log_dir
    if not TRACE_LOG_PATH:
        return
    try:
        path = Path(TRACE_LOG_PATH)
        if _ensured_log_dir != path.parent:
            path.parent.mkdir(parents=True, exist_ok=True)
            _ensured_log_dir = path.parent
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
    except Exception as e:
        # Broad on purpose, not just OSError: this module's whole
        # contract is "never raise, ever" -- e.g. json.dumps' own
        # default=str fallback can itself raise (a value whose
        # __str__ raises) with no I/O involved at all. Also resets the
        # cache on any failure (not just a failed mkdir) so the next
        # call retries mkdir() -- otherwise, if TRACE_LOG_PATH's
        # directory is deleted externally while a long-running process
        # (mcp_server.py) keeps running, every later write would keep
        # skipping mkdir() (thinking the directory's already ensured)
        # and fail forever, silently defeating the "always-on backup"
        # this exists for. Found in code review.
        _ensured_log_dir = None
        print(f"[tracing] local log write failed ({TRACE_LOG_PATH}): {e}", file=sys.stderr)


class _TracedSpan:
    """Yielded by traced_span() -- always a real object, never None,
    since the local log needs to capture `output` regardless of whether
    Langfuse is configured. `.update()` mirrors Langfuse's own
    LangfuseSpan.update() shape so call sites don't need to know
    whether Langfuse is actually involved."""

    def __init__(self, langfuse_span=None):
        self.output = None
        self._langfuse_span = langfuse_span

    def update(self, *, output=None, **kwargs) -> None:
        if output is not None:
            self.output = output
        if self._langfuse_span is not None:
            self._langfuse_span.update(output=output, **kwargs)


@contextmanager
def traced_span(as_type: str, name: str, input: dict | None = None) -> Iterator[_TracedSpan]:
    """Always yields a usable _TracedSpan and always writes one local
    JSONL log line on exit, regardless of TRACING_ENABLED. When
    TRACING_ENABLED is also True, additionally opens a real Langfuse
    observation (as_type is one of Langfuse's own observation types --
    "agent", "tool", "span", ...) and forwards `.update()` calls to it;
    nested calls automatically nest under whichever Langfuse observation
    is currently open, per the SDK's own OpenTelemetry-based context
    propagation. The local log's `run_id` grouping (see _current_run_id
    above) is independent of that and always applied."""
    is_root = _current_run_id.get() is None
    run_id = _current_run_id.get() or uuid.uuid4().hex[:12]
    token = _current_run_id.set(run_id) if is_root else None
    # monotonic, not time.time(): a long-running process (mcp_server.py)
    # could see the wall clock adjusted backward (e.g. an NTP
    # correction) mid-span, which would corrupt duration_ms if measured
    # with time.time() instead. Found in code review.
    start = time.monotonic()
    span = _TracedSpan()
    try:
        if TRACING_ENABLED:
            client = _get_langfuse_client()
            with client.start_as_current_observation(as_type=as_type, name=name, input=input) as langfuse_span:
                span._langfuse_span = langfuse_span
                yield span
        else:
            yield span
    finally:
        _write_local_log(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "run_id": run_id,
                "is_root": is_root,
                "as_type": as_type,
                "name": name,
                "input": input,
                "output": span.output,
                "duration_ms": round((time.monotonic() - start) * 1000, 1),
            }
        )
        if token is not None:
            _current_run_id.reset(token)


def record_unmet_metric_request(ticker: str, metric: str, reason: str, question: str | None = None) -> None:
    """Fires whenever call_get_financial_fact()/call_compare_financial_metric()
    (agent.py) come back empty for a reason worth tracking: either
    `metric` isn't a name this project knows at all (reason=
    "unknown_metric" -- the "let evidence decide" signal for adding a
    new RATIO_DEFINITIONS entry), or it's a known metric/ratio with no
    data for this specific ticker/period (reason="no_data_for_ticker" --
    the same shape of gap already found and documented for
    inventory_turnover/AAPL/MSFT). `question` is the free-text question
    when known (agent.py's tool-dispatch path); mcp_server.py's direct
    tool callers have no question, so it's None there. Always goes
    through traced_span(), so it's recorded locally even when Langfuse
    isn't configured."""
    with traced_span(
        "span",
        "unmet_metric_request",
        input={"ticker": ticker, "metric": metric, "reason": reason, "question": question},
    ):
        pass


def log_event(category: str, **fields) -> None:
    """Local-only debug event -- never sent to Langfuse, unlike
    traced_span()/record_unmet_metric_request() above. A retry attempt,
    a rejected tool call, a self-correction decision are instantaneous
    facts, not spans of work with a duration, so they don't fit
    traced_span()'s shape, and this project doesn't want every one of
    these mirrored to a cloud dashboard anyway -- just kept locally for
    debugging. Tags `run_id` from the currently-open traced_span, if
    any (agent.py's call sites are always inside one); None when called
    standalone (mcp_server.py's auth/rate-limit rejections happen
    before any span opens). Reuses _write_local_log's existing
    best-effort/never-raise behavior, so this also silently respects
    TRACE_LOG_PATH being disabled."""
    _write_local_log(
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "run_id": _current_run_id.get(),
            "category": category,
            **fields,
        }
    )


def flush() -> None:
    """Flushes buffered Langfuse spans -- call before a short-lived CLI
    process (agent.py's main(), eval_harness.py's run_eval()) exits,
    since Langfuse batches and sends observations asynchronously in the
    background. No-op when Langfuse isn't configured; the local JSONL
    log is written synchronously on every traced_span() exit, so it
    needs no flush."""
    if not TRACING_ENABLED:
        return
    _get_langfuse_client().flush()
