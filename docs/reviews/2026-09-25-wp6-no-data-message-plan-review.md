# Review: WP6 plan, no-data message period and wording (one independent plan-review round)

Plan: `docs/plans/2026-09-25-wp6-no-data-message.md`. The plan fixes how
`_format_no_fact_message` renders the period (audit finding 11: "None FYNone" for date,
multi-year and no-period requests, "None FY2025" for a year without a period). It also
makes the "not available" / "Returns null" descriptions true on both the agent and MCP
surfaces (finding 12). The change is screened as a group under the roadmap's Decision rule.
The plan was written while WP5's replicate was waiting for the quota reset, and WP6's
implementation is held until WP5 closes. This review covers the plan only. HEAD was
`1f72f14`.

## Pass 1: self-check of the roadmap's Step 6 against HEAD `1f72f14`
- [Fixed in plan] `MESSAGES_VERSION` no longer exists. WP2 replaced it with
  `prompt_fingerprint()` and the committed snapshot, so the version bump becomes "regenerate
  the snapshot".
- [Fixed in plan] 3c's "returns as not available" is already gone. WP3 landed "finds no
  data for" in both search descriptions, so 6b uses that phrase.
- [Verified] Trace count: 286 no-data replies ever.

  | argument shape | replies |
  |---|---|
  | year and period | 270 |
  | year without a period | 10 |
  | `period_end_date` | 6 |
  | multi-year | 0 |
  | no year | 0 |

## Round 1: independent subagent (the whole plan, escalated for `agent.py` and `prompts/`)

**Must-fix:** none.

**Should-fix, all adopted:**
- **S1: the Q4 hint can contradict the rendered period.**
  - The hint fires on `fiscal_period == "Q4"`, even when the lookup ignored the period:
    a date was given, no year was given, or the request was multi-year.
  - 2 of the 6 live date-shaped replies had Q4 (MSFT).
  - Kept deliberately, because the hint answers what the user asked for. The plan now gives
    that reason, and a unit test pins it.
- **S2: name `nvda-revenue-two-quarter-comparison` in the trace check.**
  - All 3 recent date-shaped no-data replies come from it. The model mistypes the date as
    2027-04-26/25 and currently reads "None FYNone".
  - It is also WP5's replicate question, so the WP6 decision file attributes any movement on
    it using WP5's verdict.
- **S3: render the period with `args.get("fiscal_period", "FY")`, exactly as the lookup
  reads it (`agent.py:372`), not `or "FY"`.** An explicit null then renders as `None`, which
  is what the lookup used. A test was added.
- **S4: add a `no_fact_multi_year` snapshot scenario (partial range).** No existing scenario
  covered that branch.
- **S5: the new unit tests stub `is_metric_tagged`.** Otherwise they read the cache or the
  network, and the never-tagged hint clutters the assertions.

**Nits:**
- [Adopted] The scheduled job's descendant check uses `git merge-base --is-ancestor`.
- [Adopted] "the latest available period".
- [Accepted as is] A rejected call with a date and a string year renders "period ending …".
  The whole reply is already a generic no-data message.

**For WP7, appended to its BACKLOG line:**
- A yoy no-data reply names the current period even when the prior year is the missing one
  (`formulas.py:353`).
- WP7 converts the year on a copy of `args`, but the no-data message reads the original
  (`agent.py:1885`). The copy has to be passed on too.
- Roadmap Step 7's "Bump MESSAGES_VERSION" is stale.

**Confirmed:**
- **Branch order:** it matches every lookup path: `get_metric`, `get_ratio`'s legs,
  `get_yoy_growth`, and multi-year.
- **Design:** four constants plus a helper follows `agent_messages.py`'s convention that
  each piece of text is its own constant and the logic that chooses between them stays in
  `agent.py`.
- **The list-ticker `TypeError` in `_never_tagged_hint` is real.**
- **Fingerprints:** the FACT description is in the snapshot's `mcp_list_tools`, so `mcp`
  moves in 6b only, and `judge` can't move.
- **Step 0 is safe for WP5's replicate:**
  - dirty-tree detection only covers `*.py`, `prompts`, `companies.json` and the question
    file;
  - explicit mode ignores `git_sha`;
  - the docs-health hook reads only the staged tree.

## Addendum: user question during review
The user asked what happens if WP5's replicate fails. The plan now has an "If WP5 fails"
table:
- **Accepted:** WP5 closes normally.
- **Confirmed:** the revert is kept, and a BACKLOG item says to retry the plain wording once
  the citation gate's "− 1" false positive is fixed. That false positive is the likely
  mechanism.
- **Drift:** WP5 is accepted and re-baselined.
- **The run stops:** the WP5 line stays IN PROGRESS, and it is resumed by hand.

Each case names WP6's baseline.

## Outcome
The review closed in one round, with no must-fix findings and all five should-fix findings
adopted.
