# WP8: final full run after the prompt audit (bar met, 40/47)

**Date:** 2026-09-27

## Context

WP8 is Steps 8–9 of `docs/plans/2026-09-24-prompt-audit-roadmap.md`. It spends the roadmap's
one full-suite run to check the audit's end state (agent `7aec53939ce3`, after WP1–WP7)
against the last two full runs from before the audit. Plan and plan review:
`docs/plans/2026-09-26-wp8-final-run.md`, `docs/reviews/2026-09-26-wp8-final-run-plan-review.md`.

## Decision

- **Bar met: 40/47** on the 47 shared questions (bar ≥ 38; baselines 39/47 and 38/47). The
  restored 48th question passed, so the 48-question total is **41/48**.
- **Every drop is explained** from the report and traces, so no rerun budget was used.
- **No unexplained regression** and no sum under 38, so no regression note is needed.
- **Model pin kept** (user decision): `GEMINI_MODEL_NAME=gemini-3.5-flash-lite`. Every report
  since WP2 is on this model, and the baseline-improvement work needs the same stability.
  Re-pin deliberately if the alias moves or the model is deprecated.
- **A latent Watch list trigger fired:** `_strip_citation_header` misses an echoed header that
  has no `[n]` prefix. It caused both NVDA drops, so the item moves out of the Watch list and
  becomes a baseline-improvement candidate.

## The run

- Report `eval/eval_results/20260927T071935Z.json`: 2026-09-27 07:07:52–07:19:36Z, SHA
  `04e2b1e`, clean tree, snapshot verified, agent `7aec53939ce3`, judge `2ee29f234c91`, mcp
  `b34024a4d17d`, google-genai 2.18.1, mcp 2.1.1.
- Pre-run gate: tree clean; fingerprint `7aec53939ce3`; 0 `run_agent` spans since 07:00Z;
  `.env` pin present; `tests/test_model_input_snapshot.py` 3 passed.
- No `RESOURCE_EXHAUSTED`, no dropped rows. 16 transient 429 retries, none exhausted.

## Comparison

`python compare_prompt_versions.py --base-files eval/eval_results/20260921T222521Z.json
eval/eval_results/20260922T062823Z.json --candidate-files eval/eval_results/20260927T071935Z.json`
(explicit mode). Exit 1 and the REGRESSED flags are expected with 2 base runs vs 1 candidate
(plan should-fix 1). The tool also warned that judge fingerprint, `answer_model`, `judge_model`
and config differ: the baselines are unstamped and used the alias.

| change vs baselines | questions |
|---|---|
| improved (was 0/2) | `nvda-inventory-turnover-fy2026`, `nvda-rd-expense-q4fy26-refusal`, `nvda-revenue-fy26-us-gaap` |
| improved (was 1/2) | `aapl-msft-employee-comparison`, `msft-rd-intensity-fy2025` |
| dropped | `nvda-revenue-fy26` (2/2 → 0/1), `pltr-inventory-turnover-fy2025-refusal` (2/2 → 0/1), `nvda-gross-margin-fy26` (1/2 → 0/1) |
| still failing (0/2) | `crm-buyback-and-liquidity-q1fy27`, `msft-segment-revenue-comparison-q3fy2026`, `msft-three-segments-revenue-q3fy2026`, `pltr-dividend-2019-refusal` |
| unchanged pass | the other 35 |

`nvda-revenue-yoy-growth-q1fy27` (candidate-only): passed. It also passed all 3 of its earlier
runs (`20260923T235310Z/235436Z/235540Z`).

## Drops explained

- **`pltr-inventory-turnover-fy2025-refusal`** (panel question): passed 2/3 in the WP7 screen
  at the same fingerprint (`20260926T085714Z/090017Z`). It fails the same way as the third
  screen run (`090341Z`): the model computes a turnover from search results and the gate refuses
  a `quote_not_found` claim, instead of saying Palantir has no inventory. That makes it noise
  under the plan's rule, and it used no rerun budget.
