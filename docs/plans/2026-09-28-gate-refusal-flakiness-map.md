# Map: citation-gate refusals behind flaky eval questions

> **Superseded for ticket state** by `docs/plans/2026-09-28-agent-improvement-map.md` (2026-09-28). This file keeps its evidence and is no longer edited.

Date: 2026-09-28. Wayfinder map. It is the single source of ticket state for this effort.

## Destination

A frozen set of decisions and ordered work packages. Together they remove the avoidable gate
refusals behind flaky eval questions without loosening what the gate proves. "Avoidable" means
the answer was correct, or would have been with one more corrective turn. Refusals of wrong
answers stay refusals.

## Notes

- **The grilling here was done by the agent itself, at the user's request (2026-09-28).** It
  overrides wayfinder's "grilling is with the user" default. Every self-grilled decision cites
  evidence from the replay, traces, code or corpus. A decision that loosens the gate, or that
  revisits a recorded decision (`~/.claude/CLAUDE.md` §4), is marked **needs user OK**. It is not
  final until the user agrees.
- **Evidence base.** The evidence covers every `citation_gate_refused` event since `d14eb28`
  (2026-09-19 03:12 UTC), when today's gate took shape. There are 38 refusals over 478 runs.
  Each was replayed offline (no LLM, no quota):
  1. The run's logged tool calls rebuild `all_results`.
  2. The final `submit_answer` goes through today's `verify_claims`, at HEAD `55a2a58`.
  3. A counterfactual pass re-verifies under the candidate rules.

  The scripts are scratch files for now. Committing them is a ticket below. Result counts
  matched the logged `n_results` in every run except five on 09-21/22. Those five differ because
  the fiscal-year string fix (`264fbc6`, 09-26) now resolves lookups that failed then, so their
  per-index conclusions are low-confidence.
- **Reading the counts.** A run is recovered only if every one of its warnings clears. "Rescue" is
  not the same as "correct": `msft-three-segments` shows the gate refusing a wrong answer.
- **Checks.** Any gate change is critical core (`agent.py`, `numeric_utils.py`,
  `table_grounding.py`, via `retrieval.py` rules). It needs escalated plan review, 90% diff
  coverage and a live panel. The prompt-change protocol applies to anything model-visible.
- **Quota.** 500 requests/day. The panel 3× is about 200 requests.

- **Proposed build order.** It becomes BACKLOG work packages when the map freezes, after the
  user OKs Decisions 3, 4, 9 and 12 and the fog clears:
  1. Commit the replay tool.
  2. Retry slot (D9), then a panel run and a re-mine.
  3. Verifier placeholder downgrade plus quote-number coverage (D4/D11 and D3; code-only).
  4. Table grounding: header parse, then the verbatim span (D12).
  5. Segment-table ranking.

  Each package re-mines the refusals with the replay tool before the next one starts.

### Evidence summary (38 refusals since 09-19)

| Bucket | Runs | Questions |
|---|---|---|
| Already fixed by later commits (header strip `022e851`, identities `2a6d243`) | 6 | nvda-revenue-two-quarter ×3, aapl-msft-total-assets ×2, nvda-revenue-fy26 |
| Still refused today | 32 | 14 questions; pltr-inventory-turnover-fy2025-refusal ×10 and nvda-rd-expense-q4fy26-refusal ×5 lead |
| ...of which got **no corrective retry** | 27 of 38 overall | the retry needs `calls_made < MAX_TOOL_ITERATIONS` (6) |
| ...refused on a **forced final turn** | 19 of 38 | forced turns are 45 of 478 runs (9%) |
| Retry rescue rate when a retry does run | 49 of 60 (82%) | all runs since 09-19 |

Counterfactual recoveries among the 32 live runs, from gate-rule changes alone (no retry change):
- P1, verbatim table quote (naive form): 5
- P2, a number covered by a verified claim's quote: 3
- P7, a claim value absent from `answer_text` verified as qualitative: 7
- P1+P2+P7: 14

Rejected probes:
- **P5, any number in any cited source:** too loose; see Decisions.
- **P4, auto-reattribute a misattributed quote:** recovered 0.

