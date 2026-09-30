"""
Classifies eval questions as solid/flaky/regression/insufficient-data
(how reliably they've passed across repeated eval_harness.py runs with
no code change in between), by reading every eval/eval_results/*.json
report file rather than running anything live. Complements
analyze_citation_gate.py's own FP/FN measurement: that answers "is the
citation gate itself accurate," this answers "which questions are
unreliable regardless of cause."

Classification (classify_history()) uses only a capped trailing window
of each question's recent runs, not unbounded all-time history, so a
question fixed weeks ago isn't dragged down by its own past forever.

Report format has evolved: 33 of this project's own historical files
(2026-08-14 through 2026-08-19) are a bare top-level JSON list; the
dict-wrapper format ({"backend": ..., "results": [...]}) only starts
2026-08-21 onward. `load_rows()` tolerates both -- unlike
analyze_citation_gate.py's own `load_rows()`, which assumes the
dict-wrapper shape unconditionally (fine for that script's typical
single-recent-report usage, but this script's whole point is to run
against the full historical file set).

Excludes infra-error rows from every rate: eval_harness.py's
`run_eval()` has a deliberately broad `except Exception` (network
error, Gemini free-tier quota exhaustion, an unexpected bug) that
records `answer: None` and a `detail` string describing the exception
-- a real per-question verdict was never reached, so counting it as a
"failure" measures API quota, not the agent. `answer is None` is the
reliable marker for this: every other code path always sets a real
string, even a refusal message.

Usage:
    python -m sec_agent.tools.analyze_flakiness eval/eval_results/*.json
    python -m sec_agent.tools.analyze_flakiness eval/eval_results/*.json --min-appearances 10
"""

import argparse
import json
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


def load_reports(paths: list[Path]) -> list[dict]:
    """Each report JSON file as a dict, in the order given. Tolerates two
    on-disk shapes: the current dict-wrapper ({"backend": ...,
    "results": [...]}) and this project's older bare-list reports
    (pre-2026-08-21), which become {"results": [...]} -- see this
    module's own docstring."""
    reports = []
    for path in paths:
        with path.open(encoding="utf-8") as f:
            report = json.load(f)
        reports.append({"results": report} if isinstance(report, list) else report)
    return reports


def load_rows(paths: list[Path]) -> list[dict]:
    """Concatenates the "results" list from each report, in the order
    given."""
    return [row for report in load_reports(paths) for row in report["results"]]


def is_infra_error(row: dict) -> bool:
    """True for a row eval_harness.py's run_eval() recorded from its
    broad except-Exception handler (network error, API quota
    exhaustion, an unexpected bug) rather than a real graded answer.
    `answer is None` is the reliable marker: every other code path
    always sets a real string, even a refusal message."""
    return row.get("answer") is None


def _error_type(row: dict) -> str:
    """The exception class name from an infra-error row's `detail`
    (eval_harness.py's run_eval() records f"{type(e).__name__}: {e}"),
    or "unknown" if `detail` doesn't have the expected shape."""
    detail = row.get("detail") or ""
    return detail.split(":", 1)[0] if ":" in detail else "unknown"


# ---------------------------------------------------------------------------
# Solid/flaky/regression classification
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ClassificationThresholds:
    """Bundled instead of five independent scalar params -- keeps
    classify_history()/format_summary() under ruff's PLR0913 arg-count
    limit. `solid_floor` is 0.80, not a rounder 0.85, so a single
    isolated failure still clears it at the smallest window
    `min_appearances` admits (n=5: 4/5=0.80 exactly)."""

    window: int = 20
    min_appearances: int = 5
    solid_floor: float = 0.80
    regression_streak: int = 5
    flaky_min_transitions: int = 3
    # Below this windowed pass rate, with no clean trailing streak and not
    # enough transitions to prove oscillation, classify_history() still
    # calls it "regression" rather than the more ambiguous "flaky" default.
    mostly_failing_ceiling: float = 0.5
    confidence_z: float = 1.96  # display-only Wilson CI -- not a classification gate, see below

    def __post_init__(self) -> None:
        # Each of these has the same "a >=/< comparison against 0 becomes
        # trivially true/false" footgun as window (history[-0:] silently
        # means "the whole list" -- Python slicing: -0 == 0): a
        # regression_streak/flaky_min_transitions/min_appearances of 0
        # would make classify_history()'s branching degenerate (e.g.
        # regression_streak=0 classifies a perfect all-pass history as
        # "regression", since fail_streak>=0 is always true). Reject all
        # four instead of silently misclassifying on a nonsensical config.
        for name in ("window", "min_appearances", "regression_streak", "flaky_min_transitions"):
            value = getattr(self, name)
            if value < 1:
                raise ValueError(f"{name} must be >= 1, got {value}")
        if not 0.0 <= self.solid_floor <= 1.0:
            raise ValueError(f"solid_floor must be within [0, 1], got {self.solid_floor}")
        if not 0.0 <= self.mostly_failing_ceiling <= 1.0:
            raise ValueError(f"mostly_failing_ceiling must be within [0, 1], got {self.mostly_failing_ceiling}")
        if self.mostly_failing_ceiling >= self.solid_floor:
            # classify_history()'s branch order only reaches the
            # mostly_failing_ceiling check once pass_rate < solid_floor is
            # already established -- if the ceiling isn't strictly below
            # the floor, every case that check sees is automatically below
            # it too, silently making the final "flaky" catch-all branch
            # unreachable (everything ambiguous becomes "regression").
            raise ValueError(
                f"mostly_failing_ceiling ({self.mostly_failing_ceiling}) must be < "
                f"solid_floor ({self.solid_floor})"
            )
        if self.confidence_z <= 0:
            # _wilson_interval's margin flips sign for a negative z,
            # returning an inverted (lower > upper) interval; _confidence_label
            # would also render a nonsensical negative percentage.
            raise ValueError(f"confidence_z must be > 0, got {self.confidence_z}")


