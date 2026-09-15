# Review: Comment audit Round 1 (self + fresh subagent)

Plan: `docs/plans/2026-09-14-comment-audit-round1.md`.

## Pass 1 — correctness and compliance (self, low-medium effort)

Every pointer added was verified by reading the actual target
`docs/decisions/*.md` file before writing it (not trusted from the
inventory blindly). `period_labels.py`'s module docstring correction
(the retrieval-indexing use of the period-label string was tried and
reverted, not current behavior) was cross-checked against
`index_chunks.py`'s own comment and the relevant decision file. Full
diff read confirmed comment/docstring-only changes across all 6 files.
Full pytest suite: 634 passed (matches baseline). No findings.

## Pass 2 — architecture/design/refactor (fresh subagent, no memory of the implementation session)

1. **Pointer correctness — PASS.** All 14 distinct `docs/decisions/*.md`
   references checked against their actual content; all accurate,
   including one pair of near-identically-named files
   (`2026-09-10-fix-3-more-review-findings.md` vs.
   `2026-09-09-fix-3-more-review-findings.md`) that was easy to confuse
   and wasn't.
2. **Information loss — one soft spot found.** `mcp_server.py`'s module
   docstring lost the operationally relevant explanation of *why* only
   `search_filings` gets a Scroll-To-Text-Fragment anchor
   (`get_financial_fact`/`compare_financial_metric` come from structured
   XBRL data with no prose position to anchor to) — a "why does tool A
   behave differently from B" fact worth keeping inline, not just
   decision history.
3. **Style consistency — inconsistent in one respect.** Several `"Found
   in code review."` tags were deleted with no pointer substituted
   (`mcp_server.py`'s `_is_authorized`/`_RateLimiter`/`rate_limited`
   log_event comments; `tracing.py`'s mkdir-caching/failure-reset/
   `monotonic()` comments), even though matching decision docs exist for
   all of them and a sibling comment in the same file did get a pointer.
4. **`period_labels.py` docstring correction — verified accurate**
   independently against `index_chunks.py` and the decision file; no new
   inaccuracy introduced.
5. **Leftovers — none significant.** Two short dated functional labels
   left in place (`config.py`'s "Week 7 guardrails" tags, `mcp_server.py`'s
   "2026-09-07 redesign" clause) are defensible as labels, not narration.
6. **Scope discipline — PASS.** Only the 6 files plus `BACKLOG.md`/
   `PROJECT_INDEX.md` changed; every changed line is a `#` comment or
   inside a `"""..."""` block.

## Fixes applied

- Restored the scroll-to-text-fragment WHY to `mcp_server.py`'s module
  docstring, condensed to one clause rather than the original paragraph.
- Added the missing pointer to the 6 comments finding #3 identified,
  for consistency with sibling comments in the same files:
  `mcp_server.py`'s `_is_authorized` and `_RateLimiter.allow` comments →
  `docs/decisions/2026-09-01-mcp-server-auth-rate-limiting.md`;
  `mcp_server.py`'s `rate_limited` log_event comment and `tracing.py`'s
  three `_write_local_log`/`traced_span` comments →
  `docs/decisions/2026-09-05-local-only-debug-events.md` and
  `docs/decisions/2026-09-05-local-jsonl-trace-log.md` respectively.
- Re-ran the full diff-scope check and pytest suite after applying
  fixes: still comment-only, still 634 passed.

## Outcome

Two real, actionable findings (#2, #3), both fixed the same pass.
Findings #1, #4, #5, #6 confirmed clean, no action needed. No second
review round needed — both fixes were small, mechanical, and verified
immediately.
