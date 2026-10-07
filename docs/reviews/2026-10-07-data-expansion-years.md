# Review: data expansion phase 1 (filing selection and corpus identity)

Plan: `docs/plans/2026-10-06-data-expansion-years.md`

The change is about 700 lines: it adds a fixed fiscal-year cutoff with paging to `edgar_ingest`,
and records a corpus identity in eval and replay reports. The suite had 1,288 tests before it
(collected at `8edda85`) and 1,343 after. It was reviewed at the Substantial tier: it was Substantial by design and by
size, and it touches the critical core (`sources/`, `retrieval/`, `eval/`).

The plan's `## Review log` has every finding with its disposition. This file summarizes it.

## Round 1

Passes: `/code-review high`, `arch-reviewer` (sonnet), `security-reviewer`, and `/simplify`
(4 angles).

**Fixed:**
- The replay and eval now warn on a cross-corpus or stale-index comparison.
- The pause before a fetch now applies to failed fetches too.
- `index_matches_chunks` moved out of `config`, so rebuilding the same corpus doesn't read as a
  config change.
- Ragged column arrays now fail, through `zip(strict=True)`.
- A shared, never-raising `corpus_provenance`.
- Accession and page-name validation (security S1 and S2).
- The manual script now checks at-least counts.

**Verified, no fix needed:** a failed older-page fetch drops that whole company. This is logged,
re-running is cheap, and a partial selection would look complete.

## Round 2

Passes: `/code-review high`, `arch-reviewer` (sonnet), `security-reviewer`.

**Fixed:**
- `compare_prompt_versions` now excludes stale-index reports. This touched a file outside
  round 1's diff, so round 3 was a full round.
- Notes for a base with no recorded corpus, or a stale base.
- A pause before each company's filing-list request.
- A null value no longer crashes the company.
- The validation patterns use ASCII `[0-9]` instead of `\d`.

**Deferred → BACKLOG:** `get_filing_url` doesn't check its accession (security residual).

## Round 3

Full table.

**Fixed:**
- `primaryDocument` validation: an empty value would have fetched the directory listing (this
  also closes security S3).
- A kept field that isn't a string now skips the row.
- The manual script flags a filing selected twice.

## Rounds 4–6

Changes since the last snapshot only.

- **Round 4:** stop rule applied.
  - Rounds 2, 3 and 4 each found one more kind of malformed SEC JSON. That family is settled
    under round 1's disposition: it fails that one company, logged, and the run continues.
  - `filingDate` validation was added.
  - The skip log now records the rejected value.
  - `corpus_notes` compares shas.
- **Round 5:** `date.fromisoformat` also accepts `20240630`, which sorts wrongly as a string, both
  in the oldest-row choice and in retrieval's `reportDate` matching. [Fixed] Dates must be
  canonical `YYYY-MM-DD`, with separate `bad_filing_date` and `bad_report_date` log reasons.
- **Round 6:** no correctness findings, and one test-only fix.
  - **Deferred → BACKLOG:** the same loose-date risk in `xbrl_facts`, a file outside this diff.

The security review returned no new findings from round 3 on.

## Live verification

- `tests/manual/verify_filing_selection.py`: RED on master, with 5 filings per company and no
  FY2024. GREEN after the change:
  - AAPL 11, MSFT 12, NVDA 14, CRM 14 (2 pages), PLTR 10;
  - 0 rows skipped.
- **Rebuild:** the 25 old chunk files are byte-identical. Corpus `d703a4290869`: 61 files,
  7,572 chunks.
- **Offline replay:** hit@5 549/981 against 556, coverage 37/40 unchanged. Of the 11 lost, 7 are
  churn within the same filing, 3 are distractors, and 1 is a scoping shift.
- **Full live run:** 48/48 (`20261007T072322Z`), against 46/48, with no drops.
- **First live attempt:** `20261006T215838Z` ran out of quota at question 31, because the
  baseline had run the same Pacific day. It is invalid for comparison. A quota check before a
  full run was added to `.claude/rules/live-eval-verification.md`.
- **Two issues found during the live steps, both pre-existing:**
  - the ingest's ✓ print crashes on a cp1252 console;
  - the harness's `[n]`-only citation pattern flags `[1, 6]` as no citation.
  Both are in BACKLOG.

## Outcome

Shipped in `f08389b` and `daf1b97`. The review closed clean in round 6. The stop rule was applied
in round 4 to a recurring family, without escalating to the user.

BACKLOG, under "From the 2026-10-06 data expansion phase 1 review":
- `get_filing_url` doesn't check its accession;
- `xbrl_facts` has the loose-date risk;
- the timeouts;
- the cp1252 print crash;
- the citation-marker pattern;
- the distractor class on undated queries.
