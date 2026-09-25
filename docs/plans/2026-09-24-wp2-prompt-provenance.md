# WP2: prompt fingerprint, eval provenance, compare script, judge flag, model pin, panel baseline

## Context
WP2 of `docs/plans/2026-09-24-prompt-audit-roadmap.md`: roadmap **Step 1 → "Commit 1d"**
and **Step 2**. The design is in those sections; this plan doesn't restate them. It
records only WP2's scope, what changed since the roadmap (mostly because of WP1 and
this plan's review), and the order of work.

**Why:** WP1 put every model-facing string in `prompts/`, but eval reports still can't
say which prompt version produced them. WP2 adds:
- a per-surface fingerprint of the prompt text;
- report provenance: git SHA, dirty state, fingerprint, and the `.env` settings that
  change what the model sees;
- a compare script that diffs one prompt version's panel runs against another's and
  implements the roadmap's Decision rule;
- a judge-output flag that collects evidence for finding 7;
- a pinned Gemini model version;
- the 13-question panel baseline, 3 runs, which becomes "B" for WP3.

Substantial tier (new module plus new tool). TDD for all code.

## Repo state check (2026-09-24, HEAD `eaa1b45`, clean tree, 793 passed, ruff and pyright clean)
- `prompts/__init__.py` holds only a docstring. WP1 deferred `FINGERPRINTED` and the
  fingerprint functions to WP2.
- **Reports** (`eval_harness.save_report`, `:403`) are a dict:
  `{backend, answer_model, judge_model, results}`. `answer_model` and `judge_model`
  both come from `config.GEMINI_MODEL_NAME` (default `gemini-flash-lite-latest`,
  `config.py:38`), so pinning it pins the judge too.
- **`grade_judged`** (`:121`) sets `passed = first_line.startswith("PASS")`. So
  `**PASS**` is graded FAIL today, and `PASSED` is graded PASS.
- `eval_harness.py` doesn't import `log_event` (only `flush`). Its coverage is 100%;
  `analyze_flakiness.py` is at 93%.
- **`analyze_flakiness.py`:** `load_rows` (`:45`) already handles both the list and
  dict shapes. `is_infra_error` (`:59`) is `answer is None`. The stale "no
  commit/version field" notes are at `:190-192` and `:357-358`.
- `detail` has one reader: `analyze_flakiness._error_type` (`:72`), which only sees
  infra rows. So the judge-flag prefix breaks no consumer.
- **Panel:** all 13 panel IDs exist in the 48-question file. 5 are judged.
- **`.env`** is gitignored. `GEMINI_MODEL_NAME`, `EMBED_MODEL_NAME`,
  `RERANK_MODEL_NAME` and `CHROMA_DIR` (`config.py:38-50`) all come from it, and all
  change what the model sees.
- **Anchor corrections to the roadmap:**
  - the git helper to copy is `scripts/check_docs_health.py:_git` (`:118-125`);
  - "41-question" appears in `live-eval-verification.md` at `:46` and `:63`;
  - the judge-location rule wording was already fixed in WP1.
- google-genai 2.18.1's `GenerateContentResponse` has `model_version`.

## Changes vs. the roadmap
1. **What each surface fingerprints.**
   - `agent_system`: `SYSTEM_PROMPT` only. The ratio lists and `FACT_METRICS` go in
     `NOT_FINGERPRINTED`; they're derived data, captured by their rendered form.
   - `agent_tools`: **`AGENT_TOOL_SCHEMAS` only**, which covers both content and
     send order. The 5 individual schemas and `CLAIM_UNITS` go in
     `NOT_FINGERPRINTED`. MCP's 3 schemas are the same objects. A comment notes that
     `mcp_server._TOOL_SCHEMAS`' own order isn't fingerprinted, which is irrelevant
     to Gemini evals.
   - `agent_messages`: every constant.
   - `judge`: both constants. `mcp`: its 3 strings.
   - Hash: `sha256(json.dumps(values, ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()[:12]`.
