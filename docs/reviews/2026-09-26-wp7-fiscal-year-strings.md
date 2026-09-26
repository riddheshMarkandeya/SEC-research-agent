# Review: WP7, year-string conversion and "same no-data reply" wording (commits 264fbc6, 309d90a)

Plan: `docs/plans/2026-09-26-wp7-fiscal-year-strings.md` (the full Review log is there).
- **7a** adds `_coerce_year_args` (4-digit year strings → int, logged as `tool_arg_coerced`) in
  `call_get_financial_fact`, `call_compare_financial_metric` and `_dispatch_get_financial_fact`.
- **7b** rewords the "rejected outright" sentence in SYSTEM_PROMPT and the yoy "returns null"
  clause in `FACT_TOOL_SCHEMA`.

Suite before review: 935 passed. The diff `c8c2189..309d90a` touches blast-radius paths
(`agent.py`, `prompts/`), so it classified as Substantial.

## Round 1

Passes: `/code-review` high, `arch-reviewer` (opus), `security-reviewer`, `/simplify`
(reuse, simplification, efficiency, altitude; report-only).

**Fixed (`260cf4b`)**
1. **Med** (code-review): a whole float year (`2023.0`) passes the integer schema and crashes
   `get_multi_year_average`'s `range()` with an uncaught `TypeError`, on the agent and MCP paths.
   It predates WP7. `[Fixed]`: whole floats convert too. That also removes `FY2025.0` from
   no-data replies.
2. **Low** (code-review): `"0000"`/`"0999"` converted to years 0/999. `[Fixed]`: the regex
   needs a non-zero first digit.
3. **Low** (code-review): the `no_fact_never_tagged` snapshot scenario fed the formatter a
   string year the agent can no longer send. `[Fixed]`: it now passes int `2025`.
4. **Nit** (code-review, simplify): a repeated `frozenset({"fiscal_year"})`. `[Fixed]`:
   `_COMPARE_FISCAL_YEAR_PROPS`.
5. **Nit** (arch): a test comment didn't match its input. `[Fixed]`.

**Verified, no fix needed**
- The conversion runs twice on the agent path. This was planned: the inner call covers MCP,
  and both are pinned by tests.
- `tool_arg_coerced` is logged for an ignored `fiscal_year`. The trace check joins each event
  to its call's outcome.
- The rejection log shows the converted args. The preceding `tool_arg_coerced` line and the
  span input keep the raw value.
- 7b drops any cue to retry. This is the planned wording, and reason-bearing rejections are the
  roadmap's Step 9 (e) follow-up.
- Moving the conversion into `validate_tool_args` for all integer args. All live string
  rejections are years. The claimed crash on a string `citation_index` is false: it is rejected
  as `claims_wrong_type` (rechecked with the schema's real field names).
- The year regex in `numeric_utils`. It serves a different purpose and matches a different range.
- The snapshot scenario's route, which is recorded in the plan.
- `2026.0`, which is recorded in the decision file.
- Security: no findings.

## Round 2

Delta `git diff 309d90a`. Passes: `/code-review` medium, `security-reviewer`. No findings. A
huge whole float already passed the integer check before WP7, and the multi-year average
returns at the first missing year.

## Live verification

Panel screen, 3 runs of 13 questions: 35/39 → 36/39, no REGRESSED flag. No year strings were
sent in the window, so 7a was not exercised live. Figures are in
`docs/decisions/2026-09-26-wp7-fiscal-year-strings.md`.

## Outcome

7a, 7b and the review fixes shipped. Nothing deferred from review. Suite: 936 passed. The
review closed clean after 2 rounds with no escalation.
