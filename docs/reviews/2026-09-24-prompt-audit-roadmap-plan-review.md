# Review: prompt-audit roadmap plan (three independent plan-review rounds)

Plan: `docs/plans/2026-09-24-prompt-audit-roadmap.md`. This review covers the plan
only; no code had been written. Each round was a freshly spawned Plan subagent,
given no memory of the planning session. It read the plan draft against the real
code and `trace_logs/traces.jsonl`.

## Round 1: the whole rollout (instrumentation, compare script, panel, the prompt edits)

**Must-fix, all adopted:**
- **M1.** The proposed `search_filings` description ("each headed with a citation
  number…") would have been false for MCP clients, who get `{text, source}` JSON
  (`mcp_server.py:130`). That's the same kind of bug as finding 1.
  **[Fixed]** Separate descriptions for the agent and MCP sides (WP3, 3a and 3c).
- **M2.** The proposed rule 3 ("Every number you state must appear directly in a
  tool result") would have contradicted rule 9's allowance to restate a value in
  another unit. The likely outcome was unit-conversion `calculate` calls that can
  never succeed, eating the 6-turn budget.
  **[Fixed]** The new rule 3 keeps the restatement allowance (WP4).
- **M3.** The revert-confirmation rule was biased: it compared reverted runs against
  the same low runs that raised the flag, so regression to the mean would usually
  "confirm" it. Also, a revert reproduces the base fingerprint, so the compare
  script's defaults couldn't pick out the reverted runs.
  **[Fixed]** A screen → replicate → attribute-same-day decision rule, plus an
  explicit-files mode in the compare script.

**Should-fix, adopted:**
- MCP-side description override, so the agent's input stays byte-identical.
- Git provenance checks `returncode`, runs at the start of `main()`, records the
  dirty-file list, and includes `companies.json` and the question file.
- Thresholds and panel:
  - a panel-total flag (a drop of 5 or more out of 36) and a floor marker;
  - `msft-segment-revenue-comparison-q3fy2026` replaced by
    `nvda-segment-revenue-comparison-q1fy27` (the former failed its last 8 runs, so
    it can't regress);
  - no panel question exercises `compare_financial_metric` (called once since
    09-15), recorded as a coverage gap.
- Finding 4's "no effect" evidence was on Ollama qwen, not Gemini.
- Pin the Gemini model version, because the `-latest` alias can move between days
  without any record.
- Truncate a report at its first infra error instead of excluding the whole report.
- Exclude dirty-tree reports by default, and warn when one fingerprint group spans
  several SHAs.
- The judge flag separates a harmless variant (`PASS.`) from a lenient-parse
  disagreement (`**PASS**`).

**Estimated noise, recorded in the plan:** about a 30% chance per step of at least
one false REGRESSED flag, based on the last 15 runs per question.

## Round 2: the single `prompts.py` module (later superseded by the package in round 3)

**No must-fix.**
- No import cycle, and no monkeypatch of a moved name.
- Removing the E501 exemption from `agent.py` surfaces zero new errors: all 24 hits
  are inside the moved block.

**Should-fix, all adopted:**
- Move every fixed message, not only the four named ones, so the fingerprint
  actually covers them.
- Add the new module to the `paths:` of `.claude/rules/live-eval-verification.md`
  and `plan-review-blast-radius.md`. Otherwise every later prompt edit would skip
  the live-check rule, escalated review and the 90% coverage bar.
- Keep the failure-mode warnings next to their constants:
  - no deadline language in the retry text;
  - an honest refusal is acceptable.
- Add a test pinning that `_run_agent_impl` sends `SYSTEM_PROMPT` and
  `AGENT_TOOL_SCHEMAS`.
- Correct the import list: don't import `CROSS_COMPANY_RATIOS`, since it's only
  named in a docstring, and drop the unused `load_companies`.
- No `sort_keys` in schema hashing, because key order is what Gemini receives.
- `COMPANIES` moves to `companies.py`.

## Round 3: moving all model-facing text (package, templates) and Steps 6–7

**Must-fix, all adopted:**
- **M1.** Step 7 targeted the wrong case. The traces show 138
  `invalid_fiscal_year_type` rejections (Gemini sends `"2026"`) against only 2
  extra-argument rejections.
  **[Fixed]** Step 7 now accepts digit-only year strings, after the user's decision
  to reopen the BACKLOG call. It also fixes the "rejected outright" wording.
- **M2.** A `Rejected(reason)` return type would have broken about 30 tests and
  crashed `mcp_server` (`:140`, `:150`).
  **[Fixed]** Dropped. The follow-up design (an `on_reject` callback) went to
  BACKLOG.
- **M3.** Hashing every uppercase name in a module would have included imported
  data. That includes GAAP tag names the model never sees, so XBRL fixes would
  have changed the prompt fingerprint.
  **[Fixed]** An explicit `FINGERPRINTED` tuple per module, an `ast` coverage test,
  and a hash-seed stability test.
- **M4.** Test imports of the renamed private constants would have failed at
  collection.
  **[Fixed]** Assertions unchanged, imports updated.
- **M5.** The proposed no-data wording for 6b would have been false for MCP
  clients, who get "not available for …".
  **[Fixed]** Wording that is true on both surfaces, with no exact quotes.

**Should-fix, adopted:**
- `.format` templates take computed keyword arguments, and formatted text (answers,
  quotes, warnings, chunks) is never formatted a second time.
- Golden output comes from a scratch pytest file, which keeps the trace log clean,
  with `is_metric_tagged` patched to avoid SEC calls.
- 6a covers four period forms, including the year-only and no-period cases the plan
  had missed, plus a guard against non-hashable ticker or metric values in
  `_never_tagged_hint`.
- A warning that `verify_claims` splits calculation text on the first `"="`.
- `MESSAGES_VERSION` gets bumped whenever template-selection logic changes what the
  model sees.

**Recorded as out of scope, sent to BACKLOG through WP8:**
- reason-bearing rejection messages;
- `calculate`'s 74 `missing_required_argument` rejections;
- MCP search's silent `[]`.

## Outcome

The plan was approved after all three rounds' must-fixes were folded in.

The user then chose to split it into a roadmap plus eight BACKLOG work packages
(WP1–WP8), each planned in its own session. Each WP plan still gets its own
review-floor pass, scoped to what changed since this roadmap.