def _trailing_streak(history: list[bool], want: bool) -> int:
    """Consecutive occurrences of `want` counting back from the most
    recent run; 0 if the most recent run doesn't match `want`."""
    streak = 0
    for passed in reversed(history):
        if passed is not want:
            break
        streak += 1
    return streak


def _trailing_fail_streak(history: list[bool]) -> int:
    """Consecutive failures counting back from the most recent run; 0 if
    the most recent run passed."""
    return _trailing_streak(history, want=False)


def _trailing_pass_streak(history: list[bool]) -> int:
    """Consecutive passes counting back from the most recent run -- the
    two can never both be nonzero for the same history (the last run is
    either a pass or a fail), so classify_history() can check both
    unambiguously."""
    return _trailing_streak(history, want=True)


def _count_transitions(history: list[bool]) -> int:
    """Adjacent-pair pass<->fail flips across the sequence -- the
    oscillation signal distinguishing alternating flakiness from a
    single blip (which produces exactly 2) or a clean streak (0)."""
    return sum(1 for a, b in zip(history, history[1:]) if a != b)


def _wilson_interval(passed: int, total: int, z: float) -> tuple[float, float]:
    """Two-sided Wilson score interval for a binomial proportion --
    the standard closed-form correction for small-n pass-rate estimates,
    where a raw fraction overstates confidence (5/5 "looks like" 100%
    but its 95% Wilson lower bound is only ~0.57). Display context only
    -- deliberately NOT used to gate classify_history()'s branching (see
    that function's docstring for why coupling it to solid_floor would
    be self-defeating)."""
    if total == 0:
        return (0.0, 0.0)
    p = passed / total
    z2 = z * z
    denom = 1 + z2 / total
    center = p + z2 / (2 * total)
    margin = z * math.sqrt((p * (1 - p) / total) + z2 / (4 * total * total))
    return ((center - margin) / denom, (center + margin) / denom)


