# Comment audit Round 2: pointer-fixed 10 more main-source files

**Date:** 2026-09-14

## Context

Round 1 pointer-fixed 6 small, low-risk files. `BACKLOG.md` logged the
remaining 13 main-source files plus a full `tests/` pass as follow-ups.
This round covers 10 of those 13 — the ones confirmed
`ALREADY-DOCUMENTED` in the original inventory. `agent.py`,
`xbrl_facts.py`, and `numeric_utils.py` are deferred to Round 3 (they
need dedicated attention, not a routine pointer-fix batch).

## Decision

Pointer-fixed `llm_backends.py`, `retrieval.py`, `index_chunks.py`,
`eval_harness.py`, `table_grounding.py`, `analyze_citation_gate.py`,
`chunk_documents.py`, `edgar_ingest.py`, `discover_tags.py`,
`query_chunks.py` — same process as Round 1, every pointer verified by
reading the target decision file first. Two additional fixes beyond
routine pointer-replacement:

1. **A missing decision file, found and filled**: `llm_backends.py`'s
   own creation had no `docs/decisions/` entry at all, only two plan
   docs. Wrote `docs/decisions/2026-08-20-swappable-llm-backend.md` as a
   synthesis of both before pointer-fixing the module docstring to it.
2. **A stale factual claim, corrected**: `eval_harness.py`'s module
   docstring described itself as scaffolding with "8 seed questions,"
   long since untrue — corrected alongside the narration trim, same
   class of fix as Round 1's `period_labels.py` correction.

`table_grounding.py` (the largest single file in this round) had its
very dense, technically-detailed docstrings trimmed carefully:
"confirmed live 2026-09-13"-style narration tags were removed, but the
underlying algorithmic reasoning (why 3 separate checks are needed, why
tolerances differ between them) was kept intact rather than deleted
wholesale, since that reasoning is load-bearing for understanding
genuinely complex verification logic, not just historical color.

## Why

See `docs/plans/2026-09-14-comment-audit-round2.md` for the full file
selection reasoning and per-block disposition checklist.

## Files touched

The 10 files listed above (comments/docstrings only — zero executable
code lines changed, confirmed both by a full diff read and a
programmatic tokenize-based comparison). `docs/decisions/2026-08-20-swappable-llm-backend.md`
(new). `BACKLOG.md` (narrowed follow-up scope), `PROJECT_INDEX.md` (new
index lines).

## Verification

Programmatic check: stripped comments/docstrings from both HEAD and
working-tree versions of all 10 files via Python's `tokenize` module,
diffed the remainder — byte-identical, confirming no code changed. Full
pytest suite: 634 passed (same as baseline). Two-pass review: self-check
plus a fresh subagent architecture review — see
`docs/reviews/2026-09-14-comment-audit-round2.md`.

## Related

`docs/plans/2026-09-14-comment-audit-round2.md`,
`docs/reviews/2026-09-14-comment-audit-round2.md`,
`docs/decisions/2026-09-14-comment-audit-round1.md` (the round this
follows up on). Follow-up work (`agent.py`, `xbrl_facts.py`,
`numeric_utils.py`, and the full `tests/` pass) logged in `BACKLOG.md`.
