# Week 7 guardrails, part 2: `mcp_server.py` auth + rate limiting

**Date:** 2026-09-01

## Context

Before this, `mcp_server.py` had zero auth or throttling: anyone who
could reach the port could call any tool unlimited times.

## Decision

Plain shared-secret bearer token, not the `mcp` SDK's native OAuth
support — `AuthSettings` requires `issuer_url`/`resource_server_url`
(confirmed via `inspect`), a full OAuth 2.1 flow built for multi-tenant
issuing deployments this single-operator tool doesn't have. Hand-rolled
in-memory fixed-window rate limiter, not a library — no rate-limiting
package was already a dependency, and `uvicorn.run()` runs single-
process, so no cross-process coordination is needed. Both wired into one
plain ASGI middleware (`_AuthRateLimitMiddleware`), deliberately not
Starlette's `BaseHTTPMiddleware` (documented to interfere with streaming/
disconnect propagation, a real risk on the SSE-based transport). Rate
limiting runs **before** auth, keyed by **client IP**, not the token.

## Why

Issues caught by `/code-review` before shipping, first pass: a timing
side-channel on the token comparison (`==` short-circuits; fixed with
`secrets.compare_digest()`); `_RateLimiter._windows` never evicted
expired keys, an unbounded memory leak on a long-running server (fixed by
pruning on every `allow()` call — noted, not optimized further, since an
O(n) rebuild is negligible at this project's actual scale);
`BaseHTTPMiddleware`'s streaming caveat (rewritten as plain ASGI).

A more significant issue on the second review pass: **unauthenticated
requests never touched the rate limiter at all** — auth-first design
meant credential-guessing traffic was completely unthrottled, and keying
by the one shared token meant every legitimate caller shared a single
budget. Fixed by the same change: rate limiting before auth, keyed by IP.
Also fixed in the same pass: `Retry-After`'s `int()` truncation on a
fractional-second window (changed to `math.ceil()`).

## Files touched

`mcp_server.py` (`_is_authorized`, `_RateLimiter`,
`_AuthRateLimitMiddleware`), `config.py`/`.env.example`
(`MCP_AUTH_TOKEN`, `MCP_RATE_LIMIT_REQUESTS`,
`MCP_RATE_LIMIT_WINDOW_SECONDS`).

## Verification

11 new unit tests, full suite 316/316. `tests/manual/verify_mcp_server.py`
extended with 3 new live checks against the real running server:
`check_auth()`, `check_rate_limit()`, and
`check_unauthenticated_requests_are_rate_limited()` (confirmed
`[401, 401, 429]` live). All 3 pre-existing functional checks still
passed unauthenticated against a default-config server, confirming
backward compatibility by default.

## Related

`docs/decisions/2026-08-25-mcp-server-week6.md` (the server this
hardens), `docs/decisions/2026-08-26-week7-citation-hard-gate-ollama-retry.md`
(Week 7 part 1).
