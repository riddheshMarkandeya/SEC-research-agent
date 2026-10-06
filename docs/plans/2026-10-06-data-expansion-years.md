# Plan: data expansion, phase 1: three fiscal years for the current 5 companies

Tier: **Substantial**. It changes filing selection in the critical core (`src/sec_agent/sources/`) and rebuilds the corpus. Commits only when the user asks (step 0's docs commit and step 4's two code commits are part of this approved plan).

## Context

The agent-improvement map has run out of measurable headroom. The panel is 39/39, and the last
full run (`20261006T073606Z`) is 46/48. `pltr-dividend-2019-refusal` passes under the corrected
criteria from package 4, so only `msft-segment-revenue-comparison-q3fy2026` still fails. Package 6
(the thinking-level / temperature A/B) can't show a gain on this eval, so it's deferred.

The corpus is small and uneven: the last 5 10-K/10-Q filings per company (25 filings, 3,182 chunks,
about one year). XBRL already has every year (the `companyconcept` API returns full history), but
filing text doesn't.

**Agreed order (user, 2026-10-06):** data expansion → harder eval questions → monorepo → admin web
UI → chat web UI. Package 6 resumes once the evals have headroom again.

**Decisions (grill-me, 2026-10-06, all user-confirmed):**
1. Purpose: a more realistic corpus that also restores eval headroom. Done means a new baseline
   that is measured, with every drop explained.
2. Scope: years only, for the same 5 companies, 10-K and 10-Q only. New companies (different
   sectors: a bank, a retailer, an industrial) get their own plan later.
3. Selection: a **fixed fiscal-year cutoff** in code, using each company's `fiscal_year_end_month`,
   replacing "last N filings". Fixed, not relative to today, so the corpus doesn't drift silently.
4. Indexing stays a full rebuild. Time it at the new size and record the figure for the admin-UI
   plan.
5. Measure the offline gold-rank harness first (no quota), then one full 48 run. Drops are
   classified and filed in BACKLOG. Fixes are later packages, not this plan.
6. Eval reports record a **corpus identity**, because `var/` isn't versioned.
7. Back up the current corpus before the rebuild.

**Facts checked:**
- The tickers are unchanged, so the system prompt and the tool enum don't change. The prompt
  fingerprint stays the same and only the corpus differs.
- SEC's `filings.recent` list reaches back to 2015 (AAPL) and to 2020 (MSFT, NVDA, PLTR), but for
  CRM only to 2023-07-31. CRM's FY2024 Q1 10-Q (2023-04-30) is in an older page
  (`filings.files`, 5 pages), so the selection must page.
- With `MIN_FISCAL_YEAR = 2024` (labels from `period_labels.fiscal_year_label`), the expected
  counts are AAPL 11, MSFT 12, NVDA 14, CRM 14 and PLTR 10: about 61 filings, 36 of them new.
  The spread is uneven on purpose, because NVDA's and CRM's fiscal labels run ahead of the
  calendar.

## Approach

### Code (one commit for the selection, one for the corpus identity)

**A. Filing selection (`src/sec_agent/sources/edgar_ingest.py`, critical core `sources/`)**
- Add `MIN_FISCAL_YEAR = 2024` beside `FORM_TYPES` and remove `FILINGS_PER_COMPANY`.
- Add a pure function `select_filings(rows, fiscal_year_end_month, min_fiscal_year)`. It keeps
  10-K/10-Q rows whose `reportDate` falls in fiscal year `min_fiscal_year` or later, reusing
  `period_labels.fiscal_year_label`. It skips rows with an empty or malformed `reportDate`, with a
  log line. It also reports whether the oldest row it saw is still inside the cutoff, which means
  another page is needed.
- A pure `_rows(block)` turns the submissions column arrays into row dicts. It's shared by the
  `recent` block and each older page.
