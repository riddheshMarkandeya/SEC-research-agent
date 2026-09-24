# Prompt-audit roadmap: prompts package, attribution tooling, staged rollout

This is a **roadmap** covering several work packages (WPs). It is not a single-change
plan. Each WP is a `BACKLOG.md` item (section "From the 2026-09-24 prompt-audit
roadmap"), planned and implemented in its own plan-mode session. The audit findings
are in `docs/reviews/2026-09-24-prompt-audit.md`.

## How this roadmap is executed

| WP | Scope | Roadmap section | Eval quota |
|---|---|---|---|
| WP1 | `prompts/` package move (findings: none; refactor) | Step 1, commits 1a–1c | none |
| WP2 | fingerprint, provenance, `compare_prompt_versions.py`, judge flag, model pin, panel baseline | Step 1 commit 1d, Step 2 | panel ×3 |
| WP3 | Group A wording fixes (findings 1, 2, 5, 6) | Step 3 | panel ×3 |
| WP4 | rule 3 / rule 9 contradiction (finding 3) | Step 4 | panel ×3 |
| WP5 | segment-rule emphasis (finding 4) | Step 5 | panel ×3 |
| WP6 | no-data message rendering and wording (findings 11, 12) | Step 6 | panel ×3 |
| WP7 | accept digit-only `fiscal_year` strings, "rejected outright" wording (finding 13) | Step 7 | panel ×3 |
| WP8 | final full run and wrap-up | Steps 8–9 | full run ×1 |

- **Start:** enter plan mode, read the WP's section, and re-check line numbers and
  repo state.
- **Plan:** write a short WP plan that points at the section instead of restating
  it, and add anything that has changed since. Run the review floor.
- **Save and implement:** after approval, save the WP plan to `docs/plans/`, then
  implement.
- **Screen** (prompt WPs): run the manual checks, then a light
  `independent-review-pass` before spending eval quota, then the Decision rule below.
- **Close:** write a decision file with the WP's row (commit, fingerprint, panel B
  vs C, outcome). Delete the BACKLOG line and add the index line.
- **Order:** WPs run strictly in order. Each panel comparison assumes exactly one
  prompt change since the last accepted fingerprint.
- **This roadmap is not edited; WP files record changes.** If a WP finds the
  roadmap is wrong, record the change in that WP's plan and decision files, like
  any other plan file.


## Context

The 2026-09-23 `/claude-api prompt-audit` of the agent's prompt surface found
contract and wording issues in SYSTEM_PROMPT and the tool descriptions. A later
survey of all model-facing text added three contract bugs. The user wants them
fixed so that **any regression can be attributed to a specific change and
reverted cheaply**.

Today that isn't possible:
- **Reports can't be tied to a prompt version.** Eval reports
  (`eval/eval_results/<UTC>.json`, from `eval_harness.py:save_report`) record no
  git SHA and no prompt hash.
- **"Regression" means something else.** In `analyze_flakiness.py` it means
  "trailing fail streak", not "worse than the previous version".
