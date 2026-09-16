# Backlog

Tracks open work: what's queued, what's in progress. This is **not** a
changelog — completed work's rationale and verification live in
`docs/decisions/YYYY-MM-DD-<slug>.md` (and, for Substantial work, its
own paired design doc under `docs/plans/`), indexed from
`PROJECT_INDEX.md`. Link out to the relevant decision/plan/review file
instead of re-explaining reasoning here; keep entries short.

**Keep this current as work happens, not just at session-end**: add a
line the moment a new open item is identified (a deferred idea, a
found-but-not-fixed bug, a follow-up) — don't wait for a wrap-up. Move
an item to "In progress" when you start it. **When an item is done,
delete its line entirely** — no strikethrough, no "resolved" annotation
left behind — and land its `docs/decisions/` write-up in the same step,
with an index line added to `PROJECT_INDEX.md`. If only part of a
multi-part item is resolved, rewrite the line to describe only the
remaining open part, with no decorated hybrid of done-and-not-done. An
item should never just vanish from this file with no decision-file trace
of what happened to it.

This file replaces the project's former narrative changelog's old "Next
steps" section, which needed its own 380-line cleanup pass once already
(2026-08-19) from exactly this kind of bloat — don't let this file
suffer the same fate; prune it as items resolve.

## How to read an item

Every bullet is tagged **[type, priority, effort]** — see the
`documentation-backlog-hygiene` skill's "Backlog tagging convention" for
the full definitions. Quick
reference:

- **Type**: `bug` · `refactor` · `feature` · `performance` ·
  `test-coverage` · `design` · `misc` — `(latent)` after `bug` means
  real but not currently triggered by any live code path.
- **Priority**: `Low` / `Med` / `High` — urgency, independent of type.
- **Effort**: `Trivial` / `Standard` / `Substantial` — this repo's own
  CLAUDE.md tiers; also signals how much process applies once picked
  up. `TBD` when the item hasn't been scoped enough to size yet.

## In progress

(none right now — see "Backlog" below for open items)

## Backlog

### From the 2026-09-15 broader ruff rule-category survey

Full evidence/reasoning: `docs/decisions/2026-09-15-expand-ruff-plr-rules.md`'s
Related section; raw findings not yet written up in their own decision
file pending which (if any) get adopted. Reproduce with
`ruff check --select B,SIM,UP,C4,RUF,ARG,RET,PERF,S,N,A,PTH,ERA,I .`

- [ ] **[design, Med, TBD]** Whether to select `S113`
  (request-without-timeout) and/or `B905` (zip-without-explicit-strict).
  Both surveyed with real hit counts, unlike a name-based guess:
  `S113` found 5 real production HTTP calls with no timeout at all
  (`discover_tags.py:62`, `edgar_ingest.py:56,89`,
  `xbrl_facts.py:127,341`) — a stalled SEC EDGAR response could hang the
  agent indefinitely; `B905` found 3 real `zip()` calls in the retrieval
  path (`query_chunks.py:97`, `retrieval.py:166,219`) that would
  silently truncate instead of erroring if Chroma ever returned
  mismatched-length document/metadata/distance lists. Rejected from the
  same survey, each for a specific reason rather than by category
  reputation: `S101`/`ARG001`/`ARG005`/`RUF059`/`B011` are 96-100%
  idiomatic test-file noise (asserts, mock-signature params, tuple
  unpacking) even where a handful of real hits exist; `ERA001` false-
  positives on this project's own comment-banner/decision-file-pointer
  conventions; `RET503` would push toward adding provably-unreachable
  dead code to satisfy the linter, contradicting the project's own
  error-handling philosophy; `RUF003` and a dozen other 1-4-hit codes
  weren't worth the selected-rule overhead at that volume.

### From the 2026-09-15 CLAUDE.md restructure

Full evidence/reasoning: `docs/decisions/2026-09-15-claude-md-restructure.md`.