- `get_filing_list(cik, fiscal_year_end_month)` (live, `# pragma: no cover`) fetches the
  submissions JSON. It fetches older pages from `filings.files` (`data.sec.gov/submissions/<name>`)
  only while `select_filings` says the cutoff isn't reached yet, and passes `timeout=30` to every
  request. Because these functions are touched, this also takes the S113 fix for this file's two
  calls. The `xbrl_facts` calls stay on BACKLOG:191.
- **Skip already-ingested filings:** a pure, tested `_already_ingested(out_dir, accession)` returns
  true only when **all three** files (`_meta.json`, `_text.txt`, `_tables.json`) exist. Meta is
  also written **last**, so a crash partway through never leaves a filing that later runs skip
  but `chunk_documents` silently drops. This keeps the 25 existing filings byte-identical, so chunk
  IDs, harness gold and traced citations stay stable, and it saves requests.
- **`main()` stays thin:** the per-ticker work moves into a tested helper (`_ingest_ticker`, with
  the fetch functions passed in or monkeypatched as the existing tests do). That keeps the skip,
  count and log branches out of the `# pragma: no cover` and under ruff's `max-complexity = 10`.
- **Page signal:** submissions rows are ordered by filing date, and non-10-K/10-Q rows have empty
  report dates. "Need another page" means the oldest 10-K/10-Q row on the page, by filing date,
  is still inside the cutoff. A page with no 10-K/10-Q rows means keep paging, provided older
  pages exist.
- **Logging:** add `log_event` calls next to the existing prints. They should answer: which
  filings were selected per company and from how many pages; which rows were skipped and why;
  which filings failed and with what error; and how long each stage took.
  - `ingest_filing_list`: ticker, pages fetched, number selected, number skipped as already
    present, number skipped for a bad `reportDate`.
  - `ingest_filing_failed`: ticker, accession, error.
  - `ingest_done`: counts and `elapsed_s`.

**B. Corpus identity (`retrieval/index_chunks.py`, `eval/eval_harness.py`)**
- Add a pure `corpus_identity(chunks_dir) -> {"chunk_files": n, "chunks": n, "sha": 12-hex}`. It
  hashes the sorted relative paths plus the content of every `*_chunks.jsonl` file.
- `index_chunks.main()` **deletes the old sidecar before `delete_collection`**, so a failed build
  leaves no stale identity. After a successful build it writes the identity plus `indexed_at` to
  `CHROMA_DIR/corpus_identity.json`, and logs `index_built` with the identity and `elapsed_s`.
- `eval_harness._run_config()` adds `"corpus": {"chunk_files", "chunks", "sha"}`, computed **live
  from `CHUNKS_DIR`**, because BM25 and period scoping read the chunk files at startup. It also
  adds `"index_matches_chunks"`, which compares that live identity against the sidecar's `sha`.
  `indexed_at` stays out of `config`: the compare tool reprs the whole `config`, so a timestamp
  would make two rebuilds of the same corpus look incomparable. A missing or unreadable sidecar
  gives `None` for the match, logged as `eval_provenance_corpus_missing`, and never raises (the
  same pattern as the fingerprint).
- `_CONSISTENCY_CHECKS` already compares `config`. Old reports have no `corpus` key, so the
  before/after comparison will show a config difference. That's expected for exactly this
  comparison, and the decision file says so.
- `retrieval_replay`'s report header also records `corpus_identity(CHUNKS_DIR)`, next to
  `retrieval_sha256`, so a base and a new-corpus replay can be told apart.

### Tests (TDD, `tdd-live-code-carveout`)
- Unit, red first (`tests/sources/test_edgar_ingest.py`):
  - `select_filings`: the cutoff per fiscal-year-end month (Jan, Jun, Sep, Dec), a 10-K/A
    excluded, an empty `reportDate` skipped, and the page signal (oldest row still inside the
    cutoff, a page with no 10-K/10-Q rows, the last page reached).
  - `_rows`.
  - `_already_ingested`: all three files present, and each one missing.
  - `_ingest_ticker`: skip, count and log fields, checked with `capture_events`.
