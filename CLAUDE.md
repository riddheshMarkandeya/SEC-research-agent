# Development Workflow

These are binding instructions for all work in this repo — they override
default behavior. Agreed with the user on 2026-08-24; see
`PROJECT_CONTEXT.md`'s "Development workflow" section for the narrative
version and the rest of the project's decision history.

**Scope tiers — apply the right amount of process, not the same amount
every time.** Before starting any task, classify it, and use the table
below to see what's required. When genuinely unsure which tier applies,
default to Standard, or ask.

- **Trivial**: typo/wording fix, config value change, formatting,
  `.gitignore` entry, comment fix, dependency bump with no code change.
- **Standard**: a bug fix or small feature in an existing module — the
  usual day-to-day change.
- **Substantial**: a new module, a new tool/capability, an architecture
  or design decision, anything with more than one reasonable approach.

| Step | Trivial | Standard | Substantial |
|---|---|---|---|
| 1. Design & approval | skip | skip unless there's a real fork in approach | required, before writing code |
| 2. TDD | skip | required (see carve-out below) | required (see carve-out below) |
| 3. SE principles | apply, don't refactor surroundings | apply | apply |
| 4. Debugging discipline | skip ceremony if cause is obvious | required once cause isn't obvious | required |
| 5. Documentation | usually skip | one entry, proportional to size | full `###` write-up |
| 6. Independent review | self-check the diff | self-check; `/code-review` if it feels risky | `/code-review` (medium/high) required |

## 1. Design before building

For Substantial work: write a short spec (problem, constraints,
proposed approach), present real alternatives with tradeoffs when more
than one exists, and get explicit user approval on the plan before
implementing. This is what already happened for the swappable-backend
work (design spec → implementation plan → build) — keep doing that for
work of that size.

For Standard work, a one- or two-line statement of approach before
diving in is enough — no formal options-and-approval step unless a real
fork in the road shows up mid-task, in which case stop and ask.

Trivial work skips this entirely.

## 2. TDD — with the existing live-code carve-out

Write the test before the implementation. This project already has a
deliberate, hard-won scope rule for *what* gets a unit test — keep
following it, don't override it with a blanket "test everything":

- **Pure/deterministic logic** (string/data transforms, formatting,
  grading logic, anything with no network/model/filesystem dependency):
  full TDD, red-green-refactor. Write the failing test, confirm it fails
  for the right reason, then implement.
- **Live-only code** (EDGAR HTTP calls, Chroma + embedding indexing,
  LLM round-trips): mocking these tests the mock, not the code — so
  instead, write the manual repro/verification script or command
  *first*, confirm it reproduces the bug or exercises the new behavior,
  then implement, then re-run it to confirm. Same red-green spirit,
  different tool. Document what was run and what it showed (see
  Documentation below) — a manual verification that isn't written down
  didn't happen as far as the next session is concerned.
- Every bug fix gets a regression test/repro, no exceptions at Standard
  tier or above — this is the existing pre-commit-hook-enforced rule
  (`git commit` runs the suite and refuses to commit on failure) and
  doesn't change.

## 3. Software engineering principles

DRY, YAGNI, KISS, clean code, single-responsibility functions/modules —
apply throughout. **SOLID is treated flexibly**: this codebase is mostly
plain functions and modules (NamedTuples, not class hierarchies), so
apply the *spirit* of single-responsibility/separation-of-concerns
rather than forcing formal OOP SOLID patterns where they don't fit the
existing style.

Caveat that matters in practice: a Standard-tier bug fix doesn't need
the surrounding code refactored, and a one-shot script doesn't need a
speculative abstraction for hypothetical future reuse. Don't let "best
practices" become an excuse to expand the diff beyond what the task
needs — this is already this project's stated design principle
(YAGNI on graph DB / HNSW tuning until a real question demands it is
the model to follow).

## 4. Debugging discipline

When the cause isn't already obvious: understand the problem before
acting, reproduce with the *simplest* possible failing case first (not
the full real scenario), isolate variables one at a time (this project's
own pattern: `git stash` a suspected change in/out, same input, compare
— see the rule-8 and comparison-reasoning investigations), form a
hypothesis and confirm it against evidence that would also rule out the
alternative — not just evidence consistent with it — before declaring a
root cause. Only then fix and add the regression test.

If a fix attempt fails twice in the same way (same failure mode
surviving two different wording/approach attempts), stop guessing and
bring it back to the user as a pattern worth a design decision, rather
than trying a third variation unilaterally. This is already this
project's practice (rule 8, the citation-retry-loop reversion) — keep
doing it.

Skip the ceremony when the cause is genuinely obvious (a typo, an
off-by-one visible on sight) — go straight to fix + regression test.

## 5. Documentation

Every Standard-or-larger change gets written down in `PROJECT_CONTEXT.md`
— new work as its own `###` section, a fix to existing work as an
addendum to that section — covering what changed, why (the non-obvious
part), and how it was verified. Trivial changes usually don't need an
entry.

Keep the changelog-of-record in exactly one place per change (its own
section) — don't also re-summarize it in "Next steps," which is a
todo list, not a second changelog. This project already had to do a
cleanup pass (2026-08-19) after "Next steps" grew to ~380 lines of
duplicated history; don't let it happen again. Prune "Next steps" back
to only genuinely open items whenever it starts accumulating
already-resolved entries.

## 6. Independent review pass

Once a Substantial change is implemented, tested, and verified working,
review it as if you weren't the author: check every principle in
section 3 was actually followed, check nothing needed was removed and
nothing unneeded was added. Use the `/code-review` skill (medium or
high effort) for this rather than an ad hoc read-through — it already
exists for exactly this. If it surfaces findings, fix them and repeat
steps 2-6 for the fix itself.

Cap the loop: if two review passes in a row surface no new issues (or
the same issue twice with no clean fix), stop iterating and bring it to
the user instead of continuing to churn.

For Standard-tier changes, a self-check of the diff is enough unless
something about the change feels risky enough to warrant a real
`/code-review` pass — use judgment.