def classify_history(history: list[bool], thresholds: ClassificationThresholds) -> dict:
    """Classifies one question's ordered (chronological) pass/fail
    history into solid/flaky/regression/insufficient-data, using only
    the trailing `thresholds.window` entries -- not all-time history --
    so a question's classification reflects its current code era, not
    weeks of pre-fix runs baked in forever.

    "regression" here means "currently in a persistent failing streak
    observed within the window" -- it is not tied to any code change.
    Reports from 2026-09-24 on carry a "provenance" block (git SHA and
    prompt fingerprint); compare_prompt_versions.py uses it to compare
    one prompt version against another.
    "solid" is reached via either of two independent paths: a sustained
    high windowed pass rate, or a strong-enough recent run of
    consecutive passes overriding a worse-looking full-window aggregate
    (the same recency-priority logic already used for regression,
    applied symmetrically -- without it, a question that failed for a
    while and was then fixed reads as "regression" forever, exactly the
    unbounded-history problem this whole feature exists to fix). Both
    paths report identically as "solid" since a caller only needs to
    know it's currently reliable, not which path got it there.

    "flaky" is not purely "alternates" despite that being its clearest
    case (>=flaky_min_transitions pass<->fail flips): a below-solid-floor
    history with too few transitions to prove real oscillation AND no
    active fail streak AND a pass rate >=0.5 also falls here, as the
    catch-all for "not clearly a regression, not clearly solid, not
    clearly oscillating either" -- e.g. one contiguous block of failures
    that never crossed regression_streak. This is a deliberately
    low-alarm default for a genuinely ambiguous case, not a claim that
    every "flaky" result is alternating."""
    windowed = history[-thresholds.window :]
    total = len(windowed)
    passed = sum(windowed)
    # 0.0, not None, for an empty window -- total=0 always routes to
    # insufficient-data below (min_appearances is always >=1 in practice),
    # so this value is never actually compared; keeping it a plain float
    # avoids an Optional type purely for a branch that can't be reached.
    pass_rate = (passed / total) if total else 0.0
    fail_streak = _trailing_fail_streak(windowed)
    pass_streak = _trailing_pass_streak(windowed)
    transitions = _count_transitions(windowed)
    wilson_interval = _wilson_interval(passed, total, thresholds.confidence_z)

    if total < thresholds.min_appearances:
        classification = "insufficient-data"
    elif fail_streak >= thresholds.regression_streak:
        classification = "regression"
    # Two independent paths to "solid": a strong recent run of consecutive
    # passes, or a sustained high windowed pass rate (see docstring above).
    elif pass_streak >= thresholds.regression_streak or pass_rate >= thresholds.solid_floor:
        classification = "solid"
    elif transitions >= thresholds.flaky_min_transitions:
        classification = "flaky"
    elif pass_rate < thresholds.mostly_failing_ceiling:
        classification = "regression"
    else:
        classification = "flaky"

    return {
        "classification": classification,
        "windowed_total": total,
        "windowed_passed": passed,
        "windowed_pass_rate": pass_rate,
        "transitions": transitions,
        "trailing_fail_streak": fail_streak,
        "trailing_pass_streak": pass_streak,
        "wilson_interval": wilson_interval,
        "confidence_z": thresholds.confidence_z,
    }


def summarize(rows: list[dict]) -> dict:
    """Aggregates historical pass/fail rows by question id, excluding
    infra-error rows from both the numerator and denominator of each
    question's pass rate. Returns {"questions": {id: {"type", "passed",
    "total", "pass_rate", "history"}}, "excluded_by_error_type": {...}}
    -- the exclusion breakdown is a top-level, always-visible field so it
    stays auditable rather than silently hiding rows.

    `history` is the ordered (chronological) list of bool pass/fail
    outcomes, appended in the order `rows` arrives -- required for
    classify_history()'s windowing/streak/transition logic, which needs
    true run order, not just aggregate counts. Correctness depends on
    the caller passing `rows` in chronological order; main() enforces
    this by sorting report paths before calling load_rows()."""
    questions: dict[str, dict] = {}
    excluded_by_error_type: Counter[str] = Counter()

    for row in rows:
        if is_infra_error(row):
            excluded_by_error_type[_error_type(row)] += 1
            continue
        entry = questions.setdefault(row["id"], {"type": row.get("type"), "passed": 0, "total": 0, "history": []})
        entry["total"] += 1
        passed = bool(row.get("passed"))
        if passed:
            entry["passed"] += 1
        entry["history"].append(passed)

    for entry in questions.values():
        entry["pass_rate"] = entry["passed"] / entry["total"] if entry["total"] else None

    return {"questions": questions, "excluded_by_error_type": dict(excluded_by_error_type)}


_SECTION_ORDER = ("regression", "flaky", "insufficient-data", "solid")
_SECTION_TITLES = {
    "regression": "Regression",
    "flaky": "Flaky",
    "insufficient-data": "Insufficient data",
    "solid": "Solid",
}


def _confidence_label(z: float) -> str:
    """The two-sided confidence level for critical value `z` under a
    standard normal is erf(z/sqrt(2)) -- computed directly rather than a
    lookup table of well-known z-scores, so any confidence_z (reachable
    via direct API use even with no dedicated CLI flag) labels correctly,
    not just the four textbook values."""
    return f"{math.erf(z / math.sqrt(2)):.0%} CI"


def _format_row(qid: str, entry: dict, result: dict) -> str:
    """One line per question, shared across all four sections -- avoids
    per-section column branching."""
    total, passed, rate = result["windowed_total"], result["windowed_passed"], result["windowed_pass_rate"]
    rate_str = f"{passed}/{total} = {rate:.0%}" if total else "no data"
    lower, upper = result["wilson_interval"]
    ci_str = f"[{lower:.0%}-{upper:.0%}]" if total else "--"
    ci_label = _confidence_label(result["confidence_z"])
    return (
        f"{qid:<50} {entry['type']:<12} {rate_str:<16} {ci_label} {ci_str:<14} "
        f"transitions={result['transitions']:<3} fail_streak={result['trailing_fail_streak']:<3} "
        f"pass_streak={result['trailing_pass_streak']:<3} all_time_n={entry['total']}"
    )