1b. **A committed model-input snapshot, replacing the roadmap's `MESSAGES_VERSION`**
   (user decision, 2026-09-24; a manual version bump was rejected as
   discipline-based).
   - **The problem:** hashing values can't see code that changes what a model reads
     without touching a constant:
     - `agent.py`, which picks and fills templates (WP6's "None FYNone" fix, WP7);
     - `llm_backends._to_gemini_tool`'s schema conversion;
     - `eval_harness.grade_judged`, which chooses the judge template's fields;
     - `mcp_server`, which decides when each error is returned.
   - **The fix is snapshot (approval) testing.** Promote WP1's scratch golden capture
     into one pure function, `render_model_inputs() -> dict`, in
     `tests/test_model_input_snapshot.py`. It builds the whole snapshot in a single
     call, with no module-global accumulation, so it doesn't depend on test order,
     `-k` or xdist. It records, with no network:
     - 6 scripted `_run_agent_impl` runs at a fake `agent.BACKENDS`;
     - every formatter branch;
     - the Gemini tool declarations as the project's own code builds them:
       `{name, description, parameters: _strip_additional_properties(...)}`. This is
       not the library's `model_dump`, so a google-genai or mcp upgrade that only
       adds default fields can't split fingerprint groups;
     - the judge's rendered system and user messages, with the date frozen;
     - the MCP error strings, and the listed tools as `{name, description,
       inputSchema}` built from `_TOOL_SCHEMAS`.
   - **Serialisation:** explicit, with no `default=repr`. Warnings use `._asdict()`.
     The file is written with `sort_keys=True, indent=1, ensure_ascii=False,
     allow_nan=False`, so an unexpected type fails loudly. The scratch file's
     `tool_schemas_repr` field is dropped.
   - **Scenario keys:** a named set of expected keys replaces the scratch file's
     `len == 44`, so a missing scenario gives a readable error.
   - **The snapshot file:** it writes `prompts/model_input_snapshot.json` with the
     top-level sections `agent`, `judge` and `mcp`.
     - The test fails with a readable diff whenever the rendered output differs from
       the committed file.
     - `UPDATE_SNAPSHOT=1 pytest tests/test_model_input_snapshot.py` rewrites it.
   - **The fingerprint:** each consumer key hashes its constants plus its snapshot
     section:
     - `agent` = h(agent_system, agent_tools, agent_messages, snapshot["agent"]);
     - `judge` and `mcp` likewise.
     - Sections are hashed after `json.load` and a canonical re-dump
       (`sort_keys=True` plus the constant-hash `json.dumps` settings), so neither
       key order nor CRLF conversion changes them.
   - **The result:** a logic change that alters model input fails the suite until
     the snapshot is regenerated in the same commit, and the fingerprint then changes
     automatically. A logic change that alters nothing leaves the fingerprint alone.
     No manual versions.
   - **Limits, recorded in the decision file:**
     - a code path no scenario reaches is invisible to the snapshot, though the
       constant hashes still catch any edit to its text;
     - a stale snapshot is caught by the test suite, and **at eval start**:
       `_collect_provenance` runs `pytest tests/test_model_input_snapshot.py -q` in
       a subprocess (no quota, and no test code in the eval process). It records
       `snapshot_verified: true/false/null`, where null means pytest was
       unavailable. The compare script treats a report that isn't `true` like a
       dirty one: excluded unless `--include-dirty`, with a loud warning.
       - A pre-commit hook was the alternative. It was rejected because it would
         partly reverse the 2026-09-22 decision to move code checks to pre-push,
         while provenance guards exactly the case that matters: evaluating on a
         stale snapshot.
     - adding a ticker to `companies.json` changes the search-error text, and so
       the `agent` fingerprint. That splits comparison groups and needs a new
       baseline, which is intended and stated in the rule.
     - the compare script's multi-SHA warning remains the last backstop.
   - **Determinism:**
     - `is_metric_tagged` is patched, and tracing is off;
     - the datetime is frozen for the judge;
     - a test renders in two subprocesses with different `PYTHONHASHSEED` values
       and asserts they're equal, which catches unsorted set joins.
   - **Library drift without splitting fingerprints:** provenance `config` also
     records the `google-genai` and `mcp` versions, via `importlib.metadata`.
     - `companies.json` and `RATIO_DEFINITIONS` feed the snapshot on purpose.
2. **Split 1d into 6 commits:**
   - **1d-i:** the model-input snapshot.
   - **1d-ii:** fingerprints.
   - **1d-iii:** eval_harness provenance and the judge flag.
   - **1d-iv:** `load_reports` and `compare_prompt_versions.py`.
   - **1d-v:** rule files.
   - **1d-vi:** the MCP live-check extension (user request).
3. **Compare-script arithmetic** (plan review, must-fixes 1–2). The roadmap's
   raw-count REGRESSED-TOTAL breaks when groups differ in shape. That happens with
   infra truncation, the Decision rule's F-only replicate runs, and one-sided
   questions.
   - **Totals use shared questions only.** The expected loss is
     Σ_q (base_rate_q − cand_rate_q) × n_cand_q over questions in both groups.
     REGRESSED-TOTAL fires when that is at least `ceil(0.14 × Σ n_cand_q)`: 6 for a
     13×3 panel.
   - **Small comparisons don't fail on the total.** When Σ n_cand_q < 20 (replicate
     runs), the total is reported but doesn't set the exit code.
   - **One-sided questions** are listed separately and left out of totals.
   - **Per question,** the script also prints the pass-count delta scaled to the
     candidate's n, plus a **"within 1 pass"** verdict. That is exactly Decision
     rule step 2's test, so the operator doesn't have to work it out by hand.
   - The roadmap review's "5 of 36" doesn't match the roadmap's own formula
     (`ceil(5.04) = 6`). The formula is used as written.