- **Existing tests that will break:** `tests/sources/test_edgar_ingest.py:96-101` and `:136-143`
  fake a one-argument `get_filing_list(cik)`, and their fake companies have no
  `fiscal_year_end_month`. Update both to the new signature and seam.
- Unit (`tests/retrieval/`, `tests/eval/`): `corpus_identity` is stable across file order, changes
  when content changes, and handles an empty dir. `_run_config` handles a missing or corrupt
  sidecar.
- Manual first (live-only): `tests/manual/verify_filing_selection.py` calls the real submissions
  API for the 5 companies and prints the selected filings by fiscal year, pages fetched, and the
  CRM FY2024 Q1 10-Q. On master it shows red (5 per company, no FY2024). It goes green after the
  change.
- Add `get_filing_list`'s paging to `.claude/rules/live-code-tdd.md`. `edgar_ingest.py` is already
  listed, so only a mention is needed.

## Files and steps

0. **Docs commit (now, on approval):**
   - Save this plan to `docs/plans/2026-10-06-data-expansion-years.md` and add its
     `PROJECT_INDEX.md` line.
   - **Package 6 deferred:** in the map's build order, record its trigger ("the evals have
     headroom again: after the harder-eval-questions plan, or alongside a model upgrade"). Note
     that temperature 0.1 has no recorded reason (it came from the Ollama-era `811cad0`), so it
     stays a known open item. Update BACKLOG line 50.
   - **Roadmap items in BACKLOG:**
     - data expansion phase 1 (in progress, this plan);
     - phase 2, new companies from different sectors;
     - harder eval questions;
     - monorepo;
     - admin web UI;
     - chat web UI.
     Each item gets a tag. The UI and monorepo items are marked "details later, `/wayfinder`
     first".
1. **Offline base, before any change:** on the current index, run
   `python -m sec_agent.devtools.retrieval_replay --compare var/retrieval_replay/master-base.json --out var/retrieval_replay/data-exp-base.json`.
   The query set must stay frozen: a fresh run without `--compare` picks up every trace logged
   since, so 526/901 can no longer be reproduced. `master-base.json` was made on 2026-10-06 at
   `70f458a` and reads 981 parts, 556 hits, 37/40. The check is **0 lost and 0 gained**; if that
   fails, stop and investigate.
2. Write `tests/manual/verify_filing_selection.py` and run it on master to show red.
3. TDD part A, then part B. Then run `ruff check .`, `pyright .`, and
   `pytest --cov=. --cov-report=term-missing -q`, with 90% diff coverage on `sources/`,
   `retrieval/` and `eval/`. Re-run the manual script: green.
4. Give the user the `/compact` line. Then run `independent-review-pass` (Substantial, critical
   core). Then two commits: selection, then corpus identity. No snapshot change is expected; if
   the snapshot test fails, stop.
5. **Back up:** copy `var/data`, `var/chunks` and `var/chroma_db` to
   `var/backup/2026-10-xx-25-filings/`. Record the SHA-256 of each of the 25 existing chunk files.
6. **Rebuild, timed:** run `edgar_ingest`, then `chunk_documents`, then `index_chunks`. Record the
   time of each stage, the filing, chunk and index-size figures, and the corpus identity.
   - **Guard:** the 25 existing chunk files must hash the same as in step 5. If any differs, the
     chunker or the parser has drifted since the last ingest. Stop and investigate
     (`debugging-discipline`) before measuring.
7. **Offline compare:** run `retrieval_replay --compare var/retrieval_replay/data-exp-base.json`
   on the new index. Expect it to be slow: rerank-cache keys are exact (query, chunk) pairs, so
   the new pools mostly miss the cache and the run takes well over the base's 512 s on CPU. Run it
   in the background. For each lost hit, check by hand which of three cases it is:
   - a **genuine distractor**;
   - a **valid alternative**: an older filing carries the same figure as a prior-year column, and
     the gold only names the original accession;
   - a **scoping shift**: queries naming FY2024 or 2024 dates used to fall back to unscoped
     search (`no_match`), and now scope to the new FY2024 filings, which can move hits either
     way. BM25's IDF also shifts across the whole corpus.
   Count each separately.