def _sorted_section_rows(classification: str, rows: list[tuple[str, dict, dict]]) -> list[tuple[str, dict, dict]]:
    """Regression sorted by longest active break first (most actionable);
    the other three sections by windowed pass rate ascending, ties
    broken by id for stable output."""
    if classification == "regression":
        return sorted(rows, key=lambda r: r[2]["trailing_fail_streak"], reverse=True)
    return sorted(rows, key=lambda r: (r[2]["windowed_pass_rate"], r[0]))


def format_summary(summary: dict, thresholds: ClassificationThresholds = ClassificationThresholds()) -> str:
    """Groups every question that appears in at least one loaded report
    row into exactly one of four sections -- Regression, Flaky,
    Insufficient data, Solid, most-actionable first -- via
    classify_history(). Unlike the old flat pass-rate ranking, nothing
    is silently excluded: a question with too little history to classify
    confidently gets its own section instead of being hard-dropped."""
    sections: dict[str, list[tuple[str, dict, dict]]] = {name: [] for name in _SECTION_ORDER}
    for qid, entry in summary["questions"].items():
        result = classify_history(entry["history"], thresholds)
        sections[result["classification"]].append((qid, entry, result))

    lines = []
    for name in _SECTION_ORDER:
        rows = sections[name]
        if not rows:
            continue
        lines.append(f"=== {_SECTION_TITLES[name]} ({len(rows)}) ===")
        for qid, entry, result in _sorted_section_rows(name, rows):
            lines.append(_format_row(qid, entry, result))
        lines.append("")

    excluded = summary["excluded_by_error_type"]
    if excluded:
        lines.append(f"Excluded {sum(excluded.values())} infra-error row(s) (not counted above): {excluded}")
        lines.append("")

    lines.append(
        "Note: 'regression' means an active failing streak observed in eval_results/ history, "
        "not a comparison between versions -- use compare_prompt_versions.py for that."
    )

    return "\n".join(lines)


def main():
    defaults = ClassificationThresholds()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("reports", type=Path, nargs="+", help="eval_harness.py report JSON file(s) to analyze")
    parser.add_argument(
        "--window",
        type=int,
        default=defaults.window,
        help=f"classify using only the most recent N runs per question (default: {defaults.window})",
    )
    parser.add_argument(
        "--min-appearances",
        type=int,
        default=defaults.min_appearances,
        help=f"below this many windowed runs, classify as insufficient-data (default: {defaults.min_appearances})",
    )
    parser.add_argument(
        "--solid-floor",
        type=float,
        default=defaults.solid_floor,
        help=f"windowed pass rate at/above this is solid (default: {defaults.solid_floor})",
    )
    parser.add_argument(
        "--regression-streak",
        type=int,
        default=defaults.regression_streak,
        help=(
            "this many consecutive trailing fails is a regression; this many consecutive "
            f"trailing passes overrides a bad aggregate rate back to solid (default: {defaults.regression_streak})"
        ),
    )
    parser.add_argument(
        "--flaky-min-transitions",
        type=int,
        default=defaults.flaky_min_transitions,
        help=f"this many pass<->fail flips below the solid floor is flaky (default: {defaults.flaky_min_transitions})",
    )
    parser.add_argument(
        "--mostly-failing-ceiling",
        type=float,
        default=defaults.mostly_failing_ceiling,
        help=(
            "below this windowed pass rate, with no clean streak or enough transitions to prove "
            f"oscillation, still classify as regression rather than flaky (default: {defaults.mostly_failing_ceiling})"
        ),
    )
    args = parser.parse_args()

    thresholds = ClassificationThresholds(
        window=args.window,
        min_appearances=args.min_appearances,
        solid_floor=args.solid_floor,
        regression_streak=args.regression_streak,
        flaky_min_transitions=args.flaky_min_transitions,
        mostly_failing_ceiling=args.mostly_failing_ceiling,
    )
    # Report filenames are UTC timestamps (YYYYMMDDTHHMMSSZ.json), so
    # sorting by path is sorting chronologically -- required now that
    # classify_history() depends on true run order, not just aggregate
    # counts (a shell glob happens to already expand this way, but that
    # was never guaranteed for every caller until this sort made it so).
    rows = load_rows(sorted(args.reports))
    print(format_summary(summarize(rows), thresholds))


if __name__ == "__main__":
    main()