- **Model-facing text is scattered.** It lives across `agent.py` (SYSTEM_PROMPT,
  5 schemas, around 40 tool-result, error, retry and warning strings),
  `eval_harness.py` (the judge's system and user prompts) and `mcp_server.py`
  (the MCP error strings).
- **The eval is noisy.** The last two full runs scored 38/47 and 39/47.
- **Quota is tight.** The Gemini free tier allows about 500 requests/day, at about
  4–5 per question.

**User decisions (2026-09-24):**
1. **Attribution:** one git commit per finding. Eval reports carry the git SHA and
   a per-surface prompt fingerprint, and a compare script diffs run groups.
   Undo with `git revert`. Env-var prompt variants were rejected.
2. **Finding 7** (structured judge output) is **evidence-first**: add
   instrumentation only for now.
3. **Budget:** a fixed panel run 3× per step, and one full run at the end.
4. **No Ollama/qwen checks.** Gemini (`gemini-flash-lite-latest`) is the only
   gated model.
5. **Order: tooling first, then the audit.** Raising the baseline pass rate is a
   separate plan afterwards.
   - The known failures are mostly model non-determinism, or design items already
     in `BACKLOG.md`.
   - Their fixes will probably be prompt changes, and should land on the
     cleaned-up prompt and be measured by this tooling.
   - A noisy baseline doesn't block this plan, because the panel compares each
     version against the previous one.
6. **Move every piece of text a model reads into one place.** That covers the
   agent model, the judge and MCP clients: fixed strings and templates, from
   every module.
7. **The contract bugs** from the survey join this rollout.
8. **Step 7 accepts digit-only strings for `fiscal_year` as integers.** This
   reopens an earlier call on purpose.
   - The earlier call: the `BACKLOG.md` item on `msft-cash-to-assets-fy2025`
     clause (a) left this as "don't chase model non-determinism speculatively".
   - The new evidence: 138 live `invalid_fiscal_year_type` rejections from
     Gemini, 09-11 to 09-22, 9 of them on a canary question. It's no longer
     speculative.
   - It doesn't contradict the 2026-09-09 validation decision. That decision
     rejected strings to keep unmet-metric telemetry clean, not for correctness:
     a string simply failed to match.

**Why a `prompts/` package, and why plain Python constants** (user asked: one
file or several? How do others do it?)
- **How others do it:** there are three common approaches.
  - Constants in a code module: the usual choice for a hand-built agent.
  - Template files (Jinja or YAML): used when non-engineers edit prompts.
  - A hosted prompt registry (Langfuse Prompt Management, PromptLayer, LangSmith
    Hub): used for editing without deploys, or A/B labels served in production.
- **Plain Python for this project:** the prompts are computed from
  `RATIO_DEFINITIONS`, `DEFAULT_METRIC_TAGS` and `companies.json`. A registry
  would add a runtime network dependency and a second version history besides git.
  (Pushback: Langfuse is already running, but deploy-free editing isn't a need here.)
- **A package with one module per surface, rather than one file.** The moved
  text is about 25k characters, roughly 900 lines with comments. Per-surface
  modules give:
  - a readable `git log` for each surface;
  - a fingerprint per surface, so a report shows *which* surface changed;
  - rule-file `paths:` that can name exactly what's covered.

**Other benefits:**
- The file-wide ruff exemption from the long-line check (`# ruff: noqa: E501`),
  which today covers all 2,900 lines of `agent.py`, moves to `prompts/` only.
- A move can be proven not to change anything, at zero eval cost: the hashes and
  the rendered output must be identical before and after.

**Plan reviews**: three independent-subagent rounds on 2026-09-24, all folded in
(full record: `docs/reviews/2026-09-24-prompt-audit-roadmap-plan-review.md`). The
important ones:
- The MCP search description would have become false.
- New rule 3 would have contradicted rule 9.
- The first revert rule was biased by regression to the mean.
- The panel included a question that can't regress.
- Model-alias drift wasn't detectable.
- Rule-file `paths:` must include the new module.
- The failure-mode warnings must move with the retry text.
- Nothing pinned what `_run_agent_impl` actually sends.


## Prior art

How other projects hold prompt text:
1. **Constants in a code module:** the usual choice for a hand-built agent.
2. **Template files (Jinja or YAML):** used when non-engineers edit prompts.
3. **A hosted prompt registry** (Langfuse Prompt Management, PromptLayer, LangSmith
   Hub): used for editing without deploys, or A/B labels served in production.

This project uses (1), as a package with one module per surface. The reasons are
under "Why a `prompts/` package" in Context.

For attribution, the choice was one git commit per change, fingerprinted eval
reports, and revert-and-rerun confirmation. Env-var prompt variants were rejected,
because they put branching inside SYSTEM_PROMPT.

## Decision / Design

The design is the Files and steps below. The user decisions it rests on are listed
in Context.

## Files and steps: Phase 1: Tooling (Steps 1–2)

### Step 1: `prompts/` package (WP1: commits 1a–1c) and instrumentation (WP2: commit 1d)

#### Package layout
Each module holds one surface. `__init__.py` holds only the fingerprint functions,
with no re-exports, so every name has one import path.

| Module | Contents | Consumer |
|---|---|---|
| `prompts/agent_system.py` | `SYSTEM_PROMPT` and the 4 derived ratio lists | agent model |
| `prompts/agent_tools.py` | the 5 `*_TOOL_SCHEMA`s, `CLAIM_UNITS`, `AGENT_TOOL_SCHEMAS` tuple (the order `_run_agent_impl` sends) | agent model (FACT, COMPARE, SEARCH also go to MCP) |
| `prompts/agent_messages.py` | every fixed string and template the agent model reads besides the above (list below) | agent model (refusal texts also reach the judge) |
| `prompts/judge.py` | `JUDGE_SYSTEM_PROMPT`, `JUDGE_USER_TEMPLATE` | judge model |
| `prompts/mcp.py` | the MCP error strings; later `MCP_SEARCH_TOOL_SCHEMA` (Step 3a) | MCP clients |

**Conventions:**
- **Templates** are named format strings, filled in at the call site with
  `.format(...)`. Pass *computed* keyword arguments, such as `metric=args.get("metric")`
  or `n=len(all_results)`; don't put expressions in the template.
  - Where a message has conditional parts, each part gets its own constant, and the
    conditional logic stays in the calling function. Examples:
    - the `_calculation_as_result` expression variants and unit suffix (`agent.py:1187-1195`);
    - the hint joiner;
    - the warning-bullet format.
  - Never run `.format` on already-formatted text: answers, quotes, warnings and
    chunks can contain `{`. For example, pass `CITATION_RETRY_GUIDANCE` as a keyword
    argument rather than concatenating it into a template.
- **SYSTEM_PROMPT and the schemas stay import-time f-strings.** They use generator
  expressions over `COMPANIES` and the ratio lists.
- **Fingerprinted names:** each module declares an explicit `FINGERPRINTED` tuple
  of constant names, plus a commented `NOT_FINGERPRINTED` tuple for derived data
  such as the ratio lists.
- **Logic changes that alter model-visible text:** when template *selection* or
  dispatch logic changes what the model sees, the commit bumps
  `agent_messages.MESSAGES_VERSION`, which is fingerprinted. Steps 6a and 7 do this.
- **Carry this warning in `agent_messages.py`:** `verify_claims` splits calculated
  text on the first `"="` (`agent.py:2001`), so a calculation-result template must
  not gain an `=` or a number before the result.
- **Names** are public (no leading underscore), since other modules import them.
- **Docstring** for each module: "static model-facing text for <consumer>". Data,
  logic and user-only output don't belong there.
- **Stays out:**
  - dynamic data: chunk text, the user question, the echoed answer, values;
  - `log_event` reasons, `--verbose` prints and exception messages;
  - the CLI citation key;
  - the unit literals from `xbrl_facts`/`formulas`, which are data values;
  - the offline chunk-table shaping in `chunk_documents.py`;
  - `retrieval.QUERY_INSTRUCTION` (an embedding model, not an LLM);
  - the unused `period_labels.py` sentences;
  - the MCP HTTP transport bodies (`mcp_server.py:272`, `:284`);
  - `llm_backends.py`'s `{"result": content}` wrapper (`:383`) and `temperature=0.1`.
    These are request structure and configuration, not text. The git SHA covers them.
- **`COMPANIES`** (`agent.py:87-96`) is a data lookup that the logic also uses.
  It moves to `companies.py` as a module-level constant, imported by `prompts/`
  and `agent.py`.
- **Warnings travel with their text.** Rationale comments move with each constant.
  - The do-not-change constraints written on the formatter docstrings are copied
    into self-contained comments next to `CITATION_RETRY_GUIDANCE` and
    `FINAL_TURN_SUBMIT_MESSAGE`. The source is `agent.py:2115-2130`: no
    deadline or final-attempt language, an honest refusal is acceptable, never
    estimate.
  - "Above"/"below" cross-references become `agent.<function>` names.

**`agent_messages.py` inventory** (surveyed 2026-09-24; each item also appears
as a row in the saved review's inventory table):
- **Result formats:**
  - `_citation_header` format (`agent.py:484`)
  - `_format_results_block` separators (`:499-500`)
  - no-results text (`:493`)
  - fact and comparison result formats (`:871`, `:956-959`)
  - calculation result: its expression variants, unit suffix and header
    (`:1187-1208`)
- **No-data messages:**
  - `Q4_NOT_DISCLOSED_HINT` (`:503`)
  - `_never_tagged_hint` body (`:530`)
  - no-fact and no-comparison templates (`:548`, `:569`)
- **Calculate and grounding errors:**
  - `_ground_operand` messages (`:1021`, `:1038`, `:1049`, `:1055`)
  - calculate errors (`:1096`, `:1113`, `:1118`)
- **Search errors:** invalid ticker and invalid arguments (`:2443`, `:2446`)
- **Retry and final-turn messages:**
  - `CITATION_RETRY_GUIDANCE` (`:2098`)
  - both retry-message templates (`:2132`, `:2152`)
  - `FORCE_SUBMIT_MESSAGE` (`:2194`)
  - `FINAL_TURN_SUBMIT_MESSAGE` (`:2211`)
  - mixed-turn resubmit (`:2735`)
- **CitationWarning message templates:** 11, at `:1635`, `:1651`, `:1808`, `:1817`,
  `:1856`, `:1865`, `:1877`, `:1906`, `:1915`, `:2030` and `:2610`.
- **Refusal texts:** `_format_refusal_message` (`:2162`) and the budget-exhausted
  answer (`:2763`). The judge reads both.

#### Commit 1a: system prompt and schemas → `agent_system.py`, `agent_tools.py`
- **Before editing:** a one-off snippet prints the sha256 of `SYSTEM_PROMPT` and of
  `json.dumps([FACT, COMPARE, SEARCH, CALCULATE, SUBMIT], ensure_ascii=False)`.
  There's no `sort_keys`: key order is what Gemini receives. **After moving:** the
  same snippet, with an old-name → new-name mapping, must print identical hashes.
- **Tool list:** hoist `_run_agent_impl`'s inline list (`agent.py:2831-2833`) into
  `AGENT_TOOL_SCHEMAS`. This is safe because `_to_gemini_tool` copies each schema
  instead of changing it (`llm_backends.py:236-281`).
- **New test:** a capturing `fake_start` asserts `system_prompt is SYSTEM_PROMPT`
  and `tool_schemas == list(AGENT_TOOL_SCHEMAS)`. Today nothing checks what
  `_run_agent_impl` sends.
- **Imports:**
  - `agent.py` imports `COMPANIES` from `companies` and drops `load_companies`.
    It keeps `RATIO_DEFINITIONS` and `DEFAULT_METRIC_TAGS` for its logic.
  - Don't import `CROSS_COMPANY_RATIOS` into `agent.py`: at `:894` it's only named
    in a docstring, so just rename it there.
  - `mcp_server.py:26` imports the schemas from `prompts.agent_tools` and keeps
    `CHUNKS_PER_SEARCH` from `agent`.
  - Update `tests/test_agent.py:19-26` and `tests/manual/verify_submit_answer.py`.
- **ruff exception:** move the `# ruff: noqa: E501` block (`agent.py:15-25`) into
  `agent_system.py` and `agent_tools.py`, which are the only modules with long
  lines. Review confirmed that all 24 E501 hits are inside the moved block.
- **Rule files:** add `prompts/**` to the `paths:` of
  `.claude/rules/live-eval-verification.md` and `.claude/rules/plan-review-blast-radius.md`.
  Otherwise later prompt edits lose the live-check rule, escalated review, and the
  90% coverage bar.
- **Import graph:** `prompts/` imports only `companies`, `formulas` and
  `xbrl_facts`. None of these imports `agent`, so there's no cycle. The only
  import-time effect is `config`'s `load_dotenv`, which `agent` already triggers
  today. Nothing touches the network or Chroma.

#### Commit 1b: agent messages → `agent_messages.py`
- **Before editing, record golden output.**
  - **How:** a scratch pytest file in the scratchpad, not in the repo. Pytest makes
    `conftest.py:23` disable the trace log, so `traces.jsonl` stays clean for Steps
    4–5's counts. The file writes a UTF-8 JSON file of rendered strings.
  - **Stable across the move:** it calls agent.py's function names, which don't
    change, so the same file runs before and after.
  - **What it calls:**
    - `_citation_header` and `_format_results_block`
    - `_fact_as_result`, `_comparison_as_results`, and `_calculation_as_result` (every variant)
    - `_ground_operand`, with `all_results` built so each of its 4 branches fires
    - `call_calculate`: the category-mismatch and divide-by-zero cases
    - `collect_citation_warnings` / `verify_claims`, covering each warning check
    - both retry formatters, with `{` inside the answer and the quote
    - `_format_refusal_message` and `_finalize_after_budget_exhausted`
    - both no-data formatters, in both Q4 and never-tagged branches, with
      `agent.is_metric_tagged` monkeypatched (the never-tagged branch otherwise calls SEC)
    - the judge: monkeypatch `eval_harness.complete` to capture `(system, user)`,
      and freeze the date
  - **Plain literals embedded in loop or ASGI code:**
    - agent.py `:2610`, `:2735` and `:1096`
    - the force-submit and final-turn messages
    - the MCP strings

    For these, compare the old literal with the new constant by value.
  - After the move, the output must be identical.
- **Existing message tests:** their assertions stay unchanged, but their imports
  change to `prompts.agent_messages` (`tests/test_agent.py:25-26`, `:594`) because
  the names become public. The old private imports would fail collection.
- **`_format_no_fact_message` moves unchanged**, including its "None FYNone" bug.
  The fix is finding 11, in Phase 2, so the fix gets screened.

#### Commit 1c: judge and MCP text → `judge.py`, `mcp.py`
- Move `JUDGE_SYSTEM_PROMPT` (`eval_harness.py:120`), and extract the user prompt
  (`:148-154`) as `JUDGE_USER_TEMPLATE`.
- Move the MCP strings: `mcp_server.py:142`, `:152`, `:186`, and the HTTP error
  bodies at `:272` and `:284`.
- Check with the same golden-output method. `tests/test_eval_harness.py:347-348`
  (the "Today's real date" line and "training cutoff") must stay green.

#### Commit 1d: instrumentation and compare tooling (TDD)
- **`prompts/__init__.py`: fingerprints.** `prompt_fingerprint() -> dict` returns
  `{"agent_system", "agent_tools", "agent_messages", "judge", "mcp", "agent"}`.
  - Each surface hash is sha256[:12] of
    `json.dumps([getattr(m, n) for n in m.FINGERPRINTED], ensure_ascii=False, allow_nan=False)`,
    with no `default=`.
    - Hashing values rather than source means comment-only edits don't change it.
    - A non-JSON value fails the tests loudly instead of hashing its `repr`, which
      would depend on the hash seed.
    - Imported data (`DEFAULT_METRIC_TAGS`' GAAP tags, the `RATIO_DEFINITIONS`
      objects) is counted only where rendered into text, so an XBRL tag fix doesn't
      change the prompt fingerprint.
  - `_collect_provenance` wraps the fingerprint call as well as git. On an unexpected
    error it records `"prompts": "error"` and logs it; it never raises.
  - `agent` combines agent_system, agent_tools and agent_messages. It's the
    grouping key for agent-prompt comparisons.
  - A `companies.json` or `RATIO_DEFINITIONS` edit changes the fingerprint. That's
    intended, because the model sees different text.
- **`eval_harness.py`:**
  - **`_collect_provenance()`** runs at the start of `main()`. That's before any
    quota is spent, and it fixes the SHA at run start. The result is passed to
    `save_report(..., provenance=...)` and stored as `"provenance"`:
    `{git_sha, git_dirty, dirty_files, prompts: prompt_fingerprint()}`.
  - **The git part** follows `scripts/check_docs_health.py:116-123`: check
    `returncode` and decode as UTF-8.
    - `git rev-parse --short HEAD`
    - `git status --porcelain --untracked-files=no -- *.py prompts companies.json eval/eval_questions.jsonl`
    - On a failure, set `git_sha: "unknown"` and call
      `log_event("eval_provenance_git_failed", ...)`. It never raises.
  - **`grade_judged`** keeps its `(passed, reason)` return shape and its parsing.
    When the first line isn't exactly `PASS`/`FAIL`, it computes a lenient
    `\b(PASS|FAIL)\b` verdict and prefixes the reason with
    `[nonstandard judge output; lenient parse disagrees: …]` or
    `[nonstandard judge output: …]`, plus a `log_event`. Only "disagrees" counts as
    evidence for finding 7.
- **`analyze_flakiness.py`:**
  - Add `load_reports(paths)`, which returns whole reports and handles the legacy
    list format. `load_rows` uses it.
  - Update the out-of-date "no commit/version field" notes (`:190-192`, `:357-358`).
- **New `compare_prompt_versions.py`** (repo root):
  - **Loading:**
    - Uses `load_reports` and `is_infra_error`.
    - Drops rows from a report's first infra-error row onward.
    - Skips unstamped reports in fingerprint mode.
    - Excludes dirty reports unless `--include-dirty` is given.
  - **Fingerprint mode** (the default) groups by `provenance.prompts.agent`.
    - Base and candidate default to the two most recent fingerprints;
      `--base/--candidate` override them.
    - It warns when a group covers more than one SHA.
  - **Explicit mode:** `--base-files` / `--candidate-files`.
  - **Output:**
    - It always prints each group's fingerprint, SHA(s), `answer_model` and
      report count.
    - Per question: base k/n, candidate k/n, withheld-answer counts, and a flag:
      - **REGRESSED:** a pass-rate drop of 0.5 or more;
      - **watch:** any smaller drop;
      - **improved:** any rise;
      - **floor:** a base rate of 1/3 or less.
    - A panel-total line, flagged **REGRESSED-TOTAL** when the candidate has at
      least `ceil(0.14 × runs)` fewer passes.
    - A loud warning when the judge fingerprint or `answer_model` differ.
  - **Exit code** 1 on any REGRESSED. The core is pure: `compare()` plus
    `format_comparison()`.
- **Tests, written first:**
  - **new `tests/test_prompts.py`:**
    - fingerprints are deterministic, including across two subprocesses with
      different `PYTHONHASHSEED` values;
    - each surface's hash changes when its text changes and only then;
    - an `ast` check that every top-level uppercase assignment in `prompts/*.py`
      (not an import) is listed in `FINGERPRINTED` or `NOT_FINGERPRINTED`.
  - **new `tests/test_compare_prompt_versions.py`:**
    - grouping and defaults, and explicit mode;
    - skipping unstamped and dirty reports;
    - truncating at the first infra error;
    - every flag, including floor and the total flag;
    - the multi-SHA and judge/model warnings;
    - the exit code.
  - **`tests/test_eval_harness.py`:**
    - an autouse fixture stubs the git calls;
    - provenance is written;
    - a git failure gives "unknown" without raising;
    - the nonstandard flag: absent for `PASS\n…`, plain for `PASS.`, "disagrees"
      for `**PASS**`.
  - **`tests/test_analyze_flakiness.py`:** `load_reports`.
- **`.claude/rules/live-eval-verification.md`:**
  - Fix the stale "41-question" to 48 (2 places).
  - Update the text saying `JUDGE_SYSTEM_PROMPT` lives in `eval_harness.py`, and do
    the same at `plan-review-blast-radius.md:52`.
  - Add a "Prompt changes" section: any `prompts/` change is its own commit, gets
    the panel protocol, and is checked with `compare_prompt_versions.py`.

#### Checks
- **For each commit:** `ruff check .`, `pyright .` and `pytest --cov`, plus that
  commit's hash or golden-output comparison. Record the comparison outputs for the
  decision file.
- **After 1d:** a live spot-check with `--ids aapl-ai-risk`. It's a judged question,
  and the report must contain `provenance`.
- **Review:** one `independent-review-pass` over 1a–1d before Step 2. Its
  escalated-scrutiny items:
  - no model-facing byte changed in 1a–1c;
  - no import cycle;
  - no message left behind (grep `agent.py` / `eval_harness.py` / `mcp_server.py`
    for remaining string literals passed to the model).

### Step 2 (WP2): Pin the model and run the baseline
1. **Pin the model.** A one-off `generate_content` call prints `resp.model_version`
   for `gemini-flash-lite-latest`. Set `GEMINI_MODEL_NAME=<version>` in `.env` for
   the whole rollout. If the API rejects the concrete name, keep the alias and rely
   on the same-day attribution step; note this.
2. **Run the PANEL 3×:** `python eval_harness.py --backend gemini --ids <PANEL>`.

**PANEL** (13 questions, about 195 requests per 3× run; paths checked against
`trace_logs/traces.jsonl`):

| Group | Questions |
|---|---|
| Canaries | `nvda-rd-expense-q4fy26-refusal` (Q4-hint and no-data path; follow-up searches), `nvda-crm-revenue-comparison` (`calculate`), `aapl-employees-fy25` |
| Narrative search (finding 2) | `aapl-ai-risk`, `pltr-government-contract-risk` (follow-up searches) |
| Segment (findings 2, 4) | `nvda-segment-revenue-comparison-q1fy27` (it replaces msft-segment, which failed its last 8 runs), `aapl-iphone-net-sales-q3fy2026` |
| Derived numbers (findings 3, 5) | `aapl-rd-pct-gross-profit-fy2025`, `aapl-cash-and-buyback-q3fy2026`, `nvda-revenue-two-quarter-comparison` |
| Ratio (findings 3, 5) | `msft-cash-to-assets-fy2025` (cash + total_assets + `calculate`) |
| Comparison (finding 3) | `aapl-msft-total-assets-comparison` |
| No-data / never-tagged (findings 11–13) | `pltr-inventory-turnover-fy2025-refusal` |

**Coverage gap:** no question exercises `compare_financial_metric`; it has had one
call since 2026-09-15. So finding 6 is untested, which is acceptable for deleting
one word.

**Expected false flags:** about a 30% chance per step, so budget for the
confirmation protocol.


## Files and steps: Phase 2: Audit rollout (Steps 3–9)

All edits land in `prompts/`. Line references to `agent.py` give the text's
*original* location, so find each string by its quoted content.

### Decision rule (every step)
B is the previous accepted fingerprint's runs, and C is the candidate.
1. **Screen.** Run the PANEL 3× on C, then `compare_prompt_versions.py`.
   - No REGRESSED and no REGRESSED-TOTAL: accept.
   - watch and floor flags are recorded but don't block.
2. **Replicate.** Let F be the flagged questions. Run F 3× more on C, and compare
   only the fresh runs against B (explicit mode).
   - Every question in F within one pass of B: it's noise. Accept, and record it as watch.
3. **Attribute, same day.** `git revert` the step's commit(s), run F 3×, and compare
   the reverted runs with the step-2 fresh runs.
   - The reverted runs are at least 0.5 better: **confirmed.** Keep the revert, record
     it, and file a `BACKLOG.md` item.
   - The reverted runs are as low as C: this is drift, not the prompt. `git revert`
     the revert, re-baseline the panel, and note it.
4. **Grouped steps** (3 and 6): step 3 reverts every model-affecting commit in the
   group together. If confirmed, bisect by re-applying one commit at a time (F 3×
   each).

Before each screen, run the manual checks and a light `independent-review-pass` on
the diff, so no quota is spent on a flawed edit.

### Step 3 (WP3): Group A, low-risk contract and wording fixes
- **3a: findings 1 and 2, MCP side.** No eval is needed, because Gemini's input is
  unchanged.
  - Add `prompts/mcp.py:MCP_SEARCH_TOOL_SCHEMA = copy.deepcopy(SEARCH_TOOL_SCHEMA)`
    with two new descriptions:
    - **Tool description:** "Search SEC 10-K/10-Q filing excerpts from the five covered companies. Returns the most relevant excerpts as a list of {text, source} objects, where source identifies the filing. Use it for narrative content (risk factors, MD&A, segment or product-line figures) and for any metric get_financial_fact doesn't cover. Pass ticker to restrict the search to one company. It returns filing text only, not structured XBRL values."
    - **`query` description:** "What to search for, as a natural-language question or phrase."
  - `mcp_server._TOOL_SCHEMAS` (`:166`) uses it for list_tools only. Validation keeps
    `SEARCH_TOOL_SCHEMA`.
  - Tests:
    - the listed `query` description doesn't mention "original question";
    - `SEARCH_TOOL_SCHEMA` is unchanged;
    - the parameters are equal apart from the `query` description.
- **3b: finding 6.** Change "version exists yet; use get_financial_fact per company instead.)" to "version exists; use get_financial_fact per company instead.)" (COMPARE metric description, originally `agent.py:245-246`).
- **3c: finding 2, agent side.** Replace the one-sentence SEARCH description (originally `agent.py:125`) with:
  ```python
  "description": (
      "Search SEC 10-K/10-Q filing excerpts from the five covered companies. Returns the most "
      "relevant excerpts, each headed with a citation number, ticker, "
      "form type and report date. Use it for narrative content (risk factors, MD&A, segment or "
      "product-line figures) and for any metric get_financial_fact doesn't cover or returns as "
      "not available. It returns filing text only, not structured XBRL values."
  ),
  ```
  - There's no result count (`CHUNKS_PER_SEARCH` lives in `agent`).
  - "Omitted, it searches all five" is left out, because it clashes with the ticker
    description's "Omit only if genuinely unsure".
  - If Step 6 changes the no-data wording, align "returns as not available" to match
    in that step.
- **3d: finding 5.** In the CALCULATE description (originally `agent.py:393-395`),
  change `"...or a registered ratio metric " "via compare_financial_metric) -- use calculate..."`
  to `"...or a registered ratio metric) " "-- use calculate..."`.
- **Bisect order, if flagged:** 3c, then 3d, then 3b.

### Step 4 (WP4): Finding 3, the rule 3 / rule 9 contradiction
- **Rule 3:** replace it with: "3. Every number you state must come from a tool result — either stated there directly, or restated in a different unit per rule 9. When you need a number derived from others (a total, difference, ratio, or percentage change), get it from `calculate` rather than working it out yourself — its output, like `get_financial_fact`'s, is a single citable value."
- **Rule 9:** change "If you need to combine, compare, or derive a number from values you've already seen (a difference, a ratio, a percentage change) despite rule 3 telling you not to work this out yourself -- call `calculate` FIRST and cite ITS result the same way as any other;" to "If you need to combine, compare, or derive a number from values you've already seen, call `calculate` first and cite its result the same way as any other;".
- **Trace check, no cost:** count `calculate` calls whose `operand_b` is a power of
  1000 (unit-conversion attempts), before vs after.

### Step 5 (WP5): Finding 4, the segment-rule emphasis
- **Why test it on Gemini:** commit `6f3a8ee` showed this emphasis had no effect,
  but on Ollama qwen. It was kept "for more instruction-following models", meaning
  Gemini.
- **Edit:** change "If a question asks about a specific segment or product line, do NOT call this tool at all, not even to try — go straight to `search_filings` instead." to "For a question about a specific segment or product line, use `search_filings` instead."
  - Keep the adjacent contract facts.
- **Trace check:** count `get_financial_fact` calls on the two segment questions,
  before vs after. Today there are none.

### Step 6 (WP6): Group B, findings 11 and 12, the no-data message and its description (2 commits)

- **6a: finding 11, rendering the period.** `_format_no_fact_message`
  (originally `agent.py:548-551`) renders the period wrongly in three cases:
  - "None FYNone" when the request uses `period_end_date` or a multi-year range;
  - "None FY2025" when `fiscal_year` is given without `fiscal_period`, although the
    lookup defaults to FY (`agent.py:782`);
  - "None FYNone" when no period is given, although `get_metric` returns the latest
    entry (`xbrl_facts.py:339-340`).

  **Fix:** choose the template in the same order as `call_get_financial_fact`'s
  branches. There's one constant per form in `agent_messages.py`, and the selection
  stays in `agent.py`:
  1. multi-year: `FY{start}–FY{end} average`, including a partial range;
  2. `period_end_date`: "period ending {date}". It wins over `fiscal_year`, matching
     `get_metric` at `:337`;
  3. `fiscal_year`/`fiscal_period`: FY by default;
  4. otherwise, "latest available".

  **Details:**
  - Keep `!r` on the year, so a malformed value stays visibly malformed.
  - Guard `_never_tagged_hint` against non-hashable ticker or metric values.
    `ticker not in COMPANIES` at `:522` raises `TypeError` on a list today.
  - Bump `MESSAGES_VERSION`.
  - TDD: unit tests for every argument shape first. `_format_no_comparison_message`
    has no such bug and stays as it is.
- **6b: finding 12, the "no data" wording.** The descriptions don't match what the
  model receives:

  | Where | Currently says |
  |---|---|
  | SYSTEM_PROMPT (originally `:102`, `:116`) | "not available" |
  | FACT schema (`:158`, `:194`) | "Returns null" |
  | agent loop (actual) | "(no structured data found … — try search_filings instead)" |
  | MCP clients, which also get the FACT schema (actual) | `{"error": "not available for …"}` |

  Use wording that is true on both surfaces, with no exact quotes, for example
  "…the tool reports that no data was found — fall back to `search_filings`".
  - Also align 3c's "returns as not available".
  - Leave the `:194` yoy-on-ratio sentence to Step 7, which edits it once.
- **Screen once for the group.** If it's flagged, bisect: 6a, then 6b.

### Step 7 (WP7): Finding 13, arguments that are rejected silently (1 commit, Standard, TDD)

**Evidence** (`trace_logs/traces.jsonl`): 234 `tool_call_rejected` events in total.
For `get_financial_fact`:
- 138 are `invalid_fiscal_year_type`: Gemini sent `"fiscal_year": "2025"` or
  `"2026"` every day from 09-11 to 09-22. 9 of them are on the
  `nvda-rd-expense-q4fy26-refusal` canary, and 17 on `inventory_turnover`.
- Only 2 are `unrecognized_extra_argument`: the segment cases that SYSTEM_PROMPT's
  "rejected outright" sentence is about.

Each rejection returns `None`, the model gets the generic no-data message, and it
falls back to `search_filings`, spending 2+ turns of `MAX_TOOL_ITERATIONS=6`.

**The fix:**
1. **Convert digit-only strings.** In `_rejects_invalid_fiscal_year`'s callers
   (`call_get_financial_fact`, `call_compare_financial_metric`), convert a
   `fiscal_year` that is a digit-only `str` to `int` before the check. Apply the
   same to `start_fiscal_year` / `end_fiscal_year` on the multi-year path
   (originally `:825`).
   - Work on a copy of `args`, never mutate the caller's dict.
   - `bool`, float, non-digit strings and other types stay rejected, with the
     existing reason.
   - Call `log_event("tool_arg_coerced", tool=..., field=..., value=...)` so the rate
     stays measurable.
   - The coercion code carries a short self-contained comment: this is the only
     string-to-integer conversion, because Gemini emits year strings despite the
     integer schema.
   - `mcp_server` benefits automatically, because it calls the same `call_*`
     functions.
2. **Fix the prompt wording.** SYSTEM_PROMPT's "an unrecognized argument is
   rejected outright" (originally `:102`) becomes "an unrecognized argument makes
   the call fail with the same no-data reply". Also, in the FACT schema's yoy
   sentence (`:194`), "returns null for that combination" becomes "…is rejected
   and reports no data".
3. Bump `MESSAGES_VERSION`.

**Tests, written first:**
- `"2026"` is accepted on both tools and on the multi-year fields;
- `True`, `"FY2026"`, `2026.0` and `[2026]` are still rejected;
- the caller's `args` are unchanged;
- the coercion event is logged.

Existing tests that assert `"2026"` is rejected are updated *deliberately*. List
them in the decision file as behaviour this change replaces, with this step as the
reason.

**Screening:**
- Watch in particular the two canaries that hit this path,
  `nvda-rd-expense-q4fy26-refusal` and `pltr-inventory-turnover-fy2025-refusal`.
  Their correct outcome is a refusal, and converting the year now lets the lookup
  run and return its real no-data plus Q4 or never-tagged reply.
- Trace check: count `invalid_fiscal_year_type` rejections and `tool_arg_coerced`
  events, before vs after.

**Not in this step** (added to BACKLOG in Step 9):
- reason-bearing rejection messages for the other rejection kinds (the
  `on_reject` callback design from review round 3);
- `calculate`'s 74 `missing_required_argument` rejections, which get the generic
  message at `:1096`;
- `mcp_server._search_filings` returning `[]` silently on invalid arguments.

### Step 8 (WP8): Final full run
- Run the full suite once: `python eval_harness.py --backend gemini` (48 questions,
  about 250 requests, on a fresh quota day).
- Compare it with the last two unstamped full runs using explicit mode
  (`20260921T222521Z.json` and `20260922T062823Z.json`). This gives a per-question
  diff for the non-panel questions. The working bar is 38–39/47.
- Grep the reports for `lenient parse disagrees`.
- Don't rely on `analyze_flakiness.py` for the panel questions: their windows now
  mix prompt versions.

### Step 9 (WP8, and each WP's own decision file): Documentation
- **Decision files:**
  - Each WP writes its own decision file with its row: the move checks (hash and
    golden-output results) for WP1, and for later WPs the commit SHA, fingerprint,
    pinned model, panel B vs C, outcome (accepted, replicated or reverted), watch
    flags and trace-check counts.
  - WP8 writes a summary decision file (`docs/decisions/<date>-prompt-audit-rollout.md`)
    that collects every WP's row into one table and links each WP's file.
- **`BACKLOG.md`:**
  - (a) Finding 7, deferred. Trigger: `lenient parse disagrees` appears in a report.
  - (b) One Low item for notes 8–10, revisited only with eval budget: the all-caps
    emphasis density, the tool bullets duplicating the descriptions, and rule 9's
    size. Also the cross-surface duplicate sentences the survey listed, and the
    hardcoded "five companies".
  - (c) Any confirmed-and-reverted finding.
  - (d) The baseline-improvement plan, as the next piece of work.
  - (e) The Step 7 follow-ups: reason-bearing rejection messages via an `on_reject`
    callback; `calculate`'s generic missing-argument message; MCP search's silent `[]`.
  - (f) Rewrite the existing `msft-cash-to-assets-fy2025` item to drop clause (a),
    which WP7 fixes. (The roadmap-creation commit added the addendum scheduling it.)
- **`PROJECT_INDEX.md`:** add Recent lines.
- **Model pin:** unpin `GEMINI_MODEL_NAME`, or record keeping the pin as a decision.

## Scope / Out of scope
- The finding 7 code change (evidence-gated).
- Ollama/qwen checks.
- Re-stamping the 130 historical reports.
- Improving the baseline pass rate (the next plan).

## Critical files
- **New `prompts/`:** `__init__`, `agent_system`, `agent_tools`, `agent_messages`, `judge`, `mcp`.
- **`agent.py`:** text removed, formatters and dispatchers call the constants; later, Steps 6a and 7.
- **`eval_harness.py`:** judge text moved; `main`, `save_report`, `grade_judged`.
- **`mcp_server.py`:** imports, error strings, `_TOOL_SCHEMAS`, and the rejection mapping.
- **`companies.py`:** `COMPANIES`.
- **`analyze_flakiness.py`** and the new **`compare_prompt_versions.py`**.
- **Tests:**
  - new: `tests/test_prompts.py`, `tests/test_compare_prompt_versions.py`
  - updated: `tests/test_agent.py`, `tests/test_eval_harness.py`,
    `tests/test_mcp_server.py`, `tests/test_analyze_flakiness.py`,
    `tests/manual/verify_submit_answer.py`
- **`.claude/rules/live-eval-verification.md`** and **`plan-review-blast-radius.md`**.

## Testing and verification
- **Commits 1a–1c:** identical hashes and golden-rendered outputs before and after;
  the full suite, ruff and pyright are clean; no eval quota is spent.
- **Commit 1d:**
  - the new tests pass, with at least 90% diff coverage on critical-core files;
  - a live judged question yields a report with `provenance`;
  - the compare script lists it.
- **Steps 3–7:** each step's compare output, decision outcome and trace counts are
  recorded in the decision file.
- **Step 8:** the full-suite pass count is at or above the working bar, and no
  non-panel question drops from its historical pass without an explanation.
