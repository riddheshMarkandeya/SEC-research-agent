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

## Review log

(pending)
