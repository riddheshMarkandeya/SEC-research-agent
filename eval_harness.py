"""
Eval harness: runs every question in eval_questions.jsonl through
agent.run_agent() and grades the result, so changes to retrieval/
prompting/agent behavior can be measured against a fixed baseline
instead of eyeballed. See
docs/decisions/2026-08-13-eval-harness-scaffolding-and-early-bug-hunts.md.

Three grading strategies, chosen per-question by its "type" field:
  - "numeric": exact-match. The question has one verifiable ground-truth
    number (e.g. "$72.4 billion"); grading extracts every number-like
    token from the generated answer and checks whether any of them,
    once unit-normalized, is within tolerance of the expected value.
    Deterministic and free — no LLM call needed to grade these.
  - "comparison": like "numeric", but for questions spanning multiple
    companies — requires EVERY entity in the question's "expected" list
    to have its value found in the answer, not just any one of them.
  - "judged": LLM-as-judge. For qualitative questions ("what risks does
    X describe...") or refusal questions (no ground-truth number exists
    to match), a second LLM call grades PASS/FAIL against a short
    criteria string, since there's no single correct string to diff
    against.

Usage:
    python eval_harness.py
    python eval_harness.py --questions custom_questions.jsonl
"""

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from agent import run_agent, value_is_citation_verified
from config import DEFAULT_BACKEND, GEMINI_MODEL_NAME, OLLAMA_MODEL_NAME

# OLLAMA_MODEL_NAME/GEMINI_MODEL_NAME record which specific model actually
# answered/judged a report (see save_report()'s own docstring).
# complete() is llm_backends.py's one-shot, tool-free completion helper
# that lets grade_judged() honor --judge-backend. See
# docs/decisions/2026-09-10-citation-gate-measurement-instrumentation.md.
from llm_backends import BACKENDS, complete
from tracing import flush
from numeric_utils import extract_numbers, normalize

