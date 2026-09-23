# Review: eval-question solid/flaky/regression classification

Plan: `docs/plans/2026-09-22-eval-question-classification.md`. Change:
extends `analyze_flakiness.py` with a capped-window classifier
(`ClassificationThresholds`, `classify_history()`, restructured
`format_summary()`) replacing the old unbounded flat pass-rate ranking.
Test suite before this diff: 757 passing.

## Plan review (independent subagent, before implementation)

Hand-tested the precedence chain against synthetic histories beyond the
ones named in the draft plan and found two real algorithmic bugs before
any code was written:

- **[Fixed]** A currently-recovered question (14 fails then 6 clean
  passes) was misclassified as an active regression by the original
  5-branch design. Fixed by adding a symmetric recovery check
  (`trailing_pass_streak >= regression_streak` → solid) as its own
  branch.
- **[Fixed]** `solid_floor=0.85` was unreachable by the plan's own
  headline "one blip stays solid" scenario at the smallest window
  `min_appearances` admits (`4/5=0.80 < 0.85`). Fixed by lowering the
  default to 0.80, verified by hand-computing the exact fraction.
- **[Fixed]** `main()` never sorted `args.reports` before ordering became
  correctness-critical for streak/transition logic (previously harmless
  since only unordered aggregate counts were computed). Added a sort
  before `load_rows()`.
- **[Fixed]** Two tests originally listed as "keep unchanged" would have
  raised `TypeError` from the `format_summary()` signature change
  (`min_appearances` kwarg replaced by a `ClassificationThresholds`
  object); both updated during implementation.

Full findings: this file's own record above is the record — no separate
plan-review file, since implementation started immediately after fixing
these before `ExitPlanMode`.

## Pass 1 — correctness and CLAUDE.md compliance (`/code-review`, medium)

