# Table-chunk rescue in reranking (`retrieval.py`)

**Date:** 2026-08-19 (commit `4fb6e74`, "Rescue demoted table chunks in
reranking; root-cause the MSFT segment failure")

## Context

Root-caused `msft-segment-revenue-comparison-q3fy2026` (carried forward
from the 6-accumulated-findings round) via a dedicated `--verbose`
session. NOT the same bug as the NVDA segment question — the
invented-`segment`-parameter fix was still working correctly here too.
The real failure was downstream, in retrieval itself.

## Decision

The chunk with the real numbers entered the fused candidate pool at a
reasonable rank (#14 of ~40) but the cross-encoder reranker pushed it
DOWN to #17 — worse than pre-rerank, outside `top_n=5` — in favor of
near-duplicate MD&A boilerplate that echoes the question's segment names
more than a dense numeric table does. No structured-XBRL escape hatch
exists here (confirmed via `discover_tags.py`: MSFT has no
segment-revenue tag) — had to be fixed in retrieval, not sidestepped.
`_rescue_demoted_table_chunk()`: if the reranker's own top_n contains no
`contains_table` chunk at all, but one ranked in the top half of the
fused pool, swap it in for the reranker's weakest surviving pick.

## Why

Deliberately gated on the base retrievers' own pre-rerank confidence,
not on guessing the question is fact/metric-seeking — pattern-matching
question phrasing would repeat the same fragile-heuristic risk as the
already-dropped `period_labels.py` idea. Self-limiting by construction: a
table with no lexical/semantic match to a prose question won't rank in
the top half to begin with.

A second bug found while live-verifying the first fix: MSFT's 10-Qs also
carry a recurring "Microsoft Cloud" glossary table (zero `$` figures)
also flagged `contains_table=True`, which out-ranked the real
segment-revenue table in the fused pool and got picked by the rescue by
mistake. Added `_MIN_DOLLAR_FIGURES_FOR_TABLE_RESCUE = 5` as a cheap,
general filter distinguishing "a table with actual figures" from "a
table shaped like a table," with no business-specific hardcoding.

**But the question still FAILS**, for a new, different reason exposed
only once retrieval stopped masking it: the model consistently (4/4
runs) states the lower-revenue segment is highest despite the correct
figure being right there in its own correctly-cited answer text — a
comparison/reasoning error, not retrieval or citation. Left open,
reported rather than assumed-fixed.

## Files touched

`retrieval.py` (`_rescue_demoted_table_chunk`,
`_MIN_DOLLAR_FIGURES_FOR_TABLE_RESCUE`).

## Verification

8 new tests including the exact glossary-vs-financial-table regression
shape, 214/214 full suite. Live-verified 4/4 that the correct chunk is
now retrieved reliably. Full 27-question suite: 22/27, up from 21/27, no
regressions.

## Related

`docs/decisions/2026-08-13-hybrid-retrieval-and-reranker-fix.md` (the
earlier, different reranker-demotion bug),
`docs/decisions/2026-08-20-comparison-reasoning-model-capability-limit.md`
(root-causes the remaining comparison-reasoning error).
