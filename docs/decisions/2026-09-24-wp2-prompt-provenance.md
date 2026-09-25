# Prompt fingerprints, eval provenance and a panel baseline (WP2)

**Date:** 2026-09-24

## Context

WP1 put every model-facing string in `prompts/`, but eval reports still couldn't say
which prompt version produced them. The prompt-audit roadmap's WP3+ changes need that,
plus a baseline to compare against. Plan:
`docs/plans/2026-09-24-wp2-prompt-provenance.md` (roadmap Step 1 commit 1d, and Step 2).

## Decision

- **Committed model-input snapshot:**
  - `tests/test_model_input_snapshot.py` renders everything a model receives into
    `prompts/model_input_snapshot.json`, with no network: 6 scripted agent loops, every
    formatter, the Gemini tool declarations, the judge messages, and MCP's listed tools
    and errors.
  - The test fails on any difference. `UPDATE_SNAPSHOT=1` regenerates the file.
- **Fingerprints:** `prompts.prompt_fingerprint()` returns one hash per surface, plus one
  key per consumer (`agent`, `judge`, `mcp`). Each consumer key hashes its constants
  *and* its snapshot section.
- **Report provenance:** every eval report carries `provenance`:
  - `git_sha`;
  - `git_dirty` and `dirty_files`, which include untracked files under the pathspecs;
  - `snapshot_verified`, from a pytest subprocess with a 300s timeout;
  - `config`: the `.env` model, embed, rerank and chroma settings, plus the google-genai
    and mcp versions;
  - `prompts`: the fingerprint.

  Provenance never raises and costs no quota. The run warns at start about every state
  that the compare script would later exclude.
- **`compare_prompt_versions.py`** implements the roadmap's Decision rule:
  - fingerprint mode (screen) and explicit mode (replicate and attribute);
  - totals over shared questions only;
  - REGRESSED-TOTAL at an integer ceil(14% of N), which can't fail when N < 20;
  - a per-question "within 1 pass" verdict;
  - `--since`, and warnings within and between groups;
  - it drops rows at the first infra error, and excludes reports that are dirty,
    unverified or have no SHA, unless `--include-dirty` is given.
- **Judge flag:** output whose first line isn't exactly PASS or FAIL gets a
  `[nonstandard judge output…]` reason prefix. "Lenient parse disagrees" marks output a
  whole-word reading would grade the other way. Grading itself is unchanged.
- **Model pin:** `GEMINI_MODEL_NAME=gemini-3.5-flash-lite` in `.env`. That is what
  `gemini-flash-lite-latest` resolved to, per `resp.model_version`.
- **Baseline ("B" for WP3):**
  - fingerprint `agent=cc984387c3e8` (`judge=2ee29f234c91`, `mcp=cc4ae9f9a9a6`);
  - SHA `2c3dbdd`, clean tree, snapshot verified;
  - google-genai 2.18.1, mcp 2.1.1;
  - reports `20260925T001138Z`, `20260925T001514Z` and `20260925T001931Z`.

  | question | passed |
  |---|---|
  | nvda-segment-revenue-comparison-q1fy27 | 2/3 |
  | pltr-inventory-turnover-fy2025-refusal | 2/3 |
  | the other 11 panel questions | 3/3 each |
  | **total** | **37/39** |

  - There were no infra errors and no nonstandard judge output.
  - Both failures were single-run refusals citing a failed verification, on questions
    that passed the other two runs.

## Why

- **A committed snapshot, not a manual version bump.** Hashing constants alone can't
  see code that changes what a model reads without touching a constant: `agent.py`
  filling templates, `_to_gemini_tool`'s conversion, `grade_judged`'s fields, and
  `mcp_server` choosing errors. The roadmap's `MESSAGES_VERSION` relied on someone
  remembering to bump it. The user rejected that as discipline-based, and also rejected
  per-module and global versions and hashing consumer sources.
  - With the snapshot, a logic change that alters model input fails the suite until the
    file is regenerated in the same commit. The fingerprint then changes by itself. A
    logic change that alters nothing leaves the fingerprint alone.
  - A custom JSON file in `prompts/` was chosen over syrupy and pytest-snapshot. Their
    formats sit under `tests/`, and production code would have to parse a test tool's
    format.
- **One key per consumer** (the user's choice), so a judge-only edit doesn't split the
  agent groups.
- **Snapshot check at eval start, not a pre-commit hook.** A hook would partly reverse
  the 2026-09-22 move of code checks to pre-push. Provenance guards exactly the case
  that matters: evaluating on a stale snapshot.
- **Totals over shared questions, and explicit mode for replicate and attribute.** Groups
  differ in shape (infra truncation, F-only replicates, one-sided questions), so raw
  counts mislead. A revert restores the base fingerprint, so fingerprint mode would pool
  reverted runs with the old base.
- **The judge parse stays unchanged.** Fixing it would change pass/fail outcomes, and
  finding 7 is evidence-gated. The flag collects that evidence first.
- **The MCP live check** was added at the user's request.

**Limits:**
- A code path no snapshot scenario reaches is invisible to the snapshot. The constant
  hashes still catch any edit to its text.
- Chroma index contents aren't fingerprinted. `config.chroma_dir` records only the path.
- Editing `companies.json` changes the `agent` fingerprint, which is intended: the model
  sees different text. That needs a new baseline.
- The `*.py` provenance pathspec also marks a run dirty for an untracked scratch script
  that isn't gitignored. That errs on the safe side, and the file is named.

## Files touched

- Prompt fingerprint and snapshot:
  - `prompts/__init__.py`;
  - `prompts/*.py` (`FINGERPRINTED` / `NOT_FINGERPRINTED`);
  - `prompts/model_input_snapshot.json`;
  - `llm_backends.py` (`_gemini_declaration_fields`).
- Eval and comparison:
  - `eval_harness.py`;
  - `analyze_flakiness.py` (`load_reports`);
  - `compare_prompt_versions.py`.
- `.claude/rules/live-eval-verification.md`: the "Prompt changes" section, and 41 → 48.
- Tests:
  - `tests/test_model_input_snapshot.py`, `tests/test_prompts.py` and
    `tests/test_compare_prompt_versions.py`;
  - `tests/test_eval_harness.py`, `tests/test_analyze_flakiness.py` and
    `tests/test_llm_backends.py`;
  - `tests/manual/verify_mcp_server.py`.

## Verification

- **Suite:** 917 passed, ruff and pyright clean. Diff coverage is 100% on WP2's own
  changes and 98% against `origin/master`.
- **Snapshot:**
  - its agent entries equal WP1's 44-entry golden capture;
  - a one-character template change failed the test with a readable diff;
  - rendering is identical across hash seeds, and a CRLF copy hashes the same.
- **Live:**
  - `verify_mcp_server.py` passed every check, old and new;
  - the `aapl-ai-risk` spot-check passed with full provenance;
  - the panel ran 3× with no infra errors.
- **Review:** 5 rounds, in `docs/reviews/2026-09-24-wp2-prompt-provenance.md`.

## Related

- Plan: `docs/plans/2026-09-24-wp2-prompt-provenance.md`.
- Plan review: `docs/reviews/2026-09-24-wp2-prompt-provenance-plan-review.md`.
- Code review: `docs/reviews/2026-09-24-wp2-prompt-provenance.md`.
- Roadmap: `docs/plans/2026-09-24-prompt-audit-roadmap.md`.
- Follows `docs/decisions/2026-09-24-wp1-prompts-package.md`.
