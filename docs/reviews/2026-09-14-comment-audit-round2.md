# Review: Comment audit Round 2 (self + fresh subagent)

Plan: `docs/plans/2026-09-14-comment-audit-round2.md`.

## Pass 1 — correctness and compliance (self, medium effort)

Every pointer added was verified by reading the target
`docs/decisions/*.md` file first. The new
`docs/decisions/2026-08-20-swappable-llm-backend.md` file was written
from a careful read of both plan docs it synthesizes. Full diff read
plus a programmatic check (stripped comments/docstrings from both HEAD
and working-tree versions of all 10 files via Python's `tokenize`
module, diffed the remainder) confirmed byte-identical code. Full
pytest suite: 634 passed. No findings.

## Pass 2 — architecture/design/refactor (fresh subagent, no memory of the implementation session)

1. **New decision file quality — PASS, high fidelity.** Every material
   claim in `docs/decisions/2026-08-20-swappable-llm-backend.md`
   checked out against both plan docs and a linked prior decision; test
   counts and the circular-import fix's attribution both verified
   accurate. Follows the project's decision-file skeleton exactly.
2. **Pointer correctness — PASS.** Sampled 15 of ~19 distinct
   `docs/decisions/...` targets across the 10 files; every one covers
   what its comment claims.
3. **Information loss — PASS.** `table_grounding.py`'s three-check
   algorithmic reasoning survived intact (the scattered-digit-vs-value
   distinction, the cherry-pick-vs-wholesale-row logic, the
   tolerance-asymmetry rationale) — only the "confirmed live
   2026-09-13"/"found live" narration wrapper was stripped, not the
   underlying constraint.
4. **Consistency — one real finding.** Three inline comments
   (`chunk_documents.py:45`, `chunk_documents.py:211`,
   `edgar_ingest.py:120`) still referenced "Week 1"/"Week 2" by phase
   label when cross-referencing the other module, inconsistent with
   those same two files' own module docstrings, which had already
   dropped week-phasing a few lines away. Same "fixed some narration,
   left a sibling instance bare in the same file" pattern Round 1's
   review flagged, this time for stale terminology rather than incident
   narration.
5. **Factual-accuracy corrections — PASS.** `eval_harness.py`'s stale
   "8 seed questions" claim was removed entirely (not replaced with
   another number that would just go stale again) — correct fix,
   matching Round 1's `period_labels.py` precedent.
6. **Scope discipline — PASS.** Only the 10 named files plus the new
   decision file changed; every diff hunk touches only docstring/comment
   text.

## Fixes applied

- Repointed all 3 stale "Week 1"/"Week 2" cross-references to name the
  actual module (`edgar_ingest.py`/`chunk_documents.py`) instead of a
  phase label.
- Re-ran the programmatic comment-only-diff check and the full pytest
  suite after applying fixes: still comment-only, still 634 passed.

## Outcome

One real, actionable finding (#4), fixed the same pass. Findings #1,
#2, #3, #5, #6 confirmed clean, no action needed. No second review
round needed — the fix was small, mechanical, and verified immediately.
