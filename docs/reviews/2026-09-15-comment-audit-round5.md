# Review: Comment audit Round 5 (self + fresh subagent)

Plan: `docs/plans/2026-09-15-comment-audit-round5.md`. Pointer-fixed 5
of 6 candidate small `tests/` files (`test_discover_tags.py` needed no
changes). Baseline: 634 passed.

## Pass 1 — correctness and compliance (self, low effort)

Every pointer added was verified by reading the target
`docs/decisions/*.md` file first. Full diff read plus the programmatic
tokenize-based check (reused from Rounds 2-4) confirmed byte-identical
code across all 5 edited files. Full pytest suite: 634 passed. No
findings.

## Pass 2 — architecture/design/refactor (fresh subagent, no memory of the implementation session)

1. **Wrong pointer target — one real finding.**
   `test_analyze_citation_gate.py`'s legacy-row comment
   (`test_classify_row_unknown_pre_instrumentation_for_a_legacy_row_missing_gate_fields`)
   pointed at `docs/decisions/2026-09-10-structured-claims-citation-verification.md`,
   but the 4 keys the legacy row lacks
   (`withheld_answer`/`gate_withheld_would_have_passed`/
   `gate_withheld_detail`/`citation_warning_details`) and
   `analyze_citation_gate.py` itself were both introduced by the
   earlier `docs/decisions/2026-09-10-citation-gate-measurement-instrumentation.md`
   — confirmed via `git log --follow --diff-filter=A --
   analyze_citation_gate.py`, which traces its creation to that
   decision's own commit, and that file's "Files touched" section
   explicitly lists `analyze_citation_gate.py (new)`. The structured-
   claims file came later and covers a different thing (the 5 new
   `CitationWarning` check values) — which is what this same test
   file's *other*, correctly-targeted pointer 70 lines below already
   cites. **[Fixed]** same pass: repointed to the measurement-
   instrumentation decision file.
2. **Everything else — PASS.** All other 5 pointers verified correct
   against their target files' own "Files touched"/Context sections.
   The `KEEP-AS-IS` comments in `test_period_labels.py` (real 10-Q/10-K
   quotes grounding fiscal-year/quarter expectations) and
   `test_analyze_citation_gate.py` ("confirming test for that design
   claim, not a change to analyze_citation_gate.py itself") both still
   read as legitimate terse documentation, not leftover narration. No
   dangling `PROJECT_CONTEXT.md` or `docs/plans/` references in any of
   the 6 files. Scope confirmed clean: exactly the 5 named files show a
   diff, every hunk comment/docstring-only.

## Fixes applied

- Repointed `test_analyze_citation_gate.py`'s legacy-row comment from
  the structured-claims decision file to the citation-gate-measurement-
  instrumentation decision file, which actually introduced the 4 keys
  and the module under test.
- Re-ran the programmatic comment-only-diff check and the full pytest
  suite after applying the fix: still comment-only, still 634 passed.

## Outcome

One real finding, fixed the same pass. No second review round needed
— the fix was a one-line pointer correction, verified immediately.
