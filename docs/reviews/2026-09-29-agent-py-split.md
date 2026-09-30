# Review: `agent.py` split into focused `agent/` modules

Plan: `docs/plans/2026-09-29-agent-py-split.md`. Seven pure-move commits (`198b77b`..`1445d0b`)
split `src/sec_agent/agent/agent.py` (2,209 lines) into `tool_args`, `tool_results`, `citations`,
`fact_tools`, `calculate`, `dispatch` and `submission`, with `agent.py` keeping the loop (454
lines). The tests split to match. The suite had 1053 tests before and after. Substantial passes:
the whole diff is critical core.

## Round 1

Reviewed state: `1d32829..1445d0b` plus the uncommitted step-8 docs (snapshot `7dac8ab`).

Passes: `/code-review` high, `arch-reviewer` (opus), `security-reviewer`, `/simplify` (four
angles). The first `/code-review` run hit the session limit, so it ran again after the arch
fixes and reviewed them too.

1. **None** (security): no findings. The reviewer compared the pre-split and post-split bodies
   by AST: 65/65 functions and 25/25 classes/constants are identical. It checked:
   - the `_coerce_year_args` → `validate_tool_args` order in both fact tools;
   - that `mcp_server.py`'s fact tools still validate inside `call_*`;
   - the citation gate path (`_partition_submit_call`, `submission_warnings`, `_finalize_answer`);
   - the replay tool's `dispatch.hybrid_search` memoization. It rebinds the one namespace
     `run_search` reads from, exactly as before the split.
2. **Risk** (arch): the bare-number `_quote_matches`/`verify_claims` regression tests were in
   `test_submission.py`. `[Fixed]` Moved to `test_citations.py`, where the next gate work will
   look for them.
3. **Risk** (arch): the plan copy didn't follow `docs/plans/TEMPLATE.md` and had no Review log.
   `[Fixed]` Restructured under the template headings.
4. **Q** (arch): the review file and its index line were missing. `[Verified, no fix needed]`
   Both land in the docs commit.
5. **Q** (arch): should `fact_tools.py` join `live-code-tdd.md`? `[Verified, no fix needed]` The
   rule names `xbrl_facts.py` as the live code. Before the split it named only the
   `search_filings` path through `agent.py`, and that path is now `dispatch.py`.
6. **Q** (arch): `test_tool_args.py` held a fact-tool test and a dispatch null-handling test.
   `[Fixed]` Moved to `test_fact_tools.py`/`test_dispatch.py` by the plan's split-by-test rule.
7. **Nits** (arch, code-review): stale "below", "this file" and `agent.X` references in moved
   docstrings. The same stale references were in comments across `src/` (`prompts/`,
   `verification/`, `tracing.py`, `llm_backends.py`, `mcp_server.py`, `eval_harness.py`,
   `analyze_citation_gate.py`, `formulas.py`, `xbrl_facts.py`) and `tests/`.
   - `[Fixed]` One comment-only sweep. The first sweep missed six sites, which code-review then
     found and which were fixed.
   - The snapshot is unchanged: every `prompts/` edit is a `#` comment.
8. **Nit** (arch): `tool_results.py`'s docstring called the CLI's citation key model-facing text.
   `[Fixed]`
9. **Nit** (arch): `BACKLOG.md` still named `agent._with_unit` and `agent.py`. `[Fixed]`
10. **Nit** (arch): `capture_events` would miss a caller using `tracing.log_event(...)`.
    `[Disputed]` No such caller exists. The added patch was reverted when code-review flagged it
    as speculative.
11. **Low** (arch, code-review): `_NO_SUBMISSION_WARNING` belongs in `submission.py` (then
    `agent.py` stops importing `citations`), and `_with_unit` belongs in `tool_results.py`
    (which drops the calculate → fact_tools edge). `[Deferred → BACKLOG]` Both are added to the
    public-names item. They're pure moves that fit that pass.
