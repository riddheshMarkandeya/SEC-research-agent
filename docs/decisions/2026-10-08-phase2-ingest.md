# Phase 2 corpus: 12 companies ingested; v1 gate 46/48 with a BM25 regression found

**Date:** 2026-10-08 (live run 2026-10-09T00:24Z)

## Context

Phase 2 build 2 (plan `docs/plans/2026-10-08-phase2-ingest.md`) adds JPM, BAC, TGT, WMT, XOM,
JNJ and CAT (FY2024+, 10-K/10-Q) and gates v1 on the result. The prompt and the corpus change
together, as the phase 2 map accepted. This file records the counts, the timings at the new size
(for the admin-UI plan), the scoping-gate outcome and the v1 result. It is also the regression
record that `live-eval-verification.md` requires for a live-found regression.

## Decision

- The 12-company corpus ships: `companies.json` commit `91534a6`. Fiscal year end months are pinned
  by hand: JNJ 12 and **TGT 2**. TGT 2 revisits the plan's "defer TGT labels to build 5", because
  code review found that month 2 gives correct end-year labels with no code change (user's choice,
  2026-10-08). Only Target's start-year naming is left for build 5.
- **The period-scoping gate did not trip.** The BACKLOG period-scoping item stays for v2 to measure.
- **A new regression was found and filed instead: BM25 corpus statistics.** `bm25_search` scores
  with whole-corpus IDF and average length, then filters to the ticker, so adding unrelated
  companies reorders each company's own BM25 candidates. It is not fixed here: the fix is in
  critical-core `retrieval.py` and goes through plan mode (BACKLOG, High).

## Why

**Scoping gate.** All 551 frozen replay queries and all 47 live `search_filings` calls carried a
ticker, so the cross-company case never occurred in v1. Exposure measured offline (untickered
re-run of the frozen query texts, TGT = 2): 504 queries gain a new company's filing in scope;
1,985 of those filing slots match on their own date or fiscal label (real distractors that the
`(ticker, reportDate)` fix would not remove); 224 slots across 56 queries leak in through another
filing's date. Every leak is on the fiscal-label path: MSFT's June-30 fiscal year end admits the
June-30 10-Qs of the December-year-end companies. No query lost an old date.

**BM25 regression, root cause.** The post-ingest replay (`var/retrieval_replay/phase2-new.json`
against `phase2-base.json`) fell from hit@5 549 to 480 of 981 parts, and coverage from 37 to 34 of
40 questions, while reach held at 97.2%. A differential run of all 31 lost queries against the
pre-ingest state (backup chunks and Chroma) found identical scope dates and identical vector lists
on all 31, with the BM25 list differing on all 31 (about 3.6 of 25 candidates swapped on average).
The fused pool depends only on those two lists, so BM25 statistics are the cause. ANN churn and
scoping are ruled out.

**v1 live result: 46/48** (`20261009T002418Z`, tree `df697fc`, clean, snapshot verified, no
`RESOURCE_EXHAUSTED`) against 48/48 (`20261007T072322Z`, `a96e7db`). `compare_prompt_versions`
explicit mode: 2 expected passes lost, threshold 7, "ok". Drops, each replayed offline from the
live run's own queries on both corpora:
- `msft-three-segments-revenue-q3fy2026`: **the BM25 regression.** The segment table
  (`0001193125-26-191507_47`) was a borderline hit on the old corpus (final rank 5, BM25 rank 28).
  On the new corpus its BM25 rank is 39 and it drops out. Old corpus 3/15 parts hit, new 0/15.
- `msft-segment-revenue-comparison-q3fy2026`: **not the corpus.** 0/15 parts hit on both corpora.
  This question failed in every baseline before 48/48, so variance is the leading reading.
- Neither drop is a prompt or tool effect: the run made no `compare_financial_metric` call (nor
  did the 48/48 run), so the 12-company comparison output and the system prompt's rule 7 never
  came into play.
- Both attributions are provisional until each is replicated with `--ids` on a later quota day
  (BACKLOG, on the BM25 item).

**Fact-tool dry run** (SEC only, no LLM; warms `var/xbrl_cache`): a comparison's results block
grows from at most 738 to 1,446 characters. Banks appear in net-margin comparisons on the
revenue tag that build 5 flags as understated. TGT's FY2025 total assets resolve to the year
ending 2025-02-01, Target's start-year naming in SEC's `fy`. Both are build 5 items.

**Period labels.** `verify_period_labels.py` was inconclusive for almost every new filing. Its
self-description pattern rarely matches, and the banks, WMT, XOM and CAT have no `GrossProfit`
data. Its two flags were expected false positives: the JNJ XBRL check (old 52/53-week ends) and
the TGT check (under month 1). It also gave one new false positive: a CAT 10-Q's outlook sentence
("third quarter of 2024 compared to ...") was read as its own period. Direct inspection of every
new filing's computed label against its report date found all correct except TGT under month 1,
which month 2 fixed.

## Corpus size and timings

| | Before | After |
|---|---|---|
| Filings | 61 | 139 (JPM/BAC/XOM/CAT/JNJ 10 each, TGT/WMT 14 each) |
| Chunks | 7,572 | 19,292 (JPM 3,727, BAC 2,649, CAT 1,322, WMT 1,253, JNJ 1,163, XOM 811, TGT 795) |
| Corpus identity | `d703a4290869` | `33375fa528c5` (`index_matches_chunks` true) |
| `var/data` / `var/chunks` / Chroma | 22 / 19 / 198 MB | 72 / 47 / 409 MB |

- Ingest: 160.6 s for 78 new filings, 0 failed (skip-refetch: 18.1 s for a no-op re-run).
  JPM reads 18 submissions pages, BAC 9.
- Chunking: about 3 s for all 139 filings. All 61 old chunk files are byte-identical.
- Incremental index: 1,730.7 s for 11,720 chunks (0.148 s/chunk; phase 1 was about 0.17).
- BM25 load: 4.6 s. One uncached `hybrid_search`: 4.3 to 5.5 s (cross-encoder included).
- Replay: 234.3 s with a warm rerank cache, 2,674.6 s cold (549 misses after the pools changed).

## Files touched

`src/sec_agent/sources/companies.json`, `src/sec_agent/prompts/model_input_snapshot.json`,
`tests/sources/test_companies.py`, `tests/manual/verify_filing_selection.py`; `BACKLOG.md`.

## Verification

1,391 tests pass; ruff and pyright are clean. `verify_filing_selection.py` is GREEN with 61 old
and 78 new filings. The base replay reproduced 0 lost / 0 gained. Review: 2 rounds, closed
(plan's Review log; `docs/reviews/2026-10-08-phase2-ingest.md`).

## Related

- Plan: `docs/plans/2026-10-08-phase2-ingest.md`; map: `docs/plans/2026-10-07-data-expansion-phase2-map.md`
- Prior corpus expansion: `docs/decisions/2026-10-07-data-expansion-years.md`
- Introducing change: commit `91534a6` (the regression comes from the corpus growth, not from code)
