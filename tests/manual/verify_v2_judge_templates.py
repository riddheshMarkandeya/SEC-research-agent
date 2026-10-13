"""
Live verification of the v2 judge templates (the 4 refusal kinds and
clarify) on batch 1's own questions: grades hand-written answers with the
real Gemini judge, which no unit test can do.

Per template, one question from eval/eval_questions_v2.jsonl and:
  - a known-good answer, expected PASS;
  - for not_covered, not_yet_filed and never_disclosed, a refusal giving
    another kind's reason, expected FAIL;
  - for not_covered, a terse good refusal and two good ones on the
    period-not-covered question (v2-cat-backlog-2020), one saying its
    2020 data has no backlog figure, expected PASS;
  - for not_yet_filed, a good refusal citing no filing (PASS) and the
    latest 10-Q's figure given as the unreported period's (FAIL);
  - for false_premise, an answer that accepts the premise, expected FAIL
    (that template has no wrong-reason clause);
  - for clarify, an answer asking which reading is meant and one giving
    every reading labelled (both PASS), and one giving a single reading
    unlabelled and one giving a single reading over two years (both FAIL);
  - on every refusal template, two negative controls, expected FAIL: the
    agent's canned citation-gate refusal and its turns-exhausted text,
    read from stored v1 reports.
The look-alike question (a false_premise refusal with its own criteria)
gets a good case and a case reporting the other bank's figure.
Answers use the agent's `[n]` citation markers.

Each case runs twice (stability) unless RUNS overrides it; the run
prints the planned judge-call count. grade_judged injects
today's date as "now", which the future-period cases rely on.
Exits 1 on any unexpected verdict, printing the judge's reason.

Usage (from a worktree, PYTHONPATH=src so the worktree's code runs):
    python tests/manual/verify_v2_judge_templates.py
"""

import sys

from sec_agent import config
from sec_agent.eval.eval_harness import grade_judged, load_questions, load_report
from sec_agent.eval.grading import judge_criteria_for

V2_QUESTIONS = config.PROJECT_ROOT / "eval" / "eval_questions_v2.jsonl"
DEFAULT_RUNS = 2
# 10 runs for cases a judge once misjudged: at a 20% true error rate, 10
# clean runs happen about 11% of the time. 5 for the negatives that the
# looser template sentences could turn into a false PASS.
RUNS = {
    ("v2-cost-net-sales-fy2025", "gate refusal"): 10,
    ("v2-wmt-revenue-fy2029", "good"): 10,
    ("v2-tgt-margin-fy2025", "every reading labelled"): 10,
    ("v2-wmt-revenue-fy2029", "gate refusal"): 5,
    ("v2-wmt-revenue-fy2029", "turns exhausted"): 5,
    ("v2-xom-breakeven-price", "gate refusal"): 5,
    ("v2-xom-breakeven-price", "turns exhausted"): 5,
    ("v2-cost-net-sales-fy2025", "turns exhausted"): 5,
    ("v2-wmt-revenue-fy2029", "latest 10-Q figure as the answer"): 5,
    ("v2-tgt-margin-fy2025", "one reading unlabelled"): 5,
    ("v2-cost-net-sales-fy2025", "good, terse"): 5,
    ("v2-cat-backlog-2020", "good (period not covered)"): 5,
    ("v2-cat-backlog-2020", "good (2020 data, no backlog)"): 5,
    ("v2-wmt-revenue-fy2029", "good, no filing cited"): 5,
    ("v2-tgt-margin-fy2025", "one reading over two years"): 5,
}

# Stored v1 answers holding the agent's canned texts verbatim.
CONTROL_QID = "pltr-dividend-2019-refusal"
GATE_REFUSAL_REPORT = "20260911T073808Z"
TURNS_EXHAUSTED_REPORT = "20260817T232126Z"

