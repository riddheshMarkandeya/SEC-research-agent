# Backlog

Tracks open work: what's queued, what's in progress. This is **not** a
changelog. Completed work's rationale and verification live in its
record: the commit message body, or a `docs/decisions/YYYY-MM-DD-<slug>.md`
file when the change passes the ADR gate (and, for Substantial work, its
own paired design doc under `docs/plans/`), with files indexed from
`PROJECT_INDEX.md`. Link out to the relevant record instead of
re-explaining reasoning here; keep entries short.

**Keep this current as work happens, not just at session-end**: add a
line the moment a new open item is identified (a deferred idea, a
found-but-not-fixed bug, a follow-up) — don't wait for a wrap-up. Move
an item to "In progress" when you start it. **When an item is done,
delete its line entirely** — no strikethrough, no "resolved" annotation
left behind — and land its record in the same step (the commit body,
or a decision file plus its `PROJECT_INDEX.md` line if the ADR gate
passes). If only part of a
multi-part item is resolved, rewrite the line to describe only the
remaining open part, with no decorated hybrid of done-and-not-done. An
item should never just vanish from this file with no recorded trace
of what happened to it. **Exception: items tagged "Recurring"**. When a run
is done, rewrite the item's due date instead of deleting the line; each
run still leaves its own record.

This file replaces the project's former narrative changelog's old "Next
steps" section, which needed its own 380-line cleanup pass once already
(2026-08-19) from exactly this kind of bloat — don't let this file
suffer the same fate; prune it as items resolve.

**Where items go.** Origin sections (`### From …`) hold work someone can pick up. A latent item with nothing to do until a named condition is observed goes in the `## Watch list` at the end instead, as one line: the trigger plus a record link.

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

- [ ] **[bug, High, Standard]** `numeric_utils.NUMBER_PATTERN` backtracks cubically on any long run of whitespace: `(?P<open_paren>\()?\s*(?<!\d)(?P<sign>[-−])?\$?\s*` retries both `\s*` splits from every offset in the run. Measured at HEAD `ffffee8`: `extract_numbers("x" + " "*600 + "y")` 2.2s, 1200 spaces 18s, `"(" + 2000 spaces + ")"` ~70s. Every chunk, answer and quote goes through it, and model answer text is untrusted, so one padded answer can stall `verify_claims`. Not yet checked whether any indexed chunk has such a run. Fix: start a match only at a run's first character (e.g. a `(?<!\s)` anchor before the leading `\s*`) or bound the runs, plus a timing regression test. Critical core, so it needs escalated plan review and a live spot-check. The per-sign `text[:pos]` slice in `_preceded_by_number` is also quadratic in the number of signs; fix both together. Found during the review of the formula-constant gate fix.

### From the 2026-09-24 prompt-audit roadmap

Design: `docs/plans/2026-09-24-prompt-audit-roadmap.md`. Findings: `docs/reviews/2026-09-24-prompt-audit.md`. The roadmap closed 2026-09-27 (WP8 bar met, 40/47). Summary: `docs/decisions/2026-09-27-prompt-audit-rollout.md`. What's left here are its open items. Anything that changes model-visible text still goes through the roadmap's panel-screen process.

