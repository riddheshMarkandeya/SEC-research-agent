# Plan: offline retrieval gold-rank harness

**Resume here (after /clear):**
- **Status (2026-10-01, ~21:30Z):** all measurements done, and package 5's spec is written (end
  of this file). Track A step 1 is done on master: full run 42/48, committed as `509f626`.
  Track B is mid-review: round 1 and `/simplify` are applied but **uncommitted** on
  `retrieval-harness` (3 files). They're green: 1,143 tests, ruff and pyright clean, 98% diff
  coverage, and the manual script ran live OK. The Review log at the end of this file lists every
  finding.
- **Next, in order:**
  1. ~~Round 2 review~~: done 2026-10-01, clean (see the Review log).
  2. ~~Commit the fixes~~: done as `ed50efd`. Original step: commit the fixes on `retrieval-harness`. Body: the review line and the class changes
     (`index_recall`, `other_ticker` vs `period_confusion`, the `other_ticker_ahead` field).
  3. ~~Merge~~: done as `49e794f`; master green after (1,143 passed, ruff/pyright clean).
     Original step: merge `retrieval-harness` into master. Track A step 1 is done, so the merge is unblocked.
  4. ~~Docs commit~~: done 2026-10-01 on master. The HNSW item went to the Watch list and names
     its revisit of `4c6850c`. Original step: docs commit on master (after the merge, so `PROJECT_INDEX`/`BACKLOG`/map don't conflict):
     - this plan and `docs/research/2026-09-30-rerank-improvement.md`;
     - a `docs/reviews/2026-10-01-retrieval-harness.md` review file (Substantial; findings
       deferred and disputed);
     - `PROJECT_INDEX` lines for the plan and the review;
     - on the map: the S5 ticket's figures (V0 329/901 and 31/40; V6 469 and 37/40; the rule
       table), a rerank ticket, and package 5 retitled to "strict period scoping + windowed
       MaxP rerank + fused-floor rule";
     - `BACKLOG` items: the HNSW recall miss, V3/V4 deferred, the two deferred review findings
       (rescue-displacement class, duplicate cross-encoder pass), and gte-multilingual's
       incompatibility with transformers 5.15.
  5. Then track A on master, in the order the user set on 2026-10-01: package 2, then package 5,
     then packages 3 and 4. Original step: track A packages 2-4 on master. Package 2 should take the new High backlog bug: the
     gate rejects a verbatim two-row table quote.
- **Prototypes:** `stash@{0}` holds all the V6/V7 prototypes (also in
  `%TEMP%/claude/gold/protos.patch`); `stash@{1}` and `stash@{2}` hold the older V5 and V1/V2.
  None of them gets committed.
- **Gemini quota:** about 250 requests were used on 2026-10-01 by the full run (19:19-19:31Z).
- Commits on the branch: `ed377f0`, `2ee634c`, `b2cf09c`, `58df744`, `8d96c62`, `b0e4fd0`, `ed50efd`.

Tier: Substantial (a new tool, with real design choices). After plan review there are **no
production code changes**: the tool calls `hybrid_search` as it is. The tool lives in
`devtools/`, outside the critical core, so its changed lines need 80% diff coverage.

## Carry-over: retry slot (package 1), still pending

- The retry slot is committed as `f6a75db`, agent fingerprint `4051dbdc19a7`.
- Panel 3× (`20260930T205234Z`, `205532Z`, `205927Z`): 39/39.
- Explicit-mode compare against B (`071313Z`, `071948Z`, `072319Z`): no REGRESSED, and
  pltr-inventory went 1/3 → 3/3.
- The panel logged 9 citation_retry events (1 forced) and 0 gate refusals.
- About 270 of 500 requests were used on 2026-09-30.

Still to do:
1. After the quota reset (07:00Z 2026-10-01), run the full 48-question run **from master at
   `f6a75db`**. The harness work stays on its own branch, so that run measures only the retry
   slot.
2. Re-mine the refusals: count the post-budget retries and how many they rescue.
3. A docs commit containing:
   - the 3 untracked panel reports and the full-run report;
   - `docs/decisions/2026-09-30-citation-retry-own-slot.md`: it reverses 0ba1e5d, and its
     Related section links the 2026-08-24 plan and `2026-09-16-final-turn-safety-net.md`;
   - the improvement map's package 1 marked done;
   - a PROJECT_INDEX line.

## Context

The improvement map ticket "Segment-table ranking / period-scoped retrieval (review S5)" says to
pick a variant with an offline gold-rank harness first.
- **The problem:** MSFT's Q3 FY26 segment table ranks 25–103, outside the 25-candidate pool, so
  the reranker never sees it. That caused 10 "not found" fails on msft-three-segments.
- **What's known so far:** a throwaway BM25-only simulation
  (`docs/research/2026-09-28-financial-table-retrieval.md`) suggests a period filter brings the
  table into the pool. But it covered only 3 queries, and vector ranks weren't simulated.
- **What the harness adds:** it measures retrieval on every logged query against labelled gold
  chunks, offline, with no quota, and with a regression guard. So this retrieval choice, and any
  later one, is measured before it ships. The 2026-08-16 period-label attempt, which was
  reverted, had no such guard.

## Decisions (grill-me with the user, 2026-09-30; confirmed)

1. **Replay logged queries through the checked-out retrieval code**, offline, with no LLM calls.
   - Every `search_filings` span in `var/trace_logs/traces.jsonl` is joined to its eval question
     id.
   - The set is limited to current questions that have gold, and deduplicated on (query,
     ticker). Each deduplicated query keeps the set of qids it was logged under.
   - Traces log only `result_count`, so there are no past ranks to read: everything is re-run.
