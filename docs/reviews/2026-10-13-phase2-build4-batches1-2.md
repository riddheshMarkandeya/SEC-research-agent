# Review: phase 2 build 4, batches 1–2 (v2 questions, `xbrl_source`, checker check 9)

Plan: `docs/plans/2026-10-13-phase2-build4-batch2.md` (batch 1's plan,
`docs/plans/2026-10-12-phase2-build4-v2-questions.md`, points here). Range
`18e9ec0..HEAD` plus the working tree: batch 1's commit `48ef952` (checker
change, judge sanity script, 11 judge-graded questions) and batch 2 (the
`xbrl_source` schema field, check 9, 10 extraction and period-named
questions). Commit `18e9ec0` (judge templates) had its own review. Suite
before the diff: 1659 passed. Classified Substantial: about 520 changed
lines, with `questions.py` in the critical core.

## Round 1

Passes: `/code-review` high, `arch-reviewer` (sonnet), `security-reviewer`,
`/simplify`. Pre-fix snapshot: `a3d51dbde33af149976188fce77951cab8b3ff9e`.

The first `/code-review high` run misread its argument and reviewed
`18e9ec0` alone. That commit is outside this range and was already reviewed,
so its 9 findings are recorded under "Out of range" below for the user. The
run was then repeated on the right range (`git diff 18e9ec0`).

**`/code-review` high:**

1. **Med**: refusal and clarify gold rows lost the company-ownership check
   when batch 1 made them hand-labelled. `[Fixed]`: `_foreign_rows` now runs
   for judge-graded questions too, and the refusal/clarify test has a
   wrong-company case.
2. **Med**: E3 (Target net earnings, fiscal 2024: 4,091) sat within the 1%
   band of fiscal 2023's 4,138, so the fiscal-label trap couldn't be told
   apart from the answer. `[Fixed]`: swapped to operating income, 5,566
   against fiscal 2023's 5,707.
3. **Med**: `xbrl_source` pins one accession, but the fact tool may return a
   later filing's restated comparative. `[Fixed]`: check 9 WARNs when another
   filing reports the same tag and period with a different value.
4. **Med**: R8 (`v2-cat-backlog-2020`, batch 1) has the criterion "The
   available Caterpillar filings start in 2024". E7 answers a 2020 Caterpillar
   figure from XBRL, so the criterion could fail a correct answer that cites
   the fact tool. `[Fixed]`, after the user approved it: the criterion now says
   that Caterpillar's ingested filings start in 2024, and its XBRL data, which
   does reach 2020, has no backlog figure. Either reason passes. The judge
   sanity script gained a "2020 data, no backlog" case, expected to PASS
   (5 runs). **The live re-run is still owed** because it spends Gemini quota.
5. **Low**: the "printed in a chunk" WARN claimed more than the check shows.
   `[Fixed]`: reworded to "if that's this line item and period".
6. **Low**: the unit-category filter excluded only `pure`, and its message was
   misleading. `[Fixed]`: filter dropped. The value comparison already rejects
   a wrong-scale fact.
7. **Low**: `--gold` defaults to the v1 gold file. `[Deferred → BACKLOG]`:
   this predates build 3b, and the usage text documents `--gold`.
8. **Nit**: printed precision was recomputed for each fact. `[Fixed]`: the
   `_printed_figure` closure computes it once.
9. **Nit**: a redundant `parts = []` branch. `[Fixed]`.

**`arch-reviewer`** (sonnet):

1. **Med**: batch 1's allocation table rows A4–A6 and E1–E7 still showed
   "(open)" and the draft ids. `[Fixed]`.
2. **Nit**: draft slot ids in the batch 2 table. `[Fixed]`: retitled "as
   planned".
3. **Nit**: the Review log was not started. `[Verified, no fix needed]`: it is
   filled at the end of the review, as expected.
4. **Nit**: the usage docstring's line continuation. `[Fixed]`: `\\`.
5. **Nit**: `_fact_category` excluded only `pure`. `[Fixed]`: same as
   code-review 6.
