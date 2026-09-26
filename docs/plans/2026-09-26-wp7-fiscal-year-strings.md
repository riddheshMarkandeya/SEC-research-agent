# WP7: accept digit-only year strings; "rejected outright" wording (finding 13)

Roadmap: `docs/plans/2026-09-24-prompt-audit-roadmap.md`, Step 7 (the fix, the tests and the
screening are there; this plan records only what changed since). Audit finding 13:
`docs/reviews/2026-09-24-prompt-audit.md`. BACKLOG: the WP7 line (sub-items a–d).

## Context
Gemini keeps sending `fiscal_year` as a string (`"2025"`) despite the integer schema.
`_rejects_invalid_fiscal_year` (`agent.py:208`) rejects it, the call returns `None`, and the
model gets the generic no-data reply, then spends 2+ of its 6 turns falling back to search.
Separately, SYSTEM_PROMPT says an unrecognized argument is "rejected outright", which is
false: the model gets the same no-data reply as for missing data.

**Tier:** Standard, TDD. Touches `agent.py` and `prompts/` (critical core, escalated plan
review; `arch-reviewer` on Opus at code review).

## Changes since the roadmap
- **Evidence refreshed** (`trace_logs/traces.jsonl`, 2026-09-26): 160 `invalid_fiscal_year_type`
  rejections, all on `get_financial_fact`, all digit-only strings. Still live: 18 on 09-25
  (WP5 screen), 4 today (WP6 screen; the Q4 canary sent `'2026'`). 0 on
  `compare_financial_metric`; 0 string `start/end_fiscal_year`. Coercion still covers all three
  fields and both tools as the roadmap says (one helper, no extra code per field), but the
  decision file will say the compare/multi-year coverage has no live evidence yet.
- **Two commits, not one** (grouped step, like WP6): 7a coercion, 7b wording. One commit per
  model-facing change keeps the attribute step bisectable at no quota cost unless it is needed.
- **BACKLOG (c):** no `MESSAGES_VERSION`; regenerate the snapshot instead.
- **BACKLOG (b):** the dispatcher coerces first and passes the same copy to the formatter, so a
  coerced call's no-data reply reads `FY2025`, not `FY'2025'`.
- **BACKLOG (a)** (yoy no-data names the anchor period, not the missing prior year): not done
  here. All 62 live yoy calls found data, so there is no path to measure. It moves to WP8's
  Step 9 (e) follow-up list.
- **BACKLOG (d)** (rejected calls read as "no data"): this is the roadmap's own out-of-scope
  "reason-bearing rejection messages" follow-up (Step 9 (e)). It merges into that item, not
  into WP7.
- **The "so search_filings instead" BACKLOG item (WP8, Trivial)** is folded into 7b, because 7b
  rewrites that exact sentence. Its BACKLOG line is deleted at WP7's close.
- **4-digit only, not "digit-only":** a string converts only when it is exactly 4 ASCII
  digits. `"0"` or `"99999"` stay rejected, so junk doesn't reach the lookup and pollute the
  `no_data_for_ticker` telemetry `_rejects_invalid_fiscal_year` guards. All 160 live values are
  `'2025'`/`'2026'`.
- **7b wording is shorter than the roadmap's:** the sentence becomes "an unrecognized argument
  gets the same no-data reply." and drops its "so search_filings instead…" tail, which repeats
  the fallback sentence earlier in the same bullet (and was the tool-name-as-verb item). Less
  new text to screen.
- **7a gets its own fingerprint:** a snapshot scenario through the dispatcher (below), so 7a's
  behaviour change (the reply text of a coerced call) moves the fingerprint and a bisect's
  7a-only runs are labelled correctly.
- **Quota cutoff:** the screen starts only with ≥350 requests left today (screen ~200 plus
  replicate, revert-both and 7a-only passes, ~45 per flagged question, all same day). Today
  ~302 remain, so in practice the screen runs after the next 07:00 UTC reset.
- **Step 9 (f)** (rewrite the `msft-cash-to-assets-fy2025` item) is moot: that item is no longer
  in BACKLOG (pruned in `a9311e8`).

## Steps
0. **On approval:** save this plan to `docs/plans/2026-09-26-wp7-fiscal-year-strings.md` and
   its plan review to `docs/reviews/2026-09-26-wp7-fiscal-year-strings-plan-review.md`; add
   2 Recent lines (40 → 42); mark the WP7 BACKLOG line IN PROGRESS; one docs commit by path.
   `git status` is clean first.
