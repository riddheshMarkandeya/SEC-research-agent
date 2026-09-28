# Structural review: challenging the core design (self-grilled)

Date: 2026-09-28. This is a grill-me record the agent ran against itself at the user's request. It
challenges prior design decisions and looks for structural changes, not patches. Every proposal
below states its evidence, its blast radius (any structural change touches every question) and
how to test it before adoption. Nothing here is decided until the user confirms it. It builds on
`docs/plans/2026-09-28-gate-refusal-flakiness-map.md` (the map) and its offline replay.

## Where the failures actually come from

Every eval row since the current gate (2026-09-19 03:12 UTC): 500 rows, 68 failures.

| Cause | Fails | Main questions |
|---|---|---|
| Citation-gate refusal | 41 | pltr-inventory-turnover-refusal 9, msft-segment-comparison 5, nvda-rd-q4-refusal 5 |
| Judge fail on a refusal question | 11 | nvda-rd-q4 7 (criteria fixed `ca52d68`), pltr-dividend-2019 4 |
| "Not found / not broken out" (retrieval miss) | 10 | msft-three-segments 6, msft-segment-comparison 2 |
| Wrong or incomplete value | 6 | crm-buyback 2, scattered |

- **Gate precision on graded numeric rows** (`analyze_citation_gate.py`, 339 rows):
  - 18 refusals: 9 correct answers withheld, 9 wrong answers stopped.
  - 8 wrong answers passed with citations. Almost all were "not found" answers, not wrong
    numbers.
  - Most of the 9 answers it stopped would have failed grading anyway: non-answers, and wrong-
    quarter MSFT values caught incidentally by a reformatted quote.
- **Loop mechanics** (478 traced runs):
  - 45 forced final turns, and 19 of the 38 gate refusals happened on one.
  - 27 of 38 refusals had no corrective retry. When a retry runs, it rescues 49 of 60.
  - Only 8 runs never called `submit_answer`, so the prose fallback is nearly unused.
  - `compare_financial_metric` was called 0 times.
- **Forced final turns concentrate** on pltr-inventory-turnover-refusal (17 of 25 runs),
  nvda-rd-q4-refusal (15 of 28) and msft-three-segments (7 of 9). These are the questions whose
  answer is "not available" or can't be found.

## Challenged decisions

### C1. Verbatim quotes as the grounding unit: upheld

- **Challenge:** let code locate the claimed value in the cited source and make the quote
  optional (the "SP1" rule). That would remove header-echo stripping, too-short checks and most
  table-region logic.
- **Offline test:** the replay of all 38 refusals, re-verified with value location instead of
  quote matching.
  - SP1 passes 17 of 38, against 6 today.
  - It also lets through 2 known-wrong answers: msft-three-segments quoting the December
    quarter's table (all values present in that source), and crm-buyback's wrong 2.145 billion.
  - The targeted fixes that keep quotes (map Decisions 4 and 12) also reach 17 of 38, without
    losing those catches.
- **Verdict:** keep quotes. Verbatim-quote matching is the only thing that incidentally catches
  wrong-period answers. Dropping it trades correctness for no extra recovery.

### C2. "Every number in the answer must be covered by a claim": upheld, with a refinement

It's the project's core principle, and the replay shows no case where coverage itself was wrong.
Its false positives are all mechanism gaps: restated quote numbers, formula constants (fixed
today), and placeholders. They're addressed by map Decisions 3 and 4, not by dropping the rule.

### C3. The citation retry shares the tool budget: overturned (map Decision 9)

27 of 38 refusals never got the retry. See the map.

### C4. Model configuration: challenged, needs a test

- **Temperature:** the agent runs at 0.1, inherited from the Ollama agent of 2026-08-14. No
  Gemini-specific reason is recorded, and Google recommends 1.0 for Gemini 3. Values below that
  can degrade reasoning. (Source: `docs/research/2026-09-28-gemini-model-choice.md`.)
- **Thinking:** none is configured, so gemini-3.5-flash-lite uses its **Minimal** default. The
  installed google-genai SDK supports `thinking_level` MINIMAL, LOW, MEDIUM and HIGH.
- **Why it matters:** the recurring failures are behavioural: placeholder values, citation
  misattribution, reformatted quotes, and hand-computed numbers instead of `calculate`. A thinking
  budget attacks the whole class at once.
- **A stronger model:** 3.8 Flash is on the free tier. Its daily cap isn't published, and third
  parties say about 20/day. The judge shares `GEMINI_MODEL_NAME`, so a model swap would also
  change the grader. It's deferred until a separate judge-model setting exists.

