"""
Live verification of the calculate tool (2026-09-11) -- see
docs/plans/2026-09-11-calculate-tool-and-stress-questions.md.

Exactly the CLAUDE.md live-code carve-out: whether the model actually
reaches for `calculate` instead of a self-computed value, and whether its
answer_text discloses the computation, can only be confirmed by a real run
-- system-prompt wording that looks right on paper has needed correction
before this session (rule 9's original wording), so this is checked by
reading actual output, not assumed.

Re-runs the two real questions that motivated this tool -- both self-
computed ratios the formula registry doesn't cover, both of which refused
before this tool existed (aapl-rd-pct-gross-profit-fy2025: the model cited
its two raw inputs but never stated the percentage; msft-cash-to-assets-
fy2025: the model computed the percentage but added no claim for it) --
and checks three things per the design doc's own verification section:
  1. The agent doesn't refuse (citation_warnings is empty).
  2. answer_text states the correct value.
  3. answer_text actually DISCLOSES the computation (shows the formula/
     inputs, not just the bare result) -- the prompt-level-only
     requirement confirmed via AskUserQuestion during planning, which
     needs a real run to confirm it lands, not just that the prompt asks
     for it.

Usage (from the repo root):
    python tests/manual/verify_calculate.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from agent import run_agent
from config import GEMINI_API_KEY

CASES = [
    (
        "aapl-rd-pct-gross-profit-fy2025",
        "What percentage of Apple's fiscal year 2025 gross profit was spent on research and development?",
        17.7,
    ),
    (
        "msft-cash-to-assets-fy2025",
        "What percentage of Microsoft's total assets was held as cash and cash equivalents at the end of fiscal year 2025?",
        4.9,
    ),
]

# Loose disclosure check -- looking for language/symbols that suggest the
# answer shows a computation rather than presenting the value as a bare
# fact. Deliberately lenient (this is a human-read verification script,
# not a hard gate) -- printed in full either way so the actual wording can
# be judged by eye, not just this heuristic.
_DISCLOSURE_HINTS = ("computed", "calculat", "÷", "/", "divided by", "as a percentage of")


def check_case(question_id: str, question: str, expected_value: float):
    print(f"\n[{question_id}] {question}")
    result = run_agent(question, backend="gemini", verbose=True)

    print(f"  answer_text: {result.answer}")
    print(f"  citation_warnings: {result.citation_warnings}")
    print(f"  withheld: {result.withheld_answer is not None}")

    if result.citation_warnings or result.withheld_answer is not None:
        print("  [PROBLEM] the agent refused -- calculate either wasn't used or didn't verify")
        return

    value_str = str(expected_value)
    if value_str not in result.answer and f"{expected_value:.1f}" not in result.answer:
        print(f"  [PROBLEM] expected value {expected_value} not found in the answer text")
        return
    print(f"  [OK] answer includes the expected value ({expected_value})")

    discloses = any(hint in result.answer.lower() for hint in _DISCLOSURE_HINTS)
    if discloses:
        print("  [OK] answer_text appears to disclose the computation (matched a disclosure hint)")
    else:
        print(
            "  [CHECK BY EYE] no disclosure hint matched -- read answer_text above and confirm by hand "
            "whether it shows the formula/inputs or just states the value as if it were a filed fact"
        )


def main():
    if not GEMINI_API_KEY:
        print("GEMINI_API_KEY not set -- skipping (see .env.example).")
        return
    for question_id, question, expected_value in CASES:
        check_case(question_id, question, expected_value)
    print("\nDone. Record what each case actually produced in PROJECT_CONTEXT.md before adding eval questions.")


if __name__ == "__main__":
    main()
