"""
Live verification of the citation-retry slot: the one corrective retry
no longer needs spare MAX_TOOL_ITERATIONS budget. Run BEFORE the change
(a post-budget submit with failing claims is refused with no retry) and
AFTER (the same submit gets a forced retry, and Gemini accepts the
forced submit_answer tool result without a 400).

Live-only: whether Gemini accepts a forced retry after the budget is
spent, and what it resubmits, needs a real API call.

Both triggers are made deterministic, since the natural ones are the
very flakiness being measured: MAX_TOOL_ITERATIONS is lowered to 2 so
the submit lands after the budget is spent, and the first claim check of
each run returns one injected quote_not_found warning, since natural
claims often verify cleanly and would leave the retry unexercised. Every later check
is the real verifier, so the retried answer is gated for real. What
stays live is the part a fake can't show: Gemini accepting the forced
retry tool result and what it resubmits.

Reads the citation_retry / citation_gate_refused / final_turn_forced
events back from var/trace_logs/traces.jsonl by run_id.

Usage (from the repo root):
    python tests/manual/verify_retry_slot.py
"""

import json
from pathlib import Path

from sec_agent.agent import agent, submission
from sec_agent.agent.citations import CitationWarning
from sec_agent.config import TRACE_LOG_PATH

LOW_BUDGET = 2
EVENT_CATEGORIES = ("final_turn_forced", "citation_retry", "citation_gate_refused")

QUESTIONS = {
    "pltr-inventory-turnover": "What was Palantir's inventory turnover ratio for fiscal year 2025?",
    "nvda-rd-q4fy26": "What were NVIDIA's research and development expenses for the fourth quarter of fiscal year 2026?",
    "msft-three-segments": (
        "What was revenue for each of Microsoft's three reportable segments in the quarter ended March 31, 2026?"
    ),
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


def _fail_first_check(real_verify_claims):
    """verify_claims that returns one injected warning on its first call,
    then defers to the real verifier."""
    calls = []

    def verify(claims, all_results, question, answer_text):
        calls.append(1)
        if len(calls) == 1:
            return [
                CitationWarning(
                    check="quote_not_found",
                    citation_index=1,
                    value=None,
                    unit=None,
                    message="[1] quote not found in the cited source (injected by verify_retry_slot.py)",
                    quote=None,
                )
            ]
        return real_verify_claims(claims, all_results, question, answer_text)

    return verify


def check(label: str, question: str, real_verify_claims) -> None:
    print(f"\n[{label}] {question!r}")
    path = Path(TRACE_LOG_PATH)
    before_size = path.stat().st_size if path.exists() else 0

    submission.verify_claims = _fail_first_check(real_verify_claims)
    result = agent.run_agent(question, backend="gemini", verbose=True)

    entries = _new_entries(path, before_size)
    run_ids = {e.get("run_id") for e in entries if e.get("is_root")}
    events = [e for e in entries if e.get("run_id") in run_ids and e.get("category") in EVENT_CATEGORIES]
    for e in events:
        fields = {k: v for k, v in e.items() if k not in ("timestamp", "run_id", "category", "warnings")}
        print(f"  event {e['category']}: {fields}")
    print(f"  answer: {result.answer[:300]!r}")
    print(f"  refused: {bool(result.citation_warnings)}")

    retries = [e for e in events if e["category"] == "citation_retry"]
    refused = [e for e in events if e["category"] == "citation_gate_refused"]
    if retries:
        print("  [RETRY RAN] a post-budget citation retry fired" if retries[0].get("forced") else "  [RETRY RAN]")
    elif refused:
        print("  [NO RETRY] failing claims refused without a retry (expected before the change)")
    else:
        print("  [CLEAN] claims verified first time -- this run didn't exercise the retry")


def main():
    agent.MAX_TOOL_ITERATIONS = LOW_BUDGET
    real_verify_claims = submission.verify_claims
    for label, question in QUESTIONS.items():
        check(label, question, real_verify_claims)
    print(
        "\nDone. Before the change: [NO RETRY] on any run whose claims failed. After: [RETRY RAN] "
        "with forced=True instead, and no Gemini 400 error."
    )


if __name__ == "__main__":
    main()
