"""
Live verification of the tool-turn-waste fix (2026-09-14) -- run BEFORE
the prompt changes land, to reproduce the waste, and again AFTER, to
confirm it's gone. See docs/plans/2026-09-14-tool-turn-waste.md.

Exactly the CLAUDE.md live-code carve-out: whether a real model, given
the real system prompt and real tool schemas, wastes turns re-deriving
a value it already has (or picks the wrong tool for a ranking) can only
be answered by an actual API call, not a mock -- these are properties of
the model's behavior under this prompt, not of any function's logic.

Drives agent.run_agent() directly (the real entry point, not a stub of
the loop) for three questions, one per mechanism this fix targets:

  1. pltr-revenue-2025 (Mechanism 1): does the model call `calculate`
     to convert an already-cited raw value into billions? It shouldn't
     need to -- normalize() already treats the two as the same
     quantity, and the divisor is a literal constant with no citation
     to ground it against.
  2. aapl-3yr-avg-operating-margin-fy2023-fy2025 (Mechanism 2): does the
     model re-fetch the three per-year margins after get_financial_fact
     already returned the 3-year average directly?
  3. five-company-operating-margin-ranking-fy2025 (Mechanism 3): does
     the model call compare_financial_metric (the one-call path that
     actually returns CRM), or five individual get_financial_fact calls
     (which cannot retrieve CRM's FY2026 margin at all)?

Tool-call sequence is read back from trace_logs/traces.jsonl by run_id
(traced_span always appends there synchronously, regardless of whether
Langfuse is configured -- see tracing.py) rather than parsed from
verbose stdout, so the check is exact rather than string-matched.

Informational, not a hard assert-and-exit-1 gate (same spirit as
verify_submit_answer.py) -- this script's whole purpose is to observe
and report which of several behaviors the model exhibited, before and
after a prompt change, not to fail loudly over live model
non-determinism on a single run.

Usage (from the repo root):
    python tests/manual/verify_tool_turn_waste.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from config import TRACE_LOG_PATH
from agent import run_agent


def _tool_calls_for_run(run_id: str) -> list[tuple[str, dict]]:
    """Reads back every tool-span (name, input) logged under `run_id`,
    in order, from TRACE_LOG_PATH. The root run_agent span always writes
    last (traced_span's __exit__ fires innermost-first), so scanning the
    whole file for a run_id match after the call returns is safe -- no
    race with a still-open span."""
    calls = []
    path = Path(TRACE_LOG_PATH)
    if not path.exists():
        return calls
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            if entry.get("run_id") == run_id and entry.get("as_type") == "tool":
                calls.append((entry.get("name"), entry.get("input") or {}))
    return calls


def _run_and_capture(question: str) -> tuple[list[tuple[str, dict]], str]:
    """Runs the question through the real agent loop and returns
    (tool_calls, final_answer_text). Finds the run_id by recording the
    trace log's byte length before the call and scanning only what was
    appended after -- simpler and just as reliable as monkeypatching
    uuid4, since run_agent's own top-level traced_span always logs a
    root entry on exit (tracing.py)."""
    path = Path(TRACE_LOG_PATH)
    before_size = path.stat().st_size if path.exists() else 0

    result = run_agent(question, backend="gemini", verbose=True)

    run_id = None
    if path.exists():
        with path.open(encoding="utf-8") as f:
            f.seek(before_size)
            for line in f:
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                if entry.get("is_root"):
                    run_id = entry.get("run_id")
    if run_id is None:
        return [], result.answer

    return _tool_calls_for_run(run_id), result.answer


def check_mechanism_1_unit_conversion():
    print("\n[1] Mechanism 1: unnecessary `calculate` call for a unit conversion")
    question = "What was Palantir's total revenue for 2025?"
    calls, answer = _run_and_capture(question)
    names = [c[0] for c in calls]
    print(f"  tool calls: {names!r}")
    print(f"  answer: {answer!r}")

    calculate_calls = [args for name, args in calls if name == "calculate"]
    if calculate_calls:
        print(f"  [WASTE PRESENT] {len(calculate_calls)} calculate call(s) made for a unit conversion:")
        for args in calculate_calls:
            print(f"    {args!r}")
    else:
        print("  [OK] no calculate call made -- model stated the value directly")

    if "allotted number of searches" in answer:
        print("  [BUDGET EXHAUSTED] the run timed out")


def check_mechanism_2_redundant_rederivation():
    print("\n[2] Mechanism 2: re-fetching components of an answer a tool already returned")
    question = "What was Apple's 3-year average operating margin from fiscal year 2023 through fiscal year 2025?"
    calls, answer = _run_and_capture(question)
    names = [c[0] for c in calls]
    print(f"  tool calls: {names!r}")
    print(f"  answer: {answer!r}")

    fact_calls = [args for name, args in calls if name == "get_financial_fact"]
    multi_year_calls = [a for a in fact_calls if "start_fiscal_year" in a and "end_fiscal_year" in a]
    single_year_followups = [a for a in fact_calls if "fiscal_year" in a and "start_fiscal_year" not in a]

    if multi_year_calls and single_year_followups:
        print(
            f"  [WASTE PRESENT] got the multi-year average directly "
            f"({multi_year_calls[0]!r}) then still fetched "
            f"{len(single_year_followups)} single-year value(s) afterward"
        )
    elif multi_year_calls:
        print("  [OK] multi-year average fetched, no redundant single-year re-derivation")
    else:
        print("  [INFO] multi-year path never reached at all this run")

    if "allotted number of searches" in answer:
        print("  [BUDGET EXHAUSTED] the run timed out")


def check_mechanism_3_ranking_tool_choice():
    print("\n[3] Mechanism 3: five-call ranking path instead of compare_financial_metric")
    question = (
        "Comparing Apple's fiscal year 2025 (ended September 27, 2025), Microsoft's fiscal year 2025 "
        "(ended June 30, 2025), NVIDIA's fiscal year 2026 (ended January 25, 2026), Salesforce's fiscal "
        "year 2026 (ended January 31, 2026), and Palantir's fiscal year 2025 (ended December 31, 2025), "
        "which company had the lowest operating margin?"
    )
    calls, answer = _run_and_capture(question)
    names = [c[0] for c in calls]
    print(f"  tool calls: {names!r}")
    print(f"  answer: {answer!r}")

    used_compare = "compare_financial_metric" in names
    fact_call_count = names.count("get_financial_fact")

    if used_compare:
        print("  [OK] compare_financial_metric used -- the one-call path that can actually retrieve CRM")
    elif fact_call_count >= 4:
        print(
            f"  [WASTE PRESENT] {fact_call_count} individual get_financial_fact calls instead of "
            "one compare_financial_metric call -- this path cannot retrieve CRM's FY2026 margin"
        )
    else:
        print(f"  [INFO] neither pattern clearly matched ({fact_call_count} get_financial_fact calls)")

    if "20.1" in answer or "crm" in answer.lower() or "salesforce" in answer.lower():
        print("  [OK] answer mentions Salesforce/CRM's margin")
    else:
        print("  [PROBLEM] answer does not appear to identify Salesforce/CRM as the lowest")

    if "allotted number of searches" in answer:
        print("  [BUDGET EXHAUSTED] the run timed out")


def main():
    check_mechanism_1_unit_conversion()
    check_mechanism_2_redundant_rederivation()
    check_mechanism_3_ranking_tool_choice()
    print(
        "\nDone. Before the Step 1-3 prompt changes, expect [WASTE PRESENT]/[BUDGET EXHAUSTED] "
        "on some or all three. After, expect [OK] on all three."
    )


if __name__ == "__main__":
    main()
