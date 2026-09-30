# Split `agent.py` into focused modules (map Decision 13, item 4)

## Context

`src/sec_agent/agent/agent.py` is 2,209 lines and `tests/agent/test_agent.py` is 4,199 lines
(1053 tests pass today). This is the next prerequisite on the agent-improvement map
(`docs/plans/2026-09-28-agent-improvement-map.md`, Decision 13 step 4; BACKLOG line 105). The
map's "`agent.py` module boundaries" frontier ticket is decided here. The improvement packages
that follow (retry slot, gate rules D3/D4/D11/D12, uniform submit loop S2) each land in one area
of this file. Splitting first gives smaller diffs, clearer seams and cheaper reads (`agent.py`
was read 847 times for 5.8M chars).

**This is a pure move.** No behaviour, name or text change. Function bodies stay byte-identical,
and only import lines change. Everything in `agent/` is critical core
(`plan-review-blast-radius.md`), so the 90% diff-cover bar applies to every moved line.
Current branch coverage of `agent.py` is 96%.

## Decision / Design

### User decisions (2026-09-29)

- Citation verification stays in the agent package, as `agent/citations.py`, not in
  `verification/`.
- **No re-export shim.** Every caller and every mock target moves to the new module. With F401,
  a stale `sec_agent.agent.agent.X` patch fails loudly with AttributeError; it can't silently
  patch nothing.
- **One commit per extracted module**, bottom-up. Each commit is green on the full suite, the
  snapshot and `replay --compare`.

### Module layout (inside `src/sec_agent/agent/`)

The AST dependency analysis of the current file shows these groups form a DAG. The
`acyclic_siblings` import contract then enforces that it stays one.

| Module | Moves (current line ranges / names) | Depends on (in-package) |
|---|---|---|
| `tool_args.py` | 188–369: `_INT_TYPE_VALIDATOR`, `_is_valid_int`, `_rejects_invalid_fiscal_year`, `_YEAR_STRING`, `_coerce_year_args`, `_VALIDATOR_KIND_PRIORITY`, `_reason_for_error`, `validate_tool_args`, `_FISCAL_YEAR_PROPS`, `_COMPARE_FISCAL_YEAR_PROPS` | — |
| `tool_results.py` | 84–187 + `_format_citation_key`: `_citation_header`, `_format_results_block`, `_never_tagged_hint`, `_no_fact_period`, `_format_no_fact_message`, `_format_no_comparison_message`, `_format_citation_key` | — |
| `citations.py` | 853–1496: markers/patterns, quote matching, `_number_candidates`, `_iter_citation_claims`, `CitationWarning`, `_ClaimQuote`, `_NO_SUBMISSION_WARNING`, `value_is_citation_verified`, `_strip_citation_header`, `_verify_one_claim`/numeric/qualitative, `verify_claims` | tool_results |
| `fact_tools.py` | 370–624: `call_get_financial_fact` + multi-year/YoY helpers, `_with_unit`, `_format_fact_value`, `_fact_as_result`, `call_compare_financial_metric`, `_comparison_as_results` | tool_args |
| `calculate.py` | 625–852: `_ground_operand`, `call_calculate`, `_apply_calculate_operation`, `_format_computed_number`, `_calculation_as_result` | tool_args, citations, fact_tools (`_with_unit`) |
| `dispatch.py` | `CHUNKS_PER_SEARCH`, `_resolve_search_args` (62–83), 1683–1823: `_dispatch_tool_call`, `_dispatch_*`, `run_search` | tool_args, tool_results, fact_tools, calculate |
| `submission.py` | `_bulleted`, `_format_claim_retry_message`, `_format_refusal_message`, `_partition_submit_call`, `AgentResult`, `_count_citation_checks`, `submission_warnings`, `_finalize_answer` | tool_args, citations |
| `agent.py` (remains) | `MAX_TOOL_ITERATIONS`, `_should_retry_for_citations`, `_should_force_final_submit`, `run_agent`, loop state/context/step classes, turn handlers, `_run_agent_impl`, `main` | dispatch, submission, citations, tool_results |

