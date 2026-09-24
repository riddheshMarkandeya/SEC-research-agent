# Review: prompt-surface audit (`/claude-api prompt-audit`) and model-facing-text survey

Plan: `docs/plans/2026-09-24-prompt-audit-roadmap.md` (the roadmap that schedules
every actionable finding below as a BACKLOG work package, WP1–WP8).

## Scope / Method / Status

- **Scope:** every piece of text a model reads, whether the agent model, the eval
  judge or an MCP client. That includes:
  - the SYSTEM_PROMPT and the 5 tool schemas;
  - retry, nudge and final-turn messages;
  - tool-result and error text;
  - CitationWarning messages;
  - refusal texts, which the judge reads;
  - the judge's system and user prompts;
  - MCP tool descriptions and error strings;
  - request-building code in `llm_backends.py`.
- **Method:**
  - **Audit (2026-09-23):** the pattern tables from the `claude-api` skill's
    `prompt-audit` guide, covering dated prompt text, tool descriptions, request
    config, and provenance via `git log -S`.
  - **Survey (2026-09-24):** an Explore subagent traced each tool's result string
    from dispatch to `send_tool_results`.
  - **Evidence:** traces in `trace_logs/traces.jsonl` supplied it where available,
    including rejection counts and tool usage per question.
- **Target model:** the eval-gated default, Gemini `gemini-flash-lite-latest`.
  - Ollama `qwen2.5:7b-instruct` isn't checked (user decision).
  - The guide's rows that depend on Claude (API errors from prefill, `tool_choice`,
    `temperature` or `budget_tokens`, and Claude steerability claims) don't apply.
    Forced tool choice (`mode=ANY`) and `temperature=0.1` are valid on Gemini and
    are **not** findings.
  - Findings about loud wording carry lower confidence: small models may still
    need the emphasis.
- **Status:** nothing has been applied yet. Each actionable finding is scheduled as
  a WP in the roadmap. Finding 7 is deferred until evidence appears. Notes 8–10
  were logged in BACKLOG as notes, with no change proposed.

## Findings

Locations are as of commit `98b65f5`. WP1 moves all of this text into `prompts/`.

