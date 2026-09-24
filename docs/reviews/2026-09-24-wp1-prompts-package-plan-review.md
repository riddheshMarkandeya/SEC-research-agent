# Review: WP1 plan, prompts package move (one independent plan-review round)

Plan: `docs/plans/2026-09-24-wp1-prompts-package.md`. The plan moves all model-facing
text into `prompts/` with byte-identical model input (roadmap Step 1, commits 1a–1c).
This review covers the plan only, before implementation. It was one round by a fresh
subagent, with escalated scrutiny because `agent.py` and `eval_harness.py` are
high-blast-radius files.

## Pass 1: self re-check of the roadmap against HEAD `38af001`

- [Fixed in plan] **The coverage bar has a second list.** `githooks/pre-push:43`
  hardcodes its own critical-core `--include` list, independent of the `paths:` in
  `plan-review-blast-radius.md`. That file's "Coverage bar" section says there is no
  second list.
  - Consequence: adding `prompts/**` to the rule file alone would not give `prompts/`
    the 90% bar.
  - Fix: add the entry to the hook as well, and correct the sentence.
- [Fixed in plan] **Contradiction on the MCP HTTP bodies.** The roadmap lists them
  both under "Stays out" and in commit 1c.
  - Resolved: they stay out. They are transport bodies, not tool results.
- [Fixed in plan] **The trace-log fixture's location.** It is in `tests/conftest.py`,
  so a golden file kept in the scratchpad doesn't get it.

## Pass 2: independent subagent

No blockers. Pass 1's corrections were confirmed:
- **diff-cover 10.6** matches `--include` with `glob.glob` from the current
  directory, against git-diff paths, so the quoted `'prompts/*.py'` is right.
- **Import graph:** `prompts/` imports `formulas`, which imports `xbrl_facts`, which
  imports `tracing`/`config`/`requests`; `companies` imports only `jsonschema`. There
  is no cycle, and `retrieval` imports its heavy dependencies lazily.

**Should-fix findings** (all folded into the plan):
1. **The proof covered the text, not the call sites.** Comparing loop literals by
   value doesn't prove that `_run_agent_impl` still sends them or formats them.
   - The capture moved to the backend boundary: fake `BACKENDS`, with scenarios
     scripted through the loop.
   - MCP `:186` (an f-string with `!r`) is rendered through `_handle_call_tool`.
2. **Nothing showed the golden check can fail.** Fix: assert the entry count and that
   no entry is empty, plus a one-time deliberate one-character edit that must make the
   comparison fail.
3. **The scratchpad pytest had more side effects.**
   - pyproject's `pythonpath` is lost, because the rootdir becomes the scratchpad.
   - Langfuse traffic goes out when keys are set.
   - Fix: run with `python -m pytest` from the repo root, and set
     `TRACING_ENABLED = False`.
4. **Where the formatters live.** The formatter functions must stay in `agent.py`,
   because tests monkeypatch `agent._format_no_fact_message`/`_format_no_comparison_message`.
   Only the text moves, keeping `!r`, with a golden case for missing keys.
5. **Stale names fail silently.** `from agent import X` keeps working, because `agent`
   re-imports the moved names. The private names are also used in test bodies. Fix:
   grep `tests/` and `tests/manual/` and rename them.
6. **Rule compliance, two gaps.**
   - The judge-location wording becomes false at 1c, so fix it in 1c.
   - Record the live-eval exemption in the decision file.
7. **The baseline could be lost.** It lives only in the scratchpad. Fix: a fallback
   that regenerates it from a `git worktree` at `38af001`.

**Nits** (all folded in):
- **List vs tuple:** the JSON hash can't tell a list from a tuple, so also hash
  `repr()`.
- **`companies.py`:** update its docstring for the import-time `COMPANIES` snapshot.
- **Pre-commit docs-health hook:** keep the plan and review files unstaged until the
  docs commit.

**Simpler alternative:** the single backend-boundary capture makes the separate
literals file unnecessary. Adopted.

## Outcome

The plan was approved with every finding folded in. No findings were deferred to
`BACKLOG.md`.