6. **Nit**: a drive-by rewording in `check_id_collision`. `[Verified, no fix
   needed]`: wording only.
7. **Nit**: no `start <= end` or accession-format check on `xbrl_source`.
   `[Verified, no fix needed]`: an impossible period or a bad accession
   already fails as "no fact".

**`security-reviewer`**: no findings. It looked for injection, path,
deserialization and secrets surfaces in the checker, the manual script and the
data files.

**`/simplify`** (reuse, simplification, efficiency, altitude):

- `[Fixed]`:
  - `check_anchors` returns early for an XBRL-only question, with "an
    XBRL-only figure takes no gold rows". This replaced `_part_list`'s `[]`
    special case and the "(none: …)" message.
  - One `_foreign_rows` helper serves both call sites.
  - `_check_source_fact` splits the source facts into agreeing and
    disagreeing ones in a single pass.
  - `_source_facts` compares taxonomy and tag directly, without building a
    string for each fact.
  - The manual script uses `eval_harness.load_report`.
- `[Skipped]`:
  - A `Part.source` dispatch and a shared fact iterator. These are a restructure
    beyond this diff, for a single field.
  - Moving the percent ban from the schema to the checker. That reopens a
    plan-reviewed design choice.
  - A shared tolerance helper with `retrieval_replay`. That formula predates
    this diff, and the two copies use different scale tables.
  - A `by_ticker` chunk index and a `by_tag` fact index. These are offline CLI
    costs at about 20 questions.
  - Folding the manual script's `RUNS` and `QUESTION_KINDS`, and running its
    judge calls in parallel. It is a one-off live script, and parallel calls
    risk the Gemini rate limit.

**Out of range** (the misdirected run over `18e9ec0`, the judge templates in
`src/sec_agent/prompts/judge_criteria.py` and
`src/sec_agent/devtools/compare_prompt_versions.py`). These are for the user
to triage; none was fixed here:

- the REASON_ABOUT_QUESTION example may fail good not_covered refusals;
- not_yet_filed's "latest filing allowed" weakens the rule;
- the clarify wording passes one-reading answers;
- the fail examples don't match the canned refusal texts;
- the judge_criteria fingerprint raises a false warning on v1 reports;
- REASON_ABOUT_QUESTION is fingerprinted twice;
- no unit test pins which kinds get the clause;
- "dated on or before today" checks the filing date rather than the period;
- the verify script exists only from `48ef952`.

## Round 2

Delta: `git diff a3d51db`. Passes: `/code-review` low and `security-reviewer`,
because the delta changes non-test executable code.

- `security-reviewer`: no findings.
- `/code-review` low:
  1. **Low**: the disagreement WARN also listed a second, disagreeing fact
     from the source filing itself, calling it "another filing". `[Fixed]`:
     facts from the source accession are skipped, and the test has that case.
  2. **Low**: `_source_facts` no longer filters by unit category. `[Verified,
     no fix needed]`: this was dropped on purpose in round 1 (code-review 6).
     It is not a new issue.

## Round 3

Delta: the one-line fix to round 2's finding 1. Passes: `/code-review` low
and a security check (sonnet, general-purpose), because non-test code changed.
No findings: the fix only narrows the WARN set, and the test fails without
it. The review closed clean after round 3.

## Outcome

- Shipped:
  - 21 v2 questions (11 judge-graded, 10 extraction and period-named);
  - the `xbrl_source` field;
  - checker check 9;
  - the company check on hand-labelled gold rows.
- The gate exits 0 on all 21 questions, with 0 errors and 0 warnings.
- The full suite passes 1659 tests. `questions.py` and `check_questions.py`
  are both at 100% coverage. ruff and pyright are clean.
- Open:
  - the `--gold` default, in `BACKLOG.md` tagged `[refactor, Low, Trivial]`;
  - the live re-run of `tests/manual/verify_v2_judge_templates.py` for R8's
    reworded criterion, which spends Gemini quota;
  - the out-of-range template findings, waiting on the user.