- The two `_should_*` predicates stay in `agent.py`. `_should_force_final_submit` reads
  `MAX_TOOL_ITERATIONS`, which tests and the snapshot patch on `agent.agent`, so moving it would
  break those patches.
- Private (`_`) names keep their names even when imported across modules. That keeps this a
  pure move. Pyright basic and our ruff rules don't flag it. Add a BACKLOG item for a
  public-name pass after S2, once the seams have settled.
- `python -m sec_agent.agent.agent` and `from sec_agent.agent.agent import run_agent` keep
  working.
- Module docstring: each new module gets a docstring of 1–3 lines saying what it owns.
  `agent.py`'s docstring **stays unchanged**, because it is the CLI's `--help` text
  (`ArgumentParser(description=__doc__)`, `agent.py:2185`).

**How the boundaries fit the next packages:**
- **Retry slot (D9) and uniform submit loop (S2):** these touch `agent.py` (the loop state,
  `_should_*` and the turn handlers) and `submission.py` (`_format_claim_retry_message` and
  `_finalize_answer`'s retry inputs).
- **Gate rules (D3/D4/D11) and table grounding (D12):** these touch `citations.py` only, plus
  `verification/`.
- **Not-available answer (S3):** this touches `citations.py`, `submission.py` and `prompts/`.

Each package then reads one or two modules of about 200–650 lines, not the whole 2,209-line file.

## Files and steps

### Callers to update (no shim)

- `mcp_server.py:27`: `CHUNKS_PER_SEARCH` → dispatch; `call_*` → fact_tools;
  `validate_tool_args` → tool_args.
- `eval/eval_harness.py:39`: `value_is_citation_verified` → citations. `run_agent` stays.
- `devtools/analyze_gate_replay.py`: `_dispatch_tool_call`, `run_search`, `hybrid_search` and
  `CHUNKS_PER_SEARCH` → dispatch. `submission_warnings` and `_count_citation_checks` →
  submission. `_NO_SUBMISSION_WARNING` → citations. This covers `memoized`'s default argument
  at `:441`, `:451`/`:452`, and the comment at `:64` naming `agent._dispatch_*`.
  - **`install_live_search` must rebind `dispatch.hybrid_search`.** Rebinding it on the old
    module would silently skip the memoization, and the replay is our equivalence check.
- `tests/eval/test_eval_harness.py`: `AgentResult` → submission.
- `tests/devtools/test_analyze_gate_replay.py`: the `setattr(agent, "_dispatch_*")` calls at
  `:262` and `:284-285` → dispatch; the patch targets at `:309-311` → dispatch.
- `tests/prompts/test_model_input_snapshot.py`:
  - its direct uses of `_dispatch_search_filings`, `_format_*`, `verify_claims`,
    `CitationWarning` and `call_calculate`;
  - the `get_ratio` patch at `:236` → fact_tools;
  - the `is_metric_tagged` patch at `:447` → tool_results.
  - Its `_run` overrides only `MAX_TOOL_ITERATIONS`, and `BACKENDS` stays on `agent`, so those
    don't change.
- `tests/manual/verify_submit_answer.py`, `verify_crm_fiscal_year_lookup.py` and
  `verify_tracing.py`: imports. The other manual scripts import only `run_agent`.
- **Every string/attr patch target in `tests/agent/`.** Retarget each one to the module whose
  code *looks the name up*, not the module where it's defined. Examples: `get_metric` →
  `fact_tools`, `hybrid_search` → `dispatch`, `verify_claims` → `submission`.
- **`log_event` and `traced_span` need their own handling.** `agent.py` keeps using both, so a
  stale `agent.agent.log_event` patch still resolves and captures nothing. A negative assertion
  like `log_calls == []` would then pass without checking anything, as at `test_agent.py:3054`,
  `:1821` and `:1887`. Also, the event under test often comes from a different module than the
  function under test: `tool_call_rejected` and `tool_arg_coerced` come from tool_args, and
  `citation_gate_refused` from submission.
  - **Fix:** add one `captured_events` fixture in `tests/agent/conftest.py`. It patches
    `log_event` in every `sec_agent.agent.*` module that imports it, and returns the shared call
    list.
  - Every test that inspects logged events uses the fixture instead of an inline `log_event`
    patch.
  - Tests that patch `log_event` only to silence it may use the fixture as well.
  - The single `traced_span` patch is retargeted by hand to the module whose code it wraps.

### Tests split (moves alongside each module's commit)

`tests/agent/test_agent.py` splits by the existing `# ---` sections into `test_tool_args.py`
(validate_tool_args, the SUBMIT/CALCULATE schema sections, bool fiscal_year, and
tool_call_rejected logging if it targets validate_tool_args), `test_tool_results.py`,
`test_citations.py` (value_is_citation_verified, quote matching, number candidates,
verify_claims, qualitative claims, both table-grounding sections), `test_fact_tools.py`,
`test_calculate.py`, `test_dispatch.py` (`_resolve_search_args`, `_dispatch_tool_call`),
`test_submission.py` (both `_finalize_answer` sections, `_format_claim_retry_message`,
`_partition_submit_call`) and `test_agent.py` (`_should_*`, all `run_agent` sections).

- Each test goes where its function under test lives. A mixed section splits by test.
- A helper used by one file moves with it. A helper used by several (e.g. `_fake_result`,
  `_valid_submitted_claim`) goes to `tests/agent/helpers.py`, imported as
  `from tests.agent.helpers import …`. `pytest` `pythonpath` already includes `.`.
- New test basenames must be unique across `tests/`. Checked: none of the names above exist.

### Commit sequence

First, copy this plan to `docs/plans/2026-09-29-agent-py-split.md` and add its
`PROJECT_INDEX.md` line. That goes in step 8's commit.

Before step 1, record the baselines:
- `python -m sec_agent.devtools.analyze_gate_replay --out <scratch>/base.json`
- `pytest --collect-only -q`: the test-ID list, with the file part stripped, for the name
  comparison later.
- an AST dump of every top-level statement in `agent.py`.

Then one commit per module, leaves first:
1. tool_args
2. tool_results
3. citations
4. fact_tools
5. calculate
6. dispatch
7. submission
8. docs/tooling

Each code commit moves the code, its tests and the patch targets and imports that reference it.

**Step 8, docs/tooling:**
- `live-eval-verification.md` and `live-code-tdd.md` frontmatter: add the new module paths
  (citations, calculate, fact_tools, dispatch, submission and tool_results where their content
  applies), and point the prose to the new homes.
- `plan-review-blast-radius.md`: the entry for `agent.py` names `_dispatch_tool_call` →
  dispatch and `_partition_submit_call` → submission.
- Map: close the "`agent.py` module boundaries" ticket and strike prerequisite 4 (the split).
- BACKLOG: delete line 105 and add the private-name item.
- Plan copy at `docs/plans/2026-09-29-agent-py-split.md`, with its `PROJECT_INDEX.md` line.
- A review file (Substantial).

## Testing and verification

### After every code commit

1. `ruff check .`, `pyright .` and `lint-imports`: 0 errors. `acyclic_siblings` proves the DAG.
2. `pytest --cov=. --cov-report=xml -q`: still **1053 passed**, and the collected test *names*
   match the baseline (same set, new files).
3. `diff-cover coverage.xml --compare-branch=HEAD~1 --include 'src/sec_agent/**' --fail-under=90`.
   Moved lines count as new. Today's misses (dispatch bodies 1715/1737/1754/1805, `main`) could
   push `dispatch.py` near the bar. If they do, add a dispatch unit test. Don't add a pragma.
4. **AST equivalence.** A scratch script compares the multiset of `ast.dump`s of top-level
   statements across `agent/*.py` with the baseline dump from the original `agent.py`. It
   excludes imports and each module's leading docstring. `agent.py`'s docstring is compared
   separately and must be byte-identical. A match proves the bodies are unchanged and nothing
   was lost or duplicated.
5. **Patch-target check.** A scratch script finds every `sec_agent.agent.<mod>.<name>` string
   and every `setattr(<mod>, "<name>")` in tests and devtools. For each one, it asserts that
   `<mod>`'s AST references `<name>` outside its import line. That catches a patch that
   succeeds but reaches no code.
   - It must also assert that no inline `log_event` patch is left in `tests/agent/`, since the
     `captured_events` fixture replaces them all.
   - Then check each negative log assertion (`== []`) by hand: the fixture must cover every
     emitter on the call path.
6. `analyze_gate_replay --compare <scratch>/base.json` exits 0 (identical verdicts, offline).
7. The model-input snapshot test is part of step 2: the fingerprint is unchanged.

After step 7, run one live question:
`python -m sec_agent.agent.agent "How many full-time employees does Apple have?"`. This is a
smoke test, the same as the `src/` move. No eval panel: every model-visible string and every
function body is unchanged (checks 4 and 7), and the replay covers the gate across 1,211 runs.
The review file records that as the reason the live-eval spot-check is replaced.

### Review

`independent-review-pass` by the actual diff: `/code-review`, plus `arch-reviewer` on Opus
(critical core), plus `security-reviewer`, per the recent Substantial precedent. Remind the
reviewers of `git diff --color-moved=dimmed-zebra` so moved blocks are visually inert.

## Plan review

One round, `plan-reviewer` on Opus, with escalated scrutiny because this is critical core.
Verdict: sound. Every finding was folded in:

1. **Medium: stale `log_event` patches could pass while checking nothing.** `agent.py` keeps
   importing `log_event`, so F401 doesn't catch them. Negative assertions such as
   `test_agent.py:3054`, `:1821` and `:1887` would pass vacuously, and some events come from a
   module other than the one under test.
   - **Folded in:** the `captured_events` conftest fixture, plus the extension to check 5.
2. **Medium: the AST check would have failed on the new docstrings.** Also, trimming
   `agent.py`'s docstring would change the CLI's `--help` text.
   - **Folded in:** check 4 excludes the docstrings, and `agent.py`'s docstring is kept
     unchanged.
3. **Low: the dependency table missed an edge**, calculate → fact_tools (`_with_unit`). The
   commit order was already compatible.
   - **Folded in:** the table is fixed.
4. **Low: some callers and patch targets were not listed.** These are the replay test's
   `:262`/`:284-285`, the snapshot's `get_ratio` and `is_metric_tagged` patches, the replay
   tool's `:441`/`:452` and its comment at `:64`.
   - **Folded in:** the callers list is updated.
5. **Low: the plan didn't show how the boundaries map to S2 and the gate packages.**
   - **Folded in:** added "How the boundaries fit the next packages".
6. **Low: the prerequisite numbering was inconsistent.**
   - **Folded in:** the title now reads "Decision 13, item 4".

The reviewer confirmed:
- `MAX_TOOL_ITERATIONS` placement;
- the `hybrid_search` rebinding;
- no module-level mutable state;
- that `acyclic_siblings` recurses into `sec_agent.agent`;
- that the helpers import works;
- no basename or test-name clashes;
- the line ranges.

## Review log

### Round 1 (reviewed state: `1d32829..1445d0b` plus the uncommitted step-8 docs, snapshot `7dac8ab`)

Passes: `/code-review high`, `arch-reviewer` (opus), `security-reviewer`, `/simplify`. The first
`/code-review` attempt hit the session limit, so it ran again after the arch fixes and reviewed
those fixes too.

- **security-reviewer: no findings.** It compared the bodies by AST and found all 65 functions
  and 25 classes/constants identical. The validation order, the citation gate, mcp_server's
  validation path and the replay tool's `hybrid_search` rebinding are all unchanged.
- **arch, risk: the bare-number `_quote_matches`/`verify_claims` tests were in
  `test_submission.py`.** `[Fixed]` moved to `test_citations.py`.
- **arch, risk: the plan copy didn't follow `docs/plans/TEMPLATE.md` and had no Review log.**
  `[Fixed]` headings restructured to the template, Implementation notes renamed to Addendum.
- **arch, q: the review file and its index line weren't there yet.** `[Verified, no fix needed]`
  both land in the step-8 docs commit.
- **arch, q: add `fact_tools.py` to `live-code-tdd.md`?** `[Verified, no fix needed]` the rule
  names `xbrl_facts.py` itself as the live code. Before the split it didn't name the fact tools'
  path through `agent.py` either; only the `search_filings` path was named, and that path now
  names `dispatch.py`.
- **arch, q: `test_tool_args.py` held a `call_get_financial_fact` test and a
  `_dispatch_tool_call` null-handling test.** `[Fixed]` moved to `test_fact_tools.py` and
  `test_dispatch.py`, following the plan's split-by-test rule.
- **arch, nits: stale "below"/"this file"/`agent.X` references in moved docstrings and in
  comments across `src/` and `tests/`.** These cover `agent.py`, `calculate.py`, `dispatch.py`,
  `submission.py`, `tool_args.py`, `tool_results.py`, `citations.py`, `fact_tools.py`,
  `prompts/`, `verification/`, `eval_harness.py`, `mcp_server.py`, `llm_backends.py`,
  `analyze_citation_gate.py`, `tracing.py`, `formulas.py`, `xbrl_facts.py`, test_agent,
  test_tool_args and the manual CRM script. `[Fixed]` one comment-only sweep.
  - The `(line ~2351)` pointer in test_agent already pointed at nothing before the split, so it
    was dropped.
  - `xbrl_facts.py`'s "sibling case" is `tool_results._no_fact_period`.
- **arch, nit: `tool_results.py`'s docstring called the CLI citation key model-facing.**
  `[Fixed]` in the docstring.
- **arch, nits: `BACKLOG.md` still named `agent._with_unit` and "`agent.py`/`table_grounding.py`".**
  `[Fixed]`.
- **arch, nit: `capture_events` misses a `tracing.log_event(...)` caller.** `[Disputed]` no such
  caller exists (code-review flagged the added patch as speculative), so the patch was reverted.
  The helper's docstring states the binding it covers.
- **arch and code-review: `_NO_SUBMISSION_WARNING` belongs in `submission.py`, `_with_unit` in
  `tool_results.py`.** `[Deferred → BACKLOG]` added to the public-names item. Both are pure moves
  that fit that pass.
- **code-review: underscore-private names are now cross-module API.** `[Deferred → BACKLOG]` this
  was the user's decision, and the public-names item tracks it.
- **code-review: the grounding tolerance is hand-copied across `citations.py`, `calculate.py`
  and `table_grounding.py`.** `[Deferred → BACKLOG]` it predates the split and was already
  tracked (the `_matches_any` item, now naming the new files).
- **code-review: the withheld-answer span test patches only `agent.traced_span`.**
  `[Verified, no fix needed]` that path runs no tool call, so no `dispatch.py` span opens. The
  test asserts exactly one span, and both spans that can see the answer (`run_agent`,
  `submit_answer`) are in `agent.py`.
- **code-review: the sweep missed stale references** at `tracing.py:207/234`,
  `llm_backends.py:38`, `table_grounding.py:258/277` and `mcp_server.py:3`. `[Fixed]`.
- **code-review: `_count_citation_checks`'s docstring claims `run_agent`'s span shares it.**
  `[Fixed]` it now names its real callers (`_finalize_answer` and the replay tool). The claim
  was already wrong before the split; `run_agent` counts over the dict details itself.
- **code-review: edited comments still pointed to decision/plan docs** (`citations.py`,
  `numeric_utils.py`, `tool_args.py`, `xbrl_facts.py`; `table_grounding.py` in round 2). `[Fixed]` pointers removed from those
  edited blocks.
- **code-review: an edited test comment retold an incident** (`test_verify_claims_accepts_a_long_
  bare_xbrl_number_quote_end_to_end`). `[Fixed]` it now states the invariant.
- **code-review: the snapshot test's renderers kept an unused `agent` parameter.** `[Fixed]`
  parameter and pass-through import removed.

- **/simplify (reuse, simplification, efficiency, altitude): no edits.**
  - Reuse: the inline `# noqa: PLR0913` on `_fake_result` could move to `pyproject.toml`'s
    `tests/*` per-file-ignores. `[Verified, no fix needed]` the suppression moved verbatim, with
    its reason, from `test_agent.py`. Changing the lint policy for every test is outside this
    change.
  - Efficiency: `capture_events` rescans the package on every call. `[Verified, no fix needed]`
    that costs one directory listing plus cached `sys.modules` hits, a few milliseconds per run.
  - Altitude: calling `tracing.log_event` through the module would let one patch replace
    `capture_events`. `[Verified, no fix needed]` it's a production import-style change in four
    modules, outside a pure move. The reviewer judged the helper the right size for now.

After the fixes: ruff 0, pyright 0, lint-imports 2 kept, and pytest 1053 passed with the
snapshot unchanged and the test-name set identical to the baseline.

### Round 2 (delta: `git diff 7dac8ab`, the round-1 fixes)

Passes: `arch-reviewer` (opus), `/code-review low`. `security-reviewer` wasn't re-run because
the delta changes no non-test executable code.

- **`/code-review low`: no findings.**
- **arch: 7 nits, all comment-only.** `[Fixed]` These count as nit fixes, so the round doesn't
  reopen.
  - `analyze_citation_gate.py:2` placed `_finalize_answer` in citations; it is in submission.
  - The sweep missed `llm_backends.py:56`, `agent_messages.py:9` and `companies.py:25/73`.
  - `numeric_utils.py`'s module docstring now names the real import chain (citations via
    submission).
  - `table_grounding.py`'s edited docstring still had doc pointers; removed.
  - `test_quote_matches_accepts_a_long_bare_xbrl_number_quote` retold an incident; it now
    states the invariant.

