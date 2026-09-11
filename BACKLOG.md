# Backlog

Tracks open work: what's queued, what's in progress. This is **not** a
changelog — completed work's rationale and verification live in
`PROJECT_CONTEXT.md` (and, for Substantial work, its own design doc
under `docs/plans/`). Link out to the relevant doc instead of
re-explaining reasoning here; keep entries short.

**Keep this current as work happens, not just at session-end**: add a
line the moment a new open item is identified (a deferred idea, a
found-but-not-fixed bug, a follow-up) — don't wait for a wrap-up. Move
an item to "In progress" when you start it. When it's done, remove it
from here *and* land its `PROJECT_CONTEXT.md` changelog entry in the
same step — an item should never just vanish from this file with no
changelog trace of what happened to it.

This file replaces `PROJECT_CONTEXT.md`'s old "Next steps" section,
which needed its own 380-line cleanup pass once already (2026-08-19)
from exactly this kind of bloat — don't let this file suffer the same
fate; prune it as items resolve.

## How to read an item

Every bullet is tagged **[type, priority, effort]** — see CLAUDE.md's
"Backlog tagging convention" (step 6) for the full definitions. Quick
reference:

- **Type**: `bug` · `refactor` · `feature` · `performance` ·
  `test-coverage` · `design` · `misc` — `(latent)` after `bug` means
  real but not currently triggered by any live code path.
- **Priority**: `Low` / `Med` / `High` — urgency, independent of type.
- **Effort**: `Trivial` / `Standard` / `Substantial` — this repo's own
  CLAUDE.md tiers; also signals how much process applies once picked
  up. `TBD` when the item hasn't been scoped enough to size yet.

## In progress

_(nothing right now)_

## Backlog

### From the 2026-09-10 citation-gate-measurement-instrumentation plan

Full evidence/reasoning: `docs/plans/2026-09-10-citation-gate-measurement-instrumentation.md`.

