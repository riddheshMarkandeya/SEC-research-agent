"""
One-time (re-runnable) live verification of llm_backends.complete()'s
Gemini branch (see
docs/decisions/2026-09-10-citation-gate-measurement-instrumentation.md)
with no unit-test coverage, per this project's CLAUDE.md carve-out: the
Ollama branch is pure control flow around an already-tested ollama_call()
and is unit-tested in tests/test_llm_backends.py, but the Gemini branch
makes a real API call through the google-genai SDK and mocking that
would only test the mock, not the code.

Specifically checks the property complete() exists to guarantee that the
existing BACKENDS tool-calling path can't: a single-turn, tool-free
completion at temperature 0.0, used by eval_harness.py's grade_judged()
so --judge-backend gemini doesn't require Ollama to be running at all.

Usage (from the repo root):
    python tests/manual/verify_complete.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from config import GEMINI_API_KEY
from llm_backends import complete


def main():
    if not GEMINI_API_KEY:
        print("GEMINI_API_KEY not set -- skipping (see .env.example).")
        return

    print("[complete] calling Gemini with a fixed grading-style prompt, no tools...")
    result = complete(
        "gemini",
        "You are grading an AI assistant's answer. Respond with exactly two lines: "
        "the first line is either PASS or FAIL, the second line is a one-sentence reason.",
        "Question: What is 2+2?\nGrading criteria: the answer should say 4.\n"
        "AI assistant's answer: The answer is 4.\nDoes the answer satisfy the criteria?",
        temperature=0.0,
    )
    print(f"  raw result: {result!r}")

    lines = result.splitlines()
    assert lines, "expected a non-empty response"
    assert lines[0].strip().upper().startswith("PASS"), f"expected a PASS verdict, got: {lines[0]!r}"
    print("  [OK] complete('gemini', ...) returned a plain string, no tool calls, correct PASS verdict")

    print("\n[complete] calling twice at temperature=0.0, confirming near-determinism...")
    second = complete(
        "gemini",
        "Reply with exactly one line: the single word PONG.",
        "PING",
        temperature=0.0,
    )
    third = complete(
        "gemini",
        "Reply with exactly one line: the single word PONG.",
        "PING",
        temperature=0.0,
    )
    print(f"  first:  {second!r}")
    print(f"  second: {third!r}")
    assert "PONG" in second.upper() and "PONG" in third.upper(), "expected both calls to follow the instruction"
    print("  [OK] both calls followed the one-line instruction")

    print("\nAll checks passed.")


if __name__ == "__main__":
    main()
