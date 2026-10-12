# Phase 2 build 3b: v2 authoring check script

## Context

BACKLOG line 60. Build 4 writes ~56 v2 questions in batches. The map
(`docs/plans/2026-10-07-data-expansion-phase2-map.md`, "How questions get written") requires each
batch to pass a `devtools` script before the user reviews it:
- every gold value has a verbatim anchor, confirmed in the chunk files;
- values are cross-checked against companyfacts where a tag exists;
- derived values are recomputed;
- each never-disclosed refusal records a corpus search showing the value is absent.

Build 3a deferred this script and its schema amendment
(`docs/plans/2026-10-09-phase2-build3a-v2-harness.md` §2). 3a.1's review added authoring checks
that don't belong at load time. Build 4 waits on this work.

**Tier: Substantial.** The backlog tags it Standard. It's re-tiered because it's a new tool plus
a schema amendment with real design choices.

**Constraints.**
- Work happens in worktree branch `worktree-phase2-build3b-authoring-check`, from master
  `191be0f`.
- Offline, except the cached companyfacts fetch (an SEC call, no Gemini quota).
- Touches `eval/questions.py`, which is critical core (90% diff coverage).

**Worktree mechanics.**
- pytest uses `pythonpath = ["src", "."]`, so tests import the worktree's code.
- A plain `python -m` call imports the main checkout's editable install, so CLI runs here need
  `PYTHONPATH=src`.
- The worktree has no `var/`. Real-data runs point at the main checkout's `var/` through flags
  (§2). No junction: removing the worktree could follow one into the real `var/`.

**Out of scope (stays in BACKLOG).** 3a.1's round-8 items marked "revisit with v2 run data":
- the "X is not one of" wording;
- the two missing tests;
- `set(tickers)` per entry;
- `_row_identity`;
- cross-company traps.

## Design

### 1. Schema amendment (`src/sec_agent/eval/questions.py`)

Validated at load, so a typo fails before any quota is spent.

- **Units enum.** `expected_unit` (top-level and on each entry), trap `unit`, and derivation
  input units become `{"enum": CLAIM_UNITS}`, imported from `prompts.agent_tools`. That import
  makes no cycle: no `prompts`, `sources` or `agent` module imports `eval`. A unit typo would
  otherwise silently disable a trap. All 45 v1 units are already in the enum.
- **`derivation`** (optional), on a numeric question and on a comparison `expected` entry.
  - Shape: a binary tree mirroring the agent's `calculate` tool,
    `{"operation": op, "a": input, "b": input}`.
  - `op` is one of add, subtract, multiply, divide, percent_of, percent_change. `a` and `b` keep
    the tool's `operand_a`/`operand_b` order.
  - An input is exactly one of three forms (`oneOf`, `$defs` recursion):
    - `{value, unit, part}`: an anchored figure, whose `part` names its gold rows for this qid;
    - `{value, unit, constant: true}`: an unanchored constant, such as the 2 of an average;
    - `{derivation}`: a nested step, for compound chains.
- **`absence_terms`** (a non-empty list of strings).
  - Required when `refusal_kind == "never_disclosed"`.
  - Allowed only when `type == "refusal"`.

### 2. New `src/sec_agent/devtools/check_questions.py`

```
PYTHONPATH=src python -m sec_agent.devtools.check_questions --questions FILE
    [--ids a,b] [--gold eval/retrieval_gold.jsonl]
    [--chunks-dir DIR] [--xbrl-cache-dir DIR]
```

**Inputs.**
- Questions load through `eval_harness.load_questions`, which runs the schema and 3a's checks.
- Gold rows load through `retrieval_replay.load_gold`.
- Chunks load through `index_chunks.load_chunks` over `--chunks-dir` (default
  `config.CHUNKS_DIR`) / `CHUNK_FILE_GLOB`. These are the chunk files themselves, not the index.
  Importing `retrieval_replay`/`index_chunks` pulls in chromadb and sentence-transformers, which
  costs a few seconds of startup but no network and no quota.

