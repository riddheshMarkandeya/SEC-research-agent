# Group A wording fixes, screened against the WP2 baseline (WP3)

**Date:** 2026-09-24

## Context

The prompt audit (`docs/reviews/2026-09-24-prompt-audit.md`) found four wording problems
in the tool descriptions:

| # | Problem |
|---|---|
| 1 | MCP clients were told the first search per company "always uses the user's original question", which is true only inside the agent loop |
| 2 | The `search_filings` description was one sentence, with no return shape and no guidance on when to use it |
| 5 | CALCULATE's ratio hint pointed to compare_financial_metric, although single-company ratios exist only on get_financial_fact |
| 6 | The COMPARE description said "no cross-company version exists yet" |

This is roadmap Step 3 (WP3), the first prompt change screened under the roadmap's
Decision rule. Plan: `docs/plans/2026-09-24-wp3-group-a-wording.md`.

## Decision

- **3a `10d4a58`:** MCP gets its own `search_filings` schema,
  `prompts.mcp.MCP_SEARCH_TOOL_SCHEMA`.
  - It is built from the agent's schema with `{**}` overrides of the tool description
    and the `query` description, so the parameters stay identical.
  - `mcp_server` lists it and validates against it.
  - The description says what MCP returns (`{text, source}` objects), when to use the
    tool, and to pass `ticker`.
- **3b `50d9be5`:** "version exists yet" becomes "version exists".
- **3c `252186d`:** the agent's search description now says:
  - what each excerpt is headed with;
  - to use it for narrative content and for any metric get_financial_fact "doesn't cover
    or finds no data for";
  - that it returns filing text only.
- **3d `ac03018`:** "via compare_financial_metric" is dropped from CALCULATE's ratio hint.
- **Review fix `12554a4`:** the MCP description also gets "or finds no data for". It is
  MCP-only, so the agent text is unchanged.
- **Fingerprints:**

  | | before | after |
  |---|---|---|
  | `agent` | `cc984387c3e8` | `4f36a2b026cf` |
  | `mcp` | | `3f183b31ab70` |
- **Screen verdict: accepted.** There was no REGRESSED and no REGRESSED-TOTAL flag, so no
  replicate or attribute step ran.

## Why

- **The two changes from the roadmap:**
  - **"finds no data for" instead of the roadmap's "returns as not available".** On no
    data the agent receives "(no structured data found … — try search_filings
    instead)", and the FACT schema says "Returns null". "Finds no data for" is true on
    every surface, so WP6 won't have to re-align it.
  - **MCP validates against the schema it lists.** `validate_tool_args` ignores
    descriptions, so behaviour is identical, and the listed schema and the validated one
    can't drift apart.
- **3a didn't need an eval.** It changes only what MCP clients see: the agent fingerprint
  stayed `cc984387c3e8` after it.
- **3b–3d were screened as one group,** as the roadmap prescribes for small wording
  commits. Only a flag would have triggered the revert-then-bisect path.

## Screen

Panel: 13 questions × 3 runs at `12554a4` on a clean tree with the snapshot verified
(reports `20260925T014421Z`, `014751Z`, `015101Z`). The baseline B is WP2's three reports.
Command: `compare_prompt_versions.py --base cc984387c3e8 --since 20260925T000000Z`.

| question | B | C | flag |
|---|---|---|---|
| aapl-msft-total-assets-comparison | 3/3 | 2/3 | watch |
| nvda-rd-expense-q4fy26-refusal | 3/3 | 2/3 | watch |
| nvda-segment-revenue-comparison-q1fy27 | 2/3 | 3/3 | improved |
| pltr-inventory-turnover-fy2025-refusal | 2/3 | 3/3 | improved |
| the other 9 | 3/3 | 3/3 | |
| **total** | **37/39** | **37/39** | expected passes lost 0.0, threshold 6: ok |

- **The two watch failures,** both in run 2:
  - `aapl-msft-total-assets-comparison`: the citation gate withheld a correct answer,
    marked `gate_withheld_would_have_passed: True`. The model wrote the subtraction
    inline, and the gate read "−359,241,000,000" as an uncovered number. This is the gate's
    existing uncovered-number behaviour, not a wording effect.
  - `nvda-rd-expense-q4fy26-refusal`: the refusal left out the full-year R&D figure the
    rubric asks for as context.
- **Observation: more searches.** `search_filings` calls rose from 47 in B to 62 in C,
  while fact, calculate and submit calls stayed flat (42 → 43, 16 → 14, 45 → 44). Most of
  the rise is in three questions:
  - `msft-cash-to-assets-fy2025`: 0 → 7;
  - `pltr-government-contract-risk`: 3 → 8;
  - `nvda-rd-expense-q4fy26-refusal`: 9 → 12.

  This fits the fuller "when to use it" text. Pass rates held, so it is recorded here for
  WP8's full-run comparison rather than acted on.
- **Cost:** 163 agent tool calls plus 15 judge calls, about 175 requests. That is above
  the plan's estimate of 150–160, because of the extra searches.

## Files touched

- `prompts/mcp.py`
- `prompts/agent_tools.py`
- `prompts/model_input_snapshot.json`
- `mcp_server.py`
- `tests/test_mcp_server.py`
- `tests/manual/verify_mcp_server.py`

## Verification

- **Checks:** 920 tests pass, ruff and pyright are clean, and diff-cover is 100% against
  `01ba453`.
- **Snapshot:** each commit's snapshot diff showed only its intended text.
- **Live MCP check:** `tests/manual/verify_mcp_server.py` passed at `12554a4`.
- **Screen:** see the Screen section above.
- **Review:** `docs/reviews/2026-09-24-wp3-group-a-wording.md` (2 rounds, closed clean).

## Related

- Plan: `docs/plans/2026-09-24-wp3-group-a-wording.md`.
- Plan review: `docs/reviews/2026-09-24-wp3-group-a-wording-plan-review.md`.
- Baseline and tooling: `docs/decisions/2026-09-24-wp2-prompt-provenance.md`.
- Roadmap: `docs/plans/2026-09-24-prompt-audit-roadmap.md`, Step 3.
