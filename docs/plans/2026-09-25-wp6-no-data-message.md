# WP6: no-data message period rendering and "no data" wording (audit findings 11, 12)

## Context
WP6 is **Step 6** of `docs/plans/2026-09-24-prompt-audit-roadmap.md` (read that section; this
plan records only what changed since). Findings: `docs/reviews/2026-09-24-prompt-audit.md`
rows 11 and 12.

- **Finding 11 (contract bug):** `_format_no_fact_message` (`agent.py:132-151`) always renders
  `{fiscal_period!r} FY{fiscal_year!r}`, so the model reads "None FYNone" for `period_end_date`,
  multi-year or no-period requests, and "None FY2025" for a year without a period, although
  the lookup defaults to FY (`agent.py:367`) or returns the latest entry
  (`xbrl_facts.py:339-340`).
- **Finding 12 (description ≠ behaviour):** SYSTEM_PROMPT says `"not available"`
  (`prompts/agent_system.py:36`, rule 6 at `:50`) and the FACT schema says "Returns null"
  (`prompts/agent_tools.py:65`). The agent loop actually sends "(no structured data found …
  — try search_filings instead)"; MCP sends `{"error": "not available for …"}`.

**Tier:** Standard. Touches `agent.py` and `prompts/` (critical-core, escalated plan review).
**Sequencing:** plan now. Model-facing commits wait until WP5 closes (its replicate runs
2026-09-26 07:03 UTC); one prompt change per panel comparison.

## Changes since the roadmap
- **`MESSAGES_VERSION` no longer exists.** WP2 replaced it with `prompts.prompt_fingerprint()`
  plus the committed snapshot; the version bump becomes "regenerate the snapshot".
- **3c's "returns as not available" is already gone.** WP3 landed "finds no data for" in both
  search descriptions (`agent_tools.py:30`, `mcp.py:26`), so 6b adopts that phrase instead of
  the roadmap's example, and nothing is left to align.
- **Live exposure is small (trace count, no cost):** of 286 no-data replies ever, 270 had
  year+period, 10 year-without-period, 6 `period_end_date`, 0 multi-year, 0 no-year. The
  screen is mainly a no-harm check for 6b; 6a's value is contract correctness.
- **The snapshot already pins the bug** (`tests/test_model_input_snapshot.py:229-236`:
  `no_fact_empty`, `no_fact_fy`, `no_fact_ratio_not_tagged_check` show "None FY…"). These are
  6a's red step together with new unit tests.

## Step 0 (on approval, now): mark WP5 pending, save WP6 docs
The scheduled job `7c995ae5` (02:03 CDT 2026-09-26) stops if HEAD ≠ `1f72f14`, so:
1. Edit the WP5 BACKLOG line (`BACKLOG.md:52`) to start with **"IN PROGRESS — screen done,
   replicate pending (next quota day after 2026-09-25):"** followed by the exact pending
   steps: replicate `nvda-revenue-two-quarter-comparison` 3× vs `20260925T070749Z/071108Z/
   071503Z` (explicit mode), same-day attribute if not within 1, then decision + docs; the
   3 untracked WP5 docs to commit with it.
2. Save this plan to `docs/plans/2026-09-25-wp6-no-data-message.md` and its review to
   `docs/reviews/2026-09-25-wp6-no-data-message-plan-review.md`; add 2 Recent lines (40 → 42).
3. One docs-only commit (BACKLOG, PROJECT_INDEX, the 2 WP6 files, by explicit path). The
   WP5 docs stay untracked for the scheduled run.
   The same commit appends to the WP7 BACKLOG line the three WP7 notes from this plan's
   review (see "Plan review" below).
4. Replace job `7c995ae5` with the same prompt, step 1 relaxed to "HEAD is `1f72f14` or a
   docs-only descendant (`git merge-base --is-ancestor 1f72f14 HEAD`, and
   `git diff --stat 1f72f14 HEAD` touches only `docs/`, `BACKLOG.md`, `PROJECT_INDEX*.md`),
   agent fingerprint `5d3cea51c73b`, untracked files are only the 3 WP5 docs", and step 4
   deleting the (now IN PROGRESS) WP5 BACKLOG line as the normal close, and the
   confirmed branch filing its item worded as in "If WP5 fails" below. Docs commits are
   safe for the replicate: dirty-tree detection only covers `*.py`, `prompts`,
   `companies.json` and the question file (`eval_harness.py:459,513`), and explicit-mode
   compare ignores `git_sha`.
5. Save a project memory `project_wp5_pending_replicate.md` (+ MEMORY.md line) naming the
   pending replicate, so a new session sees it even if the job dies with this session.

## If WP5 fails: what happens (roadmap Decision rule, applied by the scheduled run)
Every outcome closes WP5 with a decision file; none leaves it open-ended. WP6 starts only
after that decision file exists, and takes its B from it.