1. **Commit 7a: coercion, TDD** (`agent.py`, `tests/test_agent.py`).
   - New `_coerce_year_args(tool: str, args: dict, fields: frozenset[str]) -> dict`, next to
     `_rejects_invalid_fiscal_year`. For each field present: if the value is a `str` of length
     4 with `value.isascii() and value.isdigit()`, set `int(value)` on a **shallow copy** and
     `log_event("tool_arg_coerced", tool=tool, field=field, value=value)`. `isascii()` matters:
     `"²".isdigit()` is true and `int("²")` raises. Returns `args` itself when nothing changed.
     Comment: the only string-to-int conversion, because Gemini sends year strings despite the
     integer schema.
   - `call_get_financial_fact` (fields `_FISCAL_YEAR_PROPS`, `agent.py:337`) and
     `call_compare_financial_metric` (fields `{"fiscal_year"}`, the only year field its schema
     has): `args = _coerce_year_args(...)` as the first line, so MCP gets it (it calls these
     directly, `mcp_server.py:144,154`).
   - `_dispatch_get_financial_fact` (`agent.py:1889`) only: coerce inside the `traced_span`
     (the span input keeps the raw args the model sent) and pass the copy to both
     `call_get_financial_fact` and `_format_no_fact_message`. The second coercion inside
     `call_*` is a no-op (already int), so the event logs once per field. The compare
     dispatcher is unchanged: `_format_no_comparison_message` never reads the year.
   - `bool`, float, `"FY2026"`, `" 2025"`, `"²"`, `"99999"`, `[2026]` stay rejected with their
     existing reasons (`invalid_fiscal_year_type`, `invalid_multi_year_average_combo`).
   - No manual repro script: the changed code is plain functions reached through `call_*` and
     `_dispatch_*` with lookups stubbed; the live check is the panel screen.
   - **Tests first**, public seams (`call_*`, `_dispatch_*`), `log_event` monkeypatched as the
     existing tests do:
     - `"2025"` is accepted by `call_get_financial_fact` (`get_metric` stubbed to record its
       `fiscal_year` → `2025` int), by `call_compare_financial_metric`, and on
       `start/end_fiscal_year`;
     - `tool_arg_coerced` is logged once per field (once, not twice, via the dispatcher);
     - the caller's `args` dict is unchanged;
     - `True`, `2026.0`, `"FY2026"`, `" 2025"`, `"²"`, `"99999"`, `[2026]` are still rejected;
     - the dispatcher's no-data reply for `fiscal_year="2025"` reads `'FY' FY2025`.
   - **Replaced deliberately** (listed in the decision file): `tests/test_agent.py:1938`
     (`…rejects_non_int_fiscal_year`), `:1957` (compare), `:1918` (multi-year string years);
     each is rewritten to a non-year string (e.g. `"FY2025"`) so the rejection path stays
     covered, and its comment is rewritten to match (`:1918`'s describes a `formulas.py`
     TypeError that a non-year string still guards against).
     `test_format_no_fact_message_string_year_stays_visible` (`:250`) stays as is: the formatter
     still shows a raw string it is given. Its comment is updated (the dispatcher now converts
     before it gets there).
   - **Snapshot:** add a `dispatch_no_fact_string_year` scenario that calls
     `agent._dispatch_get_financial_fact` with `fiscal_year="2025"` and `agent.get_metric`
     stubbed to `None` (the snapshot builder already has a monkeypatch), plus its
     `EXPECTED_KEYS` entry. Before 7a it would render `FY'2025'`; after, `FY2025`. Regenerate;
     the diff should show only the new entry. `agent` moves at 7a and again at 7b.
2. **Commit 7b: wording** (`prompts/agent_system.py:36`, `prompts/agent_tools.py:101`).
   - `an unrecognized argument is rejected outright, so search_filings instead if you need
     something this tool doesn't support.` → `an unrecognized argument gets the same no-data
     reply.`
   - `-- returns null for that combination.` → `-- that combination is rejected and reports
     no data.`
   - Snapshot red → read the diff (agent_system + tool schemas + MCP list) → regenerate.
     `agent` and `mcp` move; `judge` must not.
3. Manual checks (ruff, pyright, `pytest --cov`, `Missing` column against 90% for `agent.py`);
   `/compact` line at the boundary.
