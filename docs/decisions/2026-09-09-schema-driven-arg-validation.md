# Schema-driven arg/input validation redesign

**Date:** 2026-09-09

## Context

Substantial-scope redesign, picked up from `BACKLOG.md`'s highest-impact
open item: hand-rolled tool-arg validation had broken three separate
times across three review dates, most recently `isinstance(fiscal_year,
int)` silently accepting a JSON boolean. Full design:
`docs/plans/2026-09-09-schema-driven-arg-validation.md`. Review:
`docs/reviews/2026-09-09-schema-driven-arg-validation.md`.

## Decision

One generic `validate_tool_args()` backed by `jsonschema` (pinned
`4.26.0`), with `"additionalProperties": false` added to every tool
schema so it doubles as both what's advertised and what's enforced.
Extended to two more trust boundaries per the user's own follow-up
question: `llm_backends.py`'s raw LLM response indexing, and
`companies.py`'s `load_companies()`.

## Why

`jsonschema`'s default type checker already excludes `bool` from
`"integer"`, fixing the recurring bool/int bug as a side effect of the
library switch. See the plan doc for the two carve-outs a flat schema
check can't express (the `metric` enum exception for telemetry routing,
and the `fiscal_year`/`start_fiscal_year`/`end_fiscal_year` exclusion).
Two-pass layered review found and fixed one real regression (a
one-off `null`-handling patch on a single property instead of the
general problem — fixed generally: any declared property's `null` is now
equivalent to the key being absent) plus two smaller design issues
(a `set()` conversion losing declaration order; an inconsistent
underscore-prefixed name on now-shared production infrastructure).

## Files touched

`agent.py` (`validate_tool_args`), `mcp_server.py`, `llm_backends.py`,
`companies.py`.

## Verification

Full suite 440/440. Manually verified both live paths (Ollama backend
tool calls, full `verify_mcp_server.py` pass) still accept legitimate
args after the change.

## Related

`docs/plans/2026-09-09-schema-driven-arg-validation.md`,
`docs/reviews/2026-09-09-schema-driven-arg-validation.md`.
