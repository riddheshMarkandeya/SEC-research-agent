"""
Measures the citation hard gate's (citations.py's verify_claims() and
submission.py's _finalize_answer()) false-positive/false-negative rate against ground
truth, by reading eval_harness.py report JSON files rather than running
anything live -- the report is the durable, committed artifact, so
re-classifying from it is free and re-runnable any time the
classification rules change, unlike re-running the whole eval or
reading var/trace_logs/traces.jsonl (which has no ground truth).

Definitions (numeric/comparison rows only -- judged rows have no
ground-truth number to re-grade against, so they're excluded):
  - false_positive: the gate refused an answer that would have passed
    the existing grader (grade_numeric()/grade_comparison()) if allowed
    through -- a real answer silently withheld.
  - true_positive: the gate refused an answer that would NOT have
    passed -- correctly caught a bad answer.
  - false_negative_candidate: the gate passed an answer that a human
    grader still marked wrong, and the answer DID carry a citation
    marker (has_citation=True) -- a real grounding miss the gate let
    through. Excludes "passed" and "failed with no citation at all"
    (the model just declined or retrieved nothing -- not the gate's
    fault to have caught).
  - unknown_pre_instrumentation: a report written before 2026-09-10 has
    none of the 4 new gate-evidence fields at all -- excluded from every
    rate, not silently counted as a pass.

Known asymmetry, reported rather than hidden: citations.value_is_citation_
verified() treats "no citation at all" as verified, so a correct-but-
uncited value and a correct-and-cited value both count as "would have
passed" here. false_positive_by_check breaks false positives down by
citations.CitationWarning.check, so each check's share stays visible instead
of collapsing into one rate. Older reports carry the retired prose
checks ("cited_claim_unsupported", "uncited_claim"). A "no_submission"
false positive is different in kind: the model answered in plain text
with the right number but never submitted it, so no citation check
judged that text -- read it as a submission failure, not a misjudgement.

Caveat that matters for reading these numbers: the corrective citation
retry is on for every Gemini run measured here, and a run can take
several -- so a report's numbers reflect the gate's verdict on the
model's last submission, not on its first-pass answer. The earlier
attempts' warnings are only in var/trace_logs/traces.jsonl's
"citation_retry" events (one per attempt, keyed by run_id), which this
script does not read.

Usage:
    python -m sec_agent.devtools.analyze_citation_gate eval/eval_results/20260910T120000Z.json
    python -m sec_agent.devtools.analyze_citation_gate eval/eval_results/*.json
"""

import argparse
import json
from pathlib import Path


def load_rows(paths: list[Path]) -> list[dict]:
    """Concatenates the "results" list from each report JSON file, in
    the order given -- pooling multiple runs (e.g. the baseline 41-
    question suite and the citation-stress question set) into one
    combined measurement."""
    rows = []
    for path in paths:
        with path.open(encoding="utf-8") as f:
            report = json.load(f)
        rows.extend(report["results"])
    return rows


def classify_row(row: dict) -> str:
    """Classifies one eval_harness.py report row -- see this module's
    own docstring for what each label means. Checked via `in row`, not
    `row.get(...)`, so a legacy report's genuinely absent key is
    distinguishable from a post-instrumentation row that has
    `gate_withheld_would_have_passed: null` on purpose (a passing row)."""
    if "gate_withheld_would_have_passed" not in row:
        return "unknown_pre_instrumentation"
    if row["type"] == "judged":
        return "excluded"

    gate_refused = bool(row["citation_warnings"])
    if gate_refused:
        return "false_positive" if row["gate_withheld_would_have_passed"] else "true_positive"

    if not row["passed"] and row["has_citation"]:
        return "false_negative_candidate"
    return "not_gate_attributable"


def summarize(rows: list[dict]) -> dict:
    """Aggregates classify_row() over a batch of rows into counts, rates,
    and the false-positive-by-check breakdown. `false_positive_rate` is
    computed over gate-refused rows only (false_positive / (false_positive
    + true_positive)) -- the question this answers is "when the gate
    fires, how often is it wrong," not "what fraction of all questions
    the gate wrongly refuses," which would conflate the gate's own
    accuracy with how often it fires at all."""
    counts = {
        "false_positive": 0,
        "true_positive": 0,
        "false_negative_candidate": 0,
        "not_gate_attributable": 0,
        "excluded": 0,
        "unknown_pre_instrumentation": 0,
    }
    false_positive_by_check: dict[str, int] = {}
    false_positive_ids: list[str] = []
    false_negative_candidate_ids: list[str] = []

    for row in rows:
        label = classify_row(row)
        counts[label] += 1
        if label == "false_positive":
            false_positive_ids.append(row["id"])
            for check in {d["check"] for d in row["citation_warning_details"]}:
                false_positive_by_check[check] = false_positive_by_check.get(check, 0) + 1
        elif label == "false_negative_candidate":
            false_negative_candidate_ids.append(row["id"])

    gate_refused = counts["false_positive"] + counts["true_positive"]
    false_positive_rate = counts["false_positive"] / gate_refused if gate_refused else None

    return {
        "total_rows": len(rows),
        "excluded_judged": counts["excluded"],
        "unknown_pre_instrumentation": counts["unknown_pre_instrumentation"],
        "gate_refused": gate_refused,
        "false_positive": counts["false_positive"],
        "true_positive": counts["true_positive"],
        "false_positive_rate": false_positive_rate,
        "false_negative_candidate": counts["false_negative_candidate"],
        "not_gate_attributable": counts["not_gate_attributable"],
        "false_positive_by_check": false_positive_by_check,
        "false_positive_ids": false_positive_ids,
        "false_negative_candidate_ids": false_negative_candidate_ids,
    }


def format_summary(summary: dict) -> str:
    rate = (
        "n/a (gate never fired)" if summary["false_positive_rate"] is None else f"{summary['false_positive_rate']:.1%}"
    )
    lines = [
        f"Rows: {summary['total_rows']} total "
        f"({summary['excluded_judged']} judged excluded, "
        f"{summary['unknown_pre_instrumentation']} pre-instrumentation excluded)",
        f"Gate refused: {summary['gate_refused']} "
        f"({summary['false_positive']} false positive, {summary['true_positive']} true positive) "
        f"-- false positive rate: {rate}",
        f"False negative candidates (gate passed, human grader failed, had a citation): "
        f"{summary['false_negative_candidate']}",
        f"Not attributable to the gate either way: {summary['not_gate_attributable']}",
    ]
    if summary["false_positive_by_check"]:
        lines.append(f"False positives by check: {summary['false_positive_by_check']}")
    if summary["false_positive_ids"]:
        lines.append(f"False positive question ids: {summary['false_positive_ids']}")
    if summary["false_negative_candidate_ids"]:
        lines.append(f"False negative candidate question ids: {summary['false_negative_candidate_ids']}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("reports", type=Path, nargs="+", help="eval_harness.py report JSON file(s) to analyze")
    args = parser.parse_args()

    rows = load_rows(args.reports)
    print(format_summary(summarize(rows)))


if __name__ == "__main__":
    main()