8. **Full 48 live run** (about 250 requests, on a day with no other run). Compare it with
   `20261006T073606Z` (46/48) in explicit mode. `pltr-dividend-2019-refusal` was graded under the
   old criteria there; package 4's 29/29 re-grade shows the new criteria pass, so count that
   question separately. Explain every drop from traces and classify it as one of:
   - a retrieval distractor (an older filing outranked);
   - a period-scoping shift (step 7's case);
   - the gate;
   - the model.
   File each class in BACKLOG with a tag.
9. **Docs:** a decision file `docs/decisions/2026-10-xx-data-expansion-years.md` (the cutoff
   choice, the timings, the new baseline, the drop classes); a review file; `PROJECT_INDEX.md`
   lines; BACKLOG updates.

## Verification

- Offline: the suite, ruff and pyright pass; diff coverage is at least 90% on the critical core;
  the manual script goes red, then green.
- Corpus: about 61 filings (AAPL 11, MSFT 12, NVDA 14, CRM 14, PLTR 10, give or take any SEC
  surprises, explained); the 25 old chunk files are byte-identical; the sidecar is written; the
  eval report's `provenance.config.corpus` is filled in.
- Harness: the frozen-query base shows 0 lost and 0 gained against `master-base.json` (556/981,
  37/40). The new-index delta is reported with distractor, alternative and scoping-shift misses
  counted separately, and both headers carry a corpus identity.
- Live: one clean full 48 run (no `RESOURCE_EXHAUSTED`), with every change explained against
  46/48.

## Risks

- **Old reports aren't comparable on corpus:** they lack `corpus`. Only the one 46/48 comparison
  crosses that boundary, and it's stated.
- **Period scoping on report date alone** (BACKLOG:70): more filings per ticker doesn't make it
  worse for tickered searches. Untickered searches get more same-date filings from other
  companies. If drops show this, it gets its own item.
- **Startup cost:** BM25 is rebuilt in memory from about 3× the chunks. The time is recorded in
  step 6, and a big increase gets flagged.
- **Rollback:** restore `var/backup/...` and revert the two commits. The selection code is
  independent of the data, so the commits can stay even if the bigger corpus is rolled back.

## Plan review

One round (`plan-reviewer`, opus, escalated for the critical core). Verdict: the approach is
sound, with revisions needed. All 8 findings were folded in:

1. **High.** The 526/901 base can't be reproduced, because the query set grows with the traces.
   Step 1 now uses `--compare master-base.json` with a 0 lost / 0 gained check.
2. **Med.** The sidecar alone missed the BM25 and scoping path, which reads `var/chunks` live, and
   could go stale after a failed build. The identity is now computed live from `CHUNKS_DIR`, with
   a sidecar match flag, and the sidecar is deleted before the rebuild.
3. **Med.** `indexed_at` in `config` would make rebuilds of the same corpus look incomparable. It
   stays in the sidecar only.
4. **Med.** The `main()` resilience tests break on the new signature. Both are now listed, and
   updated as the new seam.
5. **Med.** The skip branch sat in no-cover code and keyed on meta alone. It's now a tested
   `_already_ingested` that needs all three files, meta is written last, and `_ingest_ticker`
   keeps `main()` under the complexity limit.
6. **Low.** The page signal is now defined by filing-date order, and an empty page means keep
   paging, with tests.
7. **Low.** The replay header gets a corpus identity, and a slow cold-cache new-index run is
   expected.
8. **Low.** The scoping shift is now a separate drop and miss class, along with BM25's IDF
   shift.

Confirmed fine by the reviewer:
- the 25 existing chunk files should re-hash the same (only comment, path and import commits
  since `712089f`);
- gold and chunk IDs stay stable;
- the fiscal-year counts are 11/12/14/14/10 = 61;
- the prompt fingerprint doesn't change;
- `mcp_server` and `get_filing_url` work per filing;
- no new imports.

## Review log

(Filled in during `independent-review-pass`.)
