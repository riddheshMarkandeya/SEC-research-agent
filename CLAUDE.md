# Development Workflow — SEC Research Agent (project-specific additions)

See `~/.claude/CLAUDE.md` for the general workflow (scope tiers, TDD, SE
principles, error handling, debugging discipline, documentation habits,
independent review, git-as-inspection-tool, UI guidelines) — read that
first. Originally agreed with the user on 2026-08-24 as this project's
own copy of that workflow; split 2026-09-12 into the generic file above
plus this one, which now covers only what's specific to this project,
layered on top of the generic rules. See `PROJECT_CONTEXT.md`'s
"Development workflow" section for the full narrative history of how
these rules came to be.

## This project's live-code TDD carve-out

The generic file's "live-only code" category (step 2) means, concretely,
in this repo:

- **SEC EDGAR HTTP calls** (`edgar_ingest.py`, `xbrl_facts.py`)
- **Chroma + embedding indexing/retrieval** (`index_chunks.py`,
  `retrieval.py`)
- **LLM round-trips through either backend** (`agent.py`'s tool-calling
  loop, `llm_backends.py`)

For each of these, write the manual repro/verification script under
`tests/manual/verify_*.py` first, confirm it reproduces the bug or
exercises the new behavior, then implement, then re-run it — same
red-green spirit as unit TDD, different tool.

No UI exists in this project today; if one is added, name its concrete
live-only surfaces here and apply the generic file's UI section (step 8)
in full before starting that work.

## This project's documentation system

The generic file's four-artifact template (step 6), named concretely
here:

- **`PROJECT_CONTEXT.md`** — the narrative changelog.
- **`docs/plans/YYYY-MM-DD-<slug>.md`** — saved plans.
- **`docs/reviews/YYYY-MM-DD-<slug>.md`** — saved review findings.
- **`BACKLOG.md`** — open items, tagged `**[type, priority, effort]**`
  per the generic file's convention (legend at `BACKLOG.md`'s own top).

## Spot-check evals and live verification beyond TDD

Full TDD coverage is necessary but not sufficient for any change to
shared extraction/verification code that live model output flows
through — this is the generic file's step 2 rule made concrete with a
real incident, not a hypothetical: the 2026-09-12 negative-number fix to
`numeric_utils.py` had complete TDD coverage (14 new unit tests, all
passing, full suite green at 601) before a single live `eval_harness.py`
run surfaced two further real bugs no unit test had anticipated — a
spaced-hyphen subtraction expression and a Unicode minus sign (U+2212),
both only producible by a real model choosing its own notation in free
text, not by anything a test author would think to construct by hand.

**Rule**: after any change to `numeric_utils.py`, `agent.py`'s citation-
verification functions (`verify_claims`, `collect_citation_warnings`,
`_verify_one_claim`, and friends), or `retrieval.py`'s ranking/rerank
logic, run a live spot-check *in addition to* the unit-test/manual-
verification-script step already required — at minimum a targeted
`eval_harness.py --backend gemini --ids <affected-question-id(s)>`
re-run of whatever eval question(s) exercise the changed path; the full
41-question baseline (`eval_harness.py --backend gemini`, no `--ids`
filter) when the change is broad, touches multiple of the modules above,
or before considering a session's work fully done. A green test suite
alone is not sufficient evidence of correctness for this class of change.

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
`PROJECT_CONTEXT.md` changelog entry (a new addendum to the section for
the change that introduced it, naming the real failure mode and the live
run that found it) once fixed; a `BACKLOG.md` item, tagged per the usual
convention, if not fixed in the same session.

**An eval-discovered regression is exactly the "non-trivial,
multi-location bug" case `~/.claude/CLAUDE.md`'s debugging-discipline
rule already covers — don't patch it reactively.** When a live eval run
(baseline or targeted spot-check) surfaces a regression, log it to
`BACKLOG.md` with a priority tag first, then switch to plan mode to
investigate the real root cause and design the fix, implement it, and
re-run the same eval question(s) to confirm before considering it
resolved — repeating the plan → implement → re-run cycle if the first
fix doesn't fully close it. This codebase's own history (2026-09-13) is
the concrete reason this is called out again at the project level, not
left to the global rule alone: a citation-gate regression here can look
fixed (the originally-failing question passes) while quietly reopening
a different, worse gap, so "the eval question now passes" is never
sufficient confirmation on its own — the plan-and-review cycle is what
actually catches that, not the re-run by itself.
