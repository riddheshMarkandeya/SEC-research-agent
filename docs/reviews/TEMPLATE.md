# Review: [what was reviewed — the change/diff/module name]

> Copy this file to `docs/reviews/YYYY-MM-DD-<slug>.md` to start a new
> review. `TEMPLATE.md` itself is excluded from `PROJECT_INDEX.md`'s
> index and from file-count verification checks.
>
> This shape fits a review of one finished diff/change (the common
> case — CLAUDE.md step 7's two-pass review). A full-codebase or
> multi-finding batch audit not paired to a single plan may instead open
> with a **Scope** / **Method** / **Status** block and group findings by
> priority tier rather than by pass — use judgment; the Pass 1/Pass
> 2/outcome spine below is still the default.

Plan: `docs/plans/YYYY-MM-DD-<slug>.md` (omit this line if there's no
paired plan). [One-line summary of what the change does, and the test
suite count before this diff.]

## Pass 1 — correctness and CLAUDE.md compliance (self, or `/code-review`; [effort level])

[Findings from a fast, targeted correctness/compliance pass over the
diff. Tag each one `[Fixed]`, `[Verified, no fix needed]`, or
`[Deferred — filed to BACKLOG.md]` with a one-line reason. Scale effort
to the change's size — low for a one-line fix, medium/high for anything
Substantial-sized.]

## Pass 2 — architecture, design, performance, refactoring (fresh subagent, no memory of the implementation session)

[Findings from an independent subagent given the diff cold, with enough
context to judge it on its own merits — does the design fit the
codebase, is there a simpler/more idiomatic approach, real performance
concerns, would it read better refactored. Tag each finding the same way
as Pass 1 (severity + fix status). Note explicitly any attack/edge case
the subagent tried and disproved, not just what it found wrong.]

## Live verification (if applicable)

[A live spot-check or eval re-run confirming the fix works end-to-end
against the real model/data, not just against unit tests — e.g. a
targeted `eval_harness.py --backend gemini --ids ...` run, or a
`tests/manual/verify_*.py` re-run. Record before/after numbers. Omit
only when the change touches no live-code surface at all (see this
project's CLAUDE.md live-code carve-out).]

## Additional rounds (if applicable)

[Extra review/fix/re-verify cycles beyond Pass 1 and Pass 2 — most often
a live run surfacing something neither static pass could have exercised
(a real model choosing its own notation/wording, a corpus-scale
regression). Number sequentially (Round 3, Round 4, ...) and say
explicitly what each one caught that the previous round couldn't. Per
CLAUDE.md's review-loop cap: stop and bring it to the user if two rounds
in a row surface nothing new, or the same issue twice with no clean fix.]

## Outcome

[Summary: what shipped, what's still open and filed to `BACKLOG.md`
(with its tag), the final test-suite count, and whether the review loop
closed clean (no new findings) or hit the cap.]
