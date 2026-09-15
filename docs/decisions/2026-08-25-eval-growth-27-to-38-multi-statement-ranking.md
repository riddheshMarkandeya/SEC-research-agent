# Eval growth 27 → 38: multi-statement ratios, cross-section synthesis, indirect disambiguation, cross-company ranking

**Date:** 2026-08-25

## Context

Targeted three gap categories, each isolating one specific untested
variable: multi-statement ratios with no formula-registry tool support,
pure unstructured multi-chunk synthesis, and indirect (no-explicit-name)
company disambiguation. A same-day addendum then added cross-company
ranking questions after comparing PIXIU/FinBen benchmark coverage
against `compare_financial_metric`'s own untested system-prompt-worked
ranking example.

## Decision

27 → 35: `aapl-return-on-assets-fy2025`, `nvda-asset-turnover-fy2026`,
`msft-cash-to-assets-fy2025` (multi-statement, no tool support yet);
`aapl-cash-and-buyback-q3fy2026`, `crm-buyback-and-liquidity-q1fy27`
(cross-section synthesis, graded via the existing `"comparison"` type
reused for a single company's two facts); `nvda-revenue-fy2026-indirect`,
`aapl-employees-fy25-indirect`, `msft-net-income-fy2025-indirect`
(indirect disambiguation). Addendum 35 → 38: three `judged` cross-company
ranking questions, one per existing margin formula.

## Why

A real bug found in `nvda-asset-turnover-fy2026`'s own first draft,
before the full run: `expected_unit: "percent"` doesn't cross-match
`normalize()`'s `"raw"` category even for numerically-equivalent values
(104.4 vs 1.044) — fixed by switching to `"raw"`/1.04, matching how
asset turnover is conventionally expressed.

Gemini: 33/35 (8/8 new questions clean); Ollama: 23/35 (only 2/8 new
passed), surfacing several genuinely new Ollama failure modes verified
against real data: answering about the wrong company entirely
(`aapl-return-on-assets-fy2025`, computed from MSFT's real figures
despite the question naming only Apple); a fabricated total-assets value
matching no real MSFT period (`msft-cash-to-assets-fy2025`); a stale
prior-year figure plus a wrong self-computed workaround
(`aapl-cash-and-buyback-q3fy2026`); a structurally-narrower XBRL tool
result used for a broader question
(`crm-buyback-and-liquidity-q1fy27`); and a self-computed ratio with NO
citation marker at all slipping past `verify_citations()` on Gemini even
though the same self-computation was correctly gated on Ollama —
flagged as a real, newly-surfaced verifier gap (a claim can dodge the
check entirely by citing nothing), not fixed this round.

The ranking-question addendum surfaced a real ambiguity: a first draft
using "Apple's fiscal year 2025 as the reference period" for all five
companies failed outright once and, on a second run, reached the right
company via the wrong period (NVDA's own fy2025 instead of the
calendar-contemporaneous fy2026) — the same fiscal-year-label-vs-
calendar-frame mismatch class already guarded against elsewhere, hit
from a new angle. Fixed by spelling out each company's own correctly-
labeled fiscal year/end date directly in the question text.

## Files touched

`eval_questions.jsonl`.

## Verification

Gemini `eval_results/20260825T022950Z.json` (33/35), Ollama
`eval_results/20260825T044611Z.json` (23/35); ranking addendum
`eval_results/20260825T233524Z.json` (3/3 on Gemini, matching ground
truth exactly).

## Related

`docs/decisions/2026-08-25-formula-registry-roa-turnover-cash.md` (closes
the citation-verification-gap finding by removing its root cause for
three of these ratios).
