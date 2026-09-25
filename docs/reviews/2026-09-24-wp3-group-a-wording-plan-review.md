# Review: WP3 plan, Group A wording fixes (one independent plan-review round)

Plan: `docs/plans/2026-09-24-wp3-group-a-wording.md`. The plan fixes prompt-audit
findings 1, 2, 5 and 6: an MCP-only `search_filings` schema, a fuller agent-side search
description, and two phrase fixes in the COMPARE and CALCULATE descriptions. It then
screens the change under the roadmap's Decision rule against the WP2 baseline. This
review covers the plan only, before implementation. The suite had 917 tests at HEAD
`01ba453`.

## Pass 1: self-check of the roadmap's Step 3 against HEAD `01ba453`

- [Verified] All three strings are where the plan says, in `prompts/agent_tools.py`
  (`:26`/`:32`, `:146-147`, `:277-278`).
- [Verified] The agent-side `query` description is true for the agent:
  `agent._resolve_search_args` uses the original question on the first search per
  ticker. It is false only for MCP, which passes `query` straight through.
- [Verified] The agent's results are headed `[i] TICKER FORM (reportDate=…)`, which
  matches 3c's description. MCP returns `[{text, source}]`.
- [Fixed in plan] `verify_mcp_server._check_model_facing_text` expects the listed tools
  to equal `prompts.agent_tools`' schemas. After 3a it has to expect the MCP variant.

## Round 1: independent subagent (the whole plan)

**Must-fix, adopted:**
- **Tests that would break later.** The draft committed tests pinning the agent
  fingerprint `cc984387c3e8` and asserting `SEARCH_TOOL_SCHEMA` unchanged, but 3c changes
  both on purpose. That check is now a one-off before committing 3a, and the lasting test
  is "the MCP and agent schemas' parameters are equal except `query.description`".
- **Docs step incomplete.** It listed only the decision and code review. The plan and the
  plan review are now saved in step 0, with index lines.

**Should-fix, adopted:**
- **3c wording.** The roadmap's "returns as not available" isn't what the agent receives
  on no data. It gets `NO_FACT_TEMPLATE`, "(no structured data found … — try
  search_filings instead)", and the FACT schema says "Returns null". The new wording is
  "doesn't cover or finds no data for", which is true on every surface. This revisits
  the roadmap's text on new evidence: the exact message the agent is sent.
- **3b's snapshot scope.** 3b also changes the snapshot's `mcp` section and the `mcp`
  fingerprint, because MCP lists `COMPARE_TOOL_SCHEMA`.
- **Stale text after 3a:**
  - the `agent_tools.py` module docstring (`:3-4`);
  - the `mcp_server.py` module docstring (`:3-4`);
  - the `verify_mcp_server.py` print at `:161`.
- **Validation schema.** MCP search now validates against the schema it lists.
  `validate_tool_args` ignores descriptions, so behaviour is identical, and listing and
  validation can't drift apart.
- **Request estimate.** The draft's "about 140" figure had no source. The WP2 baseline
  traces show 39 runs with 150 tool calls, plus judge calls on the same model, so the
  screen costs about 150–160 requests. A same-day bisect may not fit the quota.
- **The attribute revert** must include any review-fix commit that touches agent text,
  or the reverted tree won't be back at B.

**Nits, adopted:**
- The existing module `tests/test_mcp_server.py` is now named in the plan.
- `{**…}` overrides replace mutating a deepcopy at import.
- The `/compact` implementation → review boundary is now a step.
- A BACKLOG item: the MCP `ticker` description is agent-flavoured ("…which company the
  question is about").

**Confirmed:**
- every factual claim in the new descriptions;
- no import cycle (`prompts.mcp` → `agent_tools`);
- the enum and `additionalProperties: False` survive the copy;
- 3a changes only the `mcp` fingerprint (`prompts/__init__.py` hashes the `agent` key
  from agent surfaces and the agent section only);
- adding the new constant to `FINGERPRINTED` satisfies the classification test;
- `--since 20260925T000000Z` leaves out the spot-check that shares B's fingerprint;
- grouping 3b–3d into one screen, and the bisect order 3c, 3d, 3b, match the roadmap.

## Outcome

Both must-fixes and all should-fixes are folded into the plan before approval. Nothing
was deferred.
