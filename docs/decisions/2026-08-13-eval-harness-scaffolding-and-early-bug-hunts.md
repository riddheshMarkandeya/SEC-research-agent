# Eval harness scaffolding, and the first rounds of bug-driven eval growth

**Date:** 2026-08-13 scaffolding (commit `5b5e38a`, "Week 4: eval harness
with numeric and LLM-judge grading") through 2026-08-16 (commits
`07cbf30` reranker fix, `c6104f8` comparison-synthesis fix, `d9aa1eb`
eval grown 8→16)

## Context

Deliberate ordering: evals before the agent, so there's a way to measure
whether each change helps. This project deviated from that ordering —
Week 5's agent was built on a 6-question baseline instead of the full
30-50 — a conscious tradeoff for momentum, acknowledged as making it
harder to say precisely whether Week 5 "helped" in any measured sense.

## Decision

`eval_harness.py` runs every question in `eval_questions.jsonl` through
`agent.run_agent()` (switched from `answer.generate_answer()` once the
agent existed) with three grading strategies chosen per-question by a
`"type"` field: `"numeric"` (exact-match, tolerant regex extraction,
deterministic, no LLM), `"comparison"` (same but for multi-company
`expected` lists — doesn't check attribution, only that both numbers
appear), and `"judged"` (LLM-as-judge at `temperature: 0.0`, stricter
than generation's 0.1). Every graded answer also gets a citation-marker
check. Runs are saved as timestamped JSON under `./eval_results/`,
tracked in git for comparison over time.

## Why

Sanity-checked the grading itself, not just the pipeline: a 4-question
negative-control set with deliberately wrong expected values and
inverted criteria correctly FAILed all 4.

**Found a bug in `num_ctx` before any of this eval work meant anything**:
the first live run against `agent.py` timed out — `ollama ps` showed
`context_length: 4096`, far too small once a tool call returns 5 chunks
(~3000 chars each) plus the system prompt, let alone a comparison
question's second tool call. Fixed by setting `"num_ctx": 8192`
explicitly everywhere. Worth flagging: this could easily have been
misdiagnosed as a pure model-capability limitation.

**8-question run, pre-fix: 6/8, 8/8 cited.** Both failures root-caused,
not left as "the model got it wrong": (1) `aapl-msft-employee-comparison`
— a real retrieval bug: the correct MSFT headcount chunk ranked #3 in
fused search but the cross-encoder reranker demoted it out of the top 10
(fixed via the MAX-of-RRF reranker fix, see that decision file);
(2) `pltr-dividend-2019-refusal` — a grading-criteria problem: the agent's
inference ("no dividends declared as of 2025" implies none in 2019) was
logically valid but the criteria didn't anticipate it. Fixed by rewording
the criteria to explicitly name EPS as an unrelated figure that doesn't
violate it — verified via 5/5 stable pass on the fixed answer, 3/3 stable
fail on two deliberately-bad answers, same "test the grading" discipline.

**Post-reranker-fix re-run: still 6/8** — the fix worked exactly as
intended (`aapl-msft-employee-comparison` now PASSES), but a different
question flipped: `aapl-msft-tax-rate-comparison` — a synthesis bug, not
retrieval (confirmed: the correct chunk ranked #1 when queried directly).
Root-caused as two compounding issues: (1) query-formulation fragility —
the model's self-written query for MSFT was garbled; the fix that
worked, tested directly against both companies, was to use the user's
own original question text as the search query on the FIRST search
against each not-yet-searched company (`_resolve_search_args()`'s
`searched_tickers` tracking), trusting the model's own rewritten query
only on a retry; (2) same-sentence current-vs-prior-year confusion — the
source states both periods' rates in one sentence, and the model
sometimes grabbed the prior-year clause. Fixed by sharpening the
system-prompt's period-matching rule with a concrete same-sentence
example. An interim version (system-prompt rules only, no query
override) had fixed the tax-rate comparison but broken a previously-solid
standalone question (`msft-tax-rate-q2fy26`) — the lesson that motivated
moving from "tell the model how to phrase its query" to "don't let the
model's phrasing matter for the first search."

**Final 8-question re-run, both fixes applied: 7/8, 8/8 cited** — the
best result yet, with only the already-documented PLTR grading-criteria
issue remaining.

**First eval-growth pass: 8 → 16 questions, 14/16 passed.** Targeted
NVDA/PLTR's previously-zero numeric-question coverage, a second
comparison pair, and a fiscal-quarter-labeled date. Two new questions
failed with a genuinely new class of bug: near-duplicate boilerplate
across a company's own filings (`nvda-gross-margin-fy26`) and a
differently-phrased section winning retrieval over the section with the
actual number (`msft-rd-expense-q3fy26`) — not query formulation, not
comprehension, a structural retrieval-precision limit. See
`docs/decisions/2026-08-16-fiscal-period-labels-tried-and-reverted.md`
and `docs/decisions/2026-08-16-xbrl-structured-facts-tool.md` for how
these were eventually resolved. Considered and dropped: RAGAS/DeepEval
(open-source faithfulness-metric libraries) — decided against once
`value_is_citation_verified()` existed, since it already does
faithfulness-style checking directly in this project's own pipeline.

## Files touched

`eval_harness.py` (new), `eval_questions.jsonl` (new, grown), `agent.py`.

## Verification

Numbered eval-result JSON files at each milestone (`20260815T030212Z`,
`20260815T223031Z`, `20260816T073528Z`, `20260816T224625Z`).

## Related

`docs/decisions/2026-08-13-hybrid-retrieval-and-reranker-fix.md`,
`docs/decisions/2026-08-16-fiscal-period-labels-tried-and-reverted.md`,
`docs/decisions/2026-08-16-xbrl-structured-facts-tool.md`,
`docs/decisions/2026-08-18-eval-growth-round3-financebench-1-2.md`.
