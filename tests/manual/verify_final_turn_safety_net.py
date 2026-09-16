"""
Live verification of the final-turn safety net fix (BACKLOG.md's
MAX_TOOL_ITERATIONS zero-slack bug) -- run BEFORE the loop change lands,
to reproduce the bug, and again AFTER, to confirm it's gone. See
docs/plans/2026-09-14-tool-turn-waste.md's Mechanism 4 and the follow-up
decision doc for this fix.

Exactly the CLAUDE.md live-code carve-out: whether a real model, forced
into one extra submit-only turn right as the dispatch budget runs out,
actually submits a clean refusal/answer instead of ignoring the nudge or
(for the ranking case) confidently naming a company using an incomplete
data set -- can only be answered by an actual API call, not a mock.

Drives agent.run_agent() directly (the real entry point) for three
questions, Gemini only (the new safety net is gated to
_FINAL_TURN_BACKENDS = {"gemini"}, so Ollama's behavior is unchanged by
this fix and isn't exercised here):

  1. nvda-rd-expense-q4fy26-refusal and
  2. pltr-inventory-turnover-fy2025-refusal: both correct-REFUSAL
     questions that historically make 5 successful, zero-error dispatch
     calls then die with the generic "wasn't able to finish" timeout
     message instead of ever getting a turn to submit the refusal
     they'd earned. Before the fix: expect the generic message. After:
     expect an actual refusal (or a real answer, if the model finds the
     data another way this run) -- NOT the generic message.
  3. five-company-operating-margin-ranking-fy2025: the risk case. A real
     run previously died holding 4 of 5 companies' margins (missing
     CRM, a separate already-tracked bug) with no turn left to
     communicate anything. The fix must not turn this into a
     confidently-wrong ranking that omits CRM without caveat -- flagged
     as [WATCH], not a hard failure, since full correctness judgment
     needs a human or the eval judge.

Reads the tool-call sequence and citation results back from
trace_logs/traces.jsonl by run_id, mirroring
tests/manual/verify_tool_turn_waste.py's own helper exactly (traced_span
always appends there synchronously -- see tracing.py).

Informational, not a hard assert-and-exit-1 gate (same spirit as
verify_submit_answer.py/verify_tool_turn_waste.py) -- "did the model
submit a refusal, an answer, or nothing" is exactly the kind of thing
this script exists to observe and report, not something to fail loudly
over on a single live run's non-determinism.

Usage (from the repo root):
    python tests/manual/verify_final_turn_safety_net.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from config import TRACE_LOG_PATH
from agent import run_agent

GENERIC_TIMEOUT_MARKER = "allotted number of searches"

NVDA_RD_EXPENSE_QUESTION = (
    "What were NVIDIA's research and development expenses for the fourth quarter of fiscal year 2026?"
)
PLTR_INVENTORY_TURNOVER_QUESTION = "What was Palantir's inventory turnover ratio for fiscal year 2025?"
RANKING_QUESTION = (
    "Comparing Apple's fiscal year 2025 (ended September 27, 2025), Microsoft's fiscal year 2025 "
    "(ended June 30, 2025), NVIDIA's fiscal year 2026 (ended January 25, 2026), Salesforce's fiscal "
    "year 2026 (ended January 31, 2026), and Palantir's fiscal year 2025 (ended December 31, 2025), "
    "which of these five companies had the lowest operating margin, and what was that margin?"
)


def _tool_calls_for_run(run_id: str) -> list[tuple[str, dict]]:
    """Reads back every tool-span (name, input) logged under `run_id`, in
    order. Mirrors verify_tool_turn_waste.py's helper of the same name."""
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


def _run_and_capture(question: str):
    """Runs the question through the real agent loop and returns
    (tool_call_names, result). Mirrors verify_tool_turn_waste.py's
    _run_and_capture, returning the full AgentResult (not just answer
    text) since this script also needs citations/warnings."""
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
        return [], result

    return [name for name, _args in _tool_calls_for_run(run_id)], result


def _print_common(tool_calls: list[str], result) -> None:
    print(f"  tool calls: {tool_calls!r}")
    print(f"  answer: {result.answer!r}")
    if result.withheld_answer is not None:
        print(f"  withheld_answer (real submission the citation gate refused): {result.withheld_answer!r}")
    if result.citation_warnings:
        print(f"  citation warnings: {result.citation_warnings!r}")


def check_refusal_question(label: str, question: str) -> None:
    print(f"\n[{label}] {question!r}")
    tool_calls, result = _run_and_capture(question)
    _print_common(tool_calls, result)

    if GENERIC_TIMEOUT_MARKER in result.answer:
        print("  [BUG STILL PRESENT] generic timeout -- the model never got a chance to submit its refusal")
    else:
        print("  [OK] did not hit the generic timeout -- the model got to submit something")


def check_ranking_question() -> None:
    print(f"\n[ranking] {RANKING_QUESTION!r}")
    tool_calls, result = _run_and_capture(question=RANKING_QUESTION)
    _print_common(tool_calls, result)

    if GENERIC_TIMEOUT_MARKER in result.answer:
        print("  [OK, acceptable outcome] generic timeout -- no worse than before this fix")
        return

    tickers_cited = {r["metadata"]["ticker"] for r in result.results}
    crm_present = "CRM" in tickers_cited
    caveat_language = any(
        phrase in result.answer.lower()
        for phrase in ("crm", "salesforce", "couldn't verify", "unable to verify", "not available", "missing")
    )

    if crm_present:
        print("  [OK] CRM appears among the retrieved/cited results")
    elif caveat_language:
        print("  [OK] CRM absent, but the answer appears to caveat incomplete coverage -- check the text above by hand")
    else:
        print(
            "  [WATCH] CRM does not appear in the citations AND no coverage caveat detected -- "
            "possible confidently-wrong ranking; read the full answer above and judge by hand"
        )


def main():
    check_refusal_question("1", NVDA_RD_EXPENSE_QUESTION)
    check_refusal_question("2", PLTR_INVENTORY_TURNOVER_QUESTION)
    check_ranking_question()
    print(
        "\nDone. Before the fix, expect [BUG STILL PRESENT] on questions 1-2. After, expect [OK] on "
        "both (a real refusal or answer, not the generic timeout), and no [WATCH] on the ranking question."
    )


if __name__ == "__main__":
    main()
