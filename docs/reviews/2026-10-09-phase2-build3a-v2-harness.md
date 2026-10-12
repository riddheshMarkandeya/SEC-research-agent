# Review: phase 2 build 3a, v2 eval harness

Plan: `docs/plans/2026-10-09-phase2-build3a-v2-harness.md`. Question schema validated at load,
v2 graders (`text`, judge-templated `refusal`/`clarify`), the shared `[1, 6]` multi-source
citation fix, question-file hash and pooling by question file, grade-flip reporting in the gate
replay. It was reviewed with lexical company attribution and `forbidden_values` grading
included; round 4 removed both on the user's decision. About 1,500 changed lines across
`eval/`, `agent/`, `prompts/`, `verification/` and `devtools/`, so Substantial passes. Suite:
1522 before review, 1552 at the end of round 3, 1494 after round 4's removals.

## Round 1

Snapshot `6a53307`. Passes: `/code-review` high, `arch-reviewer` (sonnet), `security-reviewer`,
`/simplify` (reuse, simplification, efficiency, altitude).

1. **High** (code-review): a per-question `tolerance` widened only the text match, so a value in
   the extra band found no citation claims and skipped the citation check. `[Fixed]`: one
   `numeric_utils.match_tolerance`, passed through to `value_is_citation_verified`.
2. **Medium** (code-review): "J.P. Morgan." ended a sentence, cutting the name off its number.
   `[Fixed]` (refined in round 2).
3. **Medium** (code-review): a pronoun ("Its net income") names no company. `[Deferred → BACKLOG]`
   ("v2 attribution misses two common phrasings"): absent from 245 stored passing answers;
   measure on build 4's first batch.
4. **Medium** (code-review): "(JPMorgan: $58.5 billion)" after a value stole its attribution.
   `[Fixed]` (refined in round 2).
5. **Medium** (code-review): bold pseudo-headings and column-per-company tables attributed
   nothing. `[Fixed]`: bold lines count as headings; a table cell takes its header cell's company.
6. **Medium** (code-review): "X and Y reported A and B, respectively" credits both to Y.
   `[Deferred → BACKLOG]`, same item as 3.
7. **Medium** (code-review): `forbidden_hits` fails a correct answer that states the trap value as
   prior-year context. `[Disputed]`: this is the frozen map's rule (no period parser), pinned by
   `test_prior_year_context_mention_hits_by_design`; 3b's authoring checklist picks trap values a
   correct answer has no reason to state.
8. **Low** (code-review): ordinal and day-first dates didn't normalize. `[Fixed]`.
9. **Low** (code-review): `--questions` compared unnormalized. `[Fixed]`.
10. **Low** (code-review): replay blamed drift-caused grade flips on the grader. `[Fixed]`: own
    bucket.