- [ ] **[misc, Med, Substantial]** **Next:** the baseline-improvement plan. All three candidates from the WP5–WP8 misses are done: the "− 1" gate false positive (2026-09-28: percent identities covered only when a percent `calculate` ran; `git log --grep="percent identit"`), the Q4-hint vs judge conflict on `nvda-rd-expense-q4fy26-refusal` (2026-09-28: criteria no longer invite the full-year figure; `git log --grep="nvda-rd-expense-q4fy26"`), and the unprefixed header echo (`docs/decisions/2026-09-27-unprefixed-citation-header-strip.md`). Post-fix panel (C `ca52d68`, reports `20260928T071313Z`/`071948Z`/`072319Z` vs WP8 B `20260926T085714Z`/`090017Z`/`090341Z`): no regressions; nvda-revenue-two-quarter-comparison and nvda-rd-expense-q4fy26-refusal 3/3. Next: the agent-improvement map `docs/plans/2026-09-28-agent-improvement-map.md` (merged; supersedes the gate-refusal map and structural review). Prerequisites first, per its Decision 13: the NUMBER_PATTERN fix below, the replay tool, Ollama removal, the `agent.py` split, eval summary mode. Frontier tickets: prose fallback path, segment-table ranking. No fallback backend after Ollama (user, 2026-09-28). The pltr item below is one of its cases. Keep the model pin for its screens. `docs/decisions/2026-09-27-prompt-audit-rollout.md`
- [ ] **[bug, Med, Standard]** `pltr-inventory-turnover-fy2025-refusal` is refused by the per-claim gate in 9 of 24 runs since 2026-09-25 (1/3 in the post-fix panel, 2/3 in WP8 B). The model files fiscal years as numeric claims ("[6] claims 2025 (raw) but that value doesn't appear in the quoted text") or a claim with a value and no unit, so a correct no-data refusal becomes "I can't confirm this answer". `withheld_answer` is empty, so the eval's gate-FP flag misses it. Check `_verify_one_claim` and the retry path in `agent.py`: should a year-shaped raw claim be treated as non-claim, and should a correct refusal be possible with no numeric claims at all? Critical core.
- [ ] **[misc, Low, Standard]** Step 7 follow-ups:
  - reason-bearing rejections via `on_reject`, including a call rejected at the boundary (partial multi-year range, yoy + multi-year), which today reads as "no data … try search_filings";
  - `calculate`'s generic missing-argument message;
  - MCP search returning a silent `[]`;
  - a yoy no-data reply names the anchor period even when the prior year is the missing one (`formulas.py:353`; no live case, all 62 yoy calls found data).

  Each one changes model-visible text, so it needs a panel screen. `docs/decisions/2026-09-26-wp7-fiscal-year-strings.md`
- [ ] **[refactor, Low, Standard]** Audit notes 8–10 (prompt style):
  - all-caps emphasis;
  - tool bullets in SYSTEM_PROMPT that duplicate the tool descriptions;
  - the size of rule 9;
  - sentences duplicated across the agent and MCP surfaces;
  - the hard-coded "five companies".

  It changes model-visible text, so it needs a panel screen. `docs/reviews/2026-09-24-prompt-audit.md`

- [ ] **[bug, Low, Standard]** `_NON_CLAIM_PATTERN`'s duration exemption covers only year/month/day ("3-year", "90 days"); other durations and counts ("12 weeks", "2 quarters") still read as uncovered numbers. Each new word is whack-a-mole; fix only if a live run withholds on one. `docs/decisions/2026-09-17-uncovered-number-gap-fixes.md`
- [ ] **[bug, Low, Standard]** `numeric_utils.NUMBER_PATTERN` has no "B"/"bn" suffix: `extract_numbers("$81.6B")` and "$81.6bn" give `(81.6, 'raw')`, while "$81.6 billion" gives `(81.6, 'billion')`. An answer written with the suffix would fail coverage against a claim in billions. Not seen live yet (the NVDA answers wrote full figures). Critical core, so escalated plan review and a live spot-check. `docs/research/2026-09-28-grounding-computed-numbers.md`
- [ ] **[design, Low, Standard]** Rule 9's "computed as" example (`prompts/agent_system.py`, `prompts/agent_tools.py`) shows only a ratio, and `calculate` renders percent_change as prose, so the model improvises its own percent-change formula. The gate now covers the unitless identities 1, −1, 100 and −100 when a percent calculation ran, but not "× 100%" (parses as 100 percent; covering it would exempt a real "100%" claim). Add a percent_change example, or match `calculate`'s rendering, only if live runs still withhold derivations. Prompt change: its own commit plus a panel run.
- [ ] **[bug, Low, Standard]** The percent-identity coverage in `verify_claims` keys on a `calculate` percent result only. A growth figure from `get_financial_fact(yoy_growth=True)` (an `xbrl` result) grants no identities, so an answer that writes "current ÷ prior − 1" after it would still withhold for the 1. Not seen live; fix only if a run shows it (e.g. also grant them for a yoy_growth result).
- [ ] **[bug, Low, Standard]** A calculate result's expression pastes each operand's unit in as-is, so a `"raw"` operand (a plain ratio or count) reaches the model as e.g. "1.04 raw". The result value itself already omits "raw" via `agent._with_unit`. Found in the WP1 code review (`docs/reviews/2026-09-24-wp1-prompts-package.md`); left unchanged because WP1 had to be byte-identical. It changes model-visible text, so it goes through the roadmap's panel-screened process: fit it in after WP2.
- [ ] **[refactor, Low, Trivial]** Duplicated enum values in `prompts/agent_tools.py`, all copied as-is from `agent.py` by WP1: the period list `["FY", "Q1", "Q2", "Q3", "Q4"]` twice, `list(COMPANIES.keys())` three times, and `CLAIM_UNITS` restating `numeric_utils.UNIT_MULTIPLIERS`'s keys by hand. Hoist each into one constant; the schemas' bytes must stay identical (check with the WP2 fingerprint). Found in the WP1 code review.
- [ ] **[design, Low, Standard]** The MCP `search_filings` schema is derived the wrong way round: `prompts.mcp.MCP_SEARCH_TOOL_SCHEMA` is the agent's schema with its agent-only text overridden, so agent-only wording in any other field reaches MCP clients silently. The `ticker` description already does ("…which company the question is about"), and three description sentences are written out on both surfaces. Fix: a neutral shared schema that the agent adds its note to. It changes model-visible text, so it needs a panel screen. Found in WP3's plan and code reviews (`docs/reviews/2026-09-24-wp3-group-a-wording.md`).

