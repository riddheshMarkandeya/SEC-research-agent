# Review: Comment audit Round 6 (self + fresh subagent)

Plan: `docs/plans/2026-09-15-comment-audit-round6.md`. Pointer-fixed
`test_llm_backends.py`, `test_xbrl_facts.py`, `test_formulas.py`,
`test_eval_harness.py`. Baseline: 634 passed.

## Pass 1 — correctness and compliance (self, medium effort)

Every pointer added was verified by reading the target
`docs/decisions/*.md` file first, including cross-checking
`llm_backends.py`'s own source docstrings for the `_to_gemini_tool`/
`_strip_additional_properties` pointer to keep the test comment
consistent with the code it tests. Full diff read plus the
programmatic tokenize-based check (reused from Rounds 2-5) confirmed
byte-identical code across all 4 files. Full pytest suite: 634 passed.
No findings.

## Pass 2 — architecture/design/refactor (fresh subagent, no memory of the implementation session)

1. **Pointer correctness — PASS.** Verified all 20 distinct
   `docs/decisions/*.md` citations across the diff. Notably confirmed
   via `git show 5e828ae` that `2026-09-09-schema-driven-arg-validation.md`
   is the literal causal origin of `llm_backends.py`'s Gemini
   `additionalProperties`-stripping bug (the same commit added
   `additionalProperties: false` to every schema and introduced the
   Gemini-side strip fix), not just a generically-plausible same-topic
   file. All other citations (`2026-09-15-xbrl-tag-selection-methodology.md`,
   `2026-08-28-ratio-definitions-table-driven-registry.md` ×2,
   `2026-09-06-full-codebase-review.md` ×2, and 16 more) confirmed
   accurate.
2. **Information loss — PASS.** The three flagged load-bearing
   reasoning threads (the ReadTimeout retry-math in
   `test_llm_backends.py`, the `as_percent` latent-regression warning
   in `test_formulas.py`, the calendarization rationale in
   `test_xbrl_facts.py`) all survived intact — only the incident-
   narration wrapper around each was trimmed.
3. **Dead references — PASS.** Zero remaining `PROJECT_CONTEXT.md`,
   `docs/plans/`, "Week 7", "found in code review", or "found live"
   occurrences across all 4 files.
4. **`test_eval_harness.py`'s docstring gap — confirmed reasonable.**
   Independently searched for any decision file covering "where
   manual eval runs are documented" — none exists. Rephrasing to drop
   the dead pointer rather than inventing a tangential citation was
   the right call, not a cop-out.
5. **Scope discipline — PASS.** Only the 4 named files touched
   repo-wide; every changed line is a comment or the module-level
   docstring in `test_eval_harness.py` — no assertions or fixture
   logic touched.

## Outcome

No findings from either pass. Clean round — no fixes needed, no
second review round required.