### C5. The tool budget and "keep searching": challenged, root cause of the refusal-question failures

- **What happens:** on a "not available" question, the model can't prove a negative, so it
  searches until the budget runs out. The forced final turn then submits with filler claims
  (years, "10", unit with no value), and the gate refuses them.
- **Scale:** that one pattern drives most failures of the two refusal questions: 14 gate
  refusals, 32 forced turns out of 53 runs.
- **What it isn't:** more budget, or more gate leniency alone. The agent has no first-class
  "not available" conclusion.

### C6. The eval process uses the panel for every change: challenged

- **The panel:** 13 questions × 3 is the only regression check for every change, including
  code-only gate changes. It costs about 200 of the 500 daily requests, and it sees only 13
  questions.
- **The replay:** re-verifying every traced final submission offline covers all 48 questions'
  history, costs nothing, and runs in minutes.
- **Its fidelity:** result counts matched in 33 of 38 refusals. The 5 misses are explained by a
  later fiscal-year fix.
- **What it found:** it surfaced the 2 lost true positives in C1, which a 13-question panel could
  easily miss.

## Proposals

Each proposal is a structural change. They're ordered by expected value per unit of risk.

### S1. Offline replay becomes the regression gate for code-only verifier changes (process)

- **What:**
  - Commit the replay as a tool (`analyze_gate_replay.py`).
  - Every change to `verify_claims`, `table_grounding` or `numeric_utils` reports its effect on
    every traced final submission since the last corpus change: refusals recovered, and new
    refusals created.
  - For graded runs, it also reports the true positives lost, via `gate_withheld_would_have_passed`
    and the known-wrong set.
  - The panel is kept for model-visible changes and for a final live check.
- **Evidence:** C1 and C6.
- **Blast radius:** none to the agent. It changes how changes are accepted.
- **Test:**
  - Re-derive today's known results with the committed tool: the 6 already-fixed runs, and the
    17 of 38 under Decisions 4 and 12.
  - Check fidelity by comparing `n_results`.
- **Simplifies:** most gate work no longer needs quota or a same-day panel.

### S2. One uniform submit loop (map Decision 9, taken further)

- **What:** treat a failed `submit_answer` verification as an ordinary tool error the model can
  answer, with one reserved final turn.
  - First step (small, map Decision 9): the retry no longer needs spare budget.
  - Later refactor: fold `retried_for_citations`, `pre_retry_*`, the forced-submit-on-prose
    path and the forced final turn into one "submit attempts left" counter.
- **Evidence:** 27 of 38 refusals had no retry, and retries rescue 82%.
- **Blast radius:** every question's loop.
- **Test:**
  - Unit tests at the `_run_agent_impl` seam with a fake backend.
  - The panel 3×, then the full 48.
  - Counterfactual expectation: most of the 27 no-retry refusals.

### S3. A first-class "not available" answer (refusal path)

- **What:** give the model a way to conclude.
  - An explicit `submit_answer` form for "the filings don't state this": a `not_available: true`
    flag or a separate field, with a reason and qualitative citations only. The gate checks the
    citations but needs no numeric claims.
  - Prompt guidance: once `get_financial_fact` reports no data and one targeted search confirms
    it, conclude rather than search again.
  - It pairs with map Decision 4 (placeholders verified as qualitative).
- **Evidence:** C5.
  - Forced turns hit 17 of 25 and 15 of 28 runs on the two refusal questions.
  - 14 gate refusals and 7 judge fails came from them (nvda-rd-q4's 7 judge fails predate
    the criteria fix).
  - WP6 (no-data message naming the period) already moved in this direction.
- **Blast radius:** model-visible (schema and prompt), so the prompt-change protocol applies.
  - It can affect answerable questions if the model starts giving up early. The panel's
    answerable questions guard that.
- **Test:**
  - The panel 3× (it contains both refusal questions, plus 11 answerable ones).
  - Watch for any new "not available" answer on an answerable question.

### S4. Agent thinking level, then temperature (model config)

- **What:** A/B test the agent at `thinking_level=LOW` against today's Minimal default, then
  temperature 1.0 as a separate arm. The judge path (`complete()`) keeps its own config, so the
  grader is unchanged.
- **Evidence:** C4. The failure classes are behavioural. The settings are inherited, not chosen.
- **Blast radius:** every question.
  - Latency and tokens rise, but request count doesn't.
  - Same 500/day bucket.
