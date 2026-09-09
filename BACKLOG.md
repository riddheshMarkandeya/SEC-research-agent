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

## In progress

_(nothing right now)_

## Backlog

### From the 2026-09-07 review of the get_metric_all_companies redesign

- [ ] **[Low]** `formulas.py`'s `RATIO_DEFINITIONS` `supports_cross_company=False` gate (return_on_assets/asset_turnover/cash_to_assets/inventory_turnover) is justified by the same instant-frame problem the 2026-09-07 fix corrected at the `get_metric_all_companies()` layer, but `get_ratio_all_companies()` uses a separate, still frame-only path (`_compute_ratio_metric_all_companies()`), so these ratios stay blocked for cross-company comparison even though their raw legs (e.g. `total_assets`, `cash_and_equivalents`) are now individually comparable. Real gap, but a separate, larger-scope item (would need `_compute_ratio_metric_all_companies()` to compose from independent per-company legs for these 4 ratios specifically) — not a defect in that fix, no concrete question needs it yet. See `PROJECT_CONTEXT.md`'s 2026-09-07 addendum.

### From the 2026-09-06 full-codebase review

Full evidence/reasoning for each: `docs/reviews/2026-09-06-full-codebase-review.md`.
The 4 High findings are DONE — see `PROJECT_CONTEXT.md`'s matching
section (2026-09-06) and its addendum (2026-09-07: §4's first fix shipped
a real regression, found and corrected before this batch resumed).
§5/§7/§9 are also DONE — see `PROJECT_CONTEXT.md`'s 2026-09-08 section.
§6/§8/§10 are also DONE — see `PROJECT_CONTEXT.md`'s 2026-09-09 section.
§11/§12/§13 are also DONE — see `PROJECT_CONTEXT.md`'s 2026-09-10 section.

- [ ] **[Low]** `retrieval.py`'s live half has no `tests/manual/verify_*.py` script, unlike every other live-only integration point — [review §14](docs/reviews/2026-09-06-full-codebase-review.md#14-retrievalpys-live-half-has-no-manual-verification-script)
- [ ] **[Low]** `xbrl_facts.py`'s `get_frame()` cross-tag merge has an untested set-iteration-order dependency — [review §15](docs/reviews/2026-09-06-full-codebase-review.md#15-xbrlfactspys-getframe-has-an-untested-ordering-dependency)
- [ ] **[Low, design note]** `query_chunks.py` duplicates `retrieval.py`'s query logic instead of reusing it
- [ ] **[Low, design note]** `tracing.py` has two overlapping "record an instantaneous fact" primitives (`record_unmet_metric_request` vs `log_event`) with no documented decision rule for which to use

### From the 2026-09-08 layered review of the §5/§7/§9 fixes

Full evidence: `docs/reviews/2026-09-08-fix-3-medium-review-findings.md`.

- [ ] **[Low, design note]** `formulas.py` now has 3 independently-written same-shape zero-denominator guards (`get_yoy_growth`, `_compute_ratio_metric`, `_compute_ratio_metric_all_companies`) with no shared `_safe_ratio()`/zero-guard helper — CLAUDE.md's Standard-tier minimalism rule is why this diff didn't extract one; worth doing once a 4th call site needs the same guard.
- [ ] **[Low, latent, not currently reachable]** `chunk_documents.py`'s `chunk_blocks()` `current_is_only_overlap` flag would be incorrectly cleared by a hypothetical empty-string block merge (`f"{overlap}\n\n{''}".strip()` collapses back to the overlap value alone) — not currently reachable since `split_into_blocks()` only ever produces non-empty blocks, so this is a documentation-worthy assumption rather than a live bug.

### From the 2026-09-09 layered review of the §6/§8/§10 fixes

Full evidence: `docs/reviews/2026-09-09-fix-3-more-review-findings.md`.

- [ ] **[Low, design note, pre-existing]** `agent.py`'s `isinstance(x, int)` fiscal-year-type guards (`fiscal_year`, `start_fiscal_year`, `end_fiscal_year` — 3 call sites now) all accept a JSON boolean (`isinstance(True, int)` is `True` in Python), silently treating it as `0`/`1` instead of rejecting it like every other non-int value. Real but pre-existing (the `start_fiscal_year`/`end_fiscal_year` guard already had this before the §8 fix mirrored it to a third site) and low-likelihood (requires a tool-calling LLM to emit a JSON bool where an integer is expected, not the numeric-string shape these guards were actually written for) — a single cross-cutting fix (e.g. `isinstance(x, int) and not isinstance(x, bool)`) covering all 3 sites at once would be cleaner than patching them one at a time.

