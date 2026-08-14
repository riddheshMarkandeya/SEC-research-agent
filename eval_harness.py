"""
Week 4 — Eval harness (scaffolding)
----------------------------------------
Runs every question in eval_questions.jsonl through answer.generate_answer()
and grades the result, so changes to retrieval/prompting/agent behavior can
be measured against a fixed baseline instead of eyeballed. This exists
specifically because Week 3's answer.py enforces "cite everything or
refuse" only via prompt instruction — nothing checks that it actually
happened. This harness is where that gets checked mechanically.

Two grading strategies, chosen per-question by its "type" field:
  - "numeric": exact-match. The question has one verifiable ground-truth
    number (e.g. "$72.4 billion"); grading extracts every number-like
    token from the generated answer and checks whether any of them,
    once unit-normalized, is within tolerance of the expected value.
    Deterministic and free — no LLM call needed to grade these.
  - "judged": LLM-as-judge. For qualitative questions ("what risks does
    X describe...") or refusal questions (no ground-truth number exists
    to match), a second LLM call grades PASS/FAIL against a short
    criteria string, since there's no single correct string to diff
    against.

This is scaffolding, not the full eval suite — eval_questions.jsonl has
6 seed questions (reusing facts already verified earlier in this
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

from answer import MODEL_NAME, OLLAMA_URL, generate_answer

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
            "options": {"temperature": 0.0},
        },
        timeout=120,
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
        answer_text, retrieved = generate_answer(q["question"], ticker=q.get("ticker"))
        has_citation = bool(CITATION_PATTERN.search(answer_text))

        if q["type"] == "numeric":
            passed, detail = grade_numeric(answer_text, q["expected_value"], q["expected_unit"])
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
                "ticker": q.get("ticker"),
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