2. **Gold = filing accession + anchor text**, not chunk IDs, so labels survive re-chunking.
   - A chunk is gold when its `accessionNumber` matches and its text contains the anchor,
     compared with whitespace normalized.
   - Labels are auto-proposed, every one is hand-checked, and they're committed as
     `eval/retrieval_gold.jsonl`.
3. **Covered questions: figures that come from filings.**
   - Numeric and comparison questions, plus the judged questions whose criteria name figures.
   - Derived ratios are labelled by the chunks holding their input figures.
   - Narrative and refusal questions are excluded.
4. **Hits.**
   - Any chunk holding the figure counts, tagged own-period or other-period (a later filing's
     prior-period column).
   - A query hits when any of its questions' gold is in its top 5.
   - A question is covered when every part is reached by at least one of its queries.
5. **Metrics:**
   - gold's ranks in BM25 and vector search;
   - whether gold reaches the reranker;
   - the final rank, where top 5 counts as a hit;
   - a miss class;
   - a regression guard in `--compare`.

   The exact definitions are in Change.
6. **Variants are not code in the tool.** Base and compare work like `analyze_gate_replay`:
   save a base report on today's code, change the real `retrieval.py` (uncommitted), then run
   again with `--compare`. A winning variant becomes the production change, and a losing one is
   discarded, so nothing piles up in the tool.
7. **Deliverable:**
   - the tool, the gold labels and the V0 baseline;
   - V1 (period-filtered lists added to rank fusion) and V2 (a strict period filter), measured
     as throwaway prototypes and then stashed. Package 5 builds the winner properly, with TDD;
   - V3 (month de-glue) and V4 (tables split out) only if the baseline shows enough dilution
     misses. They need `--chunks-dir`/`--chroma-dir` options, which aren't built now (YAGNI).

## Change

### 1. `src/sec_agent/devtools/retrieval_replay.py` (new; `retrieval.py` untouched)

**Measure** through the production path. This part is live-only and marked `# pragma: no cover`.
Per query:
- **Pool:** `hybrid_search(q, ticker, top_k=10**6, use_rerank=False)` returns the whole fused
  candidate pool from the real code. If gold is in it, gold reaches the reranker.
- **Final:** `hybrid_search(q, ticker)` with the default `top_k=5`.
  - That's exactly what `run_search` gets (`agent/dispatch.py`, `CHUNKS_PER_SEARCH=5`), table
    rescue included.
  - Any experiment inside `hybrid_search` is measured automatically.
- **BM25 diagnostic rank:** `bm25_search(q, big_n, ticker)`.
  - `big_n` is the ticker's chunk count, or the corpus size (3,182) when the ticker is None.
  - A gold chunk BM25 scores 0 on is `unranked`.
- **Vector diagnostic rank, computed exactly:**
  - Embed the query the way `vector_search` does: the embedding model plus
    `QUERY_INSTRUCTION`.
  - Take a dot product against every stored embedding, from one
    `collection.get(include=["embeddings", "metadatas"])` call cached per run.
  - This avoids large-k filtered HNSW queries, whose completeness hasn't been verified.
- The diagnostic ranks come from lists that aren't period-filtered but are ticker-filtered as the
  query is. Pool reach and the final rank come from the real path.

**Pure functions (TDD):**
- `build_query_set(records, ids, gold_qids) -> (queries, dropped)`
  - It reuses `trace_query.load` and `trace_query.question_ids`.
  - It dedupes on (query, ticker) and keeps each query's qid set.
  - It reports as dropped the spans whose run didn't join to a question id, and those whose
    qid has no gold.
- `load_gold(path)` and `gold_matches(chunk_text, metadata, gold_rows)`
  - Matching is containment with whitespace normalized, and a chunk must match both the
    accession and the anchor.
  - It returns every matching row: the part, the own-period tag and a gold-chunk key.
- **Per (query, part), for each gold chunk separately:**
  - the BM25 rank and the vector rank, or `unranked`;
  - `other_filing_ahead`: how many same-ticker chunks from other filings outrank it;
  - `own_filing_rank`: its rank among chunks of its own filing.
- **The part's best gold:** the gold chunk with the best final rank. Ties go to the best pool
  position, then the best diagnostic rank.
- **Miss classes**, taken on the best gold chunk with the better of the two retrievers:

  | Class | Meaning |
  |---|---|
  | `hit` | in the top 5 |
  | `rerank` | in the pool, cut at rerank |
  | `period_confusion` | not in the pool; own-filing rank ≤ 10 and `other_filing_ahead` ≥ 1 |
  | `dilution` | not in the pool; own-filing rank > 10 |
  | `unranked` | no retriever ranks it |

  The own-filing threshold is 10, not 25: a filing holds about 120 chunks, so 25 would be too
  loose.
- **Aggregates:** hit@5 per (query, part), the reach rate, per-question coverage, and counts by
  miss class and by own-period vs. other-period.

**CLI**, mirroring `analyze_gate_replay`'s `_parser`:
- The flags are `--file`, `--questions`, `--gold`, `--qid` (repeatable, for a quick loop),
  `--out`, `--compare BASE` and `--propose-gold OUT`.
- The report header records the git SHA, a dirty flag, the gold-file hash, the `retrieval.py`
  hash, the dropped counts and the runtime.
- **`--compare` replays the base report's own query list** instead of re-reading
  `traces.jsonl`, which grows between runs. It refuses to run if the gold hash differs.
- **Guard:** exit 1 if any (query, part) that hit in the base doesn't hit now, or if any
  question's coverage drops. It prints the gains, losses, class deltas, and the hit@5 and reach
  deltas.

