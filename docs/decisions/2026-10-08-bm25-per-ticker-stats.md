# BM25 statistics per ticker for ticker'd searches

**Date:** 2026-10-08

## Context

`retrieval.bm25_search` scored every query against one `BM25Okapi` index over the whole corpus,
then filtered to the ticker. IDF and average chunk length therefore depended on every company, so
adding the 7 phase 2 companies reordered each existing company's own BM25 list. Phase 2 build 2's
replay showed it: hit@5 549 → 480 of 981, coverage 37 → 34 of 40, and on all 31 lost queries only
the BM25 list changed. Live, it caused the `msft-three-segments-revenue-q3fy2026` drop in v1 run
`20261009T002418Z` (46/48). This is a live-found regression, so this file is written regardless of
the ADR gate.

## Decision

A search with a ticker ranks with a `BM25Okapi` built over that ticker's chunks only. The
per-ticker indexes are built eagerly in `_load_bm25_index`, and the token lists are not kept.
Searches without a ticker keep the whole-corpus index, because they search the whole corpus. The
ranking loop moved unchanged into the pure `_rank_bm25`, and index selection moved into the pure
`_bm25_source`.

## Why

- Per-ticker statistics make a company's BM25 ranking independent of which other companies are
  ingested. That is the property the regression broke.
- **Rejected: statistics over the period-scoped filing set.** These sets are a few hundred chunks
  and change with every query. rank_bm25 raises any negative IDF to `0.25 × average_idf`, and in
  sets that small many words would hit that floor.
- **Known residual: the same IDF clamp, milder.** The plan review measured MSFT-only statistics:
  the floor is 1.15, 30 words are clamped, `revenue` has an IDF of 0.27, and 71 words sit below
  the floor. So a word in more than half of a company's chunks outscores a less common one. The
  remaining losses below fit this. Income-statement chunks (revenue, cost of revenue, R&D) fell in
  scoped BM25 rank: for `msft-rd-intensity-fy2025` 1 → 8 and 1 → 11, for
  `nvda-inventory-turnover-fy2026` 4 → 8. **The next suspect is the clamp** (rank_bm25's
  `epsilon`, or another IDF variant such as BM25+/BM25L). It is not tuned in this change.

## Files touched

- `src/sec_agent/retrieval/retrieval.py`: `_bm25_by_ticker`, `_ticker_indexes`, `_rank_bm25`,
  `_bm25_source`, and the `bm25_search` routing. It logs `retrieval_bm25_ticker_index` (ticker,
  chunks, build_ms) per ticker at load, and `retrieval_bm25_unknown_ticker` when there is no index.
- `tests/retrieval/test_retrieval.py`: a stability regression test (with a precondition that the
  whole-corpus index orders the fixture differently), plus tests for grouping, the report-date
  filter, the zero-score cutoff, the `n` cap and source selection.
- `tests/manual/verify_bm25_ticker_stats.py`: a real-corpus check that `bm25_search(ticker="MSFT")`
  equals an MSFT-only rank_bm25 oracle. It was RED before the change and is GREEN after.

## Verification

- 1,399 tests pass; ruff and pyright are clean. `retrieval.py` has 100% non-pragma line and branch
  coverage.
- **Manual script** GREEN. The segment table `0001193125-26-191507_47` ranks as follows, unscoped
  and then scoped:

  | Query | Unscoped | Scoped |
  |---|---|---|
  | eval question | 119 → 139 | 12 → 19 |
  | quoted-segments query | 46 → 31 | 7 → 6 |
  | Note 16 query | 42 → 32 | 6 → 5 |

  The plan's bar of an unscoped rank of 25 or better was dropped. Even on the pre-phase-2 corpus
  that rank was 21–124, so the bar could not be met by restoring the old behaviour.
- **Memory and load time:** the working set after the index load went from 921 to 1,017 MB
  (+96 MB), measured with `K32GetProcessMemoryInfo` on Windows because psutil isn't installed.
  That is under the 300 MB flag. The load time went from 4.0 to 5.6 s; the per-ticker builds take
  33–293 ms each.
- **Offline replay** (`var/retrieval_replay/bm25-per-ticker.json` against `phase2-base.json`):

  | Corpus / code | hit@5 (of 981) | Coverage (of 40) |
  |---|---|---|
  | Base (old corpus) | 549 | 37 |
  | Current corpus, before this change | 480 | 34 |
  | Current corpus, per-ticker BM25 | **587** | **33** |

  - Against the current corpus before this change: 119 parts gained and 12 lost.
  - Against the base: 22 parts lost. In all 22 the gold chunk is still in the fused pool, so they
    are lost at the rerank stage (9 at fusion, 13 at the cross-encoder). 14 of them were already
    lost before this change.
  - The `msft-three-segments-revenue-q3fy2026` and `msft-segment-revenue-comparison-q3fy2026`
    parts come back across most of their queries.
  - Coverage loses one question against the current corpus, `msft-rd-intensity-fy2025/revenue`,
    through the clamp effect above. The other three questions lost against the base were already
    lost.
  - The replay's diagnostic `bm25` ranks now use per-ticker statistics for ticker'd queries.
    Compare them with earlier replay files with that in mind.
- **Live spot-check** `20261009T013458Z` (gemini): 3/3 PASS on
  `msft-three-segments-revenue-q3fy2026`, `msft-segment-revenue-comparison-q3fy2026` and
  `msft-rd-intensity-fy2025`.
- **Pending: the full v1 gate**, on the committed tree after the next quota reset. Target: at
  least 46/48, with every drop classified. Its figures go in the eval commit body.
- The build 6 v2 baseline will run on per-ticker BM25.

## Related

- `docs/decisions/2026-10-08-phase2-ingest.md`: where the regression was found.
