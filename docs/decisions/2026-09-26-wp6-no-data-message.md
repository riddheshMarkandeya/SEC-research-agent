# WP6: no-data reply names the period used, "finds no data" wording (accepted)

**Date:** 2026-09-26

## Context

WP6 is Step 6 of `docs/plans/2026-09-24-prompt-audit-roadmap.md` (audit findings 11 and 12).
Commit 6a `1e1491b` makes `get_financial_fact`'s no-data reply name the period the lookup
actually used (a date, a multi-year range, the latest period, or `'FY' FY2025` for a year
with no period) instead of echoing absent arguments as "None FYNone". Commit 6b `ca6cace`
replaces "not available" / "Returns null" with "finds no data" in SYSTEM_PROMPT's tool bullet,
its rule 6, and `FACT_TOOL_SCHEMA`. Review fixes `b16c64c` changed no model input.

The roadmap's WP5–WP8 exemption keeps a decision file for every WP (later WPs read their
baseline from it). Plan and reviews: `docs/plans/2026-09-25-wp6-no-data-message.md`,
`docs/reviews/2026-09-25-wp6-no-data-message-plan-review.md`,
`docs/reviews/2026-09-26-wp6-no-data-message.md`.

## Decision

**Accepted** at the screen: no question flagged REGRESSED, so no replicate or attribute runs.
`pltr-government-contract-risk` is recorded as **watch** (3/3 → 2/3, a mechanism unrelated
to WP6, below).

- **Fingerprints:** `agent` B `5d3cea51c73b` → C `e073094f18b9`; `mcp` `3f183b31ab70` →
  `de995190f615` (the MCP tool list includes the fact schema, as the plan expected);
  `judge` `2ee29f234c91` unchanged.
- **Q4 hint kept** when a date or multi-year lookup ignores `fiscal_period` (plan review S1).

## Why

**Screen** (2026-09-26 07:30–07:43Z, clean tree at `b16c64c`, explicit mode; B = WP5's
screen `20260925T073044Z/073422Z/073730Z`, C `20260926T073646Z/074012Z/074314Z`,
committed in `1b04e50`), k/3 B → C:

| question | B | C | flag |
|---|---|---|---|
| aapl-ai-risk | 3/3 | 3/3 | |
| aapl-cash-and-buyback-q3fy2026 | 3/3 | 3/3 | |
| aapl-employees-fy25 | 3/3 | 3/3 | |
| aapl-iphone-net-sales-q3fy2026 | 3/3 | 3/3 | |
| aapl-msft-total-assets-comparison | 3/3 | 3/3 | |
| aapl-rd-pct-gross-profit-fy2025 | 3/3 | 3/3 | |
| msft-cash-to-assets-fy2025 | 3/3 | 3/3 | |
| nvda-crm-revenue-comparison | 3/3 | 3/3 | |
| nvda-rd-expense-q4fy26-refusal | 0/3 | 2/3 | improved (floor) |
| nvda-revenue-two-quarter-comparison | 1/3 | 3/3 | improved (floor) |
| nvda-segment-revenue-comparison-q1fy27 | 2/3 | 2/3 | |
| pltr-government-contract-risk | 3/3 | 2/3 | watch |
| pltr-inventory-turnover-fy2025-refusal | 1/3 | 2/3 | improved (floor) |

Panel total 31/39 → 35/39, expected passes lost −4.0, threshold 6: ok.

**The improvements are not credited to WP6.**
- `nvda-revenue-two-quarter-comparison`: B's two misses were the citation gate's "− 1" false
  positive (withheld 2/0), not a no-data reply. It already went 3/3 in WP5's replicate.
- The two refusals are floor questions, and their no-data replies are fiscal-shaped
  (year + period), which 6a renders byte-identically. 6b's wording could play a part, but
  one screen can't separate it from noise.

**`pltr-government-contract-risk` miss** (`074012Z`): a search-only run (5 searches, no fact
call) whose `submit_answer` claimed the date `20250630` as a numeric value. The gate refused
it ("claims 20250630 (raw) but that value doesn't appear in the quoted text"). Neither 6a's
reply nor 6b's fact-tool wording is on that path.

**Trace check** (no-data `get_financial_fact` replies, by argument shape → next call):

| | B (2026-09-25 07:26–07:37Z) | C (2026-09-26 07:30–07:43Z) |
|---|---|---|
| fiscal (year + period) → search_filings | 6 (Q4 refusal 3, PLTR inventory 3) | 6 (same split) |
| date → next | 0 | 1 → retried the fact call |
| multi-year / latest / year only | 0 | 0 |

- **Date-shaped reply** (`nvda-revenue-two-quarter-comparison`, 07:40:05Z): the model
  mistyped the prior-year date as `2027-04-26`. The reply now read "period ending
  '2027-04-26'" instead of "None FYNone". The next call used the correct `2025-04-27`, then
  calculate and a passing answer. This is the shape 6a targets. With one instance it is
  consistent with the fix, not evidence for it.
- **Q4 question:** all three runs got the fiscal-shaped Q4 reply plus the Q4 hint and then
  searched, the same as B. One of the three sent `fiscal_year: '2026'` as a string, and the
  reply still shows it as `FY'2026'` (WP7).

**Requests** (approximate: tool calls + judge calls + 429 retries): 156 tool calls, 15 judge
calls, 8 transient 429 retries (none exhausted), about 179. Day total 2026-09-26: about 198.

## Files touched

- `agent.py`, `prompts/agent_messages.py`, `tests/test_agent.py`,
  `tests/test_model_input_snapshot.py`, `prompts/model_input_snapshot.json` (6a `1e1491b`)
- `prompts/agent_system.py`, `prompts/agent_tools.py`, `prompts/model_input_snapshot.json`
  (6b `ca6cace`)
- `agent.py` (review fixes `b16c64c`: annotation and docstring only)

## Verification

- 6a: 13 new unit tests written first (red, then green); snapshot diff limited to the
  `no_fact_*` entries. 6b: snapshot diff limited to the three reworded spans.
- ruff 0, pyright 0, pytest 930 passed; `agent.py` 96%, `prompts/agent_messages.py` 100%.
- Code review: 2 rounds, 2 fixed, 1 deferred (WP7 item (d)).
- Screen and trace check as above.

**WP7's baseline:** the WP6 screen reports `20260926T073646Z/074012Z/074314Z`, agent
fingerprint `e073094f18b9`.

## Related

- Roadmap: `docs/plans/2026-09-24-prompt-audit-roadmap.md` (Step 6, Decision rule)
- Previous WP: `docs/decisions/2026-09-26-wp5-segment-rule.md`
- Audit findings 11 and 12: `docs/reviews/2026-09-24-prompt-audit.md`
