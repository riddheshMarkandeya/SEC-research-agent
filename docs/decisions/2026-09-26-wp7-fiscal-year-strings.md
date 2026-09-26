# WP7: convert year strings to int, "same no-data reply" wording (accepted)

**Date:** 2026-09-26

## Context

WP7 is Step 7 of `docs/plans/2026-09-24-prompt-audit-roadmap.md` (audit finding 13). Gemini
sends `fiscal_year` as a string (`"2025"`) despite the integer schema. There were 160 live
`invalid_fiscal_year_type` rejections, all on `get_financial_fact` and all digit strings
(84 `'2026'`, 76 `'2025'`). Each rejection gave the model the generic no-data reply, and it
fell back to search. SYSTEM_PROMPT also said an unrecognized argument is "rejected outright",
when it actually gets the same no-data reply.

- **7a `264fbc6`:** adds `_coerce_year_args`. It converts a 4-ASCII-digit year string to an int
  and logs `tool_arg_coerced`, in `call_get_financial_fact` (all three year fields) and
  `call_compare_financial_metric` (`fiscal_year`), so MCP is covered too. The fact dispatcher
  converts before building its no-data reply, so that reply reads `FY2025`, not `FY'2025'`.
- **7b `309d90a`:** "an unrecognized argument is rejected outright, so search_filings
  instead…" → "an unrecognized argument gets the same no-data reply."; the yoy description's
  "returns null for that combination" → "that combination is rejected and reports no data".
  This also closes the BACKLOG item about using the tool name as a verb.
- **Review fixes `260cf4b`:**
  - whole floats (`2023.0`) convert too: they pass the integer schema, but they crashed the
    multi-year average's `range()`;
  - the year string needs a non-zero first digit (`"0000"` stays rejected);
  - the `no_fact_never_tagged` snapshot scenario passes int `2025`.

The roadmap's WP5–WP8 exemption keeps a decision file for every WP. Plan and reviews:
`docs/plans/2026-09-26-wp7-fiscal-year-strings.md` (Review log inside),
`docs/reviews/2026-09-26-wp7-fiscal-year-strings-plan-review.md`,
`docs/reviews/2026-09-26-wp7-fiscal-year-strings.md`.

## Decision

**Accepted** at the screen. No question was flagged REGRESSED, so there were no replicate or
attribute runs. `nvda-revenue-two-quarter-comparison` is on **watch** (3/3 → 2/3, the known
"− 1" gate false positive, below).

- **Fingerprints:** `agent` B `e073094f18b9` → 7a `63030ce94e89` → 7b `35c13d2488df` → C
  `7aec53939ce3`; `mcp` `de995190f615` → `b34024a4d17d` (at 7b, from the yoy description);
  `judge` `2ee29f234c91` unchanged. Pinned model `gemini-3.5-flash-lite`.
- **Only 4-digit strings convert**, not any digit string: `"0"`, `"99999"`, `"0000"` stay
  rejected, so junk never reaches the lookup to be counted as `no_data_for_ticker`.
- **Tests replaced deliberately.** Three tests asserted that `"2025"` is rejected:
  - `test_call_get_financial_fact_rejects_non_int_fiscal_year`;
  - `test_call_compare_financial_metric_rejects_non_int_fiscal_year`;
  - `test_call_get_financial_fact_rejects_non_int_multi_year_average_years`.

  They now use `"FY2025"` / `"FY2023"`, so the rejection path stays covered.
- **Roadmap correction:** the roadmap listed `2026.0` as "still rejected". It never was, because
  JSON Schema treats a whole float as an integer. It is now converted to `2026`.
- **Converting years in compare calls and multi-year ranges has no live evidence yet.** All 160
  rejections were `fiscal_year` on the fact tool. The same helper covers these at no extra code.

## Why

**Screen** (2026-09-26 08:53–09:04Z, clean tree at `260cf4b`, explicit mode; B = WP6's screen
`20260926T073646Z/074012Z/074314Z`, C `20260926T085714Z/090017Z/090341Z`, committed in
`f6fbb31`), k/3 B → C:

| question | B | C | flag |
|---|---|---|---|
| nvda-revenue-two-quarter-comparison | 3/3 | 2/3 | watch (withheld 0/1) |
| nvda-segment-revenue-comparison-q1fy27 | 2/3 | 3/3 | improved |
| pltr-government-contract-risk | 2/3 | 3/3 | improved |
| the other 10 panel questions | same | same | |

Panel total 35/39 → 36/39, expected passes lost −1.0, threshold 6: ok.

- **The screen ran with about 300 requests left**, below the plan's 350 cutoff, at the user's
  direction. No flag meant the cutoff (kept for same-day replicate and attribute runs) was never
  needed.
- **7a was not exercised.** This window had 0 `tool_arg_coerced` and 0 `invalid_fiscal_year_type`
  events: the model sent int years on every call. The same questions in B had 4 string
  rejections. Whether 7b's wording or noise caused that can't be told from one screen, so no
  score change is credited to WP7. The conversion itself is covered by unit tests and the
  dispatcher snapshot scenario.
- **Misses in C:**
  - `nvda-revenue-two-quarter-comparison`: withheld by the citation gate's "claims 1.0 (raw)"
    false positive on an inline "− 1" (the existing BACKLOG bug).
  - `nvda-rd-expense-q4fy26-refusal`: a correct refusal that the judge failed for not giving the
    full-year R&D figure as context, which the Q4 hint forbids. 2/3 in B too.
  - `pltr-inventory-turnover-fy2025-refusal`: computed a turnover figure from search results and
    was refused by the gate. 2/3 in B too.

**Trace check** (canary fact calls, B → C):

| | B (07:30–07:44Z) | C (08:53–09:04Z) |
|---|---|---|
| `invalid_fiscal_year_type` rejections | 4 (PLTR inventory 3, Q4 1) | 0 |
| `tool_arg_coerced` events | — | 0 |
| canary fact calls with an int year | 2 of 6 | 6 of 6 |
| next call after the canary no-data reply | search (6/6) | search (6/6) |

No unmet-metric events in either window.

**Requests** (approximate): 151 tool calls, 13 transient 429 retries (none exhausted), about 15
judge calls: about 180. Day total 2026-09-26: about 378.

## Files touched

- `agent.py`, `tests/test_agent.py`, `tests/test_model_input_snapshot.py`,
  `prompts/model_input_snapshot.json` (7a `264fbc6`, review fixes `260cf4b`)
- `prompts/agent_system.py`, `prompts/agent_tools.py`, `prompts/model_input_snapshot.json`
  (7b `309d90a`)

## Verification

- 7a: tests written first (red, then green). Snapshot diffs: 7a only the new dispatcher entry;
  7b only the four reworded spans; review fixes only `no_fact_never_tagged`.
- ruff 0, pyright 0, pytest 936 passed; `agent.py` 96%, all new lines covered.
- Code review: 2 rounds, 5 fixed, 9 verified with no fix needed, 0 deferred.
- Screen and trace check as above.

**WP8's comparison** is the full 48-question run against the full runs `20260921T222521Z` and
`20260922T062823Z` (roadmap Step 8), at agent `7aec53939ce3`.

## Related

- Roadmap: `docs/plans/2026-09-24-prompt-audit-roadmap.md` (Step 7, Decision rule)
- Previous WP: `docs/decisions/2026-09-26-wp6-no-data-message.md`
- Audit finding 13: `docs/reviews/2026-09-24-prompt-audit.md`
