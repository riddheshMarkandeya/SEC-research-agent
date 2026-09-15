# Local-only debug events beyond the Langfuse mirror

**Date:** 2026-09-05

## Context

The local JSONL log only wrote what `traced_span()`/
`record_unmet_metric_request()` already produced. The user wanted more:
local-only signal for anything "important and can help debugging,"
independent of whether it's Langfuse-worthy — several moments in this
codebase (retries, invented tool args, self-correction retries) had
already repeatedly needed hand-diagnosis.

## Decision

New `tracing.log_event(category, **fields)`, deliberately not built on
`traced_span()` — these are instantaneous facts, not spans of work, and
this project doesn't want every one mirrored to a cloud dashboard. Tags
`run_id` from the currently-open span when called from inside one,
`None` when standalone. `llm_backends.py`'s two retry loops now log
`llm_retry`; `agent.py`'s citation self-correction retry logs
`citation_retry`; the boundary-rejection guards in both `call_*`
functions now log `tool_call_rejected` with a specific `reason` —
previously these returned `None`/`{}` with zero signal anywhere, not
even the unmet-metric-request event (deliberately scoped to "formula
doesn't exist," not "model didn't follow the schema"). `mcp_server.py`'s
middleware logs `auth_rejected`/`rate_limited` with `client_ip`.

## Why

`missing_metric` was found while implementing this round, not planned:
the existing `metric is None` guard already distinguished "no formula"
from "key omitted entirely," but only the former got any signal — the
omitted-key case was completely invisible until now.

## Files touched

`tracing.py` (`log_event`), `llm_backends.py`, `agent.py`,
`mcp_server.py`.

## Verification

New/extended tests across `test_tracing.py` (+3), `test_llm_backends.py`
(+5, this function had none before), `test_agent.py` (+11). Full suite
365/365. Live-verified: pointed `OLLAMA_URL` at an unreachable port and
confirmed all 3 retry lines landed correctly grouped under the same
`run_id` as the `run_agent` span, which itself was still recorded even
though the exception propagated all the way out uncaught — confirming
the `finally`-based local logging survives an unhandled exception, not
just the happy path.

## Related

`docs/decisions/2026-09-05-local-jsonl-trace-log.md` (the mechanism this
extends).