| # | Finding | Where | Pattern | Confidence | Action |
|---|---|---|---|---|---|
| 1 | The `search_filings` `query` description ("the first search against each company always uses the user's original question") is false for MCP clients: `mcp_server.py:125-128` passes `query` straight to `hybrid_search` | `agent.py:131` | description doesn't match behaviour | High | WP3 (MCP-side description override) |
| 2 | The `search_filings` description is one sentence: no return shape, no when-to-use. MCP clients see only this, never the system prompt's bullet | `agent.py:125` | under-described tool | High | WP3 (separate agent-side and MCP-side descriptions) |
| 3 | Rule 3 forbids combining numbers, but rule 9 says "despite rule 3 telling you not to work this out yourself -- call `calculate`". Rule 3 predates the `calculate` tool | `agent.py:113`, `:119` | contradiction / patch accretion | Medium | WP4 (the new rule 3 keeps rule 9's allowance to restate a value in another unit) |
| 4 | "do NOT call this tool at all, not even to try". Commit `6f3a8ee` found this emphasis had no effect in 3 live tests, but on Ollama qwen; it was kept for more instruction-following models, meaning Gemini | `agent.py:102` | pressure language | Medium | WP5 (plain wording, with a trace check on segment questions) |
| 5 | The calculate description says a ratio is available "via compare_financial_metric"; single-company-only ratios exist only on `get_financial_fact`. The system prompt at `:105` has it right | `agent.py:393-395` | duplicates disagree | Medium | WP3 |
| 6 | "no cross-company version exists yet" | `agent.py:245-246` | migration-relative phrasing | Medium | WP3 |
| 7 | The judge's pass/fail is parsed from a two-line format (`startswith("PASS")`), so `**PASS**` or a preamble would be graded FAIL. No malformed verdict has been observed | `eval_harness.py:125`, `:157-160` | format scaffold vs structured output | Medium | Deferred until evidence appears. WP2 adds a nonstandard-output flag; the structured-output change happens only if the flag shows a lenient-parse disagreement |
| 8 | About 20 all-caps emphasis words in SYSTEM_PROMPT | SYSTEM_PROMPT | pressure language | Low | BACKLOG note (WP8) |
| 9 | The system-prompt tool bullets duplicate the schema descriptions, and the same sentences repeat across surfaces (the calculate worked example 3×, unit-conversion guidance 4×, "the ONLY way to answer" 3×) | `agent.py:101-106` and schemas | duplication | Low | BACKLOG note (WP8). Only the pair that actually contradicts each other (finding 5) is fixed |
| 10 | Rule 9 is about 450 words, and every clause traces to a real failure | `agent.py:119` | patch accretion | Low | BACKLOG note (WP8). Restructuring needs eval budget |
| 11 | The no-data message renders "None FYNone" for `period_end_date`, multi-year or no-period requests, and "None FY2025" for a year without a period (reproduced) | `agent.py:548-551` | contract bug | High | WP6 |
| 12 | The prompt says "not available" and the schema says "Returns null". The agent loop actually sends "(no structured data found … — try search_filings instead)", and MCP sends `{"error": "not available for …"}` | `agent.py:102`, `:116`, `:158`, `:194` | description doesn't match behaviour | High | WP6 (wording true on both surfaces) |
| 13 | 138 live `invalid_fiscal_year_type` rejections (Gemini sends `"2026"`), 9 of them on the `nvda-rd-expense-q4fy26-refusal` canary. Each is rejected silently and gets the generic no-data message, so the model falls back to search and spends 2+ turns. The prompt's "rejected outright" claim covers only extra arguments, which were rejected just twice | `agent.py:600-613`, `:102` | contract bug | High (traces) | WP7 (accept digit-only strings; fix the wording) |

## Other survey observations (not findings)

These are recorded so they aren't rediscovered:
- **Refusal text reaches the judge.** `_format_refusal_message` and the
  budget-exhausted answer never reach the agent model, but the judge reads them on
  judged questions.
- **Rejection reasons don't reach the model.** Schema-rejection reasons
  (`_reason_for_error`, `invalid_fiscal_year_type`, …) go only to `log_event`. The
  model always gets the generic no-data message.
- **"Five" is hardcoded** in several prompt strings, while the company list comes
  from `companies.json`.
- **Unknown tool names fall through to search.** An unknown tool name silently goes
  to `search_filings` (`agent.py:2348`).
- **Similar rejections elsewhere:**
  - `calculate` has 74 live `missing_required_argument` rejections, all answered
    with one generic message (`agent.py:1096`);
  - MCP `search_filings` returns `[]` silently on invalid arguments.

  Both go to BACKLOG in WP8.

## Inventory summary of model-facing text

Roadmap Step 1 has the line-level list (package layout and `agent_messages.py`
inventory). In this table:
- **Fixed** means a literal string.
- **Template** means a literal with runtime values filled in.
- **Dynamic** means assembled from data (for example chunk text or the answer).

| File | Fixed | Template | Dynamic | Destination in `prompts/` |
|---|---|---|---|---|
| `agent.py` | 12: 3 schemas, 4 message constants, 4 inline tool-result strings, 1 warning | 29: SYSTEM_PROMPT, 2 schemas, 4 result formatters, 3 no-data/hint builders, 4 grounding errors, 2 calculate errors, 1 invalid-ticker message, 10 warnings, 2 retry messages | chunk text, the question, the echoed answer | `agent_system`, `agent_tools`, `agent_messages` |
| `eval_harness.py` | 1 (`JUDGE_SYSTEM_PROMPT`) | 1 (the judge user prompt) | question, criteria, answer | `judge` |
| `mcp_server.py` | 4 error strings (plus 2 HTTP bodies, which stay out as transport) | 1 (`Unknown tool`) | JSON results | `mcp` |
| `llm_backends.py` | the `{"result": …}` wrapper (structural) | — | — | stays out (the git SHA covers it) |
| `xbrl_facts.py`, `formulas.py` | unit literals (data) | — | values | stay out |
| `chunk_documents.py` | offline table shaping of the corpus | — | — | stays out |
| `retrieval.py` | `QUERY_INSTRUCTION` (embedding model, not an LLM) | — | — | stays out |

## Outcome

- **Plan:** 13 findings. 11 are scheduled across WP3–WP7, 1 is deferred until
  evidence appears (7), and 3 are BACKLOG notes (8–10).
- **Prerequisites:** WP1 (`prompts/` package) and WP2 (fingerprinted eval
  provenance plus `compare_prompt_versions.py`). They let every change be
  attributed to its own commit and reverted.
- **Records:** plan reviews are in
  `docs/reviews/2026-09-24-prompt-audit-roadmap-plan-review.md`. Each WP's result
  goes in its own decision file.
