# WP1: move model-facing text into a `prompts/` package (roadmap Step 1, commits 1a–1c)

## Context

WP1 of `docs/plans/2026-09-24-prompt-audit-roadmap.md`. The full design is in that
roadmap's **Step 1**, sections "Package layout", "Commit 1a", "Commit 1b" and
"Commit 1c". This plan follows those sections and does not restate them. It records
only the changes made since, and WP1's own scope. The roadmap is not edited; this file
and the WP1 decision file record the changes.

**Goal:** every static piece of text the agent model, the judge or an MCP client reads
moves into `prompts/{agent_system,agent_tools,agent_messages,judge,mcp}.py`. The move
must be *provably byte-identical*: identical sha256 of the prompt and schemas, and
identical golden rendered output. It spends zero eval quota. Substantial tier,
refactor.

**Repo state (2026-09-24, HEAD `38af001`):** the roadmap was written against
`98b65f5`, and the only commit since touched docs. So every
`agent.py`/`eval_harness.py`/`mcp_server.py` line anchor in the roadmap still holds.
Spot-checked:
- the noqa block at `agent.py:15-25`;
- `COMPANIES` at `:96`;
- the inline tool list at `:2831-2833`;
- `JUDGE_SYSTEM_PROMPT` at `eval_harness.py:120`, and the user prompt at `:148-154`;
- the MCP strings at `:142/:152/:186`.

## Prior art

Covered by the roadmap's "Prior art" and "Why a `prompts/` package" sections: plain
Python constants, one module per surface.

## Decision / Design

The roadmap's Step 1 design, with these changes found while re-checking it:

1. **The coverage bar is not derived from the rule file's `paths:`.**
   `githooks/pre-push` hardcodes its own critical-core `--include` list, even though
   the "Coverage bar" section of `plan-review-blast-radius.md` says "no second list to
   keep in sync".
   - Adding `prompts/**` to the rule file alone would therefore *not* give `prompts/`
     the 90% bar.
   - **Fix (1a):** add `'prompts/*.py'` to the hook's `--include`. It is quoted, so
     diff-cover does the matching.
   - Correct that sentence in the rule file.
2. **The roadmap contradicts itself on the MCP HTTP bodies.** `mcp_server.py:272`
   ("rate limit exceeded") and `:284` ("unauthorized") are listed both under "Stays
   out" and in commit 1c.
   - **Resolution:** they stay out. They are transport-level `JSONResponse` bodies,
     not tool results.
   - 1c moves only `:142`, `:152` and `:186`.
3. **The trace-log guard needs its own copy.** The fixture that disables the trace log
   is in `tests/conftest.py`, not `conftest.py:23`. A scratchpad golden test file
   outside `tests/` would not load it.
   - The golden file declares its own autouse fixture, which also turns off Langfuse.
   - Check that `trace_logs/traces.jsonl`'s byte size is unchanged after each golden
     run.
4. **WP1 gets its own review.** The roadmap puts one `independent-review-pass` over
   1a–1d. WP1 gets its own over 1a–1c, because WP2 is a separate session.
5. **The golden check captures at the backend boundary.** Comparing constants to the
   old literals by value proves the text is unchanged. It does not prove that the loop
   still *sends* the right constant, or that it formats a template instead of sending
   `{n}` raw.
   - **The capture:** the golden file monkeypatches `agent.BACKENDS` with fake
     `start`/`send_tool_results`/`send_followup`. These record everything the model
     would receive: system prompt, tool schemas, tool results and follow-ups.
   - **Scripted scenarios** run through `_run_agent_impl` and reach each loop literal:
     - the retry messages;
     - the mixed tool-and-submit turn;
     - no-tool-calls;
     - the final turn;
     - budget exhaustion;
     - a bad calculate call.
   - **Per-function calls** (roadmap "Commit 1b → What it calls") still cover the
     formatter branches that are hard to script.
   - **MCP `:186`** is rendered through `_handle_call_tool`.
6. **The formatter functions stay in `agent.py`; only their text moves.**
   `tests/test_agent.py:2160` and `:2219` monkeypatch `"agent._format_no_fact_message"`
   and `"agent._format_no_comparison_message"`. `_never_tagged_hint` needs
   `is_metric_tagged` and `COMPANIES`.
   - The templates keep the `!r` conversions, so the "None FYNone" bug is preserved
     byte-for-byte.
   - A golden case with the keys missing proves it.
7. **The judge-location wording is fixed in 1c, not 1d.** The text saying
   "`JUDGE_SYSTEM_PROMPT` lives in `eval_harness.py`" (in `live-eval-verification.md`
   and at `plan-review-blast-radius.md:52`) becomes false in 1c, so 1c corrects it.
   The stale "41-question" fix stays in WP2.
8. **The live-eval exemption is recorded.** `live-eval-verification.md` asks for a
   live spot-check whenever the judge prompt or `verify_claims` changes. WP1 spends no
   quota on purpose, and its decision file records the exemption: for a pure move, the
   byte-identical proof at the backend boundary is stronger evidence than one noisy
   live question.

## Scope / Out of scope

- **Commit 1d is out of WP1.** It adds the fingerprint functions, provenance, the
  compare script and the judge flag, and it belongs to WP2.