- [ ] **[bug, High, Standard]** `_SENTENCE_BREAK`'s abbreviation exception only excludes a *lowercase* follow-on word (`U.S. sales`); a capitalized follow-on (`U.S. GAAP`, `U.S. Treasury`) still registers a sentence break, so a claim immediately followed by `, as reported under U.S. GAAP [1].` reads as unreachable from its own marker and gets wrongly refused. Confirmed live twice: directly by executing the regex (`'Revenue was $5 billion, as reported under U.S. GAAP [1].'` breaks at index 45), and end-to-end via `eval/citation_stress_questions.jsonl`'s `nvda-revenue-fy26-us-gaap` (Gemini's real answer: `"NVIDIA's total revenue for fiscal year 2026 was $215,938 million, presented in accordance with U.S. GAAP [3]."`, refused; `analyze_citation_gate.py` correctly classifies it `false_positive`/`uncited_claim`). Deliberately not fixed yet — this question is the acceptance test for the FP/FN instrumentation itself.
- [ ] **[bug (latent), Low, Trivial]** `_NON_CLAIM_PATTERN` doesn't cover a footnote-style `Note N` reference (e.g. `"Note 1, \"Organization and Summary...\""`), so the bare `1` parses as a spurious `claims 1.0 (raw)` uncited claim -- the same noise shape as the existing `10-K`/`10-Q` exclusion, just for a different filing convention. Found live verifying `nvda-revenue-fy26-us-gaap` (an earlier wording variant): Gemini's answer cited NVIDIA's 10-K "Note 1" by name and each digit in "Note 1"/"Note 2"/"Note 3" tripped the uncited-claim check. Low priority: cosmetic noise alongside a real warning, not a standalone false gate-fire in the case observed.
- [ ] **[bug, Med, Trivial]** `_CITATION_MARKER = re.compile(r"\[(\d+)\]")` does not match a comma-separated multi-source bracket like `[1, 2, 3]` at all (only `[1]`, `[2]`, `[3]` as three separate brackets) -- an answer using that format is invisible to BOTH citation checks, i.e. every claim in it reads as having no citation whatsoever, and the individual digits inside the malformed bracket are themselves picked up as spurious bare-number claims (see `crm-buyback-and-liquidity-q1fy27` below). Confirmed live in TWO independent runs, upgraded from latent to a real, recurring bug: (1) verifying `nvda-revenue-fy26-us-gaap` (an earlier wording variant), Gemini's answer ended `"...prepared in conformity with U.S. GAAP [1, 2, 3]."`; (2) the 41-question baseline's `crm-buyback-and-liquidity-q1fy27` (2026-09-10, see `docs/plans/2026-09-10-citation-gate-measurement-instrumentation.md`), `"...the Board authorized $50.0 billion in share repurchases [1, 5]..."` -- the `$50.0 billion` and the bare `1`/`5` inside the brackets all misfired as uncited claims. The system prompt (`agent.py`'s rule 8) only specifies the `[1][2]` adjacent-brackets format for the cross-company case; single-company multi-source citation format is unspecified, so this isn't a model error to correct via prompting alone -- the checker should recognize the format too.
- [ ] **[bug, Med, Trivial]** `_NON_CLAIM_PATTERN`/`extract_numbers` has no exclusion for a number embedded in an ordinal/count phrase like `"3-year"` (`"5-day"`, `"10-year"`, etc., same shape) -- `"3-year"` parses as a bare `claims 3.0 (raw)` claim, exactly the noise pattern the existing `10-K`/`10-Q` exclusion covers for filing-form mentions, just for a different common phrase. Confirmed live: the 41-question baseline's `aapl-3yr-avg-operating-margin-fy2023-fy2025` (2026-09-10) answered `"Apple's 3-year average operating margin from fiscal year 2023 through fiscal year 2025 was **31.1%** [1]."` -- the genuinely correct, correctly-cited 31.1% figure was refused because the unrelated `3` from `3-year`, sitting in the same backward window, got attributed to `[1]` too and (correctly, on ITS OWN terms) flagged as not appearing in the source. A textbook false positive: the actual claim was fine, an incidental number in the question's own echoed phrasing was not.
- [ ] **[feature, Med, Substantial]** Replace the uncited-claim heuristic with model-emitted structured claims (a `submit_answer` tool whose parameter schema carries the claims array) — Gemini can't combine `response_schema` with function calling, so a tool schema is the structured-output mechanism. Parked until the FP/FN baseline exists.
- [ ] **[feature, Low, Standard]** Model-based veto before refusal (one entailment check before the hard gate withholds an answer) — sized against whatever false-positive rate the instrumentation measures; not worth building blind.
- [ ] **[design, Low, Trivial]** `eval/citation_stress_questions.jsonl`'s separation from the main `eval/eval_questions.jsonl` (so stress questions don't skew the headline pass rate) is convention-only, not enforced in code — `analyze_citation_gate.py`'s `load_rows()` will pool any report paths it's given, and nothing marks a report or row as "from the stress set." Fine as long as the two are always run/analyzed as documented; would silently stop being fine if someone merges the files or forgets which reports came from which. Found in the 2026-09-10 instrumentation work's architecture review.
- [ ] **[test-coverage, Low, Standard]** No script reads `trace_logs/traces.jsonl` — it's a grep-by-hand file. Only worth building if the live-path `citation_gate_refused` events turn out to need routine review.
- [ ] **[design, Med, Standard]** `value_is_citation_verified` treats "no citation at all" as verified (`True`), so a correct-but-uncited value and a correct-and-cited value are indistinguishable to the eval grader — this makes the FP/FN measurement's "would have passed" test conflate two different senses of "fine." Needs a deliberate decision once real numbers are in hand, not a silent fix.
- [ ] **[bug (latent), Low, Standard]** `_run_agent_impl`'s citation-retry fallback path (`pre_retry_answer`, added 2026-08-24) can pair STALE warnings with a GROWN `all_results`: if the retry's follow-up turn makes further tool calls (appending to the same mutable `all_results` list) before hitting `MAX_TOOL_ITERATIONS`, the final `_finalize_answer(answer, warnings, all_results, ...)` call uses `warnings` computed back when `all_results` was smaller. `_iter_citation_claims`'s `1 <= n <= len(all_results)` bound check means a citation index originally out-of-range (silently skipped) can become in-range against a chunk the model never actually saw when it wrote that answer. Pre-existing in `_run_agent_impl`, not introduced by the 2026-09-10 instrumentation work — but that work's `eval_harness._citation_gate_evidence()` re-derives `citation_warning_details` via a fresh `collect_citation_warnings(withheld_answer, retrieved)` call against the (grown) `retrieved`, so in this narrow scenario it could disagree with the row's own `citation_warnings` (computed against the smaller snapshot). Doesn't affect the FP/FN pass/fail classification itself (that's `grade_numeric`/`grade_comparison`-based, untouched by this), only the diagnostic `false_positive_by_check` breakdown in that one rare fallback path. Found in code review, 2026-09-10 (see `docs/reviews/2026-09-10-citation-gate-measurement-instrumentation.md`).

### From the 2026-09-07 review of the get_metric_all_companies redesign

- [ ] **[feature, Low, Standard]** `formulas.py`'s `RATIO_DEFINITIONS` `supports_cross_company=False` gate (return_on_assets/asset_turnover/cash_to_assets/inventory_turnover) is justified by the same instant-frame problem the 2026-09-07 fix corrected at the `get_metric_all_companies()` layer, but `get_ratio_all_companies()` uses a separate, still frame-only path (`_compute_ratio_metric_all_companies()`), so these ratios stay blocked for cross-company comparison even though their raw legs (e.g. `total_assets`, `cash_and_equivalents`) are now individually comparable. Real gap, but a separate, larger-scope item (would need `_compute_ratio_metric_all_companies()` to compose from independent per-company legs for these 4 ratios specifically) — not a defect in that fix, no concrete question needs it yet. See `PROJECT_CONTEXT.md`'s 2026-09-07 addendum.

### From the 2026-09-06 full-codebase review

Full evidence/reasoning for each: `docs/reviews/2026-09-06-full-codebase-review.md`.
The 4 High findings are DONE — see `PROJECT_CONTEXT.md`'s matching
section (2026-09-06) and its addendum (2026-09-07: §4's first fix shipped
a real regression, found and corrected before this batch resumed).
§5/§7/§9 are also DONE — see `PROJECT_CONTEXT.md`'s 2026-09-08 section.
§6/§8/§10 are also DONE — see `PROJECT_CONTEXT.md`'s 2026-09-09 section.
§11/§12/§13 are also DONE — see `PROJECT_CONTEXT.md`'s 2026-09-10 section.
§14/§15 are also DONE — see `PROJECT_CONTEXT.md`'s 2026-09-09/10 section.

- [ ] **[refactor, Low, Standard]** `query_chunks.py` duplicates `retrieval.py`'s query logic instead of reusing it
- [ ] **[design, Low, Standard]** `tracing.py` has two overlapping "record an instantaneous fact" primitives (`record_unmet_metric_request` vs `log_event`) with no documented decision rule for which to use

### From the 2026-09-08 layered review of the §5/§7/§9 fixes

Full evidence: `docs/reviews/2026-09-08-fix-3-medium-review-findings.md`.

- [ ] **[refactor, Low, Standard]** `formulas.py` now has 3 independently-written same-shape zero-denominator guards (`get_yoy_growth`, `_compute_ratio_metric`, `_compute_ratio_metric_all_companies`) with no shared `_safe_ratio()`/zero-guard helper — CLAUDE.md's Standard-tier minimalism rule is why this diff didn't extract one; worth doing once a 4th call site needs the same guard.
- [ ] **[bug (latent), Low, Trivial]** `chunk_documents.py`'s `chunk_blocks()` `current_is_only_overlap` flag would be incorrectly cleared by a hypothetical empty-string block merge (`f"{overlap}\n\n{''}".strip()` collapses back to the overlap value alone) — not currently reachable since `split_into_blocks()` only ever produces non-empty blocks, so this is a documentation-worthy assumption rather than a live bug.

### From the 2026-09-10 layered review of the §11/§12/§13 fixes

Full evidence: `docs/reviews/2026-09-10-fix-3-more-review-findings.md`.

- [ ] **[performance, Low, Standard]** `_never_tagged_hint()` (called from both `_format_no_fact_message` and, as of §12, `_format_no_comparison_message`) re-fetches `xbrl_facts.fetch_concept()` for the exact (ticker, tag) pair the caller's own lookup just fetched moments earlier — normally a free disk-cache hit, but `fetch_concept()` never caches a 404 response, so on the one case this hint actually exists for (a company that genuinely never tags a concept at all) it makes a real second live SEC network round-trip synchronously inside message formatting. Root cause is in `xbrl_facts.fetch_concept()`'s caching, not in either message formatter — a separate, larger-scope item than either function's own fix.
- [ ] **[bug (latent), Low, Trivial]** `tracing.py`'s `traced_span()` builds `span.error = f"{type(e).__name__}: {e}"` inside its `except` block before `raise` — if the caught exception's own `__str__` raised, that would replace the original exception instead of re-raising it, contradicting the docstring's "never swallows" claim. Not currently reachable: no exception type actually raised anywhere in this codebase (`ValueError`, `KeyError`, `requests.RequestException`, etc.) has a `__str__` that can raise.
- [ ] **[design, Low, Standard]** `search_filings`' unknown-ticker rejection returns a bespoke, actionable string built inline in `_dispatch_tool_call` (naming the invalid ticker and listing valid ones), while `call_get_financial_fact`/`call_compare_financial_metric` fold the same failure into their generic `_format_no_fact_message`/`_format_no_comparison_message` (which don't name the ticker as the problem). An incidental inconsistency between three sibling "unknown ticker" paths, not a bug — worth a deliberate decision later (upgrade the other two similarly, or document why search_filings needs to differ) rather than leaving it accidental. Still stands after the 2026-09-09 schema-validator redesign — `validate_tool_args` deliberately preserved this asymmetry rather than resolving it (out of scope for that change).

### From the 2026-09-09 schema-driven arg-validation redesign

Full evidence/reasoning: `docs/plans/2026-09-09-schema-driven-arg-validation.md`, `docs/reviews/2026-09-09-schema-driven-arg-validation.md`. Surfaced while auditing the codebase for other schema-validation opportunities, or by that change's own two-pass review — real but lower-severity than what that change fixed, not addressed there.

- [ ] **[bug (latent), Low, Standard]** `xbrl_facts.py`'s `get_metric()` does unchecked `entry["val"]`/`entry["end"]`/`entry["form"]`/`entry["accn"]` indexing on SEC API response entries after `_pick_entry*` filters them — a SEC schema change or odd entry would raise a raw `KeyError` from inside XBRL-parsing internals instead of a clear error. Lower priority than the fixed items: SEC's schema is stable and the surrounding fetch/cache code is already fairly defensive.
- [ ] **[bug, Low, Trivial]** `eval_harness.py`'s `_select_questions` reads `q["id"]` before the per-question `try/except` in `run_eval()` that already contains most other malformed-question crashes — one malformed question entry still crashes the whole eval batch instead of just failing that question. Narrow, low-traffic (offline eval tool, not a live path).
- [ ] **[refactor, Low, Standard]** `_dispatch_tool_call`'s `search_filings` branch re-derives ticker validity by hand (`isinstance`/`COMPANIES` membership) a second time, after `validate_tool_args` already checked the same thing internally via the schema, purely to decide which rejection message to show — a residual instance of the same "hand-rolled check duplicating the schema" pattern this redesign otherwise eliminated. Found in the redesign's own architecture-review pass; not fixed there because a clean fix means changing `validate_tool_args`'s return type across all 4 call sites for a 2-line message-selection convenience, out of proportion to that change.

### Carried over from `PROJECT_CONTEXT.md`'s old "Next steps" (pre-2026-09-06)

- [ ] **[feature, Low, Substantial]** Per-call LLM "generation" tracing (token counts, prompt/completion text, per-call cost/latency as Langfuse generation objects) — explicitly scoped out of the Langfuse tracing work, parked until a real debugging need shows up. See `PROJECT_CONTEXT.md`'s "Week 7 guardrails, part 3" section.
- [ ] **[feature, Low, Substantial]** Multi-turn conversational QA (ConvFinQA-style follow-ups) — `run_agent()` is single-turn only. Parked; revisit only on a real multi-turn need. See `PROJECT_CONTEXT.md`'s Next-steps history (2026-08-25).
- [ ] **[feature, Low, Substantial]** Graph DB (Neo4j) as a retrieval layer — parked; only worth it if a relationship/multi-hop-shaped question actually appears. See `PROJECT_CONTEXT.md` (2026-08-20 discussion).
- [ ] **[test-coverage, Low, Standard]** Growing the eval set further toward the original 30-50 FinanceBench-style target — optional, not a fixed requirement.
- [ ] **[misc, Low, TBD]** "Week 8 — polish + write-up" — no detail scoped yet.

(HNSW index tuning was rejected outright, not parked, so it isn't carried over — see `PROJECT_CONTEXT.md` for that reasoning if needed.)
