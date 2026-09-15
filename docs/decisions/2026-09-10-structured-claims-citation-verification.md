# Structured-claims citation verification replaces the prose heuristic

**Date:** 2026-09-10/11

## Context

The measurement campaign (see
`docs/decisions/2026-09-10-citation-gate-measurement-instrumentation.md`)
found the prose-parsing citation heuristic was wrong 100% of the time it
fired. Rather than patch those bugs one at a time, this session replaced
the whole mechanism. Full design:
`docs/plans/2026-09-10-structured-claims-citation-verification.md`.
Review: `docs/reviews/2026-09-10-structured-claims-citation-verification.md`.

## Decision

New `submit_answer` tool with a `claims` array — one entry per numeric
fact, each with value, unit, citation index, and a verbatim supporting
quote. `verify_claims()` checks quote grounding, value attribution, and
a coverage cross-check that every number in `answer_text` maps to some
claim. The old prose pipeline is completely untouched, kept as a
universal fallback (Ollama's only path; Gemini's occasional fallback).
Two decisions confirmed with the user before implementation: keep
hard-gating rather than downgrade to warn-only; defer the model-based-
veto backlog item since all 4 measured false positives die structurally
under the new design.

## Why

See the plan/review docs for the full mechanical detail (Gemini's forced
`ANY` + `allowed_function_names` follow-up turn; the loop restructuring
around `_partition_submit_call()`). Three live bugs found and fixed
during implementation before either formal review pass: a bare XBRL
number quote wrongly rejected as too short; a rule-9 wording
contradiction with rule 3 that caused a live regression; a comma-
separated multi-source bracket surviving marker-stripping untouched.

## Files touched

`agent.py` (`SUBMIT_TOOL_SCHEMA`, `verify_claims`, `_partition_submit_call`),
`llm_backends.py` (`force_tool` plumbing), `eval_harness.py`.

## Verification

**Re-measurement**: baseline 33/41 (materially different, harder-graded
failure set), 0/41 gate fires. Combined with stress set: 0/45 gate
fires, down from the pre-redesign measurement's 6/45, all 6 wrong. All
three of the plan's named acceptance-test targets confirmed passing.
Full suite 557 → 558. Two-pass review completed with 3 real findings,
all fixed.

## Related

`docs/decisions/2026-09-10-citation-gate-measurement-instrumentation.md`,
`docs/plans/2026-09-10-structured-claims-citation-verification.md`,
`docs/reviews/2026-09-10-structured-claims-citation-verification.md`,
`docs/decisions/2026-09-11-calculate-tool-and-stress-questions.md` (closes
a structural gap this redesign's rule 9 left open).
