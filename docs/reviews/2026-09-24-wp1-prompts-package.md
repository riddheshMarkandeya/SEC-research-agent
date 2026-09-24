# Review: WP1, model-facing text moved into `prompts/` (commits bbf41d7..a71fd2d)

Plan: `docs/plans/2026-09-24-wp1-prompts-package.md`. The change is a pure move of
every static model-facing string into `prompts/`, with byte-identical model input.
The suite had 790 tests before the change and 791 at review start. The review ran
the five-pass `independent-review-pass` over `38af001..HEAD`: 3 rounds, with ruff and
pyright clean before each.

## Pass 1: correctness and CLAUDE.md compliance (`/code-review`, high)

No correctness regressions. The reviewer independently re-checked that the moved
text matches `38af001` byte for byte. Findings:
- [Fixed] Comments and docstrings this diff edited still ended in `docs/` pointers:
  - `agent._format_citation_retry_message`;
  - `agent._format_claim_retry_message`;
  - the calculate section header;
  - the `_format_claim_retry_message` test section comment.
- [Fixed] `githooks/pre-push`: `'prompts/*.py'` didn't match the rule file's
  `prompts/**`. Changed to `'prompts/**/*.py'`, and confirmed that diff-cover (which
  uses `glob.glob(recursive=True)`) still matches all 5 top-level files.
- [Fixed] The metric list `sorted(DEFAULT_METRIC_TAGS) + sorted(RATIO_DEFINITIONS)`
  was built separately for the system prompt and for the fact schema's enum. It is
  now one `FACT_METRICS` constant.
- [Fixed] A stale `llm_backends._to_gemini_tool` docstring said the schemas live in
  `agent.py`.
- [Fixed] A mis-wrapped `call_compare_financial_metric` docstring, and a stray blank
  line left by the move.
- [Verified, kept] Building `COMPANIES` at import in `companies.py` makes the ingest
  modules read `companies.json` at import. The roadmap chose that location, and the
  decision file records why it still holds.
- [Verified, kept] The `agent_tools` → `agent_system` import for the ratio lists is
  left to WP2's fingerprint design.
- [Verified, kept] The separator and bullet constants are model-visible bytes, so
  they stay in `prompts/`.

## Passes 2–3: docs hygiene, architecture and design (fresh subagent)

Layout, `.format` safety, placeholder/call-site matching, import cycles and naming
were all confirmed. Findings:
- [Fixed] `live-eval-verification.md` loads for `prompts/**`, but its rule named only
  the judge prompts. It now covers all `prompts/` text, and the two back-to-back
  parentheticals are merged.
- [Fixed] The comment on `CALCULATE_TOOL_SCHEMA`, moved verbatim, retold its history
  (the FinQA/PAL background, "built after finding..."). It is trimmed to the design
  facts.
- [Verified, kept] `CLAIM_UNITS` in `prompts/` and the `*_EXPRESSION` template names
  are optional. The roadmap's layout stands, and renaming would be churn.

## Pass 4: security (fresh subagent)

No findings. Every `.format` call formats a fixed `prompts/` constant. Model, user,
MCP-client and filing text only ever arrives as keyword arguments, and no rendered
output is ever used as a template again. `UNKNOWN_TOOL_TEMPLATE` formats the client's
tool name with `!r`, exactly as before.

## Pass 5: `/simplify` (reuse, simplification, efficiency, altitude)

- [Fixed] The "a raw unit is shown bare" rule was written twice, in
  `_format_fact_value` and `_calculation_as_result`. It is now one `agent._with_unit`
  helper.
- [Skipped] Inlining the separator constants, and baking `CITATION_RETRY_GUIDANCE`
  into the retry templates. The first is covered above; the second is restructuring
  for no gain.
- [Deferred — filed to BACKLOG.md] Enum duplication that already existed before
  WP1: the period list, `list(COMPANIES.keys())`, and `CLAIM_UNITS` restating
  `UNIT_MULTIPLIERS`.
- [Coverage] Two rewritten `agent.py` branches had no repo test: the
  `percent_change` expression and the generic search invalid-arguments message.
  Tests pinning both outputs exactly were added.

## Live verification

None, on purpose (the WP1 exemption in the decision file): no model-facing byte
changed. After each round, the checks were re-run:
- the sha256 of the prompt and schemas;
- the 44-entry golden capture at the backend boundary;
- the trace log's size.

All were identical to the pre-move baseline.

## Additional rounds

- **Round 2** (on the round 1 fixes): no correctness or security findings. The design
  pass found a still-ragged docstring rewrap and an unannotated `_with_unit` value
  parameter, both fixed.
  - One pass-1 claim was disproved: that `**` might stop matching top-level files. It
    was checked against diff-cover's source and a real run.
  - One `/simplify` altitude claim was disproved: that diff-cover matches includes
    with `fnmatch`. It uses `fnmatch` only for excludes.
- **Round 3** (on the round 2 edits): all passes clean. The one extra fix was dropping
  a `docs/decisions/` pointer from the `_to_gemini_tool` docstring this diff had
  edited.
  - The reuse reviewer spotted a model-visible issue outside WP1's scope: a calculate
    expression shows a raw operand's unit as "1.04 raw". It is filed to BACKLOG.md,
    because fixing it would change model input.

## Outcome

- **Shipped:** WP1 (commits 1a–1c, the leftover sweep, and a review-fix commit).
- **Suite:** 793 tests pass, and ruff and pyright are clean.
- **Coverage:** critical-core diff coverage is 99%. The one uncovered line predates
  WP1.
- **Filed to BACKLOG.md:** the "raw" unit in calculate expressions
  `[bug, Low, Standard]`, and the schema enum duplication
  `[refactor, Low, Trivial]`.
- **Loop:** closed after round 3 with no new issues.