### From the 2026-09-26 backlog review

Full reasoning: that cleanup's commit body (`git log --grep="Watch list"`).

- [ ] **[misc, Med, Substantial]** Remove the Ollama backend and its code. Small local models
  aren't a target; only cloud models big enough for the task are (user decision, 2026-09-26).
  About 449 mentions across 14 files (`llm_backends.py`, `agent.py`, `config.py`,
  `eval_harness.py`, tests, `tests/manual/verify_*.py`). It touches the blast-radius core, so
  schedule it after WP8 and before the `agent.py` split, which it shrinks. Open points for its
  own plan:
  - (a) Ollama is the only backend that needs no API key, so it's the only fallback when the
    Gemini free-tier quota runs out. Decide whether a second cloud backend replaces it.
  - (b) The prose-fallback citation path is also Gemini's last resort, not only Ollama's. Decide
    whether it stays; the three prose-path Watch list entries follow from that.
  - (c) `grade_judged`/`_grade` default to `"ollama"` in their signatures.
  - (d) Update `.claude/rules/plan-review-blast-radius.md` (it names `_ollama_send*`) and
    `config.py`'s backend comment.
  - (e) If (a) keeps Ollama after all, extending the final-turn safety net
    (`_FINAL_TURN_BACKENDS` in `agent.py`) to it is open again, and needs live verification.

### From the 2026-09-25 token-efficiency workflow change

Full evidence/reasoning: `docs/decisions/2026-09-25-token-efficiency-workflow.md`.

- [ ] **[misc, Med, Standard]** Pilot: over the next 2 WPs, measure main-thread and subagent
  tokens and count review findings. Method: sum `message.usage` per unique `message.id` in
  `~/.claude/projects/<project>/*.jsonl` (main thread) and `*/subagents/*.jsonl`, with cache
  reads weighted at 0.1. Compare against the decision file's baseline:
  86% main-thread share, 351k median context. Also note anything lost to compaction.
  - Restore Opus reviewers or two clean rounds if findings drop.
  - Raise the window if compaction loses something important.
  - The first `/retro` run closes this out (its baseline is `~/.claude/retros/2026-09-25.md`).
- [ ] **[design, Low, Trivial]** After a clean pilot, consider lowering `autoCompactWindow` from
  300k to 200k (simulated −68% main-thread input vs −56%, ~4.5 vs ~2 compactions per session).
- [ ] **[design, Low, Standard]** After a clean pilot, trial `arch-reviewer` on Sonnet at
  Substantial tier too. Today it escalates to Opus there.
- [ ] **[design, Low, Trivial]** Consider lowering `PROJECT_INDEX.md`'s `Recent` cap (50 → ~25).
  It's read in full every session (~16KB).
- [ ] **[feature, Med, Standard]** Add a summary mode to `eval_harness.py`: one line per question
  plus a final table on stdout, with full detail left in the results JSON. Eval and pytest output
  put 2.4M chars into context across past sessions (2026-09-25 read/grep audit).
