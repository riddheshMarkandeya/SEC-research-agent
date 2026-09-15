# Week 7 guardrails, part 3: Langfuse tracing

**Date:** 2026-09-04

## Context

Closes the last open Week 7 item. Before this, zero observability into
runtime behavior existed, and (per the 2026-08-28 ratio-registration
work) "let evidence decide" for new formulas was 100% manual.

## Decision

New `tracing.py`, single-responsibility, gated by
`TRACING_ENABLED = bool(LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY)`.
`agent.py`'s `run_agent()` became a thin traced wrapper around a renamed
`_run_agent_impl()`; `_dispatch_tool_call()` and `mcp_server.py`'s three
tool handlers wrap each call in a `"tool"`-typed span, nesting under
`run_agent` via OTel context propagation. Two distinct
`record_unmet_metric_request()` reasons: `"unknown_metric"` (a real
"should we add a formula" signal) vs `"no_data_for_ticker"` (a
recognized metric with no data for this ticker/period) — deliberately
not recorded for boundary rejections (schema violations), which would be
noise.

## Why

The actual `langfuse` SDK was installed and inspected live before
writing any wiring code — caught that the docs' `create_event()` claim
doesn't exist, confirmed the real mechanism (`as_type="span"`
observations) and that `as_type="tool"`/`"agent"` are real valid types.
Per-call LLM generation tracing (token counts, cost/latency) was
deliberately scoped out, per the user's direction, as a real but
separate enhancement with no evidence yet it's needed.

Two rounds of real gaps caught by `/code-review`, both in the
unmet-metric-request tracing: first pass — `yoy_growth`/multi-year-
average branches skipped the `None`-check other paths had, making a
genuine no-data case invisible; second pass — the opposite bug in the
same code, recording `unknown_metric` when `metric` was omitted entirely
(a schema violation) rather than genuinely unrecognized, polluting the
signal with schema-noise. Both fixed with regression tests.

## Files touched

`tracing.py` (new), `agent.py`, `mcp_server.py`,
`tests/manual/verify_tracing.py` (new).

## Verification

A throwaway smoke-test script confirmed the write path end-to-end
against real Langfuse credentials before any production code was
written. 11 new tests in `test_tracing.py` plus 11 in `test_agent.py`,
full suite 334/334. Live: `run_agent` span appeared with 1 nested tool
span; `unmet_metric_request` event appeared with the right reason for a
deliberately-unsupported metric.

## Related

`docs/decisions/2026-09-05-local-jsonl-trace-log.md` (the
Langfuse-independent backup built the next day).
