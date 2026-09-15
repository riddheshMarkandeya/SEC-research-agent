# A verifiable `calculate` tool, plus new citation-gate stress questions

**Date:** 2026-09-11

## Context

Designing new stress questions to test the structured-claims verifier
surfaced a real, previously-unnoticed problem: rule 9 told the model to
verify a hand-computed value by quoting its raw inputs, but
`_verify_one_claim`'s value-attribution check always requires the
claimed VALUE ITSELF to appear in the quote — quoting two raw inputs
never produces a number candidate equal to their ratio, so any
rule-9-compliant computed claim was *guaranteed* to fail. This explained
3 separate self-computed-ratio refusals as one structural gap, not three
flukes. Full design:
`docs/plans/2026-09-11-calculate-tool-and-stress-questions.md`.

## Decision

New `calculate` tool (PAL/Toolformer-style — the model calls it, real
code does the math, the result becomes a normal citable result), chosen
over a FinQA-style "compute claim" schema extension since it reuses the
entire existing claim-verification pipeline unchanged and prevents wrong
arithmetic by construction rather than catching it after the fact. The
formula registry stays as-is for named ratios; `calculate` is the
fallback for arithmetic it doesn't cover. Two independent guarantees:
operand grounding (reuses `_number_candidates()`) and arithmetic
correctness (runs in real Python, category-mismatch and divide-by-zero
guarded explicitly).

## Why

See the plan doc for the full prior-art research (RAGAS/Citations
API/Grounding API are all span-grounding only, none have a notion of a
verifiably-derived number; the actual established solution comes from
FinQA/ConvFinQA/TAT-QA's program-and-operands pattern) and the three
`AskUserQuestion` design forks resolved before implementation.

## Files touched

`agent.py` (`CALCULATE_TOOL_SCHEMA`, `call_calculate`,
`_calculation_as_result`), `eval/citation_stress_questions.jsonl`.

## Verification

Both motivating questions passed cleanly on the first real run via
`tests/manual/verify_calculate.py` and the real `eval_harness.py`
pipeline. A bonus live finding: the model's first `calculate` call
mislabeled a unit; `_ground_operand` correctly rejected it and the model
self-corrected. Full suite 558 → 584. Two-pass layered review found and
fixed one real bug.

A second, unrelated finding surfaced while re-running the stress set:
`msft-three-segments-revenue-q3fy2026` refused with a genuine false
positive from a quote split across blank pipe-delimited cells — filed to
`BACKLOG.md`, not fixed this session (needs its own careful redesign,
see the table-grounding decision files below).

## Related

`docs/plans/2026-09-11-calculate-tool-and-stress-questions.md`,
`docs/reviews/2026-09-11-calculate-tool-and-stress-questions.md`,
`docs/decisions/2026-09-12-structure-aware-table-quote-grounding.md`
(resolves the segment-table finding above).
