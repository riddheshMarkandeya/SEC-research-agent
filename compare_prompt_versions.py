"""
Compares eval runs of one prompt version against another, so a pass-rate
change can be attributed to a specific prompt commit.

Reports carry a "provenance" block (eval_harness._collect_provenance())
whose prompts.agent fingerprint identifies the agent-prompt version. This
script implements the decision rule used for every prompt change:

1. Screen (fingerprint mode, the default): the two most recent
   fingerprints are the base (B) and candidate (C). Any REGRESSED question
   or a counting REGRESSED-TOTAL exits 1.
2. Replicate and 3. attribute (explicit mode): --base-files and
   --candidate-files compare exactly the runs named. Each question's
   "within 1 pass" column is the replicate step's test. Always use
   explicit mode here: a revert restores B's fingerprint, so fingerprint
   mode would pool the reverted runs with the original B.

Rows from a report's first infra error onward are dropped (a quota error
or crash, not a graded answer). Reports with no known commit, uncommitted
changes or an unverified model-input snapshot are excluded unless
--include-dirty.

Usage:
    python compare_prompt_versions.py
    python compare_prompt_versions.py --since 20260925T000000Z
    python compare_prompt_versions.py --base-files a.json b.json --candidate-files c.json
"""

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

from analyze_flakiness import is_infra_error, load_reports

RESULTS_DIR = Path(__file__).resolve().parent / "eval" / "eval_results"

# A question whose pass rate drops by at least this much is REGRESSED;
# any smaller drop is only "watch".
REGRESSED_DROP = 0.5
# A base pass rate at or below this can barely drop further, so a
# question sitting there is marked "floor": it can't show a regression.
FLOOR_RATE = 1 / 3
# REGRESSED-TOTAL: expected passes lost across shared questions reach
# this percentage of the candidate's question-runs (6 of a 13x3 panel).
TOTAL_DROP_PERCENT = 14
# Below this many candidate question-runs, 14% of N rounded up is so small
# that a single lost pass trips the total; it is reported but can't fail.
MIN_RUNS_FOR_TOTAL = 20
# "Within 1 pass": the candidate lost at most one pass against what the
# base's rate predicts for the candidate's run count.
WITHIN_PASSES = 1
_EPSILON = 1e-9


@dataclass
class Report:
    name: str
    provenance: dict | None
    backend: str | None
    answer_model: str | None
    judge_model: str | None
    rows: list[dict]
    dropped: int


@dataclass
class Tally:
    passes: int = 0
    runs: int = 0
    withheld: int = 0

    @property
    def rate(self) -> float:
        return self.passes / self.runs


@dataclass
class QuestionRow:
    qid: str
    base: Tally
    candidate: Tally
    flags: list[str]
    scaled_delta: float
    within_one_pass: bool


@dataclass
class Total:
    expected_loss: float
    runs: int
    threshold: int
    regressed: bool
    counts: bool


@dataclass
class Comparison:
    rows: list[QuestionRow]
    base_only: list[str]
    candidate_only: list[str]
    total: Total
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Loading and grouping
# ---------------------------------------------------------------------------
def truncate_at_infra_error(rows: list[dict]) -> tuple[list[dict], int]:
    """Rows before the first infra error, and how many were dropped. A
    quota error usually repeats for every later question, so nothing
    after the first one is a real result."""
    for i, row in enumerate(rows):
        if is_infra_error(row):
            return rows[:i], len(rows) - i
    return rows, 0


def load(paths: list[Path]) -> list[Report]:
    """Reports sorted by file name, which is a UTC timestamp for every
    report eval_harness writes, so the order is chronological."""
    reports = []
    for path, data in zip(paths, load_reports(paths), strict=True):
        rows, dropped = truncate_at_infra_error(data["results"])
        reports.append(
            Report(
                name=path.stem,
                provenance=data.get("provenance"),
                backend=data.get("backend"),
                answer_model=data.get("answer_model"),
                judge_model=data.get("judge_model"),
                rows=rows,
                dropped=dropped,
            )
        )
    return sorted(reports, key=lambda r: r.name)


