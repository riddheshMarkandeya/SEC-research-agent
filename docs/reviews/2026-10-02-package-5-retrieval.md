# Review: package 5, strict period scoping, windowed MaxP rerank and fused-floor rule

Plan: `docs/plans/2026-10-02-package-5-retrieval.md`. The change adds `retrieval/period_scope.py`
and `retrieval/rerank_windows.py`, rewires `retrieval.py` (scoped pool, MaxP scoring, floor rule,
the `search_details` seam, a `retrieval_search` event) and moves `devtools/retrieval_replay.py`
onto that seam. The suite stood at 1238 before review. The diff is Substantial by its paths
(`retrieval/` is critical core) and its size (~970 lines).

## Round 1

Passes: `/code-review` high, `arch-reviewer` (opus), `security-reviewer`, `/simplify` (reuse,
simplification, efficiency and altitude agents). Snapshot `94908ad`.

1. **[Med]** (code-review, arch): `period_scope._fiscal_dates` raised `KeyError` for a chunk
   ticker missing from `companies.json`, which would fail every unticker'd fiscal-year search.
   `[Fixed]` The filing is skipped, with a test. `_query_scope` logs
   `retrieval_scope_unknown_tickers`, and that line was fired once and read.
2. **[Med]** (code-review): `classify` judged pool misses by unscoped ranks, so a gold chunk the
   period scope left out was misattributed. `[Fixed]` Added a new `scope_excluded` class, with
   the report date threaded from `index_gold`.
3. **[Low]** (code-review): `_part_rerank_cause` undercounted `rescue`. `[Fixed]` It returns
   `rescue` when the rescue swapped out any of the part's gold chunks.
4. **[Low]** (code-review): the combine docstring said "ties go to the cross-encoder", which is
   only true inside the floor. `[Fixed]` The docstring now states both cases. The scoring is
   unchanged because it is a prototype port.
5. **[Low]** (code-review): the provenance hash missed `period_labels.py` and `companies.json`.
   `[Fixed]`
6. **[Low]** (code-review): the carried table header has no token budget, and after one table
   the caption is `</TABLE>`. `[Deferred → BACKLOG]` This behaviour is faithful to the
   prototype that acceptance was measured on, so changing it needs a new measurement.
7. **[Low]** (code-review, simplify-efficiency): per-search re-tokenizing and the per-search
   filing-list walk. `[Verified, no fix needed]` Each costs well under 2% of the cross-encoder's
   3–5 s.
8. **[Risk]** (arch, code-review): the `_rescue_demoted_table_chunk` docstring retold an
   incident. `[Fixed]` It now states the general reasoning.
9. **[Risk]** (arch): `search_details` was entirely pragma'd, so its pure assembly had no unit
   test. `[Fixed]` Extracted the pure `_search_record`, tested three ways. The floor is resolved
   once and returned as `fused_floor`.
10. **[Risk]** (arch): the plan didn't follow the template headings, and its results were split
    across sections. `[Fixed]` Restructured; results now live in "Testing and verification".
11. **[Nit]** (arch, simplify-reuse/altitude): `_live_retriever` silenced tracing for the whole
    process as a hidden side effect. `[Fixed]` Moved into `main()` and restored in `finally`. A
    shared tracing helper is `[Deferred → BACKLOG]`, since it reaches `analyze_gate_replay`.
12. **[Nit]** (arch): the `rescued` list key was unused. `[Fixed]` Dropped from the harness.
13. **[Nit]** (arch, simplify-altitude): `search_details` returns an untyped dict.
    `[Deferred → BACKLOG]` (TypedDict).
14. **[Nit]** (arch): the scope dataclass and the scope dict were both named `scope`. `[Fixed]`
    The dict is renamed `scope_record`. Also: `_TWO_DIGIT_YEARS` became `_TWO_DIGIT_YEAR_LIMIT`,
    and a stale test comment was fixed.
