# Development Workflow

These are binding instructions for all work in this repo — they override
default behavior. Agreed with the user on 2026-08-24; see
`PROJECT_CONTEXT.md`'s "Development workflow" section for the narrative
version and the rest of the project's decision history. Extended
2026-09-06 with explicit error-handling/logging, prior-art-research, and
layered-review rules, and again the same day with the `docs/plans/`,
`docs/reviews/`, and `BACKLOG.md` documentation system below.

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

Before doing anything else for a Standard or Substantial task: confirm
plan mode is actually active. If it isn't, say so and ask the user to
enter it before any edits happen — this workflow assumes a plan exists
and is approved before implementation starts, and that only happens
inside plan mode.

| Step | Trivial | Standard | Substantial |
|---|---|---|---|
| 1. Design & approval | skip | skip unless there's a real fork in approach | required, before writing code |
| 2. TDD | skip | required (see carve-out below) | required (see carve-out below) |
| 3. SE principles | apply, don't refactor surroundings | apply | apply |
| 4. Error handling & logging | skip | apply to new/changed code | apply thoroughly; plan failure/logging points during step 1 |
| 5. Debugging discipline | skip ceremony if cause is obvious | required once cause isn't obvious | required |
| 6. Documentation | usually skip | one entry, proportional to size | full `###` write-up |
| 7. Independent review | self-check the diff | self-check; layered review (see step 7) if it feels risky | layered review (see step 7) required |

## 1. Design before building

For Substantial work: write a short spec (problem, constraints,
proposed approach), present real alternatives with tradeoffs when more
than one exists, and get explicit user approval on the plan before
implementing. This project uses Claude Code's native plan mode for
this — write the plan directly, get it approved via `ExitPlanMode`,
then implement. Don't assume any plugin or external tool (e.g. the
`superpowers` plugin's `brainstorming`/`writing-plans` skills) is
available or in use — this project deliberately doesn't run those, to
avoid their token cost. Write the plan yourself, by hand, as part of
the normal workflow.

The `~/.claude/plans/...` file plan mode writes to is a single,
session-global scratch file that the next task overwrites — it is not
project history. As soon as the plan is approved, copy its content into
the repo at `docs/plans/YYYY-MM-DD-<slug>.md` before starting
implementation, so it survives past this session. One file per task —
problem/context, the approach actually chosen and why, files touched,
and how it'll be verified — not a separate spec-then-plan pair.