Review closed after round 2: nothing executable changed and no new finding remains open.

## Addendum (2026-09-29, during execution)

Commits: `198b77b` tool_args, `30d5a67` tool_results, `260cf56` citations, `500f7e6` fact_tools,
`d56eae8` calculate, `d5ac152` dispatch, `1445d0b` submission. `agent.py` 2,209 → 454 lines;
`test_agent.py` 4,199 → 695 lines, split into eight test modules plus `tests/agent/helpers.py`.

Deviations from the plan:
- **`capture_events(monkeypatch, sink)` helper instead of a `captured_events` fixture.** Every
  `log_event` patch had the same one-line shape, so a helper function replaced each line in place
  with no test-signature changes. The effect is the same: it patches `log_event` in every
  `sec_agent.agent` module. Check 5 confirmed that no inline `log_event` patch is left.
- **The replay comparison ran once, on the final commit, not after each commit.** A full replay
  takes about 30 minutes. Check 4 (AST equivalence) passed after every commit. The plan was to
  bisect per commit only if the final comparison showed a difference.
- **Commits 2–5 carried 4 pyright errors in `tests/prompts/test_model_input_snapshot.py`.**
  Pyright inferred the render helpers' dicts as `dict[str, str]` once they called the typed moved
  functions instead of going through the untyped `agent` parameter. The verify script's
  `tail -1` hid the pyright line. Commit 6 fixed them, commit 7 fixed a fifth one of the same
  kind, and the message of commit 6 records this. Tests passed at every commit.
- **The top-level statement mover missed one trailing comment.** The comment describing
  `_ClaimQuote` sits below that statement, not above it, so it was reattached by hand in the
  citations commit.
- **The string-year dispatcher test briefly landed in `test_calculate.py`.** It sat between the
  calculate sections. The dispatch commit moved it to `test_dispatch.py`.

Results after commit 7:
- **Replay comparison:** `analyze_gate_replay --compare base.json` replayed 1212 runs, 0 errored.
  Refused 278 then and 278 now. Recovered 0, newly refused 0, check changes 0, tool-result
  drift 0, verdict changes on drifted runs 0. It exited 0. The 114 drifted runs are source
  drift since the traced runs, not a code effect.
- **Live smoke question:** `python -m sec_agent.agent.agent "How many full-time employees does
  Apple have?"` answered "approximately 166,000 full-time equivalent employees [1]", cited to
  the AAPL 10-K (accession 0000320193-25-000079). It used one question's worth of Gemini calls.