4. **Grouping** (must-fix 3). A revert restores the base fingerprint, so re-baselined
   runs and the old B share one `agent` group.
   - Fingerprint mode keeps grouping by `provenance.prompts.agent` and adds
     `--since <report-timestamp>` to drop older reports.
   - It warns when the judge hash, `answer_model`, `config` or SHA differ *within* a
     group, as well as between groups.
   - The new rule section says Decision-rule steps 2–3 always use explicit mode.
5. **Judge flag cases** (must-fix 4).
   - `passed` is computed exactly as today, before any flag logic.
   - "Standard" means the stripped, uppercased first line is exactly `PASS` or
     `FAIL`. Anything else is nonstandard.
   - The lenient verdict is a `\b(PASS|FAIL)\b` search over the whole uppercased text.
     It is **None** when neither word appears or both do. None gives the plain flag,
     never "disagrees".
   - "Disagrees" means lenient is not None and differs from `passed`.
   - The prefix includes `repr(first_line)[:60]` as evidence.
   - Test cases: `PASS\n…` (no flag), `PASS.` (plain), `**PASS**` (disagrees),
     `PASSED` (plain), `PASS/FAIL: FAIL` (plain), and an empty string (plain).
6. **Provenance hardening** (should-fixes 5–7):
   - **git command:** `git --no-optional-locks status --porcelain -z --untracked-files=no -- *.py prompts companies.json eval/eval_questions.jsonl`.
     A second check, `--untracked-files=all -- prompts`, counts an un-added prompts
     file as dirty.
     - `*.py` matches at any depth, so a tests-only edit also marks the tree dirty.
       That's accepted.
   - **`config`:** provenance also records
     `{gemini_model, embed_model, rerank_model, chroma_dir, google_genai, mcp}`: the
     first four from `config`, the library versions from `importlib.metadata`.
   - **Blind spot:** the Chroma index contents aren't fingerprinted. Record that in
     the decision file.
   - **Tests** stub eval_harness's own `_git` helper, not `subprocess.run`
     globally.
7. **Pin before the spot-check.** The single `aapl-ai-risk` run then checks both
   `provenance` and that the API accepts the concrete model name, before the panel
   spends its quota.

## Steps
0. **Save this plan** to `docs/plans/2026-09-24-wp2-prompt-provenance.md` (from
   `TEMPLATE.md`), and the review below to
   `docs/reviews/2026-09-24-wp2-prompt-provenance-plan-review.md`. Keep both unstaged
   until step 9, because the docs-health pre-commit check would block them.
1. **Commit 1d-i: model-input snapshot** (change 1b).
   - Promote the scratch `test_golden.py` to `tests/test_model_input_snapshot.py`
     as the pure `render_model_inputs()` described in change 1b.
   - Generate `prompts/model_input_snapshot.json` with `UPDATE_SNAPSHOT=1`.
   - **Check:** every value it has in common with the WP1 scratch
     `golden_before.json` (regenerate from `38af001` if lost) is equal, and the new
     tool-declaration entries equal `_strip_additional_properties` of today's
     schemas. That proves the snapshot starts from byte-identical model input.
   - **Self-check, once:** change one template character, confirm the test fails
     with a readable diff, then revert.
   - **Size and readability:** the scratch capture repeats the system prompt and
     schemas in all 6 loop runs, over 100 KB. The repo version records them once,
     in their own entries. Each loop run asserts its `start` call received exactly
     those values and records only a marker. That keeps the file small and its
     diffs readable.
   - **Layout:** one key per scenario, `indent=1`, `ensure_ascii=False`. A change
     then shows up as a small, reviewable git diff.
