# Comment Overhaul — Round 6 (tests/, batch 2: 4 large-but-mechanical unit test files)

## Context

Round 5 pointer-fixed 5 small `tests/` files. `BACKLOG.md`'s Round 6
item bundled 15 more files across 3 themed sub-groups. Consistent with
the pacing every prior round has used, this round covers only
sub-group (a): 4 large unit-test files confirmed "mostly self-citing,
routine pointer-fix" (`test_llm_backends.py`, `test_xbrl_facts.py`,
`test_formulas.py`, `test_eval_harness.py`). Sub-groups (b) (7
`tests/manual/verify_*.py` scripts) and (c) (4 files needing
non-mechanical editing) are logged as Round 6b/6c follow-ups.

All 4 files were read in full during planning, and every candidate
decision-file mapping was verified by reading the target file directly.

## Decision / Design

Pointer-fixed narration across all 4 files — dead `PROJECT_CONTEXT.md`
references, `docs/plans/*.md`-only citations repointed to their paired
`docs/decisions/*.md` files, and "found in code review"/"found live"
date-tagged narration repointed to the decision file that actually
covers each incident. One genuine gap found and handled without a new
decision file: `test_eval_harness.py`'s `answer_model`-tracking
comment had no matching decision file (small, undocumented, but not
narrative-heavy enough to warrant a dedicated EXTRACT file) — trimmed
the "Found live (date)" decoration only, kept the self-contained WHY.

Several blocks were deliberately kept mostly intact because they
explain load-bearing "why" reasoning, not just incident history:
`test_llm_backends.py`'s ReadTimeout-should-not-retry math (60-70s/
240s/12-minute-hang), `test_formulas.py`'s "currently latent... would
otherwise silently break eval grading" `as_percent` warning, and
`test_xbrl_facts.py`'s calendarization rationale for instant vs.
duration metrics — only the incident-narrative wrapper around each was
trimmed.

`test_eval_harness.py`'s module docstring dropped its dead
`PROJECT_CONTEXT.md` reference without a replacement pointer — no
single decision file covers "where manual runs are documented" as a
concept, so the sentence was rephrased instead of citing a
tangentially-related file just to have a pointer.

## Files and steps

1. Read each file in full; confirm each candidate mapping by reading
   the target decision file directly.
2. Pointer-fix confirmed-mapped narration; repoint dead/plan-only
   citations.
3. Leave fixture-provenance comments and genuine non-narrative WHY
   untouched.
4. Re-scan each file for missed narration.
5. Verify, then update `PROJECT_INDEX.md` and `BACKLOG.md`.
6. Write this plan, the paired review, and the round's decision file.

## Testing and verification

- Full `git diff` read confirming comment/docstring-only changes.
- The programmatic tokenize-based check (reused from Rounds 2-5),
  confirming byte-identical code across all 4 files.
- Full pytest suite: 634 passed (matches baseline exactly).
- Full two-pass review (step 7): self-check plus a freshly-spawned
  subagent.

## Related

`docs/decisions/2026-09-15-comment-audit-round6.md`,
`docs/reviews/2026-09-15-comment-audit-round6.md`,
`docs/decisions/2026-09-15-comment-audit-round5.md` (the round this
follows up on). Follow-up work (Round 6b: the 7 manual verify scripts;
Round 6c: 4 dense/interlinked test files; Rounds 7-10+: `test_tracing.py`,
`test_numeric_utils.py`, `test_table_grounding.py`, `test_agent.py`)
logged in `BACKLOG.md`.
