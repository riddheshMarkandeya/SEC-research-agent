# Phase 2 build 3a: v2 eval harness (schema, graders, `[1, 6]` fix, question hash)

## Context

BACKLOG "Phase 2 build 3: v2 harness". The decisions are frozen in
`docs/plans/2026-10-07-data-expansion-phase2-map.md` ("v2 question types and mix", "Grading new
question types", "Not-yet-specified items closed", "Build order" item 3). v2 (~56 questions, 7
categories) needs a question schema, new graders, the multi-source citation fix and question-file
provenance before build 4 can write any questions. The user split build 3 (2026-10-09):

- **3a (this plan):** schema, graders, `[1, 6]` fix, question-file hash, per-category summary,
  quota rule text.
- **3b (own session, own plan):** the `devtools` authoring check script (verbatim anchors,
  companyfacts cross-check, recomputed derived values, corpus-wide absence search). It needs the
  schema that 3a fixes. Build 4 waits on 3b.

Constraints: offline only (the Gemini quota is reserved for the v1 gate after 2026-10-10 07:00Z).
v1's graders and questions stay unchanged, except for the `[1, 6]` grader fix, which the map
names explicitly. Its effect on v1 is measured offline. Work happens on branch
`phase2-build3-harness`, chosen by the user, and merges after tomorrow's v1 gate has run on
master. Each session ends with the checkout back on master, so the gate runs on master's code.

### Facts established in exploration

