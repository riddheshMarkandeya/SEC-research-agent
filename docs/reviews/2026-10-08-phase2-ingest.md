# Review: phase 2 build 2, seven companies added to the registry

Plan: `docs/plans/2026-10-08-phase2-ingest.md`. Adds 7 companies to `companies.json` with
hand-pinned fiscal year end months, a test pinning them, a regenerated model-input snapshot, and
recorded counts in `verify_filing_selection.py`. Suite before: 1,390 (plus 2 import-contract
tests that fail only under a cp1252 console). Classified Substantial by design tier; the diff is
about 50 lines plus the snapshot.

## Round 1

Passes: `/code-review` high, `arch-reviewer` (sonnet), `security-reviewer`, `/simplify` (reuse,
simplification, efficiency, altitude).

1. **High** (code-review): TGT should be month 2, not 1. Its years and quarters end on Saturdays
   either side of a month boundary; month 2 gives unique end-year labels and selects the same 14
   filings (checked live). `[Fixed]`. This revisits the plan's deferral of TGT labels to build 5;
   the user chose month 2.
2. **Med** (code-review): `get_metric_all_companies`' instant-metric branch makes 12 sequential
   cold fetches, and any one failure aborts the comparison. Pre-existing. `[Deferred → BACKLOG]`,
   with an exposure note on the SEC network failure item.
3. **Med** (code-review): `get_frame`/`_frame_entry` use frames entries unvalidated.
   Pre-existing and already tracked. `[Deferred → BACKLOG]`
4. **Med** (code-review): JNJ's fiscal 2026 ends 2027-01-03, which month 12 will mislabel once
   it's filed. `[Deferred → BACKLOG]` (build 5).
5. **Med** (code-review): the banks' revenue tag understates revenue in comparisons.
   `[Verified, no fix needed]`: already the build 5 Revenues-override item.
6. **Low** (code-review): staged and working-tree versions differed. `[Fixed]`: restaged.
7. **Med** (code-review): system-prompt rule 7 will fire on most comparisons now that some
   companies lack a metric. `[Deferred → step 8]`: the live run made no
   `compare_financial_metric` call, so it didn't arise.
8. **Low** (code-review): docstring invariants in `period_labels`/`xbrl_facts` are now stale.
   Those functions aren't touched here. `[Deferred → BACKLOG]` (build 5).
9. **Low** (code-review): `load_chunks` and `_scan_chunk_files` disagree on blank lines.
   Pre-existing and latent. `[Deferred → BACKLOG]`
10. **Low** (code-review, simplify): the ticker set and months were pinned in two tests. `[Fixed]`:
    one exact-dict test.
11. **Nit** (arch): unbacked "About 60 SEC requests". `[Fixed]`: about 40, one per submissions
    page. The other arch notes (counts recorded before running, plan headings, line citations
    in the plan) are `[Verified, no fix needed]`.
12. security, and simplify's reuse, efficiency and altitude angles: no findings.

## Round 2

Delta: `938ad17` (stash snapshot). Passes: `/code-review` low, `security-reviewer`. No findings.
The code-review note that Target's year end moves between January and February is covered: the
consumers compare months with `<=` and modulo, and all 14 TGT filings were checked under month 2.

## Live verification

- Post-ingest replay: hit@5 549 → 480 of 981. Root cause: BM25 whole-corpus statistics (see the
  decision file). Filed as BACKLOG High.
- Full v1: 46/48 (`20261009T002418Z`) against 48/48. One drop is the BM25 regression
  (`msft-three-segments-revenue-q3fy2026`); the other, `msft-segment-revenue-comparison-q3fy2026`,
  isn't explained by the corpus. Replication on a later quota day is pending.

## Outcome

Shipped `91534a6`. Suite: 1,391 passing. The review closed clean after 2 rounds: 4 fixed,
5 deferred to BACKLOG or step 8. Open: the BM25 statistics regression **[bug, High, Standard]**
and build 5's widened fiscal-year item.