### From the 2026-09-10 layered review of the §11/§12/§13 fixes

Full evidence: `docs/reviews/2026-09-10-fix-3-more-review-findings.md`.

- [ ] **[Low, design note]** `_never_tagged_hint()` (called from both `_format_no_fact_message` and, as of §12, `_format_no_comparison_message`) re-fetches `xbrl_facts.fetch_concept()` for the exact (ticker, tag) pair the caller's own lookup just fetched moments earlier — normally a free disk-cache hit, but `fetch_concept()` never caches a 404 response, so on the one case this hint actually exists for (a company that genuinely never tags a concept at all) it makes a real second live SEC network round-trip synchronously inside message formatting. Root cause is in `xbrl_facts.fetch_concept()`'s caching, not in either message formatter — a separate, larger-scope item than either function's own fix.
- [ ] **[Low, latent, not currently reachable]** `tracing.py`'s `traced_span()` builds `span.error = f"{type(e).__name__}: {e}"` inside its `except` block before `raise` — if the caught exception's own `__str__` raised, that would replace the original exception instead of re-raising it, contradicting the docstring's "never swallows" claim. Not currently reachable: no exception type actually raised anywhere in this codebase (`ValueError`, `KeyError`, `requests.RequestException`, etc.) has a `__str__` that can raise.
- [ ] **[Low, design note]** Three tools now each hand-validate their own ticker/metric/fiscal_year arguments against their own `*_TOOL_SCHEMA` declarations (`call_get_financial_fact`, `call_compare_financial_metric`, and now `search_filings`'s dispatch branch), each guard discovered and patched separately across three different review dates (2026-09-06, 2026-09-09, 2026-09-10) rather than derived from the schema once. A generic schema-driven arg-validator (checking enum membership/JSON-schema type for every declared property before a tool body runs) would close this whole class of bug structurally instead of one field at a time — a Substantial-scope redesign, not a Standard-tier fix.
- [ ] **[Low, design note]** `search_filings`' unknown-ticker rejection returns a bespoke, actionable string built inline in `_dispatch_tool_call` (naming the invalid ticker and listing valid ones), while `call_get_financial_fact`/`call_compare_financial_metric` fold the same failure into their generic `_format_no_fact_message`/`_format_no_comparison_message` (which don't name the ticker as the problem). An incidental inconsistency between three sibling "unknown ticker" paths, not a bug — worth a deliberate decision later (upgrade the other two similarly, or document why search_filings needs to differ) rather than leaving it accidental.

### Carried over from `PROJECT_CONTEXT.md`'s old "Next steps" (pre-2026-09-06)

- Per-call LLM "generation" tracing (token counts, prompt/completion text, per-call cost/latency as Langfuse generation objects) — explicitly scoped out of the Langfuse tracing work, parked until a real debugging need shows up. See `PROJECT_CONTEXT.md`'s "Week 7 guardrails, part 3" section.
- Multi-turn conversational QA (ConvFinQA-style follow-ups) — `run_agent()` is single-turn only. Parked; revisit only on a real multi-turn need. See `PROJECT_CONTEXT.md`'s Next-steps history (2026-08-25).
- Graph DB (Neo4j) as a retrieval layer — parked; only worth it if a relationship/multi-hop-shaped question actually appears. See `PROJECT_CONTEXT.md` (2026-08-20 discussion).
- `cash_to_assets` ratio's citation-verification gap — `verify_citations()` doesn't check uncited numeric claims at all; no concrete failing case yet. See `PROJECT_CONTEXT.md`'s "Formula registry extended" section (2026-08-25).
- Growing the eval set further toward the original 30-50 FinanceBench-style target — optional, not a fixed requirement.
- "Week 8 — polish + write-up" — no detail scoped yet.

(HNSW index tuning was rejected outright, not parked, so it isn't carried over — see `PROJECT_CONTEXT.md` for that reasoning if needed.)