## Decisions so far

1. **The live set is the replay set, not the eval reports.** Eval reports count a refusal even
   when a later commit fixed its cause: 6 of the 38 pass today. Future tickets measure against a
   fresh replay. (Self-grilled: the replay matched logged result counts in 33 of 38.)
2. **The biggest lever is the retry budget, not the gate rules.** 27 of 38 refusals never got the
   one-shot corrective retry, because `_should_retry_for_citations` only fires while
   `calls_made < MAX_TOOL_ITERATIONS`. When a retry runs it rescues 82% of runs. That projects
   about 20 rescues from giving the retry its own turn, and nothing about what the gate proves
   changes. It costs 1 extra LLM request, only on refused turns. Detailed design: Decision 9.
3. **P2: a verified claim's quote covers the numbers in it.** Deferred to the BACKLOG Watch list
   (user, 2026-10-01; package 2's re-mine found no retry it would fix). Was: adopt, needs user OK
   (loosens coverage). If a claim's quote passed verification, every number in that quote is text from the
   cited filing. Coverage only asks that the answer's numbers trace to a filing, and this
   satisfies it. The risk (a number from the quote restated with the wrong meaning) is the same
   one every claim already carries, since value checks can't read semantics. Live cases:
   - "$5.1 billion or 17%" with only 17 claimed;
   - "Agentforce 360" in a quoted risk sentence;
   - the H20 "$4.5 billion" in a quoted gross-margin sentence.
4. **P7: a claim value that the answer never states is verified as qualitative.** Deferred to the
   BACKLOG Watch list with D3 (user, 2026-10-01). Was: adopt, needs user OK. A claim's value matters only as coverage for a number the reader sees. A value
   missing from `answer_text` asserts nothing, but today it can refuse the whole answer. Live
   cases are placeholder values in qualitative claims: 2025/2024 for "As of December 31,2025", 10
   for "Condensed Consolidated Balance Sheets", 2003, and unit "raw" with a null value. That's
   7 runs, mostly pltr-inventory-turnover. The prompt already forbids placeholders (rule 9), so
   the model ignores it. The quote-in-source check still runs. Schema-side alternative
   rejected in Decision 11.
5. **Rejected: P5, cover any number found anywhere in a cited source.** A cited chunk is about
   2,000 characters, with many numbers from other periods and segments. It would cover exactly
   the wrong-period misstatements the gate exists to catch.
6. **Rejected: P4, silently re-attribute a quote to the result it actually came from.** The
   reader-facing `[n]` in `answer_text` would still point at the wrong source. It recovered 0 runs
   on its own, and the reliable evidence is only 1 run.
7. **msft-three-segments and msft-segment-comparison are retrieval failures, not gate false
   positives.** The Q3 FY26 segment table is in the corpus: chunk 35 of the 2026-03-31 10-Q,
   `0001193125-26-191507`. The refused answers quoted the Q2 (December) table instead, and the
   gate was right to refuse them (`wp=False`). This moves to ticket "Segment-table retrieval by
   period".
8. **The `[26]` out-of-range citation comes from forced final turns.** In run `704b4e2cb0c9`, the
   budget ran out with a 6th `search_filings` pending. The forced answer cited result 26, from the
   search that never ran, and got no retry. It folds into Decision 9: the retry message
   already names the valid range.

9. **Retry slot design: the citation retry no longer needs spare budget.** **Needs user OK**
   (it revisits the 2026-08-24 "share the MAX_TOOL_ITERATIONS budget" choice from `0ba1e5d`).
   - **Change.** Drop `loop_state.calls_made < MAX_TOOL_ITERATIONS` from both retry conditions
     (`_handle_submit_turn` and `_handle_no_tool_calls_turn`). The retry stays capped at one per
     conversation by `retried_for_citations`, and stays Gemini-only.
   - **Why it's safe.**
     - The loop stays bounded. After a post-budget retry, a submit is verified and finalized. A
       tool call either takes the one forced final turn or breaks to
       `_finalize_after_budget_exhausted`, which already re-verifies `pre_retry_submit_args` and
       refuses exactly as today.
     - Worst case is `MAX_TOOL_ITERATIONS + 3` round trips. That's the bound the 09-16 safety-net
       decision already documented, assuming the retry could stack.
   - **Why it was a choice, not a principle.** The guard came from a `for` loop that broke at the
     cap. No cost rationale was recorded.
   - **Evidence.** 27 of 38 refusals had no retry. The retry rescues 49 of 60 runs when it runs.
     The extra request only happens on a refused turn: 38 of 478 runs.
   - **Forced turn.** The dropped pending call behind the `[26]` citation needs nothing new: the
     retry feedback already carries "results are numbered 1-25".
   - **Logging.** Add `calls_made` to the `citation_retry` event, so post-budget retries can be
     counted.
   - **Verification.**
     - Unit tests at the `_run_agent_impl` seam with a fake backend: a retry after a forced final
       turn; a retry at exactly `MAX_TOOL_ITERATIONS`; a post-retry tool call ends in
       `_finalize_after_budget_exhausted`.
     - Then the panel 3× against the post-fix B runs (`20260928T071313Z`, `071948Z`, `072319Z`).
   - **Re-measure after it ships.** The replay can't simulate a retry's outcome, which needs the
     LLM. Re-mine the refusals from the panel and eval runs before deciding Decisions 3 and 4 and
     the table-quote ticket: some may become unnecessary.

10. **Segment-table retrieval: the table is indexed but ranks out of the candidate pool.**
    - Offline probe of the 18 logged MSFT queries from the refused runs: chunk 35 of the
      2026-03-31 10-Q (`0001193125-26-191507`) never reached the top 10.
    - The chunk is indexed: all 108 chunks of that 10-Q are in Chroma.
    - For the plain question it ranks 103 in BM25 and 76 in vector search. For a keyword query it
      ranks 25 and 33.
    - `CANDIDATE_POOL_SIZE` is 25 per method, so fusion and reranking rarely see it.
    - The chunk is mostly cost-allocation prose, with the segment table at its tail. The
      December-quarter MD&A summary chunk (`2025-12-31#44`) ranks 1–21 instead.
    - Next step: ticket "Segment-table ranking fix".

11. **Claim schema vs. verifier rule: fix it in the verifier (Decision 4).** No schema change for
    now. From the research note `docs/research/2026-09-28-claim-schema-placeholder-values.md`:
    - No Gemini schema feature can forbid the live failures: 2025 and 10 are valid numbers, and
      "raw" is a valid unit.
    - Vendor guidance and benchmarks say models fill optional fields from world knowledge, and
      that values should be validated in the application.

    Refinements to Decision 4:
    - Match a claim value to `answer_text` the way coverage does: `normalize()`, 1% tolerance,
      and the same citation-bracket and non-claim strips. Don't match by string presence.
    - Treat a claim with `value` None and any unit as qualitative.
    - Log each downgrade (`claim_downgraded_qualitative`).

    It changes no model input, so the fingerprint is unchanged and no panel run is needed. The
    critical-core spot-check and the 90% coverage bar still apply.

    A `claims` union type (`anyOf`) would revisit the 2026-09-15 rejection
    (`docs/decisions/2026-09-15-qualitative-claims-schema.md`), and would need a live check that
    Gemini accepts it. It's not pursued: it couldn't stop these values anyway.

12. **Verbatim multi-row table quotes: two changes, header parse first.** Approved and shipped
    (user, 2026-10-01; `docs/decisions/2026-10-01-verbatim-table-row-span.md`). This
    revisits the 2026-09-13 revert of the "exact substring" shortcut. Research note:
    `docs/research/2026-09-28-table-quote-grounding.md`.
    - **(a) Header parse fix.** `_classify_row` reads a leading single-cell row such as
      `| Three Months Ended | | | | |` as a group label. Verified on NVDA chunk 34
      (`0001045810-26-000052`): the $74,550 cell gets `group_label='Three Months Ended'`.
      - The table then loses its real period header rows from every permitted region.
      - Any quote gets required to name a bogus group label, so even the proposed row-span rule
        failed the real NVIDIA quote.
      - Fix the classification. Check it against every table fixture in
        `tests/test_table_grounding.py` and the other tracked tables.
    - **(b) Position-anchored verbatim span, OR-ed with `quote_is_grounded`.** Accept a quote that
      meets all of these:
      - it is found by position inside the cell's own table block (every occurrence tried);
      - it starts at a row boundary and ends at a cell boundary;
      - it covers the claimed row from its first cell through the claimed cell;
      - it includes the governing group label only if the span contains a label row.

      The naive "contains its own row" rule was rejected: without alignment it accepts a
      mid-header-row start, which reopens the header cherry-pick. The research prototype passed
      every existing test plus new splice and cherry-pick attacks. `GroundedCell` needs row and
      column positions.
    - **Prior art.** FEVEROUS and TAT-QA address evidence by coordinates. FinQA uses whole rows.
      Nothing published verifies by free-text substring on linearized tables.
    - **Out of this decision.** A verbatim Intelligent Cloud row still grounds a 35,013 claim
      because of the 1% tolerance. That's pre-existing and already tracked in BACKLOG.
    - **Tests.** Use the note's list: accept the real NVIDIA 3-row and 2-row quotes and MSFT
      multi-row quotes with and without group label; reject the raw 09-13 slice, a cell-aligned
      splice, own row plus a trailing foreign label, a mid-row start, a mid-header cherry-pick, and
      a truncated trailing number.

## Open tickets

### Tool-message citations on refusal questions
- Question: On refusal questions the model cites the Q4 hint or the no-data message as if it were
  a numbered result ("No company files a separate quarterly report for Q4..." as [1]). It also
  volunteers context figures (FY and Q1–Q3 R&D, cash balances). Should tool messages become
  citable results? Should the refusal path need no claims? Or is it a prompt fix?
- Type: grilling (self), probably a prompt change later.
- Blocked by: Build WP "Retry slot" shipped and re-measured (Decision 9).
- Status: open.

### Segment-table ranking fix
- Question: How should the Q3 FY26 MSFT segment table reach the candidate pool? The options are
  table-aware chunking (a table with its own caption as a chunk), a bigger `CANDIDATE_POOL_SIZE`,
  or extending `_rescue_demoted_table_chunk`. Which is the root cause, and does the same thing
  hide other tables? See Decision 10 for the facts.
- Type: grilling (self), under `debugging-discipline`. `retrieval.py` and `chunk_documents.py`
  are critical core.
- Blocked by: none.
- Status: open. **Frontier.**

### Commit the replay tool
- Question: Should the offline replay and counterfactual scripts become a repo tool (for example
  `analyze_gate_replay.py`, next to `analyze_citation_gate.py`)? Every later ticket and work
  package re-measures with it.
- Type: task.
- Blocked by: none.
- Status: open. **Frontier.**

## Not yet specified

- **Claim field order.** The schema declares `value` before `quote`. A hypothesis from the
  research note: the model commits to a number before copying the quote. A quote-first order is a
  cheap, model-visible experiment (prompt-change protocol). Worth trying only if placeholders or
  value mismatches persist after Decision 4 ships.
- **Reformatted table-row quotes.** The model strips pipes or restacks rows ("Gross profit | 71.1
  | 75.0"), so no cell is located and flat matching fails (nvda-gross-margin, nvda-inventory-
  turnover, 09-21/22 runs). It's unclear whether this still happens after WP1–WP8. Re-measure
  after the retry fix.
- **Self-computed derived numbers without `calculate`** (inventory turnover 2.92, R&D intensity
  11.7%). This is prompt territory. It may shrink once retries run.
- **Cell-only quotes** ("$12,985", "Assets"), which fail as too short to verify.

## Out of scope

- Judge-graded content failures with no gate involvement, such as pltr-dividend-2019-refusal's
  "states a fact instead of saying not covered". These belong to judge criteria work.
- Wrong-value answers the gate correctly let through or correctly refused, such as the
  crm-buyback 2.145 billion case (`wp=False`).
- The Ollama backend. The retry is Gemini-only by design, and the eval runs on Gemini.
