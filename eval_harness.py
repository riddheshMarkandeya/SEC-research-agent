"""
Week 4/5 — Eval harness (scaffolding)
----------------------------------------
Runs every question in eval_questions.jsonl through agent.run_agent()
and grades the result, so changes to retrieval/prompting/agent behavior
can be measured against a fixed baseline instead of eyeballed. This
exists specifically because Week 3's answer.py (and now Week 5's
agent.py) enforce "cite everything or refuse" only via prompt
instruction — nothing checks that it actually happened. This harness is
where that gets checked mechanically.

Routes through agent.run_agent() rather than answer.generate_answer()
as of Week 5 — the agent resolves which ticker(s) a question is about
itself (via tool-calling), which is a closer match to how this system
is actually meant to be used, and lets comparison questions exercise
the agent's multi-tool-call path. Every existing question's "ticker"
field is now purely documentation for a human skimming the file — it's
no longer passed into the call; the agent has to infer it from the
question text, same as real usage.

Three grading strategies, chosen per-question by its "type" field:
  - "numeric": exact-match. The question has one verifiable ground-truth
    number (e.g. "$72.4 billion"); grading extracts every number-like
    token from the generated answer and checks whether any of them,
    once unit-normalized, is within tolerance of the expected value.
    Deterministic and free — no LLM call needed to grade these.
  - "comparison": like "numeric", but for questions spanning multiple
    companies — requires EVERY entity in the question's "expected" list
    to have its value found in the answer, not just any one of them.
    Added after finding, by hand, that agent.py could correctly
    retrieve both companies' figures via two tool calls but only report
    one of them in its final synthesis — this type exists specifically
    to catch that failure mode mechanically instead of by manual luck.
  - "judged": LLM-as-judge. For qualitative questions ("what risks does
    X describe...") or refusal questions (no ground-truth number exists
    to match), a second LLM call grades PASS/FAIL against a short
    criteria string, since there's no single correct string to diff
    against.

This is scaffolding, not the full eval suite — eval_questions.jsonl has
8 seed questions (reusing facts already verified earlier in this
project rather than new research) to prove the harness works end-to-end.
Growing it to the full 30-50 question FinanceBench-style set is a
separate, later task.

Usage:
    python eval_harness.py
    python eval_harness.py --questions custom_questions.jsonl
"""

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import requests

from agent import run_agent
from answer import MODEL_NAME, OLLAMA_URL  # still used directly by grade_judged()

QUESTIONS_PATH = Path("./eval_questions.jsonl")
RESULTS_DIR = Path("./eval_results")

CITATION_PATTERN = re.compile(r"\[\d+\]")

# ---------------------------------------------------------------------------
# Numeric grading
# ---------------------------------------------------------------------------
# Matches an optional "$", a number (with optional thousands-commas and
# decimal point), and an optional trailing unit word or "%". Deliberately
# broad — it's fine to pick up spurious candidates (e.g. a "[1]" citation
# marker parsing as the number 1); grading only needs the *correct* value
# to appear somewhere among the candidates, extra noise is harmless.
NUMBER_PATTERN = re.compile(
    r"\$?\s*(\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+\.\d+|\d+)\s*(billion|million|thousand|percent)?\s*(%)?",
    re.IGNORECASE,
)

UNIT_MULTIPLIERS = {"thousand": 1e3, "million": 1e6, "billion": 1e9}


def extract_numbers(text: str) -> list[tuple[float, str]]:
    """Return every (value, unit) candidate found in text. unit is one of
    'raw', 'thousand', 'million', 'billion', 'percent'."""
    candidates = []
    for match in NUMBER_PATTERN.finditer(text):
        raw_value, unit_word, percent_sign = match.groups()
        try:
            value = float(raw_value.replace(",", ""))
        except ValueError:
            continue
        if percent_sign or (unit_word and unit_word.lower() == "percent"):
            unit = "percent"
        elif unit_word:
            unit = unit_word.lower()
        else:
            unit = "raw"
        candidates.append((value, unit))
    return candidates


def _normalize(value: float, unit: str) -> tuple[str, float]:
    """Collapse a (value, unit) into a (category, comparable_number) pair.
    'percent' is its own category since it's not on the same scale as a
    dollar/count figure — 20 (percent) and 20 (raw) are not the same
    claim and must never compare equal."""
    if unit == "percent":
        return "percent", value
    return "scale", value * UNIT_MULTIPLIERS.get(unit, 1.0)


def grade_numeric(answer_text: str, expected_value: float, expected_unit: str) -> tuple[bool, str]:
    expected_category, expected_norm = _normalize(expected_value, expected_unit)
    tolerance = max(0.01 * abs(expected_norm), 0.05)  # 1% relative, with a small floor

    for value, unit in extract_numbers(answer_text):
        category, norm = _normalize(value, unit)
        if category != expected_category:
            continue
        if abs(norm - expected_norm) <= tolerance:
            return True, f"found matching value: {value} ({unit})"

    return False, f"no value matching {expected_value} {expected_unit} found in answer"


