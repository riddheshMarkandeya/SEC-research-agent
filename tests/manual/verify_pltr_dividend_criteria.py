"""
Live verification of the pltr-dividend-2019-refusal judge criteria: grades
stored answers and hand-written controls with the real Gemini judge, which
no unit test can do.

Cases, all graded under the current criteria (eval/eval_questions.jsonl):
  1. positive sample: correct stored answers across every wording form,
     both judge models' eras, expected PASS;
  2. stability: the latest stored answer graded 5x, expected 5/5 PASS;
  3. negative controls: two made-up nonzero dividends (1x each), a stored
     gate-refusal text and a stored budget-exhausted text (3x each),
     expected FAIL;
  4. an EPS control (no dividend, plus an EPS figure), expected PASS.
Then, unless --skip-old, the positive sample again under the old criteria
(read from OLD_REV), to show the delta on the same judge on the same day.
The old-criteria pass is a diagnostic and never fails the run.

grade_judged injects today's date as "now"; harmless for a 2019 question.

About 45 judge calls with the old pass, about 30 without (--skip-old).
Exits 1 on any unexpected verdict in cases 1-4.

Usage (from the repo root):
    python tests/manual/verify_pltr_dividend_criteria.py [--skip-old]
"""

import argparse
import json
import subprocess
import sys

from sec_agent import config
from sec_agent.eval.eval_harness import grade_judged, load_questions

QID = "pltr-dividend-2019-refusal"
# The last commit with the old criteria.
OLD_REV = "3edc8be"
RESULTS_DIR = config.PROJECT_ROOT / "eval" / "eval_results"

# One report per wording form, picked by hand from the deduped stored answers.
SAMPLE_REPORTS = [
    "20260821T023051Z",  # "did not declare any dividends in 2019"
    "20260821T025213Z",  # "dividend per share in 2019 was $0"
    "20260825T044611Z",  # "did not find any specific mention ... no record"
    "20260825T195207Z",  # no dividends, mentions EPS data
    "20260907T004456Z",  # "the financial statements ... do not contain this information"
    "20260910T212525Z",  # "filings do not provide a specific dividend per share figure"
    "20260912T225536Z",  # "did not declare or pay any dividends ... in 2019"
    "20260914T233319Z",  # "did not have a dividend per share in 2019 because ... never"
    "20260916T024339Z",  # "never declared or paid any cash dividends" (graded FAIL 5 of 6)
    "20260918T194825Z",  # same as 20260914T233319Z, different citation
    "20260919T003333Z",  # "was a private company in 2019"
    "20260921T222521Z",  # "never declared or paid cash dividends"
    "20260922T062823Z",  # never, and "no dividends were declared or paid in 2019"
    "20260929T204453Z",  # "did not pay a dividend per share in 2019"
    "20261003T030904Z",  # "did not ... in 2019 and has never ..."
]
STABILITY_REPORT = "20261006T073606Z"
GATE_REFUSAL_REPORT = "20260911T073808Z"
BUDGET_EXHAUSTED_REPORT = "20260817T232126Z"

NONZERO_DIVIDENDS = [
    "Palantir paid a dividend of $0.25 per share in 2019 [1].",
    "Palantir's 2019 dividend per share was about $0.10 [2].",
]
EPS_CONTROL = "Palantir paid no dividends in 2019 [1]; its 2019 net loss per share was $(1.02) [2]."


def _stored_answer(report: str) -> str:
    data = json.loads((RESULTS_DIR / f"{report}.json").read_text(encoding="utf-8"))
    # Early reports are a bare list of results; later ones wrap it with metadata.
    results = data if isinstance(data, list) else data["results"]
    answer = next(r["answer"] for r in results if r["id"] == QID)
    if answer is None:
        raise ValueError(f"{report}: stored answer is None")
    return answer


def _question_and_criteria(questions_text: str) -> tuple[str, str]:
    for line in questions_text.splitlines():
        if line.strip():
            q = json.loads(line)
            if q["id"] == QID:
                return q["question"], q["criteria"]
    raise KeyError(QID)


def _old_criteria() -> str:
    text = subprocess.run(
        ["git", "show", f"{OLD_REV}:eval/eval_questions.jsonl"],
        capture_output=True, text=True, encoding="utf-8", check=True, cwd=config.PROJECT_ROOT,
    ).stdout
    return _question_and_criteria(text)[1]


def _grade(label: str, question: str, answer: str, criteria: str, expect_pass: bool | None) -> bool:
    """Prints one line; returns whether the verdict matched (always True
    when expect_pass is None, i.e. diagnostic only)."""
    passed, reason = grade_judged(question, answer, criteria)
    got = "PASS" if passed else "FAIL"
    expected = "-" if expect_pass is None else ("PASS" if expect_pass else "FAIL")
    ok = expect_pass is None or passed == expect_pass
    mark = "" if ok else "  <-- UNEXPECTED"
    print(f"{label:<34} expected={expected:<4} got={got}{mark}\n    {reason[:200]}", flush=True)
    return ok


def _new_criteria_cases() -> list[tuple[str, str, bool]]:
    cases = [(f"sample {r}", _stored_answer(r), True) for r in SAMPLE_REPORTS]
    cases += [(f"stability {STABILITY_REPORT} #{i + 1}", _stored_answer(STABILITY_REPORT), True) for i in range(5)]
    cases += [(f"nonzero dividend {i + 1}", text, False) for i, text in enumerate(NONZERO_DIVIDENDS)]
    for report, name in ((GATE_REFUSAL_REPORT, "gate refusal"), (BUDGET_EXHAUSTED_REPORT, "budget exhausted")):
        cases += [(f"{name} #{i + 1}", _stored_answer(report), False) for i in range(3)]
    cases.append(("EPS control", EPS_CONTROL, True))
    return cases


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-old", action="store_true", help="skip the old-criteria diagnostic pass")
    args = parser.parse_args()

    questions = [q for q in load_questions(config.QUESTIONS_PATH) if q["id"] == QID]
    question, new_criteria = questions[0]["question"], questions[0]["criteria"]
    print(f"judge model: {config.GEMINI_MODEL_NAME}\n\n== current criteria ==", flush=True)
    results = [_grade(label, question, answer, new_criteria, expect) for label, answer, expect in _new_criteria_cases()]
    failures = results.count(False)
    print(f"\ncurrent criteria: {len(results) - failures}/{len(results)} as expected", flush=True)

    if not args.skip_old:
        old_criteria = _old_criteria()
        print(f"\n== old criteria ({OLD_REV}), diagnostic ==", flush=True)
        old_passes = 0
        for report in SAMPLE_REPORTS:
            passed, _ = grade_judged(question, _stored_answer(report), old_criteria)
            old_passes += passed
            print(f"sample {report:<27} got={'PASS' if passed else 'FAIL'}", flush=True)
        print(f"\nold criteria: {old_passes}/{len(SAMPLE_REPORTS)} PASS on the positive sample", flush=True)

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
