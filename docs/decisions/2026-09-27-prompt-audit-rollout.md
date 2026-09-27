# Prompt-audit rollout summary (WP1–WP8, roadmap closed)

**Date:** 2026-09-27

## Context

`docs/plans/2026-09-24-prompt-audit-roadmap.md` turned the findings of
`docs/reviews/2026-09-24-prompt-audit.md` into eight work packages. Each package changed what a
model reads, one commit at a time, and was screened on the 13-question × 3-run panel. This is
the roadmap's Step 9 file. It gives one row per WP and says what is left open.

## Decision

The roadmap is closed. WP1–WP7 were all accepted at their screens, and none was reverted. WP8's
full run passed its bar at 40/47, against 39/47 and 38/47 from before the audit. The Gemini model
pin stays.

| WP | commits | agent fingerprint | panel B → C | outcome | watch | record |
|---|---|---|---|---|---|---|
| WP1 prompts package | `bbf41d7`, `ccdb9c8`, `e66ecce` (+ review fixes) | — (before fingerprints) | no panel: sha256 hashes and a 44-entry golden capture byte-identical after every commit | accepted (pure move) | — | `docs/decisions/2026-09-24-wp1-prompts-package.md` |
| WP2 provenance and baseline | `8f5fc68`…`c4ee23c` (1d), review fixes to `2c3dbdd` | `cc984387c3e8` | baseline, no B: C 37/39 | accepted | — | `docs/decisions/2026-09-24-wp2-prompt-provenance.md` |
| WP3 group-A wording | `10d4a58`, `50d9be5`, `252186d`, `ac03018`, `12554a4` | `cc984387c3e8` → `4f36a2b026cf` | 37/39 → 37/39 | accepted | `aapl-msft-total-assets-comparison` | `docs/decisions/2026-09-24-wp3-group-a-wording.md` |
| WP4 rule 3 / rule 9 | `7fdfecd`, `0675297` (+ docstring fixes) | `4f36a2b026cf` → `d2131f5d5aae` | 37/39 → 33/39 | accepted | `nvda-rd-expense-q4fy26-refusal` (Q4-refusal signal; replicate was noise) | `docs/decisions/2026-09-25-wp4-rule3-rule9.md` |
| WP5 segment rule | `d45156f` | `d2131f5d5aae` → `5d3cea51c73b` | 33/39 → 31/39 | accepted after replicate 3/3 | `nvda-revenue-two-quarter-comparison` ("− 1" gate false positive) | `docs/decisions/2026-09-26-wp5-segment-rule.md` |
| WP6 no-data message | `1e1491b`, `ca6cace` (+ `b16c64c`) | `5d3cea51c73b` → `e073094f18b9` | 31/39 → 35/39 | accepted | `pltr-government-contract-risk` | `docs/decisions/2026-09-26-wp6-no-data-message.md` |
| WP7 year strings | `264fbc6`, `309d90a` (+ `260cf4b`) | `e073094f18b9` → `7aec53939ce3` | 35/39 → 36/39 | accepted | `nvda-revenue-two-quarter-comparison` | `docs/decisions/2026-09-26-wp7-fiscal-year-strings.md` (figures as corrected in `cbc2bf4`) |
| WP8 final run | (report only) | `7aec53939ce3` | full suite: 39/47 and 38/47 → **40/47** (41/48) | bar met; model pin kept | the header-echo gate miss (both NVDA drops) | `docs/decisions/2026-09-27-wp8-final-run.md` |

## Why

- **Every panel total stayed above its threshold**, and every REGRESSED flag was explained as
  noise or by a named mechanism outside the prompt text. So nothing was reverted.
- **The panel moved 37 → 36 across WP3–WP7**, and the full suite moved 38–39 → 40. The audit
  aimed to fix contradictions and mismatches, not to raise scores. Its bar was "no worse", and
  it met that.
- **What remains is mostly the citation gate, not prompt text.** Every WP8 drop and most panel
  misses were gate refusals, either false positives on correct answers or refusals of
  computed values. That is why the baseline-improvement plan comes next.

## Left open (filed in `BACKLOG.md`)

- (a) **Finding 7** (judge structured output) is deferred to the Watch list. Its trigger is
  `lenient parse disagrees` in a report; there have been 0 hits so far.
- (b) **Notes 8–10**, one Low item: all-caps emphasis, tool bullets that duplicate their
  descriptions, the size of rule 9, sentences duplicated across surfaces, and the hard-coded
  "five companies".
- (c) **Confirmed-and-reverted findings:** none. WP3–WP7 were all accepted.
- (d) **The baseline-improvement plan** is next. Candidates: the "− 1" gate false positive, the
  Q4-hint vs judge conflict, and the unprefixed header echo.
- (e) **Step 7 follow-ups:** reason-bearing rejections via `on_reject` (including boundary
  rejections), `calculate`'s generic missing-argument message, MCP search's silent `[]`, and
  the yoy no-data reply naming the anchor period.
- (f) Moot: this was already recorded at WP7.

## Files touched

This file; `docs/decisions/2026-09-27-wp8-final-run.md`; `BACKLOG.md`; `PROJECT_INDEX.md`.

## Related

- Roadmap: `docs/plans/2026-09-24-prompt-audit-roadmap.md`
- Audit findings: `docs/reviews/2026-09-24-prompt-audit.md`
- Final run: `docs/decisions/2026-09-27-wp8-final-run.md`