def grade_comparison(answer_text: str, expected: list[dict]) -> tuple[bool, str]:
    """Like grade_numeric, but for questions spanning multiple companies:
    passes only if EVERY entry in `expected` (each a {"ticker",
    "expected_value", "expected_unit"} dict) has its value found in the
    answer — not just any one of them. Reuses grade_numeric per entity
    rather than duplicating the extraction/tolerance logic.

    Known limitation: this doesn't check that a found number is
    correctly *attributed* to the right entity (e.g. it would still
    pass if the answer accidentally swapped which company a number was
    reported for) — only that both numbers appear somewhere in the
    text. Good enough to catch "dropped an entity entirely," which is
    the specific failure this type was added for; attribution-checking
    would need a smarter (likely LLM-judge-based) check layered on top.
    """
    missing = []
    for entry in expected:
        passed, _ = grade_numeric(answer_text, entry["expected_value"], entry["expected_unit"])
        if not passed:
            missing.append(f"{entry['ticker']} ({entry['expected_value']} {entry['expected_unit']})")

    if missing:
        return False, f"missing or wrong value(s) for: {', '.join(missing)}"
    return True, f"found matching values for all {len(expected)} entities"


# ---------------------------------------------------------------------------
# LLM-as-judge grading
# ---------------------------------------------------------------------------
JUDGE_SYSTEM_PROMPT = """You are grading an AI assistant's answer against a specific pass/fail criteria. \
Be strict: the criteria must be clearly satisfied by the answer text, not just plausible in general. \
Respond with exactly two lines: the first line is either PASS or FAIL, the second line is a one-sentence reason."""


def grade_judged(question: str, answer_text: str, criteria: str) -> tuple[bool, str]:
    user_prompt = (
        f"Question asked: {question}\n\n"
        f"Grading criteria: {criteria}\n\n"
        f"AI assistant's answer:\n{answer_text}\n\n"
        f"Does the answer satisfy the grading criteria?"
    )
    response = requests.post(
        OLLAMA_URL,
        json={
            "model": MODEL_NAME,
            "messages": [
                {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            # See agent.py's _call_ollama for why num_ctx is set explicitly
            # rather than left at Ollama's 4096-token default. The judge's
            # own input (question + criteria + one answer) is smaller than
            # what generation sees, but the answer being graded can itself
            # be long, so the same headroom applies.
            "options": {"temperature": 0.0, "num_ctx": 8192},
        },
        timeout=240,
    )
    response.raise_for_status()
    verdict_text = response.json()["message"]["content"].strip()

    first_line = verdict_text.splitlines()[0].strip().upper() if verdict_text else ""
    passed = first_line.startswith("PASS")
    reason = verdict_text.splitlines()[1].strip() if len(verdict_text.splitlines()) > 1 else verdict_text
    return passed, reason


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def load_questions(path: Path) -> list[dict]:
    questions = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                questions.append(json.loads(line))
    return questions


def run_eval(questions_path: Path) -> list[dict]:
    questions = load_questions(questions_path)
    results = []

    for q in questions:
        print(f"[{q['id']}] {q['question']}")
        answer_text, retrieved = run_agent(q["question"])
        has_citation = bool(CITATION_PATTERN.search(answer_text))

        if q["type"] == "numeric":
            passed, detail = grade_numeric(answer_text, q["expected_value"], q["expected_unit"])
        elif q["type"] == "comparison":
            passed, detail = grade_comparison(answer_text, q["expected"])
        elif q["type"] == "judged":
            passed, detail = grade_judged(q["question"], answer_text, q["criteria"])
        else:
            raise ValueError(f"Unknown question type: {q['type']!r} in question {q['id']!r}")

        status = "PASS" if passed else "FAIL"
        print(f"  -> {status} ({detail})")
        if not has_citation:
            print("  -> WARNING: answer has no [n] citation marker at all")

        results.append(
            {
                "id": q["id"],
                "ticker": q.get("ticker") or q.get("tickers"),
                "question": q["question"],
                "type": q["type"],
                "passed": passed,
                "detail": detail,
                "has_citation": has_citation,
                "answer": answer_text,
                "n_chunks_retrieved": len(retrieved),
            }
        )

    return results


def print_summary(results: list[dict]) -> None:
    total = len(results)
    passed = sum(r["passed"] for r in results)
    cited = sum(r["has_citation"] for r in results)

    print(f"\n{'=' * 60}")
    print(f"Results: {passed}/{total} passed, {cited}/{total} included a citation marker")
    for r in results:
        mark = "PASS" if r["passed"] else "FAIL"
        cite = "" if r["has_citation"] else "  [no citation]"
        print(f"  [{mark}] {r['id']} ({r['type']}){cite}")


def save_report(results: list[dict]) -> Path:
    RESULTS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = RESULTS_DIR / f"{timestamp}.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    return out_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", type=Path, default=QUESTIONS_PATH)
    args = parser.parse_args()

    results = run_eval(args.questions)
    print_summary(results)
    out_path = save_report(results)
    print(f"\nFull report saved to {out_path}")


if __name__ == "__main__":
    main()