15. **[Q]** (arch): `hybrid_search(use_rerank=False)` logs no event. `[Verified, no fix needed]`
    It is a diagnostic path with no rerank to record; noted in the plan's Addendum.
16. **[Low]** (simplify-reuse): the new fiscal-year-end cache contradicted `load_companies()`'s
    documented uncached design. `[Fixed]` Removed.
17. **[Low]** (simplify-altitude): scoping on bare dates admits other companies' same-date
    filings when no ticker is given. `[Deferred → BACKLOG]` Prototype semantics; it needs
    measuring.
18. **[Nit]** (simplify-simplification): `_unscoped_miss_class` renamed to `_pool_miss_class`;
    `strict=True` added to `max_per_owner`'s zip. `[Fixed]` Other simplify items
    (where-clause rewrite, inlining `_search_record`, `mock.patch`, `calendar.month_name`) were
    `[Verified, no fix needed]`: marginal, or they would undo a tested seam.
19. Security: no issues. ReDoS, the impossible-date exception, Chroma `where` injection (dates
    come from the index, not the query), log injection and resource use were each checked and
    disproved.

## Round 2

Delta: `git diff 94908ad`. Passes: `/code-review` medium, `arch-reviewer` (opus),
`security-reviewer`.

1. **[Med]** (code-review): `best_gold` could pick a scope-excluded gold chunk over an
   in-scope one that also missed the pool, which misclassified the part. `[Fixed]` Added
   `scope_excluded` to the sort key after `pool_pos`, with a test.
2. **[Risk]** (arch): no test checked that `main()` suppresses and restores the trace writer.
   `[Fixed]` Added a parametrized test covering the success and exception paths. A mutant with
   the restore removed was killed.
3. **[Nit]** (arch): `_part_rerank_cause` computed the causes twice; two docstrings read badly.
   `[Fixed]` Bare `p.name` provenance keys and the hard-coded floor 3 in one test were
   `[Verified, no fix needed]`: no collision exists, and that test's arithmetic depends on 3.
4. **[Q]** (arch): the step 10 class breakdown predated the new classes. `[Fixed]` The F = 3
   re-run is recorded in the plan; it is identical apart from `scope_excluded` 0.
5. Security: no issues. The per-search `load_companies()` read fails only on an operator-side
   file, never from a query.

## Round 3

Delta: the round-2 fixes. Passes: `/code-review` low, `arch-reviewer` (opus),
`security-reviewer`.

1. **[Risk]** (arch): no test pinned `pool_pos` ranking ahead of `scope_excluded`, so the
   round-2 bug could come back unseen. `[Fixed]` Added a pooled-and-excluded case. The
   reintroduced bug, run as a mutant, was killed.
2. **[Nit]** (arch, code-review): the restore test didn't prove the retriever ran, and it
   called the private writer; one docstring line overran; the `_live_retriever` docstring was
   stale. `[Fixed]`
3. Security: no issues.

The round-3 fixes were test-only plus docstrings, and each new test was mutation-checked, so no
round 4 ran.

## Live verification

- `tests/manual/verify_period_scoped_rerank.py`: green on all 6 checks after round 1.
- `retrieval_scope_unknown_tickers` fired once with NVDA dropped from the company list, and its
  log line was read.
- Offline acceptance re-run at F = 3 (`var/retrieval_replay/pkg5-f3-r2.json`): 526/901 and
  37/40, identical to step 10.
- The live 48-question eval (plan steps 13–14) is still pending and needs quota.

## Outcome

Closed clean after 3 rounds: 19 fixed, 4 deferred to `BACKLOG.md` under "From the 2026-10-02
package 5 review" (`[design, Low, Standard]` ×2, `[refactor, Low, Standard]`,
`[refactor, Low, Trivial]`). Final gates: ruff clean, pyright 0 errors, 1252 passed, diff
coverage 100% overall and on `retrieval/`.
