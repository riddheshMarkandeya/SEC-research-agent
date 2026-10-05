"""
Live verification of the uniform submit loop: a failing submit is answered
with a citation retry for as long as a turn is left, not just once. Run
BEFORE the change (the second failing submit is refused) and AFTER (a
second retry runs, and Gemini accepts two forced submit_answer tool
results in a row without a 400).

Live-only: whether Gemini accepts back-to-back forced retries, and what it
resubmits, needs a real API call.

Both triggers are made deterministic, since the natural ones are the
flakiness being measured: MAX_TOOL_ITERATIONS is lowered to 2 so the
retries land past the budget (forced), and the first two submit-gate
checks of each run return an injected quote_not_found warning. Only a
check inside a submit turn that the real gate didn't already reject for
its schema counts, so neither the end-of-run re-gate of a cached
submission nor a schema-invalid submit can use one up. Every later check
is the real gate. On a [RESERVE SPENT] run that ends with no turn left,
the turns run out on an injected failure, so its refusal says nothing
about the real gate; one that ends on forcing_failed re-gates the cached
submission through the real gate.

Reads the citation_retry / final_turn_forced / submit_turns_ended /
citation_gate_refused events back from var/trace_logs/traces.jsonl by
run_id.

Usage (from the repo root):
    python tests/manual/verify_uniform_submit_loop.py
"""

import json
from pathlib import Path

from sec_agent.agent import agent
from sec_agent.agent.citations import CitationWarning
from sec_agent.config import TRACE_LOG_PATH

LOW_BUDGET = 2
INJECTED_FAILURES = 2
EVENT_CATEGORIES = ("final_turn_forced", "citation_retry", "submit_turns_ended", "citation_gate_refused")

QUESTIONS = {
    "aapl-employees": "How many full-time equivalent employees did Apple have as of September 27, 2025?",
    "msft-cash-to-assets": (
        "What percentage of Microsoft's total assets was held as cash and cash equivalents at the end of fiscal year 2025?"
    ),
    "nvda-rd-q4fy26": "What were NVIDIA's research and development expenses for the fourth quarter of fiscal year 2026?",
}


def _new_entries(path: Path, before_size: int) -> list[dict]:
    # Binary mode: before_size is a byte offset from stat(), and a
    # text-mode seek is only defined for tell() cookies. A shrunk (rotated)
    # log is read whole.
    if not path.exists():
        return []
    with path.open("rb") as f:
        if before_size <= path.stat().st_size:
            f.seek(before_size)
        return [json.loads(line.decode("utf-8")) for line in f if line.strip()]


def _inject_submit_failures(real_handle_submit_turn, real_submission_warnings):
    """Wraps the loop's submit handler so the gate check inside each of the
    first INJECTED_FAILURES schema-valid submit turns returns one injected
    warning. Gate calls outside a submit turn (the cached re-gate) and
    schema-invalid submits get the real gate's verdict."""
    state = {"injected": 0, "in_submit_turn": False}

    def handle_submit_turn(args, other, ctx, loop_state):
        state["in_submit_turn"] = True
        try:
            return real_handle_submit_turn(args, other, ctx, loop_state)
        finally:
            state["in_submit_turn"] = False

    def gate(args, all_results, question):
        answer_text, warnings = real_submission_warnings(args, all_results, question)
        schema_invalid = any(w.check == "no_structured_answer" for w in warnings)
        if state["in_submit_turn"] and not schema_invalid and state["injected"] < INJECTED_FAILURES:
            state["injected"] += 1
            warning = CitationWarning(
                check="quote_not_found",
                citation_index=1,
                value=None,
                unit=None,
                message="[1] quote not found in the cited source (injected by verify_uniform_submit_loop.py)",
                quote=None,
            )
            return answer_text, [warning]
        return answer_text, warnings

    return handle_submit_turn, gate


def check(label: str, question: str, real_handle_submit_turn, real_submission_warnings) -> None:
    print(f"\n[{label}] {question!r}")
    path = Path(TRACE_LOG_PATH)
    before_size = path.stat().st_size if path.exists() else 0

    agent._handle_submit_turn, agent.submission_warnings = _inject_submit_failures(
        real_handle_submit_turn, real_submission_warnings
    )
    result = agent.run_agent(question, backend="gemini", verbose=True)

    entries = _new_entries(path, before_size)
    run_ids = {e.get("run_id") for e in entries if e.get("is_root")}
    events = [e for e in entries if e.get("run_id") in run_ids and e.get("category") in EVENT_CATEGORIES]
    for e in events:
        fields = {k: v for k, v in e.items() if k not in ("timestamp", "run_id", "category", "warnings", "withheld_answer")}
        print(f"  event {e['category']}: {fields}")
    print(f"  answer: {result.answer[:300]!r}")
    print(f"  refused: {bool(result.citation_warnings)}")

    retries = [e for e in events if e["category"] == "citation_retry"]
    forced_turns = [e for e in events if e["category"] == "final_turn_forced"]
    ended = [e for e in events if e["category"] == "submit_turns_ended"]
    if len(retries) >= INJECTED_FAILURES:
        print(f"  [SECOND RETRY RAN] {len(retries)} retries, forced: {[r.get('forced') for r in retries]}")
    elif retries and forced_turns and ended:
        # Expected after the change: a forced final turn and a retry share
        # the reserve, so nothing is left for a second retry.
        verdict = (
            "the refusal is the injected failure, not the real gate"
            if ended[0].get("reason") == "no_turn_left"
            else "forcing failed; the cached submission was re-gated by the real gate"
        )
        print(f"  [RESERVE SPENT] the forced final turn and one retry used both reserve turns ({verdict})")
    elif retries:
        print("  [ONE RETRY] the second failing submit got no retry (expected before the change)")
    else:
        print("  [NO SUBMIT] the run never reached a submit -- it didn't exercise the retry")


def main():
    agent.MAX_TOOL_ITERATIONS = LOW_BUDGET
    real_handle_submit_turn = agent._handle_submit_turn
    real_submission_warnings = agent.submission_warnings
    for label, question in QUESTIONS.items():
        check(label, question, real_handle_submit_turn, real_submission_warnings)
    print(
        "\nDone. Before the change: [ONE RETRY] on every run that submitted. After: [SECOND RETRY RAN], "
        "or [RESERVE SPENT] when a forced final turn came first, and no Gemini 400 error."
    )


if __name__ == "__main__":
    main()
