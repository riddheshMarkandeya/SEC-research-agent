# Review: [what was reviewed: the change, diff or module name]

> Copy this file to `docs/reviews/YYYY-MM-DD-<slug>.md` to start a new
> review. `TEMPLATE.md` itself is excluded from `PROJECT_INDEX.md`'s
> index and from file-count verification checks.
>
> A review file exists only for Substantial work, or when a finding is
> deferred or disputed. Otherwise the plan's `## Review log` and the
> commit body's review line are the record (see `independent-review-pass`).
> A full-codebase or batch audit that isn't paired to one plan may open
> with a **Scope** / **Method** / **Status** block instead, and group
> findings by priority. Use judgment.

Plan: `docs/plans/YYYY-MM-DD-<slug>.md` (omit this line if there's no
paired plan). [A one-line summary of what the change does, the test suite
count before this diff, and the review depth the diff classified as:
Trivial, Standard or Substantial passes.]

## Round 1

Passes: [the passes run, with levels and models: e.g. `/code-review`
medium, `arch-reviewer` (sonnet), `security-reviewer`, `/simplify`].

1. **[Severity]** ([pass]): [the finding]. `[Fixed]`,
   `[Verified, no fix needed]`, `[Deferred → BACKLOG]` or `[Disputed]`,
   each with a one-line reason. For a pass that finds nothing, say so
   and note any attack or edge case that was tried and disproved.

## Round 2+ (if applicable)

Delta: [the snapshot the fix was diffed against]. Passes: [the pass(es)
whose findings were fixed, plus `/code-review low`, plus
`security-reviewer` if the delta changed non-test executable code; or
"full round" if the fix touched files outside round 1's diff].

[Findings, in the same format as round 1.]

## Live verification (if applicable)

[A live spot-check or eval re-run showing the fix works end to end
against the real model and data, e.g. `eval_harness.py --ids ...` or a
`tests/manual/verify_*.py` re-run. Record the before and after numbers.
Omit this section only when the change touches no live-code surface. A
live finding after the review closed starts a new round.]

## Outcome

[What shipped; what's still open in `BACKLOG.md`, with its tag; the final
test-suite count; and whether the review closed clean or escalated (the
same issue twice goes to the user).]