def agent_fingerprint(report: Report) -> str | None:
    prompts = (report.provenance or {}).get("prompts")
    return prompts.get("agent") if isinstance(prompts, dict) else None


def is_excluded(report: Report, include_dirty: bool) -> bool:
    """A stamped report with no known commit, uncommitted changes, or an
    unverified model-input snapshot doesn't reliably describe a commit.
    Unstamped (older) reports have nothing to check."""
    if include_dirty or report.provenance is None:
        return False
    provenance = report.provenance
    sha = provenance.get("git_sha")
    return (
        not sha
        or sha == "unknown"
        or provenance.get("git_dirty") is not False
        or provenance.get("snapshot_verified") is not True
    )


def select(
    reports: list[Report], include_dirty: bool, since: str | None = None
) -> tuple[list[Report], list[Report]]:
    """(kept, excluded) among the reports named at or after `since` (a
    UTC timestamp, like report names)."""
    kept: list[Report] = []
    excluded: list[Report] = []
    for report in reports:
        if not since or report.name >= since:
            (excluded if is_excluded(report, include_dirty) else kept).append(report)
    return kept, excluded


def group_by_fingerprint(reports: list[Report]) -> dict[str, list[Report]]:
    """Stamped reports grouped by agent fingerprint; unstamped ones are
    skipped."""
    groups: dict[str, list[Report]] = {}
    for report in reports:
        fingerprint = agent_fingerprint(report)
        if fingerprint is not None:
            groups.setdefault(fingerprint, []).append(report)
    return groups


def default_pair(
    groups: dict[str, list[Report]], base: str | None = None, candidate: str | None = None
) -> tuple[str | None, str | None]:
    """(base, candidate), filling whichever wasn't given so the
    comparison runs forward in time: the candidate defaults to the most
    recent fingerprint after the base, the base to the latest fingerprint
    before the candidate. Either is None when no such fingerprint exists."""
    by_recency = sorted(groups, key=lambda fp: groups[fp][-1].name)
    if candidate is None:
        newer = by_recency[by_recency.index(base) + 1 :] if base in by_recency else by_recency
        candidate = newer[-1] if newer else None
    if base is None and candidate in by_recency:
        older = by_recency[: by_recency.index(candidate)]
        base = older[-1] if older else None
    return base, candidate


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------
def tally(reports: list[Report]) -> dict[str, Tally]:
    tallies: dict[str, Tally] = {}
    for report in reports:
        for row in report.rows:
            t = tallies.setdefault(row["id"], Tally())
            t.runs += 1
            t.passes += bool(row.get("passed"))
            t.withheld += bool(row.get("withheld_answer"))
    return tallies


def _flags(base: Tally, candidate: Tally) -> list[str]:
    change = candidate.rate - base.rate
    flags = []
    if change <= -REGRESSED_DROP + _EPSILON:
        flags.append("REGRESSED")
    elif change < -_EPSILON:
        flags.append("watch")
    elif change > _EPSILON:
        flags.append("improved")
    if base.rate <= FLOOR_RATE + _EPSILON:
        flags.append("floor")
    return flags


def _question_row(qid: str, base: Tally, candidate: Tally) -> QuestionRow:
    scaled_delta = candidate.passes - base.rate * candidate.runs
    return QuestionRow(
        qid=qid,
        base=base,
        candidate=candidate,
        flags=_flags(base, candidate),
        scaled_delta=scaled_delta,
        within_one_pass=scaled_delta >= -WITHIN_PASSES - _EPSILON,
    )