- **Test:**
  - The panel 3× per arm (about 200 requests each), on days with no other run.
  - Then the full 48 on the winner.
  - Compare against a replay of the same day's refusals, so gate fixes and model changes aren't
    confused.
  - Do this after S1 and S2 ship, so a single variable changes.

### S5. Period-scoped retrieval, plus the glued-month fix

- **Evidence:**
  - MSFT's Q3 segment table is indexed but ranks 25–103, and the candidate pool is 25.
  - That caused 10 "not found" fails and 7 of 9 forced turns on msft-three-segments.
  - Research: `docs/research/2026-09-28-financial-table-retrieval.md`.
- **What (smallest change, `retrieval.py` only):**
  - Parse the period from the query in code: dates, fiscal years via `period_labels`, quarters.
    1,521 of the 1,851 logged queries contain one.
  - Map it to the matching filings' `reportDate`.
  - Run BM25 and vector search again restricted to those filings, and add the results to the
    existing rank fusion as extra lists. The unfiltered lists stay.
  - With no period parsed, behaviour is unchanged.
  - No re-chunk, re-index or prompt change.
  - Prior art: FinanceBench shows 19% correct with one shared store against 50% per document.
    HiREC finds the document first, then the passage.
- **Offline evidence (research note, BM25 only):** MSFT target rank on 3 logged queries.

  | Variant | Rank |
  |---|---|
  | Today | 40 / 45 / 29 |
  | With the period filter | 10 / 11 / 9, inside the 25 pool |
  | Table-as-own-chunk only | 34 / 39 / 1 |

  Vector ranks were not simulated.
- **Separately, a bug:** the chunker glues month names to the word before them ("Three Months
  EndedMarch 31"). BM25 then tokenizes `endedmarch`, so "March" never matches those headers.
  Verified with `retrieval._tokenize`. 70 chunk-file lines contain a glued `Ended<Month>`.
  Fixing it needs a re-chunk and re-index, and it's corpus-wide.
- **A prior decision this touches:** a period label added to every chunk's text was tried and
  reverted on 2026-08-16 (14/16 → 13/16: a shared label lifted a boilerplate chunk). A filter
  changes no chunk text or embedding, so that failure mode doesn't apply. Still, name it as a
  revisit.
- **Blast radius:** every search on every question.
- **Test (offline, no LLM):**
  - Join each logged `search_filings` query to its question.
  - Label gold chunks and hand-check about 10.
  - Measure gold rank in each list, whether gold reaches the reranker, and hit@5 per variant.
  - Keep the variant only if hit@5 improves and no current top-5 hit drops out. The 08-16
    simulation lacked this guard.
  - Then the panel.
- **Deferred:** tables as their own chunks with a non-citable header, only if dilution misses
  remain. XBRL segment facts need full-instance parsing, because companyfacts and frames exclude
  dimensions. That's exact but narrow.

### Dropped or deferred

- **Model upgrade to 3.8 Flash:** deferred. The free-tier cap is unverified, and the judge would
  change with it. It needs a judge-model setting first.
- **Removing `compare_financial_metric` from the agent's tools:** 0 calls in 478 runs, so it's a
  simplification. But the schema is model-visible, and the MCP server still uses the function.
  Low value; fold it into the next prompt-change commit.
- **Deleting the prose fallback:** 8 runs used it, and it's the Ollama path. Keep it.

## Suggested order

1. S1 (replay tool).
2. S2 step 1 (retry slot), then the panel.
3. Map Decisions 4, 3 and 12, verified with S1 at no quota cost.
4. S3 (not-available path, prompt protocol).
5. S4 (thinking A/B).
6. S5 (retrieval).

Each step re-mines refusals with S1 before the next, so every number above gets re-measured, not
assumed.

## Confirmed with the user (2026-09-28)

- The judge stays on gemini-3.5-flash-lite during any model testing. An agent model swap first
  needs its own judge-model setting, because the judge reads `GEMINI_MODEL_NAME` today.
- Model-visible changes keep the one-commit-plus-panel rule. The replay can't predict how the
  model behaves after a change.
- The final live check depends on the change's reach:

  | Change type | Final check |
  |---|---|
  | Code-only gate change | Offline replay over all traced runs, plus a targeted live spot-check of the affected questions (`live-eval-verification.md`) |
  | Prompt or schema change affecting some questions | Panel 3× screen, then replicate or attribute if anything is flagged |
  | Change affecting every question (S2, S4, S5) | Panel 3× screen, then a full 48-question run before accepting |