- **`nvda-revenue-fy26`** (run `d00cb8964070`): `get_financial_fact` found 215,938,000,000. The
  model's claim quoted `"NVDA 10-K (reportDate=2026-01-25)\nrevenue = 215938000000 USD"`, which
  is the rendered citation header without its `[1] ` prefix. `_strip_citation_header` strips
  only the exact `[n] …` header, so the quote failed `quote_not_found`. The citation retry, three
  searches and a forced final turn repeated the same quote, and the gate withheld it
  (`gate_withheld_would_have_passed: True`).
- **`nvda-gross-margin-fy26`** (run `b8d0368b4dda`): the same first step. The fact returned 71.1
  and the quote carried the unprefixed header. After the retry the model switched to a prose
  answer about the Hopper → Blackwell transition and dropped 71.1. The gate refused an uncovered
  "4.5 billion" (`gate_withheld_would_have_passed: False`).
- **Why these two now:** in the 09-21 baseline both fact calls sent `fiscal_year='2026'` and
  were rejected, so the model reached the value by other paths. WP7's int conversion now lets the
  fact call succeed first time, which exposes the header-echo quote. The miss itself is older
  than the audit: submit spans with an unprefixed-header quote and `quote_not_found` appear in
  the traces on 09-11, 09-12, 09-13, 09-17, 09-19, 09-21, 09-22, 09-25 and 3 times on 09-27.
  In the 09-22 baseline, the same int-year fact path passed both questions, so the header echo
  depends on the sampled run.

**Rerun:** none. The plan reruns only drops the trace doesn't explain, and all three are
explained.

## Judge flag

`lenient parse disagrees`: 0 hits in the new report. Finding 7's trigger is still unmet.

## Trace counts

Windows start at each run's first `run_agent` span and end at the report's timestamp.
`final_turn_forced` (added 09-23) and `tool_arg_coerced` (added 09-26) postdate the baselines.

| kind, reason | 09-21 22:12–22:25Z | 09-22 06:16–06:28Z | 09-27 07:07–07:19Z |
|---|---|---|---|
| `tool_call_rejected`, `invalid_fiscal_year_type` | 7 | 9 | 0 |
| `tool_call_rejected`, `claims_not_in_enum` | 1 | 0 | 0 |
| `tool_arg_coerced` | — | — | 5 |
| `unmet_metric_request`, `no_data_for_ticker` | 1 | 1 | 2 |
| `citation_gate_refused` | 4 | 4 | 5 |
| `final_turn_forced` | — | — | 6 |
| `llm_retry` (429) | 19 | 18 | 16 |

WP7's conversion replaced every `invalid_fiscal_year_type` rejection (16 across the baselines,
0 now, with 5 conversions). The 09-21 window holds 50 `run_agent` spans for 47 questions, so it
isn't a clean one-run window. Its counts are an upper bound.

## Caveats

- **47 vs 48:** the bar compares the 47 shared questions. The 48th has no baseline.
- **Alias vs pin:** the baselines ran on `gemini-flash-lite-latest`. Nobody recorded what the
  alias pointed to on 09-21/22. It resolved to `gemini-3.5-flash-lite` on 09-24. A model change
  between the baselines and now is unconfirmed, and it isn't ruled out either.
- **One candidate run:** each per-question result is a single sample. The sum is the bar, not
  any one row.

## Files touched

The report above; this file; `docs/decisions/2026-09-27-prompt-audit-rollout.md`; `BACKLOG.md`;
`PROJECT_INDEX.md`.

## Related

- Plan: `docs/plans/2026-09-26-wp8-final-run.md`; review:
  `docs/reviews/2026-09-26-wp8-final-run-plan-review.md`
- Roadmap summary: `docs/decisions/2026-09-27-prompt-audit-rollout.md`
- Previous WP: `docs/decisions/2026-09-26-wp7-fiscal-year-strings.md`
- Header-strip fix whose gap fired: `docs/decisions/2026-09-19-citation-header-in-quote-fix.md`