def total_threshold(runs: int) -> int:
    """ceil(14% of runs), in integers: 0.14 * 50 is 7.000000000000001 in
    floating point, which a float ceil turns into 8."""
    return -(-TOTAL_DROP_PERCENT * runs // 100)


def _total(rows: list[QuestionRow]) -> Total:
    runs = sum(r.candidate.runs for r in rows)
    expected_loss = sum((r.base.rate - r.candidate.rate) * r.candidate.runs for r in rows)
    threshold = total_threshold(runs)
    return Total(
        expected_loss=expected_loss,
        runs=runs,
        threshold=threshold,
        regressed=runs > 0 and expected_loss >= threshold - _EPSILON,
        counts=runs >= MIN_RUNS_FOR_TOTAL,
    )


def _distinct(reports: list[Report], key) -> set[str]:
    return {repr(key(r)) for r in reports}


# Each report property whose variation means the runs aren't comparable,
# with how to read it from a report.
_CONSISTENCY_CHECKS = {
    "git SHA": lambda r: (r.provenance or {}).get("git_sha"),
    "judge fingerprint": lambda r: ((r.provenance or {}).get("prompts") or {}).get("judge"),
    "backend": lambda r: r.backend,
    "answer_model": lambda r: r.answer_model,
    "judge_model": lambda r: r.judge_model,
    "config": lambda r: (r.provenance or {}).get("config"),
}


def consistency_warnings(base: list[Report], candidate: list[Report]) -> list[str]:
    """Differences that would make a pass-rate change mean something
    other than the prompt change: within either group, or (except the git
    SHA, which is expected to differ) between them."""
    warnings = []
    for label, key in _CONSISTENCY_CHECKS.items():
        for side, reports in (("base", base), ("candidate", candidate)):
            if len(_distinct(reports, key)) > 1:
                warnings.append(f"{side} group spans several values of {label}: {sorted(_distinct(reports, key))}")
        if label != "git SHA" and _distinct(base, key) != _distinct(candidate, key):
            warnings.append(f"{label} differs between base and candidate")
    return warnings


def compare(base: list[Report], candidate: list[Report]) -> Comparison:
    base_tallies, cand_tallies = tally(base), tally(candidate)
    shared = sorted(base_tallies.keys() & cand_tallies.keys())
    rows = [_question_row(q, base_tallies[q], cand_tallies[q]) for q in shared]
    return Comparison(
        rows=rows,
        base_only=sorted(base_tallies.keys() - cand_tallies.keys()),
        candidate_only=sorted(cand_tallies.keys() - base_tallies.keys()),
        total=_total(rows),
        warnings=consistency_warnings(base, candidate),
    )


def exit_code(comparison: Comparison) -> int:
    regressed = any("REGRESSED" in r.flags for r in comparison.rows)
    return 1 if regressed or (comparison.total.regressed and comparison.total.counts) else 0


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
def _group_label(reports: list[Report]) -> str:
    fingerprints = sorted({agent_fingerprint(r) or "unstamped" for r in reports})
    return ",".join(fingerprints)


def describe_group(side: str, reports: list[Report]) -> str:
    shas = sorted({(r.provenance or {}).get("git_sha") or "?" for r in reports})
    models = sorted({r.answer_model or "?" for r in reports})
    dropped = sum(r.dropped for r in reports)
    line = (
        f"{side} {_group_label(reports)}: {len(reports)} report(s), "
        f"SHA {','.join(shas)}, answer_model {','.join(models)}"
    )
    return line + (f", {dropped} row(s) dropped at infra errors" if dropped else "")


def _fraction(t: Tally) -> str:
    return f"{t.passes}/{t.runs}"


def format_comparison(comparison: Comparison, base: list[Report], candidate: list[Report]) -> str:
    lines = [describe_group("base", base), describe_group("candidate", candidate), ""]
    lines += [f"WARNING: {w}" for w in comparison.warnings]
    lines.append(f"{'question':45} {'base':>6} {'cand':>6} {'withheld':>9} {'delta':>6} {'within1':>7}  flags")
    for r in comparison.rows:
        withheld = f"{r.base.withheld}/{r.candidate.withheld}"
        within = "yes" if r.within_one_pass else "NO"
        lines.append(
            f"{r.qid:45} {_fraction(r.base):>6} {_fraction(r.candidate):>6} {withheld:>9} "
            f"{r.scaled_delta:>+6.1f} {within:>7}  {' '.join(r.flags)}"
        )
    for label, qids in (("only in base", comparison.base_only), ("only in candidate", comparison.candidate_only)):
        if qids:
            lines.append(f"{label} (left out of the total): {', '.join(qids)}")
    total = comparison.total
    verdict = "REGRESSED-TOTAL" if total.regressed else "ok"
    note = "" if total.counts else f" (reported only: fewer than {MIN_RUNS_FOR_TOTAL} candidate runs)"
    lines.append(
        f"panel total: expected passes lost {total.expected_loss:.1f} over {total.runs} run(s), "
        f"threshold {total.threshold}: {verdict}{note}"
    )
    return "\n".join(lines)


def format_single_group(reports: list[Report]) -> str:
    """The table for one fingerprint alone, e.g. a new baseline."""
    lines = [describe_group("only", reports), "", f"{'question':45} {'passed':>7} {'withheld':>9}"]
    tallies = tally(reports)
    for qid in sorted(tallies):
        t = tallies[qid]
        lines.append(f"{qid:45} {_fraction(t):>7} {t.withheld:>9}")
    passes, runs = sum(t.passes for t in tallies.values()), sum(t.runs for t in tallies.values())
    lines.append(f"total: {passes}/{runs}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("reports", nargs="*", type=Path, help="report files (default: every eval_results report)")
    parser.add_argument("--base", help="base agent fingerprint (default: the latest before the candidate)")
    parser.add_argument("--candidate", help="candidate agent fingerprint (default: the most recent after the base)")
    parser.add_argument("--base-files", nargs="+", type=Path, help="explicit mode: the base runs")
    parser.add_argument("--candidate-files", nargs="+", type=Path, help="explicit mode: the candidate runs")
    parser.add_argument("--since", help="ignore reports named before this UTC timestamp, e.g. 20260925T000000Z")
    parser.add_argument("--include-dirty", action="store_true", help="keep reports from a dirty or unverified tree")
    return parser.parse_args(argv)


def _select_and_report(
    label: str, reports: list[Report], include_dirty: bool, since: str | None = None
) -> list[Report]:
    """select()'s kept reports, printing any exclusions so no report is
    dropped quietly."""
    kept, excluded = select(reports, include_dirty, since)
    if excluded:
        names = ", ".join(r.name for r in excluded)
        print(f"{label}: {len(excluded)} dirty or unverified report(s) excluded (see --include-dirty): {names}")
    return kept


def _explicit(args: argparse.Namespace) -> int:
    base = _select_and_report("base", load(args.base_files), args.include_dirty)
    candidate = _select_and_report("candidate", load(args.candidate_files), args.include_dirty)
    if not (base and candidate):
        print("Nothing to compare: every file on one side was excluded.")
        return 2
    comparison = compare(base, candidate)
    print(format_comparison(comparison, base, candidate))
    return exit_code(comparison)


def _by_fingerprint(args: argparse.Namespace) -> int:
    paths = args.reports or sorted(RESULTS_DIR.glob("*.json"))
    groups = group_by_fingerprint(_select_and_report("fingerprint mode", load(paths), args.include_dirty, args.since))
    if not groups:
        print("No stamped, clean reports to compare (see --include-dirty and --since).")
        return 0
    unknown = [fp for fp in (args.base, args.candidate) if fp is not None and fp not in groups]
    if unknown:
        print(f"Unknown fingerprint(s): {', '.join(unknown)}. Known: {', '.join(sorted(groups))}")
        return 2
    if len(groups) == 1 and not (args.base or args.candidate):
        print(format_single_group(next(iter(groups.values()))))
        return 0
    base_fp, candidate_fp = default_pair(groups, args.base, args.candidate)
    if base_fp is None or candidate_fp is None or base_fp == candidate_fp:
        print(
            "A comparison needs two different fingerprints "
            f"(base: {base_fp or 'none older'}, candidate: {candidate_fp or 'none newer'})."
        )
        return 2
    comparison = compare(groups[base_fp], groups[candidate_fp])
    print(format_comparison(comparison, groups[base_fp], groups[candidate_fp]))
    return exit_code(comparison)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.base_files or args.candidate_files:
        if not (args.base_files and args.candidate_files):
            print("Explicit mode needs both --base-files and --candidate-files.")
            return 2
        return _explicit(args)
    return _by_fingerprint(args)


if __name__ == "__main__":
    sys.exit(main())