- [ ] **[refactor, Med, Substantial]** Split `agent.py` (2,414 lines) and `tests/test_agent.py`
  (4,327 lines) into focused modules (e.g. prompt assembly, tool dispatch, citation checks,
  final-answer handling). A long-standing user goal.
  - It touches the blast-radius core, so it needs its own plan, and the live-eval rules apply.
  - Token angle: `agent.py` was read 847 times for 5.8M chars in overlapping ranges.
  - Design reasons come first.

### From the 2026-09-22 eval-question-classification change

Full evidence/reasoning: `docs/plans/2026-09-22-eval-question-classification.md`'s
"Prior art" section.

- [ ] **[feature, Low, Substantial]** Adopting Meta-style same-commit
  burst reruns (rerun each eval question N times on one fixed code
  version before/after a change) would let a future version compute a
  true probabilistic flakiness score instead of `classify_history()`'s
  windowed streak/transitions proxy — holding code constant is what
  actually isolates "flaky" from "a real regression," which the current
  heuristic can only approximate from single-run-per-code-era history.
  Needs a new eval-harness feature (a same-version rerun mode), not just
  an analysis-script change — deliberately out of proportion to the
  2026-09-22 classification change itself.

### From the 2026-09-22 pytest-coverage adoption

Full evidence/reasoning: `docs/decisions/2026-09-22-adopt-pytest-coverage.md`,
`docs/decisions/2026-09-22-coverage-baseline-close-and-hard-gate.md`.

- [ ] **[test-coverage, Low, Standard]** Full-repo pytest coverage
  baseline mostly closed on 2026-09-22 (94% overall, up from 90%) — see
  `docs/decisions/2026-09-22-coverage-baseline-close-and-hard-gate.md`.
  `query_chunks.py` deleted (superseded), `index_chunks.py`/
  `eval_harness.py` fully closed. Still open: `chunk_documents.py`'s
  `process_filing`/`main` (81% under branch mode, real file-I/O logic,
  testable but not live-only — deliberately not pragma-excluded) and
  `mcp_server.py`'s ASGI middleware/`build_app` (84% under branch mode
  — genuinely live wiring, but currently just uncovered, not
  pragma-excluded: `mcp_server.py` carries zero `# pragma: no cover`
  markers and isn't in `.claude/rules/live-code-tdd.md`'s list either —
  add both if this gap is closed via exclusion rather than new tests).
  Only the 90%/80% two-tier diff-coverage bar applies to new/changed
  lines going forward; these two remaining gaps close opportunistically,
  file by file, as those files are next touched for other reasons.

### From the 2026-09-17 orphaned-table-overlap chunking fix

Full evidence/reasoning: `docs/decisions/2026-09-17-fix-orphaned-table-overlap-chunking.md`
and its paired review file.

- [ ] **[design, Low, TBD]** `table_grounding.locate_value`'s
  1%-relative-tolerance was what let the original bug silently
  false-match a wrong-but-close cell (0.24% off) instead of failing
  cleanly with "value not found" — a contributing factor, not itself
  fixed by the chunking fix. Worth a future look at whether the
  tolerance should be tighter or paired with a stronger uniqueness
  check.
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
  agent indefinitely; `B905` found 2 real `zip()` calls in the retrieval
  path (`retrieval.py:166,219`; a third, `query_chunks.py:97`, no
  longer exists — that file was deleted as superseded duplicate code,
  see `docs/decisions/2026-09-22-coverage-baseline-close-and-hard-gate.md`)
  that would silently truncate instead of erroring if Chroma ever
  returned mismatched-length document/metadata/distance lists. Rejected from the
  same survey, each for a specific reason rather than by category
  reputation: `S101`/`ARG001`/`ARG005`/`RUF059`/`B011` are 96-100%
  idiomatic test-file noise (asserts, mock-signature params, tuple
  unpacking) even where a handful of real hits exist; `ERA001` false-
  positives on this project's own comment-banner/decision-file-pointer
  conventions; `RET503` would push toward adding provably-unreachable
  dead code to satisfy the linter, contradicting the project's own
  error-handling philosophy; `RUF003` and a dozen other 1-4-hit codes
  weren't worth the selected-rule overhead at that volume.

