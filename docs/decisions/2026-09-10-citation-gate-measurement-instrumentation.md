# Citation-gate FP/FN measurement instrumentation; Ollama demoted to secondary backend

**Date:** 2026-09-10

## Context

The uncited-claim heuristic took five review rounds to stabilize and
carries a large share of `test_agent.py`'s tests. Rather than rewrite
the hard gate on the strength of an argument alone (structured claims
would be more robust, per how Gemini's `groundingSupports`/Vertex's
Check Grounding/RAGAS's faithfulness metric all solve this), this
session built measurement apparatus first and ran it. Full design:
`docs/plans/2026-09-10-citation-gate-measurement-instrumentation.md`.
Review: `docs/reviews/2026-09-10-citation-gate-measurement-instrumentation.md`.

## Decision

Tagged every citation warning with a `check` type and index
(`CitationWarning`). `AgentResult` gained `withheld_answer` — the
model's actual answer whenever the hard gate refused it, previously
thrown away. New `analyze_citation_gate.py` classifies each refused row
as false positive / true positive / false-negative candidate by
re-grading the withheld text against ground truth. `config.DEFAULT_BACKEND`
flipped to `"gemini"` — Ollama demoted, not removed.

## Why

**The measurement found**: baseline 36/41 passed, of the 29 numeric/
comparison rows the gate fired twice, and **both firings were false
positives**. Combined with 4 new stress questions: 100% false-positive
rate across every refusal measured this session — 0 true positives, 0
false negatives. Every false positive traced to an identified root
cause (a capitalized-abbreviation sentence-break bug, a
self-computed-ratio-with-no-tool shape, an ordinal-count-phrase parsing
gap, a comma-separated citation bracket the regex doesn't recognize) —
see the plan doc for the full per-question trace. This became the
evidence base for the structured-claims redesign that followed
immediately after.

## Files touched

`agent.py` (`CitationWarning`, `AgentResult`, `withheld_answer`),
`eval_harness.py` (4 additive report fields), `analyze_citation_gate.py`
(new), `llm_backends.py` (`complete()`), `config.py`
(`DEFAULT_BACKEND`), `eval/citation_stress_questions.jsonl` (new).

## Verification

See the plan/review docs for the full measurement run detail
(`eval/eval_results/20260910T212525Z.json` baseline,
`20260910T211730Z.json` stress set).

## Related

`docs/plans/2026-09-10-citation-gate-measurement-instrumentation.md`,
`docs/reviews/2026-09-10-citation-gate-measurement-instrumentation.md`,
`docs/decisions/2026-09-10-structured-claims-citation-verification.md`
(the redesign this measurement justified).
