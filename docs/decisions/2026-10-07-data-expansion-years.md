# Data expansion, phase 1: FY2024+ filings for the current 5 companies

**Date:** 2026-10-07

## Context

The corpus held the last 5 10-K/10-Q filings per company: 25 filings and 3,182 chunks, about one
year. The last full run (`20261006T073606Z`) scored 46/48, so the eval had run out of measurable
headroom. Filing text was the bottleneck; XBRL already holds every year. Plan:
`docs/plans/2026-10-06-data-expansion-years.md`.

## Decision

`edgar_ingest` keeps every 10-K/10-Q from fiscal year `MIN_FISCAL_YEAR = 2024` on, using each
company's own fiscal-year labels. It replaces "the last N filings" and reads SEC's older
submissions pages when needed. Eval reports and replays now record a corpus identity, plus whether
the Chroma index was built from the same chunk files.

The corpus is now 61 filings and 7,572 chunks, with corpus identity `d703a4290869`. The new
baseline is **48/48** (`20261007T072322Z`, agent `07c62fe87934`, git `a96e7db`).

## Why

- **The cutoff is fixed, not relative to today.** A relative window would change the corpus
  silently on every ingest, so two eval runs could differ for no visible reason. A fixed cutoff
  still grows forward as new filings arrive, but the oldest filing stays put.
- **The spread across companies is uneven on purpose:** AAPL 11, MSFT 12, NVDA 14, CRM 14,
  PLTR 10. NVDA's and CRM's fiscal-year labels run ahead of the calendar, so FY2024 reaches
  further back for them.
- **Paging is required.** CRM's `recent` block stops at 2023-07-31, so its FY2024 Q1 10-Q is on
  an older page. The next page is read only while the oldest 10-K/10-Q on the current page,
  by filing date, is still inside the cutoff.
- **Filings already ingested are skipped,** keyed on all three files with meta written last.
  The 25 old chunk files therefore stayed byte-identical, as did the chunk IDs, the harness gold
  and the cited chunks in old traces.
- **The corpus identity is computed live from the chunk files.** BM25 and period scoping read
  those files directly. The index's own record is stored as a sidecar file and only compared
  against it.
  - A different corpus counts as a config difference.
  - A stale index is a separate, top-level flag. It triggers a startup warning and a
    `compare_prompt_versions` exclusion.

## Measured

**Rebuild timings** (CPU only; the admin-UI plan needs these):

| Stage | Time | Notes |
|---|---|---|
| ingest | 49.5 s | 35 new filings; 26 already present, including one saved by a run that crashed partway |
| chunk | 2 s | |
| index | **1,258 s (about 21 min)** | full rebuild; Chroma grew from 138 MB to 178 MB |

**Guard:** all 25 old chunk files hash the same as the backup in
`var/backup/2026-10-06-25-filings/`.

**Offline replay on the frozen query set**, the same queries as the base:

| | Base | New corpus |
|---|---|---|
| hit@5 | 556 of 981 parts | 549 of 981 parts |
| reach | 960 | 953 |
| Questions covered | 37/40 | 37/40 (no change) |

- The new corpus lost 11 hits and gained 4.
- Wall time was 2,573 s, because the rerank cache was cold: 3 hits out of 551.

The 11 lost hits break down as follows:

| Class | Count | Questions |
|---|---|---|
| Rank churn within the same filing | 7 | msft employee comparison ×4, msft net income FY2025 (indirect), nvda gross margin FY26, nvda revenue YoY Q1 FY27 |
| Genuine distractor | 3 | nvda cost of revenue FY2026, msft employees (the "employees OR staff" query), aapl buyback availability |
| Scoping shift | 1 | aapl 3-year average operating margin FY2023–25 (net_sales part) |
| Valid alternative | 0 | |

- **Rank churn:** no new filing reached the top 5. The gold chunk had been sitting at rank 3–5,
  and BM25's IDF and the fusion order shifted with the bigger corpus.
- **Genuine distractors:** an older filing outranks the gold chunk on a query with no date, or
  on wording that repeats across filings. Each case:
  - nvda cost of revenue: the FY2024 and FY2025 10-Ks;
  - msft "employees OR staff": the FY2024 10-K's risk factor;
  - aapl buyback availability: the FY2025 Q2 10-Q's repurchase table.
- **Scoping shift:** a question naming FY2023 to FY2025 now scopes into the new FY2024 filings.
  That question was already uncovered.

The 4 gains are all NVDA FY2026 income-statement queries.

**Live run:** 48/48 (`20261007T072322Z`), against 46/48 for `20261006T073606Z`, compared in
explicit mode.
- **Drops:** none, against a panel threshold of 7. The "config differs" warning is the expected
  new `corpus` key.
- **The two gains are both explained:**
  - `pltr-dividend-2019-refusal` gains because package 4 corrected its grading criteria. The
    baseline graded it under the old criteria, so it doesn't count as a corpus effect.
  - `msft-segment-revenue-comparison-q3fy2026` gains in a single run, so it isn't attributed to
    the corpus.
- **Not a drop:** `crm-ai-risk` failed in the partial run `20261006T215838Z`, which ran out of
  quota at question 31 and is invalid for comparison. It gave a one-sentence answer from
  10 chunks. It passes here with the same 10 chunks, so that was model variance, not retrieval.

## Files touched

- `src/sec_agent/sources/edgar_ingest.py`
- `src/sec_agent/retrieval/index_chunks.py`
- `src/sec_agent/eval/eval_harness.py`
- `src/sec_agent/devtools/retrieval_replay.py`
- `src/sec_agent/devtools/compare_prompt_versions.py`
- their tests
- `tests/manual/verify_filing_selection.py`
- `.claude/rules/live-code-tdd.md`
- `.claude/rules/live-eval-verification.md` (new quota check before a full run)

Commits: `f08389b` (selection) and `daf1b97` (corpus identity).

## Verification

- ruff 0, pyright 0, 1343 passed, diff-cover 100% on the changed lines, lint-imports 2 kept.
- `verify_filing_selection.py`: RED on master, GREEN after the change, against live SEC data.
- The offline replay and the live run, as above.
- Review: 6 rounds, `docs/reviews/2026-10-07-data-expansion-years.md`.

## Related

- Plan: `docs/plans/2026-10-06-data-expansion-years.md`
- Review: `docs/reviews/2026-10-07-data-expansion-years.md`
- Previous baseline: `docs/decisions/2026-10-06-close-package-4-not-available-answer.md`
