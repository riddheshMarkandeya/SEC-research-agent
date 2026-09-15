# Local JSONL trace log — a Langfuse-independent backup

**Date:** 2026-09-05

## Context

While reviewing the just-shipped Langfuse tracing, the user asked
whether full LLM-call detail could hit Langfuse Cloud's free-tier cap,
and whether local logging should exist as a backup. Researched live: the
free tier is 50,000 observations/month (hard-capped, silently stops
recording) and only 30-day retention. At this project's scale the cap
isn't a near-term risk, but retention means data disappears regardless,
and `TRACING_ENABLED=False` (the default for anyone cloning this repo)
meant zero observability rather than degraded observability.

## Decision

`traced_span()` now always writes one local JSONL line to
`TRACE_LOG_PATH`, regardless of whether Langfuse is configured — Langfuse
becomes the optional cloud/dashboard layer on top of an always-on local
baseline. Required a real contract change: `traced_span()` used to yield
`None` when disabled; it now always yields a `_TracedSpan` wrapper.
`run_id` grouping via `contextvars.ContextVar`, reimplementing OTel's own
nesting mechanism locally as a flat `run_id` + `is_root` flag (no full
parent/child linkage — no concrete need yet).

## Why

Log is `.gitignore`d (high-volume/regenerable per-run, unlike the
curated `eval_results/*.json` which is tracked for exactly the opposite
reason).

**A real bug found live, not by a test**: the first full suite run after
this change left 18 real lines in the actual project's
`trace_logs/traces.jsonl` — every existing test exercising `traced_span()`
indirectly had no reason to mock a local-logging concern that didn't
exist when written. Fixed with an autouse `conftest.py` fixture setting
`TRACE_LOG_PATH = ""` by default.

Six issues caught by `/code-review`: missing regression coverage for a
Langfuse-enabled + `question=None` combination (restored); `mkdir()`
called on every single write (cached, invalidated on failure — a second-
order bug where the cache wasn't invalidated on a write failure would
have defeated the entire "always-on backup" premise, fixed); the
exception handler was narrower than the module's documented "never
raise" contract (widened to `except Exception`); two tests asserted on
an unrelated `tmp_path` that would have passed even with the guard
deleted (fixed by spying on `Path.open` directly, after discovering the
first attempted fix also silently passed due to the module's own broad
except swallowing the assertion); `time.time()` (wall clock) used for
duration measurement instead of `time.monotonic()` (fixed).

## Files touched

`tracing.py`, `tests/conftest.py` (new).

## Verification

18 tests added to `test_tracing.py`, full suite 347/347. Live-verified
twice: a real question through `agent.py` with Langfuse keys forced
empty confirmed local logging fires independently; extended
`verify_tracing.py` with checks confirming the local log and real
Langfuse trace agree for the same run, and that local logging survives
Langfuse being disabled.

## Related

`docs/decisions/2026-09-04-langfuse-tracing.md` (predecessor),
`docs/decisions/2026-09-05-local-only-debug-events.md` (the same-day
follow-up extending this to non-span events).
