# Plan: package 5, strict period scoping, windowed MaxP rerank and fused-floor rule

Tier: **Substantial** (a new retrieval behaviour, revisits a recorded decision, in the critical
core). Branch `package-5-retrieval` from master. Commits only when the user asks.

## Context

The agent-improvement map (`docs/plans/2026-09-28-agent-improvement-map.md`) orders the packages
2 → **5** → 3 → 4 → 6, and package 2 is done. Package 5 removes the largest measured cause of
retrieval misses: the offline gold-rank harness (`docs/plans/2026-09-30-retrieval-gold-rank-harness.md`)
showed 478 of 572 misses happen at rerank. Three causes: the cross-encoder truncates long table
chunks at 512 tokens, other periods' filings crowd the pool, and the max-of-ranks rule lets fused
ranks squeeze out chunks the cross-encoder ranks in its top 5. The harness measured the stack on
901 query-part pairs: today 329 hits and 31/40 questions covered; with the stack (V6 + `floor3`),
526 hits and 37/40.

**The spec is the harness plan's "Step 7: package 5 spec" (items 1–12) and is binding.** This
plan turns it into build steps and adds only what the spec left open. Prototype code to port:
`%TEMP%/claude/gold/protos.patch` (and `git stash@{0}`), plus the floor rule in
`%TEMP%/claude/gold/cache_sim.py:71-72`.

User decision (2026-10-02): the live baseline is **replay-adjusted**. That means the package 1 full
run `20261001T193130Z` (42/48), re-verified under today's gate with `analyze_gate_replay`.

## Decision / Design (spec items 1–7)

1. **`src/sec_agent/retrieval/period_scope.py` (new, pure).**
   `query_report_dates(query, filings, fiscal_year_end_months) -> set[str] | None`, where `filings`
   is a list of `(ticker, form, reportDate)` and `fiscal_year_end_months` maps ticker → month.
   **The caller passes only `ticker`'s filings, or every filing when `ticker` is None.** The
   prototype's `_filings(ticker)` does this. Without it, another company's nearby date would skip
   the FY path. Port `_query_report_dates` **semantically verbatim**, because the acceptance check
   needs an exact match:
   - every explicit "Month D, YYYY" (`findall`) matches report dates within 7 days. The union is
     returned when non-empty; otherwise fall through to the FY path;
   - only the first `fiscal YYYY` / `FY YY` match counts, plus the first quarter match (`Q1` or
     "first quarter");
   - FY with no quarter matches 10-K dates only;
   - uses `period_labels.fiscal_year_label` / `fiscal_quarter`.

   **The one deliberate deviation:** an impossible explicit date ("September 31, 2025",
   "February 29, 2025", day 0) raises `ValueError` in the prototype. That would kill the agent run
   or the MCP request, since query text is untrusted and nothing upstream catches it. Skip that
   date (`except ValueError`) and report it in the result for the log. It can't change acceptance:
   no cached query crashed. It also returns the reason for a fallback (`no_date`, `no_match`),
   either as a small result tuple or a second function. Pick whichever reads cleaner and keep it
   pure.
2. **`src/sec_agent/retrieval/rerank_windows.py` (new, pure).**
   - `split_windows(text, count_tokens, window=380) -> list[str]` ports `_windows`: line-boundary
     splits, a line costs `count_tokens(line) + 1`, and inside `<TABLE>` a new window is prefixed
     with the caption line (the previous non-blank line), `<TABLE>` and the first 3 table lines.
     Keep the `line not in header` quirk.
   - `max_per_owner(owner, scores, n) -> list[float]`.
   - `RERANK_WINDOW_TOKENS = 380`, with a comment: it leaves room for the query in 512, and it is
     deliberately untuned.
