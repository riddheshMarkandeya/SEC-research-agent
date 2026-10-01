# Review: offline retrieval gold-rank harness (`retrieval-harness` branch)

Plan: `docs/plans/2026-09-30-retrieval-gold-rank-harness.md`. The branch adds
`src/sec_agent/devtools/retrieval_replay.py` (it replays logged `search_filings` queries
against hand-checked gold chunks and classifies each miss), 247 gold rows in
`eval/retrieval_gold.jsonl`, unit tests and a manual live script. No production code changes.
Review depth: Substantial (1,460 lines).

## Round 1

Diff: `master...b0e4fd0`. Passes: `/code-review` high, `arch-reviewer` (opus),
`security-reviewer`, then `/simplify` (reuse, simplification, efficiency, altitude).

1. **[High]** (code-review): the rerank cause came from the best gold chunk by pool position,
   not the one the cross-encoder ranked best. `[Fixed]`: it now uses the part's pooled gold chunk
   with the best ce rank, and a test pins the difference.
2. **[High]** (code-review): an HNSW recall miss (exact vector rank in the top 25, but the
   approximate search left it out) was classed as dilution, period_confusion or other_ticker.
   `[Fixed]`: new `index_recall` class.
3. **[Med]** (code-review): `period_confusion` won over `other_ticker` whenever a single
   same-ticker other-filing chunk was ahead, even with dozens of other tickers' chunks ahead.
   `[Fixed]`: the larger count decides.
4. **[Med]** (code-review, arch): `rank_stats` scanned the ranking twice and had an unreachable
   `return None` marked no-cover. `[Fixed]`: one pass, which now also returns
   `other_ticker_ahead` (from `/simplify`).
5. **[Med]** (code-review, arch): `propose_gold` centred each snippet with `text.find(token)`,
   which picks the first occurrence. `[Fixed]`: `figure_matches` returns match objects.
6. **[Med]** (code-review): in compare mode the report header described the current CLI
   arguments, not the base's query set. `[Fixed]`: it inherits the base's `trace_file`, `qids`
   and `gold_questions_without_queries`.
7. **[Low]** (code-review): a `--qid` with no gold gave an empty report and exit 0. `[Fixed]`:
   usage error.
8. **[Low]** (arch): a missing gold file, or a missing or malformed `--compare` base, gave a
   traceback. `[Fixed]`: a `retrieval_replay: ...` message and exit 2.
9. **[Low]** (arch): the manual script repeated the search-span filter. `[Fixed]`: `search_key`
   is shared.
10. **[Low]** (arch): plan wording on ticker filtering and the thousands-matching deviation.
    `[Fixed]`.
11. **[Med]** (code-review, arch): the harness rebuilds the cross-encoder ordering and the
    rerank cause outside `hybrid_search`. `[Fixed, docstring]`: the ce scores come from
    `retrieval._get_rerank_model()`, so prototype rerankers were measured correctly (arch's
    claim otherwise was wrong). What is restated is the max-of-ranks rule and the rescue gate;
    the docstrings say so, and package 5's spec must update `rerank_cause` with the rule or
    expose retrieval's ranks.
12. **[Med]** (code-review): a chunk that the table rescue pushes out of the cross-encoder's top 5
    is classed `fusion`. `[Deferred → BACKLOG]`: telling it apart needs retrieval's own combined
    ranking, the same seam as item 11.
13. **[Low]** (code-review): each query runs the cross-encoder twice and BM25 and the embedding
    three times. `[Deferred → BACKLOG]`: runtime only, inside a 15-45 minute run.
14. **[Nit]** (arch): `trace_query._safe` and `eval_harness._git_state` are private names used
    across modules. `[Disputed]`: devtools reuse them read-only, and renaming them would touch
    modules outside this branch.
15. security: no findings.
16. `/simplify`: fixed a test helper's nested default for `pool`. Skipped: reusing
    `numeric_utils`' parser and `normalize_for_match` for gold anchors, because both would change
    matching that the 247 gold rows were hand-checked against. Skipped: a `_fail()` helper for
    two call sites.

## Round 2

Delta: `git diff b0e4fd0`, 3 files. Passes: `/code-review` low, `arch-reviewer` (sonnet),
`security-reviewer`.

1. **[Med]** (code-review): a `--compare --qid X` run would write the base's `qids` into its
   header. `[Verified, no fix needed]`: `main` rejects `--compare` with `--qid` as a usage error.
2. arch: no findings; it checked each round-1 fix against the delta.
3. security: no findings.

## Live verification

`tests/manual/verify_retrieval_replay.py` ran against the real index after the fixes: OK, 28 of
30 logged queries reproduce `hybrid_search`'s order exactly, and the other 2 are HNSW recall
misses, now classed `index_recall`.

## Outcome

Shipped as `ed50efd` and merged to master in `49e794f`. Final suite: 1,143 passed, ruff and
pyright clean, 98% diff coverage. The review closed clean in round 2. Still open in `BACKLOG.md`:
the rescue-displacement class (`[design, Low, Standard]`) and the duplicate passes
(`[performance, Low, Standard]`), under the 2026-09-30 retrieval-harness section.
