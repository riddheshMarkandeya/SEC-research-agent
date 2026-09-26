# WP5: plain segment-rule wording accepted (screen regression was gate noise)

**Date:** 2026-09-26

## Context

WP5 is Step 5 of `docs/plans/2026-09-24-prompt-audit-roadmap.md` (audit finding 4). Commit
5a `d45156f` replaced SYSTEM_PROMPT's pressure wording in the `get_financial_fact` bullet
("If a question asks about a specific segment or product line, do NOT call this tool at all,
not even to try — go straight to `search_filings` instead.") with "For a question about a
specific segment or product line, use `search_filings` instead of this tool."

The screen (reports `1f72f14`) flagged REGRESSED on one question, so the roadmap's Decision
rule called for a replicate. This record exists because the screen found a live regression
(exempt from the ADR gate per `.claude/rules/live-eval-verification.md`). Plan and reviews:
`docs/plans/2026-09-24-wp5-segment-rule.md`,
`docs/reviews/2026-09-24-wp5-segment-rule-plan-review.md`,
`docs/reviews/2026-09-25-wp5-segment-rule.md`.

## Decision

**Accepted.** The replicate passed 3/3, within 1 of B's 3/3, so the screen's 1/3 was noise.
5a stays, and `nvda-revenue-two-quarter-comparison` is recorded as **watch**. The failure
mechanism behind the screen's two misses, a citation-gate false positive, is filed as its own
BACKLOG item.

- **Fingerprints (agent):** B `d2131f5d5aae` (WP4 accepted) → C `5d3cea51c73b`.
  `judge` and `mcp` unchanged.
- **Change from the roadmap:** the roadmap's replacement text ended at "instead". WP5's plan
  review (S4) added "of this tool" so "instead" has an object once "do NOT call this tool" is
  gone.

## Why

**Screen** (2026-09-25, explicit mode, B `20260925T070749Z/071108Z/071503Z`, C
`20260925T073044Z/073422Z/073730Z`), per question k/3 B → C:

| question | B | C | flag |
|---|---|---|---|
| aapl-ai-risk | 2/3 | 3/3 | improved |
| aapl-cash-and-buyback-q3fy2026 | 3/3 | 3/3 | |
| aapl-employees-fy25 | 3/3 | 3/3 | |
| aapl-iphone-net-sales-q3fy2026 | 3/3 | 3/3 | |
| aapl-msft-total-assets-comparison | 2/3 | 3/3 | improved |
| aapl-rd-pct-gross-profit-fy2025 | 3/3 | 3/3 | |
| msft-cash-to-assets-fy2025 | 3/3 | 3/3 | |
| nvda-crm-revenue-comparison | 3/3 | 3/3 | |
| nvda-rd-expense-q4fy26-refusal | 1/3 | 0/3 | watch floor |
| nvda-revenue-two-quarter-comparison | 3/3 | 1/3 | REGRESSED |
| nvda-segment-revenue-comparison-q1fy27 | 2/3 | 2/3 | |
| pltr-government-contract-risk | 3/3 | 3/3 | |
| pltr-inventory-turnover-fy2025-refusal | 2/3 | 1/3 | watch |

Panel total 31/39 vs 33/39, expected passes lost 2.0, threshold 6: ok.

- **The two REGRESSED misses** (`073044Z`, `073422Z`) were both the citation gate withholding
  a passing answer (`gate_withheld_would_have_passed: True`). The warning in each was
  `claims 1.0 (raw) but no claim in your submit_answer call covers it`: the gate read the
  `1` in an inline "a ÷ b − 1" percent-change display as an uncovered number. Same family as
  WP3's "−359,241,000,000" on `aapl-msft-total-assets-comparison`. Nothing in the segment
  wording touches this path.
- **Replicate** (2026-09-26 07:03–07:05Z, clean tree at `a9311e8`, reports
  `20260926T070328Z/070358Z/070520Z`, committed in `ee2357a`): **3/3** vs B's 3/3, delta
  +0.0, within 1. No gate withholds. So no attribute (revert) runs were needed.

**Segment override: did not fire.** Trace counts by question ID:

| | B panel | C panel | B MSFT side | C MSFT side |
|---|---|---|---|---|
| `get_financial_fact` calls on segment questions | 0 | 0 | 0 | 0 |
| `search_filings` on `nvda-segment-revenue-comparison-q1fy27` / `aapl-iphone-net-sales-q3fy2026` | 6 / 3 | 7 / 3 | | |
| `search_filings` on `msft-three-segments-revenue-q3fy2026` (3 runs) | | | 15 | 15 |
| panel search / fact / calculate / submit | 66 / 41 / 15 / 44 | 58 / 40 / 14 / 45 | | |

No invented-argument calls and no consolidated value cited as a segment figure, so nothing
flagged and nothing watch-counted.

**Answer to `6f3a8ee`'s open question** (does the "do NOT … not even to try" emphasis matter
on Gemini?): no measurable effect. Gemini made no fact calls on any segment question with or
without it, matching the historical 0/51 on the panel segment questions. The plain wording
loses nothing.

**Requests** (approximate: tool calls + judge calls + 429 retries):
- 2026-09-25 (WP5's share): B side run 18 tool calls; screen + C side run 175 tool calls,
  15 judge calls, 13 transient 429 retries (none exhausted). About 221.
- 2026-09-26: replicate 14 tool calls, no judge calls, no retries. About 14.

## Files touched

- `prompts/agent_system.py` (commit `d45156f`)
- `prompts/model_input_snapshot.json` (commit `d45156f`)

## Verification

- Commit 5a: ruff, pyright, pytest clean; snapshot diff showed only the one sentence in the
  `agent` section (code review `docs/reviews/2026-09-25-wp5-segment-rule.md`, 1 clean round).
- Screen and replicate via `compare_prompt_versions.py` explicit mode, figures above.

**WP6's baseline:** the WP5 screen reports `20260925T073044Z/073422Z/073730Z`, agent
fingerprint `5d3cea51c73b` (the "If WP5 fails" table's accept row in
`docs/plans/2026-09-25-wp6-no-data-message.md`). The replicate reports are not pooled into B.

## Related

- Roadmap: `docs/plans/2026-09-24-prompt-audit-roadmap.md` (Step 5, Decision rule)
- Previous WP: `docs/decisions/2026-09-25-wp4-rule3-rule9.md`
- Same gate FP family: `docs/decisions/2026-09-24-wp3-group-a-wording.md`