**`--propose-gold`** writes a scratch file for hand review, never the committed gold.
- For each covered question and part, it finds the ticker's chunks that contain the expected
  figure in any plausible filing format:
  - millions (`35,013`);
  - billions converted to millions;
  - thousands, as a prefix match on the millions figure (PLTR and some AAPL tables);
  - percent (`32.6`, `32.6%`);
  - per-share decimals (`2.94`);
  - negatives in parentheses.
- Comparison parts take their ticker from `expected[].ticker`: entity labels like `MSFT-PBP`
  map to `MSFT`.
- Each match is listed with its accession, reportDate, chunk index and a 200-character snippet.
- Derived ratios and figure-bearing judged questions are labelled by hand. That's explicitly
  budgeted.

### 2. `eval/retrieval_gold.jsonl` (new, hand-checked)
- A row is `{qid, part, accession, report_date, anchor, own_period, note}`.
- The anchor is a short verbatim snippet: the figure plus its row label, so a bare figure can't
  match an unrelated chunk.
- A figure in two chunks of one filing gets two rows, and both are gold. Example: MSFT `35,013`
  is in chunk 35 (the segment note) and chunk 47 (the MD&A table).
- `own_period` is a hand label, since chunk metadata has no fiscal-period field.
- Every row is reviewed, and ambiguous cases are recorded in `note`.

### 3. Tests: `tests/devtools/test_retrieval_replay.py`, TDD, pure functions only
- the query-set join, qid sets, dedupe and dropped counts;
- gold matching: whitespace, an accession mismatch, several gold chunks, own vs. other period;
- best-gold selection and every miss class, including `unranked`;
- the coverage aggregate;
- the compare guard: a lost part-hit or lost coverage exits 1, a gain doesn't, and a gold-hash
  mismatch is refused;
- compare replaying the base report's query list;
- the propose-gold formats: thousands prefix, percent, decimals, negatives.

### 4. Manual script: `tests/manual/verify_retrieval_replay.py` (live-code rule)
- On about 30 sampled queries, the tool's final top 5 equals a direct `hybrid_search(q, ticker)`.
- The exact vector ranks agree with `vector_search(q, 25, ticker)` on the top 25.
- It prints chunk 35's ranks for the research note's three MSFT queries.
- Add the tool's live binding to `.claude/rules/live-code-tdd.md`'s list.

### 5. Measurements (throwaway prototypes, not committed)
- **V0:** the full base report `var/retrieval_replay/base-v0.json`. Read the miss classes.
- **V1:** a quick period parser inside `hybrid_search` that adds filtered BM25 and vector lists
  to rank fusion, then `--compare`. Explicit dates map to `reportDate`; FY and quarter go through
  `period_labels`.
- **V2:** the same parse used as a strict filter, then `--compare`.
- Stash both, and record the figures in the map ticket.
- Runtime: about 920 query pairs before the gold filter, at about 1–3 s of CPU rerank each, so
  roughly 15–45 minutes per full run. Iterate with `--qid` first.

## Files
- `src/sec_agent/devtools/retrieval_replay.py` (new)
- `tests/devtools/test_retrieval_replay.py` (new)
- `tests/manual/verify_retrieval_replay.py` (new)
- `eval/retrieval_gold.jsonl` (new)
- `.claude/rules/live-code-tdd.md` (add the live binding)
- Docs:
  - a plan copy at `docs/plans/2026-09-30-retrieval-gold-rank-harness.md` (step 1 after
    approval);
  - a PROJECT_INDEX line and a review file;
  - the map ticket updated with the V0/V1/V2 figures;
  - a BACKLOG item for V3/V4, if the dilution misses warrant it.

## Branch and commits
- Work on the branch `retrieval-harness`. That keeps master clean at `f6a75db` for tomorrow's
  full run, and no V1/V2 stash can end up in its tree. Merge after the run.
- Commit 1: the tool, its tests and the manual script.
- Commit 2: the gold labels.
- Commit 3: docs and figures.

## Verification
1. `ruff check .`, `pyright .` and `pytest --cov` on the full suite pass, with 80% diff coverage
   on the tool. Live-only lines are pragma'd.
2. `tests/manual/verify_retrieval_replay.py` passes:
   - the top 5 equals `hybrid_search`;
   - the exact vector ranks agree with HNSW on the top 25;
   - it shows chunk 35's MSFT ranks, next to the research note's BM25 ranks of 40, 45 and 29.
3. Gold review: every row is checked, and about 10 are checked against the filing text directly.
4. The full V0 run completes, and the report states the dropped counts in its header.
5. `retrieval.py` is untouched, so no live eval spot-check is needed.

## Plan review

`plan-reviewer` (Opus). Verdict: sound, but revise before building. Every finding was folded in:
1. **The seam refactor isn't needed.** Two `hybrid_search` calls measure the real path, so
   there's no critical-core diff.
2. **`--compare` would re-read a growing trace log.** It now replays the base report's query
   list and checks the gold hash.
3. **One figure can sit in several chunks** (MSFT chunks 35 and 47). Ranks are now kept per gold
   chunk, with a best-gold rule, and the reproduction check uses chunk 35.
4. **`--propose-gold` missed thousands, percents and decimals.** Those formats are added, and
   hand-labelling time is budgeted.
5. **The miss classes were underspecified.** They now use the better of the two retrievers on
   the best gold chunk, add `unranked` and `other_filing_ahead`, and use an own-filing
   threshold of 10.
6. **Large-k filtered HNSW queries are unverified.** Vector ranks now come from an exact dot
   product, checked against HNSW on the top 25.