QUESTIONS_PATH = Path("./eval/eval_questions.jsonl")
RESULTS_DIR = Path("./eval/eval_results")

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
            # A plain-text match isn't enough on its own -- all_results
            # is optional (None skips this) so existing/simple callers
            # that don't have citation context keep working unchanged.
            # See docs/decisions/2026-09-10-citation-gate-measurement-instrumentation.md.
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
The answer may cite dates or filings that fall after your own training cutoff -- do not treat a date as \
evidence of fabrication merely because it is unfamiliar to you. Only treat a date as hypothetical or \
fabricated if it falls after the real current date stated in the prompt below. \
Respond with exactly two lines: the first line is either PASS or FAIL, the second line is a one-sentence reason."""


def grade_judged(question: str, answer_text: str, criteria: str, backend: str = "ollama") -> tuple[bool, str]:
    """Routes through llm_backends.complete() so `backend` (--judge-
    backend) picks which one actually grades, at the same temperature=0.0
    (stricter than generation's 0.1) and no tool_schemas -- grading never
    calls tools. complete() reuses each backend's existing retry/backoff/
    log_event machinery, so that guarantee holds here too. See
    docs/decisions/2026-09-06-full-codebase-review.md and
    docs/decisions/2026-09-10-citation-gate-measurement-instrumentation.md.

    Injects the real wall-clock date (same datetime.now(timezone.utc)
    pattern as save_report()'s timestamp) so the judge isn't relying on
    its own stale training-cutoff sense of "now" -- without this, a judge
    model trained before a filing's real date reflexively calls a
    correctly-cited current filing "hypothetical future data" (see
    docs/decisions/2026-09-17-fix-judge-hypothetical-date-bug.md). This
    assumes grading happens contemporaneously with generation -- true for
    every call site today (grade_judged only ever runs synchronously
    inside run_eval, right after the answer is generated); would need
    revisiting if a regrade-from-saved-report tool is ever added."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    user_prompt = (
        f"Today's real date is {today}. Treat filing/financial data dated at or before today as real.\n\n"
        f"Question asked: {question}\n\n"
        f"Grading criteria: {criteria}\n\n"
        f"AI assistant's answer:\n{answer_text}\n\n"
        f"Does the answer satisfy the grading criteria?"
    )
    verdict_text = complete(backend, JUDGE_SYSTEM_PROMPT, user_prompt, temperature=0.0)

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


def _grade_by_type(q: dict, answer_text: str, retrieved: list[dict] | None) -> tuple[bool, str]:
    """Numeric/comparison type dispatch shared between _grade() below
    (the real pass/fail verdict) and _citation_gate_evidence() (the
    "would this have passed" check on the withheld text) -- both need
    the same two calls, so this avoids updating two places in sync for a
    signature change or a third gradeable type. Caller is responsible
    for confirming q["type"] is one of these two first."""
    if q["type"] == "numeric":
        return grade_numeric(answer_text, q["expected_value"], q["expected_unit"], retrieved)
    return grade_comparison(answer_text, q["expected"], retrieved)


def _grade(
    q: dict, answer_text: str, citation_warnings: list[str], retrieved: list[dict], judge_backend: str = "ollama"
) -> tuple[bool, str]:
    """Dispatches to the right grading strategy for question type
    q["type"], kept separate from run_eval()'s live agent loop so it's
    testable without network/Ollama calls (same rationale as
    _select_questions() above).

    Numeric/comparison questions short-circuit to FAIL when the agent
    hard-gate-refused (non-empty citation_warnings) instead of calling
    grade_numeric()/grade_comparison() on the refusal text -- a refusal
    message necessarily repeats the claimed value it's rejecting, which
    a plain text scan could otherwise match as if it were a real,
    verified answer. See
    docs/decisions/2026-08-26-week7-citation-hard-gate-ollama-retry.md.
    Judged questions are deliberately NOT short-circuited here: some are
    written to expect a refusal, and grade_judged() already evaluates
    the actual answer text against its own criteria, which is the
    correct way to check whether refusing was the right call.

    `judge_backend` is passed straight through to grade_judged() -- see
    run_eval()'s docstring for why it isn't just reused from `backend`."""
    if citation_warnings and q["type"] in ("numeric", "comparison"):
        return False, "agent refused to answer (hard-gated on unverified citation(s)) -- no value to grade"
    if q["type"] in ("numeric", "comparison"):
        return _grade_by_type(q, answer_text, retrieved)
    if q["type"] == "judged":
        return grade_judged(q["question"], answer_text, q["criteria"], judge_backend)
    raise ValueError(f"Unknown question type: {q['type']!r} in question {q['id']!r}")


def _empty_citation_gate_evidence() -> dict:
    """A fresh dict on every call -- deliberately NOT a module-level
    constant. `citation_warning_details` is a list; a shared constant
    would hand every row in a batch the SAME list object via a shallow
    `dict(...)`/`**` copy -- harmless today since nothing mutates it in
    place, but a silent corrupt-every-other-row trap waiting for the
    next edit that does. See
    docs/decisions/2026-09-10-citation-gate-measurement-instrumentation.md."""
    return {
        "withheld_answer": None,
        "gate_withheld_would_have_passed": None,
        "gate_withheld_detail": None,
        "citation_warning_details": [],
    }


def _citation_gate_evidence(
    q: dict, retrieved: list[dict], withheld_answer: str | None, citation_warning_details: list[dict]
) -> dict:
    """The 4 additive report fields the citation-gate FP/FN measurement
    work needs. `_grade()`'s own short-circuit still scores a hard-gated
    numeric/comparison question as FAIL -- that user-facing verdict is
    untouched here. This is purely additional evidence: what the model
    actually said before the hard gate withheld it, and whether that
    text would have passed the existing grader if the gate hadn't fired.

    Only populated when the gate actually refused a numeric/comparison
    question -- a judged question has no ground-truth number to re-grade
    against, and a passing row has nothing withheld to re-grade in the
    first place. `gate_withheld_would_have_passed` re-runs the SAME
    grade_numeric()/grade_comparison() (via _grade_by_type(), shared with
    _grade()'s real verdict) the real verdict would have used.

    `citation_warning_details` is passed straight through from
    `AgentResult.citation_warning_details` (the caller already has it)
    rather than re-derived by calling collect_citation_warnings() a
    second time -- that re-derivation can't see a structured-path
    (quote_not_found/value_not_in_quote/etc.) refusal at all, since those
    only ever come from verify_claims(). Passing the real field through
    keeps analyze_citation_gate.py's false_positive_by_check breakdown
    accurate for both checkers. See
    docs/decisions/2026-09-10-citation-gate-measurement-instrumentation.md."""
    if withheld_answer is None or q["type"] not in ("numeric", "comparison"):
        return _empty_citation_gate_evidence()

    would_pass, would_detail = _grade_by_type(q, withheld_answer, retrieved)

    return {
        "withheld_answer": withheld_answer,
        "gate_withheld_would_have_passed": would_pass,
        "gate_withheld_detail": would_detail,
        "citation_warning_details": citation_warning_details,
    }


def run_eval(
    questions_path: Path,
    ids: list[str] | None = None,
    include_skipped: bool = False,
    backend: str | None = None,
    judge_backend: str | None = None,
) -> list[dict]:
    """`backend=None` resolves to config.DEFAULT_BACKEND, resolved HERE
    rather than via a literal `= DEFAULT_BACKEND` parameter default -- a
    parameter default is bound once at module-import time and would
    silently freeze in whatever DEFAULT_BACKEND was at that moment,
    ignoring any later change (same reasoning as agent.run_agent()'s
    matching fix).

    `judge_backend` then defaults to `backend` itself, NOT
    config.DEFAULT_BACKEND directly: --backend ollama is the no-API-key
    path this project deliberately keeps runnable, and defaulting the
    judge to DEFAULT_BACKEND instead would make it silently require a
    Gemini key for every judged question even when the caller explicitly
    asked for the no-key backend. --judge-backend still overrides this
    either way, e.g. to grade a Gemini run's judged questions with Ollama
    as a cross-model check. See
    docs/decisions/2026-09-10-citation-gate-measurement-instrumentation.md."""
    backend = backend or DEFAULT_BACKEND
    judge_backend = judge_backend or backend
    questions = load_questions(questions_path)
    questions = _select_questions(questions, ids, include_skipped)
    results = []

    for q in questions:
        print(f"[{q['id']}] {q['question']}")
        try:
            result = run_agent(q["question"], backend=backend)
            answer_text, retrieved, citation_warnings = result.answer, result.results, result.citation_warnings
            # Excludes hard-gated refusals: agent.py's _format_refusal_message()
            # echoes each warning's own "[n] claims ..." text verbatim, which
            # still matches CITATION_PATTERN, so a refusal would otherwise get
            # has_citation=True -- a real answer's citation and a refusal's
            # description of a FAILED citation shouldn't count the same way in
            # this stat. See
            # docs/decisions/2026-08-26-week7-citation-hard-gate-ollama-retry.md.
            has_citation = not citation_warnings and bool(CITATION_PATTERN.search(answer_text))

            passed, detail = _grade(q, answer_text, citation_warnings, retrieved, judge_backend)
            gate_fields = _citation_gate_evidence(
                q, retrieved, result.withheld_answer, result.citation_warning_details
            )
        except Exception as e:
            # Broad on purpose: a network error, exhausted retries, or an
            # unexpected bug in run_agent()/_grade() should all fail just
            # THIS question the same way, not silently discard every
            # already-graded result in the batch before it (no partial
            # report, no flush) -- this is a boundary where many
            # different failure types should all degrade identically.
            # See docs/decisions/2026-09-06-full-codebase-review.md.
            print(f"  -> ERROR: {type(e).__name__}: {e}")
            results.append(
                {
                    "id": q["id"],
                    "ticker": q.get("ticker") or q.get("tickers"),
                    "question": q["question"],
                    "type": q["type"],
                    "passed": False,
                    "detail": f"{type(e).__name__}: {e}",
                    "has_citation": False,
                    "citation_warnings": [],
                    "answer": None,
                    "n_chunks_retrieved": 0,
                    **_empty_citation_gate_evidence(),
                }
            )
            continue

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
                **gate_fields,
            }
        )

    flush()
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