2. **Commit 1d-ii: fingerprints (TDD).**
   - **Tests first,** in the new `tests/test_prompts.py`:
     - determinism, including across two subprocesses with different
       `PYTHONHASHSEED` values;
     - patching a fingerprinted constant changes that surface's hash, and changes
       `agent` if and only if it's one of the 3 agent surfaces;
     - patching a `NOT_FINGERPRINTED` name changes nothing;
     - an `ast` check: every top-level uppercase `Assign`/`AnnAssign` target in the
       5 surface modules (not imports, not the two tuples themselves) is in exactly
       one tuple;
     - every fingerprinted value is JSON-serialisable with `allow_nan=False`;
     - changing one snapshot section (a tmp copy, via a path parameter) changes only
       that consumer's key;
     - a CRLF copy of the snapshot hashes the same as the LF original;
     - a missing or unreadable snapshot raises, which provenance turns into
       `"prompts": "error"`.
   - **Then the code:** the tuples, and `prompts/__init__.py:prompt_fingerprint()`,
     which returns
     `{"agent_system", "agent_tools", "agent_messages", "judge", "mcp", "agent"}`.
     The `agent`, `judge` and `mcp` keys include their snapshot sections (change 1b).
3. **Commit 1d-iii: `eval_harness.py` (TDD).**
   - **Tests first:**
     - provenance is written;
     - a git failure gives `git_sha: "unknown"` plus a `log_event`, and never raises;
     - a fingerprint exception gives `"prompts": "error"`;
     - untracked prompts files and dirty files are parsed from `-z` output;
     - `snapshot_verified` is true, false, or null (pytest missing), with the
       subprocess stubbed;
     - `config` is recorded;
     - every judge-flag case in change 5.
   - **Then the code:**
     - `_git` (copied from `check_docs_health._git`, binary mode, UTF-8 decode);
     - `_collect_provenance()`, run in `main()` right after `parse_args`;
     - `save_report(..., provenance=None)`, which writes the key only when given, so
       the existing tests at `:389-420` stay valid;
     - the `log_event` import;
     - the flag in `grade_judged`, plus `log_event("judge_nonstandard_output", …)`.
4. **Commit 1d-iv: comparison tooling (TDD).**
   - **`analyze_flakiness.load_reports(paths)`** handles the legacy list shape, and
     `load_rows` is built on it. Update the notes at `:190-192` and `:357-358`:
     reports carry provenance from WP2 on.
   - **New `compare_prompt_versions.py`**, following roadmap 1d as amended by
     changes 3–4:
     - drop rows from the first infra error onward, and print how many were dropped;
     - skip unstamped reports in fingerprint mode;
     - exclude dirty reports unless `--include-dirty` is given, in either mode;
     - explicit mode accepts unstamped files;
     - "most recent" is decided by the UTC report filename;
     - the flags: REGRESSED (a drop of 0.5 or more), watch, improved, floor (base rate
       of 1/3 or less);
     - the warnings, `--since`, and exit 1 on any REGRESSED or a counting
       REGRESSED-TOTAL;
     - **one group only** (right after the baseline): print its per-question k/n
       table and exit 0.
     - The core is pure: `compare()` plus `format_comparison()`, with a thin `main()`.
       Keep within C901 ≤ 10 and PLR0911-0915.
     - Thresholds are named constants (PLR2004).
   - **Tests first:** new `tests/test_compare_prompt_versions.py` covers the
     roadmap's list plus:
     - uneven n and one-sided questions;
     - the small-N total not failing;
     - the "within 1 pass" verdict;
     - `--since`;
     - warnings within a group.
     Also `load_reports` tests in `tests/test_analyze_flakiness.py`.
