# Classify eval questions as solid / flaky / regression

## Context

The eval suite (`eval_harness.py`, 47 questions) has accumulated 127
historical run reports in `eval/eval_results/` since 2026-08-14.
Questions are inherently non-deterministic (LLM generation, tool-choice
variance, occasional judge variance), so a question can fail without any
code change — and the project already leans on this fact constantly:
nearly every recent decision doc ends with a paragraph manually arguing
"this baseline dip is pre-existing flakiness, not a regression" by eyeballing
`analyze_flakiness.py`'s pass-rate table (e.g.
`docs/decisions/2026-09-22-pyright-clean-refactor.md`,
`docs/decisions/2026-09-21-ruff-complexity-refactor.md`).

`analyze_flakiness.py` (added 2026-09-18, see
`docs/decisions/2026-09-18-flaky-eval-questions-three-fixes.md`) already
ranks questions by **all-time, unbounded** pass rate — but that's it: one
continuous number, no classification, and no time-boundedness. Two real
problems fall out of that today:

1. **Unbounded history conflates code eras.** A question fixed two weeks
   ago still carries its old failing runs into its pass rate forever
   (live data has `n_runs` per question ranging from 1 to 62).
2. **No distinction between "genuinely non-deterministic" and "currently,
   persistently broken."** Both look like "a somewhat low pass rate" in
   the existing flat ranking; telling them apart is still done by hand,
   per question, every session.

The user asked for a properly-grounded way to make this call — "how is
flakiness normally defined by others" — rather than continuing to eyeball
a sorted list.

## Prior art

- **Google's flaky-test mitigation** (Google Testing Blog): tracks a
  per-test flake rate over a bounded window (they cite 30 runs / a
  30-day window at their scale) and quarantines a test once its flake
  rate crosses a threshold (~10%), removing it from the blocking gate
  without deleting it. **Adopted**: the bounded-window idea — but as a
  **run-count** window, not a calendar-day window. This project's run
  cadence is bursty and irregular (targeted `--ids` reruns cluster
  during active debugging of one question, full-baseline runs are
  sporadic) — a day-based window would give inconsistent resolution
  across questions; a run-count window gives every question a
  comparably-sized sample regardless of when those runs happened to land.
- **Academic flaky-test classification literature** (a 2025 OOPSLA paper
  on flaky-test classification; the "Dictionary of Flaky Tests" /
  ContextQA practitioner guides): the categorical distinction "a case
  that always fails is a bug/regression; a case that alternates is
  flaky," with **consecutive-failure run length** named as the practical
  signal used to tell a real regression from noise. **Adopted directly**
  — this is exactly the `_trailing_fail_streak`/`_count_transitions`
  mechanism below.
- **Wilson score interval** for small-sample binomial proportions: the
  statistically preferred alternative to a raw `passed/total` fraction
  when `total` is small, since a raw fraction overstates confidence at
  low n (e.g. 5/5 "looks like" 100% but a 95% Wilson lower bound on that
  same data is only ~0.57). **Adopted, but as an informational
  annotation, not a classification gate** — see "Why Wilson score isn't
  used as a threshold gate" below.
- **Meta's Probabilistic Flakiness Score**: reruns a test many times on
  the *identical* code version and computes the probability a
  truly-deterministic-pass test would show at least one observed failure
  by chance — the most rigorous available approach, because holding code
  constant is what cleanly isolates "flaky" from "a real regression" in
  the first place. **Not adopted**: this project's eval harness doesn't
  currently do same-commit burst reruns — every report file interleaves
  with real code changes between runs, so there's no "same version,
  rerun N times" data to compute this from. Building that harness
  feature is a legitimately more accurate direction, but it's new
  infrastructure, not a classification-logic change — flagged as a
  `BACKLOG.md` idea for later, out of proportion to this task.
- **CUSUM/SPRT changepoint detection, DeFlaker, iDFlakies**: formal
  statistical changepoint detection and code-coverage-linked flaky-test
  detection, respectively, both built for large CI fleets with
  thousands of runs per test and (for DeFlaker/iDFlakies specifically)
  line-coverage instrumentation tied to code diffs. **Not adopted**: this
  project has at most ~60 historical runs for its most-run question and
  no coverage-to-eval-row linkage; both are real, heavier-weight
  directions to revisit only if the simple streak/transitions heuristic
  turns out to be insufficient in practice.