7. **Deduping on (query, ticker) collides across qids.** Each query now keeps its qid set.
8. **The guard was per query, not per part.** It's now per (query, part), plus per-question
   coverage.
9. **The manual script and the live-code list were missing.** Added
   `verify_retrieval_replay.py` and the rule-file entry.
10. **Join failures were dropped silently, and a None ticker wasn't handled.** The header now
    reports dropped counts, and `big_n` falls back to the corpus size.
11. **Runtime wasn't stated.** It's about 15–45 minutes per full run, with a `--qid` loop for
    iteration.

## Results so far (2026-09-30)

All runs replay 512 deduplicated queries; 901 in-scope (query, part) pairs, 424 out of scope
(a query whose ticker filter excludes every gold chunk of the part). V0 = `b2cf09c`, clean tree.

| | V0 | V1 fuse | V2 strict |
|---|---|---|---|
| hit@5 | 329 (36.5%) | 382 (42.4%) | 445 (49.4%) |
| pool reach | 89.6% | 98.0% | 98.0% |
| rerank / dilution / period_confusion | 478 / 66 / 28 | 501 / 17 / 1 | 438 / 17 / 1 |
| questions covered | 31/40 | 32/40 | 33/40 |
| part hits gained / lost | | 63 / 10 | 126 / 10 |

- Both variants fail the guard (exit 1). V1's 10 losses were marginal V0 hits (rank 3-5) cut at
  rerank. All 10 of V2's were V0 hits through a later filing's prior-period column, which the
  strict filter removes; the own-period chunk is then cut at rerank.
- V0's misses are mostly rerank (478 of 572), with gold already in the pool. That's what
  Addendum A investigates.

Deviations from the plan, found by the first runs:
- An `other_ticker` miss class (unfiltered queries; only other tickers' chunks outrank gold).
- Out-of-scope parts aren't scored (the first V0 marked 424 cross-ticker pairs `unranked`), but
  still count against question coverage.
- The report header captures git state and the `retrieval.py` hash before the run.
- Thousands-scale figures are matched by scaling and rounding at 1e3/1e6/1e9, not by a prefix
  match on the millions figure. That's stricter, and the tests cover it.
- From the review (2026-10-01): an `index_recall` class (exact vector rank within the 25
  candidates, yet HNSW left the chunk out), and `other_ticker` vs `period_confusion` decided by
  which kind of chunk outranks gold more. Reports before then use the older classes; hits and
  coverage are unchanged.

## Addendum A: cross-encoder rank diagnostic (user-approved 2026-09-30)

Splits the `rerank` misses by cause, so the rerank research targets the right component.
- The live retriever also returns the cross-encoder's own ordering of the fused pool (same model
  as `rerank()`), plus the pool's table and rescue-qualifying table chunk ids.
- Each gold chunk records `ce_rank`. A `rerank` part gets a `rerank_cause` on its best gold:
  - `fusion`: the cross-encoder ranks it in the top 5, but the max-of-ranks combination drops it;
  - `rescue_threshold`: the cross-encoder ranks it lower, it's a rescue-qualifying table, no table
    made the top 5, and only its fused rank (past half the pool) blocks the table rescue;
  - `model`: otherwise; the cross-encoder itself scores it low.
- The summary counts the causes. TDD for the pure split; the manual script checks that the
  cross-encoder ordering reproduces `rerank()`'s scores. Cost: one more cross-encoder pass per
  query (about a third more runtime).

**Result** (`8d96c62`, clean tree, `var/retrieval_replay/base-v0-ce.json`, the new compare base):
the V0 figures are unchanged, and `rerank causes: fusion 16, model 462`. The cross-encoder itself
causes the misses. A profile of the 462 `model` misses (scratch analysis, not committed):
- the best gold's ce_rank has a median of 19.5 (6-10: 50, 11-20: 199, 21-30: 157, 31+: 56), and
  its pool position a median of 23;
- 86% of them are table chunks, about the same share as for hits (90%). Tables alone don't explain
  the misses;
- **truncation:** the reranker (`ms-marco-MiniLM-L-6-v2`) reads 512 tokens, query included. The
  gold anchor lies past that cutoff in 158 of 462 misses, against 14 of 329 hits. 397 of the
  missed gold chunks are truncated at all. The median gold chunk is 2814 chars for misses and
  2275 for hits;
- the two MSFT segment questions account for 243 of the 462.

Research: `docs/research/2026-09-30-rerank-improvement.md`, which proposes the rerank variants to
measure.

### V5: windowed MaxP rerank (prototype `stash@{0}`; V1/V2 moved to `stash@{1}`)

The current cross-encoder scores each candidate as the max over windows of about 380 tokens,
split on line boundaries. A window that starts inside a `<TABLE>` repeats the caption line and
the table's first three lines. CPU latency is 3.5-4.9 s per search, against 2.7-3.7 s.
Compared against `base-v0-ce.json`:
- hit@5 rises from 329 to 351 (+2.4 pts: 37 part hits gained, 15 lost); reach is unchanged.
- Questions covered rise from 31 to 34. It gains msft-rd-intensity and **both MSFT segment
  questions** and loses none. The guard still exits 1, on the 15 lost part hits.
- Rerank causes go from fusion 16 / model 462 to fusion 28 / model 428.
- The losses are mostly NVDA/AAPL income-statement and balance-sheet queries. Inference: the max
  over windows favours long chunks with many windows, a known MaxP bias. Not checked yet.