def _model_name_for(backend: str) -> str:
    return OLLAMA_MODEL_NAME if backend == "ollama" else GEMINI_MODEL_NAME


def save_report(results: list[dict], backend: str, judge_backend: str | None = None) -> Path:
    """`backend` ("ollama"/"gemini") alone doesn't say which specific
    model answered -- OLLAMA_MODEL_NAME/GEMINI_MODEL_NAME are both
    configurable via .env and can change over time, which would make an
    old report ambiguous about what actually produced it. `answer_model`
    records whichever one actually ran; `judge_model` records whichever
    backend actually judged -- `judge_backend` defaults to `backend`
    itself, same reasoning as run_eval()'s own default (see that
    function's docstring)."""
    judge_backend = judge_backend or backend
    RESULTS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = RESULTS_DIR / f"{timestamp}.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "backend": backend,
                "answer_model": _model_name_for(backend),
                "judge_model": _model_name_for(judge_backend),
                "results": results,
            },
            f,
            indent=2,
        )
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
    parser.add_argument(
        "--judge-backend",
        choices=list(BACKENDS),
        default=None,
        help="which LLM backend grades judged-type questions (default: same as --backend)",
    )
    args = parser.parse_args()

    ids = [i.strip() for i in args.ids.split(",")] if args.ids else None
    results = run_eval(
        args.questions,
        ids=ids,
        include_skipped=args.include_skipped,
        backend=args.backend,
        judge_backend=args.judge_backend,
    )
    print_summary(results)
    out_path = save_report(results, backend=args.backend, judge_backend=args.judge_backend)
    print(f"\nFull report saved to {out_path}")
    # A print, not an import -- analyze_citation_gate.py stays a
    # standalone reader of the report file, not coupled to this module.
    print(f"Citation-gate FP/FN breakdown: python analyze_citation_gate.py {out_path}")


if __name__ == "__main__":
    main()
