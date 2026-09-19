"""
Ranks eval questions by historical flakiness (how often they've failed
across repeated eval_harness.py runs with no code change in between),
by reading every eval/eval_results/*.json report file rather than
running anything live. Complements analyze_citation_gate.py's own
FP/FN measurement: that answers "is the citation gate itself accurate,"
this answers "which questions are unreliable regardless of cause."

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
    python analyze_flakiness.py eval/eval_results/*.json
    python analyze_flakiness.py eval/eval_results/*.json --min-appearances 10
"""

import argparse
import json
from collections import Counter
from pathlib import Path


def load_rows(paths: list[Path]) -> list[dict]:
    """Concatenates the "results" list from each report JSON file, in
    the order given. Tolerates two on-disk shapes: the current
    dict-wrapper ({"backend": ..., "results": [...]}) and this
    project's older bare-list reports (pre-2026-08-21) -- see this
    module's own docstring."""
    rows = []
    for path in paths:
        with path.open(encoding="utf-8") as f:
            report = json.load(f)
        rows.extend(report if isinstance(report, list) else report["results"])
    return rows


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


def summarize(rows: list[dict]) -> dict:
    """Aggregates historical pass/fail rows by question id, excluding
    infra-error rows from both the numerator and denominator of each
    question's pass rate. Returns {"questions": {id: {"type", "passed",
    "total", "pass_rate"}}, "excluded_by_error_type": {...}} -- the
    exclusion breakdown is a top-level, always-visible field so it
    stays auditable rather than silently hiding rows."""
    questions: dict[str, dict] = {}
    excluded_by_error_type: Counter[str] = Counter()

    for row in rows:
        if is_infra_error(row):
            excluded_by_error_type[_error_type(row)] += 1
            continue
        entry = questions.setdefault(row["id"], {"type": row.get("type"), "passed": 0, "total": 0})
        entry["total"] += 1
        if row.get("passed"):
            entry["passed"] += 1

    for entry in questions.values():
        entry["pass_rate"] = entry["passed"] / entry["total"] if entry["total"] else None

    return {"questions": questions, "excluded_by_error_type": dict(excluded_by_error_type)}


def format_summary(summary: dict, min_appearances: int = 5) -> str:
    """Ranks questions by pass rate ascending (flakiest first),
    excluding any question with fewer than `min_appearances` historical
    (non-infra-error) rows -- not enough data to be meaningful."""
    ranked = sorted(
        ((qid, entry) for qid, entry in summary["questions"].items() if entry["total"] >= min_appearances),
        key=lambda item: item[1]["pass_rate"],
    )

    lines = [f"{'id':<50} {'type':<12} {'pass rate':<16} n_runs"]
    for qid, entry in ranked:
        rate_str = f"{entry['passed']}/{entry['total']} = {entry['pass_rate']:.0%}"
        lines.append(f"{qid:<50} {entry['type']:<12} {rate_str:<16} {entry['total']}")

    excluded = summary["excluded_by_error_type"]
    if excluded:
        lines.append("")
        lines.append(f"Excluded {sum(excluded.values())} infra-error row(s) (not counted above): {excluded}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("reports", type=Path, nargs="+", help="eval_harness.py report JSON file(s) to analyze")
    parser.add_argument(
        "--min-appearances",
        type=int,
        default=5,
        help="exclude a question with fewer than this many non-infra-error historical rows (default: 5)",
    )
    args = parser.parse_args()

    rows = load_rows(args.reports)
    print(format_summary(summarize(rows), args.min_appearances))


if __name__ == "__main__":
    main()