**Output and exit codes.**
- Prints `ERROR` / `WARN` / `INFO` lines per question, then a summary.
- Exits 0 with no errors, 1 on any error, 2 on a usage or read failure.

**Structure.**
- Each check is a pure function `(question, ctx) -> list[Finding]`. `ctx` holds the chunks, gold
  rows, a fetch callable and the other suite's ids, so tests use in-memory fixtures.
- Small helpers keep each check under ruff's complexity limits.

**Gold parts** (which figures need an anchor):

| Question | Part needing an anchor |
|---|---|
| numeric, no derivation | `"value"` (its expected value) |
| comparison entry, no derivation | the entry's label (its value) |
| any derivation input with a `part` | that part (the input's value) |
| numeric or entry **with** a derivation | its inputs only. The result is often printed nowhere, as v1's `aapl-revenue-growth-q3fy2026` gold shows (input rows only) |
| text | `"value"`, matched against `accepted` |
| judged | parts are hand-labelled (v1 has `AAPL-numerator` and others). Its rows get the chunk-match check only |

**Checks.** Each is an error unless marked otherwise.

1. **Anchors.**
   - Each gold part has at least 1 gold row for (qid, part).
   - Every row for the qid matches a chunk (`retrieval_replay.gold_matches`).
   - The matched chunk's ticker is among the part's companies: `grading.entry_companies` for an
     entry, else the question's tickers.
   - At least one of the part's rows has an anchor containing the part's figure
     (`retrieval_replay.figure_matches`; for text, `grading.text_matches(anchor, accepted)`).
   - On a non-judged question, a row whose part isn't a gold part is an error, so a typo'd part
     can't silently never count.
2. **Derivations.**
   - **Recompute.** Evaluate bottom-up: `numeric_utils.normalize` each input, then
     `calculate._apply_calculate_operation`, which is the tool's own arithmetic and rounding.
   - **Tool guards.** Copy the guards `call_calculate` applies before the arithmetic
     (`calculate.py:150-158`): operands of mismatched categories are an error, and a zero
     divisor for divide, percent_of or percent_change is an error. This also prevents a
     `ZeroDivisionError`.
   - **Result check.** An error when the recomputed result is outside
     `match_tolerance(norm_expected, question tolerance)` of the expected value. That's the
     grader's own band, including its absolute floor.
   - **Rounding spread.** Unrounded arithmetic, with each anchored input at ± half a unit of its
     authored value's last decimal (the `_decimals` rule `figure_matches` uses), over all
     corners. Constants are exact. The spread is the half-width of the result's range.
     - Spread wider than the default band (`match_tolerance(norm_expected, None)`) and no
       `tolerance` set: error, "needs a tolerance (spread X)".
     - Spread wider than a `tolerance` that is set: error.
     - A `tolerance` set when the default band already covers the spread: WARN, "unneeded".
     - The spread is always printed, so `tolerance_note` can record it, as the map requires.
3. **XBRL cross-check** (INFO/WARN only).
   - Applies to each anchored figure whose unit isn't percent.
   - Looks in the companyfacts of the matched chunk's ticker (`discover_tags.fetch_company_facts`,
     disk-cached in `--xbrl-cache-dir`) for facts whose `accn` is one of the part's anchor
     accessions and whose `val` matches the normalized raw figure within its authored precision.
   - A match is INFO naming the taxonomy:tag, the unit (USD, shares, ...), the period and the
     form, for the author to check by eye. Expect some unrelated matches: a 10-K carries
     hundreds of facts.
   - No match is INFO: "no XBRL fact matched (text-only or untagged)".
   - A fetch failure (`requests.RequestException`, `OSError`, `ValueError`) is a WARN naming the
     ticker, and the run continues. Tickers come from chunk metadata, so they are always in
     `companies.json` and the fetch's `KeyError` can't occur.
   - Driven by value rather than by a tag the author records: it needs no schema field, and it
     confirms the value the anchor shows, not a tag the author chose.
   - `fetch_company_facts` gains an optional `cache_dir` parameter (default: the module's
     `CACHE_DIR`, read at call time).