5. **Commit 1d-v: rules.** In `live-eval-verification.md` (its `paths:` already
   covers `prompts/**`; leave it):
   - "41-question" → 48 at `:46` and `:63`;
   - a new **Prompt changes** section:
     - one commit per `prompts/` change;
     - the panel protocol with `compare_prompt_versions.py`;
     - explicit mode for Decision-rule steps 2–3;
     - a change that alters what a model reads, whether text or logic, regenerates
       `prompts/model_input_snapshot.json` in the same commit
       (`UPDATE_SNAPSHOT=1`), after reading its diff. When a new code path starts
       sending model text, add a scenario for it.
6. **Commit 1d-vi: MCP live-check extension** (user request). Extend
   `tests/manual/verify_mcp_server.py` (live-only per the TDD carve-out; it starts
   the real server and connects a real MCP client). It adds checks for what WP1
   moved and WP2 touches:
   - each listed tool's `description` and `inputSchema` equal
     `prompts.agent_tools`' schema, in `_TOOL_SCHEMAS` order;
   - a no-data `get_financial_fact` call (for example AAPL revenue FY1990) returns
     exactly `{"error": FACT_NOT_AVAILABLE_ERROR}`;
   - a no-data `compare_financial_metric` call returns
     `{"error": COMPARISON_NOT_AVAILABLE_ERROR}`;
   - an unknown tool name returns `is_error` with
     `UNKNOWN_TOOL_TEMPLATE.format(name=…)`.
   Also update the script's docstring list.
7. **Review:** after the full suite passes, give the `/compact` line, then run
   `independent-review-pass` over 1d-i..vi. Escalated items:
   - the fingerprint covers every model-visible constant;
   - the snapshot reaches every WP1 golden scenario, is deterministic, and
     tolerates CRLF;
   - provenance never raises and costs no quota;
   - the judge flag changes no pass/fail outcome.
8. **Live (Step 2).** Use one quota day; Gemini resets at midnight Pacific, not UTC.
   The estimate is about 225 requests: a question averages about 4.5 agent requests
   (from the traces), there are about 0.6 retries per run, and each panel run adds 5
   judge calls.
   0. **MCP check (no Gemini quota):** run `python tests/manual/verify_mcp_server.py`
      on the committed tree. Every check must pass, including the new ones from 1d-vi
      and the existing auth and rate-limit checks.
   1. **Pin the model:** a scratchpad script (not in the repo) calls
      `llm_backends._get_gemini_client().models.generate_content(model=GEMINI_MODEL_NAME, contents="ping")`
      and prints `resp.model_version`.
      - Check the pinned name's free-tier daily cap. Limits are per model.
      - Set `GEMINI_MODEL_NAME=<version>` in `.env`.
      - If the API rejects the name: keep the alias, record it, and add a follow-up
        to log `resp.model_version` for each run. That touches `llm_backends`, which
        is critical-core, so it gets its own item rather than going into WP2.
   2. **Spot-check:** `python eval_harness.py --backend gemini --ids aapl-ai-risk`.
      The report must have `provenance` with a clean tree, the pinned model and
      `config`, and `compare_prompt_versions.py` must list it.
   3. **Panel 3×:** `python eval_harness.py --backend gemini --ids <PANEL>`, on a
      clean tree.
      - Start only if at least about 250 requests of that day's quota remain.
      - Stop at `RESOURCE_EXHAUSTED`.
      - Run `compare_prompt_versions.py --since <spot-check timestamp>` to get the
        single-group baseline table.
9. **Docs:**
   - **Decision file** `docs/decisions/2026-09-24-wp2-prompt-provenance.md`:
     - the baseline fingerprint, SHA, pinned model, `config`, and per-question k/3
       and total;
     - changes 1–7, including 1b;
     - the MCP live-check result;
     - the Chroma blind spot;
     - the user's decisions: a committed model-input snapshot instead of a manual
       version (per-consumer, global and per-module versions were considered, along
       with hashing consumer sources), and the MCP verification added to the live
       step;
     - the snapshot's limits (change 1b).
   - **Review file:** save the code review to `docs/reviews/`.
   - **`BACKLOG.md`:** delete the WP2 line; WP8 files finding 7. Add the
     `model_version`-logging item only if the pin fails.
   - **`PROJECT_INDEX.md`:** add Recent lines.
   - Commit, and don't push.