- **Loss analysis** (offline, from the two reports). 8 of the 15 lost hits are `fusion`: the
  cross-encoder still ranks gold 3-5, but under max-of-ranks a fused rank r ties a ce rank r, so
  up to 10 contenders compete for 5 slots. 6 are `model` (gold's ce rank slips from 1-4 to 6-11);
  1 had ce 36 and was a hit only through its fused rank. The lost gold chunks are short (1841-2634
  chars, under the 2814 median). That fits the long-chunk bias guess but doesn't prove it.
- **Revisiting the max-of-ranks decision** (`docs/decisions/2026-08-13-hybrid-retrieval-and-reranker-fix.md`):
  max was chosen because the cross-encoder buried a correct long MSFT chunk (rank 43/48). The new
  information is a 901-pair measurement. Prototype `combine_proto.py` (scratch) offers
  `COMBINE_MODE=ce` (cross-encoder rank only, rescue kept) and `COMBINE_MODE=tiebreak` (max, with
  ties going to the cross-encoder). Both get measured; nothing changes without the grilling
  session.

### V6: V2 strict + V5 MaxP together (both scratch prototypes applied)
Run: `var/retrieval_replay/v6-strict-maxp.json`.
- Results:
  - hit@5 rises from 329 to **469 (52.1%)**, with 150 part hits gained and 10 lost. Reach is 98.0%.
  - Questions covered: **37/40**. It gains crm-buyback, five-company-net-margin, msft-rd-intensity,
    both MSFT segment questions and nvda-inventory-turnover, and loses none. The guard exits 1 on
    the 10 lost hits.
  - Classes: rerank 414, dilution 17, period_confusion 1.
  - **Rerank causes: fusion 147, model 267.** With the period filter, the max-of-ranks tie
    squeeze becomes the single largest fixable cause, which leads to V7.
- Uncovered: aapl-3yr-avg-operating-margin, five-company gross- and operating-margin rankings.

### V7: V6 + combination rule (`combine_proto.py` applied on top)
Runs: `v7-ce.json` (`COMBINE_MODE=ce`) and `v7-tiebreak.json` (`COMBINE_MODE=tiebreak`).

## Next measurements (user-agreed 2026-09-30, in order)

1. **Finish V7.** Pick the combination rule from `tiebreak` against `ce`, on top of V6.
2. **CPU timing script** (after V7, so the runs don't compete for CPU). Use 3 real pools, as in the
   research note's timing:
   - `bge-reranker-base` (512 tokens);
   - `bge-reranker-v2-m3`, which also settles whether it loads through `CrossEncoder`;
   - `gte-multilingual-reranker-base`, plus its specs from its config;
   - ONNX/int8 builds of `gte-reranker-modernbert-base`, to test the quantization speedup the
     Multi-Reranker paper suggests.
3. **Stronger short-context model plus windowing**, on top of V6/V7: the fastest model from step 2
   that fits the latency budget (no more than about 2-3x today, never 30 s).
4. **Header-carry ablation:** MaxP windows without the repeated caption and header, to see
   whether the header matters or only the windowing does.
5. **Long-chunk bias check:** add the final top-5 ids to the report (a small harness change, with
   TDD), then check which chunks displaced gold in V5's losses.
6. **The 10 lost hits from the strict filter:** try letting it also accept the next filing's
   report date (the prior-year column). Otherwise the grilling session decides whether part-hit
   losses without coverage loss are acceptable.
7. **Grilling session:** pick the stack. It becomes package 5's spec, then a TDD build, the manual
   script, the review pass, and the live panel plus the full 48-question run (every-question
   change).

Dropped, with reasons in the research note: the ms-marco L-12 swap (no gain in published scores),
jina v2/v3 (non-commercial licence), e5-mistral-7b (too heavy for CPU), and full-pool ModernBERT
(39-45 s per search).
Caution: all 901 pairs come from the same 41 questions, so harness gains can overfit. The live
run is the confirmation.

### V7 results (appended 2026-10-01)
- **tiebreak** (`v7-tiebreak.json`):
  - hit@5 is 482 (53.5%) against V6's 469, with 163 part hits gained and 10 lost against V0.
  - Questions covered: 37/40, the same as V6. Reach is 98.0%.
  - Rerank causes: fusion 129, model 272.
  - Ties explain only part of the fusion misses. Most of the rest are strict losses: a chunk with
    a better fused rank beats gold's ce rank of 4-5. The `ce` run tests removing the fused rank
    entirely.
- **ce** (`v7-ce.json`):
  - hit@5 is 599 (66.5%), with 291 part hits gained and 21 lost against V0.
  - Questions covered: 34/40, three fewer than tiebreak. Reach is 98.0%.
  - Rerank causes: model 284 (no fusion cause, by construction).
  - Coverage lost against V0: aapl-employees-fy25-indirect and nvda-revenue-two-quarter-comparison.
    nvda-inventory-turnover is also uncovered, where V6 covered it.
  - Against tiebreak: 145 part hits gained and 28 lost. Every one of the 28 had its gold at fused
    pool position 1-3, with a ce rank of 6-35. These include aapl-msft-employee-comparison, the
    same kind of headcount chunk as the 2026-08-13 incident. So the floor does real work, but
    only near the top of the fused list.
  - Next: a narrower floor, where only fused ranks up to F keep the max rule (`floorF`). It's
    measured offline with `cache_sim.py`, below.

### Queued after V7 ce (2026-10-01)
All variant code is in `retrieval.py`'s prototype blocks, uncommitted. A copy of the whole
prototype diff is in `%TEMP%/claude/gold/protos.patch`. New env switches:
- `RERANK_HEADER=0`: MaxP windows without the carried caption and table header (step 4).
- `RETRIEVAL_NEXT_FILING=1`: the strict filter also accepts the next filing's report date for
  the same ticker (step 6).
- `RERANK_MODEL=<hf repo>`: swaps the cross-encoder (step 3). Optional extras:
  - `RERANK_MAXLEN` sets the max length (default 512);
  - `RERANK_ONNX=<file>` loads an ONNX build through onnxruntime, e.g. `onnx/model_int8.onnx`;
  - `RERANK_WINDOW` sets the MaxP window size (default 380).
- Smoke-tested 2026-10-01:
  - NVDA Q1 FY2026 maps to 2025-04-27, and the next filing to 2025-07-27;
  - the int8 ModernBERT ONNX build scores a relevant pair 3.17 and an irrelevant one 0.26;
  - the header toggle changes only the carried prefix.

`timing2.py` (the step 2 models) is running and logs to `gold/timing2.log`. The planned v8 and v9
harness runs were cancelled before they started, and replaced with `gold/cache_sim.py`:
- `cache` runs the base query list once under the env config. It stores every list the harness
  needs, plus the pool's ce scores, in a pickle. This costs about half a harness run, because it
  skips the second, reranked `hybrid_search`.
- `sim` replays any combination rule (`max`, `tiebreak`, `ce`, `floorF`, each with the rescue)
  through `evaluate_query` and `summarize` in seconds.
- Planned caches: V6 (strict + maxp), `RERANK_HEADER=0` (step 4), `RETRIEVAL_NEXT_FILING=1`
  (step 6), then the step 3 model. Each one is first checked against v7's 482/599.
- **Validated 2026-10-01:** a cache of 2 questions (49 query-part pairs) under strict + maxp
  reproduces `v7-tiebreak` and `v7-ce` exactly, pair for pair (38 and 44 hits).
- **Step 2 done, step 3 closed:** no stronger model fits the latency budget. Figures are in the
  research note's "Second timing run".
- **Running** (`gold/chain.sh`): the caches `v6`, then `noheader`, then `nextfiling`, each logging
  to `gold/<name>.log`. Then `v5losses` (step 5), then `stage2-v6` (below).

### Combination rule on the V6 cache (`gold/v6.pkl`, 2026-10-01)
The replay reproduces V6 `max` at 469, `tiebreak` at 482 and `ce` at 599.

| Rule | hit@5 | Covered |
|---|---|---|
| max (today's rule) | 469 | 37 |
| tiebreak | 482 | 37 |
| ce | 599 | 34 |
| floor1 (max kept for fused rank 1 only) | 592 | 34 |
| floor2 | 579 | 35 |
| floor3 | 526 | 37 |
| slot1 (ce fills 4, the 5th goes to the best fused-top-F chunk not already in) | 592 | 34 |
| slot2 | 579 | 35 |
| slot3 | 546 | 35 |
| slot5 | 503 | 35 |

`floor1` with the 1e-9 tiebreak is the same as `slot1`.

What decides coverage is 3 questions, each hanging on one query whose gold sits at fused position
2-3 with a ce rank of 6-15:
- `aapl-employees-fy25-indirect`: pool position 3, ce rank 15;
- `nvda-revenue-two-quarter-comparison` Q1FY27: pool position 3, ce rank 7;
- `nvda-inventory-turnover` inventory: one query only, pool position 2, ce rank 6.

So the 34 vs 37 gap is three single-query outcomes. The part-hit gain (+117 for `ce` over
`tiebreak`) is the steadier signal, though the agent re-queries live, and a lost query can be
recovered or not. No rule wins both measures, so this goes to the grilling session (step 7) as a
trade-off. The candidates are `ce` (599/34), `floor2` (579/35) and `floor3` (526/37). The live
48-question run would be the arbiter.

### Steps 4 and 6 on their caches (2026-10-01)
Each row is hit@5 / questions covered, with the V6 cache's figures for comparison:

| Cache | tiebreak | ce | floor2 | floor3 |
|---|---|---|---|---|
| V6 | 482 / 37 | 599 / 34 | 579 / 35 | 526 / 37 |
| `RERANK_HEADER=0` (step 4) | 462 / 35 | 459 / 33 | 459 / 33 | 459 / 35 |
| `RETRIEVAL_NEXT_FILING=1` (step 6) | 438 / 35 | 561 / 33 | 525 / 33 | 459 / 35 |

- **Step 4:** the carried caption and table header are what make MaxP work. Without them, `ce`
  loses 140 hits and uncovers `msft-segment-revenue-comparison`. Keep the header carry.
- **Step 6:** dropped. Of the 21 V0 hits that V6 `ce` loses, the next-filing date recovers only
  2, while it gains 3 and loses 41 against V6 `ce`. Reach also falls, from 98.0% to 97.4%,
  because the extra filing's chunks crowd the pool. The strict filter's part-hit losses go to
  the grilling session as they stand.

### Step 5: long-chunk bias check (2026-10-01)
Cache `gold/v5losses.pkl` covers V5 (`RERANK_MODE=maxp`, `max` rule) on the 9 questions behind
its 15 lost hits. It reproduces all 15 as misses.
- Median chunk length is 2,253 characters for the gold, 2,235 for the chunks that took the top 5,
  and 2,213 for the corpus.
- MaxP gives a long chunk more windows, and so more chances at a high max, but there's no sign
  that this pushes gold out.
- Mostly the displacers are other tables from the same statements: 2 to 5 of the top 5 contain
  a `<TABLE>`. The causes match the earlier loss analysis: the fused floor pushes out gold at ce
  rank 3-5 (8 of the 15), and the model ranks gold at 6-35 (the rest).
- No length normalisation is needed.

**Step 3 option, measured on a sample only:** a second stage reranks the top 10 under `ce` with
int8 ModernBERT at 1024 tokens. On the 2-question check cache it scores hit@5 37/49, against
`ce`'s 44/49, at a median of 13.6 s while another run shared the CPU.
- **Full V6 run:** hit@5 601, covering 35/40, against `ce`'s 599 and 34/40. That's a wash. It
  covers nvda-inventory-turnover and nvda-revenue-two-quarter-comparison, but uncovers
  aapl-msft-tax-rate-comparison.
- **Cost:** the second stage alone adds 9.63 s median (p90 11.22 s, max 12.54 s) on an idle CPU,
  on top of about 4-5 s for L-6 MaxP. That's roughly 3x today, at the edge of the budget, for no
  measured gain. Dropped. Step 3 is closed.

### All measurements done (2026-10-01)
What goes to the grilling session (step 7):
- **Period scoping:** strict (V2) is the base of every best result.
- **MaxP:** with the header carry; the carry is essential (step 4).
- **Combination rule:** the open trade-off. `ce` (599/34), `floor2` (579/35), `floor3`
  (526/37) or `tiebreak` (482/37).
- **Dropped:** the next-filing date (step 6), length normalisation (step 5), a stronger model
  over the full pool or as a second stage (steps 2-3).

Step 5's harness change is done: `evaluate_query` now writes the query's `final` top 5 into the
report, with a TDD assertion, and the 45 harness tests, ruff and pyright pass. It's uncommitted,
and only reports from v8 onward have the field.
For step 5's analysis, the V5 rerun on the 9 questions behind its 15 lost hits was cancelled with
the queue. A `cache` run (`RERANK_MODE=maxp`, `--qid` on those 9 questions) does the same job:
the `sim` results include the `final` top 5.

## Step 7: package 5 spec (grilled by Claude on the user's instruction, 2026-10-01)
The user accepted taking `ce` and `floor3` to the live run, and asked Claude to settle the other
questions alone. One new finding changed the live-run order (Q3).

1. **Stack.** Strict period scoping (V2), then windowed MaxP with the header carried (V5), then
   the fused-rank floor rule. Nothing else from the prototypes ships: no model swap, no ONNX class,
   no second stage, no next-filing dates, no length normalisation, and no env switches.
2. **Combination rule: one code path, `floor F`.** The score is the ce RRF term. A chunk with
   fused rank <= F scores max(fused term, ce term) + 1e-9 x ce term. F = 0 is pure `ce`, so both
   candidates are the same code with a constant (`_FUSED_FLOOR_RANKS`), and the loser leaves no
   dead branch. The table rescue stays as it is. It revisits the max-of-ranks decision, so a
   new decision file links back to `docs/decisions/2026-08-13-hybrid-retrieval-and-reranker-fix.md`.
3. **Which rule goes live first: `floor3`.** `ce`'s 73-hit lead over `floor3` (599 vs 526) is not
   broad. Per question on the V6 cache (part hits only one rule gets):
   - msft-three-segments-revenue: ce +60, floor3 +6;
   - msft-segment-revenue-comparison: ce +18, floor3 0;
   - the other 21 differing questions: ce +27, floor3 +31 (aapl-msft-employee-comparison alone is
     floor3 +10).

   Both MSFT segment questions are covered under both rules; their many logged queries inflate
   `ce`'s count. Without them `floor3` is level on hits and covers 3 more questions. So:
   - full live run of `floor3` (~250 requests, its own quota day);
   - then, offline and free, replay that run's newly logged queries through the harness under
     F = 3 and F = 0;
   - run `ce` live only if that replay shows F = 0 newly covering a question that `floor3` missed
     live. Otherwise `floor3` ships and `ce` is not run.
4. **Strict period scoping.**
   - Dates come from the query: an explicit date matches report dates within 7 days, plus fiscal
     year and quarter labels through `period_labels`. This is the prototype's
     `_query_report_dates`.
   - If no date is parsed or matched, or both filtered lists come back empty, use today's
     unfiltered lists.
   - The 10 part hits strict loses (none of them coverage) are accepted. The next-filing widening
     was measured and dropped (step 6).
5. **MaxP.**
   - 380-token windows on line boundaries, counted with the model's tokenizer.
   - A window that starts inside `<TABLE>` repeats the caption line, `<TABLE>` and the first 3
     table lines.
   - A chunk scores its best window.
   - Window size is not tuned: 380 leaves room for the query in 512, and tuning on 41 questions
     would overfit.
   - Latency rises from 2.7-3.7 s to 3.5-4.9 s per search; accepted.
6. **Module shape.**
   - The date parsing and window splitting are pure and testable; they go in new sibling modules
     (`retrieval/period_scope.py`, `retrieval/rerank_windows.py`), so `retrieval.py` (354 lines,
     critical core) only gains the wiring.
   - Filtered BM25 and the Chroma `$in` query stay in `retrieval.py`.
7. **Logging** through `tracing.log_event`, one event per search. It answers:
   - which report dates scoped the search, or why it fell back;
   - how many windows the reranker scored;
   - F.
8. **Tests (TDD).**
   - Windows: header carry, no carry outside tables, line-boundary splits, a single over-long line.
   - Max over windows.
   - Date parsing: explicit date, FY, quarter, no match.
   - List choice, including the empty-filter fallback.
   - The rule at F = 0 and F = 3, with the rescue still applied.
   - The Chroma `where` filter and model loading are live-only (`# pragma: no cover`), covered by
     a manual script in `tests/manual/`.
   - `retrieval.py` is critical core: 90% diff coverage, `arch-reviewer` on Opus.
9. **Offline acceptance (before any quota).** The harness on the built code must match the V6
   cache exactly: F = 3 gives 526/901 and 37/40, and F = 0 gives 599 and 34. Any gap is a build
   bug, not noise. Save it as the new base report.
10. **Live order and quota.**
    - Track A's full run on master comes first; it is the live baseline.
    - The `floor3` run goes on a later quota day.
    - A question that drops against the baseline is explained from traces (WP8 style) before
      shipping. A drop caused by retrieval blocks shipping.
11. **Harness alignment.** `rerank_cause` restates the max-of-ranks rule, so package 5 updates
    it to the floor rule, or has retrieval expose its fused, ce and combined ranks so the
    harness stops restating them. The seam also lets the harness tell a rescue displacement
    from a fusion cut.
12. **Branching.** `retrieval-harness` merges first (after track A step 1). Package 5 branches
    from master after that, since its acceptance check needs the harness. It starts in plan mode
    with `design-before-building`; this section is its draft spec.

## Review log

Round 1 (2026-10-01, Substantial: 1,460 lines; branch diff `master...b0e4fd0`): code-review high,
arch-reviewer (opus), security-reviewer. `/simplify` was not run in round 1; it runs in round 2.
- security: no findings.
- **[Fixed]** `rank_stats` scanned twice, with an unreachable pragma'd `return None` (code-review,
  arch). Now one pass.
- **[Fixed]** The rerank cause came from the pool-position best gold chunk. It now comes from the
  part's pooled gold chunk the cross-encoder ranked best (code-review).
- **[Fixed]** An HNSW recall miss was classed as period_confusion/dilution/other_ticker. New
  `index_recall` class (code-review). It also settles arch's question about a ticker-filtered query
  landing in `other_ticker`.
- **[Fixed]** `period_confusion` was chosen when a single same-ticker other-filing chunk was ahead,
  even with dozens of other tickers' chunks ahead. It's now decided by which count is larger
  (code-review).
- **[Fixed]** `propose_gold` centred snippets with `text.find(token)`. `figure_matches` now returns
  the match objects (code-review, arch).
- **[Fixed]** A `--qid` with no gold silently gave an empty report and exit 0. It's now a usage
  error (code-review).
- **[Fixed]** A missing gold file or a missing or malformed `--compare` base gave a traceback. They
  now print `retrieval_replay: ...` and exit 2 (arch).
- **[Fixed]** In compare mode the header described the current CLI args. It now inherits the base's
  `trace_file`, `qids` and `gold_questions_without_queries` (code-review, arch).
- **[Fixed]** The manual script repeated the search-span filter. `search_key` is now shared (arch).
- **[Fixed]** Plan wording on ticker filtering, plus the thousands-matching deviation (arch).
- **[Fixed, docstring]** The `ce` ordering and rerank cause are rebuilt outside `hybrid_search`
  (code-review, arch).
  - Checked: `ce` comes from `retrieval._get_rerank_model()`, which the MaxP prototype wrapped. So the
    V5-V7 cause splits did measure the prototype's scoring, and arch's claim that they don't was
    wrong.
  - What is restated is the max-of-ranks rule and the rescue gate. The docstrings now say so.
  - Package 5 changes the combination rule, so it must update `rerank_cause` with it, or expose
    retrieval's own ranks through a seam. Added to its spec below.
- **[Deferred → BACKLOG]** A chunk the table rescue displaces from the cross-encoder's top 5 is
  classed `fusion` (code-review). Telling it apart needs retrieval's own combined ranking: the same
  seam as above.
- **[Deferred → BACKLOG]** Each query runs the cross-encoder twice, and BM25 and the embedding 3
  times (code-review). It's a runtime cost only, inside the 15-45 minutes a full run already takes.
- **[Disputed]** `trace_query._safe` and `eval_harness._git_state` are called across modules (arch
  nit). Devtools reuse them read-only, and renaming them would touch modules outside this
  branch. Accepted coupling.

Verified after the fixes: 52 harness tests (15 new or changed, red first), and the full suite of
1,143 passed. ruff and pyright are clean, and diff coverage is 98%. The manual script ran live:
OK, 28/30 queries with exact order, 2 HNSW recall misses.

Round 1, `/simplify` (4 agents: reuse, simplification, efficiency, altitude):
- **[Fixed]** `rank_stats` is now one pass with per-filing and per-ticker counts. It returns
  `other_ticker_ahead`, which `classify` reads directly instead of deriving it by subtraction
  (efficiency, altitude).
- **[Fixed]** A test helper's nested default for `pool` (simplification).
- **[Skipped]** Reusing `numeric_utils`' number parser in `figure_matches`, and
  `normalize_for_match` for gold anchors (reuse). Both would change behaviour: the 247 gold rows
  were hand-checked against the current matcher, and casefold/NFKC would widen anchor matching.
- **[Skipped]** A `_fail()` helper for the two exit-2 paths in `main` (simplification). Two call
  sites don't justify it.
- Verified after: 1,143 passed; ruff and pyright clean; diff coverage 98%.

Round 2 (2026-10-01, delta `git diff b0e4fd0`, 3 files): code-review low, arch-reviewer (sonnet),
security-reviewer. Clean round, so review ends here.
- arch: no findings. It checked each round-1 [Fixed] item against the delta, and ruff, pyright
  and the 52 harness tests are clean.
- security: no findings.
- **[Dismissed]** code-review: a `--compare --qid X` run would write the base's `qids` into its
  header. It can't happen: `main` rejects `--compare` with `--qid` as a usage error.
