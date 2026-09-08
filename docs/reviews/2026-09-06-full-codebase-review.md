# Full-codebase review — 2026-09-06

**Scope:** entire codebase (not a single diff) — ingestion/retrieval
pipeline, the XBRL facts/formula/agent-reasoning layer, the MCP
server/tracing/eval infra, and the test suite.

**Method:** 4 independent, freshly-spawned subagents in parallel (no
shared context with each other or with any implementation session),
each briefed on this project's actual engineering conventions (from
`CLAUDE.md`) and told to verify findings against real code execution or
real cached/ingested data rather than reading-and-guessing. Each also
read `PROJECT_CONTEXT.md` for grounding on already-decided tradeoffs, so
deliberate design choices wouldn't get flagged as bugs.

**Status:** the 4 High findings are FIXED (2026-09-06, same day) — see
`PROJECT_CONTEXT.md`'s matching section for what changed and how it was
verified. Everything else below is still open, tracked in `BACKLOG.md`.

---

## High priority — real crashes / data loss in production paths

### 1. `agent.py`'s "don't trust the schema" defenses have gaps that crash instead of degrading

[agent.py:448](../../agent.py#L448) and the mirrored check at
[agent.py:555](../../agent.py#L555) use `in` against a dict, which
throws `TypeError` on a non-hashable arg (e.g. the model passing
`"ticker": ["AAPL"]`) — verified live. Similarly,
[agent.py:468-474](../../agent.py#L468-L474) passes
`start_fiscal_year`/`end_fiscal_year` straight through with no type
check, so a numeric-*string* year crashes `formulas.py:444` with
`TypeError`. `agent.py` has **zero** try/except blocks anywhere, so
either crashes the whole request — the same bug class this file's own
docstrings say it's been bitten by three times already (missing metric,
invented keys, empty-string dates), just a fourth/fifth still-open
instance.

### 2. `eval_harness.py` has no per-question exception isolation

[eval_harness.py:254-290](../../eval_harness.py#L254-L290) — if
question 30 of 40 exhausts its retries, all 29 already-graded results
are silently discarded, no partial report is saved, and Langfuse never
flushes.

### 3. `eval_harness.py`'s `grade_judged()` bypasses `llm_backends.py` entirely

[eval_harness.py:150-181](../../eval_harness.py#L150-L181) — raw
`requests.post` with no retry/backoff, reintroducing the exact "Ollama
not accepting connections yet" failure this project already hardened
the *answering* path against.

### 4. `compare_financial_metric` silently returns empty for `total_assets`/`cash_and_equivalents`/`inventory` at the latest fiscal year

Verified against real cached SEC data — SEC doesn't assign a `frame` to
the newest annual instant-fact entry, and the project already knew
about this exact quirk (it's why the ratio metrics built on these are
marked `supports_cross_company=False` in
[formulas.py:107-125](../../formulas.py#L107-L125)) but never extended
the same guard to the raw metrics exposed on the compare tool.

## Medium priority

### 5. `chunk_documents.py`'s final chunk-flush has no tail filter

Unlike the mid-loop path — confirmed producing malformed last chunks in
4 of 25 real ingested filings, and in 2 of those the `contains_table`
metadata comes out **wrong**, which undermines `retrieval.py`'s
table-rescue logic. See
[chunk_documents.py:283-284](../../chunk_documents.py#L283-L284).

### 6. `chunk_documents.py:64-68`'s `strip_leading_metadata()` truncates to 1 character

If fewer than 2 newlines precede the "UNITED STATES" anchor — doesn't
trigger on any of the 25 current filings, but it's an untested landmine
for the next company/filing ingested. See
[chunk_documents.py:64-68](../../chunk_documents.py#L64-L68).

### 7. `edgar_ingest.py:190`'s `get_filing_list(cik)` call is unguarded

Unlike the per-filing loop right below it; one bad network call for one
company aborts ingestion for every subsequent company too. See
[edgar_ingest.py:190](../../edgar_ingest.py#L190).

### 8. A string `fiscal_year` silently misrecords as `"no_data_for_ticker"`

[agent.py:492-493](../../agent.py#L492-L493) — a non-int `fiscal_year`
doesn't crash but silently returns no data, which then gets logged as
`reason="no_data_for_ticker"`, polluting the "should we add a formula
for this" telemetry with false negatives.

### 9. `formulas.py`'s ratio computation has no zero-denominator guard

Unlike the adjacent `get_yoy_growth`, which does
([formulas.py:370](../../formulas.py#L370)) —
[formulas.py:72](../../formulas.py#L72) and
[formulas.py:264](../../formulas.py#L264) have no protection.
`inventory_turnover` (`cost_of_revenue / inventory`) is the most
exposed case.

### 10. `tracing.py`'s `traced_span()` never records exception info

[tracing.py:124-166](../../tracing.py#L124-L166) — the `try/finally`
(no `except`) means a crash and a benign no-op look identical in the
local backup log, undercutting its "always-on debugging backup"
purpose.

### 11. `mcp_server.py` never calls `tracing.flush()` on shutdown

[mcp_server.py:59](../../mcp_server.py#L59) imports only
`log_event, traced_span` — no lifespan/shutdown handler exists, so
not-yet-flushed Langfuse observations can be lost on restart/redeploy.
The local JSONL backup is unaffected (written synchronously).

### 12. Two smaller consistency gaps

`_format_no_comparison_message` is missing the "never tagged" hint its
sibling `_format_no_fact_message` has
([agent.py:362-372](../../agent.py#L362-L372)), and `search_filings`
doesn't validate/log an unrecognized ticker the way
`call_get_financial_fact`/`call_compare_financial_metric` do.

## Test-coverage gaps

### 13. `edgar_ingest.py`'s `parse_filing()` has zero test coverage

It's pure/deterministic (no network dependency) with several
non-trivial documented edge cases, so per this project's own TDD rule
it should have full unit tests. See
[edgar_ingest.py:109](../../edgar_ingest.py#L109).

### 14. `retrieval.py`'s live half has no manual verification script

`bm25_search`/`vector_search`/`rerank` ([retrieval.py:150](../../retrieval.py#L150))
has no `tests/manual/verify_*.py` script, unlike every other live-only
integration point in the project (MCP server, tracing/Langfuse, period
labels).

### 15. `xbrl_facts.py`'s `get_frame()` has an untested ordering dependency

[xbrl_facts.py:427](../../xbrl_facts.py#L427) — if two tags in
`tags_in_play` (an unordered set) both reported the same ticker, the
result would silently depend on set iteration order. Existing tests
only cover the disjoint-ticker case.

## Low priority / design notes (not bugs)

- `query_chunks.py` duplicates `retrieval.py`'s query logic instead of
  reusing it — the same "two independently-drifting copies" pattern
  `config.py` was written specifically to avoid elsewhere.
- `tracing.py` now has two overlapping "record an instantaneous fact"
  primitives (`record_unmet_metric_request` vs `log_event`) with no
  documented rule for which to use when adding a third.

## Areas reviewed with no findings

`retrieval.py`'s RRF/rerank logic, `numeric_utils.py`, `discover_tags.py`,
`companies.py`, `index_chunks.py`, the MCP server's auth/rate-limit
middleware, `config.py`'s defaults, and the test suite's mocking
discipline all came back clean — no new issues found.
