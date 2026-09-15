# MCP server exposing all 3 agent tools over Streamable HTTP (Week 6)

**Date:** 2026-08-25

## Context

Expose `search_filings`/`get_financial_fact`/`compare_financial_metric`
to any MCP client, not just this project's own tool-calling loop. Scoped
and design-approved conversationally first (Substantial-tier): HTTP
transport chosen over stdio (a future web UI is planned on the same
server); plain structured JSON results with no `[n]` citation numbering
(agent.py's citation framing is specific to its own system prompt, not
something a generic MCP client expects).

## Decision

Reuses `agent.py`'s existing tool logic and schemas rather than
duplicating them — `_call_get_financial_fact`/
`_call_compare_financial_metric` renamed to public
`call_get_financial_fact`/`call_compare_financial_metric`. Used the
low-level `mcp.server.Server` API (not `FastMCP`, which derives schemas
from type hints/docstrings — would mean maintaining the already-hardened
tool descriptions a second time). Every tool result carries an
always-present `source` block (ticker, form, period, accession, a real
`sec_url`), matching how reference MCP servers behave.
`search_filings` citations additionally get a browser-native "Scroll To
Text Fragment" (`#:~:text=`) anchor.

## Why

`sec_url` construction needed no new ingestion work — `edgar_ingest.py`
already stores `cik`/`primaryDocument` per filing, and already had the
URL formula in `fetch_filing_html()`; extracted into
`_filing_document_url()`/`get_filing_url()`. Two design mistakes caught
and fixed before finalizing: the text-fragment was originally gated on
the whole chunk's `contains_table` flag rather than the excerpt's own
content (would wrongly drop the fragment for a mostly-prose chunk with
one small table); the excerpt was originally planned as "the first
sentence" but replaced with a fixed-length, word-boundary-truncated
prefix, since a period-based splitter would frequently cut mid-number in
a filing full of dollar figures. Percent-encoding was double-checked
live (not assumed) against the text-fragment spec's `-`/`,` syntactic
meaning.

## Files touched

`mcp_server.py` (new), `agent.py` (public renames),
`tests/manual/verify_mcp_server.py` (new).

## Verification

Live end-to-end via `verify_mcp_server.py`: starts the real server, real
`mcp` client over genuine HTTP, checks `list_tools()`, value correctness
against ground truth, real live `sec_url` fetchability, and that a
text-fragment excerpt literally appears in the fetched live filing page.
Full suite 275/275.

## Related

`docs/decisions/2026-09-01-mcp-server-auth-rate-limiting.md` (Week 7's
follow-up guardrails for this server).
