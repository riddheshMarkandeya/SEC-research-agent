# Tool-turn-waste fix: stop re-deriving what a tool already gave

**Date:** 2026-09-14

## Context

A live 47-question baseline (31/47) found its largest failure cluster
wasn't a citation-verification bug at all: 9 of 16 failures ended in the
canned "ran out of searches" timeout, and tracing every one showed the
agent usually already held the correct answer and burned its remaining
turns re-deriving or mis-deriving it. Full design:
`docs/plans/2026-09-14-tool-turn-waste.md`.

## Decision

Two of four mechanisms fixed via prompt/schema-description/error-message
changes only, no tool-calling-loop change: `calculate` being used for an
ungroundable unit conversion (fixed by telling the model `normalize()`
already handles unit restatement); re-deriving a value a tool already
returned whole (fixed with a rule-9 addition: if a tool already returns
the exact quantity asked for, submit it, don't fetch its components). A
third mechanism (`_ground_operand`'s error message blaming the wrong
field) fixed by computing which correction actually applies instead of
one generic message.

## Why

A fourth mechanism (the model never using `compare_financial_metric` for
3+-company ranking questions) was attempted via prompt wording, three
times, and failed identically each time — per this project's "fails
twice in the same way" rule, brought back for a decision rather than
tried a fourth way unilaterally; one more authorized attempt also
failed, and all wording was reverted to avoid shipping unproven changes
that could regress currently-passing questions for zero measured
benefit. Filed to `BACKLOG.md` with a working hypothesis. A fifth,
structurally-related idea (`MAX_TOOL_ITERATIONS=6` leaves zero slack for
a legitimate final answer) was scoped out deliberately — it needs a
tool-calling-loop change with its own wrong-answer risk, not a prompt
change.

## Files touched

`agent.py` (`CALCULATE_TOOL_SCHEMA` description, system prompt rule 9,
`_ground_operand`).

## Verification

Full suite 631 → 634. Live: a 7-question targeted spot-check passed 7/7.
A full 47-question re-run moved 31/47 → 36/47, with the 4 new failures
each independently traced to pre-existing, already-documented mechanisms
this diff never touches.

## Related

`docs/plans/2026-09-14-tool-turn-waste.md`,
`docs/reviews/2026-09-14-tool-turn-waste.md`.