| WP5 outcome | What the run does | BACKLOG | WP6's B |
|---|---|---|---|
| Replicate ≥ 2/3 (within 1 of B's 3/3) | accept 5a, record as watch | delete WP5 line; add gate "− 1" FP + "search_filings instead" items | WP5 screen reports, fingerprint `5d3cea51c73b` |
| Replicate ≤ 1/3, reverted runs ≥ 0.5 better | **confirmed**: keep `git revert d45156f` (pressure wording restored) | delete WP5 line; add a new item "plain segment wording regressed nvda-revenue-two-quarter-comparison on Gemini; failure mechanism was the gate's '− 1' FP, so retry the plain wording after that FP is fixed" (linked to the gate FP item); plus the 2 items above | WP4's reports (`20260925T070749Z/071108Z/071503Z`), fingerprint `d2131f5d5aae` |
| Replicate ≤ 1/3, reverted runs as low | **drift**: revert the revert, accept 5a, re-baseline (note it) | same as the first row | WP5 screen reports + the replicate |
| Run stops on anything unexpected (quota, dirty tree, crash, job lost with the session) | nothing committed beyond what's done; it reports | WP5 line stays IN PROGRESS; the memory entry points a new session at it | WP6 waits; we resume the WP5 step by hand |

Because the likely failure mechanism is the citation gate, not the segment wording, a
confirmed result is recorded as "reverted pending the gate fix", not as "plain wording is
worse". Fixing the gate FP itself is a separate Standard item (agent.py, needs its own screen),
not folded into WP5 or WP6.

## Step 1+ (after WP5 closes)
1. `git status` clean except known docs; read WP5's decision for B: WP5's screen reports
   (`20260925T073044Z/073422Z/073730Z`) if accepted, WP4's three if 5a was reverted.
2. **Commit 6a (finding 11), TDD.**
   - `prompts/agent_messages.py`: `NO_FACT_TEMPLATE` gets a `{period}` slot in place of
     `{fiscal_period!r} FY{fiscal_year!r}`, plus one constant per form:
     `NO_FACT_PERIOD_MULTI_YEAR = "FY{start!r}–FY{end!r} average"`,
     `NO_FACT_PERIOD_END_DATE = "period ending {date!r}"`,
     `NO_FACT_PERIOD_FISCAL = "{fiscal_period!r} FY{fiscal_year!r}"`,
     `NO_FACT_PERIOD_LATEST = "the latest available period"`. Add them to `FINGERPRINTED`
     (classification enforced by `tests/test_prompts.py:96`). Fill the period first, then
     pass it as a keyword argument (the module's no-double-format convention).
   - `agent.py`: new `_no_fact_period(args) -> str`, same order as `call_get_financial_fact`
     / `get_metric`: (1) `start_fiscal_year` or `end_fiscal_year` is not None → multi-year
     (a missing side renders as `None`, which is what was sent — the call was rejected for
     it); (2) truthy `period_end_date` (an empty string falls through, as in `get_metric`);
     (3) `fiscal_year` is not None → fiscal, with `args.get("fiscal_period", "FY")` exactly
     as the lookup reads it (`agent.py:372`) — not `or "FY"`, so an explicit `null` renders
     `None`, which is what the lookup used;
     (4) otherwise latest. `!r` stays on every value so malformed input stays visible
     (e.g. `FY'2025'` until WP7).
   - `_never_tagged_hint`: `isinstance(ticker, str) and isinstance(metric, str)` before the
     membership checks (a list ticker raises `TypeError` today); this replaces the
     type-checker `assert` and its comment.
   - **Q4 hint kept as is, deliberately:** it still fires on `fiscal_period == "Q4"` even
     when the lookup ignored the period (date, no year, multi-year). After 6a such a reply
     reads "period ending '2026-01-31'" plus the Q4 hint; 2 of 6 live date-shaped no-data
     replies had Q4 (MSFT). Kept because the hint answers what the user asked for (a Q4
     figure), which is still true; pinned by a unit test (date + Q4).
   - `_format_no_comparison_message` unchanged.
   - **Tests first** (`tests/test_agent.py`, monkeypatch `agent.is_metric_tagged` as
     `test_agent.py:239` does, or use a ratio metric, so no cache/network read and no
     never-tagged text in assertions): one per shape — year+period, year only (→
     `'FY' FY2025`), explicit `fiscal_period: None` with a year (→ `None FY2025`),
     `period_end_date` (wins over `fiscal_year`), date + Q4 (hint kept), empty-string date
     with a year, full and partial multi-year, nothing (→ latest), string year keeps
     `'2025'`, list ticker doesn't raise. Red → implement → green.
   - **Snapshot:** add a `no_fact_multi_year` scenario (partial range) to
     `tests/test_model_input_snapshot.py:229-236` and `EXPECTED_KEYS`; then
     `UPDATE_SNAPSHOT=1`. The diff shows only `no_fact_*` entries in the `agent` section.
3. **Commit 6b (finding 12).**
   - `agent_system.py:36`: `returns "not available" if the company doesn't tag it or the
     period wasn't recognized` → `finds no data if the company doesn't tag it or the period
     isn't recognized`.
   - `agent_system.py:50` (rule 6): `A \`get_financial_fact\` call returning "not available"
     for one company` → `A \`get_financial_fact\` call that finds no data for one company`.
   - `agent_tools.py:65`: `Returns null if the company doesn't tag this metric or the period
     isn't recognized` → `Finds no data if …` (rest unchanged).
   - `agent_tools.py:101` (yoy "returns null for that combination") stays for WP7.
   - MCP error strings unchanged (true enough: "not available"); `mcp` fingerprint moves
     because MCP lists the FACT schema — expected, record it. `judge` must not move.
   - Snapshot red → regenerate; diff limited to these three spans (agent + mcp sections).
4. Manual checks (ruff, pyright, pytest --cov); `/compact` line at the boundary.
5. `independent-review-pass`, light, over 6a..6b.
6. **Screen** (Decision rule): ≥250 requests left today (count from traces), clean tree; panel
   3× (same 13 IDs), explicit mode vs B's three reports. Grouped step: if confirmed at
   attribute, bisect 6a then 6b.
7. **Trace check (no cost):** no-data replies by argument shape and what the model did next
   (search vs refuse vs retry) B vs C; Q4 question's behaviour (the Q4 hint path is shared).
   Name `nvda-revenue-two-quarter-comparison` explicitly: all 3 recent date-shaped no-data
   replies come from it (the model mistypes the date as 2027-04-26/25 and today reads "None
   FYNone"), so 6a most likely shows there. It is also WP5's replicate question; the decision
   file attributes any movement on it using WP5's verdict.
8. Docs: decision file, code review, delete WP6 BACKLOG line, index lines; commit reports then
   docs by path. No push.

**Authorisation on approval:** step 0 now (edits, one docs commit, cron replacement,
memory); after WP5 closes: 6a, 6b, review fixes, Decision-rule reverts, reports and docs
commits; ~200 Gemini requests for the screen plus ~25 per replicate/attribute question.

## Out of scope
`_format_no_comparison_message`; MCP error text; yoy/ratio "returns null" (WP7); digit-string
years (WP7); the all-caps emphasis (WP8).

## Critical files
`agent.py`, `prompts/agent_messages.py`, `prompts/agent_system.py`, `prompts/agent_tools.py`,
`prompts/model_input_snapshot.json`, `tests/test_agent.py`. Reuse: snapshot test,
`prompt_fingerprint`, `compare_prompt_versions.py`, the WP4/WP5 trace-check script pattern.

## Plan review (1 independent round; source for the step-0 review file)
- **Must-fix:** none.
- **Should-fix, adopted:** S1 Q4 hint with an ignored period: keep it, give the reason, pin
  it with a test. S2 name `nvda-revenue-two-quarter-comparison` in the trace check.
  S3 render `fiscal_period` via `args.get(..., "FY")` and test an explicit null. S4 add a
  multi-year snapshot scenario. S5 stub `is_metric_tagged` in the new tests.
- **Nits, adopted:** `merge-base --is-ancestor` in the job's check; "the latest available
  period"; a rejected date + string-year call renders "period ending …" (accepted, the reply is
  already a generic no-data message).
- **For WP7 (appended to its BACKLOG line in step 0):** (a) a yoy no-data reply names the
  current period even when the prior year is the missing one (`formulas.py:353`); (b) WP7
  coerces the year on a copy of `args` but the no-data message reads the original
  (`agent.py:1885`), so it would still show `FY'2025'`; pass the coerced args; (c) roadmap
  Step 7's "Bump MESSAGES_VERSION" is stale (now: regenerate the snapshot).
- **Confirmed:** branch order matches every lookup path (get_metric, get_ratio's legs,
  get_yoy_growth, multi-year); `MESSAGES_VERSION` is gone; "finds no data for" landed; the
  FACT description is in the snapshot's `mcp_list_tools`, so `mcp` moves in 6b only; `judge`
  can't move; the snapshot shows the bug; the list-ticker `TypeError` is real; the trace
  counts reproduce; step 0 is safe for the WP5 replicate; screen budget and bisect match the
  Decision rule.

## Verification
Unit tests per shape; snapshot diff limited to intended spans; fingerprints (`agent` and
`mcp` move, `judge` doesn't); explicit-mode screen verdict and trace counts in the decision
file.
