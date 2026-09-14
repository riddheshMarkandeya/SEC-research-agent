# Review: tool-turn-waste fix (Mechanisms 1 + 2, Mechanism 3 reverted)

Plan: `docs/plans/2026-09-14-tool-turn-waste.md`. Fixes two of the four
turn-waste mechanisms a 47-question eval baseline found (2026-09-13,
31/47): an unnecessary `calculate` call for a pure unit conversion, and
re-fetching a value's components after a tool already returned the
exact answer. Prompt/schema-description/error-message changes only, no
loop change. Full suite green throughout (631 → 634).

## Pass 1 — correctness and CLAUDE.md compliance (self, medium effort)

1. **[Verified, no fix needed] Architecture fit.** Duplicating guidance
   between `SYSTEM_PROMPT`'s tool overview and each tool's own schema
   `description` matches this codebase's existing convention (the
   pre-existing `yoy_growth` text already does this) — both are
   separate channels shown to the model, so reinforcing both is
   consistent, not new debt.
2. **[Verified] Mechanism 1's fix is grounded in the actual verifier,
   not assumed.** Traced `_verify_one_claim`/`normalize()`/
   `_number_candidates`: a claim restated in a different unit
   (`4.48 billion` quoting a raw `4,475,446,000` source) passes
   `verify_claims` with zero warnings, confirming the new rule-9
   guidance's 1%-tolerance claim matches the real verification math
   exactly, not a hopeful approximation.
3. **[Fixed, found in self-review before the second pass] Test
   assertion checked the absence of an arbitrary phrase rather than the
   intent.** An early version of
   `test_call_calculate_operand_wrong_unit_names_the_correct_unit_not_the_value`
   asserted `"not correct" not in error.lower()` — true but meaningless.
   Replaced with a positive assertion on what the message should
   actually say once its wording was later revised (see Pass 2 item 2).

## Pass 2 — architecture, design, performance, refactoring (fresh subagent, no memory of the implementation session)

**Verdict: found one High-severity real gap, fixed before shipping.**

1. **[Fixed, HIGH] The terminal-case message overclaimed what
   `_ground_operand` had actually checked.** The first version's
   message, on failing to ground an operand under any unit, said
   *"trying a different unit **or citation index** will not help"* and
   *"this operand simply isn't grounded in anything you've
   retrieved"* — but the function only ever inspected
   `all_results[citation_index - 1]`, never any other already-retrieved
   result. If the model's actual mistake were a wrong citation index
   (the value genuinely living in a different result — a plausible
   transcription slip), this message would be false, and would actively
   tell the model not to try the one correction that would have worked
   — reopening exactly the class of problem this whole fix exists to
   close, just relocated to a different field. **Fix**: added a third
   check — scan every OTHER already-retrieved result under the
   claimed unit before concluding terminal; if the value is found
   there, name that result and say the citation index specifically is
   wrong. Only when neither a different unit (same result) nor the same
   unit (different result) matches is the terminal message now used,
   and its claim is true because both alternatives were actually
   checked, not assumed. New regression test:
   `test_call_calculate_operand_wrong_citation_index_names_the_correct_result`.
2. **[Fixed, Medium] The mislabeled-unit message asserted more
   confidence than a coincidental-tolerance match can support.** *"the
   value and citation index are correct"* is a stronger claim than a
   fuzzy numeric match in a multi-number chunk can actually prove — a
   pre-existing epistemic limit of this codebase's whole tolerance-based
   matching approach (shared by `_quote_matches`, `value_is_citation_
   verified`, etc.), not something this diff should silently overstate.
   Softened to "double check `{operand_name}`'s UNIT specifically"
   — still actionable, without a certainty claim the check doesn't
   earn. Test assertion loosened to match (checks for "unit" being
   named, not the retracted "are correct" phrasing).
3. **[Verified, no fix needed] Test coverage is meaningful, not
   overfit.** The new tests assert on which operand is named, which
   unit is suggested, and which result index is named — semantic
   properties of the fix — rather than pinning an exact string.
   Existing calculate tests (`rejects_operand_not_grounded_in_cited_
   source`, `..._names_it_specifically`) were confirmed to still route
   through the (now-true) terminal branch correctly, since their
   fixtures genuinely don't contain the operand under any unit or index.
4. **[Noted, not fixed — pre-existing, out of scope] Rule 3 wasn't
   cross-updated with rule 9's new "restating in a different unit is
   not a derivation" carve-out.** Low risk (rule 9's wording is concrete
   and gives a worked example), and touching rule 3 was outside this
   diff's scope; flagged for awareness, not acted on.
