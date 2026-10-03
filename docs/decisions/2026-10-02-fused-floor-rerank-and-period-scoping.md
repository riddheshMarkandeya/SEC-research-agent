# Fused-floor rerank rule, windowed MaxP cross-encoder scoring and strict period scoping

**Date:** 2026-10-02

## Context

The offline gold-rank harness put 478 of 572 retrieval misses at the rerank stage. It found
three causes:

- The cross-encoder truncates long table chunks at 512 tokens, so the row that answers a
  question is often never scored.
- Other periods' near-identical tables crowd the candidate pool.
- The 2026-08-13 MAX-of-RRF rule lets every chunk keep the better of its fused and rerank ranks,
  so fused ranks squeeze out chunks the cross-encoder puts in its top 5.

On 901 logged query parts, the stack before this change scored 329 hits and covered 31 of 40
questions.

## Decision

This revisits the 2026-08-13 MAX-of-RRF decision, because the harness gave measured evidence
it lacked.

1. **Fused floor (F = 3).** A chunk scores the RRF term of its cross-encoder rank. Only the
   fused pool's top 3 keep the better of their two ranks, and a 1e-9 cross-encoder share breaks
   ties.
2. **Windowed MaxP.** Each candidate is split on line boundaries into windows of 380 tokens,
   leaving room for the query in 512. A window that starts inside a table carries the caption,
   the `<TABLE>` tag and the first 3 table rows. A chunk scores its best window.
3. **Strict period scoping.** A query that names a period, whether an explicit date within
   ±7 days, a fiscal year, or a fiscal year plus quarter, searches only the matching filings.
   When nothing matches, or the filtered search comes back empty, it falls back to the
   unscoped search.

## Why

Each rule was measured offline on the same 901 query parts before it was built:

| Rule | Hits | Questions covered |
|---|---|---|
| Stack before this change | 329 | 31/40 |
| Full stack, F = 3 | 526 | 37/40 |
| Full stack, F = 0 (pure cross-encoder order) | 599 | 34/40 |

F = 0 scores more hits, but it loses whole questions. Those are long, many-topic passages that
both base retrievers rank first and the cross-encoder scores poorly. A floor of 3 keeps those
questions without letting every fused rank compete.

The post-live replay (plan step 15) re-checks F = 0 against F = 3 on the live run's own
queries.

Strict scoping costs 10 part hits, where the prior-year column lives only in the next filing.
That loss was measured and accepted.

Latency rises to 3.5–4.9 s per search; also accepted.

Two other deviations from the prototype:

- An impossible date in untrusted query text is skipped rather than allowed to raise.
- A company missing from the company list is skipped on the fiscal-year path and logged.

## Files touched

- `src/sec_agent/retrieval/period_scope.py` (new)
- `src/sec_agent/retrieval/rerank_windows.py` (new)
- `src/sec_agent/retrieval/retrieval.py`
- `src/sec_agent/devtools/retrieval_replay.py`
- Tests:
  - `tests/retrieval/` (test_period_scope, test_rerank_windows, test_retrieval)
  - `tests/devtools/test_retrieval_replay.py`
  - `tests/manual/verify_period_scoped_rerank.py`
  - `tests/manual/verify_retrieval_replay.py`

## Verification

- **Offline acceptance reproduced the prototype exactly:**
  - F = 3: 526/901 and 37/40. Re-run after review with an identical result.
  - F = 0: 599 and 34/40.
- **Live script:** green on all 6 checks.
- **Gates:** 1252 tests pass, and diff coverage is 100%.
- **Live 48-question eval** (`eval/eval_results/20261003T030904Z.json`): 44/48, against the
  replay-adjusted 42/48 baseline. It gained 4 questions and dropped 2. Both drops are
  citation-gate refusals of a quote cited to the wrong source number, where the quote was in
  another retrieved source, so neither drop comes from retrieval. The gate re-mine of the run
  showed no verdict changes.
- **Post-live replay of the run's own queries:** F = 3 covered 16/16 questions and F = 0
  covered 13/16. F = 0 newly covered nothing, so F = 3 stands. Details are in the plan's
  "Testing and verification" section.

## Related

- Revisits `docs/decisions/2026-08-13-hybrid-retrieval-and-reranker-fix.md`. Its MAX-of-RRF
  rule is narrowed to the fused top 3.
- Plan: `docs/plans/2026-10-02-package-5-retrieval.md`
- Review: `docs/reviews/2026-10-02-package-5-retrieval.md`
- Spec and measurements: `docs/plans/2026-09-30-retrieval-gold-rank-harness.md` ("Step 7")
