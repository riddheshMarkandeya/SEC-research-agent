# Review: WP3, Group A wording fixes (commits 10d4a58..ac03018, fix 12554a4)

Plan: `docs/plans/2026-09-24-wp3-group-a-wording.md`. WP3 changes four things:
- it gives MCP clients their own `search_filings` schema (`prompts.mcp.MCP_SEARCH_TOOL_SCHEMA`),
  which `mcp_server` both lists and validates against;
- it rewrites the agent's `search_filings` description;
- it drops "yet" from the COMPARE single-company-ratio note;
- it drops "via compare_financial_metric" from CALCULATE's ratio hint.

The suite had 917 tests before WP3 and 920 at review start. The review ran the five-pass
`independent-review-pass` over `01ba453..HEAD` in 2 rounds, with ruff and pyright clean and
the full suite passing before each. The only model-facing change the review made is to the
MCP search description, so the agent fingerprint stayed `4f36a2b026cf` and the frozen
agent text was screened as committed.

## Round 1 (`01ba453..ac03018`)

### Pass 1: correctness (`/code-review`, medium)
- No bugs found. It verified:
  - the MCP schema's parameters equal the agent's, so MCP accepts exactly the same
    arguments as before;
  - the `{text, source}` claim matches `_search_filings`' return value;
  - the "citation number, ticker, form type and report date" claim matches
    `_citation_header`;
  - "a registered ratio metric" is still true through `get_financial_fact`'s enum.
- [Fixed] The MCP search description said only "any metric get_financial_fact doesn't
  cover", while the agent's says "doesn't cover or finds no data for". The added clause is
  also true over MCP, which returns "not available". Pass 3 flagged the same gap. The fix
  changes only the `mcp` section of the snapshot.

### Passes 2 and 3: comments, docs and design (one fresh subagent)
- [Fixed, should] The `mcp_server.py` module docstring still ended with a docs/decisions
  pointer. The diff rewrote that docstring, so the pointer was brought up to the
  self-contained-comment rule.
- [Fixed, nit] The `verify_mcp_server` print "are exactly prompts/' (…)" now reads "match
  prompts/ (search: prompts.mcp's MCP variant)".
- [Fixed, nit] Plan step 0 said the plan was copied "from `TEMPLATE.md`", but it follows
  the WP1/WP2 plan layout instead. The claim was dropped.
- [Fixed, nit] The parity test didn't compare the top-level `type`. Pass 5 later replaced
  it with a whole-schema comparison.
- [Verified, kept] The helper names `_search` and `_search_parameters` stay in the module.
  The classification test collects only uppercase names, and underscore names aren't
  exported.
- [Verified, kept] The shallow `{**}` copy shares the `ticker` sub-dict and its `enum` with
  the agent's schema. Nothing mutates schemas, and before WP3 MCP shared the whole object
  anyway.
- Confirmed:
  - the placement in `prompts/mcp.py`, with no import cycle;
  - `FINGERPRINTED` membership, so a change to the search parameters moves both the
    `agent` and `mcp` fingerprints and an agent-only description change moves only `agent`;
  - the new tests compare against constants rather than literal text, apart from the
    "original question" guard.

### Pass 4: security (fresh subagent)
- No high-confidence findings.
- A runtime dump of the MCP schema confirmed that `type`, `required: ["query"]`,
  `additionalProperties: false` and the ticker `enum` all survive.
- `validate_tool_args` still runs before `hybrid_search`.
- Auth and rate limiting are untouched.

### Pass 5: `/simplify` (reuse, simplification, efficiency, altitude)
- [Fixed] The parity test now deep-copies both schemas, deletes the two descriptions and
  compares the whole dicts. It is shorter and covers any future function-level key.
- [Skipped] Building the MCP schema with `deepcopy` and then mutating it. The plan review
  already chose the `{**}` overrides over mutating a deepcopy, and nothing new has come up.
- [Skipped] Replacing the generator-throw lambda in the unknown-argument test. It is this
  file's existing idiom.
- [Skipped] Moving the "original question" assert. It guards exactly the bug being fixed.
- [Deferred, filed to BACKLOG.md] Altitude found two things:
  - The derivation runs backwards: the MCP schema is the agent's with its agent-only text
    overridden, so agent-only wording added to any other field (as the `ticker`
    description already has) reaches MCP silently.
  - Three of the search description's sentences are duplicated across the two surfaces.

  Both fixes restructure agent text that was frozen for this screen, so they go into the
  Low BACKLOG item this plan had already filed for the `ticker` description.
- Reuse and efficiency found nothing.

Fix commit: `12554a4`.

## Round 2 (`12554a4`, low effort)
- Pass 1 (`/code-review`, low): no bugs.
- Passes 2 and 3: no findings. There was one optional nit: the parity test's name says
  "only in descriptions" but allows only two to differ. Skipped.
- Pass 4: no high-confidence findings.
- Pass 5: all four angles clean, and `/simplify` made no edits.

The round was clean, so the loop closed.

## Live verification
- `python tests/manual/verify_mcp_server.py` at `12554a4`: all checks passed. Those checks
  include that the listed tools equal `MCP_SEARCH_TOOL_SCHEMA`, `FACT_TOOL_SCHEMA` and
  `COMPARE_TOOL_SCHEMA`, and that live fact, compare and search results match ground truth.
- The Decision-rule screen of the agent text is recorded in
  `docs/decisions/2026-09-24-wp3-group-a-wording.md`.

## Outcome
Two rounds ran and the loop closed clean. The suite has 920 tests; ruff and pyright are
clean, and diff-cover is 100% against `01ba453`. Fingerprints at `12554a4`: `agent`
`4f36a2b026cf`, `mcp` `3f183b31ab70`. One Low BACKLOG item is open: the MCP search schema's
derivation direction, the agent-flavoured `ticker` description, and the duplicated
description sentences.
