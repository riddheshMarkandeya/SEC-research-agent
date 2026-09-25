# Review: WP2 plan, prompt fingerprint and eval provenance (two independent plan-review rounds)

Plan: `docs/plans/2026-09-24-wp2-prompt-provenance.md`. The plan adds per-surface
prompt fingerprints, eval-report provenance, a version-comparison script, a judge
nonstandard-output flag, a model pin and a panel baseline (roadmap Step 1 commit 1d,
and Step 2). This review covers the plan only, before implementation. The suite had
793 tests at HEAD `eaa1b45`.

## Pass 1: self re-check of the roadmap against HEAD `eaa1b45`

- [Fixed in plan] `eval_harness.py` doesn't import `log_event`; 1d adds the import.
- [Fixed in plan] The git helper to copy is `scripts/check_docs_health.py:_git`
  (`:118-125`), not `:116-123`.
- [Fixed in plan] The judge-location rule wording was already fixed in WP1. What's
  left is the stale "41-question" (at `:46` and `:63`) and the new "Prompt changes"
  section.
- [Fixed in plan] `MESSAGES_VERSION` is referred to by the roadmap but was never
  created. It was later replaced; see round 2.
- [Verified] All 13 panel IDs exist, and 5 are judged. The only reader of `detail`
  is `analyze_flakiness._error_type`, which sees only infra-error rows.
  google-genai 2.18.1 has `model_version`.

## Round 1: independent subagent (the whole WP2 plan)

**Confirmed:**
- hashing values under the SHA plus a clean-tree check is the simplest way to tie a
  report to one prompt version;
- the fingerprint coverage choices hold: `AGENT_TOOL_SCHEMAS` only, with the derived
  ratio lists excluded;
- JSON hashing is deterministic;
- CRLF with `autocrlf=true` gives no false dirty reports.

**Must-fix, all adopted:**
- **The REGRESSED-TOTAL count broke on unevenly shaped groups.** Infra truncation,
  replicate runs of only the flagged questions, and one-sided questions all produce
  them. Now the total is computed over shared questions only, with rates scaled to
  the candidate's run count.
- **The compare script didn't implement the Decision rule's "within 1 pass" test.**
  It now prints it per question, and small comparisons don't fail on the total.
- **Re-baselined runs share a fingerprint with the old base** (a revert restores the
  hash). Added `--since`, warnings within a group, and a rule that steps 2–3 use
  explicit mode.
- **The lenient judge parse had undefined cases:** `PASSED`, `PASS/FAIL: FAIL` and
  empty output. The flag's semantics are now defined; `passed` is unchanged.

**Should-fix, adopted:**
- an un-added prompts file counts as dirty, and git runs with
  `--no-optional-locks` and `-z`;
- the `.env` settings that change model input are recorded in provenance;
- the git stub is scoped to eval_harness's own `_git`;
- the quota day resets at midnight Pacific, and limits are per model;
- logging `model_version` becomes a follow-up only if the pin fails;
- diff-cover runs against `eaa1b45` as well as `origin/master`.

**Nits, adopted:**
- provenance runs after `parse_args`;
- explicit mode's rules for dirty and unstamped reports;
- print how many rows infra truncation dropped;
- the pin script lives in the scratchpad.

## User decisions between rounds

- **MCP verification added to the live step.** `tests/manual/verify_mcp_server.py`
  gains checks for the tool descriptions and schemas and the 3 error strings WP1
  moved. It uses no Gemini quota.
- **Code changes that alter model input.** Hashing constant values can't see them:
  logic in `agent.py`, `llm_backends`, `grade_judged` or `mcp_server` that changes
  what a model reads.
  - First chosen: per-consumer version numbers. The global and per-module versions
    were considered.
  - The user then pushed back: a manual bump is discipline-based.
  - Final choice: **a committed model-input snapshot** (approval testing), whose
    sections are folded into the fingerprint. Hashing consumer source files was
    also rejected, because it fires on unrelated edits and orphans baselines.

## Round 2: independent subagent (the snapshot design only)

**Confirmed:** a custom JSON file under `prompts/`, not syrupy or pytest-snapshot.
Those store their own formats under `tests/`, and production code would have to
parse them.

**Must-fix, all adopted:**
- a single pure `render_model_inputs()`, not module-global accumulation that depends
  on test order;
- no `default=repr` fallback in serialisation;
- a determinism check across two processes with different `PYTHONHASHSEED`s;
- capture the project's own tool-declaration output rather than library
  `model_dump`s, so a library upgrade can't split fingerprint groups. Library
  versions are recorded in provenance `config` instead.

**Should-fix, adopted:**
- **A stale-snapshot check at eval start**, run as a provenance subprocess, which
  records `snapshot_verified`. The alternative, a pre-commit hook, was rejected: it
  would partly reverse the 2026-09-22 move of code checks to pre-push.
- canonical `sort_keys` hashing;
- state that a companies.json edit changes the fingerprint;
- named scenario keys instead of a count;
- drop the duplicate `repr` capture.

## Outcome

All findings from both rounds were folded into the plan before approval.