4. **Absence.**
   - For `absence_terms`, search every chunk of the question's companies, across all of their
     filings: case-insensitive, whitespace-collapsed substring.
   - Any hit is an error, with the accession, chunk index and a snippet. The author either fixes
     the question or picks a narrower term. There is no override field: a check you can
     acknowledge away doesn't show absence.
   - When the question's companies have zero chunks, that's an error: nothing was searched.
   - Hits in other companies' chunks are INFO counts, the corpus-wide record.
5. **Question tickers vs `companies.json`.** A ticker outside `COMPANIES` is an error on a
   question with something to grade (`expected`, `expected_value` or `forbidden_values`). A
   refusal may name an uncovered company.
6. **Entry companies made explicit.** On a question with 2 or more tickers, a comparison entry
   whose label isn't exactly a ticker and has no `companies` list is an error. Without the
   list, a per-company figure, or a value across only some of the companies, is charged to all
   of them.
7. **Trap beside the answer** (WARN). A `forbidden_values` figure that `figure_matches` finds in
   a chunk holding one of the qid's gold anchors gets a warning: "a correct answer may state it
   for context and fail". This makes the checklist constraint mechanical where it can be.
8. **Id collision.** When the file being checked isn't `config.QUESTIONS_PATH`, an id already
   used in v1 is an error. Gold rows are keyed by qid and shared between the files.

**Authoring checklist.** It lives in the module docstring and shows with `--help`:
- Draft from the chunk files and the filings, never through the agent's tools.
- Give each figure gold rows with a short verbatim anchor.
- Pick trap values that a correct answer has no reason to state and cite. Not the comparative
  column printed beside the answer: a claim that states the trap value for the asked company
  fails the answer.
- On a multi-company question, list `companies` on each non-ticker entry.
- Record a `derivation` for every derived value, with its inputs anchored.
- Record `absence_terms` for every never-disclosed refusal.
- Set a `tolerance` only when the script reports a spread that needs one, and record that
  spread in `tolerance_note`.
- The batch passes this script before the user reviews it.

**Logging.** This is a hand-run devtool whose report is its output, like the other devtools.
Its one external call, the companyfacts fetch, reports failures in that output (check 3).

### Reuse
- `retrieval_replay`: `load_gold`, `gold_matches`, `figure_matches`, `_decimals`.
- `index_chunks`: `load_chunks`, `CHUNK_FILE_GLOB`.
- `discover_tags.fetch_company_facts`.
- `calculate._apply_calculate_operation`.
- `numeric_utils`: `normalize`, `match_tolerance`.
- `grading`: `entry_companies`, `text_matches`.
- `questions.question_tickers`.
- `eval_harness.load_questions`.
- `agent_tools.CLAIM_UNITS`.
- `companies.COMPANIES`.

## Steps (TDD, `tdd-live-code-carveout`)

0. Copy this plan to `docs/plans/2026-10-12-phase2-build3b-authoring-check.md` and add its
   `PROJECT_INDEX.md` line.
1. Schema. Write the failing tests in `tests/eval/test_questions.py`, then change the schema. The
   tests:
   - a valid nested derivation, and a constant input;
   - a bad operation, and an input that mixes two forms;
   - a unit typo in each place a unit can appear;
   - a never-disclosed refusal without `absence_terms`, and `absence_terms` on a non-refusal.

   v1 must still validate.
2. `discover_tags.fetch_company_facts`: add the `cache_dir` parameter, with a test using a
   tmp cache file.
3. Checks 1–8, one red-green cycle each, in `tests/devtools/test_check_questions.py`. Cases
   include:
   - a derived question with input rows only (passes);
   - judged rows;
   - a mismatched category, and a zero divisor;
   - a spread over the default band, over a set tolerance, and within it while one is set;
   - absence with zero chunks;
   - a fetch error.