### Why Wilson score isn't used as a threshold gate

Checked directly (verified by running the formula, not just algebra on
paper) before deciding: gating `classify_history`'s solid branch on a
95% Wilson lower bound instead of the raw fraction would require `n≈22`
even for a *perfect* pass record to clear a 0.85 floor
(`n/(n+z²) ≥ 0.85` → `n ≥ z²·(0.85/0.15) ≈ 21.8` at `z=1.96`) — above the
`window=20` cap itself, so a perfect-record question could never reach
"solid." Worse, this plan's own required scenario ("a single isolated
failure in an otherwise-clean 20-run window stays solid") computes to a
95% Wilson lower bound of **0.764** on 19/20 — below a 0.85 floor, which
would silently invert that requirement. Making both numbers compatible
would mean hand-tuning `solid_floor` and `confidence_z` jointly against
`window` via this same algebra any time either changes — a fragile
coupling not worth introducing for a 47-question suite. **Resolution**:
keep classification on the plain windowed fraction, and surface the
Wilson interval as an additional *display* field per question — visible
context for how much to trust a given rate at a glance, without it
silently gating any classification outcome.

## Decision / Design

Extend `analyze_flakiness.py`'s three existing functions plus `main()`'s
argparse — no new file, no new module.

### `ClassificationThresholds`

```python
@dataclass(frozen=True)
class ClassificationThresholds:
    window: int = 20
    min_appearances: int = 5
    solid_floor: float = 0.80
    regression_streak: int = 5
    flaky_min_transitions: int = 3
    confidence_z: float = 1.96  # display-only Wilson CI, not a classification gate
```

One bundled type instead of five independent scalar params — keeps
`classify_history`/`format_summary` under ruff's `PLR0913` arg-count
limit and matches this project's own stated preference (2026-09-21
decision) for a named-field type over a sprawling parameter list.

Defaults, justified against the real distribution (`n_runs` 1–62 live
today):

- **`window=20`** — caps the heaviest-history questions (several sit at
  55–62 runs today) to a recent slice reflecting the current code era,
  while leaving lighter-history questions (14–24 runs) effectively
  uncapped rather than starved of data.
- **`solid_floor=0.80`** — chosen so a single isolated blip stays solid
  even at the *smallest* window `min_appearances` admits (`n=5`):
  `4/5 = 0.80` exactly, `5/6 ≈ 0.833`. An initial 0.85 default silently
  failed this exact invariant at `n∈{5,6}` — caught in independent plan
  review before implementation (see Addendum).
- **`regression_streak=5`** — well above 1 (a single bad-luck fail must
  never read as "regression"), but small enough that a real break is
  flagged after only a quarter of the window. Reused symmetrically for
  the recovery check below.
- **`flaky_min_transitions=3`** — a single isolated failure produces
  exactly 2 transitions (pass→fail, fail→pass); requiring ≥3 forces at
  least one additional flip, i.e. genuine oscillation, not one blip.
- **`min_appearances=5`** — existing flag, reused unchanged, now gates
  "insufficient-data" against the *windowed* count instead of a hard
  exclusion.

### `classify_history()` — the core algorithm

New pure function plus helpers (`_trailing_fail_streak`,
`_trailing_pass_streak`, `_count_transitions`, `_wilson_interval`), all
pure/deterministic. Final precedence, every history hits exactly one
branch:

1. `trailing_fail_streak >= regression_streak` → **regression** (an
   active break is the most actionable signal, checked first regardless
   of aggregate rate).
2. else `trailing_pass_streak >= regression_streak` → **solid**
   (currently reliable — a strong recent run of passes overrides a worse
   full-window aggregate; see Addendum for why this branch exists).