3. **`retrieval.py` wiring (critical core; it gains only wiring).**
   - `_FUSED_FLOOR_RANKS = 3`. `_combine_fused_and_rerank(candidates, scores, top_n,
     fused_floor=_FUSED_FLOOR_RANKS)` scores a chunk at `ce` (its cross-encoder RRF term).
     Chunks with fused rank ≤ F score `max(fused, ce) + 1e-9 * ce`, exactly as in `cache_sim`.
     The table rescue is unchanged. Rewrite the docstring: F = 0 is pure cross-encoder, and it
     names the measurement that changed the rule. Self-contained, no doc paths.
   - Filtered search: `bm25_search` / `vector_search` gain an optional `report_dates`. BM25 skips
     records outside the dates. The vector `where` becomes a `$and` of a `reportDate $in` and the
     ticker clause, or a single clause when there is only one. This reuses the existing functions,
     not prototype copies.
   - The filing list comes from `_bm25_records` (live, pragma). Fiscal year-end months come from
     `load_companies()`.
   - Scope choice in `hybrid_search`: when dates are found, use the filtered lists only (strict).
     When no dates are found, or **both** filtered lists come back empty (Chroma and the chunk
     files out of sync), use today's unfiltered lists.
   - `rerank` scores with MaxP. It splits each candidate with `split_windows`, counting tokens with
     the model's tokenizer (`tokenizer(t, add_special_tokens=False)`), runs one flat `predict`,
     then takes `max_per_owner`.
   - `use_rerank=False` returns the **scoped** fused pool. The V6 cache's pool came from scoped
     `hybrid_search(use_rerank=False)`, and the harness needs that.
   - **Seam (spec item 11; closes BACKLOG line 58).** A public `search_details(query, ticker,
     top_k) -> dict` returns:
     - `results`: today's `hybrid_search` output;
     - `pool` ids with their MaxP `scores` (in pool order), the cross-encoder order `ce`, and the
       pre-rescue `combined` order;
     - `rescued`: the id swapped in by the table rescue, or None;
     - the `tables` and `rescuable` id sets;
     - `scope`: the report dates, or the fallback reason;
     - `windows`: the number of windows scored.

     `hybrid_search` becomes a thin wrapper returning `results`. `_rescue_demoted_table_chunk`
     reports which id it swapped in, and `rescuable` reuses its dollar-figure gate, so the harness
     stops restating it. `use_rerank=False` keeps today's fused-only output.
   - **Logging (spec item 7).** One `tracing.log_event("retrieval_search", ...)` per search, with:
     - `ticker`;
     - `scope`: the dates as a sorted list (a set would serialise as an unqueryable string via
       `default=str`), or `no_date`, `no_match` or `filtered_empty`, plus any skipped invalid
       dates;
     - `pool_size`;
     - `windows`;
     - `fused_floor`;
     - `rescued` (bool).

     Questions it answers: which dates scoped this search or why it fell back; how much CE work it
     cost; which rule ran; whether the rescue fired. It is never-raising (inherits
     `_write_local_log`). The plan review checked the consumers, and all ignore the new category:
     `build_query_set` needs `as_type`, `analyze_gate_replay` keys on `name` and
     `citation_gate_refused`, and `trace_query` only shows a `[+retrieval_search xN]` count.
   - Update the module docstring's pipeline steps: the scope step, MaxP and the floor rule.
4. **Harness (`devtools/retrieval_replay.py`).**
   - `_live_retriever` calls `retrieval.search_details` once per query, instead of two
     `hybrid_search` calls and its own `predict`. The CE order is then the MaxP one by
     construction, and the run is cheaper.
   - `rerank_cause` uses the exposed ranks. New cause `rescue`: gold was in the pre-rescue
     combined top 5 but swapped out. `fusion` covers CE top 5, not rescued, cut by the floor
     rule. `rescue_threshold` and `model` stay as they are. Update the docstring (it no longer
     restates the max rule).
   - `--fused-floor N` (default `retrieval._FUSED_FLOOR_RANKS`, read at call time, not bound as a
     default argument). The harness recombines `pool` + `scores` with retrieval's own pure
     `_combine_fused_and_rerank(..., fused_floor=N)`. That keeps F out of the public
     `search_details`/`rerank` API and doesn't restate the rule. It has two real uses: acceptance
     at F = 3 and F = 0, and the post-live replay (spec item 3).
   - `--since` (ISO prefix, reusing `trace_query._iso_prefix`) selects only the floor3 live run's
     newly logged queries:
     - a named pure filter function is unit-tested;
     - question `ids` are built from **all** records before the time filter (the window-edge
       warning at `trace_query.py:78-80`);
     - `--since` with `--compare` is a usage error, like `--qid`.
   - The harness's own searches don't write `retrieval_search` events to `traces.jsonl` (the file
     it reads). That would be about 900 lines per run. Redirect or discard them the way
     `analyze_gate_replay.install_trace_capture` does.
   - Provenance: hash every `retrieval/*.py` (a `retrieval_sha256` per file, or one combined
     hash), not only `retrieval.py`.