4. CLI `main` test with tmp question, gold and chunk files and a stub fetch: exit codes 0, 1
   and 2.
5. The only live-only line is the default fetch binding, marked `# pragma: no cover`.
6. Smoke run on real data. Not an acceptance bar: v1 predates the checks, so derived v1
   questions without a `derivation` will report their input parts as unexpected. Record the
   counts, and confirm every v1 anchor matches a chunk.
   ```
   PYTHONPATH=src python -m sec_agent.devtools.check_questions --questions eval/eval_questions.jsonl \
     --chunks-dir "C:/riddhesh/projects/SEC research agent/var/chunks" \
     --xbrl-cache-dir "C:/riddhesh/projects/SEC research agent/var/xbrl_cache"
   ```
7. Run `ruff check .`, `pyright .` and `pytest --cov=. --cov-report=term-missing -q`. Diff
   coverage must reach 90% on `questions.py` and 80% on the script and `discover_tags`.
8. BACKLOG: delete line 60, and keep the round-8 items as a line of their own. The commit body
   records the change.

## Verification

- The unit suite is green, and the coverage bars are met.
- The v1 smoke run completes and prints per-question findings, with the expected exit code.
- A hand-made two-question fixture file in the job tmp dir gives exit 1 with exactly the two
  expected errors:
  - a numeric question whose derivation needs a tolerance it doesn't have;
  - a never-disclosed refusal whose term is present in the chunks.

## Plan review

Plan-reviewer agent (opus), 1 round. Every finding was folded in:

1. High: the plan required an anchor for derived values that are printed nowhere. Fixed: a
   question or entry with a derivation needs anchors for its inputs only. Tested.
2. High: the spread rule ignored grading's absolute floor and the tool's rounding. Fixed: the
   spread is computed without rounding, as a half-width, and compared with `match_tolerance`.
3. Med: a set tolerance smaller than the spread passed silently. Fixed: that's now an error.
4. Med: the recompute skipped the tool's category and zero-divisor guards. Fixed: both are now
   errors, and both are tested.
5. Med: judged questions' hand-labelled gold parts had no rule. Fixed: they get the chunk-match
   check only.
6. Med: an absence check with no chunks passed vacuously. Fixed: zero chunks is an error. Hits
   stay errors with no override field: a check that can be acknowledged away doesn't show
   absence.
7. Med: the smoke run had no `var/` in the worktree. Fixed with `--chunks-dir` and
   `--xbrl-cache-dir`, plus `PYTHONPATH=src`.
8. Low: units should be a schema enum. Adopted: check 6 is now in the schema.
9. Low: question ids could collide across files. Added check 8.
10. Low: the XBRL cross-check will be noisy. Matches compare normalized raw values, name the
    unit, and stay at INFO level; the `KeyError` case is ruled out.
11. Low: the import cost is a few seconds. Noted; the "not Chroma" wording is fixed.
12. Low: "last printed digit" was undefined. Fixed: it's now the authored value's `_decimals`.

## Review log

**Round 1** (snapshot `1e4a0f6`; Substantial by design tier): `/code-review high`, `arch-reviewer`
(sonnet), `security-reviewer`, `/simplify` (4 angles).

- code-review: a top-level `derivation` on a non-numeric question crashed the checker with a
  `KeyError`. [Fixed] `derivation` (top level) is numeric-only, checked at load beside
  `absence_terms` in `_TYPE_ONLY_FIELDS`.
- code-review + arch: a part name used for two figures silently kept one. [Fixed] `_part_clashes`
  errors on a name given two figures, or one figure of different companies.
- code-review: a derivation whose inputs are all constants needed no anchor. [Fixed] Error.
- code-review: the absence search missed punctuation and Unicode variants (hyphens, curly
  quotes). [Fixed] `_fold` reduces text to lower-case alphanumeric words before the substring
  search. Spellings it can't equate (noninterest vs non-interest) are a checklist line.