# (question id, label, answer, expected PASS)
CASES = [
    ("v2-cost-net-sales-fy2025", "good", (
        "I can't answer this from my sources. Costco is not one of the companies whose SEC filings I have "
        "access to; my filings cover Apple, Microsoft, NVIDIA, Salesforce, Palantir, JPMorgan Chase, Bank of "
        "America, Target, Walmart, Exxon Mobil, Johnson & Johnson and Caterpillar."
    ), True),
    ("v2-cost-net-sales-fy2025", "good, terse", (
        "None of the filings available to me cover Costco, so I can't give that figure."
    ), True),
    ("v2-cat-backlog-2020", "good (period not covered)", (
        "I can't give Caterpillar's backlog at the end of 2020: the Caterpillar filings available to me start "
        "in 2024 [1], so that period isn't covered by my sources."
    ), True),
    # The fact tool does reach 2020 (v2-cat-operating-profit-2020), so an
    # answer saying so must still pass.
    ("v2-cat-backlog-2020", "good (2020 data, no backlog)", (
        "Caterpillar's structured financial data reaches back to 2020 [1], but it has no order backlog "
        "figure, and the Caterpillar filings available to me start in 2024, so I can't give the backlog at "
        "the end of 2020."
    ), True),
    ("v2-cost-net-sales-fy2025", "wrong reason (never disclosed)", (
        "Costco's filings do not disclose a net sales figure for fiscal 2025, so I can't give one."
    ), False),
    ("v2-wmt-revenue-fy2029", "good", (
        "Walmart's fiscal 2029 hasn't been reported yet: it ends January 31, 2029, and no 10-K or 10-Q covers "
        "it. The most recent filing I have is the 10-Q for the quarter ended July 31, 2026 [1], so I can't "
        "give total revenues for fiscal 2029."
    ), True),
    ("v2-wmt-revenue-fy2029", "good, no filing cited", (
        "Walmart's fiscal 2029 hasn't been reported yet, so no filing covers it and I can't give its total "
        "revenues."
    ), True),
    ("v2-wmt-revenue-fy2029", "wrong reason (not covered)", (
        "Walmart is not one of the companies covered by the filings available to me, so I can't answer."
    ), False),
    # Made-up figure: tests that citing the latest filing doesn't excuse
    # passing its figure off as the unreported period's.
    ("v2-wmt-revenue-fy2029", "latest 10-Q figure as the answer", (
        "Walmart's fiscal 2029 total revenues were $179.4 billion, per its latest 10-Q for the quarter ended "
        "July 31, 2026 [1]."
    ), False),
    ("v2-xom-breakeven-price", "good", (
        "Exxon Mobil's filings don't disclose a breakeven oil price. Its 10-K and 10-Qs discuss realized "
        "prices and earnings drivers [1], but none states the oil price the company needs to break even, "
        "so I can't give that figure."
    ), True),
    ("v2-xom-breakeven-price", "wrong reason (period not covered)", (
        "The period you're asking about isn't covered by the Exxon Mobil filings available to me, so I "
        "can't give a breakeven price."
    ), False),
    ("v2-cat-dividend-cut-2025", "good", (
        "The premise is incorrect: Caterpillar did not cut its dividend in June 2025. In June 2025 its Board "
        "of Directors approved a seven percent increase in the quarterly dividend to $1.51 per share [1]."
    ), True),
    ("v2-cat-dividend-cut-2025", "accepts the premise", (
        "Caterpillar cut its quarterly dividend in June 2025 mainly because higher tariffs raised its "
        "manufacturing costs and squeezed profit [1], so the Board chose to preserve cash for operations."
    ), False),
    ("v2-jpm-gwim-net-income-2025", "good", (
        "JPMorgan Chase doesn't have a Global Wealth & Investment Management segment; that is Bank of "
        "America's segment name. JPMorgan Chase's wealth business is reported as Asset & Wealth Management, "
        "whose 2025 net income was $6,522 million [1]."
    ), True),
    ("v2-jpm-gwim-net-income-2025", "other bank's figure", (
        "JPMorgan Chase's Global Wealth & Investment Management segment reported net income of $4,670 "
        "million in 2025 [1], up 10% from $4,263 million in 2024."
    ), False),
    ("v2-tgt-margin-fy2025", "asks which reading", (
        "Do you mean Target's gross margin rate or its operating income margin rate for fiscal 2025? Both "
        "are reported as a percent of net sales [1], and they differ a lot, so let me know which one you need."
    ), True),
    ("v2-tgt-margin-fy2025", "every reading labelled", (
        "\"Margin\" could mean two things for Target in fiscal 2025: its gross margin rate was 27.9% [1], "
        "and its operating income margin rate was 4.9% [1]."
    ), True),
    ("v2-tgt-margin-fy2025", "one reading unlabelled", (
        "Target's margin in fiscal 2025 was 27.9% [1]."
    ), False),
    # Two figures in the labelling pattern, but both one reading.
    ("v2-tgt-margin-fy2025", "one reading over two years", (
        "Target's gross margin rate was 27.9% in fiscal 2025 [1] and its gross margin rate was 28.2% in "
        "fiscal 2024 [1]."
    ), False),
]
# Which template each question must still use, or its cases test the
# wrong thing.
QUESTION_KINDS = {
    "v2-cost-net-sales-fy2025": "not_covered",
    "v2-cat-backlog-2020": "not_covered",
    "v2-wmt-revenue-fy2029": "not_yet_filed",
    "v2-xom-breakeven-price": "never_disclosed",
    "v2-cat-dividend-cut-2025": "false_premise",
    "v2-jpm-gwim-net-income-2025": "false_premise",
    "v2-tgt-margin-fy2025": "clarify",
}
REFUSAL_TEMPLATE_QIDS = [
    "v2-cost-net-sales-fy2025", "v2-cat-backlog-2020", "v2-wmt-revenue-fy2029", "v2-xom-breakeven-price",
    "v2-cat-dividend-cut-2025",
]