Not shipped (spec item 1): model swap, ONNX, second stage, next-filing dates, length
normalisation, env switches.

### Risks

- **Exact-match acceptance hinges on a faithful port:** first-match regex semantics, the window
  header quirk, the stable sort in the CE ranks, and the date-before-FY order. Any "cleanup" that
  changes behaviour shows up as a gap at step 10, and that is where it should be caught.
- Latency rises to 3.5–4.9 s per search (accepted, spec item 5). The eval runtime grows to match.
- Strict scoping can drop a prior-year comparison column that lives only in the next filing.
  The 10 part hits this loses were measured and accepted (spec item 4).

## Files and steps

### Build order (TDD per `tdd-live-code-carveout`)

0. **On master, before branching: the replay-adjusted baseline.** `analyze_gate_replay` re-runs
   searches through `dispatch.hybrid_search`, so it must run before package 5's retrieval
   exists. Command: `python -m sec_agent.devtools.analyze_gate_replay --since <run start>
   --until <run end> --out var/trace_logs/replay-baseline-pkg5.json`, with the window taken from
   report `20261001T193130Z`. Record its per-question verdict changes in the plan's Results. No
   quota. Judged questions get no offline grade (`analyze_gate_replay.py:254` returns None).
   A judged question the replay flips from refusal to answer counts as **unknown** in the
   adjusted baseline. Step 14 compares on the deterministically graded questions, and reads
   traces for the unknowns.
1. Branch `package-5-retrieval`. Save this plan to `docs/plans/2026-10-02-package-5-retrieval.md`
   with a PROJECT_INDEX line.
2. **Manual script first (live code):** `tests/manual/verify_period_scoped_rerank.py`. Run it red
   against master's code; it then confirms green after the build:
   - "NVDA Q1 FY2026 revenue" scopes to `2025-04-27`, and every result has that `reportDate`;
   - a query with no date falls back, and its scope is `no_date`;
   - a long MSFT segment table chunk gets more than one window, with the header carried;
   - `search_details["results"] == hybrid_search(...)`;
   - re-combining `pool` + MaxP scores reproduces `results`.

   Update `tests/manual/verify_retrieval_replay.py`'s rebuild check to the MaxP scores.
3. `period_scope.py` tests then code (`tests/retrieval/test_period_scope.py`):
   - explicit date (±7 days; nothing in the window → FY path);
   - two explicit dates in one query → the union;
   - an impossible date (Sep 31, Feb 29 2025, day 0) is skipped, not raised;
   - FY with no quarter → 10-K only;
   - FY + Q, and the "second quarter" wording;
   - two-digit FY;
   - no match;
   - `None` ticker across companies;
   - a ticker'd caller passes only that ticker's filings, so another company's nearby date
     doesn't scope it.
4. `rerank_windows.py` tests then code:
   - header carry;
   - no carry outside tables;
   - line-boundary splits;
   - a single over-long line becomes its own window;
   - the caption is the last **non-blank** line before `<TABLE>`, even across a blank line;
   - `max_per_owner`.
5. `_combine_fused_and_rerank` tests: F = 0 equals pure CE order; F = 3 keeps a fused-rank-2 chunk
   with CE rank 15; the 1e-9 tiebreak; the rescue still applies under both, and the `rescued` id
   is reported. Update the existing max-of-ranks tests to the new rule. Each one changed is
   named in the commit body, with a reason.
6. List choice (pure helper, e.g. `_choose_lists(dates, filtered, unfiltered)`): strict, no
   dates, and both-filtered-empty fallback.
7. Wiring in `retrieval.py` (pragma-marked live lines only), `search_details`, logging.
8. Harness changes with tests (`tests/devtools/test_retrieval_replay.py`): the `rescue` cause,
   `fusion` with the floor, `--since` filtering, the `--fused-floor` parse.
9. Gates: `ruff check .`, `pyright .`, `pytest --cov=. --cov-report=term-missing -q`; 90% diff
   coverage on the critical core. Fire the `filtered_empty` path once (a date the index lacks,
   via a patched filing list in the manual script) and read the real log line.
