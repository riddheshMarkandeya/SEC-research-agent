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

- [ ] **[bug, Low, Standard]** `_SENTENCE_BREAK`'s abbreviation exception only excludes a *lowercase* follow-on word (`U.S. sales`); a capitalized follow-on (`U.S. GAAP`, `U.S. Treasury`) still registers a sentence break. Downgraded from High/Trivial and re-scoped 2026-09-10: this only matters on the prose-verification fallback path now (the structured-claims `submit_answer` path added that day doesn't parse prose at all), and Gemini rarely takes that path — the live re-measurement (`docs/plans/2026-09-10-structured-claims-citation-verification.md`) confirmed `nvda-revenue-fy26-us-gaap`, the original repro, now passes cleanly via the structured path. Still real for Ollama (no forcing mechanism, prose fallback is its normal path) or a Gemini forced-submit exhaustion — fix if it recurs there.
- [ ] **[bug, Low, Standard]** `_CITATION_MARKER = re.compile(r"\[(\d+)\]")` does not match a comma-separated multi-source bracket like `[1, 2, 3]`. Downgraded from Med/Trivial 2026-09-10 and now genuinely fallback-path-only: the 41-question baseline re-run initially found this ALSO hit the new structured path (`verify_claims`'s coverage check extracted bare digits out of `[1, 3, 5]`/`[1, 17]` brackets as spurious uncovered numbers -- `crm-revenue-q1fy27`, `msft-net-income-fy2025-indirect`), fixed same day via a separate `_ANY_CITATION_BRACKET` pattern used only by that check (`_CITATION_MARKER` itself is untouched -- the old prose pipeline reads its single capture group as one index and can't just have the pattern widened). `_CITATION_MARKER` itself, and the prose fallback path that still uses it directly, remains unfixed.
- [ ] **[feature, Low, Standard]** Model-based veto before refusal (one entailment check before the hard gate withholds an answer) — deferred 2026-09-10 pending the structured-claims redesign's own measurement. Re-evaluated 2026-09-11 with the full 41-question baseline + 4-question stress set now analyzed: **0/45 gate fires post-redesign**, down from 6/45 (100% false positive) pre-redesign. Still no evidence a veto is needed — there's nothing left for it to overturn in this corpus. Revisit only if a wider/harder question set finds the gate firing again.
- [ ] **[design, Low, Trivial]** `eval/citation_stress_questions.jsonl`'s separation from the main `eval/eval_questions.jsonl` (so stress questions don't skew the headline pass rate) is convention-only, not enforced in code — `analyze_citation_gate.py`'s `load_rows()` will pool any report paths it's given, and nothing marks a report or row as "from the stress set." Fine as long as the two are always run/analyzed as documented; would silently stop being fine if someone merges the files or forgets which reports came from which. Found in the 2026-09-10 instrumentation work's architecture review.
- [ ] **[test-coverage, Low, Standard]** No script reads `trace_logs/traces.jsonl` — it's a grep-by-hand file. Only worth building if the live-path `citation_gate_refused` events turn out to need routine review.
- [ ] **[test-coverage, Low, Standard]** `eval/citation_stress_questions.jsonl`'s 4 questions were purpose-built for the prose-heuristic bugs the 2026-09-10 structured-claims redesign structurally eliminated (2 of the 4 now pass trivially and no longer stress anything). Write a new stress set targeting the *new* verifier's actual failure modes instead: a heavily paraphrased quote sitting near the 0.90 coverage threshold, a number stated in `answer_text` with no matching entry in `claims`, and a chunk containing both the asked-for period and a prior period (to stress `_number_candidates`' same-sentence value attribution). See `docs/plans/2026-09-10-structured-claims-citation-verification.md`.
- [ ] **[design, Low, Standard]** Two hard multi-entity questions (`nvda-revenue-two-quarter-comparison`, a 5-company gross-margin comparison tried ad hoc) exhausted the 6-turn tool budget without answering, and a self-computed-ratio question (`aapl-rd-pct-gross-profit-fy2025`) got both raw inputs correctly cited but never computed/stated the ratio itself. Confirmed 2026-09-10 these are model tool-choice/reasoning limitations, not citation-gate bugs — `gate_withheld_would_have_passed` is `None` on all of them (the gate never fired). Not sized or scoped yet; would need prompt-engineering or a dedicated ratio tool, not a verifier change.
- [ ] **[design, Med, Standard]** `msft-cash-to-assets-fy2025` (41-question baseline, 2026-09-11): the model correctly cited its two raw inputs ($30,242M cash `[1]`, $619,003M total assets `[2]`) but then computed "approximately 4.89%" by hand in `answer_text` with NO corresponding `claims` entry -- system-prompt rule 9 (updated 2026-09-10 specifically for this case) says a self-computed value must still get a claim quoting the inputs it came from, and the model didn't do that here despite the rule existing. `gate_withheld_would_have_passed=True` (the 4.89% figure was itself correct), so this measures as a false positive, but the refusal is arguably the gate doing exactly its job -- the *number* being right doesn't mean the *answer* was properly grounded per this project's own stated rule. One observed instance -- an immediate full-baseline re-run had this exact question (`msft-cash-to-assets-fy2025`) pass cleanly with a proper claim for the computed value, so this looks like model non-determinism rather than a persistent gap (see the `nvda-cost-of-revenue-fy2026` item below for the same pattern on a different question) -- re-check if it recurs before deciding whether this needs a rule-9 wording tweak or a claims-array relaxation (e.g. letting one claim cover a derived value by citing its inputs' claims instead of quoting the derived number itself).
- [ ] **[bug (latent), Low, Standard]** `nvda-cost-of-revenue-fy2026` (41-question baseline, 2026-09-11): one run answered via `search_filings` prose (citing `[13]`) and got a `quote_not_found` refusal; an immediate manual re-run of the identical question instead went through `get_financial_fact` (the structured XBRL path) and answered cleanly with zero warnings -- model tool-choice is non-deterministic across runs for this question, and the exact failing quote/source pair from the original run wasn't captured anywhere (the `CitationWarning` message doesn't include the quote text itself, only the citation index), so this couldn't be reproduced to confirm whether `_quote_matches` has a real gap against dense filing-table prose or the model's original quote was simply wrong. Marked latent, not a confirmed bug: needs either a repro with the actual failing quote+source captured, or richer logging (the new `traced_span("tool", "submit_answer", ...)` added 2026-09-11 does capture `checks` in its span output going forward -- check Langfuse/`trace_logs/traces.jsonl` next time this recurs before spending more live-question budget chasing it blind).
- [ ] **[design, Low, Standard]** `nvda-gross-margin-fy26` (41-question baseline, 2026-09-11): the model correctly stated 71.1% with a valid claim `[1]`, then added a second, redundant claim re-deriving the same figure ("...or 71.1 expressed as a percentage of revenue in its Consolidated Statements of Income) `[18]`") whose quote doesn't literally contain "71.1" (it's a derived restatement, not a direct source quote) -- `_verify_one_claim` correctly fails that second claim, but `verify_claims`'s all-or-nothing design means one bad redundant claim refuses an otherwise fully-grounded answer. Not clearly a code bug (the second claim genuinely doesn't verify) or clearly a system-prompt gap (rule 9 doesn't currently address a model restating an already-cited value a second way) -- needs a decision once this pattern is confirmed to recur: tighten rule 9 to discourage redundant restatement claims, or relax `verify_claims` to tolerate a claim that duplicates an already-verified value under a different citation. Didn't recur in an immediate re-run (that run failed the same question a different way -- tool-budget exhaustion, not a gate refusal -- consistent with general model non-determinism on this question, not a persistent gate gap).

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