3. else `pass_rate >= solid_floor` → **solid** (protects "one blip in an
   otherwise-clean window stays solid").
4. else `transitions >= flaky_min_transitions` → **flaky** (real
   oscillation below the solid floor).
5. else `pass_rate < 0.5` → **regression** (mostly-broken, no long
   recent recovery run and no single clean trailing streak either).
6. else → **flaky** (mostly-passing, below floor, not enough oscillation
   or recent-streak evidence to prove either way — the most ambiguous
   fallback, documented as such rather than presented as clean-cut).

Below `min_appearances` (on the windowed count) → **insufficient-data**
before any of the above runs.

Also computes a **display-only** `wilson_interval` (95% two-sided, via
`confidence_z`) on the windowed `passed`/`total` — not used anywhere in
the branching above.

### `summarize()` and `format_summary()`

`summarize()` gains one new field per question, `history: list[bool]`,
populated in chronological order (a breaking change to its return
shape). `format_summary()` is restructured from one flat pass-rate-
sorted list into four labeled sections — Regression, Flaky,
Insufficient data, Solid, most-actionable first — every question that
appears in at least one loaded report row lands in exactly one section
(no silent dropping, unlike today's hard `min_appearances` exclusion).

`main()` also now sorts `args.reports` before calling `load_rows()` —
required once ordering feeds streak/transition logic instead of only
unordered aggregate counts (see Addendum).

## Scope / Out of scope

Stays a pure on-demand CLI report (resolved via a direct question to the
user) — no new persisted snapshot file. `eval/eval_results/*.json` is
already the committed source of truth; a second, separately-maintained
snapshot would need its own staleness discipline this project doesn't
otherwise have.

A question in `eval_questions.jsonl` with zero recorded runs at all was
already invisible to `summarize()` before this change and stays exactly
as invisible after — unchanged behavior, out of scope (would need
cross-referencing `eval_questions.jsonl` itself, a different data source
this script doesn't read).

Meta-style same-commit burst reruns (which would enable a true
probabilistic flakiness score instead of this heuristic) are new
eval-harness infrastructure, not an analysis-script change — tracked in
`BACKLOG.md`, not built here.

## Files and steps

1. `analyze_flakiness.py` — add `ClassificationThresholds`,
   `_trailing_fail_streak`/`_trailing_pass_streak`/`_count_transitions`/
   `_wilson_interval`/`classify_history`; extend `summarize()` with
   `history`; restructure `format_summary()` into 4 sections; extend
   `main()`'s CLI flags and sort `args.reports`.
2. `tests/test_analyze_flakiness.py` — full TDD for every new function
   plus updates to existing `summarize`/`format_summary` tests whose
   contracts changed.
3. `docs/decisions/2026-09-22-eval-question-classification.md`,
   `PROJECT_INDEX.md`, `BACKLOG.md` — per the documentation system.

## Testing and verification

All new logic is pure/deterministic (no network/LLM/filesystem
dependency) — full red-green-refactor TDD, no live/manual counterpart
needed, matching this test file's own existing convention. After
implementation: `pytest tests/test_analyze_flakiness.py -v`, full suite
`pytest -q`, `ruff check .`, `pyright .`, then a real run against
`eval/eval_results/*.json` to sanity-check known cases (a chronically
troubled question lands in Regression/Flaky, a consistently reliable one
lands in Solid). Diff coverage checked against the project's 80%
ordinary-file bar (`analyze_flakiness.py` is not in the 90%
critical-core list).

## Addendum

An independent review of this plan (before implementation) hand-tested
the precedence chain against synthetic histories beyond the ones
originally named as test cases and found two real bugs, both fixed
before implementation started:

1. **A currently-recovered question was misclassified as an active
   regression.** History = 14 fails then 6 clean passes (`window=20`):
   the original 5-branch design fell through to a `pass_rate < 0.5`
   catch-all that called this "regression," despite the 6 most recent
   runs being clean. Fixed by adding the symmetric recovery check
   (`_trailing_pass_streak` against `regression_streak`) that is now
   branch 2 above.
2. **`solid_floor=0.85` was unreachable by this plan's own headline
   scenario at the smallest window `min_appearances` admits** (`4/5 =
   0.80 < 0.85`). Fixed by lowering the default to 0.80.

The review also caught that `main()` never sorted `args.reports` before
this change made ordering correctness-critical (fixed, see above), and
that two tests originally listed as "unchanged" would actually break
from the `format_summary()` signature change (fixed during
implementation). Full findings in the review notes carried into
`docs/decisions/2026-09-22-eval-question-classification.md`.
