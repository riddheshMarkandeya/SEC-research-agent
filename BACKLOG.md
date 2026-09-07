# Backlog

Tracks open work: what's queued, what's in progress. This is **not** a
changelog — completed work's rationale and verification live in
`PROJECT_CONTEXT.md` (and, for Substantial work, its own design doc
under `docs/plans/`). Link out to the relevant doc instead of
re-explaining reasoning here; keep entries short.

**Keep this current as work happens, not just at session-end**: add a
line the moment a new open item is identified (a deferred idea, a
found-but-not-fixed bug, a follow-up) — don't wait for a wrap-up. Move
an item to "In progress" when you start it. When it's done, remove it
from here *and* land its `PROJECT_CONTEXT.md` changelog entry in the
same step — an item should never just vanish from this file with no
changelog trace of what happened to it.

This file replaces `PROJECT_CONTEXT.md`'s old "Next steps" section,
which needed its own 380-line cleanup pass once already (2026-08-19)
from exactly this kind of bloat — don't let this file suffer the same
fate; prune it as items resolve.

## In progress

_(nothing right now)_

## Backlog

### From the 2026-09-06 full-codebase review

Full evidence/reasoning for each: `docs/reviews/2026-09-06-full-codebase-review.md`.

- [ ] **[High]** `agent.py`'s tool-dispatch functions crash (`TypeError`) on non-hashable/non-int LLM tool-call arguments instead of degrading gracefully — [review §1](docs/reviews/2026-09-06-full-codebase-review.md#1-agentpys-dont-trust-the-schema-defenses-have-gaps-that-crash-instead-of-degrading)
- [ ] **[High]** `eval_harness.py`'s `run_eval()` has no per-question exception isolation — one failing question loses the whole batch's results — [review §2](docs/reviews/2026-09-06-full-codebase-review.md#2-evalharnesspy-has-no-per-question-exception-isolation)
- [ ] **[High]** `eval_harness.py`'s `grade_judged()` bypasses `llm_backends.py`'s retry/backoff and logging entirely — [review §3](docs/reviews/2026-09-06-full-codebase-review.md#3-evalharnesspys-gradejudged-bypasses-llmbackendspy-entirely)
- [ ] **[High]** `compare_financial_metric` silently returns empty for `total_assets`/`cash_and_equivalents`/`inventory` at the latest fiscal year (SEC frame-anchoring gap) — [review §4](docs/reviews/2026-09-06-full-codebase-review.md#4-comparefinancialmetric-silently-returns-empty-for-totalassetscashandequivalentsinventory-at-the-latest-fiscal-year)
- [ ] **[Medium]** `chunk_documents.py`'s final chunk-flush produces malformed last chunks + wrong `contains_table` metadata (confirmed in 4/25 real filings) — [review §5](docs/reviews/2026-09-06-full-codebase-review.md#5-chunkdocumentspys-final-chunk-flush-has-no-tail-filter)
- [ ] **[Medium]** `chunk_documents.py`'s `strip_leading_metadata()` can truncate a document to 1 character on an untested edge case — [review §6](docs/reviews/2026-09-06-full-codebase-review.md#6-chunkdocumentspy64-68s-stripleadingmetadata-truncates-to-1-character)
- [ ] **[Medium]** `edgar_ingest.py`'s `get_filing_list()` call is unguarded, unlike the per-filing loop below it — one bad network call aborts ingestion for every remaining company — [review §7](docs/reviews/2026-09-06-full-codebase-review.md#7-edgaringestpy190s-getfilinglistcik-call-is-unguarded)
- [ ] **[Medium]** A string `fiscal_year` silently misrecords as `"no_data_for_ticker"` telemetry instead of a schema-violation signal — [review §8](docs/reviews/2026-09-06-full-codebase-review.md#8-a-string-fiscalyear-silently-misrecords-as-nodataforticker)
- [ ] **[Medium]** `formulas.py`'s ratio computation has no zero-denominator guard (unlike `get_yoy_growth`) — [review §9](docs/reviews/2026-09-06-full-codebase-review.md#9-formulaspys-ratio-computation-has-no-zero-denominator-guard)
- [ ] **[Medium]** `tracing.py`'s `traced_span()` never records exception info — a crash and a no-op look identical in the local log — [review §10](docs/reviews/2026-09-06-full-codebase-review.md#10-tracingpys-tracedspan-never-records-exception-info)
- [ ] **[Medium]** `mcp_server.py` never calls `tracing.flush()` on shutdown — Langfuse observations can be lost on restart — [review §11](docs/reviews/2026-09-06-full-codebase-review.md#11-mcpserverpy-never-calls-tracingflush-on-shutdown)
- [ ] **[Medium]** `_format_no_comparison_message` is missing the "never tagged" hint its sibling has; `search_filings` doesn't validate/log an unknown ticker like the other two tools do — [review §12](docs/reviews/2026-09-06-full-codebase-review.md#12-two-smaller-consistency-gaps)
- [ ] **[Low]** `edgar_ingest.py`'s `parse_filing()` has zero test coverage despite being pure/deterministic — [review §13](docs/reviews/2026-09-06-full-codebase-review.md#13-edgaringestpys-parsefiling-has-zero-test-coverage)
- [ ] **[Low]** `retrieval.py`'s live half has no `tests/manual/verify_*.py` script, unlike every other live-only integration point — [review §14](docs/reviews/2026-09-06-full-codebase-review.md#14-retrievalpys-live-half-has-no-manual-verification-script)
- [ ] **[Low]** `xbrl_facts.py`'s `get_frame()` cross-tag merge has an untested set-iteration-order dependency — [review §15](docs/reviews/2026-09-06-full-codebase-review.md#15-xbrlfactspys-getframe-has-an-untested-ordering-dependency)
- [ ] **[Low, design note]** `query_chunks.py` duplicates `retrieval.py`'s query logic instead of reusing it
- [ ] **[Low, design note]** `tracing.py` has two overlapping "record an instantaneous fact" primitives (`record_unmet_metric_request` vs `log_event`) with no documented decision rule for which to use

### Carried over from `PROJECT_CONTEXT.md`'s old "Next steps" (pre-2026-09-06)

- Per-call LLM "generation" tracing (token counts, prompt/completion text, per-call cost/latency as Langfuse generation objects) — explicitly scoped out of the Langfuse tracing work, parked until a real debugging need shows up. See `PROJECT_CONTEXT.md`'s "Week 7 guardrails, part 3" section.
- Multi-turn conversational QA (ConvFinQA-style follow-ups) — `run_agent()` is single-turn only. Parked; revisit only on a real multi-turn need. See `PROJECT_CONTEXT.md`'s Next-steps history (2026-08-25).
- Graph DB (Neo4j) as a retrieval layer — parked; only worth it if a relationship/multi-hop-shaped question actually appears. See `PROJECT_CONTEXT.md` (2026-08-20 discussion).
- `cash_to_assets` ratio's citation-verification gap — `verify_citations()` doesn't check uncited numeric claims at all; no concrete failing case yet. See `PROJECT_CONTEXT.md`'s "Formula registry extended" section (2026-08-25).
- Growing the eval set further toward the original 30-50 FinanceBench-style target — optional, not a fixed requirement.
- "Week 8 — polish + write-up" — no detail scoped yet.

(HNSW index tuning was rejected outright, not parked, so it isn't carried over — see `PROJECT_CONTEXT.md` for that reasoning if needed.)
