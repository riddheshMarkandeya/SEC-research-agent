---
paths:
  - "numeric_utils.py"
  - "agent.py"
  - "retrieval.py"
  - "eval_harness.py"
  - "chunk_documents.py"
---

# Spot-check evals and live verification beyond TDD

Full TDD coverage is necessary but not sufficient for any change to
shared extraction/verification code that live model output flows
through — this is the `tdd-live-code-carveout` skill's rule made
concrete with a real incident, not a hypothetical: the 2026-09-12
negative-number fix to `numeric_utils.py` had complete TDD coverage (14
new unit tests, all passing, full suite green at 601) before a single
live `eval_harness.py` run surfaced two further real bugs no unit test
had anticipated — a spaced-hyphen subtraction expression and a Unicode
minus sign (U+2212), both only producible by a real model choosing its
own notation in free text, not by anything a test author would think to
construct by hand.

**Rule**: after any change to `numeric_utils.py`, `agent.py`'s citation-
verification functions (`verify_claims`, `collect_citation_warnings`,
`_verify_one_claim`, and friends), `retrieval.py`'s ranking/rerank
logic, `eval_harness.py`'s `grade_judged`/`JUDGE_SYSTEM_PROMPT` (the
LLM-as-judge grading itself — a prompt-wording change here can only be
confirmed correct by a real judge call, same as any other prompt
change; see the 2026-09-17 judge hypothetical-date fix), or
`chunk_documents.py`'s chunking logic (a change here reshapes the
entire indexed corpus that every citation-grounding check reads from —
see the 2026-09-17 orphaned-table-overlap fix, where full unit-test
coverage confirmed the fix's logic but only a direct real-corpus
inspection confirmed it actually repaired a live filing's chunk), run a
live
spot-check *in addition to* the unit-test/manual-verification-script
step already required — at minimum a targeted
`eval_harness.py --backend gemini --ids <affected-question-id(s)>`
re-run of whatever eval question(s) exercise the changed path; the full
41-question baseline (`eval_harness.py --backend gemini`, no `--ids`
filter) when the change is broad, touches multiple of the modules above,
or before considering a session's work fully done. A green test suite
alone is not sufficient evidence of correctness for this class of change.

**Keep the `paths:` list above current the same way `BACKLOG.md` keeps
itself current** (see this project's own `CLAUDE.md`): if a live
spot-check or baseline run ever catches a regression in a file not
already listed there, add it in the same step, not as a deferred
follow-up — mirroring exactly how `numeric_utils.py` earned its own
place here in the first place.

## Gemini free-tier quota awareness

The free tier caps at 500 requests/day (`RESOURCE_EXHAUSTED` past that).
This has been hit twice in one week from over-running full baselines
during active debugging. Prefer targeted `--ids` re-runs to confirm one
specific fix live; reserve full 41-question runs for a genuine final
confirmation, not exploratory checks while still iterating on a fix. If
a full run partway-fails with `RESOURCE_EXHAUSTED` errors, that report is
invalid for any before/after comparison — say so explicitly, keep the
file for the audit trail, and do not treat any row past the first error
as a real result.

## Regression notes

When a live spot-check (the rule above) or any other live verification
finds a regression that unit tests didn't catch, record it explicitly —
don't let a live-only-discovered bug go unrecorded just because it fell
outside the original TDD loop that produced the change. At minimum: a
new `docs/decisions/YYYY-MM-DD-<slug>.md` file (naming the real failure
mode, the live run that found it, and cross-linking back via `Related`
to the decision file for the change that introduced the regression —
never edited into that original file, which stays an immutable record)
once fixed; a `BACKLOG.md` item, tagged per the usual convention, if not
fixed in the same session.

**An eval-discovered regression is exactly the "non-trivial,
multi-location bug" case the `debugging-discipline` skill already
covers — don't patch it reactively.** When a live eval run (baseline or
targeted spot-check) surfaces a regression, log it to `BACKLOG.md` with
a priority tag first, then switch to plan mode to investigate the real
root cause and design the fix, implement it, and re-run the same eval
question(s) to confirm before considering it resolved — repeating the
plan → implement → re-run cycle if the first fix doesn't fully close it.
This codebase's own history (2026-09-13) is the concrete reason this is
called out again at the project level, not left to the global skill
alone: a citation-gate regression here can look fixed (the
originally-failing question passes) while quietly reopening a different,
worse gap, so "the eval question now passes" is never sufficient
confirmation on its own — the plan-and-review cycle is what actually
catches that, not the re-run by itself.
