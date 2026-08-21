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

from agent import run_agent, value_is_citation_verified
from config import DEFAULT_BACKEND, OLLAMA_MODEL_NAME, OLLAMA_URL  # used directly by grade_judged()
from llm_backends import BACKENDS
from numeric_utils import extract_numbers, normalize

QUESTIONS_PATH = Path("./eval_questions.jsonl")
RESULTS_DIR = Path("./eval_results")

CITATION_PATTERN = re.compile(r"\[\d+\]")

# ---------------------------------------------------------------------------
# Numeric grading
# ---------------------------------------------------------------------------
# extract_numbers()/normalize() live in numeric_utils.py, shared with
# agent.py's verify_citations() -- see that module's docstring for why.


def grade_numeric(
    answer_text: str, expected_value: float, expected_unit: str, all_results: list[dict] | None = None
) -> tuple[bool, str]:
    expected_category, expected_norm = normalize(expected_value, expected_unit)
    tolerance = max(0.01 * abs(expected_norm), 0.05)  # 1% relative, with a small floor

    for value, unit in extract_numbers(answer_text):
        category, norm = normalize(value, unit)
        if category != expected_category:
            continue
        if abs(norm - expected_norm) <= tolerance:
            # A plain-text match isn't enough on its own -- found live,
            # not hypothetical: aapl-employees-fy25 used to "pass" here
            # even though its citation actually pointed at a chunk about
            # debt notes, nothing to do with employee count. all_results
            # is optional (None skips this) so existing/simple callers
            # that don't have citation context keep working unchanged.
            if all_results is not None and not value_is_citation_verified(
                expected_value, expected_unit, answer_text, all_results
            ):
                return False, (
                    f"found matching value: {value} ({unit}) but its citation isn't actually "
                    "supported by the source (likely self-computed or misattributed)"
                )
            return True, f"found matching value: {value} ({unit})"

    return False, f"no value matching {expected_value} {expected_unit} found in answer"


def grade_comparison(
    answer_text: str, expected: list[dict], all_results: list[dict] | None = None
) -> tuple[bool, str]:
    """Like grade_numeric, but for questions spanning multiple companies:
    passes only if EVERY entry in `expected` (each a {"ticker",
    "expected_value", "expected_unit"} dict) has its value found in the
    answer — not just any one of them. Reuses grade_numeric per entity
    rather than duplicating the extraction/tolerance logic, including
    its citation-verification check when `all_results` is given.

    Known limitation: this doesn't check that a found number is
    correctly *attributed* to the right entity in the general case (e.g.
    it would still pass if the answer accidentally swapped which
    company a number was reported for while still citing SOME source for
    it) — only that both numbers appear somewhere in the text and, if
    `all_results` is given, that each is backed by an actual citation
    somewhere. Good enough to catch "dropped an entity entirely" and
    "cited a value that isn't actually in any source," the two failure
    modes this type has concretely hit; a full entity-swap check would
    need a smarter (likely LLM-judge-based) check layered on top.
    """
    missing = []
    for entry in expected:
        passed, _ = grade_numeric(answer_text, entry["expected_value"], entry["expected_unit"], all_results)
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
            "model": OLLAMA_MODEL_NAME,
            "messages": [
                {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            # See llm_backends.py's _ollama_call for why num_ctx is set explicitly
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


def _select_questions(questions: list[dict], ids: list[str] | None, include_skipped: bool) -> list[dict]:
    """Applies --ids / skip-flag filtering, kept separate from
    run_eval()'s live agent loop so it's testable without network/Ollama
    calls. Explicit `ids` always wins over a question's own `skip` flag
    -- asking for a question by ID directly is a stronger signal than
    the file's default, and is how you'd re-run a skip-flagged question
    on demand without editing eval_questions.jsonl. Result follows the
    file's own order, not the order `ids` were given in."""
    if ids is not None:
        wanted = set(ids)
        selected = [q for q in questions if q["id"] in wanted]
        missing = wanted - {q["id"] for q in selected}
        if missing:
            raise ValueError(f"Unknown question id(s): {sorted(missing)}")
        return selected
    if include_skipped:
        return questions
    return [q for q in questions if not q.get("skip")]


def run_eval(
    questions_path: Path, ids: list[str] | None = None, include_skipped: bool = False, backend: str = "ollama"
) -> list[dict]:
    questions = load_questions(questions_path)
    questions = _select_questions(questions, ids, include_skipped)
    results = []

    for q in questions:
        print(f"[{q['id']}] {q['question']}")
        answer_text, retrieved, citation_warnings = run_agent(q["question"], backend=backend)
        has_citation = bool(CITATION_PATTERN.search(answer_text))

        if q["type"] == "numeric":
            passed, detail = grade_numeric(answer_text, q["expected_value"], q["expected_unit"], retrieved)
        elif q["type"] == "comparison":
            passed, detail = grade_comparison(answer_text, q["expected"], retrieved)
        elif q["type"] == "judged":
            passed, detail = grade_judged(q["question"], answer_text, q["criteria"])
        else:
            raise ValueError(f"Unknown question type: {q['type']!r} in question {q['id']!r}")

        status = "PASS" if passed else "FAIL"
        print(f"  -> {status} ({detail})")
        if not has_citation:
            print("  -> WARNING: answer has no [n] citation marker at all")
        for w in citation_warnings:
            print(f"  -> CITATION WARNING: {w}")

        results.append(
            {
                "id": q["id"],
                "ticker": q.get("ticker") or q.get("tickers"),
                "question": q["question"],
                "type": q["type"],
                "passed": passed,
                "detail": detail,
                "has_citation": has_citation,
                "citation_warnings": citation_warnings,
                "answer": answer_text,
                "n_chunks_retrieved": len(retrieved),
            }
        )

    return results


def print_summary(results: list[dict]) -> None:
    total = len(results)
    passed = sum(r["passed"] for r in results)
    cited = sum(r["has_citation"] for r in results)
    unverified = sum(bool(r["citation_warnings"]) for r in results)

    print(f"\n{'=' * 60}")
    print(
        f"Results: {passed}/{total} passed, {cited}/{total} included a citation marker, "
        f"{unverified}/{total} had at least one unverified numeric citation"
    )
    for r in results:
        mark = "PASS" if r["passed"] else "FAIL"
        cite = "" if r["has_citation"] else "  [no citation]"
        unverified_flag = "  [unverified citation]" if r["citation_warnings"] else ""
        print(f"  [{mark}] {r['id']} ({r['type']}){cite}{unverified_flag}")


def save_report(results: list[dict], backend: str) -> Path:
    RESULTS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = RESULTS_DIR / f"{timestamp}.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump({"backend": backend, "results": results}, f, indent=2)
    return out_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", type=Path, default=QUESTIONS_PATH)
    parser.add_argument(
        "--ids",
        type=str,
        default=None,
        help="comma-separated question IDs to run (default: all, minus any skip: true questions)",
    )
    parser.add_argument(
        "--include-skipped",
        action="store_true",
        help="also run questions marked skip: true (ignored if --ids is given)",
    )
    parser.add_argument(
        "--backend", choices=list(BACKENDS), default=DEFAULT_BACKEND, help="which LLM backend to use"
    )
    args = parser.parse_args()

    ids = [i.strip() for i in args.ids.split(",")] if args.ids else None
    results = run_eval(args.questions, ids=ids, include_skipped=args.include_skipped, backend=args.backend)
    print_summary(results)
    out_path = save_report(results, backend=args.backend)
    print(f"\nFull report saved to {out_path}")


if __name__ == "__main__":
    main()
