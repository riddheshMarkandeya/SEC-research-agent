# WP3: Group A wording fixes (audit findings 1, 2, 5, 6)

## Context
WP3 of `docs/plans/2026-09-24-prompt-audit-roadmap.md`: **Step 3**, the first prompt change
screened under the roadmap's Decision rule, using WP2's tooling. It fixes four findings from
`docs/reviews/2026-09-24-prompt-audit.md`:

| # | Problem | Fix |
|---|---|---|
| 1 | MCP clients read a `query` description ("the first search against each company always uses the user's original question") that is false for them: `mcp_server._search_filings` passes `query` straight to `hybrid_search` | MCP-only search schema |
| 2 | The `search_filings` description is one sentence: no return shape, no when-to-use. MCP clients see nothing else | new descriptions, separate for MCP and agent |
| 5 | The calculate description says ratios are available "via compare_financial_metric", but single-company-only ratios exist only on `get_financial_fact` | drop the phrase |
| 6 | "no cross-company version exists yet" (migration-relative) | drop "yet" |

**Tier:** Standard. Edits are in `prompts/` (critical-core) and `mcp_server.py`.

## Repo state (2026-09-24, HEAD `01ba453`, clean tree, 917 passed)
- **Baseline B:** agent fingerprint `cc984387c3e8`, SHA `2c3dbdd`, model
  `gemini-3.5-flash-lite` (pinned in `.env`).
  - Reports: `20260925T001138Z`, `001514Z`, `001931Z`. Panel total 37/39.
  - The `aapl-ai-risk` spot-check (`20260924T215337Z`) shares that fingerprint, so screens
    use `--since 20260925T000000Z`.
- **Text locations (verified):** `prompts/agent_tools.py`:
  - `SEARCH_TOOL_SCHEMA` (`:22`): description `:26`, `query` description `:32`;
  - COMPARE metric description, "version exists yet" (`:146-147`);
  - CALCULATE description, "via compare_financial_metric" (`:277-278`).
- **Verified facts the new text relies on:**
  - `agent._resolve_search_args` (`agent.py:79-82`) uses the original question for the
    first search per ticker, so the agent's `query` description stays as it is.
  - Agent results are headed `[i] TICKER FORM (reportDate=…)`
    (`agent_messages.CITATION_HEADER_TEMPLATE`).
  - MCP returns `[{text, source}]` (`mcp_server.py:129`), and `source` is ticker, form,
    reportDate, filingDate, accessionNumber and optional sec_url.
  - Both surfaces search all five companies when `ticker` is omitted, and
    `companies.json` has 5.
  - On no data the agent receives `NO_FACT_TEMPLATE`, "(no structured data found … —
    try search_filings instead)", not "not available".
- **MCP:**
  - `_TOOL_SCHEMAS` (`mcp_server.py:165`) holds SEARCH, FACT and COMPARE, and feeds
    `_handle_list_tools`;
  - `_search_filings` validates against `SEARCH_TOOL_SCHEMA` (`:121`).
- **Snapshot:** `_render_mcp` records `mcp_list_tools`. Effects by commit:
  - 3a changes only the `mcp` section and fingerprint;
  - 3b changes both `agent` and `mcp`, because MCP lists COMPARE;
  - 3c and 3d change `agent` only.
- **Imports:** there's no cycle if `prompts/mcp.py` imports `prompts/agent_tools.py`.
- **Tests:** `tests/test_mcp_server.py` exists. Its `:357` test checks only tool names.