11. **Risk** (arch): tolerance rule duplicated in citations.py. `[Fixed]` with 1. Copies in
    `calculate.py` and `table_grounding.py` `[Deferred → BACKLOG]` ("Two copies of the
    match-tolerance formula remain"): outside the diff.
12. **Nits/q** (arch): import placement, two docstrings, grading.py module docstring, Addendum
    gaps. `[Fixed]`.
13. **security**: no findings.
14. **simplify**: module-level validator, `_sole_entity`, one grade-change dict, cwd-independent
    `--questions` default `[Fixed]`. Skipped with reasons: reuse of `eval_harness._root_relative`
    (importing it loads the agent stack, ~9 s), month table and `CITATION_PATTERN` alias
    (marginal), efficiency 2-4 (microseconds). `analyze_citation_gate` classing refusal/clarify
    rows `[Deferred → BACKLOG]` (no v2 report exists yet); alias-coverage check folded into the
    build 3b item.

## Round 2

Delta `6a53307..a1023ba`. Passes: `/code-review` high, `arch-reviewer` (sonnet),
`security-reviewer`.

1. **Medium** (code-review): out-of-repo `--questions` paths spelled with `/`, reports with `\`.
   `[Fixed]`: platform spelling, as the harness records.
2. **Medium** (code-review): round 1's parenthesis fix rejected "(Walmart FY2025)". `[Fixed]`: a
   parenthesis tags unless it holds a figure of its own.
3. **Medium** (code-review): the prebuilt validator reported the first error, not the best.
   `[Fixed]`: `best_match`.
4. **Low** (code-review): a period-column table under a company heading attributed nothing.
   `[Fixed]`: the lead-in search skips table rows.
5. **Low** (code-review): round 1's initial rule swallowed sentence ends after "U.S.". `[Fixed]`:
   only periods inside alias names, plus Inc./Co./Corp., are protected.
6. **Low** (code-review): "5.25 June 2024" read as a date. `[Fixed]`.
7. **Low** (code-review): tolerance copies elsewhere. Same as round 1 item 11 (BACKLOG).
8. **Low** (code-review): an own `root_relative` in config.py instead of a copy. `[Verified, no fix
   needed]`: the copy's spelling now matches; moving it widens the diff into `config.py` for one
   line.
9. **Nit** (code-review): `grade_changes["drifted"]` vs `s["drifted"]`. `[Fixed]`: `tool_drift`.
10. **Nit** (code-review, arch): comment left above the wrong import. `[Fixed]`.
11. **Risk** (arch): Addendum step numbering. `[Fixed]`. **q** (arch): drift vs refused
    precedence. `[Fixed]` (docstring).
12. **security**: no findings.

Round 2's code-review findings were new issues in round-1 fixes, not repeats. Findings 2, 4
and 5 were fixed, then made moot by round 4.

## Round 3

Delta `a1023ba..df2be47`. Passes: `/code-review` high, `security-reviewer`.

1. **security**: no findings.
2. **Medium/Low** (code-review), 8 findings in the prose-attribution rules: "U.S. GAAP" splitting a
   sentence, "(Walmart's was lower)" taken as a tag, a parenthesis search crossing lines,
   "percent" and plain counts missing from the own-figure check, a table skip overriding a
   no-company header, duplicated suffix lists, and missing negative tests. Three came from round
   2's own fixes. Each round had found the same class of issue with no clean fix, which is the
   escalation case. It went to the user, who chose to drop prose attribution and attribute
   through the agent's structured claims instead (BACKLOG "Phase 2 build 3a.1"). Moot after
   round 4.
3. **Low** (code-review): `_DAY_FIRST_DATE`'s `,` lookbehind blocked "Monday,25 June 2024".
   `[Fixed]`: `(?<!\d[.,])`, with a test.

## Round 4

Delta `df2be47..f04039c`: the removal (552 lines deleted, 30 added). Passes: `/code-review` low,
`security-reviewer`.

1. **security**: no findings.
2. **code-review**: no findings. Its prompt to look for helpers left without callers:
   `extract_numbers_with_spans` was already unused in `src` on master; the others still have
   callers. `[Verified, no fix needed]`.

## Live verification

None (offline session: the Gemini quota was reserved for the v1 gate). Offline stand-ins:

- Gate replay `--compare` against the base replay on master code: 276 v1 runs since 2026-10-06,
  0 grade changes, 0 verdict changes, re-run after rounds 1-2 with the same result; 9 graded
  runs cite with multi-index brackets.
- `check_attribution` (before its removal) over 245 stored passing v1 comparison answers: 6
  flagged, all genuinely wrong (August runs matching MSFT's 18% for Apple's 17.9%); unchanged
  after rounds 1-3. Claim-based attribution should catch the same 6: each cites a Microsoft
  source for the value.

Owed after merge: a targeted v1 `--ids` run on the multi-bracket questions (BACKLOG "Live
spot-check owed for the `[1, 6]` grader fix").

## Outcome

Shipped on branch `phase2-build3-harness`, to merge after the 2026-10-10 v1 gate: question
schema and load-time validation, `text`/`refusal`/`clarify` grading, the `[1, 6]` fix, one
tolerance rule, question-file provenance and pooling, and grade-flip reporting in the replay.
Lexical attribution was removed.

Open in `BACKLOG.md`:
- **[feature, High, Standard]** Phase 2 build 3a.1, claim-based company attribution. It must
  land before build 4's first batch counts.
- **[feature, Low, Standard]** A `ticker` field on claims, checked by the gate.
- **[refactor, Low, Standard]** Two copies of the match-tolerance formula remain.
- **[bug, Low, Standard]** `analyze_citation_gate` counts refusal and clarify rows.
- **[bug, Med, Standard]** A bullet that starts with its number reads as negative.
- The live spot-check owed for the `[1, 6]` fix.

Final suite: 1494 passed. The review closed after 4 rounds. The repeat after round 3 went to the
user, who changed the design rather than ask for another patch.