- **[Fixed]** Module and `ClassificationThresholds` docstrings pointed to
  `docs/decisions/2026-09-22-eval-question-classification.md` for the
  actual reasoning instead of stating it self-containedly — a direct
  violation of this project's comment-hygiene rule (`docs/decisions/
  2026-09-15-revoke-comment-pointer-convention.md`), and the referenced
  file didn't exist yet at review time. Rewrote both to state the
  reasoning directly.
- **[Fixed]** `window=0` silently meant "use the whole history" instead
  of the CLI flag's implied "classify on zero recent runs," because
  Python's `history[-0:]` equals `history[0:]`. Added `__post_init__`
  validation rejecting `window < 1`.
- **[Fixed]** The final `else: "flaky"` fallback branch could label a
  non-oscillating, persistent partial-failure history as "flaky" while
  the docstring only defined "flaky" via the oscillation signal.
  Extended the docstring to state this fallback explicitly rather than
  leaving it undocumented.
- **[Fixed]** `_format_row` hardcoded a "95% CI" label regardless of the
  actual `confidence_z` used (only reachable via direct API use, no CLI
  flag existed for it at the time). Added a `confidence_z`-driven label.

## Pass 2/3 — architecture, design, performance, refactoring, modularity + doc hygiene (fresh subagent)

- **[Fixed]** `regression_streak`, `flaky_min_transitions`, and
  `min_appearances` had the same class of footgun as `window` (a
  `>=`/`<` comparison against 0 becomes trivially true/false) with no
  guard. Verified empirically: `regression_streak=0` classified a
  perfect all-pass 20-run history as "regression." Added validation for
  all three, plus `solid_floor` range validation.
- **[Fixed]** `_trailing_fail_streak`/`_trailing_pass_streak` were
  near-duplicate code (the docstring even said "mirrors ... exactly").
  Consolidated into a shared `_trailing_streak(history, want)`, kept as
  thin named wrappers for call-site readability and the existing test
  API.
- **[Fixed]** `r[2]["windowed_pass_rate"] or 0.0` in
  `_sorted_section_rows` was dead defensive code — `windowed_pass_rate`
  is guaranteed a plain float, never falsy-as-None, by
  `classify_history()`'s own contract. Simplified to a direct reference.
- **[Verified, no fix needed]** `entry["pass_rate"]`/`entry["passed"]`
  in `summarize()`'s output are no longer read by the reporting
  pipeline (superseded by `history`-derived windowed stats) but remain
  a valid standalone aggregate for any other caller of `summarize()` —
  not dead code.
- **[Fixed]** A test comment pointed to "the plan's own reasoning"
  instead of stating the fact directly. Rewrote to state the Wilson
  lower-bound value and its significance inline.
- **[Fixed]** The plan's own documentation checklist (decision doc,
  `PROJECT_INDEX.md` entry, `BACKLOG.md` item) hadn't been executed yet
  at review time — closed in this same session, see below.

## Pass 4 — security review (fresh subagent)

No findings. Pure arithmetic/classification logic over trusted,
locally-generated JSON report files; no new file I/O, subprocess,
network, templating, deserialization, or credential-handling surface.

## Pass 5 — reuse, simplification, efficiency (`/simplify`)

**Round 1 findings, all fixed:**
- Four copy-pasted `if x < 1: raise ValueError(...)` blocks in
  `__post_init__` collapsed into one loop over the shared field names.
- Two `elif` branches both assigning `classification = "solid"` merged
  into one `or`-combined condition.
- A hardcoded `_KNOWN_Z_CONFIDENCE` lookup table (four well-known
  z-scores → percentage strings) replaced with the closed-form
  `erf(z/sqrt(2))` computation it was a hand-copied special case of —
  verified numerically to reproduce all four original table entries
  exactly, and now correct for any `confidence_z`, not just those four.
- A bare module constant `_MOSTLY_FAILING_THRESHOLD`, governing the same
  kind of classification decision as the other four (validated,
  CLI-exposed) thresholds, was promoted to a proper
  `mostly_failing_ceiling` field on `ClassificationThresholds` with the
  same validation treatment and a new `--mostly-failing-ceiling` CLI
  flag.
- Reuse and efficiency agents found nothing (no existing binomial/
  streak/section-formatter helper elsewhere in the repo to reuse
  instead; no wasted computation at this script's ~130-file scale).

**Round 2** (re-review of round 1's own fixes, per this skill's own
rule that a `/simplify` edit must be re-checked): found two further real
issues introduced by promoting `mostly_failing_ceiling` to a
configurable field:
- **[Fixed]** `confidence_z` was left unvalidated. A negative value
  flips the sign of `_wilson_interval`'s margin term, returning an
  inverted (`lower > upper`) interval, and would render a nonsensical
  negative percentage via the new `erf`-based label. Verified the
  inversion numerically. Added `confidence_z > 0` validation.
- **[Fixed]** Nothing constrained `mostly_failing_ceiling` relative to
  `solid_floor`, despite them being opposite ends of the same pass-rate
  range in `classify_history()`'s branch order. If a caller set
  `mostly_failing_ceiling >= solid_floor` (a legal CLI flag combination),
  every case reaching that check would already have `pass_rate <
  solid_floor`, making it automatically `< mostly_failing_ceiling` too —
  silently eliminating the final "flaky" catch-all branch for every
  ambiguous case, everything becoming "regression" instead. Added a
  cross-field `mostly_failing_ceiling < solid_floor` validation.

**Round 3**: re-checked the round-2 fixes for style consistency,
altitude (whether `__post_init__`'s now-7 checks warrant restructuring
into a declarative table — concluded no, per YAGNI: four collapse into
the existing loop, the remaining three are irreducibly heterogeneous
single- or cross-field checks), and reuse/efficiency. No further
findings — review loop closed clean per the two-round cap.

## Live verification

Not applicable — this change touches no live-code surface
(`.claude/rules/live-eval-verification.md`'s and `.claude/rules/
plan-review-blast-radius.md`'s file lists are untouched; `eval_harness.py`
itself is unmodified). Verified instead against the real historical
data: `python analyze_flakiness.py eval/eval_results/*.json` against all
127 report files. `msft-segment-revenue-comparison-q3fy2026` (24%
all-time, long-documented as chronically troubled in `BACKLOG.md`) lands
in Regression with an active 8-run trailing fail streak;
`crm-rpo-fy26` (98% all-time) lands in Solid at 19/20=95%. The
recovery-streak fix (from plan review) visibly does real work on this
real data: several questions with a rough historical patch but a long
current pass streak (e.g. `nvda-supply-chain-risk`, 50% windowed rate
but a 9-run current pass streak) correctly land in Solid rather than
Flaky/Regression.

## Outcome

Shipped: `ClassificationThresholds`, `classify_history()` and its four
helpers, restructured `summarize()`/`format_summary()`, extended CLI.
Nothing deferred to `BACKLOG.md` from this review itself (every finding
across all passes and rounds was fixed in-session); one pre-existing
scope boundary from the plan (Meta-style same-commit burst reruns) is
tracked there as a genuinely separate, larger feature. Final test suite:
766 passing (up from 757 before this change). `ruff check .` and
`pyright .` both zero errors full-repo. Diff coverage on
`analyze_flakiness.py`: 91.9% (above the 80% ordinary-file bar; this
file is not in the 90% critical-core list). Review loop closed clean
after 3 rounds (round 3 found nothing new).
