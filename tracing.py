"""
Observability (Week 7 guardrails, last sub-item): traces agent runs and
tool calls to Langfuse, plus a specific "unmet metric/ratio request"
signal for the ratio-formula-registration work's own requirement (see
PROJECT_CONTEXT.md, 2026-08-28 addendum) -- there was no
logging/telemetry anywhere for "a metric/ratio was requested and
unavailable," so "let evidence decide" for new financial-ratio formulas
was 100% manual until now.

Isolated into its own module so agent.py/mcp_server.py never import the
langfuse SDK directly -- every call site there just calls
traced_span()/record_unmet_metric_request()/flush(), all safe no-ops
when tracing isn't configured. TRACING_ENABLED gates every call
explicitly (same pattern llm_backends._get_gemini_client() already uses
for GEMINI_API_KEY) rather than relying on the SDK's own behavior when
unconfigured, which Langfuse's docs don't fully document either way.
"""

from contextlib import contextmanager
from typing import Iterator

from config import LANGFUSE_BASE_URL, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY

TRACING_ENABLED = bool(LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY)

_client = None


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


@contextmanager
def traced_span(as_type: str, name: str, input: dict | None = None) -> Iterator[object | None]:
    """Yields a Langfuse observation to update (e.g.
    `span.update(output=...)`), or None when tracing is disabled --
    every call site must check for None before calling anything on it.
    `as_type` is one of Langfuse's own observation types ("agent",
    "tool", "span", ...). Nested calls automatically nest under
    whichever traced_span is currently open, per the SDK's own
    OpenTelemetry-based context propagation."""
    if not TRACING_ENABLED:
        yield None
        return
    client = _get_langfuse_client()
    with client.start_as_current_observation(as_type=as_type, name=name, input=input) as span:
        yield span


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
    tool callers have no question, so it's None there. No-op when
    tracing is disabled."""
    if not TRACING_ENABLED:
        return
    with traced_span(
        "span",
        "unmet_metric_request",
        input={"ticker": ticker, "metric": metric, "reason": reason, "question": question},
    ):
        pass


def flush() -> None:
    """Flushes buffered spans -- call before a short-lived CLI process
    (agent.py's main(), eval_harness.py's run_eval()) exits, since
    Langfuse batches and sends observations asynchronously in the
    background. No-op when disabled."""
    if not TRACING_ENABLED:
        return
    _get_langfuse_client().flush()
