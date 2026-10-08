# Plan: phase 2 build 2: ingest the 7 new companies, then the v1 regression gate

Tier: **Substantial**. It grows the corpus about 2× in filings and changes what the model reads
(`companies.json` feeds the system prompt's company list and the ticker enum). Code change is
small; the work is the ingest, the measurements and the gate. The commits listed below are part
of this approved plan.

## Context

Phase 2 map (`docs/plans/2026-10-07-data-expansion-phase2-map.md`, frozen) and BACKLOG
"Phase 2 build 2". Build 1 (`7179888`) made the prompt derive the company count from
`COMPANIES`, so adding companies needs no prompt-text edit. This package adds JPM, BAC, TGT,
WMT, XOM, JNJ and CAT (FY2024+, 10-K/10-Q), chunks them, indexes them incrementally, and gates
v1: first an offline `retrieval_replay` against the pre-ingest result (period-scoping check),
then a full v1 live run, with every drop classified.

**Facts checked in plan mode (live SEC, read-only, 2026-10-08):**
- The real `collect_filings` selects **78 new filings**: JPM, BAC, XOM, CAT, JNJ 10 each
  (FY2024 Q1 to FY2026 Q2); TGT and WMT 14 each (fiscal year ending early 2024 onward). Corpus
  goes from 61 to **139** filings. JPM needs 18 submissions pages and BAC 9 (424B2 noise);
  paging already handles it. No bad rows.
- CIKs: JPM 0000019617, BAC 0000070858, TGT 0000027419, WMT 0000104169, XOM 0000034088 (map
  decision; filings through the 2026-06-30 10-Q are under it), JNJ 0000200406, CAT 0000018230.
- **SEC's `fiscalYearEnd` is the last 52/53-week end date, not the nominal month**: JNJ `0103`,
  TGT `0201`. Pin `fiscal_year_end_month` by hand: JNJ **12**, TGT **1**, WMT 1, the rest 12.
  With JNJ = 1 every JNJ quarter would be mislabelled.
- Every new 10-K/10-Q primary document holds the full financial statements (no Exhibit 13
  wrapper). The JPM and BAC primaries are about 12–13 MB each (AAPL-sized filings are about
  1–2 MB), so chunk count and index time will grow far more than the filing count.
- **TGT period labels are wrong** under the end-month rule (its period ends fall in the first
  days of Feb/May/Aug/Nov): the 2025-02-01 and 2026-01-31 10-Ks are both labelled FY2026, and Q1
  reads as Q2. Selection is unaffected (the same 14 filings either way). `period_scope` would
  scope TGT fiscal-year/quarter queries to the wrong filing. **User decision (2026-10-08): defer
  to build 5**, widening its fiscal-year fix design to cover `period_labels`/`period_scope` as
  well as `xbrl_facts` (52/53-week tolerance plus Target's start-year naming). No v1 question
  names TGT. JNJ labels are right from FY2024 on with month 12 (its odd ends, 2023-01-01 and
  2023-04-02, are all pre-cutoff).

## Approach

Reuse everything from phase 1 (`docs/plans/2026-10-06-data-expansion-years.md`): skip-refetch
(`edgar_ingest._already_ingested`), the corpus identity sidecar, incremental `build_index`
(default, no `--full`), `retrieval_replay --compare`, `compare_prompt_versions` explicit mode,
`tests/manual/verify_filing_selection.py`, `tests/manual/verify_period_labels.py`. No new
production code unless the scoping gate (step 7) trips.

## Steps

0. **Docs commit:** save this plan to `docs/plans/2026-10-08-phase2-ingest.md`, add its
   `PROJECT_INDEX.md` line (check the 50-entry cap), mark BACKLOG build 2 "in progress, plan
   …", and widen build 5's BACKLOG line with the TGT `period_labels`/`period_scope` finding
   (user decision above).
1. **Pre-ingest replay base** (no quota, current index, background):
   `python -m sec_agent.devtools.retrieval_replay --compare var/retrieval_replay/data-exp-new.json --out var/retrieval_replay/phase2-base.json`.
   Frozen query set from phase 1's post-ingest result (549/981). Check: **0 lost, 0 gained**
   and corpus identity `d703a4290869`. If not, stop and investigate (`debugging-discipline`)
   before ingesting. First hypothesis: the Chroma index was rebuilt 2026-10-08T00:26Z (same
   sha) after the base was recorded, and an HNSW rebuild can shift ANN results; check the lost
   parts' `vector.rank` against the base. If that's all it is, `phase2-base.json` becomes the
   base as-is and the drift is recorded.
2. **Back up:** copy `var/data`, `var/chunks`, `var/chroma_db` to
   `var/backup/2026-10-08-61-filings/`; record SHA-256 of all 61 chunk files.
3. **Code change (TDD, small):**
   - Red: `tests/sources/test_companies.py:12` expects the 12 tickers; add a test pinning
     JNJ = 12 and TGT = 1 with a comment that SEC's `fiscalYearEnd` is a 52/53-week end date,
     not the nominal month (so nobody "corrects" it from SEC).
   - Green: add the 7 entries to `src/sec_agent/sources/companies.json` (names: JPMorgan Chase
     & Co., Bank of America Corporation, Target Corporation, Walmart Inc., Exxon Mobil
     Corporation, Johnson & Johnson, Caterpillar Inc.).
   - Regenerate the model-input snapshot (`UPDATE_SNAPSHOT=1 pytest
     tests/prompts/test_model_input_snapshot.py`); read the diff first: only the company list,
     "TWELVE" and the ticker enum should change.
   - Extend `tests/manual/verify_filing_selection.py`'s `EXPECTED_COUNTS` (`:26`) with
     JPM/BAC/XOM/CAT/JNJ 10, TGT/WMT 14 (today `.get(ticker, 0)` at `:52` lets any new ticker
     pass), then run it: 61 old + 78 new.
   - `ruff check .`, `pyright .`, `pytest --cov=. --cov-report=term-missing -q` (send output to
     a scratch file). Fix any test that assumed 5 real companies.
4. **Ingest, chunk, index, timed** (record each stage's time, filing/chunk counts, Chroma size,
   new corpus identity, BM25 startup time):
   `python -m sec_agent.sources.edgar_ingest`, then `chunk_documents`, then `index_chunks`
   (incremental). After chunking, before indexing, give the user the chunk count and a time
   estimate (phase 1: 1,258 s for 7,572 chunks, about 0.17 s/chunk); run indexing in the
   background.
   - **Guard:** the 61 old chunk files hash the same as in step 2. If not, stop and
     investigate (`debugging-discipline`).
   - Run `tests/manual/verify_period_labels.py`; record confirmed / mismatch / inconclusive
     counts per new ticker (inconclusive is not verified). Expected: TGT mismatches (build 5)
     and a JNJ false positive from its XBRL check (`:209` flags any 10-K end outside month 12
     across all history, e.g. 2023-01-01); banks/XOM/CAT may be inconclusive (no
     `GrossProfit`). Anything else is a new finding to classify before going on.
5. `/compact` line to the user, then `independent-review-pass` on the diff (small, but it
   changes model input: at least Standard; arch pass for docs).
6. **Commit** `companies.json` + test + snapshot alone (one commit per prompt change, so a
   revert undoes it).
7. **Post-ingest replay** (background):
   `retrieval_replay --compare var/retrieval_replay/phase2-base.json --out var/retrieval_replay/phase2-new.json`.
   **Revisits the map's gate mechanism** ("Not-yet-specified items closed", period scoping):
   the plan review found all 551 frozen queries carry a ticker, and a ticker'd search only
   sees its own company's filings (`period_scope.py:49-59`, `retrieval.py:177`, Chroma
   `where`). So this replay can only show BM25 IDF shift and ANN churn, never the cross-company
   scoping case. Classify every lost hit as same-company rank churn, ANN churn or valid
   alternative (join `final` ids, `accession_chunkindex`, against chunk metadata in a throwaway
   script under `$CLAUDE_JOB_DIR/tmp`; the report doesn't store scope dates).
7b. **Scoping gate, offline probe** (pure, no quota, no ranking): a throwaway script runs
   `period_scope.query_report_dates` on every frozen query text **untickered**, against the
   pre- and post-ingest filing lists. For each query whose scope gains a new company's filing,
   split it into:
   - **matched on its own date or label**: a real cross-company distractor that the
     BACKLOG:95 fix wouldn't change (explicit dates are ±7 days, so a same-date filing always
     matches on its own);
   - **leaked through another filing's date**: the fiscal-label path (`period_scope.py:102-110`)
     returns dates, and the filter admits every filing sharing that date whatever its fiscal
     label or form. This is the only case the `(ticker, reportDate)` fix addresses.
   This gives the exposure size. The trip condition is measured live in step 8.
7c. **Fact-tool dry run** (SEC requests only, no Gemini quota): call the fact tools directly
   for the metrics/periods of every v1 question that uses `compare_financial_metric` or
   another all-companies path (`xbrl_facts.py:468-474`, `:577-582`), including the three
   `five-company-*-ranking` questions. This warms `var/xbrl_cache` for the 7 new tickers (so no
   live SEC timeout mid-run looks like a drop), and records which new-ticker values appear
   (build 5's known wrong ones, e.g. TGT stale cash) and how output size changes. That
   predicts the prompt/tool effects before step 8.
8. **Full v1 live run** (about 250 requests). Before starting, list `eval/eval_results/` for
   reports since the last reset (07:00Z); if any, wait. Committed, clean tree.
   `python -m sec_agent.eval.eval_harness --backend gemini`. Compare against `20261007T072322Z`
   (48/48) with `compare_prompt_versions` in explicit mode.
   - **Scoping gate, live:** from the run's traces, list every `search_filings` span with no
     ticker, its scope reason and dates, and whether a new company's chunk reached the
     results. **The gate trips** if a drop traces to the "leaked through another filing's
     date" case. Then stop and go back to plan mode for a short addendum plan for the
     BACKLOG:95 fix (scope by `(ticker, reportDate)` pairs through `period_scope`, the BM25
     filter and the Chroma `where` clause; `retrieval.py` is critical core: 90% diff coverage
     and a live spot-check). Otherwise record "not triggered", with the 7b exposure count, on
     BACKLOG:95 (v2 measures it).
   - Prompt and corpus changed together (accepted by the map). Explain each drop from traces
     as one of: the leaked-date scoping case; a cross-company distractor matched on its own
     date; same-company churn; a prompt/tool effect (12 companies in the list, enum or
     comparison output, compared with 7c's prediction); the gate; or the model.
   - **Replicate before attributing:** re-run each drop with targeted `--ids` on a later quota
     day (panel protocol, `live-eval-verification.md`) before calling it variance or a
     regression. A regression gets that rule's treatment (BACKLOG item, decision file).
9. **Docs commit:** decision file `docs/decisions/2026-10-xx-phase2-ingest.md` (counts,
   timings at the new size for the admin-UI plan, gate outcome, v1 result and drop classes);
   review file; `PROJECT_INDEX.md` lines; BACKLOG: delete build 2, file each drop class,
   record the scoping-gate outcome on BACKLOG:95.

## Verification

- Suite, ruff, pyright green; snapshot diff shows only the company list, count word and enum.
- `verify_filing_selection.py`: 61 old + 78 new.
- Corpus: 139 filings; 61 old chunk files byte-identical; sidecar matches live identity
  (`index_matches_chunks` true).
- Replay: base reproduces 0/0 (or the drift is explained as ANN); post-ingest delta
  classified; 7b exposure counted; 7c predictions recorded; gate decision from step 8 traces
  recorded on BACKLOG:95.
- Live: one clean full v1 run (no `RESOURCE_EXHAUSTED`), every change against 48/48 explained.

## Risks

- **Corpus size:** the bank filings may multiply chunk count several times over. That slows
  indexing (one-off, background), BM25 startup and per-query BM25 scoring (every eval
  question). Measure startup and per-search time in step 4/8; flag a large increase rather
  than fix it here.
- **Quota day:** step 8 needs a day with no other run; it may land on a later day than steps
  1–7.
- **Rollback:** restore `var/backup/2026-10-08-61-filings/` and revert the `companies.json`
  commit.

## Plan review

`plan-reviewer` (opus), 2026-10-08. All 8 findings folded in:
1. (high) The replay can't trip the scoping gate: all 551 frozen queries carry a ticker.
   → Step 7 now classifies only churn. The gate moves to the 7b offline probe (exposure size)
   and step 8's untickered trace spans (trip condition). Stated as a revisit of the map's gate
   mechanism.
2. (high) The trip condition didn't match the fix. Explicit dates make same-date filings match
   on their own; only the fiscal-label path leaks. → 7b and step 8 split the two cases, and
   only the leak trips the gate.
3. (med) The replay report lacks scope dates and ticker/date per chunk. → The seam is named:
   a join against chunk metadata, plus an offline re-run of `query_report_dates`.
4. (med) 12-company fact tools hit SEC live mid-run, and the ranking questions say "five".
   → Added 7c, a fact-tool dry run.
5. (med) `verify_period_labels.py` will give a JNJ false positive, and banks may be
   inconclusive. → Pre-stated in step 4.
6. (med) `verify_filing_selection.py` lets the new tickers pass unchecked. → Step 3 extends
   `EXPECTED_COUNTS`.
7. (med) A drop was attributed to variance from a single run. → Step 8 now replicates each
   drop with `--ids` on a later quota day.
8. (low) The 0/0 bar may fail because the index was rebuilt on 10-08. → Step 1's first
   hypothesis is ANN drift, checked by `vector.rank`.

## Review log