def _stored_answer(report: str) -> str:
    results = load_report(config.RESULTS_DIR / f"{report}.json")["results"]
    row = next((r for r in results if r["id"] == CONTROL_QID), None)
    if row is None or row["answer"] is None:
        raise ValueError(f"{report}: no stored answer for {CONTROL_QID}")
    return row["answer"]


def _all_cases() -> list[tuple[str, str, str, bool]]:
    controls = [("gate refusal", _stored_answer(GATE_REFUSAL_REPORT)),
                ("turns exhausted", _stored_answer(TURNS_EXHAUSTED_REPORT))]
    return CASES + [(qid, label, text, False) for qid in REFUSAL_TEMPLATE_QIDS for label, text in controls]


def main() -> int:
    questions = {q["id"]: q for q in load_questions(V2_QUESTIONS)}
    cases = _all_cases()
    unknown = set(RUNS) - {(qid, label) for qid, label, _, _ in cases}
    if unknown:
        raise ValueError(f"RUNS names cases that don't exist: {sorted(unknown)}")
    # Checked before any judge call, so a renamed or re-kinded question
    # stops the run instead of failing partway or testing the wrong template.
    for qid in {qid for qid, _, _, _ in cases}:
        q = questions.get(qid)
        kind = q.get("refusal_kind", q["type"]) if q else None
        if kind != QUESTION_KINDS.get(qid):
            raise ValueError(f"{qid}: kind is {kind}, cases expect {QUESTION_KINDS.get(qid)}")
    planned = sum(RUNS.get((qid, label), DEFAULT_RUNS) for qid, label, _, _ in cases)
    print(f"judge model: {config.GEMINI_MODEL_NAME}, {planned} judge calls\n", flush=True)
    failures = total = 0
    for qid, label, answer, expect_pass in cases:
        q = questions[qid]
        kind = q.get("refusal_kind", q["type"])
        for run in range(1, RUNS.get((qid, label), DEFAULT_RUNS) + 1):
            passed, reason = grade_judged(q["question"], answer, judge_criteria_for(q))
            total += 1
            ok = passed == expect_pass
            failures += not ok
            mark = "" if ok else "  <-- UNEXPECTED"
            print(f"{kind:<16} {qid:<30} {label:<32} #{run} expected={'PASS' if expect_pass else 'FAIL':<4} "
                  f"got={'PASS' if passed else 'FAIL'}{mark}", flush=True)
            if not ok:
                print(f"    {reason}", flush=True)
    print(f"\n{total - failures}/{total} as expected", flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
