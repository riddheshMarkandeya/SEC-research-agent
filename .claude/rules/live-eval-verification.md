---
paths:
  - "src/sec_agent/verification/numeric_utils.py"
  - "src/sec_agent/agent/**"
  - "src/sec_agent/retrieval/retrieval.py"
  - "src/sec_agent/eval/eval_harness.py"
  - "src/sec_agent/retrieval/chunk_documents.py"
  - "src/sec_agent/prompts/**"
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

**Rule**: after any change to `numeric_utils.py`, `citations.py`'s citation-
verification functions (`verify_claims`, `_verify_one_claim`,
`value_is_citation_verified`, and friends), `retrieval.py`'s ranking/rerank
logic, `eval_harness.py`'s `grade_judged` and the judge prompts it
sends (`prompts/judge.py`; the LLM-as-judge grading itself — a
prompt-wording change here can only be confirmed correct by a real judge
call, same as any other prompt change; see the 2026-09-17 judge
hypothetical-date fix), any other text in `prompts/` (every string the
agent model reads: system prompt, tool schemas, tool-result, warning and
retry messages — a wording change there changes model behaviour with no
code change, and only a live run confirms its effect), or
`chunk_documents.py`'s chunking logic (a change here reshapes the
entire indexed corpus that every citation-grounding check reads from —
see the 2026-09-17 orphaned-table-overlap fix, where full unit-test
coverage confirmed the fix's logic but only a direct real-corpus
inspection confirmed it actually repaired a live filing's chunk), run a
live
spot-check *in addition to* the unit-test/manual-verification-script
step already required — at minimum a targeted
`python -m sec_agent.eval.eval_harness --backend gemini --ids <affected-question-id(s)>`
re-run of whatever eval question(s) exercise the changed path; the full
48-question baseline (`python -m sec_agent.eval.eval_harness --backend gemini`, no `--ids`
filter) when the change is broad, touches multiple of the modules above,
or before considering a session's work fully done. A green test suite
alone is not sufficient evidence of correctness for this class of change.

**Keep the `paths:` list above current the same way `BACKLOG.md` keeps
itself current** (see this project's own `CLAUDE.md`): if a live
spot-check or baseline run ever catches a regression in a file not
already listed there, add it in the same step, not as a deferred
follow-up — mirroring exactly how `numeric_utils.py` earned its own
place here in the first place.

## Prompt changes

Every eval report records `provenance`: git SHA, dirty state, the
`prompts/` fingerprint, whether the model-input snapshot was verified,
and the `.env` model settings. `compare_prompt_versions.py` compares
runs by that fingerprint. For any change to what a model reads:

- **One commit per change.** A `git revert` of that commit is then the
  undo, and a panel comparison attributes a pass-rate change to exactly
  one edit.
- **Regenerate the model-input snapshot in the same commit.** Any change
  that alters what a model receives, whether a `prompts/` constant or the
  logic that picks, fills or converts it (the `agent/` package, `llm_backends.py`,
  `eval_harness.grade_judged`, `mcp_server.py`), fails
  `tests/prompts/test_model_input_snapshot.py`. Read the diff it prints, then run
  `UPDATE_SNAPSHOT=1 pytest tests/prompts/test_model_input_snapshot.py` (PowerShell:
  `$env:UPDATE_SNAPSHOT=1; pytest tests/prompts/test_model_input_snapshot.py;
  Remove-Item Env:UPDATE_SNAPSHOT`). The
  fingerprint hashes the snapshot, so this is what gives the change a
  new fingerprint. When a new code path starts sending model text, add a
  scenario for it there, or the snapshot can't see it. Editing
  `companies.json` also changes the fingerprint, which is intended: the
  model sees different text.
- **Run the panel protocol, not a single question.** The panel, the
  screen → replicate → attribute decision rule and the thresholds are in
  `docs/plans/2026-09-24-prompt-audit-roadmap.md` ("Decision rule").
  Screen with `python -m sec_agent.devtools.compare_prompt_versions` (fingerprint mode).
  For the replicate and attribute steps, always use explicit mode
  (`--base-files` / `--candidate-files`): a revert restores the base
  fingerprint, so fingerprint mode would pool reverted runs with the
  original base.
- **Only clean runs count.** Evaluate on a committed tree. The compare
  script excludes reports whose tree was dirty or whose snapshot wasn't
  verified, unless `--include-dirty` is given.

## Gemini free-tier quota awareness

The free tier caps at 500 requests/day per model (`RESOURCE_EXHAUSTED` past
that); the day resets at midnight Pacific time.
This has been hit twice in one week from over-running full baselines
during active debugging. Prefer targeted `--ids` re-runs to confirm one
specific fix live; reserve full 48-question runs for a genuine final
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
to the decision file, or the commit SHA, of the change that introduced
the regression — never edited into that original file, which stays an
immutable record)
once fixed; a `BACKLOG.md` item, tagged per the usual convention, if not
fixed in the same session. This decision file is exempt from the ADR gate
in `documentation-backlog-hygiene`: it's always written.

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
