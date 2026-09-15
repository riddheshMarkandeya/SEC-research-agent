# Week 7 guardrails, part 1: citation hard-gate + Ollama retry/backoff

**Date:** 2026-08-26

## Context

Two of Week 7's four guardrail sub-items (rate limits and Langfuse
tracing deliberately deferred to later parts). `verify_citations()` had
existed since Week 5c but only ever produced warnings alongside a
still-returned answer — the design principle already called for this to
become a hard guardrail.

## Decision

`_format_refusal_message()` and a single choke-point helper,
`_finalize_answer()`, that both of `run_agent()`'s return sites route
through: if citation warnings are still non-empty (after Gemini's
one-shot retry is exhausted, or immediately for Ollama), the answer text
is withheld and replaced with a refusal naming the failed claim(s).
`_ollama_call()` gained a 3-attempt linear backoff on
`ConnectionError`/`ConnectTimeout` only.

## Why

The first backoff draft also retried on plain `Timeout` (including
`ReadTimeout`) — but this project's CPU-only setup already takes 60-70s+
per question, so a `ReadTimeout` is plausibly a genuinely slow-but-
working answer, not a stalled server; retrying it would silently turn
one 240s timeout into up to three. Fixed by splitting the timeout into
`(connect=10, read=240)` and narrowing the retry to `ConnectionError`
only.

A `/code-review` pass caught a real eval-harness false positive: a
hard-gate refusal necessarily repeats the value it's rejecting, and
`grade_numeric()`'s plain text scan couldn't tell a refusal apart from a
real match — confirmed live before fixing. Fixed by extracting `_grade()`
which short-circuits numeric/comparison questions to FAIL whenever
`citation_warnings` is non-empty, without ever text-scanning a refusal.
A third review pass (multi-angle) found two more real issues: the
`has_citation` eval stat matched the raw refusal text and inflated the
citation-rate stat; the third return site (`run_agent()`'s generic
timeout fallback) hardcoded its own tuple instead of routing through
`_finalize_answer()`, so the single-choke-point invariant wasn't
literally true even though behaviorally harmless. Both fixed. A fourth
pass came back empty except one free micro-fix (short-circuit ordering);
capped there per the two-clean-passes rule.

## Files touched

`agent.py` (`_format_refusal_message`, `_finalize_answer`),
`llm_backends.py` (Ollama retry/backoff), `eval_harness.py` (`_grade`,
`has_citation` fix).

## Verification

Full suite 293/293 (up from 275). Live-checked success paths unaffected
on both backends; live-checked the retry loop engages against a real
(not mocked) unreachable-port scenario (~21s elapsed, 3 real attempts);
live-checked the `_grade()` fix end-to-end.

## Related

`docs/decisions/2026-09-01-mcp-server-auth-rate-limiting.md` (Week 7
part 2), `docs/decisions/2026-09-04-langfuse-tracing.md` (Week 7 part 3).