## Changes vs. the roadmap
- **3c wording (revisiting the roadmap's text).** The roadmap wrote "doesn't cover or
  returns as not available", but that isn't what the agent receives (see above). Use
  "doesn't cover or finds no data for", which is true on every surface and won't need
  re-aligning in WP6.
- **MCP validation uses the listed schema.** `_search_filings` validates against
  `MCP_SEARCH_TOOL_SCHEMA`. `validate_tool_args` ignores descriptions, so behaviour is
  identical, and the schema clients see can never drift from the one they're checked
  against.

## Steps (one commit per change, per the live-eval rule's "Prompt changes" section)
Every commit runs the manual checks and regenerates `prompts/model_input_snapshot.json`
(`UPDATE_SNAPSHOT=1`) after reading its diff. The snapshot test is the red step for a
wording change.

0. **Save** this plan to `docs/plans/2026-09-24-wp3-group-a-wording.md`, and the plan review below to
   `docs/reviews/2026-09-24-wp3-group-a-wording-plan-review.md`. Keep both unstaged until
   the docs commit, with their index lines added then.
1. **3a: MCP search schema (TDD).** Findings 1 and 2, MCP side. No eval: Gemini's input
   doesn't change.
   - **Tests first** (`tests/test_mcp_server.py`):
     - the listed `search_filings` tool equals `MCP_SEARCH_TOOL_SCHEMA`'s name,
       description and parameters;
     - its `query` description doesn't mention "original question";
     - `MCP_SEARCH_TOOL_SCHEMA["function"]["parameters"]` equals `SEARCH_TOOL_SCHEMA`'s
       except `query.description`. This is the lasting guard;
     - `_search_filings` still rejects an unknown argument.
   - **Code:**
     - `prompts/mcp.py`: build `MCP_SEARCH_TOOL_SCHEMA` from `SEARCH_TOOL_SCHEMA` with
       `{**…}` overrides (no import-time mutation, key order kept). It gets the roadmap's
       tool description (**{text, source}** shape, when to use it, pass `ticker`, filing
       text only) and `query` description "What to search for, as a natural-language
       question or phrase."
     - Add it to mcp's `FINGERPRINTED`, and update the module docstring.
     - `mcp_server.py`: `_TOOL_SCHEMAS` lists it, and `_search_filings` validates against
       it. Update the module docstring (`:3-4`) and `_search_filings`' docstring.
     - Update the `agent_tools.py` module docstring (`:3-4`): FACT and COMPARE are listed
       to MCP clients, and SEARCH via its MCP variant. Docstrings aren't hashed.
     - `verify_mcp_server.py`: expect `MCP_SEARCH_TOOL_SCHEMA`, and fix the print at
       `:161`.
   - **One-off check, not a committed test:** `prompt_fingerprint()["agent"]` is still
     `cc984387c3e8`, and `mcp` has changed.
2. **3b: finding 6.** "version exists yet; use…" → "version exists; use…" (COMPARE metric
   description). The snapshot diff shows both the `agent` and `mcp` sections.
3. **3c: finding 2, agent side.** Replace the SEARCH description with:
   "Search SEC 10-K/10-Q filing excerpts from the five covered companies. Returns the most
   relevant excerpts, each headed with a citation number, ticker, form type and report
   date. Use it for narrative content (risk factors, MD&A, segment or product-line
   figures) and for any metric get_financial_fact doesn't cover or finds no data for. It
   returns filing text only, not structured XBRL values."
4. **3d: finding 5.** In CALCULATE: `"...or a registered ratio metric " "via
   compare_financial_metric) -- use calculate..."` → `"...or a registered ratio metric) "
   "-- use calculate..."`.
5. **Implementation → review boundary:** give the `/compact` line (CLAUDE.md trial).
6. **`independent-review-pass`** over the 4 commits (all five passes, low to medium
   effort), before any quota is spent. That's the roadmap's "light review before each
   screen". Commit fixes, regenerating the snapshot if the text changes.
7. **Live, no quota:** `python tests/manual/verify_mcp_server.py`. Everything passes.
8. **Screen (Decision rule step 1).** Start only if at least about 250 of the day's Gemini
   quota remain; the day resets at midnight Pacific.
   - **Cost:** about 150–160 requests. The WP2 baseline traces show 39 runs with 150 tool
     calls, plus judge calls on the same model.
   - On a clean tree at the final HEAD (C):
     - run the panel 3×;
     - run `python compare_prompt_versions.py --base cc984387c3e8 --since 20260925T000000Z`;
     - **no REGRESSED and no REGRESSED-TOTAL: accept.** watch and floor flags are
       recorded.
9. **Only if flagged** (about 15 requests per flagged question per step):
   - **Replicate:** run F 3× more, then explicit mode against B's three files.
   - **Attribute, same day:** revert every agent-text commit together (3b–3d plus any
     review-fix commit that touched agent text), run F 3×, and compare with explicit mode.
   - **If confirmed,** bisect in the order 3c, 3d, 3b (F 3× each). The bisect probably
     won't fit the same quota day, so it may move to the next day with a re-baseline.
   - 3a is never reverted: it's MCP-only.
10. **Docs:**
    - decision file `docs/decisions/<date>-wp3-group-a-wording.md`: the new `agent` and
      `mcp` fingerprints, per-question k/3 against B, the verdict and flags, the measured
      request count, and the two changes from the roadmap;
    - the code review in `docs/reviews/`;
    - delete the WP3 `BACKLOG.md` line, and add a Low item: the MCP `ticker` description
      is agent-flavoured ("…which company the question is about");
    - `PROJECT_INDEX.md`: 4 Recent lines (plan, plan review, code review, decision;
      44 → 48, under the 50 cap);
    - commit the live reports and the docs, and don't push.

**Commits:** approving this plan authorises commits 3a–3d, the review-fix commit(s), a
revert and bisect only as the Decision rule prescribes, the reports commit and the docs
commit. The screen spends about 150–160 Gemini requests, plus more only if something is
flagged.

## Plan review (1 independent round, 2026-09-24; source for the step-0 review file)
- **Must-fix, adopted:**
  - no committed tests pinning the agent fingerprint or "`SEARCH_TOOL_SCHEMA` unchanged",
    since 3c changes both on purpose. It's a one-off check instead, and the
    equal-parameters test is the lasting guard;
  - save the plan and the plan review (step 0), with index lines.
- **Should-fix, adopted:**
  - "finds no data for" instead of "returns as not available";
  - 3b also changes the `mcp` section;
  - the stale docstrings (`agent_tools.py:3-4`, `mcp_server.py:3-4`) and the
    `verify_mcp_server` print;
  - validate MCP search against the listed schema;
  - a measured request estimate of about 150–160, with the note that a bisect may not
    fit the same quota day;
  - the attribute revert includes review-fix commits that touch agent text.
- **Nits, adopted:**
  - the existing test module named;
  - `{**…}` instead of mutating a deepcopy;
  - the `/compact` boundary;
  - a BACKLOG item for the MCP ticker description.
- **Confirmed:**
  - every factual claim in the new descriptions;
  - no import cycle;
  - enum and `additionalProperties` preserved;
  - 3a changes only `mcp`;
  - the classification test is satisfied by adding to `FINGERPRINTED`;
  - the compare command (`--since` excludes the spot-check; `default_pair` picks the
    later fingerprint);
  - the grouping and bisect order match the roadmap.

## Out of scope
- The system prompt's `search_filings` bullet and the other duplications (finding 9),
  rule 3 / rule 9 (WP4), and the no-data wording (WP6).
- The ticker description on either surface (BACKLOG item only).

## Critical files
- `prompts/agent_tools.py` (3b–3d, and the docstring)
- `prompts/mcp.py` (3a)
- `mcp_server.py`
- `prompts/model_input_snapshot.json`
- `tests/test_mcp_server.py`
- `tests/manual/verify_mcp_server.py`
- **Reuse:**
  - `prompts.prompt_fingerprint`;
  - `compare_prompt_versions.py`;
  - `tests/test_model_input_snapshot.py`;
  - `validate_tool_args`.

## Verification
- **Each commit:**
  - `ruff check .`, `pyright .` and `pytest --cov=. --cov-report=term-missing -q` are
    clean;
  - the snapshot diff shows only the intended text;
  - diff-cover is at least 90% on `prompts/` and at least 80% elsewhere.
- **After 3a:** `agent` is still `cc984387c3e8`, and `mcp` has changed.
- **Live:** `verify_mcp_server.py` passes. The panel screen's compare output and verdict
  are recorded.