- **`prompts/__init__.py`** is therefore created empty apart from its docstring.
- **`FINGERPRINTED`/`NOT_FINGERPRINTED`** also arrive in 1d, together with the `ast`
  test that enforces them. Adding them now, with nothing enforcing them, would be
  untested dead data.

## Files and steps

0. **Save this plan and the plan review**
   (`docs/reviews/2026-09-24-wp1-prompts-package-plan-review.md`). Leave both
   unstaged until step 7: the pre-commit docs-health check blocks a staged `docs/`
   file that has no `PROJECT_INDEX.md` entry.
1. **Record the baselines before any edit** (scratchpad, not the repo):
   - **`hash_check.py`:**
     - sha256 of `SYSTEM_PROMPT`;
     - sha256 of `json.dumps([FACT, COMPARE, SEARCH, CALCULATE, SUBMIT], ensure_ascii=False)`,
       with no `sort_keys`;
     - sha256 of `repr()` of the schema objects, which catches a list/tuple change
       that JSON can't see.

     It takes an old→new import-name mapping.
   - **`test_golden.py`:** the backend-boundary capture (change 5), the per-function
     calls, the judge (`eval_harness.complete` monkeypatched, date frozen), and MCP
     `:142/:152/:186`. It writes `golden_before.json`, keyed by scenario.
     - **How it runs:** from the repo root, with
       `python -m pytest <scratch>/test_golden.py -p no:cacheprovider`.
     - **Isolation:** its own autouse fixture sets `tracing.TRACE_LOG_PATH = ""` and
       `tracing.TRACING_ENABLED = False`, and monkeypatches `agent.is_metric_tagged`.
     - **Self-check:** assert the entry count and that no entry is empty. Once, change
       one character in a template, confirm the comparison fails, then revert.
     - **Fallback:** if the scratchpad is lost mid-WP, regenerate the "before" files
       from a `git worktree` at `38af001`.
   - **Baseline counts:** the `pytest -q` pass count, and the `ruff check .`/`pyright .`
     output.
2. **Commit 1a:** `SYSTEM_PROMPT`, the 4 ratio lists, the 5 schemas, `CLAIM_UNITS` and
   `AGENT_TOOL_SCHEMAS` move to `prompts/agent_system.py` and `prompts/agent_tools.py`.
   - **`COMPANIES`** (ticker → name) moves to `companies.py` as a module constant.
     `load_companies`' docstring says `COMPANIES` is the import-time snapshot.
   - **The `# ruff: noqa: E501` block** moves out of `agent.py`.
   - **Imports** change in `agent.py`, `mcp_server.py`, `tests/test_agent.py` and
     `tests/manual/verify_submit_answer.py`.
   - **New test, written first:** a capturing `fake_start` asserts
     `system_prompt is SYSTEM_PROMPT` and `tool_schemas == list(AGENT_TOOL_SCHEMAS)`.
   - **Rule files:** add `prompts/**` to the `paths:` of
     `.claude/rules/live-eval-verification.md` and `plan-review-blast-radius.md`.
     Also add the `pre-push` `--include` entry.
   - **Checks:** identical hashes, then ruff, pyright and pytest clean. Commit.
3. **Commit 1b:** the `agent_messages.py` inventory from the roadmap moves.
   - **Conventions to follow:**
     - templates;
     - `.format` safety;
     - one constant per conditional part;
     - the `=`-split warning for `verify_claims`;
     - the do-not-change comments on `CITATION_RETRY_GUIDANCE`/`FINAL_TURN_SUBMIT_MESSAGE`.
   - **Kept as it is:** the "None FYNone" bug. The formatter functions stay in
     `agent.py`.
   - **Tests:** update the test imports, and rename the private names in test bodies
     too.
   - **Checks:** the golden output is identical, and the suite is clean. Commit.
4. **Commit 1c:** `JUDGE_SYSTEM_PROMPT` and a new `JUDGE_USER_TEMPLATE` go to
   `prompts/judge.py`, and the 3 MCP strings go to `prompts/mcp.py`.
   - Correct the judge-location wording in both rule files.
   - **Checks:** the golden output is identical, and the suite is clean. Commit.
5. **Leftover grep:**
   - Grep `agent.py`, `eval_harness.py` and `mcp_server.py` for model-facing literals
     left behind.
   - Grep `tests/`, `tests/manual/` and `scripts/` for moved names still reached
     through `agent`/`eval_harness`.
6. **Stop:** give the `/compact` line, then run `independent-review-pass` over 1a–1c.
7. **Docs:**
   - write the decision file `docs/decisions/2026-09-24-wp1-prompts-package.md`;
   - delete the WP1 line from `BACKLOG.md`;
   - add the `PROJECT_INDEX.md` Recent lines.

The user's plan approval authorises commits 1a, 1b and 1c as their checks pass. The
docs go in with the step-7 commit. Nothing is pushed.

## Testing and verification

- **Identical output, no quota:** the hash and golden checks are identical for each
  commit.
- **Each commit is clean:** `ruff check .`, `pyright .` and
  `pytest --cov=. --cov-report=term-missing -q` all pass, with the baseline test count
  plus the new test.
- **No import cycle:** `python -c "import prompts.agent_system, prompts.agent_tools, prompts.agent_messages, prompts.judge, prompts.mcp, agent, mcp_server, eval_harness"`
  succeeds.
- **The coverage glob works:** a local `diff-cover --include ... 'prompts/*.py'` run
  against `origin/master` matches the new files.