**Commits:** approving this plan authorises commits 1d-i..vi as each one's checks
pass, the review-fix commit(s), and the docs commit. Nothing is pushed. The live step
spends about 225 Gemini requests.

## Plan review (1 independent round, 2026-09-24; source for the step-0 review file)
- **Confirmed:**
  - hashing values under the SHA plus a clean-tree check is the simplest way to tie
    a report to one prompt version;
  - the fingerprint coverage choices are correct;
  - JSON hashing is deterministic;
  - the judge flag can't break any consumer of `detail`;
  - `model_version` exists;
  - CRLF with `autocrlf=true` doesn't cause false dirty reports.
- **Must-fix, all adopted:**
  - the total over uneven groups (change 3);
  - the Decision rule's "within 1 pass" test (change 3);
  - re-baselines sharing a fingerprint, plus warnings within a group (change 4);
  - undefined lenient-parse cases (change 5).
- **Should-fix, adopted:**
  - untracked prompts files, `--no-optional-locks` and `-z`;
  - recording the `.env` config;
  - scoping the git stub to `_git`;
  - the quota day resets at midnight Pacific, with per-model limits;
  - `model_version` logging, conditional on the pin failing;
  - diff-cover against `eaa1b45` as well as `origin/master`.
- **Nits, adopted:**
  - provenance runs after `parse_args`;
  - explicit mode's rules for dirty and unstamped reports;
  - printing the infra-truncation count;
  - the pin script lives in the scratchpad;
  - no pre-push change is needed (`compare_prompt_versions.py` isn't critical-core).

**Second round (after the snapshot decision), focused on change 1b:**
- **Confirmed:** a custom JSON file in `prompts/`, not syrupy or pytest-snapshot.
  Their formats sit under `tests/`, and production code would have to parse a test
  tool's format.
- **Must-fix, all adopted:**
  - a single pure render function, not order-dependent module-global accumulation;
  - no `default=repr`;
  - a determinism check across processes with different `PYTHONHASHSEED`s;
  - capture the project's own tool-declaration output rather than library
    `model_dump`s, so an upgrade can't split fingerprints, and record library
    versions in `config`.
- **Should-fix, adopted:**
  - a stale-snapshot check at eval start, in a provenance subprocess. A pre-commit
    hook was rejected; see change 1b.
  - canonical `sort_keys` hashing;
  - stating that a companies.json edit changes the fingerprint;
  - named scenario keys;
  - dropping `tool_schemas_repr`.

## Out of scope
- Changing the judge's output format (finding 7 is evidence-gated; only the flag
  lands here).
- Re-stamping the 130 historical reports.
- Ollama/qwen.
- Any prompt wording change: WP3 onwards.

## Critical files
- `prompts/__init__.py` (`prompt_fingerprint`), the tuples in `prompts/*.py`, and
  the new `prompts/model_input_snapshot.json`.
- New `tests/test_model_input_snapshot.py`.
- `tests/manual/verify_mcp_server.py`.
- `eval_harness.py`: `main`, `save_report`, `grade_judged`, and the new `_git` and
  `_collect_provenance`.
- `analyze_flakiness.py`, and the new `compare_prompt_versions.py`.
- Tests: new `tests/test_prompts.py` and `tests/test_compare_prompt_versions.py`;
  updated `tests/test_eval_harness.py` and `tests/test_analyze_flakiness.py`.
- `.claude/rules/live-eval-verification.md`.
- **Reuse:**
  - `analyze_flakiness.is_infra_error`;
  - `scripts/check_docs_health._git`;
  - `tracing.log_event`;
  - the per-test `eval_harness.complete` stubs.

## Verification
- **Each commit:** `ruff check .`, `pyright .` and
  `pytest --cov=. --cov-report=term-missing -q` are all clean. Run `diff-cover`
  against both `eaa1b45` (WP2 only) and `origin/master`: 90% or more on critical-core
  files (`eval_harness.py`, `prompts/`) and 80% or more elsewhere.
- **1d-i:** the snapshot's agent entries equal WP1's `golden_before.json`, and the
  one-character self-check fails as expected.
- **Every later commit:** the snapshot test passes with no regeneration, since no
  model input changes in WP2.
- **Live:**
  - the spot-check report carries `provenance`, and the compare script lists it;
  - three panel reports exist under one fingerprint with no infra errors;
  - the baseline table is recorded.