10. **Offline acceptance (spec item 9, no quota).** First, count the V6-cache rows
    (`%TEMP%/claude/gold/v6.pkl`) whose scoped pool is empty. The `filtered_empty` fallback is
    new behaviour, not in the prototype. If the count is 0, the fallback can't move the figures;
    record that. Otherwise expect a gap, and explain it per row. Then run `retrieval_replay --compare
    var/retrieval_replay/base-v0-ce.json` at `--fused-floor 3`: it must give **526/901 and 37/40**.
    At `--fused-floor 0`: **599 and 34/40**. Any gap is a build bug (`debugging-discipline`), not
    noise. The F = 3 report becomes the new base report. The guard's exit 1 on V0's lost hits is
    expected, so read the figures, not the exit code. Note the `index_recall` share (BACKLOG line
    292's trigger).
11. `/compact` line to the user, then `independent-review-pass`: code-review high, `arch-reviewer`
    on Opus (critical core, plan path for spec conformance), security-reviewer (the query text is
    untrusted and goes into regexes and a Chroma `where`), `/simplify`. Review file
    `docs/reviews/2026-10-0X-package-5-retrieval.md`.
12. Decision file `docs/decisions/2026-10-0X-fused-floor-rerank-and-period-scoping.md`. It records
    the max-of-ranks revisit and links back under `Related` to
    `docs/decisions/2026-08-13-hybrid-retrieval-and-reranker-fix.md`. It also covers strict
    scoping and MaxP with the header carry. Add PROJECT_INDEX lines, and delete BACKLOG line 58.

### Live (spec items 3 and 10; quota)

13. On its own quota day, on a committed clean branch tree: a **full 48-question run** (~250
    requests): `python -m sec_agent.eval.eval_harness --backend gemini`. The spec's item 3
    replaces the reach table's panel 3× for this package; only the full run is done.
14. Compare it against the replay-adjusted baseline (step 0). A question that drops is explained
    from traces (WP8 style); a drop caused by retrieval blocks shipping. Re-mine refusals with
    the replay tool (the map's after-each-package rule).
15. Offline: `retrieval_replay --since <run start>` at F = 3 and at F = 0. Run `ce` live only if
    F = 0 newly covers a question that `floor3` missed live. Otherwise `floor3` ships and `ce` is
    not run.
16. Merge to master on the user's say. Update the map (package 5 struck, figures, next package
    3) and BACKLOG's in-progress line.

### Critical files

- New: `src/sec_agent/retrieval/period_scope.py`, `src/sec_agent/retrieval/rerank_windows.py`,
  `tests/retrieval/test_period_scope.py`, `tests/retrieval/test_rerank_windows.py`,
  `tests/manual/verify_period_scoped_rerank.py`.
- Changed: `src/sec_agent/retrieval/retrieval.py`, `tests/retrieval/test_retrieval.py`,
  `src/sec_agent/devtools/retrieval_replay.py`, `tests/devtools/test_retrieval_replay.py`,
  `tests/manual/verify_retrieval_replay.py`.
- Reused: `period_labels.fiscal_year_label` / `fiscal_quarter`, `companies.load_companies`,
  `tracing.log_event`, `trace_query._iso_prefix`, the existing `bm25_search` / `vector_search` /
  `_rescue_demoted_table_chunk`.
- Callers that are unchanged but get the new behaviour: `agent/dispatch.run_search`,
  `mcp_server` search, and `analyze_gate_replay`'s memoized search.

## Testing and verification

- **Step 0 (2026-10-02, master `9143665`):** `analyze_gate_replay --since 2026-10-01T19:20
  --until 2026-10-01T19:32` replayed all 48 runs of `20261001T193130Z` (errored 0, drifted 0,
  tool-result drift 0) → `var/trace_logs/replay-baseline-pkg5.json`. Refused 1 then, 0 now: the
  one recovery is `nvda-segment-revenue-comparison-q1fy27`, which is judged, so it's ungraded and
  counts as unknown. Newly refused 0; check changes 0. The adjusted baseline is therefore 42/48
  graded as run, with that one question unknown (it failed as a refusal in the run).
- **Step 10 pre-check:** the V6 cache has 0 of 512 queries with an empty pool (smallest 27), so
  the `filtered_empty` fallback can't change the acceptance figures.
- **Step 2/9:** `tests/manual/verify_period_scoped_rerank.py` ran red (ImportError) before the
  build, then green on all 6 checks: NVDA Q1 FY26 → `2025-04-27` only; `no_date`; the MSFT table
  chunk → 3 windows; `search_details` = `hybrid_search` and pool + scores rebuild the top 5 for
  3 queries (pools 34–35, 70–72 windows); the `filtered_empty` fallback returns 5 results, and
  its real log line was read. Gates: ruff clean, pyright 0 errors, 1238 passed, diff coverage
  98% (80% bar) and 100% on `retrieval/` (90% bar).
- **Step 10, offline acceptance (2026-10-02): exact match on both rules.** Both runs use
  `retrieval_replay --compare var/retrieval_replay/base-v0-ce.json` on the uncommitted build
  tree.
  - **F = 3** (`var/retrieval_replay/pkg5-f3.json`, the new base report): hit@5 **526/901**
    (58.4%), **37/40** covered, reach 883 (98.0%). Classes: rerank 357, dilution 17,
    period_confusion 1, index_recall 0. Rerank causes: fusion 104, model 253, rescue 0.
    Uncovered: aapl-3yr-avg-operating-margin and the two five-company margin rankings.
  - **F = 0** (`pkg5-f0.json`): hit@5 **599** (66.5%), **34/40**. Its uncovered list adds
    aapl-employees-fy25-indirect, nvda-inventory-turnover-fy2026 and
    nvda-revenue-two-quarter-comparison.
  - Both exit 1 on part hits lost against V0, as expected (the strict-scope and floor-rule
    losses the spec accepted).
  - `index_recall` is 0, so BACKLOG's HNSW trigger isn't met.
- **After review round 1 (2026-10-02):** F = 3 re-run with the reviewed harness
  (`var/retrieval_replay/pkg5-f3-r2.json`, the base report from here on): identical **526/901,
  37/40**, reach 883. The new `scope_excluded` class counts 0, and the rescue-first part cause
  moves nothing (fusion 104, model 253). The run started before the round-1 `/simplify` edits
  and the round-2 `best_gold` key, none of which changes a search; with `scope_excluded` at 0
  the key can't move a class either. Live script re-run green (6 checks), and the new
  `retrieval_scope_unknown_tickers` event fired once with NVDA dropped from the company list:
  scope fell back to the other companies' FY2026 10-Ks and the log line read
  `{"category": "retrieval_scope_unknown_tickers", "tickers": ["NVDA"]}`.
- **Final gates (2026-10-02):** ruff clean, pyright 0 errors, 1252 passed, diff coverage 100%
  overall and on `retrieval/`.
- **Step 13, live full eval (2026-10-03 UTC, commit `903e179`, clean tree):** report
  `eval/eval_results/20261003T030904Z.json`, run window 02:58:37–03:12 UTC, about 380 Gemini
  requests used that quota day. Result **44/48**, against the replay-adjusted 42/48.
- **Step 14, comparison against the step 0 baseline:**
  - Gained 4: `aapl-msft-employee-comparison` (the retrieval loss the map assigned to this
    package), `crm-buyback-and-liquidity-q1fy27`, `msft-three-segments-revenue-q3fy2026`, and
    `nvda-segment-revenue-comparison-q1fy27` (unknown in the baseline).
  - Dropped 2, both citation-gate refusals of a verbatim quote cited to the wrong source
    number. The quote is in a source the agent did retrieve, so neither is a retrieval drop and
    shipping isn't blocked:
    - `nvda-revenue-yoy-growth-q1fy27`: all four searches scoped correctly to `2026-04-26`. The
      model cited [12] (`0001045810-26-000052_34`, the segment table) for the income-statement
      `Total revenue` row quoted from [2], [14], [16] and [19].
    - `crm-ai-risk`: the quote cited as [13] (`0001108524-26-000060_51`) is verbatim in [15]
      (`_52`, the next chunk of the same risk factor). The gate's retry repeated it.
  - Still failing in both runs: `pltr-dividend-2019-refusal` and
    `msft-segment-revenue-comparison-q3fy2026` (judged).
  - Re-mine (`analyze_gate_replay --since 2026-10-03T02:58:37 --until 2026-10-03T03:12`,
    `var/trace_logs/replay-pkg5-live.json`): 48 replayed, errored 0, drifted 0; refused 2 then
    and 2 now, recovered 0, newly refused 0, check changes 0, tool-result drift 0. Today's gate
    agrees with the run.
- **Step 15, offline replay of the live run's queries** (`retrieval_replay --since
  2026-10-03T02:58:37`; 45 parts, 4 out-of-scope skipped, 16 questions):
  - **F = 3** (`var/retrieval_replay/pkg5-live-f3.json`): hit@5 25/45, reach 44, **16/16**
    covered. Classes: hit 25, rerank 19, dilution 1. Rerank causes: fusion 9, model 10.
  - **F = 0** (`pkg5-live-f0.json`): hit@5 30/45, reach 44, **13/16** covered. Uncovered:
    `aapl-cash-and-buyback-q3fy2026`, `aapl-employees-fy25-indirect`,
    `aapl-msft-employee-comparison`.
  - F = 0 newly covers no question that F = 3 missed, so `ce` is not run live and F = 3 ships.
    The live queries repeat the offline pattern: F = 0 gains part hits and loses whole questions.

## Plan review

Round 1 (`plan-reviewer`, Opus, 2026-10-02). Verdict: the port is faithful, and step 0 and the
acceptance query set are correct.
- **[High, folded in]** An impossible explicit date raises `ValueError` from untrusted query text
  and kills the agent run or MCP request. It is now skipped and logged, with a test. This is the
  one deliberate deviation from the prototype.
- **[Med, folded in]** The filing list must be scoped to the ticker, as in the prototype's
  `_filings(ticker)`; stated in item 1 and tested.
- **[Med, folded in]** Explicit dates are a `findall` union, not first-match-returns; the caption
  is the last non-blank line. The wording and tests are fixed.
- **[Med, folded in]** The `filtered_empty` fallback isn't in the prototype. Step 10 now counts
  empty-pool rows in `v6.pkl` before acceptance.
- **[Med, folded in]** The harness would write about 900 events per run into the trace file it
  reads. Its events are now redirected, as `install_trace_capture` does, and `scope` is logged
  as a sorted list.
- **[Low, folded in]** F is recombined in the harness from the exposed `scores` through the pure
  `_combine_fused_and_rerank`, instead of being threaded through the public API. The default is
  read at call time.
- **[Low, folded in]** `--since`: ids are built before filtering, it's rejected with
  `--compare`, and it has a named pure filter under test.
- **[Low, folded in]** Judged questions in the step 0 replay have no offline grade. Their flips
  count as unknown and are read from traces in step 14.
- Checked fine by the reviewer: step 0 is needed (the gate replay memoizes the live
  `dispatch.hybrid_search`); `--compare base-v0-ce.json` replays the cache's exact query set; the
  floor formula, stable sort and rescue match `cache_sim`; the `rescue` cause is well defined
  (the rescue replaces only the last slot); the date regexes don't backtrack.

## Review log

Full findings and dispositions: `docs/reviews/2026-10-02-package-5-retrieval.md`.

- **Round 1** (snapshot `94908ad`): `/code-review` high, `arch-reviewer` (opus),
  `security-reviewer`, `/simplify` (4 agents). 13 fixed, 4 deferred → BACKLOG, the rest
  verified with no fix needed. Security found nothing.
- **Round 2** (delta from `94908ad`): `/code-review` medium, arch (opus), security. 4 fixed,
  including the `best_gold` ordering bug.
- **Round 3** (the round-2 fixes): `/code-review` low, arch (opus), security. 2 fixed (a test
  pinning the ordering, and nits), each new test mutation-checked. Closed clean.

## Addendum (2026-10-02, during the build)

- **`fused_floor` is a parameter of `search_details` after all.** Plan item 4 had the harness
  recombine `pool` + `scores` itself, but the table rescue needs each candidate's text and
  metadata, which ids and scores alone don't carry. Exposing the candidate tuples would have
  been the bigger API. So `search_details(..., fused_floor=None)` passes it to
  `_combine_fused_and_rerank`, with `None` meaning `_FUSED_FLOOR_RANKS` read at call time (the
  review's default-binding concern still holds). The event logs the floor actually used.
- **`rerank()` was removed.** It had no caller outside `retrieval.py`; `search_details` does the
  scoring and combining, and `hybrid_search` wraps it.
- **TDD slip:** `period_scope.py` was written before its tests were run red. To make up for it,
  three mutants (tolerance 0, FY path always taken, two-digit years +1900) were each run against
  the suite, and each was killed (2, 4 and 1 failures). `rerank_windows`, the floor rule,
  `_choose_lists` and the harness went red-first. Hand-tracing the prototype's algorithm
  corrected two expected values in `test_rerank_windows.py` and one in `test_retrieval.py`
  before implementation.
- **`hybrid_search(use_rerank=False)` logs no `retrieval_search` event.** It's the CLI
  `--no-rerank` and manual-script diagnostic path, with no windows, floor or rescue to record;
  the plan's "one event per search" means per reranked search.