5. **[Noted, not fixed — cosmetic] `_ground_operand`'s now-three-phase
   check (same unit → other units, same result → same unit, other
   results) could be restructured into one pass that computes all
   matches up front, then branches.** A readability nit, not a
   correctness issue; not worth the diff size increase for this task.

## Live verification

- **Targeted spot-check** (`eval/eval_results/20260914T232305Z.json`,
  7 questions): all four Mechanism-1/2 targets pass
  (`pltr-revenue-2025`, `crm-revenue-q1fy27`, `aapl-revenue-growth-
  q3fy2026`, `aapl-3yr-avg-operating-margin-fy2023-fy2025`), plus three
  regression guards for questions that legitimately use `calculate`/
  ratios (`msft-cash-to-assets-fy2025`, `aapl-rd-pct-gross-profit-
  fy2025`, `nvda-inventory-turnover-fy2026`) — 7/7 clean, zero
  regression on the legitimate-`calculate` path.
- **Full 47-question baseline** (`eval/eval_results/20260914T233319Z.json`):
  **36/47 passed, up from 31/47** (2026-09-13). Mechanism-by-mechanism:
  - **Mechanism 1 (unit conversion) — confirmed dead.** `crm-revenue-
    q1fy27` passed cleanly with zero `calculate` calls. `pltr-revenue-
    2025`'s specific live instance in this run still failed, but its
    trace shows **zero `calculate` calls** (get_financial_fact then 4
    `search_filings` calls) — a different, pre-existing, unrelated
    "redundant prose re-verification" behavior, not the targeted
    calculate-loop. That same question passed cleanly in 3 other live
    calls earlier in this session (the targeted spot-check, plus two ad
    hoc re-verifications), consistent with this project's documented
    live model non-determinism (see `BACKLOG.md`'s `msft-cash-to-assets-
    fy2025` history, same pattern).
  - **Mechanism 2 (re-derivation) — confirmed dead.** `aapl-revenue-
    growth-q3fy2026` and `aapl-3yr-avg-operating-margin-fy2023-fy2025`
    both passed cleanly, first turn, no re-fetching.
  - **4 new failures, none attributable to this diff**: `aapl-ai-risk`
    and `crm-ai-risk` show the identical pre-existing `"[N] claims N
    (raw) but that value doesn't appear in the quoted text"` pattern
    already present in the 2026-09-13 baseline on `nvda-supply-chain-
    risk`/`pltr-government-contract-risk` (a numbered-list-bullet
    misread as a numeric claim — an unrelated, already-live bug class
    this diff never touches). `pltr-dividend-2019-refusal` now gives a
    correctly-reasoned, well-cited direct answer instead of the old
    accidental citation-gate refusal; the grading criteria wanted an
    explicit refusal phrasing, a judge/criteria brittleness unrelated to
    this diff. `nvda-inventory-turnover-fy2026`'s specific instance in
    this run hit a different retrieval path (searching for inventory
    via prose after `inventory_turnover`'s pre-built ratio returned
    unavailable) — the same question passed cleanly with `calculate`
    used correctly in this session's own targeted spot-check minutes
    earlier, again consistent with live non-determinism rather than a
    regression.
  - **5 additional passes not directly targeted** (`nvda-supply-chain-
    risk`, `nvda-crm-revenue-comparison`, `aapl-cash-equivalents-
    q3fy2026`, `nvda-segment-revenue-comparison-q1fy27`, `five-company-
    net-margin-ranking-fy2025`) — plausibly benefiting from reduced
    prompt noise or ordinary live non-determinism; not claimed as a
    direct effect of this diff.
- Per `CLAUDE.md`'s quota-awareness rule, a second full baseline was not
  run to chase the non-determinism above — the targeted spot-check
  already isolates the fixed mechanisms cleanly, and this project's own
  documented history treats single-question live variance as expected,
  not as evidence requiring another full run.

## Outcome

Mechanisms 1 and 2 (4 of the original 9 timeout failures) are fixed and
live-verified, with zero measured regression on questions that
legitimately exercise `calculate`/ratios. The full baseline moved 31/47
→ 36/47. Mechanism 3 (rankings not routing through `compare_financial_
metric`) was attempted three times live with two different wordings,
failed identically each time, and was reverted — see the plan's
addendum and `BACKLOG.md` for the concrete evidence and working
hypothesis. Mechanism 4 (the turn-budget/final-safety-net loop change)
remains explicitly out of scope, filed to `BACKLOG.md` per the plan's
own Scope section.
