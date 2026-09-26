# Review: WP7 plan, digit-only year strings and "rejected outright" wording (one independent plan-review round)

Plan: `docs/plans/2026-09-26-wp7-fiscal-year-strings.md`. The plan converts 4-digit year
strings to integers at the `get_financial_fact` / `compare_financial_metric` boundary (audit
finding 13: 160 live `invalid_fiscal_year_type` rejections). It also replaces SYSTEM_PROMPT's
false "rejected outright" and the yoy schema's "returns null". Screened as a grouped step
(7a coercion, 7b wording) under the roadmap's Decision rule. HEAD was `dc0a893`.

## Pass 1: self-check of the roadmap's Step 7 against HEAD `dc0a893`
- [Verified] Evidence refreshed: 160 rejections, all on `get_financial_fact`, all digit-only
  strings, still live (18 on 09-25, 4 on 09-26). None on compare or on the multi-year fields.
- [Fixed in plan] `MESSAGES_VERSION` no longer exists (BACKLOG (c)); regenerate the snapshot.
- [Fixed in plan] BACKLOG (b): the dispatcher passes its coerced copy to the formatter.
- [Moved] BACKLOG (a) (yoy prior-year naming; 0 of 62 live yoy calls missed) and (d)
  (reason-bearing rejection replies, already the roadmap's Step 9 (e)) go to WP8's follow-ups.
- [Moot] Step 9 (f): the `msft-cash-to-assets-fy2025` item is no longer in BACKLOG.

## Round 1: plan-reviewer (Opus; escalated for `agent.py` and `prompts/`)

**Must-fix:** none.

**Should-fix, all adopted:**
- **S1: 7a changed model-visible text with no fingerprint move.** The only string-year
  snapshot scenario calls the formatter directly, bypassing the dispatcher. A bisect's 7a-only
  runs would carry B's fingerprint. The plan now adds a dispatcher snapshot scenario in 7a.
- **S2: the quota budget covered only the screen.** A replicate, a revert-both pass and a
  7a-only bisect pass must all run the same day, about 45 requests per flagged question. The
  screen now starts only with at least 350 requests left.
- **S3: the 7b wording departed from the roadmap without saying so,** and its "so
  search_filings instead" tail repeats the bullet's earlier fallback sentence. The plan now
  uses the shorter "an unrecognized argument gets the same no-data reply." and records the
  change.

**Nits, all adopted:**
- N4: coerce only each tool's own year fields (compare has only `fiscal_year`), and count
  coercions joined with the call's outcome.
- N5: accept only 4-digit strings, so `"0"` and `"99999"` stay rejected and don't pollute the
  unmet-metric telemetry.
- N6: corrected the test definition line references, and the rewritten multi-year test's
  comment gets updated too.
- N7: the compare dispatcher needs no change, because its formatter never reads the year.
- N8: one line on why no manual repro script is needed.

**Verified by the reviewer:**
- the evidence counts (84 `'2026'`, 76 `'2025'`);
- the `isascii` need (`"²".isdigit()` is true);
- single logging under double coercion;
- MCP coverage through the `call_*` functions;
- the Recent count.