4. `independent-review-pass` over 7a..7b (Substantial by blast radius: code-review high,
   arch opus, security, simplify). Fixes committed; Review log appended to the repo plan.
5. **Screen** (Decision rule): clean tree, ≥350 requests left today counted from traces; panel
   3× (the same 13 IDs as WP5/WP6); explicit mode vs B = WP6's screen
   `20260926T073646Z/074012Z/074314Z`, agent `e073094f18b9`. If confirmed at attribute, bisect
   7a then 7b.
6. **Trace check (no cost), B vs C:** `invalid_fiscal_year_type` rejections vs
   `tool_arg_coerced` events; per coerced call, found or not and the next call; the two canaries
   (`nvda-rd-expense-q4fy26-refusal`, `pltr-inventory-turnover-fy2025-refusal`), whose correct
   outcome is still a refusal, now reached through a real lookup's no-data + Q4 / no-data reply;
   new `no_data_for_ticker` unmet-metric events from coerced lookups (expected, now real).
   Count coercions joined with that call's outcome, not alone. Reuse the WP6 script pattern (`run_agent` question → ID, tool sequence per `run_id`).
7. **Docs:** decision file (roadmap row, replaced tests, the 7a-behaviour-not-fingerprint note),
   code review file, BACKLOG: delete the WP7 line and the "so search_filings instead" line; add
   (a) and merge (d) into WP8's follow-up list (WP8's line names Step 9 (e)); index lines;
   commit reports, then docs, by path. No push.

**Authorisation on approval:** step 0 docs commit; 7a, 7b, review fixes, Decision-rule reverts,
reports and docs commits; ~200 Gemini requests for the screen plus ~25 per replicate/attribute
question.

## Out of scope
Reason-bearing rejection messages (incl. BACKLOG (d)); yoy prior-year naming (a); `calculate`'s
generic missing-argument message; MCP search's silent `[]`; MCP error strings; the all-caps
emphasis (WP8).

## Critical files
`agent.py` (`_rejects_invalid_fiscal_year`, `call_get_financial_fact`,
`call_compare_financial_metric`, `_dispatch_get_financial_fact`,
`_dispatch_compare_financial_metric`), `prompts/agent_system.py`, `prompts/agent_tools.py`,
`prompts/model_input_snapshot.json`, `tests/test_agent.py`. Reuse: `_FISCAL_YEAR_PROPS`,
`_is_valid_int`, `tracing.log_event`, the snapshot test, `compare_prompt_versions.py`, the WP6
trace-check script pattern.