- `agent/citations.py:29` `_CITATION_MARKER = \[(\d+)\]` drives `_iter_citation_claims`, whose
  only consumer is `value_is_citation_verified` (the grader's check). A value cited only as
  `[1, 6]` is currently invisible: it counts as "never cited" and passes, or it falls into the
  next single marker's window. 132 of 2,700 stored eval answers use multi-index brackets,
  including today's v1 runs, so the fix can flip v1 grades in either direction.
- `eval_harness.CITATION_PATTERN` (`\[\d+\]`) feeds only `has_citation` (report flag). This is
  BACKLOG line 74.
- `citations._ANY_CITATION_BRACKET` already matches `[1, 3, 5]` (used by `verify_claims`).
- `companies.json` has **no aliases**, and its schema forbids extra keys. The map's
  "`companies.json` alias" premise is wrong (see Deviations).
- v1 `comparison` entries are not always companies: segments (`MSFT-PBP`) and periods
  (`NVDA-Q1FY27`) are used as entry labels. None of the 43 recent passing comparison answers
  uses a table; they use bullets or sentences.
- `prompt_fingerprint()` returns per-surface keys and hashes each snapshot section separately
  (`prompts/__init__.py:45`). `compare_prompt_versions` groups reports by the `agent` key alone
  (`:175-183`); every `_CONSISTENCY_CHECKS` entry (judge key, config, ...) only warns.
- `_grade_by_type` is shared by `_grade`, `_citation_gate_evidence` and
  `analyze_gate_replay.grade()` (which returns None for anything but numeric/comparison).
- `PROVENANCE_PATHSPECS` names only the default `QUESTIONS_PATH`.
- `analyze_gate_replay` already re-grades numeric/comparison runs offline through
  `eval_harness._grade_by_type`, but its `--compare` reports gate-verdict changes only, not
  grade flips.

## Decision / Design

### 1. `[1, 6]` fix (shared by v1 and v2)
- `citations.py`: rename `_ANY_CITATION_BRACKET` → public `ANY_CITATION_BRACKET`.
  `_iter_citation_claims` walks `ANY_CITATION_BRACKET` matches. The window per bracket is
  unchanged. For each in-range index in the bracket it yields the window's claims, verified
  against that index's source. `value_is_citation_verified`'s `any(matches)` then means "at least
  one of the bracket's sources grounds it", which is the same semantics as a single marker.
  Remove `_CITATION_MARKER` if it ends up unused, and rewrite the comment that says it can't be
  widened.
- `eval_harness.CITATION_PATTERN = ANY_CITATION_BRACKET` (closes BACKLOG line 74).

### 2. Question schema: new `src/sec_agent/eval/questions.py`
- `QUESTION_SCHEMA` (jsonschema, already a dependency), `additionalProperties: false`, so a typo
  like `expected_vale` fails at load:
  - common: `id`, `question`, `type` ∈ {numeric, comparison, judged, text, refusal, clarify},
    `ticker` | `tickers`, `skip`.
  - per type (if/then): numeric needs `expected_value` and `expected_unit`; comparison needs
    `expected[]`; judged needs `criteria`; text needs `accepted[]` (≥1); refusal needs
    `refusal_kind` ∈ {not_covered, not_yet_filed, never_disclosed, false_premise}; clarify needs
    `readings[]` (≥2). refusal and clarify take an optional `criteria` (question-specific detail
    appended to the template).
  - v2 tags: `category` ∈ {extraction, numerical-reasoning, cross-period, cross-company,
    text-footnote, refusal-trap, ambiguous}, `steps` (int ≥1, reported as 1/2/3+),
    `answer_source` ∈ {table, text, both}, `trap` ∈ {none, look-alike, fiscal-label,
    false-premise, not-disclosed, out-of-corpus, future-period}, `needs_calculate` (bool).
    `dependentRequired`: `category` present → all five tags required. v1 questions carry none.
  - Optional: `accepted` on numeric/comparison (the ambiguous-default "name the period" check),
    `forbidden_values[]` ({value, unit, ticker?}), `tolerance` (relative, >0) with a required
    `tolerance_note`.
- `validate_questions(questions)` validates each question and checks that ids are unique. It
  raises `ValueError` naming the id or line number. `eval_harness.load_questions` calls it, so a
  malformed file fails before any quota is spent (closes BACKLOG line 228).
- Acceptance: all 48 v1 questions validate unchanged (test).
- 3b will **amend** this schema with its own optional keys (derivation inputs for recomputed
  values, the absence-search record for never-disclosed refusals). Verbatim anchors need no
  schema change: they live in `eval/retrieval_gold.jsonl`, keyed by qid, as in v1.

### 3. Graders: new `src/sec_agent/eval/grading.py` (pure, offline-testable)
- **Aliases** (`ENTITY_ALIASES`) are built from `COMPANIES`: the ticker, the full name, the name
  minus its legal suffix (Inc., Corporation, & Co., ", Inc."), plus a small hand table (JPMorgan,
  JP Morgan, BofA, Exxon, ExxonMobil, J&J, Palantir, Nvidia). Matching is case-sensitive with
  word boundaries ("Target" the company, not "target margin").
- **Segments**: split on newlines (bullets, table rows), then on sentence ends
  `(?<=[.!?])\s+(?=[A-Z])`. **Clauses** within a segment: split on `;` or `, ` (comma followed by
  a space, so `35,013` stays whole) and on ` vs. `/` versus `/` while `/` compared to|with `.
- **`attributed_entity(answer, span)`**, three steps, first hit wins:
  1. the nearest alias before the number in its clause;
  2. else the nearest alias after it in its clause (`$X at JPM`, `$X (JPM)`);
  3. else the nearest alias before it in its segment.
  Otherwise `None`. Tests cover prefix ("JPM reported $X, and BAC reported $Y"), postfix ("$X at
  JPM vs $Y at BAC", "$X (JPM)"), possessives and bullets.
- **`value_occurrences(answer, value, unit, tolerance)`**: spans of matching numbers. Reuses
  `numeric_utils.extract_numbers_with_spans` and `normalize`, with the same 1% rule as
  `grade_numeric`.
- **`check_attribution(answer, expected)`**: for each entry whose label is a known ticker, at
  least one occurrence of its value must be attributed to that ticker. Non-ticker labels
  (segments, periods) are skipped. It returns the misattributed entries.
- **`text_matches(answer, accepted)`**: normalizes both sides. Dates go to ISO first ("January
  31, 2026", "Jan. 31, 2026", "1/31/2026", "2026-01-31"), then lowercase, strip punctuation and
  collapse whitespace. It then does a whole-word substring match of any accepted variant.
- **`forbidden_hits(answer, forbidden, asked_ticker)`**: an occurrence counts only when it is
  attributed to the forbidden entry's ticker (default: the question's ticker), as in the map.
  Unattributed occurrences are ignored. Known cost, kept per the map's no-period-parser rule: a
  correct answer that also states the trap value for context ("Target's revenue was $Y, up from
  $X") fails. A test pins this. 3b's authoring checklist gets the constraint: pick trap values a
  correct answer has no reason to state (not the comparative column printed beside the answer).

### 4. Judge criteria templates: new `src/sec_agent/prompts/judge_criteria.py`
- `REFUSAL_CRITERIA` {kind: text}: each requires a refusal or no-answer that gives that kind's
  reason. `CLARIFY_CRITERIA` with `{readings}`: pass on a clarifying question, or on an answer
  that covers each reading with its label. FINGERPRINTED.
- It gets its own surface and consumer key `judge_criteria`. The key hashes the surface plus a
  new `judge_criteria` snapshot section: a scenario in `test_model_input_snapshot.py` renders
  each refusal kind and a clarify question through the harness's template filling (including
  an appended per-question `criteria`). The snapshot is regenerated in the same commit.
  Sections hash separately, so the `judge` key, and with it v1's judge fingerprint, stays equal
  to master's. `test_prompts.py` `SURFACES`/`CONSUMER_KEY` get the new entry.
  `compare_prompt_versions._CONSISTENCY_CHECKS` gets a `judge_criteria` warning.
  `grade_judged` and `judge.py` are untouched: the harness passes the filled template as
  `criteria`.

### 5. Harness wiring (`eval_harness.py`)
- **Deterministic grading lives in `_grade_by_type`**, so `_grade`, `_citation_gate_evidence`
  and the replay all see the same verdict:
  - numeric and comparison (as now), plus text: `text_matches` and ≥1 `CITATION_PATTERN`
    marker;
  - then, on a pass: the `accepted` check if present; for v2 comparison questions (`category`
    present), `check_attribution`; `forbidden_values` if present. Each failure has its own
    detail string.
  - `DETERMINISTIC_TYPES = ("numeric", "comparison", "text")` is used by the hard-gate
    short-circuit, `_citation_gate_evidence` and `analyze_gate_replay.grade()`.
- `_grade` adds refusal and clarify (`grade_judged` with the filled template). judged is
  unchanged. Refusal, clarify and judged can't be re-graded offline (they need the judge); the
  docstrings say so.
- `grade_numeric` takes an optional `tolerance` (default: the current 1%, so v1 is
  byte-identical). `_grade_by_type` passes `q.get("tolerance")`.
- Report rows add `category` and `trap` when present. `format_summary` adds a per-category table
  (same columns as `_type_table`, with the label column sized to the longest name, since
  "numerical-reasoning" is 19 characters) when any row has a category, so `--summarize` works on
  saved reports too.
- Provenance: `config["questions"] = {"path": <root-relative>, "sha256": <12 hex of the bytes
  with CRLF→LF>}`. `_collect_provenance(questions_path)` gets it from `main`, and
  `_git_state` adds that path to the dirty-check pathspecs, so an uncommitted v2 file marks the
  run dirty.
- **Pooling is enforced, not just warned:** `compare_prompt_versions` groups by `(agent
  fingerprint, questions path)`. A report without the field counts as `eval/eval_questions.jsonl`,
  which is true of every existing report, so v1 history keeps pooling. A questions-hash
  difference within a group warns through the existing `config` check (a v1 question edit).
- Module docstring: list the six types.

### 6. Measurement tool: `analyze_gate_replay --compare` reports grade flips
- Add a `grade_changes` bucket: runs whose `correct` differs from the base's (True/False only),
  computed in `_tally_against_base` **before** its early returns (errors) and before `_tally`'s
  "unchanged verdict" return. A flip on a run the gate refuses now is listed separately
  (`grade_changes_refused`): the replay grades the text as if it had been let through, so that
  flip isn't a real v1 verdict change. `compare_failed` is unchanged; flips are listed, not
  failed on. This covers grader-only changes to the deterministic types (numeric, comparison,
  text), now and later.

### 7. Docs and rules
- `.claude/rules/live-eval-verification.md`:
  - add `src/sec_agent/eval/grading.py` to `paths:`;
  - add the map's quota and gating rule: never run v1 and v2 on the same quota day; v1 gates
    corpus, fact-tool, retrieval and grader changes (`--ids`, then a full run); agent and prompt
    headroom work runs v2 first and is kept only if v2 improves, then the full v1 runs the next
    day; a grader-only change re-grades stored runs with `analyze_gate_replay --compare`, with no
    generation quota.
- BACKLOG (edit items by their text, not line numbers):
  - delete the `CITATION_PATTERN` multi-index item and the `_select_questions` malformed-question
    item;
  - rewrite the build 3 item as 3b (script), including the schema amendment and the
    forbidden-value authoring constraint;
  - add a "live spot-check owed" item: after merge, a targeted v1 `--ids` run on the questions
    with multi-index citations, on a day with spare quota;
  - add to build 4's item: the first batch includes a judge sanity pass on the refusal and
    clarify templates (known-good and known-bad answers) before its questions count.
- Plan copy `docs/plans/2026-10-09-phase2-build3a-v2-harness.md` plus a `PROJECT_INDEX.md` line.
  Review file at the end (Substantial).

## Deviations from the frozen map (named, per §4)

- **Aliases live in `eval/grading.py`, not `companies.json`.** The map assumed aliases already
  exist there. Adding them would change a validated agent-facing file (the `sources/` critical
  core and its schema) for an eval-only need.
- **Attribution and forbidden values apply to v2 questions only** (keyed on `category`). This
  follows the map's own "v1's graders unchanged". The `[1, 6]` fix is the one shared change, as
  the map lists it.
- **Attribution looks after the number too.** The map says "nearest preceding company name".
  A preceding-only rule fails correct postfix phrasings ("$X at JPM vs $Y at BAC" credits Y to
  JPM). Hence the clause-scoped three-step rule in §3.

## Files and steps

TDD for every pure function; commits on the branch.

0. `git switch -c phase2-build3-harness`. Commit the plan copy and index line.
1. **Replay base on master code, before any edit:** `python -m sec_agent.devtools.analyze_gate_replay`
   on the v1 traces since 2026-10-06 (exact flags read from its `--help` at run time), written
   to `var/` and run in the background. Record the run count and wall time. While it runs, only
   write new files the replay doesn't import (`questions.py` and its tests). No edits to
   existing `agent/`, `eval/`, `devtools/` or `verification/` modules until it finishes.
2. `[1, 6]` fix. Red tests in `tests/agent/test_citations.py`: a value cited `[1, 2]` where only
   source 2 grounds it is verified; one where neither grounds it is not; an out-of-range index
   inside a bracket is ignored; single `[n]` behaviour is unchanged. `CITATION_PATTERN`
   `has_citation` test.
3. `grade_changes` bucket (test), then the candidate replay with `--compare` against the step-1
   base. Every flip is listed and explained in the commit body.
4. `questions.py` schema and validation (tests: the v1 file validates; each type's missing field;
   tag dependency; unknown key; duplicate id; tolerance without a note).
5. `grading.py` (tests use realistic answer text lifted from stored reports: bullet and sentence
   comparisons, a JPM/BAC swap, a possessive, "Target" lowercase noise, dates in 4 formats,
   forbidden value attributed vs unattributed vs another entity).
6. `judge_criteria.py`, surface and consumer key, snapshot scenario and regeneration,
   consistency check (tests in `tests/prompts/`; a test asserts the `judge` key equals its
   pre-change value).
7. Harness wiring, tolerance, rows, category table, questions hash, dirty pathspec, and pooling
   by questions path in `compare_prompt_versions`. Tests:
   - in `tests/eval/test_eval_harness.py`: dispatch per type with `grade_judged` stubbed; the
     v1 numeric/comparison detail strings unchanged; `_citation_gate_evidence` on a text
     question; the hash stable across CRLF/LF;
   - in `tests/devtools/`: pooling and the consistency check.

   Fix the fixtures that the load-time validation breaks: `test_eval_harness.py:158-162` (no
   `type`), and `:427` and `:829` (numeric without `expected_value`). Grep for any others.
8. Offline sanity: a scratch script in the job tmp dir runs `check_attribution` over the stored
   passing cross-company v1 answers (AAPL/MSFT, NVDA/CRM). Expect every one attributed; any
   miss is fixed or explained.
9. Rules and BACKLOG text. Pre-commit checks: `ruff check .`, `pyright .`,
   `pytest --cov=. --cov-report=term-missing -q`; changed lines ≥90% (eval/, prompts/, agent/
   are critical core).
10. Give the `/compact` line, then `independent-review-pass` (eval/ and agent/ are critical core,
    so at least Standard), review file, `git switch master` at session end.

## Testing and verification

- Unit tests as listed. Full suite green. ruff, pyright and import-linter at 0 (the new modules
  import downward only: `eval/grading` → `verification`, `sources`; nothing imports
  `devtools`).
- `model_input_snapshot.json` changes only by the new `judge_criteria` section. The `agent`,
  `judge` and `mcp` fingerprint keys equal master's, so v1 history still pools; the new
  `judge_criteria` key is present.
- The v1 question file validates. `--summarize` on an old report still prints (no category table).
- Replay `--compare`: the grade flips caused by the `[1, 6]` fix are counted and each one is
  explained. This is the offline stand-in for the live check.
- **Not done here (no quota):** the live spot-check the rules require for `citations.py` and
  `eval_harness.py`. It's owed after merge (BACKLOG item). The new v2 graders get their first
  live exercise on build 4's first batch / the v2 baseline.

## Plan review

2026-10-09, one round, `plan-reviewer` (Opus), 12 findings, all folded in:

1. High: the new checks sat in `_grade`, invisible to gate evidence and replay. Moved into
   `_grade_by_type` with `DETERMINISTIC_TYPES` (§5).
2. Medium-high: the judge criteria templates had no snapshot coverage. Added a `judge_criteria`
   snapshot section and consumer key, and regenerate the snapshot; the `judge` key is still
   provably unchanged (§4).
3. Medium: preceding-only attribution fails postfix phrasings. Replaced by the clause-scoped
   three-step rule, named as a deviation (§3).
4. Medium: load-time validation breaks three test fixtures. Listed in step 7.
5. Medium: 3b's data had no home in the closed schema. 3b amends the schema; anchors stay in
   `retrieval_gold.jsonl` (§2).
6. Medium: v1/v2 pooling was only a warning, and the v2 file wasn't in the dirty check.
   Grouping now goes by questions path, the path is added to the dirty pathspec, and the wrong
   "consistency break" fact is fixed (§5).
7. Medium-low: unattributed forbidden hits went beyond the map. Reverted to the map's rule; the
   prior-year-context cost is pinned by a test and becomes a 3b authoring constraint (§3).
8. Low: `grade_changes` placement and refused-now runs. Computed before the early returns, and
   refused-now flips get their own bucket (§6).
9. Low: category column width. Sized to the longest name (§5).
10. Low: the background base replay ran while code was edited. Only new, unimported files are
    written until it finishes (step 1).
11. Low: the judge templates need a live check. Build 4's first batch gets a judge sanity pass
    (§7).
12. Low: BACKLOG edits by line number. Now by text (§7).

## Addendum (implementation, 2026-10-09)

Departures from the design above, each found while building it. These supersede §3's
three-step rule and §5's "group by (fingerprint, path)":

- **Lexical attribution was dropped before commit** (user decision, 2026-10-09; revisits the
  map's "nearest preceding company name" rule on new evidence). Three review rounds each found
  new misattributions in the prose-matching rules below, several caused by the previous round's
  fixes. `check_attribution`, `forbidden_hits` and their helpers are gone from `eval/grading.py`;
  v2 comparisons grade like v1, and `forbidden_values` is validated but not graded. The
  replacement attributes through the agent's structured claims: a claim that passed the gate,
  states the value and cites a source whose `metadata.ticker` is the expected company (BACKLOG
  "Phase 2 build 3a.1"). A `ticker` field on claims, checked by the gate, is a later option
  (BACKLOG). The next bullet records what was built and why it was abandoned.
- **Attribution had six steps, not three (since removed).** Step 1 is an adjacent postfix tag ("$681.0 billion
  (WMT)", "$182.4 billion at JPMorgan"): without it, "Target's $106.6 billion vs $681.0 billion
  (WMT)" credited WMT's value to TGT. Step 6 is a fallback for an unnamed bullet: the single
  company named by the nearest heading or "...:" lead-in line above it. The step-8 sanity check
  found this answer shape in stored runs ("- Microsoft's effective tax rate was:" over unnamed
  sub-bullets). A comma before a 4-digit year no longer ends a clause, so "June 27, 2026 (17.9%)"
  keeps its company; the same check found that one. Code review (round 1) added the rest: a
  parenthesis tags only when it closes right after the name ("(JPMorgan: $58.5 billion)" is a
  comparison, not a tag); a markdown table with a column per company takes the name from its
  column's header cell (the new step 5); a bold line ("**JPMorgan**") counts as a heading; and a
  sentence doesn't end at an initial or legal suffix ("J.P. Morgan", "Inc.").
- **Pooling filters instead of grouping.** `compare_prompt_versions` fingerprint mode keeps only
  runs of one question file (`--questions`, default v1, normalized to the root-relative POSIX
  form reports record) and says how many it left out. The effect is the same as grouping by
  (fingerprint, path), and the output stays one comparison. Explicit mode (`--base-files` /
  `--candidate-files`) doesn't filter: the caller picks the files, and a mixed pick shows up only
  as the `config` consistency warning.
- **No pinned hash for the `judge` key.** The parametrized
  `test_changing_one_snapshot_section_changes_only_its_consumer_key` (now including
  `judge_criteria`) proves sections hash independently. A one-off manual check (not a test)
  confirmed the `agent`, `judge` and `mcp` keys equal master's (`0b2c6bd205ea`, `2ee29f234c91`,
  and mcp unchanged). A pinned hash would break on every legitimate judge change.
- **One tolerance rule.** `numeric_utils.match_tolerance` (1%, floor 0.05) replaces the formula
  copied in `citations.py` and the grader. `value_is_citation_verified` takes the grader's
  per-question tolerance, so a widened tolerance can't skip the citation check (code review
  found that bypass). `calculate.py` and `table_grounding.py` keep their own copies: outside
  this diff.
- **Text dates** also accept ordinals ("February 1st, 2025") and day-first forms ("1 February
  2025").
- **Replay grade flips on drifted runs are listed apart**: grading reads the rebuilt tool
  results, so drift alone can flip a grade.
- `validate_questions` also requires each `forbidden_values` entry to name a ticker when the
  question has no single `ticker`, since there is no default company to charge it to.

Measurements:

- Base replay (master code, before any edit): 276 runs since 2026-10-06 (cold cache; wall time not recorded). The warm candidate replay took a few minutes.
  Candidate replay (`--compare`, with the `[1, 6]` fix): 0 grade changes, 0 verdict changes.
  9 of the replayed graded runs cite with multi-index brackets (`crm-rpo-fy26` x3,
  `nvda-revenue-fy26-us-gaap` x4, `nvda-revenue-yoy-growth-q1fy27`,
  `msft-three-segments-revenue-q3fy2026`); all grade the same before and after.
- Step 8 sanity check (before attribution was dropped): `check_attribution` over 245 stored passing v1 comparison answers (4
  company-labelled questions). 6 flagged, all from August, all genuinely wrong: none states
  Apple's 17.9% tax rate, and v1 matched it against Microsoft's 18% within the 1% tolerance. One
  also flags MSFT because `numeric_utils` reads a bullet "- 20%" as -20%: a pre-existing bug,
  filed in BACKLOG (not fixed here: critical core, needs a live spot-check).

## Review log

### Round 1 (snapshot `6a53307`; Substantial)

Passes: `/code-review high`, `arch-reviewer` (sonnet), `security-reviewer`, `/simplify` (4 agents).

- security: no findings.
- arch: imports placement, `_grade` docstring, `_collect_provenance` wording, grading.py docstring
  missing `judge_criteria_for`, Addendum gaps `[Fixed]`; duplicated tolerance rule `[Fixed]`
  (`numeric_utils.match_tolerance`; calculate.py/table_grounding.py copies left: outside diff).
- code-review 1 widened tolerance skipped the citation check `[Fixed]`; 2 "J.P. Morgan." split
  `[Fixed]`; 4 parenthetical steal `[Fixed]`; 5 bold headings / column tables `[Fixed]`;
  8 ordinal / day-first dates `[Fixed]`; 9 `--questions` spelling `[Fixed]`; 10 drift-caused grade
  flips `[Fixed]` (own bucket); 3 pronoun carry-over and 6 "respectively" `[Deferred → BACKLOG]`
  (absent from 245 stored answers; measure on build 4's batch); 7 prior-year context trips
  `forbidden_hits` `[Disputed]`: the map's rule, pinned by a test, 3b authoring constraint.
- simplify: module-level validator, `_sole_entity`, one grade-change dict, cwd-independent
  `--questions` default `[Fixed]`. Skipped: reuse of `eval_harness._root_relative` (importing it
  costs ~9 s of agent-stack load), calculate/table_grounding tolerance copies, month table,
  `CITATION_PATTERN` alias (tests use it), efficiency 2-4 (negligible); `analyze_citation_gate`
  classing refusal/clarify rows and an alias-coverage check (no v2 reports exist yet; to BACKLOG).
- After fixes: 1545 passed, ruff/pyright 0, diff-cover 100%.

### Round 2 (delta `6a53307`..`a1023ba`)

Passes: `/code-review high`, `arch-reviewer` (sonnet), `security-reviewer`.

- code-review high, 10 findings (dispositions after the list):
  1. `root_relative_questions` spells out-of-repo paths with `/`, harness records `\` on
     Windows. Fix: move one `root_relative` into `sec_agent/config.py`, used by both (also #8).
  2. `_tags` rejects "(Walmart FY2025)" / "(WMT, fiscal 2025)" (regressed from round 1).
     Fix: tag when the parenthesis's first name is followed by `)`, `,`, `'s` or a period word
     before any number.
  3. `_VALIDATOR.validate` raises the first error, not `best_match`: vaguer messages. Fix: raise
     `jsonschema.exceptions.best_match(_VALIDATOR.iter_errors(q))`.
  4. Table under a company heading with year columns attributes nothing: let `_lead_in_entity`
     skip table lines.
  5. `(?<!\b[A-Z]\.)` swallows real sentence ends after "U.S." / "Class A.".
  6. `_DAY_FIRST_DATE` matches "5.25 June 2024": add `(?<![\d.,])`.
  7. calculate.py/table_grounding.py tolerance copies (simplify reuse 1 too): decide fix vs BACKLOG.
  9. `grade_changes["drifted"]` vs `s["drifted"]` naming: rename key `tool_drift`.
  10. stale "GEMINI_MODEL_NAME" comment above the `llm_backends` import (same as arch nit).
  This is round 2 surfacing new issues in round-1 fixes, not a repeat. 1, 3, 6, 9, 10 `[Fixed]`;
  2, 4, 5 `[Fixed]` then made moot by round 4; 7 `[Deferred → BACKLOG]` ("Two copies of the
  match-tolerance formula remain"); 8 `[Verified, no fix needed]` (spellings now match; a
  shared helper would widen the diff into `config.py`).

- security: no findings.
- arch: Addendum step numbering (fallback is step 6) `[Fixed]`; drift takes precedence over
  refused in `_tally_grade_change` `[Fixed]` (docstring); stale "GEMINI_MODEL_NAME" sentence
  above the `llm_backends` import `[Fixed]` (imports moved back).
- Offline replay re-run vs `replay-build3a-base.json`: 276 runs, 0 grade changes (0 refused,
  0 drifted-caused), 4 drifted runs, 0 errors.

### Round 3 (delta `a1023ba`..`df2be47`)

Passes: `/code-review high`, `security-reviewer`. Arch not re-run: its round-2 fixes were doc and
docstring only.

- security: no findings.
- code-review high, 9 findings: 8 are new misattributions in the prose-attribution rules ("U.S.
  GAAP" now splitting a sentence, "(Walmart's was lower)" taken as a tag, a parenthesis search
  crossing lines, "percent" and plain counts missing from the own-figure check, a table skip
  overriding a no-company header, duplicated suffix lists, missing negative tests). Three come
  from round 2's own fixes. This is the escalation case (the same class of issue each round with
  no clean fix), so it went to the user, who chose to drop prose attribution: all 8 moot after
  round 4. The ninth, `_DAY_FIRST_DATE`'s `,` lookbehind blocking "Monday,25 June 2024",
  `[Fixed]` (`(?<!\d[.,])`, with a test).

### Round 4 (delta `df2be47`..`f04039c`)

The strip: lexical attribution removed from `eval/grading.py` and `_grade_by_type`, a test pins
that v2 attribution and trap values aren't graded yet. 552 lines deleted, 30 added. Passes:
`/code-review low`, `security-reviewer`.

- security: no findings.
- code-review low: no findings. It asked whether helpers were left without callers:
  `match_tolerance` and `ANY_CITATION_BRACKET` still have callers; `extract_numbers_with_spans`
  was already unused in `src` on master `[Verified, no fix needed]`.

Review closed: a round with no new finding. 4 rounds; checks at close: 1494 passed, ruff and
pyright 0, diff coverage 100%.
