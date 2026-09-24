# Model-facing text moved into a `prompts/` package (WP1)

**Date:** 2026-09-24

## Context

WP1 of `docs/plans/2026-09-24-prompt-audit-roadmap.md` (Step 1, commits 1a–1c). The
prompt audit found wording problems spread across `agent.py`, `eval_harness.py` and
`mcp_server.py`. Before any wording changes, every static string a model reads needs
one home, so that WP2 can fingerprint it and later work packages can change it one
commit at a time. WP1 is a pure move: no byte any model receives may change.

## Decision

All static model-facing text now lives in `prompts/`:
- `agent_system.py`: the system prompt, the ratio lists and `FACT_METRICS`;
- `agent_tools.py`: the 5 tool schemas, `CLAIM_UNITS` and `AGENT_TOOL_SCHEMAS`;
- `agent_messages.py`: tool-result, no-data, warning, retry, final-turn and refusal text;
- `judge.py`: the judge's system prompt and `JUDGE_USER_TEMPLATE`;
- `mcp.py`: the MCP tool error strings.

Call sites fill named templates with `.format(...)`, passing any outside content only
as keyword arguments. `prompts/__init__.py` holds only a docstring. The fingerprint
tuples and functions arrive in WP2 together with the test that enforces them.

Commits: `bbf41d7` (1a), `ccdb9c8` (1b), `e66ecce` (1c), `a71fd2d` (leftover-grep
find), plus the review-fix commit.

## Why

Changes from the roadmap, all found while re-checking it against HEAD:
1. **The coverage bar keeps a second list.** `githooks/pre-push` hardcodes its own
   critical-core `--include` list. `prompts/**/*.py` was added there, and the rule
   file's claim that no second list exists was corrected. The glob is `**` so it
   matches the rule file's `prompts/**`. diff-cover resolves includes with
   `glob.glob(..., recursive=True)`, and that matched all 5 files.
2. **The MCP HTTP bodies stay out.** "rate limit exceeded" and "unauthorized" are
   transport responses, not tool results. The roadmap listed them in two places.
3. **The golden test sets its own trace guard**, because `tests/conftest.py` doesn't
   apply to a scratchpad test file.
4. **WP1 gets its own review**, rather than sharing one with WP2's commit 1d.
5. **The golden capture is taken at the backend boundary**, not by comparing
   literals. Comparing values proves the text is unchanged, but not that the loop
   still sends the right constant, formatted.
6. **The formatter functions stay in `agent.py`**, because tests monkeypatch them.
   Only their text moved. The "None FYNone" output is kept byte for byte and is left
   for its own work package.
7. **The rule files' judge-location wording was fixed in 1c**, the commit that made
   the old wording false.
8. **Live-eval exemption.** `.claude/rules/live-eval-verification.md` asks for a live
   spot-check after a change to the judge prompt, `verify_claims` or (as of this
   change) any `prompts/` text. WP1 spent no quota on purpose. For a pure move, a
   byte-identical capture of everything the model receives is stronger evidence than
   one noisy live question. The exemption covers only a provably byte-identical
   move; any wording change in later work packages still needs the live check.

Kept as settled, although reviewers raised them again:
- **`COMPANIES` in `companies.py`:** three reviewers noted that every importer now
  reads `companies.json` at import. The roadmap placed it there because both the
  agent's logic and the prompt text read it. Every module affected already calls
  `load_companies()` on first use, so a malformed file failed those modules anyway.
- **`CLAIM_UNITS` and the ratio lists in `prompts/`:** they are derived data that
  logic also uses. The roadmap's layout stands. WP2's fingerprint design is the place
  to revisit it if the `agent_tools` → `agent_system` import makes per-surface
  fingerprints awkward.
- **Separator and bullet constants** (`RESULT_BLOCK_SEPARATOR`,
  `NO_DATA_HINT_SEPARATOR`, `WARNING_BULLET_TEMPLATE`): these are bytes the model
  reads, so they stay in `prompts/` for WP2's fingerprint to cover.

## Files touched

- **New:** `prompts/__init__.py`, `agent_system.py`, `agent_tools.py`,
  `agent_messages.py`, `judge.py`, `mcp.py`.
- **Edited:** `agent.py`, `companies.py`, `eval_harness.py`, `mcp_server.py`,
  `llm_backends.py` (docstring only) and `githooks/pre-push`.
- **Rules:** `.claude/rules/live-eval-verification.md`,
  `.claude/rules/plan-review-blast-radius.md`.
- **Tests:** `tests/test_agent.py`, `tests/manual/verify_submit_answer.py`.

## Verification

- **Hashes:** the sha256 of `SYSTEM_PROMPT`, and of the 5 schemas as both JSON and
  `repr`, were identical to the pre-move baseline after every commit and after the
  review fixes.
- **Golden capture:** 44 entries, byte-identical after every commit and after the
  review fixes. It covers 6 scripted `_run_agent_impl` scenarios recorded at a fake
  backend, every formatter branch, the judge prompt and the MCP strings. A
  deliberate one-character template change was detected, and the capture matched
  again once it was reverted.
- **Trace log:** `trace_logs/traces.jsonl` was unchanged (4084959 bytes) after every
  golden run. No eval quota was spent.
- **Tools:** ruff and pyright report 0 errors, and 793 tests pass (the 790 baseline
  plus 3 new tests):
  - one pins what `_run_agent_impl` sends to the backend;
  - one pins the `percent_change` expression;
  - one pins the generic search invalid-arguments message.
- **Coverage:** critical-core diff coverage against `origin/master` is 99%. The one
  uncovered line predates WP1.
- **No import cycle:** importing all `prompts` modules together with `agent`,
  `mcp_server` and `eval_harness` succeeds.

## Related

- Plan: `docs/plans/2026-09-24-wp1-prompts-package.md`
- Plan review: `docs/reviews/2026-09-24-wp1-prompts-package-plan-review.md`
- Code review: `docs/reviews/2026-09-24-wp1-prompts-package.md`
- Roadmap: `docs/plans/2026-09-24-prompt-audit-roadmap.md`