## Verification
Unit tests per shape (red first); snapshot diff limited to the new dispatcher entry after 7a and
to the two spans after 7b; fingerprints (`agent`/`mcp` move at 7b, `judge` doesn't); explicit-mode screen verdict;
trace counts (rejections → coercions) in the decision file.

## Plan review (1 independent round, plan-reviewer on Opus; source for the step-0 review file)
- **Must-fix:** none.
- **Should-fix, adopted:**
  - S1: 7a changed model-visible text with no fingerprint move. Added a dispatcher snapshot
    scenario in 7a.
  - S2: the quota budget covered only the screen. The screen now starts at ≥350 requests
    left, which in practice means after a reset.
  - S3: the 7b wording departed from the roadmap without saying so, and repeated the bullet's
    fallback sentence. Shortened the wording and recorded the change above.
- **Nits, adopted:**
  - N4: coerce only each tool's own year fields, and count coercions joined with the call's
    outcome.
  - N5: accept 4-digit strings only, so junk stays rejected.
  - N6: corrected the test def line references and the `:1918` comment.
  - N7: the compare dispatcher needs no change.
  - N8: one line on why no manual repro script is needed.
- **Verified by the reviewer:**
  - the evidence counts (160 in total: 84 `'2026'`, 76 `'2025'`);
  - the need for `isascii`;
  - single logging under double coercion;
  - MCP coverage;
  - the dispositions of (a)–(d) and Step 9 (f).

## Review log

### Round 1 (`c8c2189..309d90a`, Substantial by blast radius)

Passes: `/code-review` high, `arch-reviewer` (opus), `security-reviewer`, `/simplify` (reuse,
simplification, efficiency, altitude; report-only, no edits).

1. **Med** (code-review): a whole float year (`2023.0`) passes the integer schema, and
   `get_multi_year_average`'s `range()` raises `TypeError` on it. The exception is uncaught,
   on both the agent and MCP paths (reproduced). It predates WP7, and the traces hold no float
   years. `[Fixed]`: `_coerce_year_args` also converts whole floats, so `FY2025.0` in a no-data
   reply goes too (code-review item 3). Test first (red on `float`).
2. **Low** (code-review): `[0-9]{4}` let `"0000"`/`"0999"` through as year 0/999, which is the
   junk the plan's 4-digit rule was meant to keep out. `[Fixed]`: `[1-9][0-9]{3}`; both are
   added to the still-rejected list, along with `2025.5`.
3. **Low** (code-review): the `no_fact_never_tagged` snapshot scenario still fed the formatter a
   `"2025"` string, a reply the agent can no longer send. `[Fixed]`: int `2025`; the snapshot
   diff is that one line.
4. **Nit** (code-review, simplify simplification and efficiency): `frozenset({"fiscal_year"})`
   appeared twice in `call_compare_financial_metric`. `[Fixed]`: `_COMPARE_FISCAL_YEAR_PROPS`.
5. **Nit** (arch): `test_format_no_fact_message_string_year_stays_visible`'s comment described
   a non-year string, but its input was `"2025"`. `[Fixed]`: the input is now `"FY2025"`.
6. **Low** (code-review, simplify simplification and efficiency): the conversion runs twice on
   the agent path (dispatcher, then `call_get_financial_fact`). `[Verified, no fix needed]`:
   planned. The inner call is what covers MCP, and both are pinned by tests (the dispatcher
   reply test, and the direct `call_*` tests). Returning `(fact, args)` would change a
   signature that MCP and about 40 tests use, to save one no-op scan.
7. **Low** (code-review): `tool_arg_coerced` is logged for `fiscal_year` even when a multi-year
   range makes the lookup ignore it. `[Verified, no fix needed]`: the value is still validated,
   so the conversion is real, and the Step 6 trace check joins each coercion with its call's
   outcome.
8. **Low** (code-review): `tool_call_rejected` after a conversion logs the converted args.
   `[Verified, no fix needed]`: the `tool_arg_coerced` line just before it, and the span input,
   keep the raw value.
9. **Med** (code-review): 7b's "gets the same no-data reply" drops any cue to retry without the
   invented argument. `[Verified, no fix needed]`: this is the plan's wording (it states the
   real behaviour, which "rejected outright" misstated). Reason-bearing rejections are the
   roadmap's Step 9 (e) follow-up, and the screen measures the wording.
10. **Low** (simplify, altitude): the conversion should live in `validate_tool_args` for every
    integer argument. `[Verified, no fix needed]`:
    - All 160 live string rejections are year fields. There are no string
      `citation_index`/`_a`/`_b` values in the traces.
    - The claimed crash on a string `citation_index` is false: `validate_tool_args` on
      `SUBMIT_TOOL_SCHEMA` rejects it (checked).
    - Generalizing would widen the blast radius with no evidence behind it.
11. **Nit** (simplify, reuse): `numeric_utils._BARE_YEAR_STRING` is another year regex.
    `[Verified, no fix needed]`: it serves a different purpose (a year in parentheses in
    extracted text), accepts 1900–2099 and uses `\d`, so sharing it would change one side's
    behaviour.
12. **Nit** (arch): the snapshot scenario goes through `_dispatch_tool_call` with
    `gross_margin` (stubbing `get_ratio`), not through `_dispatch_get_financial_fact` with
    `get_metric` stubbed as the plan said. `[Verified, no fix needed]`: it is the real dispatch
    path, and it is recorded here.
13. **Nit** (arch): the plan listed `2026.0` as still rejected. `[Verified, no fix needed]`: it
    was accepted before WP7 (JSON Schema treats it as an integer). With item 1 it is now
    converted to `2026` and tested. This goes in the decision file.
14. Security: no findings.

### Round 2 (delta `git diff 309d90a`, uncommitted)

Passes: `/code-review` medium, `security-reviewer`. No findings from either. (Security: a huge
whole float already passed the integer check before this change, and `get_multi_year_average`
returns at the first missing year, so converting it adds no new path.) The review closed after 2
rounds: 5 fixed, 9 verified with no fix needed, 0 deferred. Checks:
ruff 0, pyright 0, 936 passed, `agent.py` 96% with the new lines covered. Fingerprints:
`agent` `35c13d2488df` → `7aec53939ce3`; `mcp` `b34024a4d17d` and `judge` `2ee29f234c91`
unchanged.