Before drafting that plan, look at how this problem has already been
solved elsewhere — existing open-source projects, libraries, or
write-ups tackling the same problem. Actually read the code or docs
rather than guessing at pros/cons from the name alone. If more than one
reasonable direction exists (there usually is once you've looked), lay
out the real alternatives with their tradeoffs and use `AskUserQuestion`
to let the user choose, rather than picking one yourself. Prefer an
existing, well-maintained library when it removes real implementation
work; don't reach for one when the equivalent is a handful of lines of
straightforward code you'd fully understand and control anyway — an
added dependency has to earn its place.

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
- **Residual case**: after implementation, check what's actually
  covered. Anything not exercised by an automated test or a live-
  verification script is a gap, not an acceptable end state. If a path
  genuinely can't be exercised by any script you're able to write (a
  human judgment call on a UI, a real third-party approval step,
  physical hardware, etc.), say so explicitly and ask the user to test
  that specific path manually before calling the task done — don't
  silently ship a path nothing has ever actually exercised.

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

## 4. Error handling and logging

Both are a standing requirement for Standard-or-larger work, not an
afterthought bolted on at the end — plan for them during step 1 (what
can fail here, what would you need to see in a log to debug it later)
rather than discovering the gaps during step 7's review.

- **Logging**: add it liberally at decision points, external calls,
  retries, and failure paths — anywhere a future debugging session
  would otherwise have to reconstruct what happened from behavior
  alone. This project's own `tracing.py`/`log_event` pattern is a
  concrete model of the generic principle: broad, best-effort,
  never-raising logging under a clear category/event name, so it stays
  queryable by cause later. Don't gate logging on whether it "seems
  necessary now" — the point is to have the trail before you know
  you'll need it.
- **Error handling**: prefer catching the most specific exception type
  the failing call can actually raise over a broad `except Exception`.
  A broad catch is sometimes still the right call (a best-effort path
  that must never itself crash its caller, or a boundary where many
  different failure types should all degrade the same way) — when you
  reach for one, use judgment, and leave a short comment saying why the
  broad catch is deliberate rather than lazy.
- This doesn't reopen section 3's minimalism: extensive logging is
  about *visibility*, not defensiveness. Don't add error handling for a
  state that's provably impossible given the surrounding code — that's
  still dead code wearing a safety-net costume. Do add it at every
  point where a real external system (network, filesystem, another
  process, user input) can actually fail.

## 5. Debugging discipline

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

## 6. Documentation and backlog hygiene

Every Standard-or-larger change gets written down in `PROJECT_CONTEXT.md`
— new work as its own `###` section, a fix to existing work as an
addendum to that section — covering what changed, why (the non-obvious
part), and how it was verified. This is the single running changelog
for the whole project's history; keep adding to it here, don't split it
into per-change files. Trivial changes usually don't need an entry.

Three other places hold specific artifact types, each written directly
by hand as part of the normal workflow — no plugin or external tool
produces any of these automatically:

- **`docs/plans/YYYY-MM-DD-<slug>.md`** — the saved plan-mode output for
  Substantial work (see step 1). One file per task.
- **`docs/reviews/YYYY-MM-DD-<slug>.md`** — independent-review findings
  (see step 7).
- **`BACKLOG.md`** (repo root) — everything still open: queued ideas,
  found-but-not-yet-fixed issues, in-progress work. Not a changelog —
  link to `PROJECT_CONTEXT.md`/`docs/plans/`/`docs/reviews/` for the
  reasoning behind an item instead of re-explaining it here.

**Keep `BACKLOG.md` and `PROJECT_CONTEXT.md` current as work happens,
not just at the end of a task.** Add a line to `BACKLOG.md` the moment a
new open item is identified — a deferred idea, a bug found but not
fixed right now, a follow-up spun off mid-task — rather than waiting
until wrap-up to remember it. Mark an item "in progress" in `BACKLOG.md`
when you start it. When an item is finished, remove it from `BACKLOG.md`
and land its `PROJECT_CONTEXT.md` changelog entry in the same step —
never let an item quietly disappear from the backlog with no changelog
trace of what happened to it.

Keep the changelog-of-record in exactly one place per change (its own
`PROJECT_CONTEXT.md` section, or its own `docs/plans/`/`docs/reviews/`
file) — don't re-summarize it in `BACKLOG.md`, which is a todo list, not
a second changelog. `PROJECT_CONTEXT.md`'s old inline "Next steps"
section already had to be cleaned up once (2026-08-19) after growing to
~380 lines of duplicated history, and was moved out to `BACKLOG.md`
entirely (2026-09-06) for the same reason — don't let `BACKLOG.md` grow
back into that shape either; prune it as items resolve.

## 7. Independent review pass

Once a Substantial change (or a Standard one that feels risky) is
implemented, tested, and verified working, review it from two
independent angles before considering it done:

1. **Correctness and compliance** — run the existing `/code-review`
   skill (medium or high effort) for a fast, targeted pass on bugs and
   CLAUDE.md adherence.
2. **Architecture, design, performance, and refactoring** — separately,
   launch a freshly-spawned subagent (one with no memory of the
   implementation session, so it isn't anchored to choices already
   made) and give it the diff plus enough context to judge it on its
   own merits. Ask it explicitly to check: does the design fit the rest
   of the codebase's architecture, is there a simpler or more idiomatic
   approach, are there real performance concerns, and would the code
   (naming, structure, organization) read better refactored — not just
   "is it correct." A refactor-for-clarity finding is a real finding
   here, not a nice-to-have.

Save the findings to `docs/reviews/YYYY-MM-DD-<slug>.md` (see step 6) —
from either pass, or both combined — and add any unresolved finding to
`BACKLOG.md` as part of finishing the review, not left to be remembered
later.

Fix whatever either pass surfaces, then repeat both passes on the fix
itself. Cap the loop: if two rounds in a row (across either pass)
surface no new issues, or the same issue twice with no clean fix, stop
iterating and bring it to the user instead of continuing to churn.

For Standard-tier changes, a self-check of the diff is enough unless
something about the change feels risky enough to warrant the layered
review above — use judgment.

## 8. Use git extensively as an inspection tool

Check `git status`/`git diff`/`git log` liberally throughout a task, not
just at the start and end — before editing, to see what's already
uncommitted and avoid confusing your own changes with pre-existing ones;
after editing, to confirm a diff is exactly what was intended and
nothing stray got included; when debugging, to isolate a suspected
change (`git stash` it in/out, same input, compare — see section 5);
when picking up old work, to check a file's real history via `git show`/
`git log -p` rather than guessing from context alone (this is what
caught the true end of a file mid-edit once — see the citation-retry
session's test-file mishap).

This is about inspection, not authorization: it does **not** change the
standing rule that commits only happen when the user explicitly asks for
one. Checking state often; committing only on request.
