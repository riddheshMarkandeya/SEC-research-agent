# [Short, descriptive title of the change]

> Copy this file to `docs/plans/YYYY-MM-DD-<slug>.md` to start a new plan.
> `TEMPLATE.md` itself is excluded from `PROJECT_INDEX.md`'s index and
> from file-count verification checks.

## Context

[What prompted this change — the problem, the constraint, or the failing
case that triggered it. For a bug fix: the root cause, confirmed against
real code/data, not guessed. For a feature/redesign: the motivating gap
or the eval/review finding that surfaced it.]

## Prior art (if applicable)

[What existing tools, libraries, papers, or established patterns were
checked before designing this — read/searched for real, not guessed at
from the name alone. Omit this section when the change is small and
mechanical enough that no real research was warranted.]

## Decision / Design

[The approach actually chosen, and why — the concrete design: new
files/functions, schema or data-shape changes, the key logic. Name real
alternatives only when more than one reasonable approach existed, and
say what was traded away by picking this one over the other(s).]

## Scope / Out of scope (if applicable)

[What this plan deliberately does NOT cover, and why — e.g. a related
problem parked for a separate follow-up, or a boundary drawn to avoid
scope creep. Omit if the plan's boundary is already obvious from Context
and Decision alone.]

## Files and steps

[Ordered, concrete implementation steps and the file(s) each one
touches — the checklist an implementer follows top to bottom.]

## Testing and verification

[How correctness gets confirmed: which parts get full red/green TDD
(pure/deterministic logic) vs. a manual `tests/manual/verify_*.py`
live-verification script (live-only code per this project's CLAUDE.md
carve-out — SEC EDGAR calls, Chroma/embedding indexing, LLM
round-trips); what the acceptance criteria are; what live spot-check or
eval re-run (`eval_harness.py --ids ...`) confirms it end-to-end, not
just in isolation.]

## Addendum (if applicable)

[If actual execution deviates from this plan after implementation
starts — a step fails repeatedly, a live run disproves an assumption,
the user redirects mid-task — record what was tried, what happened, and
what changed, as a dated addendum appended here rather than rewriting
the plan's original sections. Omit entirely when execution matched the
plan as written.]