- [ ] **[bug, Low, Standard]** `scripts/check_docs_sync.py`'s `PreToolUse`
  hook only reliably catches the docs/index staging mismatch when `git
  add` and `git commit` are separate tool calls — a single chained
  `git add -A && git commit -m "..."` is checked against whatever was
  already staged *before* that command runs (the hook fires pre-execution),
  so it can miss the mismatch in that form. Documented, not fixed.

### From the 2026-09-15 ruff adoption

Full evidence/reasoning: `docs/decisions/2026-09-15-adopt-ruff-linter.md`.

- [ ] **[refactor, Low, Substantial]** 155-violation pre-existing lint
  baseline, not fixed on adoption (deliberately — see the decision
  file). `E501` (144) is mostly deliberate long system-prompt/tool-
  schema strings and single-line test-fixture dicts, low value to
  fix. The genuine modularity findings (11 total): `agent.py`'s
  `call_get_financial_fact`/`call_calculate`/`_dispatch_tool_call`/
  `_run_agent_impl` (all `C901` excess-complexity; the last also trips
  `PLR0912`/`PLR0915`), `formulas.py`'s and `tests/test_agent.py`'s one
  `PLR0913` each (too-many-arguments), and
  `tests/manual/verify_period_labels.py`'s `main` (`C901`). Fix
  opportunistically per the incremental-improvement policy whenever
  one of these functions is next touched, not as a dedicated pass.
- [ ] **[misc, Low, TBD]** Migrate `ruff` from changed-files-scoped
  manual review to a hard pre-commit gate (alongside the existing
  pytest hook) once enough of the codebase is clean that a full-repo
  run wouldn't be dominated by the baseline above. Migrate alongside
  `pyright`'s own equivalent item below, not separately.

### From the 2026-09-15 pyright adoption

Full evidence/reasoning: `docs/decisions/2026-09-15-adopt-pyright.md`.

- [ ] **[refactor, Low, Standard]** 117-error pre-existing basic-mode
  `pyright` baseline, not fixed on adoption (deliberately — see the
  decision file). Entirely in test files (110: `test_formulas.py`,
  `test_xbrl_facts.py`, `test_agent.py`, `test_llm_backends.py`,
  `test_mcp_server.py`, `test_edgar_ingest.py`) and manual verify
  scripts (7: `verify_mcp_server.py`, `verify_tracing.py`,
  `verify_period_labels.py`) — mostly `reportOptionalSubscript`/
  `reportOptionalMemberAccess` noise from mocks/fixtures, not core-module
  gaps (all 7 core modules plus `tracing.py` are clean). Fix
  opportunistically whenever one of these test files is next touched.
- [ ] **[misc, Low, TBD]** Migrate `pyright` from changed-files-scoped
  manual review to a hard pre-commit gate (alongside `ruff`'s own
  equivalent item above and the existing pytest hook) once enough of the
  codebase is clean that a full-repo run wouldn't be dominated by the
  baseline above.
- [ ] **[design, Low, TBD]** Revisit Pyright **strict** mode. Rejected
  on 2026-09-15 adoption: real baseline was 4,655 errors, ~94% Unknown-
  type-propagation noise from this codebase's dict-shaped data flow
  (bare `dict`/`list` returns, third-party calls with no stubs), not
  real gaps — see the decision file's full category breakdown. Worth
  retrying only after either (a) a real reduction in untyped-dict data
  flow (e.g. more `TypedDict`/`dataclass` use for XBRL facts, search
  results, tool-call args), or (b) designing a scoped-down strict
  preset that excludes the highest-noise categories rather than
  adopting pyright's off-the-shelf `strict` bundle wholesale.

### From the 2026-09-11 hand-rolled-complexity review

Full evidence: `docs/decisions/2026-09-11-negative-number-support.md`
and `docs/reviews/2026-09-11-negative-number-support.md`. That review's
other findings needed no new tracking here: the
citation-verification subsystem's general complexity is already covered
by the `_QUOTE_ANCHOR_CHARS`/normalize-duplication entries below, and the
retrieval-rescue and XBRL-period-duration findings had no live failure or
concrete fix to attach, on top of already being thoroughly documented in
their own code.