12. **Low** (code-review): underscore-private helpers are now the cross-module API, including
    from `devtools/`. `[Deferred → BACKLOG]` This was the user's decision, to keep the split a
    pure move. The public-names item renames them after the S2 loop refactor.
13. **Low** (code-review): the tolerance `max(0.01*abs(norm), 0.05)` is hand-copied across
    `citations.py`, `calculate.py` and `table_grounding.py`. `[Deferred → BACKLOG]` It predates
    the split and was already tracked as the `_matches_any` item, which now names the new files.
14. **Medium** (code-review): the withheld-answer span test patches only `agent.traced_span`,
    while tool spans now live in `dispatch.py`. `[Verified, no fix needed]` That test runs no
    tool call and asserts exactly one span. Both spans that can see the answer (`run_agent`,
    `submit_answer`) are opened in `agent.py`, which is patched.
15. **Low** (code-review): `_count_citation_checks`'s docstring claimed `run_agent`'s span output
    shares it. `[Fixed]` It now names its real callers. The claim was already wrong before the
    split.
16. **Low** (code-review): edited comments kept pointers to decision/plan docs, and one edited
    test comment retold an incident. `[Fixed]` The pointers were removed and the comment now
    states the invariant.
17. **Low** (code-review): the snapshot test's renderers kept an unused `agent` parameter.
    `[Fixed]` Removed.
18. **Nits** (`/simplify`): no edits.
    - The inline `noqa: PLR0913` moved verbatim with its reason. A repo-wide per-file-ignore
      would be a lint-policy change.
    - `capture_events` rescans the package on every call, at a cost of milliseconds.
    - Calling `tracing.log_event` through the module would replace the helper, but that's a
      production import-style change outside a pure move.

## Round 2

Delta: `git diff 7dac8ab` (the round-1 fixes). Passes: `arch-reviewer` (opus), `/code-review`
low. `security-reviewer` wasn't re-run: the delta changes no non-test executable code, only
comments and docstrings.

- `/code-review` low: no findings.
- **Nits** (arch, 7, all comment-only). `[Fixed]` As nit fixes, they don't reopen the round.
  - `analyze_citation_gate.py:2` placed `_finalize_answer` in citations; it is in submission.
  - Four stale references were left: `llm_backends.py:56`, `agent_messages.py:9`,
    `companies.py:25/73`.
  - `numeric_utils.py`'s docstring now names the real import chain (citations via submission).
  - Doc pointers were removed from `table_grounding.py`'s edited docstring.
  - One more moved test comment now states its invariant instead of retelling the incident.

## Live verification

The plan's live-eval spot-check (`live-eval-verification.md` covers `agent/**`) was replaced by
one live question plus the offline replay:
- every function body is AST-identical to the pre-split code;
- the model-input snapshot, and so the prompts fingerprint, is unchanged;
- the replay re-runs the citation gate over every traced run.

Results:
- **Replay:** `python -m sec_agent.devtools.analyze_gate_replay --compare` against the pre-split
  baseline replayed 1212 runs, 0 errored. Refused 278 then and 278 now. Recovered 0, newly
  refused 0, check changes 0, tool-result drift 0, verdict changes on drifted runs 0. Exit 0.
- **Live question:** `python -m sec_agent.agent.agent "How many full-time employees does Apple
  have?"` answered "approximately 166,000 full-time equivalent employees [1]", cited to the AAPL
  10-K (accession 0000320193-25-000079). That cost one question's worth of Gemini calls.

## Outcome

The seven move commits shipped, plus a follow-up commit carrying the review fixes and docs.
The review closed clean after round 2.
- Suite: 1053 passed.
- Checks: ruff 0, pyright 0, lint-imports 2 kept.
- Snapshot: unchanged.
- Test names: the same set as before the split.
- Open in `BACKLOG.md`:
  - **[refactor, Low, Standard]** public names, plus the `_NO_SUBMISSION_WARNING` and
    `_with_unit` placements;
  - **[refactor, Low, Trivial]** the shared tolerance helper.