- code-review: the spread reads precision from the authored value, so writing "1.2 billion" as
  1200 million understates it. [Fixed, checklist] Inputs are written as the filing prints them.
  Deriving precision from the anchor's printed number would need `figure_matches` to report its
  scale; not worth it while the checklist covers it.
- code-review: a spread was still checked when the recompute's unit category differed, and the
  "tolerance unneeded" WARN ignored derivations that errored. [Fixed] Both.
- code-review: trap-beside-answer ignored the trap's own `ticker`. [Fixed] Only that company's
  gold chunks count.
- code-review: `accepted` wasn't a graded field for the ticker check. [Fixed]
- code-review + arch + altitude: `_EXACT_OPERATIONS` copies calculate's formulas unrounded and
  could drift. [Fixed, pinned] A test checks every operation against
  `_apply_calculate_operation` where rounding is moot. A shared public function in
  `calculate.py` (critical core) is out of this change's scope.
- code-review + efficiency: the corpus-wide absence count ran on the hit path too. [Fixed] Only
  on the no-hit path.
- arch nits: the `1e-9` allowance comment and the Python-side type-only rule's comment [Fixed];
  private imports (`_apply_calculate_operation`, `_decimals`) and `assert` narrowing
  [Verified, no fix needed: the plan chose this reuse over copies, and renaming touches
  critical core]; plan Addendum and stale review item 8 [Fixed, Addendum below].
- security: no findings.
- /simplify applied: one derivation-tree walk; `_figure_parts` lost two constant parameters;
  `gold_parts` removed; one band in `_check_spread`; XBRL facts indexed by accession once per
  ticker instead of scanning the whole payload per part; `_fold` builds on
  `normalize_for_match`. Skipped: moving `retrieval_replay`/`index_chunks` helpers to a light
  module to save ~3-5 s of chromadb import (touches critical core); a shared precision helper
  (same); splitting `_compute`'s mode flag and the tri-state in `_check_derivation`
  (cosmetic); keying `check_tickers` by type; precomputing folded text for every chunk (it's
  needed only for absence questions).

**Round 2** (delta from `1e4a0f6`): `/code-review low`, `arch-reviewer` (sonnet),
`security-reviewer`.

- code-review: `trap.get("ticker", single_ticker(question))` evaluates the default eagerly.
  [Verified, no fix needed] `single_ticker` returns None for a multi-company question and never
  raises, and `.get` returns the trap's own ticker when present; a test covers that case.
- arch: `check_absence` docstring left run-on by an edit. [Fixed, nit]
- arch: a punctuation-only absence term folds to "" and matches every chunk. [Verified, no fix
  needed] It fails loudly, as a hit in every chunk, never as a silent pass.
- arch: `_fold` drops non-ASCII letters. [Verified, no fix needed] Filings are English; the
  docstring says so.
- security: no findings.

Round 2 found no new issue needing an executable change, so the review is closed.

## Addendum (2026-10-12)

- `absence_terms` (and, after review, a top-level `derivation`) being allowed on one type only
  is checked in `validate_questions`, not the schema: the schema's error for that rule names no
  field.
- Output uses `+/-` and `ascii()` chunk snippets in place of `±`: Windows pipes default to
  cp1252, and chunk text holds characters it can't encode.
- Plan review item 8 says "check 6 is now in the schema": it was the units-enum check, numbered 6
  in the draft, that moved into the schema. Check 6 in the final list is the entry-companies
  check.
- Smoke run on v1 (step 6): 48 questions, 27 errors, all from the 9 derived v1 questions that
  predate `derivation` (3 each: two unexpected input parts and no `value` rows). Every v1 anchor
  matches a chunk. 19 XBRL matches, about 13 s.
- Verification fixture (two questions, real chunks): exit 1 with exactly the two expected
  errors, "needs a tolerance (spread +/-1.15 percent)" and an absence term found in 13 AAPL
  chunks.