### From the 2026-09-10 citation-gate-measurement-instrumentation plan

Full evidence/reasoning: `docs/plans/2026-09-10-citation-gate-measurement-instrumentation.md`.

- [ ] **[feature, Low, Standard]** Model-based veto before refusal (one entailment check before the hard gate withholds an answer) — deferred 2026-09-10 pending the structured-claims redesign's own measurement. Re-evaluated 2026-09-11 with the full 41-question baseline + 4-question stress set now analyzed: **0/45 gate fires post-redesign**, down from 6/45 (100% false positive) pre-redesign. Still no evidence a veto is needed — there's nothing left for it to overturn in this corpus. Revisit only if a wider/harder question set finds the gate firing again. **2026-09-26**: WP5's gate refusals on `nvda-revenue-two-quarter-comparison` were an uncovered-number false positive (the `1` in "a ÷ b − 1", `claims 1.0 (raw)`), not an entailment case. That goes to the narrow gate fix the WP5 close-out files, so there's still no evidence for a veto.
- [ ] **[design, Low, Standard]** `nvda-gross-margin-fy26` (41-question baseline, 2026-09-11): the model correctly stated 71.1% with a valid claim `[1]`, then added a second, redundant claim re-deriving the same figure ("...or 71.1 expressed as a percentage of revenue in its Consolidated Statements of Income) `[18]`") whose quote doesn't literally contain "71.1" (it's a derived restatement, not a direct source quote) -- `_verify_one_claim` correctly fails that second claim, but `verify_claims`'s all-or-nothing design means one bad redundant claim refuses an otherwise fully-grounded answer. Not clearly a code bug (the second claim genuinely doesn't verify) or clearly a system-prompt gap (rule 9 doesn't currently address a model restating an already-cited value a second way) -- needs a decision once this pattern is confirmed to recur: tighten rule 9 to discourage redundant restatement claims, or relax `verify_claims` to tolerate a claim that duplicates an already-verified value under a different citation. Didn't recur in an immediate re-run (that run failed the same question a different way -- tool-budget exhaustion, not a gate refusal -- consistent with general model non-determinism on this question, not a persistent gate gap).
- [ ] **[refactor, Low, Trivial]** The `category, norm = normalize(...); tolerance = max(0.01*abs(norm), 0.05); any(c == category and abs(v - norm) <= tolerance for c, v in candidates)` pattern is now duplicated 6 times across `agent.py`/`table_grounding.py` (`_iter_citation_claims`, `value_is_citation_verified`, `_verify_one_claim`, `verify_claims`'s coverage check, `_ground_operand`/`call_calculate` for the `calculate` tool, 2026-09-11, and `table_grounding.locate_value`/`quote_is_grounded`, 2026-09-12) -- plus `eval_harness.grade_numeric`'s own copy, a natural 7th if a shared helper is ever extracted. Pre-existing style tolerated 3 times already; the `calculate` tool's addition was a good opportunity to extract a shared `_matches_any(value, unit, candidates) -> bool` helper instead of continuing to copy it, and the table-grounding fix is a second one, deferred for the same reason. Found in the `calculate` tool's architecture review, 2026-09-11 (`docs/reviews/2026-09-11-calculate-tool-and-stress-questions.md`) -- not fixed there or in the 2026-09-12 fix, since it's a cosmetic DRY cleanup unrelated to either change's actual scope.

### From the 2026-09-14 tool-turn-waste fix

Full evidence/reasoning: `docs/plans/2026-09-14-tool-turn-waste.md`,
`docs/reviews/2026-09-14-tool-turn-waste.md`. Surfaced while diagnosing
why 9/16 failures in the 2026-09-13 47-question baseline were turn-
budget timeouts, not citation-gate refusals.

- [ ] **[design, Med, Standard]** The model never routes a 3+-company ranking question through `compare_financial_metric` -- confirmed across the ENTIRE trace history, it has never once been called on `five-company-*-ranking-fy2025`, always five individual `get_financial_fact` calls instead, which cannot even retrieve the right answer (see the fiscal-year-label bug below) and exhausts the 6-turn budget doing it. Attempted THREE times live against real Gemini calls with two different prompt wordings -- a narrowed "use this for 3+ companies" rule, then (after the first failed) an added reassurance that anchor-based closest-period matching is correct even when the question states each company's own distinct fiscal year/period-end date -- and failed identically each time, same five-call pattern, same timeout. Per this project's "fails twice in the same way" rule, brought back for a decision rather than tried a fourth way; the fourth attempt (one more targeted wording) also failed, and all wording was reverted to the original text rather than ship unproven changes that could regress 5 currently-passing comparison questions (`nvda-revenue-two-quarter-comparison`, `aapl-msft-tax-rate/employee/total-assets-comparison`, `msft-three-segments-revenue-q3fy2026`) for zero measured benefit. **Working hypothesis, not yet tested**: the target question spells out each company's own distinct fiscal year and period-end date explicitly (e.g. "Apple's fiscal year 2025 (ended September 27, 2025) ... NVIDIA's fiscal year 2026 (ended January 25, 2026)"), which may read to the model as needing exact per-company lookups rather than trusting the tool's anchor-and-closest-match approximation, no matter how that's worded. Needs a different angle before a fifth prompt attempt -- e.g. a worked example showing the tool's approximation IS the graded-correct answer for this exact question shape, or accepting this as a standing model limitation and moving the fix to code (a validator step, or splitting the tool call per stated date). **Addendum 2026-09-24**: the prompt audit found `compare_financial_metric` called only once in the whole trace log since 2026-09-15. The roadmap's 13-question eval panel has no question that exercises it (`docs/plans/2026-09-24-prompt-audit-roadmap.md`, Step 2), so prompt-wording changes to that tool are effectively untested until this item lands.

### From the 2026-09-06 full-codebase review

Full evidence/reasoning for each: `docs/reviews/2026-09-06-full-codebase-review.md`.
All numbered findings from this review are resolved — see
`docs/decisions/2026-09-06-full-codebase-review.md` (§1-§4, plus the
2026-09-07 addendum), `docs/decisions/2026-09-08-fix-3-medium-review-findings.md`
(§5/§7/§9), `docs/decisions/2026-09-09-fix-3-more-review-findings.md`
(§6/§8/§10), and `docs/decisions/2026-09-10-fix-3-more-review-findings.md`
(§11/§12/§13). The two genuinely open, lower-priority findings this
review also surfaced remain below.

- [ ] **[design, Low, Standard]** `tracing.py` has two overlapping "record an instantaneous fact" primitives (`record_unmet_metric_request` vs `log_event`) with no documented decision rule for which to use

### From the 2026-09-10 layered review of the §11/§12/§13 fixes

Full evidence: `docs/reviews/2026-09-10-fix-3-more-review-findings.md`.

- [ ] **[performance, Low, Standard]** `_never_tagged_hint()` (called from both `_format_no_fact_message` and, as of §12, `_format_no_comparison_message`) re-fetches `xbrl_facts.fetch_concept()` for the exact (ticker, tag) pair the caller's own lookup just fetched moments earlier — normally a free disk-cache hit, but `fetch_concept()` never caches a 404 response, so on the one case this hint actually exists for (a company that genuinely never tags a concept at all) it makes a real second live SEC network round-trip synchronously inside message formatting. Root cause is in `xbrl_facts.fetch_concept()`'s caching, not in either message formatter — a separate, larger-scope item than either function's own fix.
- [ ] **[design, Low, Standard]** `search_filings`' unknown-ticker rejection returns a bespoke, actionable string built inline in `_dispatch_tool_call` (naming the invalid ticker and listing valid ones), while `call_get_financial_fact`/`call_compare_financial_metric` fold the same failure into their generic `_format_no_fact_message`/`_format_no_comparison_message` (which don't name the ticker as the problem). An incidental inconsistency between three sibling "unknown ticker" paths, not a bug — worth a deliberate decision later (upgrade the other two similarly, or document why search_filings needs to differ) rather than leaving it accidental. Still stands after the 2026-09-09 schema-validator redesign — `validate_tool_args` deliberately preserved this asymmetry rather than resolving it (out of scope for that change).

### From the 2026-09-09 schema-driven arg-validation redesign

Full evidence/reasoning: `docs/plans/2026-09-09-schema-driven-arg-validation.md`, `docs/reviews/2026-09-09-schema-driven-arg-validation.md`. Surfaced while auditing the codebase for other schema-validation opportunities, or by that change's own two-pass review — real but lower-severity than what that change fixed, not addressed there.

- [ ] **[bug (latent), Low, Standard]** `xbrl_facts.py`'s `get_metric()` does unchecked `entry["val"]`/`entry["end"]`/`entry["form"]`/`entry["accn"]` indexing on SEC API response entries after `_pick_entry*` filters them — a SEC schema change or odd entry would raise a raw `KeyError` from inside XBRL-parsing internals instead of a clear error. Lower priority than the fixed items: SEC's schema is stable and the surrounding fetch/cache code is already fairly defensive.
- [ ] **[bug, Low, Trivial]** `eval_harness.py`'s `_select_questions` reads `q["id"]` before the per-question `try/except` in `run_eval()` that already contains most other malformed-question crashes — one malformed question entry still crashes the whole eval batch instead of just failing that question. Narrow, low-traffic (offline eval tool, not a live path).
- [ ] **[refactor, Low, Standard]** `_dispatch_tool_call`'s `search_filings` branch re-derives ticker validity by hand (`isinstance`/`COMPANIES` membership) a second time, after `validate_tool_args` already checked the same thing internally via the schema, purely to decide which rejection message to show — a residual instance of the same "hand-rolled check duplicating the schema" pattern this redesign otherwise eliminated. Found in the redesign's own architecture-review pass; not fixed there because a clean fix means changing `validate_tool_args`'s return type across all 4 call sites for a 2-line message-selection convenience, out of proportion to that change.

### Carried over from the project's pre-2026-09-06 history

- [ ] **[misc, Low, TBD]** "Week 8 — polish + write-up" — no detail scoped yet.

(HNSW index tuning was rejected outright, not parked, so it isn't carried over as an open item.)

## Watch list

Latent items with nothing to do until the named trigger is observed. When it is, move the item
back into an origin section as work. One line each: the trigger, plus the record that holds the
detail. The fuller write-ups from before the 2026-09-26 cleanup are in
`git show e45de8b:BACKLOG.md`.

**Citation verification**

- **[feature, Low, TBD]** The prose-fallback citation path has no `quote` capture like the structured path's. Trigger: a prose-path failure that needs it, or the Ollama item's prose-path decision. `docs/decisions/2026-09-18-flaky-eval-questions-three-fixes.md`
- **[bug, Low, Standard]** `_SENTENCE_BREAK` treats a capitalized word after an abbreviation (`U.S. GAAP`) as a sentence break. Prose-fallback path only. Trigger: a recurrence on Gemini's forced-submit fallback, or the Ollama item's prose-path decision. `docs/plans/2026-09-10-citation-gate-measurement-instrumentation.md`
- **[bug, Low, Standard]** `_CITATION_MARKER` doesn't match a multi-source bracket like `[1, 2, 3]` on the prose-fallback path. The structured path's coverage check already handles it via `_ANY_CITATION_BRACKET`. Trigger: same as `_SENTENCE_BREAK`. `docs/plans/2026-09-10-citation-gate-measurement-instrumentation.md`
- **[bug (latent), Low, Standard]** `_verify_one_claim` checks quote-to-value grounding, not whether the answer's own prose labels the cell's period correctly. A fix needs a `period` field on the claim schema. Trigger: a live false accept. `docs/plans/2026-09-12-structure-aware-table-quote-grounding.md`
- **[bug (latent), Low, Trivial]** `_quote_matches`'s flat anchor path can accept a wrong-period or digit-inflated quote for a prose-only value (table sources no longer use it). Trigger: a prose-path false accept. `docs/reviews/2026-09-13-table-grounding-region-scoped-matching.md`
- **[bug (latent), Low, Standard]** `table_grounding`'s fuzzy coverage could accept a similar-but-wrong segment label from a different table block. Trigger: a tracked filing with near-identical sibling labels. `docs/reviews/2026-09-13-table-grounding-region-scoped-matching.md`
- **[bug (latent), Low, Trivial]** A large `header_context` inflates `quote_is_grounded`'s coverage (25% → 88% in synthetic testing, never past the 90% threshold). Trigger: a fabricated quote crossing it. `docs/reviews/2026-09-13-table-grounding-region-scoped-matching.md`
- **[bug (latent), Low, Trivial]** `_classify_row` treats a data row with a blank first cell as a header and drops it from `locate_value` (fails safe to `_quote_matches`). Trigger: a real filing with that shape. `docs/reviews/2026-09-13-table-grounding-region-scoped-matching.md`
- **[feature, Low, TBD]** `NUMBER_PATTERN` doesn't recognize `M`/`B`/`K` abbreviations. Rule 9 bans them; if ever added, recognize `MM`/`Bn`, not bare letters. Trigger: an abbreviation in a live answer. `docs/decisions/2026-09-17-uncovered-number-gap-fixes.md`
- **[test-coverage, Low, Standard]** Citation stress modes: the two-nearby-percentages question (`nvda-revenue-yoy-growth-q1fy27`) cited the risky sentence in only 1 of 3 runs, and a paraphrased quote near the 0.90 threshold is untested. Trigger: `analyze_flakiness.py` history showing the risky sentence exercised reliably (then close it), or a way to force a paraphrase. `docs/decisions/2026-09-23-restore-nvda-yoy-stress-question.md`

**Refusals that need the failing quote captured** (check the `submit_answer` span's `checks` in `trace_logs/traces.jsonl` first; the trace query script item helps)

- **[bug (latent), Low, Standard]** `nvda-cost-of-revenue-fy2026`: a `quote_not_found` refusal via `search_filings` prose, then clean via XBRL on re-run. Trigger: a recurrence. `e45de8b:BACKLOG.md`
- **[bug (latent), Low, Standard]** `msft-segment-revenue-comparison-q3fy2026`: `quote_not_found` on the real segment values `35013`/`34681`/`13192` (2026-09-14 baseline). Trigger: a recurrence. `e45de8b:BACKLOG.md`
- **[bug (latent), Low, Standard]** `aapl-rd-pct-gross-profit-fy2025`: two other refusal modes (`cited_claim_unsupported` on 17.7%, and an inline uncited 17.7%/0.177). Confirm which one fired before blaming the 2026-09-17 fix. Trigger: a recurrence. `e45de8b:BACKLOG.md`

**Agent loop and code structure**

- **[bug (latent), Low, Standard]** The final-turn safety net could force a grounded but incomplete answer (fewer companies than asked). Trigger: a confidently wrong ranking from a forced submit. `docs/decisions/2026-09-16-final-turn-safety-net.md`
- **[refactor, Low, Trivial]** `_dispatch_tool_call`'s tool branches are an if-chain. Trigger: a 5th or 6th tool (then use a dispatch table). `docs/reviews/2026-09-11-negative-number-support.md`
- **[refactor, Low, Standard]** `formulas.py` has 3 hand-written zero-denominator guards. Trigger: a 4th call site (then extract a shared `_safe_ratio()`). `docs/reviews/2026-09-08-fix-3-medium-review-findings.md`
- **[feature, Low, Substantial]** Per-call LLM generation tracing in Langfuse (tokens, prompt/completion text, cost and latency per call). Trigger: a real debugging need. `docs/decisions/2026-09-04-langfuse-tracing.md`

**Tooling and workflow**

- **[design, Med, Standard]** Audit finding 7: the judge verdict is parsed from a two-line format (`startswith("PASS")`), so `**PASS**` or a preamble would grade FAIL. Fix: structured output for the judge. It touches `grade_judged`, so it needs a panel screen. Trigger: `lenient parse disagrees` in any eval report (0 hits through WP8). `docs/reviews/2026-09-24-prompt-audit.md`
- **[design, Low, TBD]** Pyright strict mode (rejected 2026-09-15: ~94% of its errors were noise from dict-shaped data). Trigger: less untyped-dict data flow (`TypedDict`/`dataclass`), or a scoped-down strict preset. `docs/decisions/2026-09-15-adopt-pyright.md`
- **[design, Low, TBD]** A `PreToolUse`/`ExitPlanMode` hook backstop for the plan-review floor. Trigger: instruction-only enforcement caught missing a review. `docs/decisions/2026-09-17-mandatory-plan-review-floor.md`