- [ ] **[refactor, Low, Trivial]** `agent._dispatch_tool_call`'s tool
  branches are an inline if-chain (4 today: `get_financial_fact`/
  `compare_financial_metric`/`calculate`/`search_filings`) that will keep
  growing linearly with each new tool, each hand-repeating the same
  span/call/format/mutate shape. Not worth a registry-based dispatch
  table at 4 tools; revisit if a 5th/6th tool is added.

### From the 2026-09-10 citation-gate-measurement-instrumentation plan

Full evidence/reasoning: `docs/plans/2026-09-10-citation-gate-measurement-instrumentation.md`.

- [ ] **[bug, Low, Standard]** `_SENTENCE_BREAK`'s abbreviation exception only excludes a *lowercase* follow-on word (`U.S. sales`); a capitalized follow-on (`U.S. GAAP`, `U.S. Treasury`) still registers a sentence break. Downgraded from High/Trivial and re-scoped 2026-09-10: this only matters on the prose-verification fallback path now (the structured-claims `submit_answer` path added that day doesn't parse prose at all), and Gemini rarely takes that path — the live re-measurement (`docs/plans/2026-09-10-structured-claims-citation-verification.md`) confirmed `nvda-revenue-fy26-us-gaap`, the original repro, now passes cleanly via the structured path. Still real for Ollama (no forcing mechanism, prose fallback is its normal path) or a Gemini forced-submit exhaustion — fix if it recurs there.
- [ ] **[bug, Low, Standard]** `_CITATION_MARKER = re.compile(r"\[(\d+)\]")` does not match a comma-separated multi-source bracket like `[1, 2, 3]`. Downgraded from Med/Trivial 2026-09-10 and now genuinely fallback-path-only: the 41-question baseline re-run initially found this ALSO hit the new structured path (`verify_claims`'s coverage check extracted bare digits out of `[1, 3, 5]`/`[1, 17]` brackets as spurious uncovered numbers -- `crm-revenue-q1fy27`, `msft-net-income-fy2025-indirect`), fixed same day via a separate `_ANY_CITATION_BRACKET` pattern used only by that check (`_CITATION_MARKER` itself is untouched -- the old prose pipeline reads its single capture group as one index and can't just have the pattern widened). `_CITATION_MARKER` itself, and the prose fallback path that still uses it directly, remains unfixed.
- [ ] **[feature, Low, Standard]** Model-based veto before refusal (one entailment check before the hard gate withholds an answer) — deferred 2026-09-10 pending the structured-claims redesign's own measurement. Re-evaluated 2026-09-11 with the full 41-question baseline + 4-question stress set now analyzed: **0/45 gate fires post-redesign**, down from 6/45 (100% false positive) pre-redesign. Still no evidence a veto is needed — there's nothing left for it to overturn in this corpus. Revisit only if a wider/harder question set finds the gate firing again.
- [ ] **[test-coverage, Low, Standard]** No script reads `trace_logs/traces.jsonl` — it's a grep-by-hand file. Only worth building if the live-path `citation_gate_refused` events turn out to need routine review.
- [ ] **[test-coverage, Low, Standard]** `eval/citation_stress_questions.jsonl`'s original 4 questions targeted 3 specific citation-verifier failure modes; only 2 are covered by a passing question so far (same-chunk multi-period value attribution, table-only quote grounding — see `docs/decisions/2026-09-11-calculate-tool-and-stress-questions.md`). Two modes remain genuinely untested: a chunk with two nearby PERCENTAGES in one sentence (tried twice with different phrasings, both hit the model's own tool-choice budget exhaustion — a pre-existing, unrelated limitation, dropped per the 2-strikes debugging rule, not attempted a third time); a paraphrased quote near the 0.90 coverage threshold (genuinely hard to force via question wording alone, since the model is instructed to quote verbatim and mostly does).
- [ ] **[design, Low, Standard]** Found live verifying the `calculate` tool (2026-09-11), re-running `msft-cash-to-assets-fy2025` 5 times: it passed cleanly 3/5 times but exhausted the 6-turn budget or hit a real (pre-existing, unrelated) quote-mismatch refusal the other 2 -- traced to a compounding interaction, not a `calculate` bug: (a) the model sometimes emits `fiscal_year` as a STRING (`"2025"` not `2025`), which `_rejects_invalid_fiscal_year` correctly rejects, forcing a `search_filings` fallback (2 extra calls) instead of the direct `get_financial_fact` path; (b) `calculate` itself sometimes mislabels an already-raw XBRL value's unit on its first attempt (e.g. passing a raw dollar amount as `unit_a: "billion"`), which `_ground_operand` correctly rejects, costing one retry turn to self-correct (also observed on `aapl-rd-pct-gross-profit-fy2025`, where it self-corrected without issue since that question's shorter path had turns to spare). On an already-tight-budget question, (a)+(b) together can exceed `MAX_TOOL_ITERATIONS=6` before a final answer is submitted. **Addendum 2026-09-14**: clause (b) recurred and got a full root-cause fix at the message level -- `aapl-revenue-growth-q3fy2026`'s 2026-09-13 baseline failure was this exact mislabeled-unit case (`operand_a=109417000000` mislabeled `"billion"`), and the old message blamed the value/citation index instead of the unit, so the model's retry never touched the field that was actually wrong. `_ground_operand` now computes which correction actually applies (mislabeled unit vs. wrong citation index vs. genuinely ungroundable) instead of guessing -- see `docs/reviews/2026-09-14-tool-turn-waste.md`. This fixes the MESSAGING half of (b); it does not stop the model from mislabeling a unit in the first place, and (a) remains fully unaddressed -- still not fixed at the source, per this item's original "don't chase model non-determinism speculatively" reasoning.
- [ ] **[bug (latent), Low, Standard]** `nvda-cost-of-revenue-fy2026` (41-question baseline, 2026-09-11): one run answered via `search_filings` prose (citing `[13]`) and got a `quote_not_found` refusal; an immediate manual re-run of the identical question instead went through `get_financial_fact` (the structured XBRL path) and answered cleanly with zero warnings -- model tool-choice is non-deterministic across runs for this question, and the exact failing quote/source pair from the original run wasn't captured anywhere (the `CitationWarning` message doesn't include the quote text itself, only the citation index), so this couldn't be reproduced to confirm whether `_quote_matches` has a real gap against dense filing-table prose or the model's original quote was simply wrong. Marked latent, not a confirmed bug: needs either a repro with the actual failing quote+source captured, or richer logging (the new `traced_span("tool", "submit_answer", ...)` added 2026-09-11 does capture `checks` in its span output going forward -- check Langfuse/`trace_logs/traces.jsonl` next time this recurs before spending more live-question budget chasing it blind).
- [ ] **[bug (latent), Low, Standard]** Table grounding's residual: a claim whose value genuinely IS a real table cell, quoted with no contradicting period/label token, still verifies even when the surrounding ANSWER PROSE misdescribes which period that cell covers (e.g. `"Productivity and Business Processes Revenue $102,149"` -- a real nine-month FY2026 cell -- grounds fine even if the answer calls it "the quarter"). `_verify_one_claim` checks quote-to-value grounding, not whether the answer's own prose correctly labels the period; closing this needs a `period` field on the claim schema checked against the cell's column header, not a `table_grounding.py` change. Found and deliberately scoped out during the 2026-09-12 table-grounding fix (`docs/plans/2026-09-12-structure-aware-table-quote-grounding.md`'s "Known limitations" section) -- no concrete question currently exercises it as a live false accept. Still accurate after the 2026-09-13 redesign: the QUOTE itself must still correctly identify the period/column (enforced by the new cherry-pick check) -- what's NOT checked is whether the answer's own PROSE, separately from the quote, describes the period correctly.
- [ ] **[bug (latent), Low, Trivial]** `_quote_matches`'s flat anchor-path false accept (a long segment label lets a wrong-period or digit-inflated quote clear the flat coverage/anchor check on its own) remains open for genuinely prose-stated values (no table in the source, or the value only appears in surrounding text, so `table_grounding.locate_value` never runs at all). Not observed live as a real prose-path false accept; flagged only because the mechanism is architecturally identical wherever `_quote_matches`'s anchor path is still the final word (table sources no longer use it at all as of the 2026-09-13 redesign, which replaced the anchor floor with a region-scoped coverage + number-presence + cherry-pick check). Revisit only if a prose-path instance is ever found.
- [ ] **[bug (latent), Low, Standard]** `table_grounding._classify_row`'s parenthesization heuristic (a single-cell, non-numeric row is a permanent "header" if parenthesized, else a resettable "label") could misclassify a real, named SEC convention: ASC 852 Predecessor/Successor fresh-start reporting renders both period labels parenthesized (`"(Predecessor)"`/`"(Successor)"`), which would (a) never set `group_label` for either period's rows, and (b) leak the Predecessor label into the permanent, shared `header_context` used by every cell in the block, letting a quote pair the Successor's real value with the Predecessor's label. Scanned the entire local corpus (all 5 tickers) for every real parenthesized single-cell row -- all 15 are genuine table-wide captions or signature-block titles, none are resettable labels, so the heuristic holds against today's evidence; none of this project's 5 tracked tickers has gone through bankruptcy/fresh-start reporting. Found in the 2026-09-13 redesign's architecture review (`docs/reviews/2026-09-13-table-grounding-region-scoped-matching.md`) -- not fixed, per this project's practice of not chasing unevidenced hypotheticals; revisit if a tracked company's filing ever actually uses this convention.
- [ ] **[bug (latent), Low, Standard]** `table_grounding.py` has no defense against a quote citing a DIFFERENT group/segment's label if that label is merely similar (not identical) to the correct one across two DIFFERENT tables/blocks (e.g. two sibling segments named "Segment A"/"Segment B") -- coverage-based fuzzy matching alone could tolerate this. Confirmed NOT exploitable in any of this project's 4 real table fixtures (their labels are all sufficiently distinct), and confirmed there's no actual cross-block STATE leak (`header_context`/`group_label`/`caption_units` are correctly recomputed independently per `<TABLE>` block) -- the risk is purely fuzzy-tolerance, not a structural bug. Found in the 2026-09-13 redesign's architecture review; the missing test coverage for multiple `<TABLE>` blocks this same review flagged was fixed directly (`test_two_table_blocks_in_one_chunk_do_not_leak_context_between_them`), this residual fuzzy-tolerance concern was not, since no concrete real-filing exploit was constructible.
- [ ] **[bug (latent), Low, Trivial]** `table_grounding.quote_is_grounded`'s coverage check can be measurably inflated by a large `header_context` (many leading caption/header lines): a fabricated quote reusing header vocabulary around a real value moved from 25% to 88% coverage as a synthetic header grew from 0 to 60 lines, in the 2026-09-13 redesign's architecture review -- but never crossed the 90% acceptance threshold in that testing, on any real or constructed fixture. Recorded as a latent watch item, not fixed speculatively.
- [ ] **[bug (latent), Low, Trivial]** `table_grounding._classify_row` misclassifies a data row whose first cell is blank (a wrapped/continuation label with real values already present) as a "header" row instead of "data", silently dropping it from `locate_value`'s consideration. Fails safe (falls through to the ordinary flat-text `_quote_matches` path, not a false accept) -- found in the 2026-09-13 redesign's architecture review as a minor, unexploited structural-coverage gap; worth a fixture/test if a real filing with this shape is found.
- [ ] **[design, Low, Standard]** `nvda-gross-margin-fy26` (41-question baseline, 2026-09-11): the model correctly stated 71.1% with a valid claim `[1]`, then added a second, redundant claim re-deriving the same figure ("...or 71.1 expressed as a percentage of revenue in its Consolidated Statements of Income) `[18]`") whose quote doesn't literally contain "71.1" (it's a derived restatement, not a direct source quote) -- `_verify_one_claim` correctly fails that second claim, but `verify_claims`'s all-or-nothing design means one bad redundant claim refuses an otherwise fully-grounded answer. Not clearly a code bug (the second claim genuinely doesn't verify) or clearly a system-prompt gap (rule 9 doesn't currently address a model restating an already-cited value a second way) -- needs a decision once this pattern is confirmed to recur: tighten rule 9 to discourage redundant restatement claims, or relax `verify_claims` to tolerate a claim that duplicates an already-verified value under a different citation. Didn't recur in an immediate re-run (that run failed the same question a different way -- tool-budget exhaustion, not a gate refusal -- consistent with general model non-determinism on this question, not a persistent gate gap).
- [ ] **[refactor, Low, Trivial]** The `category, norm = normalize(...); tolerance = max(0.01*abs(norm), 0.05); any(c == category and abs(v - norm) <= tolerance for c, v in candidates)` pattern is now duplicated 6 times across `agent.py`/`table_grounding.py` (`_iter_citation_claims`, `value_is_citation_verified`, `_verify_one_claim`, `verify_claims`'s coverage check, `_ground_operand`/`call_calculate` for the `calculate` tool, 2026-09-11, and `table_grounding.locate_value`/`quote_is_grounded`, 2026-09-12) -- plus `eval_harness.grade_numeric`'s own copy, a natural 7th if a shared helper is ever extracted. Pre-existing style tolerated 3 times already; the `calculate` tool's addition was a good opportunity to extract a shared `_matches_any(value, unit, candidates) -> bool` helper instead of continuing to copy it, and the table-grounding fix is a second one, deferred for the same reason. Found in the `calculate` tool's architecture review, 2026-09-11 (`docs/reviews/2026-09-11-calculate-tool-and-stress-questions.md`) -- not fixed there or in the 2026-09-12 fix, since it's a cosmetic DRY cleanup unrelated to either change's actual scope.

### From the 2026-09-14 tool-turn-waste fix

Full evidence/reasoning: `docs/plans/2026-09-14-tool-turn-waste.md`,
`docs/reviews/2026-09-14-tool-turn-waste.md`. Surfaced while diagnosing
why 9/16 failures in the 2026-09-13 47-question baseline were turn-
budget timeouts, not citation-gate refusals.

- [ ] **[design, Med, Standard]** The model never routes a 3+-company ranking question through `compare_financial_metric` -- confirmed across the ENTIRE trace history, it has never once been called on `five-company-*-ranking-fy2025`, always five individual `get_financial_fact` calls instead, which cannot even retrieve the right answer (see the fiscal-year-label bug below) and exhausts the 6-turn budget doing it. Attempted THREE times live against real Gemini calls with two different prompt wordings -- a narrowed "use this for 3+ companies" rule, then (after the first failed) an added reassurance that anchor-based closest-period matching is correct even when the question states each company's own distinct fiscal year/period-end date -- and failed identically each time, same five-call pattern, same timeout. Per this project's "fails twice in the same way" rule, brought back for a decision rather than tried a fourth way; the fourth attempt (one more targeted wording) also failed, and all wording was reverted to the original text rather than ship unproven changes that could regress 5 currently-passing comparison questions (`nvda-revenue-two-quarter-comparison`, `aapl-msft-tax-rate/employee/total-assets-comparison`, `msft-three-segments-revenue-q3fy2026`) for zero measured benefit. **Working hypothesis, not yet tested**: the target question spells out each company's own distinct fiscal year and period-end date explicitly (e.g. "Apple's fiscal year 2025 (ended September 27, 2025) ... NVIDIA's fiscal year 2026 (ended January 25, 2026)"), which may read to the model as needing exact per-company lookups rather than trusting the tool's anchor-and-closest-match approximation, no matter how that's worded. Needs a different angle before a fifth prompt attempt -- e.g. a worked example showing the tool's approximation IS the graded-correct answer for this exact question shape, or accepting this as a standing model limitation and moving the fix to code (a validator step, or splitting the tool call per stated date).
- [ ] **[bug, Med, Standard]** `get_financial_fact(ticker="CRM", metric="operating_margin"/"gross_margin", fiscal_year=2026, fiscal_period="FY")` returns `None` (not found), while the exact same fact via `period_end_date="2026-01-31"` returns the real value (20.1%/77.7%). This is the mechanical reason the per-company ranking path above loses CRM specifically (its FY2026 corresponds to a period-end fiscal-year-labeling gap this tool doesn't resolve, unlike `compare_financial_metric`'s own anchor+closest-match path, which retrieves it fine). Not investigated further this session -- found live while verifying Mechanism 3's diagnosis, not root-caused in `xbrl_facts.py`/`formulas.py` yet.
- [ ] **[bug (latent), Low, Standard]** The eval judge (Gemini, same backend) sometimes marks a CORRECT answer wrong for citing a real, current 2026 filing date as "hypothetical" or "future" -- observed in the 2026-09-13 baseline on `msft-segment-revenue-comparison-q3fy2026` (*"answering based on a hypothetical or future date (March 31, 2026) that is beyond current verifiable financial data"* -- the answer was in fact correct and well-cited). Did NOT reproduce in the 2026-09-14 baseline re-run -- that same question failed differently that run (a citation-gate refusal, not a judge complaint), consistent with the judge itself being non-deterministic across live calls of the identical grading prompt. Not fixed or root-caused; corrupts before/after eval comparisons whenever it fires, since the failure has nothing to do with the answer's actual correctness. Worth a fix to the judge's own grading prompt (explicitly telling it these are real, live filing dates, not hypotheticals) if it recurs at a rate that shows up reliably.
- [ ] **[bug (latent), Low, Standard]** `msft-segment-revenue-comparison-q3fy2026` failed via a genuine `quote_not_found` citation-gate refusal in the 2026-09-14 baseline (`"[1] claims 35013 (million) ... doesn't appear in source [1]"`, plus `34681`/`13192` the same way) -- notable because `35013` and `34681` are the exact real segment-revenue values the 2026-09-13 table-grounding redesign's own review fixtures were built around (Productivity's real revenue vs. a wrong-segment attribution). Not investigated further this session (`table_grounding.py` is untouched by the 2026-09-14 diff, and the same question passed cleanly with all 3 segment values correctly grounded on `msft-three-segments-revenue-q3fy2026`, a different eval question against the same underlying table, in this SAME baseline run) -- flagged as a residual worth a targeted repro (capture the actual failing quote, not just the `CitationWarning`'s citation index, same gap `:72` above already notes) if it recurs.

### From the 2026-09-16 final-turn-safety-net fix

Full evidence/reasoning: `docs/decisions/2026-09-16-final-turn-safety-net.md`.

- [ ] **[bug (latent), Low, Standard]** The final-turn safety net's CRM-shaped grounded-but-incomplete risk (a forced final submit answering with fewer companies than the question asks about, all correctly cited, but still substantively wrong) is mitigated by message wording, not eliminated by anything structural, and wasn't directly exercised live -- the CRM fiscal-year-lookup bug (below) didn't trigger in any post-fix live run, so the model always had all 5 companies' data when forced to submit. Revisit if a future run hits that combination and produces a confidently-wrong ranking: strengthen the message, or gate on the most recent tool call's own scope, before reaching for a structural classifier.
- [ ] **[feature, Low, TBD]** Extend the final-turn safety net (`_should_force_final_submit`) to Ollama -- currently gated to `_FINAL_TURN_BACKENDS = {"gemini"}` only, since no live evidence exists for how Ollama responds to a directive nudge under budget pressure (matching this project's existing precedent for gating other corrective-pressure mechanisms to Gemini first). Needs its own live verification before extending.

### From the 2026-09-15 qualitative-claims-schema fix

Full evidence/reasoning: `docs/decisions/2026-09-15-qualitative-claims-schema.md`.
Surfaced by the confirmatory 47-question baseline re-run after that fix
(37/47) -- neither question involves a qualitative claim, so these are
unrelated to that fix, just observed in the same run.

- [ ] **[bug (latent), Low, Standard]** `nvda-supply-chain-risk` (a
  qualitative "what risks" question, but with a real number "12"
  mentioned in the answer prose) failed with `"claims 12.0 (raw) but no
  claim in your submit_answer call covers it"` -- an `uncovered_number`
  warning, the OPPOSITE problem from the placeholder-value bug that fix
  addressed (a real number stated with no matching `claims` entry at
  all, not a fabricated entry for a non-existent number). Single
  observation, not yet reproduced or root-caused.
- [ ] **[bug (latent), Low, Standard]** `aapl-rd-pct-gross-profit-fy2025`
  failed the same way on the two `calculate`-tool INPUT values
  (`"claims 34550.0 (raw)..."`/`"claims 195201.0 (raw)..."` both
  uncovered), despite the model's own `withheld_answer` showing a
  correct, well-formed answer citing both values with markers `[1]`/`[2]`
  -- suggesting the model's `claims` array was simply missing entries for
  two of the citations it used in `answer_text`. Single observation, not
  yet reproduced; possibly related to the existing `calculate`-tool
  turn-budget/mislabeling interaction already tracked below, possibly a
  distinct gap. Not investigated further this session (out of scope for
  the qualitative-claims fix).

### From the 2026-09-07 review of the get_metric_all_companies redesign

- [ ] **[feature, Low, Standard]** `formulas.py`'s `RATIO_DEFINITIONS` `supports_cross_company=False` gate (return_on_assets/asset_turnover/cash_to_assets/inventory_turnover) is justified by the same instant-frame problem the 2026-09-07 fix corrected at the `get_metric_all_companies()` layer, but `get_ratio_all_companies()` uses a separate, still frame-only path (`_compute_ratio_metric_all_companies()`), so these ratios stay blocked for cross-company comparison even though their raw legs (e.g. `total_assets`, `cash_and_equivalents`) are now individually comparable. Real gap, but a separate, larger-scope item (would need `_compute_ratio_metric_all_companies()` to compose from independent per-company legs for these 4 ratios specifically) — not a defect in that fix, no concrete question needs it yet. See `docs/decisions/2026-09-07-fix-get-metric-all-companies-instant-metrics.md`.

### From the 2026-09-06 full-codebase review

Full evidence/reasoning for each: `docs/reviews/2026-09-06-full-codebase-review.md`.
All numbered findings from this review are resolved — see
`docs/decisions/2026-09-06-full-codebase-review.md` (§1-§4, plus the
2026-09-07 addendum), `docs/decisions/2026-09-08-fix-3-medium-review-findings.md`
(§5/§7/§9), `docs/decisions/2026-09-09-fix-3-more-review-findings.md`
(§6/§8/§10), and `docs/decisions/2026-09-10-fix-3-more-review-findings.md`
(§11/§12/§13). The two genuinely open, lower-priority findings this
review also surfaced remain below.

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

### Carried over from the project's pre-2026-09-06 history

- [ ] **[feature, Low, Substantial]** Per-call LLM "generation" tracing (token counts, prompt/completion text, per-call cost/latency as Langfuse generation objects) — explicitly scoped out of the Langfuse tracing work, parked until a real debugging need shows up. See `docs/decisions/2026-09-04-langfuse-tracing.md`.
- [ ] **[feature, Low, Substantial]** Multi-turn conversational QA (ConvFinQA-style follow-ups) — `run_agent()` is single-turn only. Parked since Week 5's single-turn architecture; revisit only on a real multi-turn need.
- [ ] **[feature, Low, Substantial]** Graph DB (Neo4j) as a retrieval layer — parked; only worth it if a relationship/multi-hop-shaped question actually appears.
- [ ] **[test-coverage, Low, Standard]** Growing the eval set further toward the original 30-50 FinanceBench-style target — optional, not a fixed requirement.
- [ ] **[misc, Low, TBD]** "Week 8 — polish + write-up" — no detail scoped yet.

(HNSW index tuning was rejected outright, not parked, so it isn't carried over as an open item.)
