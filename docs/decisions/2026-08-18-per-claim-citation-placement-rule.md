# Per-claim citation placement (system-prompt rule 8)

**Date:** 2026-08-18 (commit `62f2d16`, "Add per-claim citation placement
rule; try and revert citation-retry loop" — a squashed commit also
covering `docs/decisions/2026-08-18-citation-retry-loop-v1-tried-reverted.md`,
an unrelated change that landed the same day)

## Context

Discussing `nvda-crm-revenue-comparison`'s eval results surfaced a
distinct pattern from plain misattribution: the model answered "NVIDIA's
revenue was $81.6 billion, while Salesforce's was $11.1 billion [1][2]."
— both citations bundled at the sentence's end. `_iter_citation_claims()`'s
windowing captures both numbers under `[1]`'s window (nothing resets it
between them) while `[2]`'s window is empty, so `[1]` gets blamed for a
number probably backed by `[2]`'s own source.

## Decision

System-prompt rule 8 requires a citation immediately after each
individual fact in a multi-company sentence, not bundled at the end.

## Why

Verified live: the motivating question went from bundled `[1][2]` to
`"...$81.6 billion [1], while...$11.1 billion [2]."`, and
`nvda-crm-revenue-comparison` became a reliable PASS. A real regression
found immediately after via live testing (not assumed): the first
wording broke a previously rock-solid question
(`nvda-rd-expense-q4fy26-refusal`) 3 times in a row (tool-loop exhaustion
or topic derailment), vs. 5/5 clean historical runs with no rule 8.
Root-caused via variable isolation (`git stash` rule 8 in/out, same
question, multiple samples each way) before fixing — confirmed
causation. Fix: narrowed rule 8's wording to explicitly scope it to
multi-company sentences only, and explicitly state it adds no
requirement to single-company/refusal answers. This improved but did not
fully restore baseline reliability (~2-3/4 clean vs. 5/5 with no rule 8)
— accepted as a real, documented trade-off between a correctness/trust
fix and an occasional ungraceful failure on one fragile question.
Further wording iteration was deliberately stopped once two attempts
showed a persistent pattern, per this project's debugging discipline.

## Files touched

`agent.py` (system prompt).

## Verification

Live re-tests as described above; full eval suite tracking
`nvda-crm-revenue-comparison` and
`nvda-rd-expense-q4fy26-refusal` across iterations.

## Related

`docs/decisions/2026-08-18-citation-verification-wired-into-eval-gate.md`
(the run that surfaced this pattern),
`docs/decisions/2026-08-18-citation-retry-loop-v1-tried-reverted.md`
(squashed into the same commit).
