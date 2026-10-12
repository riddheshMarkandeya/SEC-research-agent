"""
Unit tests for eval_harness.py. Covers the deterministic grading logic
(grade_numeric, grade_comparison, load_questions) plus grade_judged's
response-PARSING logic with a mocked LLM call — the call itself isn't
made, only the "split PASS/FAIL + reason out of the model's reply" logic
is exercised. run_eval()'s end-to-end behavior (live retrieval + live
LLM calls) is exercised by manual runs (python -m sec_agent.eval.eval_harness) instead,
not here.

extract_numbers()/normalize() moved to numeric_utils.py (shared with
agent.py's citation checks) — see tests/verification/test_numeric_utils.py.
"""

import ast
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from sec_agent.devtools import compare_prompt_versions
from sec_agent.eval import eval_harness
from sec_agent.llm import llm_backends
from sec_agent.agent.submission import AgentResult
from sec_agent.prompts.judge_criteria import REFUSAL_CRITERIA
from sec_agent.eval.eval_harness import (
    _grade,
    _grade_by_type,
    _run_one,
    _select_questions,
    grade_comparison,
    grade_judged,
    grade_numeric,
    load_questions,
    run_eval,
    save_report,
)


def _answered(text: str, citation_warnings: list[str] | None = None) -> AgentResult:
    """An agent result for _grade: `text`, with no retrieved results or claims."""
    return AgentResult(text, [], citation_warnings or [], None, [], [])


# ---------------------------------------------------------------------------
# grade_numeric
# ---------------------------------------------------------------------------
def test_grade_numeric_passes_on_matching_value():
    passed, _ = grade_numeric("Total RPO was approximately $72.4 billion.", 72.4, "billion")
    assert passed is True


def test_grade_numeric_fails_on_wrong_value():
    passed, _ = grade_numeric("Total RPO was approximately $50 billion.", 72.4, "billion")
    assert passed is False


def test_grade_numeric_fails_when_unit_category_differs_even_if_number_matches():
    # 72.4% and $72.4 billion must never be confused just because "72.4"
    # appears in both — this is the regression test for the category-
    # safety design in numeric_utils.normalize().
    passed, _ = grade_numeric("The rate was 72.4%.", 72.4, "billion")
    assert passed is False


def test_grade_numeric_within_tolerance_passes():
    # expected=100 raw -> tolerance = max(1% of 100, 0.05) = 1.0
    passed, _ = grade_numeric("The figure was 100.9.", 100, "raw")
    assert passed is True


def test_grade_numeric_outside_tolerance_fails():
    passed, _ = grade_numeric("The figure was 102.", 100, "raw")
    assert passed is False


def test_grade_numeric_skips_citation_check_when_all_results_not_given():
    # Backward compatible: existing callers that don't pass all_results
    # (including every test above) keep the old pure-text-match
    # behavior -- no citation markers to check against anyway.
    passed, _ = grade_numeric("Total RPO was approximately $72.4 billion.", 72.4, "billion")
    assert passed is True


def test_grade_numeric_fails_when_matched_values_only_citation_is_unverified():
    # The real, live-found bug this closes: aapl-employees-fy25 "passes"
    # today because 166,000 appears in the answer text, even though its
    # citation actually points at a chunk about debt notes and share
    # repurchases -- nothing to do with employee count.
    results = [{"text": "Future principal payments for the Company's Notes..."}]
    answer = "Apple had approximately 166,000 full-time equivalent employees [1]."
    passed, detail = grade_numeric(answer, 166000, "raw", all_results=results)
    assert passed is False
    assert "citation" in detail.lower()


def test_grade_numeric_passes_when_matched_values_citation_is_verified():
    results = [{"text": "employees = 166000 raw"}]
    answer = "Apple had approximately 166,000 full-time equivalent employees [1]."
    passed, _ = grade_numeric(answer, 166000, "raw", all_results=results)
    assert passed is True


# ---------------------------------------------------------------------------
# grade_comparison
# ---------------------------------------------------------------------------
_TAX_RATE_COMPARISON = [
    {"ticker": "AAPL", "expected_value": 17.9, "expected_unit": "percent"},
    {"ticker": "MSFT", "expected_value": 20, "expected_unit": "percent"},
]


def test_grade_comparison_passes_when_all_entities_found():
    answer = "Apple's effective tax rate was 17.9%, while Microsoft's was 20%."
    passed, _ = grade_comparison(answer, _TAX_RATE_COMPARISON)
    assert passed is True


def test_grade_comparison_fails_when_one_entity_dropped():
    # This is the literal regression case: agent.py once produced an
    # answer covering only Microsoft's figure and silently dropped
    # Apple's, despite having retrieved both.
    answer = "Microsoft's effective tax rate was 20%, driven by foreign earnings taxed at lower rates."
    passed, detail = grade_comparison(answer, _TAX_RATE_COMPARISON)
    assert passed is False
    assert "AAPL" in detail
    assert "MSFT" not in detail


def test_grade_comparison_fails_when_both_entities_missing():
    answer = "I don't have enough information to answer this comparison."
    passed, detail = grade_comparison(answer, _TAX_RATE_COMPARISON)
    assert passed is False
    assert "AAPL" in detail and "MSFT" in detail


def test_grade_comparison_skips_citation_check_when_all_results_not_given():
    answer = "Apple's effective tax rate was 17.9%, while Microsoft's was 20%."
    passed, _ = grade_comparison(answer, _TAX_RATE_COMPARISON)
    assert passed is True


def test_grade_comparison_fails_when_one_entitys_citation_is_unverified():
    results = [{"text": "AAPL tax rate = 17.9 percent"}, {"text": "unrelated MSFT text"}]
    answer = "Apple's effective tax rate was 17.9% [1], while Microsoft's was 20% [2]."
    passed, detail = grade_comparison(answer, _TAX_RATE_COMPARISON, all_results=results)
    assert passed is False
    assert "MSFT" in detail


def test_grade_comparison_passes_when_all_entities_citations_verified():
    results = [{"text": "AAPL tax rate = 17.9 percent"}, {"text": "MSFT tax rate = 20 percent"}]
    answer = "Apple's effective tax rate was 17.9% [1], while Microsoft's was 20% [2]."
    passed, _ = grade_comparison(answer, _TAX_RATE_COMPARISON, all_results=results)
    assert passed is True


# ---------------------------------------------------------------------------
# load_questions
# ---------------------------------------------------------------------------
def test_load_questions_parses_jsonl_and_skips_blank_lines(tmp_path):
    path = tmp_path / "questions.jsonl"
    path.write_text(
        '{"id": "q1", "ticker": "AAPL", "question": "A?", "type": "judged", "criteria": "c"}\n'
        "\n"
        '{"id": "q2", "ticker": "AAPL", "question": "B?", "type": "judged", "criteria": "c"}\n',
        encoding="utf-8",
    )
    questions = load_questions(path)
    assert [q["id"] for q in questions] == ["q1", "q2"]


# ---------------------------------------------------------------------------
# _select_questions -- --ids / skip-flag filtering, kept separate from
# run_eval()'s live agent loop so it's testable without network/LLM calls
# ---------------------------------------------------------------------------
def _q(id_, skip=None):
    q = {"id": id_, "question": f"{id_}?"}
    if skip is not None:
        q["skip"] = skip
    return q


def test_select_questions_with_no_ids_and_no_skip_flags_returns_everything():
    questions = [_q("a"), _q("b"), _q("c")]
    assert _select_questions(questions, ids=None, include_skipped=False) == questions


def test_select_questions_excludes_skip_flagged_by_default():
    questions = [_q("a"), _q("b", skip=True), _q("c")]
    result = _select_questions(questions, ids=None, include_skipped=False)
    assert [q["id"] for q in result] == ["a", "c"]


def test_select_questions_include_skipped_forces_skip_flagged_back_in():
    questions = [_q("a"), _q("b", skip=True), _q("c")]
    result = _select_questions(questions, ids=None, include_skipped=True)
    assert [q["id"] for q in result] == ["a", "b", "c"]


def test_select_questions_with_ids_returns_only_those_in_file_order():
    questions = [_q("a"), _q("b"), _q("c")]
    # Requested out of order -- result should still follow file order,
    # not the order given in --ids.
    result = _select_questions(questions, ids=["c", "a"], include_skipped=False)
    assert [q["id"] for q in result] == ["a", "c"]


def test_select_questions_with_ids_ignores_skip_flag():
    # Explicit --ids always wins over a question's own skip flag --
    # asking for a question by ID is a stronger signal than the file's
    # default.
    questions = [_q("a", skip=True)]
    result = _select_questions(questions, ids=["a"], include_skipped=False)
    assert [q["id"] for q in result] == ["a"]


def test_select_questions_with_unknown_id_raises():
    questions = [_q("a")]
    try:
        _select_questions(questions, ids=["a", "does-not-exist"], include_skipped=False)
        assert False, "expected ValueError"
    except ValueError as e:
        assert "does-not-exist" in str(e)


# ---------------------------------------------------------------------------
# _grade — dispatch + hard-gate short-circuit: a refusal's own warning
# text repeats the claimed number, which grade_numeric's plain text scan
# could otherwise match as a false PASS.
# ---------------------------------------------------------------------------
def test_grade_fails_numeric_question_when_agent_refused_even_if_value_is_in_refusal_text():
    # The refusal text contains the expected value as part of explaining
    # why the claim was rejected, which a naive grade_numeric() call
    # would still match.
    q = {"type": "numeric", "expected_value": 166000.0, "expected_unit": "raw"}
    refusal_text = (
        "I can't confirm this answer against the sources I retrieved -- "
        "the following claim(s) don't hold up under citation verification:\n"
        "- [1] claims 166000.0 (raw) but that value doesn't appear in the cited source"
    )
    warnings = ["[1] claims 166000.0 (raw) but that value doesn't appear in the cited source"]

    passed, detail = _grade(q, _answered(refusal_text, warnings))

    assert passed is False
    assert "refused" in detail.lower()


def test_grade_fails_comparison_question_when_agent_refused():
    q = {"type": "comparison", "expected": [{"ticker": "AAPL", "expected_value": 1.0, "expected_unit": "raw"}]}
    passed, detail = _grade(q, _answered("some refusal text", ["[1] claims ... doesn't appear"]))
    assert passed is False
    assert "refused" in detail.lower()


def test_grade_still_calls_grade_numeric_when_no_citation_warnings():
    q = {"type": "numeric", "expected_value": 72.4, "expected_unit": "billion"}
    passed, _ = _grade(q, _answered("Total RPO was approximately $72.4 billion."))
    assert passed is True


def test_grade_does_not_short_circuit_judged_questions_with_citation_warnings(monkeypatch):
    # Judged refusal-style questions (e.g. nvda-rd-expense-q4fy26-refusal)
    # expect a refusal as the CORRECT answer -- grade_judged must still
    # run and decide based on its own criteria, not be pre-empted.
    monkeypatch.setattr(
        "sec_agent.eval.eval_harness.complete",
        lambda backend, system_prompt, user_prompt, temperature=0.0: (
            "PASS\nCorrectly refused, no such data exists."
        ),
    )
    q = {
        "type": "judged",
        "question": "What was the R&D expense?",
        "criteria": "the answer should refuse, since no such figure exists",
    }
    passed, _ = _grade(q, _answered("I can't confirm this...", ["[1] claims ... doesn't appear"]))
    assert passed is True


def test_grade_raises_on_unknown_type():
    try:
        _grade({"type": "mystery", "id": "q1"}, _answered("answer"))
        assert False, "expected ValueError"
    except ValueError as e:
        assert "mystery" in str(e)


def test_grade_by_type_dispatches_comparison_questions_to_grade_comparison():
    # Every _grade test above exercises _grade_by_type only via its
    # "numeric" branch (or an invalid type, to hit the ValueError) --
    # "comparison" is never dispatched through this function directly,
    # even though grade_comparison() itself is separately well-tested.
    q = {"type": "comparison", "expected": _TAX_RATE_COMPARISON}
    answer = "Apple's effective tax rate was 17.9%, while Microsoft's was 20%."
    passed, _ = _grade_by_type(q, answer, None, [])
    assert passed is True


# ---------------------------------------------------------------------------
# grade_judged — mocked llm_backends.complete() (routes through this
# so --judge-backend can be honored).
# complete() itself still reuses each backend's existing retry/backoff/
# log_event machinery, rather than a raw requests.post that would bypass
# it entirely (see docs/decisions/2026-09-06-full-codebase-review.md,
# §3) -- these tests only cover the response-parsing logic and that
# grade_judged is wired up correctly.
# ---------------------------------------------------------------------------
def test_grade_judged_parses_pass(monkeypatch):
    monkeypatch.setattr(
        "sec_agent.eval.eval_harness.complete",
        lambda backend, system_prompt, user_prompt, temperature=0.0: "PASS\nThe answer clearly satisfies the criteria.",
    )
    passed, reason = grade_judged("Q?", "some answer", "some criteria")
    assert passed is True
    assert reason == "The answer clearly satisfies the criteria."


def test_grade_judged_parses_fail(monkeypatch):
    monkeypatch.setattr(
        "sec_agent.eval.eval_harness.complete",
        lambda backend, system_prompt, user_prompt, temperature=0.0: "FAIL\nThe answer does not mention the required risk.",
    )
    passed, reason = grade_judged("Q?", "some answer", "some criteria")
    assert passed is False
    assert reason == "The answer does not mention the required risk."


def test_grade_judged_lowercase_pass_still_counts(monkeypatch):
    monkeypatch.setattr("sec_agent.eval.eval_harness.complete", lambda backend, system_prompt, user_prompt, temperature=0.0: "pass\nfine.")
    passed, _ = grade_judged("Q?", "some answer", "some criteria")
    assert passed is True


def test_grade_judged_user_prompt_includes_todays_real_date(monkeypatch):
    # Regression anchor for the judge "hypothetical future date" false
    # refusal (docs/decisions/2026-09-17-fix-judge-hypothetical-date-bug.md)
    # -- without this grounding, a judge model trained before a filing's
    # real date reflexively calls a correctly-cited current filing
    # "hypothetical future data". Asserts an ISO-date-shaped string was
    # injected rather than re-deriving "today" via a second datetime.now()
    # call, which would race the one inside grade_judged() across a UTC
    # day boundary.
    captured = {}

    def fake_complete(backend, system_prompt, user_prompt, temperature=0.0):
        captured["system_prompt"] = system_prompt
        captured["user_prompt"] = user_prompt
        return "PASS\nfine."

    monkeypatch.setattr("sec_agent.eval.eval_harness.complete", fake_complete)
    grade_judged("Q?", "some answer", "some criteria")

    assert re.search(r"Today's real date is \d{4}-\d{2}-\d{2}", captured["user_prompt"])
    assert "training cutoff" in captured["system_prompt"]


def test_grade_judged_calls_complete_with_temperature_0(monkeypatch):
    # grade_judged wants stricter, more deterministic grading than
    # generation's default temperature 0.1, and never needs tool-calling
    # (complete() itself never passes tool_schemas -- see llm_backends.py).
    calls = []

    def fake_complete(backend, system_prompt, user_prompt, temperature=0.0):
        calls.append({"backend": backend, "temperature": temperature})
        return "PASS\nfine."

    monkeypatch.setattr("sec_agent.eval.eval_harness.complete", fake_complete)
    grade_judged("Q?", "some answer", "some criteria")
    assert calls[0]["temperature"] == 0.0


def test_grade_judged_routes_to_the_requested_backend(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "sec_agent.eval.eval_harness.complete",
        lambda backend, system_prompt, user_prompt, temperature=0.0: calls.append(backend) or "PASS\nfine.",
    )
    grade_judged("Q?", "some answer", "some criteria", backend="gemini")
    assert calls == ["gemini"]


def test_grade_judged_defaults_to_gemini_backend(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "sec_agent.eval.eval_harness.complete",
        lambda backend, system_prompt, user_prompt, temperature=0.0: calls.append(backend) or "PASS\nfine.",
    )
    grade_judged("Q?", "some answer", "some criteria")
    assert calls == ["gemini"]


# ---------------------------------------------------------------------------
# save_report — writes {"backend", "answer_model", "judge_model", "results"}
# ---------------------------------------------------------------------------
def test_save_report_writes_backend_and_results(monkeypatch, tmp_path):
    monkeypatch.setattr(eval_harness, "RESULTS_DIR", tmp_path)
    results = [{"id": "q1", "passed": True}]

    out_path = save_report(results, backend="gemini")

    with out_path.open(encoding="utf-8") as f:
        saved = json.load(f)
    assert saved["backend"] == "gemini"
    assert saved["results"] == results


def test_save_report_records_the_actual_answering_and_judging_model(monkeypatch, tmp_path):
    # The report must record which specific model actually answered and
    # judged, not just the generic "gemini" backend label --
    # GEMINI_MODEL_NAME is configurable via .env and can change over
    # time, so an old report would otherwise become ambiguous about what
    # really produced it.
    monkeypatch.setattr(eval_harness, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(eval_harness, "GEMINI_MODEL_NAME", "fake-gemini-model")

    with save_report([], backend="gemini").open(encoding="utf-8") as f:
        report = json.load(f)

    assert report["answer_model"] == "fake-gemini-model"
    assert report["judge_model"] == "fake-gemini-model"


@pytest.mark.parametrize("kwargs", [{"backend": "ollama"}, {"judge_backend": "ollama"}])
def test_run_eval_rejects_an_unknown_backend_before_any_question(monkeypatch, tmp_path, kwargs):
    # A stale backend name (e.g. a leftover DEFAULT_BACKEND in .env) must
    # stop the run up front: per question it would only be swallowed by
    # the per-question isolation below and saved as a normal-looking
    # all-failed report.
    questions_path = tmp_path / "questions.jsonl"
    questions_path.write_text(json.dumps(_numeric_question("q1")), encoding="utf-8")
    monkeypatch.setattr(eval_harness, "run_agent", lambda *a, **k: pytest.fail("run_agent was called"))

    with pytest.raises(ValueError, match="'ollama'.*gemini"):
        run_eval(load_questions(questions_path), **kwargs)


# ---------------------------------------------------------------------------
# run_eval — per-question exception isolation. run_eval()'s live agent
# loop is otherwise "live" (real retrieval/LLM calls, exercised by manual
# runs per this file's own top docstring), but once run_agent() is
# mocked, the loop's own control flow is pure/deterministic, so this one
# behavior gets a real unit test rather than only a manual check. See
# docs/decisions/2026-09-06-full-codebase-review.md.
# ---------------------------------------------------------------------------
def test_run_eval_isolates_one_questions_exception_from_the_rest(monkeypatch, tmp_path):
    # One question raising (e.g. run_agent() exhausting Gemini's
    # retries) must not kill the whole batch -- no partial report, no
    # flush -- discarding every already-graded result before it.
    questions_path = tmp_path / "questions.jsonl"
    questions_path.write_text(
        "\n".join(
            json.dumps(q)
            for q in [
                {"id": "q1", "ticker": "AAPL", "question": "Q1?", "type": "numeric", "expected_value": 1, "expected_unit": "raw"},
                {"id": "q2", "ticker": "AAPL", "question": "Q2?", "type": "numeric", "expected_value": 2, "expected_unit": "raw"},
                {"id": "q3", "ticker": "AAPL", "question": "Q3?", "type": "numeric", "expected_value": 3, "expected_unit": "raw"},
            ]
        ),
        encoding="utf-8",
    )

    def fake_run_agent(question, backend):
        if question == "Q2?":
            raise RuntimeError("Gemini exhausted retries")
        return AgentResult(f"The answer is {question[1]}.", [], [], None, [], [])

    monkeypatch.setattr(eval_harness, "run_agent", fake_run_agent)
    flush_calls = []
    monkeypatch.setattr(eval_harness, "flush", lambda: flush_calls.append(1))

    results = run_eval(load_questions(questions_path))

    assert [r["id"] for r in results] == ["q1", "q2", "q3"]
    assert results[0]["passed"] is True
    assert results[2]["passed"] is True
    assert results[1]["passed"] is False
    assert "RuntimeError" in results[1]["detail"]
    assert "Gemini exhausted retries" in results[1]["detail"]
    # Still flushes and returns a full (partial-failure) report rather
    # than losing everything to the one exception.
    assert flush_calls == [1]
    # The 4 gate-evidence fields must exist even on an exception row --
    # schema consistency matters here because analyze_citation_gate.py
    # reads every row in a report uniformly.
    for r in results:
        assert r["withheld_answer"] is None
        assert r["gate_withheld_would_have_passed"] is None
        assert r["gate_withheld_detail"] is None
        assert r["citation_warning_details"] == []


# ---------------------------------------------------------------------------
# run_eval -- citation-gate evidence fields (added for the FP/FN
# gate-measurement work, see
# docs/decisions/2026-09-10-citation-gate-measurement-instrumentation.md).
# _grade()'s short-circuit still scores a hard-gated numeric/comparison
# question as FAIL (unchanged, user-facing verdict) -- these fields are
# purely additive evidence for later analysis: what the model actually
# said before being refused, and whether that text would have passed the
# existing grader if the gate hadn't fired.
# ---------------------------------------------------------------------------
def _write_one_numeric_question(tmp_path, expected_value=100, expected_unit="raw"):
    questions_path = tmp_path / "questions.jsonl"
    questions_path.write_text(
        json.dumps(
            {
                "id": "q1",
                "ticker": "AAPL",
                "question": "Q1?",
                "type": "numeric",
                "expected_value": expected_value,
                "expected_unit": expected_unit,
            }
        ),
        encoding="utf-8",
    )
    return questions_path


def test_run_eval_records_gate_withheld_would_have_passed_true_for_a_correct_but_refused_answer(
    monkeypatch, tmp_path
):
    questions_path = _write_one_numeric_question(tmp_path)
    retrieved = [{"text": "value = 100 raw"}]

    def fake_run_agent(question, backend):
        return AgentResult(
            "I can't confirm this answer against the sources I retrieved...",
            retrieved,
            ["claims 100.0 (raw) but no citation marker appears anywhere near it to trace the claim to a source"],
            "The value was 100.",
            [
                {
                    "check": "uncited_claim",
                    "citation_index": None,
                    "value": 100.0,
                    "unit": "raw",
                    "message": "claims 100.0 (raw) but no citation marker appears anywhere near it to trace the claim to a source",
                }
            ],
            [],
        )

    monkeypatch.setattr(eval_harness, "run_agent", fake_run_agent)

    results = run_eval(load_questions(questions_path))

    assert results[0]["passed"] is False  # user-facing verdict unchanged -- still a hard-gated refusal
    assert results[0]["withheld_answer"] == "The value was 100."
    assert results[0]["gate_withheld_would_have_passed"] is True
    assert "100" in results[0]["gate_withheld_detail"]
    assert results[0]["citation_warning_details"][0]["check"] == "uncited_claim"


def test_run_eval_records_gate_withheld_would_have_passed_false_for_a_wrong_value(monkeypatch, tmp_path):
    questions_path = _write_one_numeric_question(tmp_path)
    retrieved = [{"text": "value = 100 raw"}]

    def fake_run_agent(question, backend):
        return AgentResult(
            "I can't confirm this answer against the sources I retrieved...",
            retrieved,
            ["claims 999.0 (raw) but no citation marker appears anywhere near it to trace the claim to a source"],
            "The value was 999.",
            [
                {
                    "check": "uncited_claim",
                    "citation_index": None,
                    "value": 999.0,
                    "unit": "raw",
                    "message": "claims 999.0 (raw) but no citation marker appears anywhere near it to trace the claim to a source",
                }
            ],
            [],
        )

    monkeypatch.setattr(eval_harness, "run_agent", fake_run_agent)

    results = run_eval(load_questions(questions_path))

    assert results[0]["passed"] is False
    assert results[0]["withheld_answer"] == "The value was 999."
    assert results[0]["gate_withheld_would_have_passed"] is False


def test_run_eval_gate_fields_are_empty_when_the_gate_never_fired(monkeypatch, tmp_path):
    questions_path = _write_one_numeric_question(tmp_path)

    def fake_run_agent(question, backend):
        return AgentResult("The value was 100 [1].", [{"text": "value = 100 raw"}], [], None, [], [])

    monkeypatch.setattr(eval_harness, "run_agent", fake_run_agent)

    results = run_eval(load_questions(questions_path))

    assert results[0]["passed"] is True
    assert results[0]["withheld_answer"] is None
    assert results[0]["gate_withheld_would_have_passed"] is None
    assert results[0]["gate_withheld_detail"] is None
    assert results[0]["citation_warning_details"] == []


def test_run_eval_backend_default_follows_config(monkeypatch, tmp_path):
    # A literal backend default would be bound at function-definition
    # time, ignoring config.DEFAULT_BACKEND entirely -- same gotcha as
    # run_agent()'s matching test in tests/agent/test_agent.py.
    questions_path = _write_one_numeric_question(tmp_path)
    backends_seen = []

    def fake_run_agent(question, backend):
        backends_seen.append(backend)
        return AgentResult("The value was 100 [1].", [{"text": "value = 100 raw"}], [], None, [], [])

    monkeypatch.setattr(eval_harness, "run_agent", fake_run_agent)
    monkeypatch.setattr(eval_harness, "DEFAULT_BACKEND", "totally-custom-backend")
    monkeypatch.setitem(llm_backends.BACKENDS, "totally-custom-backend", (None, None, None))

    run_eval(load_questions(questions_path))

    assert backends_seen == ["totally-custom-backend"]


@pytest.mark.parametrize("verbose", [False, True])
def test_run_eval_prints_the_question_text_only_when_verbose(monkeypatch, tmp_path, capsys, verbose):
    questions_path = _write_one_numeric_question(tmp_path)
    monkeypatch.setattr(
        eval_harness,
        "run_agent",
        lambda question, backend: AgentResult("The value was 100 [1].", [{"text": "value = 100 raw"}], [], None, [], []),
    )

    run_eval(load_questions(questions_path), verbose=verbose)

    out = capsys.readouterr().out
    if verbose:
        assert out.startswith("[q1] Q1?\n  -> PASS (")
    else:
        assert out == "[1/1] q1 (numeric)  PASS\n"


# ---------------------------------------------------------------------------
# _progress_lines — the per-question stdout, compact by default
# ---------------------------------------------------------------------------
def _row(**overrides):
    row = {
        "id": "q1",
        "question": "Q1?",
        "type": "numeric",
        "passed": True,
        "detail": "found matching value: 1 (raw)",
        "has_citation": True,
        "citation_warnings": [],
        "answer": "The answer is 1 [1].",
    }
    return {**row, **overrides}


def test_question_prefix_pads_the_counter_to_the_total_width():
    assert eval_harness._question_prefix(_row(), 3, 48) == "[ 3/48] q1 (numeric)  "


def test_progress_lines_compact_pass_is_the_bare_outcome():
    assert eval_harness._progress_lines(_row(), verbose=False) == ["PASS"]


def test_progress_lines_compact_fail_shows_both_flags_and_no_detail():
    row = _row(passed=False, detail="no value matching", has_citation=False, citation_warnings=["bad cite"])
    assert eval_harness._progress_lines(row, verbose=False) == ["FAIL  [no citation]  [unverified citation]"]


def test_progress_lines_compact_error_shows_truncated_detail_and_no_citation_flag():
    detail = "ClientError: 429 RESOURCE_EXHAUSTED " + "x" * 100
    row = _row(passed=False, detail=detail, has_citation=False, answer=None)
    (line,) = eval_harness._progress_lines(row, verbose=False)
    assert line == f"ERROR  {detail[:77]}..."
    assert "[no citation]" not in line


def test_truncate_flattens_a_multi_line_detail():
    assert eval_harness._truncate("ClientError: 400 {\n  'error': 'bad'\n}") == "ClientError: 400 { 'error': 'bad' }"


def test_progress_lines_verbose_keeps_the_full_per_question_output():
    row = _row(passed=False, detail="no value matching", has_citation=False, citation_warnings=["w1", "w2"])
    assert eval_harness._progress_lines(row, verbose=True) == [
        "  -> FAIL (no value matching)",
        "  -> WARNING: answer has no [n] citation marker at all",
        "  -> CITATION WARNING: w1",
        "  -> CITATION WARNING: w2",
    ]


def test_progress_lines_verbose_error_prints_no_citation_warning():
    row = _row(passed=False, detail="RuntimeError: boom", has_citation=False, answer=None)
    assert eval_harness._progress_lines(row, verbose=True) == ["  -> ERROR: RuntimeError: boom"]


# ---------------------------------------------------------------------------
# print_summary — pure aggregation/formatting over a results list
# ---------------------------------------------------------------------------
def test_print_summary_reports_aggregate_counts(capsys):
    results = [
        _row(id="q1"),
        _row(id="q2", type="judged", passed=False, has_citation=False, citation_warnings=["bad cite"]),
    ]
    eval_harness.print_summary(results)
    out = capsys.readouterr().out
    assert "1/2 passed" in out
    assert "1/2 included a citation marker" in out
    assert "1/2 had at least one unverified numeric citation" in out


def test_format_summary_tabulates_counts_per_type():
    results = [
        _row(id="n1"),
        _row(id="n2", passed=False, detail="no value matching 5 raw", has_citation=False),
        _row(id="n3", passed=False, detail="RuntimeError: boom", has_citation=False, answer=None),
        _row(id="j1", type="judged", citation_warnings=["w"]),
    ]
    lines = eval_harness.format_summary(results).splitlines()
    table = lines[lines.index("type        passed  no-cite  unverified  errors") :]
    # n3's missing citation is counted in the errors column, not no-cite.
    assert table[1] == "numeric        1/3        1           0       1"
    assert table[2] == "judged         1/1        0           1       0"


def test_format_summary_lists_only_failing_rows_with_truncated_detail():
    long_detail = "no value matching " + "x" * 200
    results = [
        _row(id="ok"),
        _row(id="bad", passed=False, detail=long_detail),
        _row(id="err", passed=False, detail="RuntimeError: boom", has_citation=False, answer=None),
    ]
    out = eval_harness.format_summary(results)
    tail = out[out.index("Not passed (2):") :].splitlines()
    assert tail == [
        "Not passed (2):",
        f"  bad (numeric): {long_detail[:147]}...",
        "  err (numeric) ERROR: RuntimeError: boom",
    ]


def test_format_summary_omits_not_passed_when_everything_passed():
    assert "Not passed" not in eval_harness.format_summary([_row()])


def test_format_summary_names_passed_rows_that_carry_citation_flags():
    results = [
        _row(id="clean"),
        _row(id="uncited", type="judged", has_citation=False),
        _row(id="unverified", citation_warnings=["w"]),
        _row(id="failed", passed=False, has_citation=False),
    ]
    out = eval_harness.format_summary(results)
    assert out[out.index("Passed with citation flags") :].splitlines() == [
        "Passed with citation flags (2):",
        "  uncited (judged)  [no citation]",
        "  unverified (numeric)  [unverified citation]",
    ]


def test_format_summary_omits_the_flagged_section_when_no_passed_row_is_flagged():
    assert "Passed with citation flags" not in eval_harness.format_summary([_row()])


def test_format_summary_accepts_old_rows_without_citation_fields():
    old_row = {"id": "q1", "type": "numeric", "passed": True, "detail": "ok", "answer": "1"}
    out = eval_harness.format_summary([old_row])
    assert "1/1 passed, 0/1 included a citation marker, 0/1 had at least one unverified" in out


# ---------------------------------------------------------------------------
# load_report / format_report_header -- summarizing a saved report
# ---------------------------------------------------------------------------
def test_load_report_reads_the_current_dict_shape(tmp_path):
    path = tmp_path / "r.json"
    path.write_text(json.dumps({"backend": "gemini", "results": [_row()]}), encoding="utf-8")
    assert eval_harness.load_report(path) == {"backend": "gemini", "results": [_row()]}


def test_load_report_wraps_an_old_bare_list_report(tmp_path):
    path = tmp_path / "r.json"
    path.write_text(json.dumps([_row()]), encoding="utf-8")
    assert eval_harness.load_report(path) == {"results": [_row()]}


@pytest.mark.parametrize("content", ['{"backend": "gemini"}', "42", '{"results": "nope"}'])
def test_load_report_rejects_json_that_is_not_a_report(tmp_path, content):
    path = tmp_path / "r.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match="not an eval report"):
        eval_harness.load_report(path)


def test_load_report_missing_file_raises_oserror(tmp_path):
    with pytest.raises(OSError):
        eval_harness.load_report(tmp_path / "nope.json")


def test_format_report_header_names_the_run():
    report = {
        "backend": "gemini",
        "answer_model": "gemini-x",
        "provenance": {
            "git_sha": "abc1234",
            "git_dirty": True,
            "prompts": {"agent_system": "111111111111", "agent": "3f9a1c2e77d0", "judge": "9e8d7c6b5a41"},
        },
        "results": [],
    }
    assert eval_harness.format_report_header("r.json", report) == (
        "Report r.json: backend=gemini answer_model=gemini-x git=abc1234 (dirty) "
        "agent_prompts=3f9a1c2e77d0 judge_prompts=9e8d7c6b5a41"
    )


def test_format_report_header_clean_tree_has_no_dirty_marker():
    provenance = {"git_sha": "abc", "git_dirty": False, "prompts": {"agent": "a1", "judge": "j1"}}
    report = {"backend": "gemini", "answer_model": "m", "provenance": provenance}
    assert "git=abc agent_prompts=a1" in eval_harness.format_report_header("r.json", report)


def test_format_report_header_shows_a_failed_fingerprint():
    report = {"provenance": {"git_sha": "abc", "prompts": "error"}}
    assert eval_harness.format_report_header("r.json", report).endswith("agent_prompts=error judge_prompts=error")


def test_format_report_header_marks_missing_fields_of_an_old_report():
    assert eval_harness.format_report_header("r.json", {"results": []}) == (
        "Report r.json: backend=? answer_model=? git=? agent_prompts=? judge_prompts=?"
    )


# ---------------------------------------------------------------------------
# main — argparse + orchestration (run_eval/save_report mocked; the live
# call itself is exercised by manual runs, per this module's own docstring)
# ---------------------------------------------------------------------------
def _numeric_question(qid: str) -> dict:
    return {"id": qid, "ticker": "AAPL", "question": f"{qid}?", "type": "numeric", "expected_value": 1, "expected_unit": "raw"}


def _write_questions(tmp_path, ids):
    questions_path = tmp_path / "questions.jsonl"
    questions_path.write_text(
        "\n".join(json.dumps(_numeric_question(i)) for i in ids), encoding="utf-8"
    )
    return questions_path


def _forbid(monkeypatch, name):
    def fail(*args, **kwargs):
        pytest.fail(f"{name} was called")

    monkeypatch.setattr(eval_harness, name, fail)


def _main(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["eval_harness.py", *argv])
    eval_harness.main()


def test_main_parses_ids_and_orchestrates_run_eval_then_save_report(monkeypatch, capsys, tmp_path):
    calls = {}
    questions_path = _write_questions(tmp_path, ["q1", "q2", "q3"])

    def fake_run_eval(questions, backend, judge_backend, verbose):
        calls["run_eval_args"] = ([q["id"] for q in questions], backend, judge_backend, verbose)
        return [_row()]

    def fake_save_report(results, backend, judge_backend, provenance):
        calls["save_report_args"] = (results, backend, judge_backend)
        calls["provenance"] = provenance
        return Path("./eval/eval_results/fake.json")

    monkeypatch.setattr(eval_harness, "run_eval", fake_run_eval)
    monkeypatch.setattr(eval_harness, "save_report", fake_save_report)
    monkeypatch.setattr(eval_harness, "_collect_provenance", lambda path: {"git_sha": "abc1234"})
    monkeypatch.setattr(eval_harness.hf_logging, "disable_progress_bar", lambda: calls.setdefault("bars_off", True))

    _main(monkeypatch, "--questions", str(questions_path), "--ids", "q1, q3", "--backend", "gemini")

    assert calls["run_eval_args"] == (["q1", "q3"], "gemini", None, False)
    assert calls["save_report_args"][1:] == ("gemini", None)
    assert calls["provenance"] == {"git_sha": "abc1234"}
    assert calls["bars_off"] is True
    out = capsys.readouterr().out
    assert "Full report saved to" in out
    assert "Citation-gate FP/FN breakdown: python -m sec_agent.devtools.analyze_citation_gate" in out


def test_main_passes_verbose_through(monkeypatch, tmp_path):
    seen = {}

    def fake_run_eval(questions, backend, judge_backend, verbose):
        seen["verbose"] = verbose
        return []

    monkeypatch.setattr(eval_harness, "run_eval", fake_run_eval)
    monkeypatch.setattr(eval_harness, "save_report", lambda *a, **k: Path("fake.json"))
    monkeypatch.setattr(eval_harness, "_collect_provenance", lambda path: {})
    monkeypatch.setattr(eval_harness.hf_logging, "disable_progress_bar", lambda: None)

    _main(monkeypatch, "--questions", str(_write_questions(tmp_path, ["q1"])), "--verbose")

    assert seen["verbose"] is True


@pytest.mark.parametrize("argv_tail", [["--ids", "nope"], ["--questions", "missing.jsonl"]])
def test_main_rejects_bad_question_selection_before_provenance(monkeypatch, tmp_path, capsys, argv_tail):
    # Provenance runs a snapshot subprocess that can take minutes, so a
    # typo must fail before it, as a usage error rather than a traceback.
    _forbid(monkeypatch, "_collect_provenance")
    _forbid(monkeypatch, "run_eval")
    questions_path = _write_questions(tmp_path, ["q1"])

    with pytest.raises(SystemExit) as exc:
        _main(monkeypatch, "--questions", str(questions_path), *argv_tail)

    assert exc.value.code == 2
    assert "error:" in capsys.readouterr().err


def test_main_summarize_prints_a_saved_report_without_running(monkeypatch, tmp_path, capsys):
    for name in ("run_eval", "_collect_provenance", "save_report"):
        _forbid(monkeypatch, name)
    monkeypatch.setattr(eval_harness.hf_logging, "disable_progress_bar", lambda: pytest.fail("bars touched"))
    path = tmp_path / "20260101T000000Z.json"
    path.write_text(json.dumps({"backend": "gemini", "results": [_row(), _row(id="q2", passed=False)]}), encoding="utf-8")

    _main(monkeypatch, "--summarize", str(path))

    out = capsys.readouterr().out
    assert out.startswith("Report 20260101T000000Z.json: backend=gemini")
    assert "Results: 1/2 passed" in out
    assert "  q2 (numeric): found matching value" in out


def test_main_summarize_unreadable_report_is_a_usage_error(monkeypatch, tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        _main(monkeypatch, "--summarize", str(tmp_path / "nope.json"))

    assert exc.value.code == 2
    assert "can't read report" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Provenance -- ties a report to the code and prompt version that produced
# it. Collected before any quota is spent, and never allowed to raise: a
# provenance failure must not cost a whole eval run.
# ---------------------------------------------------------------------------
def _fake_git(outputs: dict):
    """A stand-in for eval_harness._git: returns outputs[args], or raises
    the stored exception."""

    def fake(*args):
        result = outputs[args]
        if isinstance(result, Exception):
            raise result
        return result

    return fake


_REV_PARSE = ("rev-parse", "--short", "HEAD")
_STATUS = (
    "--no-optional-locks",
    "status",
    "--porcelain",
    "-z",
    "--untracked-files=all",
    "--",
    *eval_harness.PROVENANCE_PATHSPECS,
)


def test_provenance_pathspecs_name_existing_repo_relative_paths():
    # A pathspec that matches nothing never marks a report dirty, silently.
    for spec in eval_harness.PROVENANCE_PATHSPECS[1:]:
        assert not Path(spec).is_absolute()
        assert (eval_harness.PROJECT_ROOT / spec).exists(), spec


def test_git_state_clean_tree(monkeypatch):
    monkeypatch.setattr(
        eval_harness,
        "_git",
        _fake_git({_REV_PARSE: "abc1234\n", _STATUS: ""}),
    )
    assert eval_harness._git_state() == {"git_sha": "abc1234", "git_dirty": False, "dirty_files": []}


def test_git_state_lists_modified_renamed_and_unadded_files(monkeypatch):
    # -z output: NUL-separated "XY path" entries; a rename carries its
    # original path as a separate following entry. An un-added module
    # counts: code can import it while the SHA doesn't contain it.
    status = " M agent.py\0R  prompts/new.py\0prompts/old.py\0?? helpers.py\0?? prompts/extra.py\0"
    monkeypatch.setattr(eval_harness, "_git", _fake_git({_REV_PARSE: "abc1234\n", _STATUS: status}))
    state = eval_harness._git_state()
    assert state["git_dirty"] is True
    assert state["dirty_files"] == ["agent.py", "helpers.py", "prompts/extra.py", "prompts/new.py"]


def test_git_state_failure_records_unknown_and_logs_without_raising(monkeypatch):
    events = []
    monkeypatch.setattr(
        eval_harness, "_git", _fake_git({_REV_PARSE: OSError("no git"), _STATUS: OSError("no git")})
    )
    monkeypatch.setattr(eval_harness, "log_event", lambda category, **fields: events.append((category, fields)))
    assert eval_harness._git_state() == {"git_sha": "unknown", "git_dirty": None, "dirty_files": []}
    assert events[0][0] == "eval_provenance_git_failed"


def test_git_state_treats_undecodable_output_as_a_git_failure(monkeypatch):
    error = UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")
    monkeypatch.setattr(eval_harness, "_git", _fake_git({_REV_PARSE: "abc1234\n", _STATUS: error}))
    monkeypatch.setattr(eval_harness, "log_event", lambda category, **fields: None)
    assert eval_harness._git_state()["git_dirty"] is None


def test_snapshot_test_node_id_names_a_real_test():
    # If the test were renamed, pytest would find no such node and every
    # report would be marked unverified.
    path, name = eval_harness.SNAPSHOT_TEST.split("::")
    tree = ast.parse((eval_harness.PROJECT_ROOT / path).read_text(encoding="utf-8"))
    assert name in {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}


def test_git_state_keeps_the_dirty_state_when_only_rev_parse_fails(monkeypatch):
    # Each fact is recorded as found; compare_prompt_versions excludes a
    # report with no SHA on its own.
    monkeypatch.setattr(
        eval_harness, "_git", _fake_git({_REV_PARSE: eval_harness.GitError("unborn"), _STATUS: " M agent.py\0"})
    )
    monkeypatch.setattr(eval_harness, "log_event", lambda category, **fields: None)
    assert eval_harness._git_state() == {"git_sha": "unknown", "git_dirty": True, "dirty_files": ["agent.py"]}


def test_git_state_keeps_the_sha_when_only_the_status_call_fails(monkeypatch):
    monkeypatch.setattr(
        eval_harness, "_git", _fake_git({_REV_PARSE: "abc1234\n", _STATUS: eval_harness.GitError("index.lock")})
    )
    monkeypatch.setattr(eval_harness, "log_event", lambda category, **fields: None)
    assert eval_harness._git_state() == {"git_sha": "abc1234", "git_dirty": None, "dirty_files": []}


class _CompletedProcess:
    def __init__(self, returncode, stdout=b"", stderr=b""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def test_git_helper_decodes_stdout_as_utf8(monkeypatch):
    # Binary mode plus an explicit decode: a non-ASCII path must survive
    # regardless of the Windows code page.
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return _CompletedProcess(0, stdout=" M prompts/caf\u00e9.py\0".encode("utf-8"))

    monkeypatch.setattr(eval_harness.subprocess, "run", fake_run)
    assert eval_harness._git("status") == " M prompts/caf\u00e9.py\0"
    command, kwargs = calls[0]
    assert command == ["git", "status"]
    assert kwargs["cwd"] == eval_harness.PROJECT_ROOT
    assert "text" not in kwargs


def test_run_snapshot_check_compares_only_and_never_rewrites(monkeypatch):
    # With UPDATE_SNAPSHOT inherited, the check would overwrite the
    # committed snapshot and then trivially "verify" it.
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return _CompletedProcess(1)

    monkeypatch.setenv("UPDATE_SNAPSHOT", "1")
    monkeypatch.setattr(eval_harness.subprocess, "run", fake_run)
    assert eval_harness._run_snapshot_check() == 1
    command, kwargs = calls[0]
    assert eval_harness.SNAPSHOT_TEST in command
    assert "UPDATE_SNAPSHOT" not in kwargs["env"]
    assert kwargs["cwd"] == eval_harness.PROJECT_ROOT
    assert kwargs["timeout"] == eval_harness.SNAPSHOT_CHECK_TIMEOUT


def test_git_helper_raises_on_a_nonzero_exit(monkeypatch):
    class Result:
        returncode = 128
        stdout = b""
        stderr = "fatal: not a git repository".encode("utf-8")

    monkeypatch.setattr(eval_harness.subprocess, "run", lambda *a, **k: Result())
    with pytest.raises(eval_harness.GitError, match="not a git repository"):
        eval_harness._git("rev-parse", "HEAD")


@pytest.mark.parametrize(("returncode", "expected"), [(0, True), (1, False), (2, None), (5, None)])
def test_snapshot_verified_maps_pytest_exit_codes(monkeypatch, returncode, expected):
    # 0: the snapshot matches; 1: a test failed, so the snapshot is stale;
    # anything else means the check itself couldn't run, which is not
    # the same as the snapshot being wrong.
    monkeypatch.setattr(eval_harness, "_run_snapshot_check", lambda: returncode)
    assert eval_harness._snapshot_verified() is expected


def test_snapshot_verified_is_none_when_pytest_is_not_installed(monkeypatch):
    monkeypatch.setattr(eval_harness.importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(eval_harness, "_run_snapshot_check", lambda: pytest.fail("should not run"))
    assert eval_harness._snapshot_verified() is None


@pytest.mark.parametrize("error", [OSError("cannot start"), subprocess.TimeoutExpired("pytest", 1)])
def test_snapshot_verified_is_none_when_the_subprocess_fails_or_hangs(monkeypatch, error):
    def broken():
        raise error

    monkeypatch.setattr(eval_harness, "_run_snapshot_check", broken)
    monkeypatch.setattr(eval_harness, "log_event", lambda category, **fields: None)
    assert eval_harness._snapshot_verified() is None


def test_run_config_records_model_settings_and_library_versions():
    config = eval_harness._run_config()
    assert set(config) == {"gemini_model", "embed_model", "rerank_model", "chroma_dir", "google_genai", "mcp"}
    assert config["gemini_model"] == eval_harness.GEMINI_MODEL_NAME
    assert config["google_genai"]


def test_run_config_records_chroma_dir_relative_to_the_project_root(monkeypatch, tmp_path):
    # Reports are committed, so a store inside the checkout is recorded
    # without the machine-specific prefix; one outside it stays absolute.
    monkeypatch.setattr(eval_harness, "CHROMA_DIR", str(eval_harness.PROJECT_ROOT / "var" / "chroma_db"))
    assert eval_harness._run_config()["chroma_dir"] == "var/chroma_db"
    monkeypatch.setattr(eval_harness, "CHROMA_DIR", str(tmp_path))
    assert eval_harness._run_config()["chroma_dir"] == str(tmp_path)


def test_run_config_records_none_for_a_missing_library(monkeypatch):
    def missing(name):
        raise eval_harness.importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(eval_harness.importlib.metadata, "version", missing)
    config = eval_harness._run_config()
    assert config["google_genai"] is None and config["mcp"] is None


def _stub_provenance_parts(monkeypatch):
    monkeypatch.setattr(
        eval_harness, "_git_state", lambda extra=(): {"git_sha": "abc1234", "git_dirty": False, "dirty_files": []}
    )
    monkeypatch.setattr(eval_harness, "_snapshot_verified", lambda: True)
    monkeypatch.setattr(eval_harness, "_run_config", lambda: {"gemini_model": "m"})
    monkeypatch.setattr(
        eval_harness, "corpus_provenance",
        lambda chunks_dir, chroma_dir: {"corpus": {"sha": "abc"}, "index_matches_chunks": True},
    )


def test_collect_provenance_combines_every_part(monkeypatch):
    _stub_provenance_parts(monkeypatch)
    monkeypatch.setattr(eval_harness, "prompt_fingerprint", lambda: {"agent": "fp"})
    assert eval_harness._collect_provenance() == {
        "git_sha": "abc1234",
        "git_dirty": False,
        "dirty_files": [],
        "snapshot_verified": True,
        # The corpus is part of config; the index match flag isn't, so a
        # rebuild of the same corpus doesn't read as a config change.
        "config": {
            "gemini_model": "m",
            "corpus": {"sha": "abc"},
            "questions": eval_harness._questions_provenance(eval_harness.QUESTIONS_PATH),
        },
        "index_matches_chunks": True,
        "prompts": {"agent": "fp"},
    }


def test_collect_provenance_records_a_fingerprint_failure_without_raising(monkeypatch):
    events = []

    def broken_fingerprint():
        raise ValueError("bad snapshot")

    _stub_provenance_parts(monkeypatch)
    monkeypatch.setattr(eval_harness, "prompt_fingerprint", broken_fingerprint)
    monkeypatch.setattr(eval_harness, "log_event", lambda category, **fields: events.append((category, fields)))
    assert eval_harness._collect_provenance()["prompts"] == "error"
    assert events[0][0] == "eval_provenance_fingerprint_failed"


def test_provenance_warnings_name_a_dirty_tree_and_an_unverified_snapshot():
    clean = {"git_sha": "abc1234", "git_dirty": False, "snapshot_verified": True, "prompts": {"agent": "fp"}}
    assert eval_harness._provenance_warnings(clean) == []
    warnings = eval_harness._provenance_warnings(
        {**clean, "git_dirty": True, "dirty_files": ["agent.py"], "snapshot_verified": False, "prompts": "error"}
    )
    assert len(warnings) == 3
    assert any("agent.py" in w for w in warnings)
    # Every state compare_prompt_versions excludes is warned about.
    for sha in ("unknown", "", None):
        assert any("records no commit" in w for w in eval_harness._provenance_warnings({**clean, "git_sha": sha}))
    assert any("status unknown" in w for w in eval_harness._provenance_warnings({**clean, "git_dirty": None}))


def test_provenance_warnings_name_an_index_built_from_other_chunks():
    clean = {"git_sha": "abc1234", "git_dirty": False, "snapshot_verified": True, "prompts": {"agent": "fp"}}
    assert eval_harness._provenance_warnings({**clean, "index_matches_chunks": None}) == []
    warnings = eval_harness._provenance_warnings({**clean, "index_matches_chunks": False})
    assert len(warnings) == 1 and "index_chunks" in warnings[0]


@pytest.mark.parametrize(
    "change",
    [
        {},
        {"git_sha": "unknown"},
        {"git_sha": ""},
        {"git_sha": None},
        {"git_dirty": True, "dirty_files": ["agent.py"]},
        {"git_dirty": None},
        {"snapshot_verified": False},
        {"snapshot_verified": None},
        {"index_matches_chunks": False},
        {"index_matches_chunks": None},
    ],
)
def test_every_report_the_compare_script_excludes_is_warned_about_at_eval_start(change):
    provenance = {"git_sha": "abc1234", "git_dirty": False, "snapshot_verified": True, "prompts": {"agent": "fp"}}
    provenance.update(change)
    report = compare_prompt_versions.Report("r", provenance, "gemini", "m", "m", [], 0)
    excluded = compare_prompt_versions.is_excluded(report, include_dirty=False)
    assert bool(eval_harness._provenance_warnings(provenance)) is excluded


def test_save_report_writes_provenance_when_given(monkeypatch, tmp_path):
    monkeypatch.setattr(eval_harness, "RESULTS_DIR", tmp_path)
    out_path = save_report([], backend="gemini", provenance={"git_sha": "abc1234"})
    with out_path.open(encoding="utf-8") as f:
        assert json.load(f)["provenance"] == {"git_sha": "abc1234"}


def test_save_report_omits_provenance_when_not_given(monkeypatch, tmp_path):
    monkeypatch.setattr(eval_harness, "RESULTS_DIR", tmp_path)
    with save_report([], backend="gemini").open(encoding="utf-8") as f:
        assert "provenance" not in json.load(f)


# ---------------------------------------------------------------------------
# Judge nonstandard-output flag -- evidence for whether the judge's verdict
# format needs changing. `passed` is computed exactly as before; only the
# reason gains a prefix, and "disagrees" marks the one case that matters:
# a lenient reading of the output would have graded it differently.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("verdict", "passed", "prefix"),
    [
        ("PASS\nfine.", True, None),
        ("fail\nmissing.", False, None),
        ("PASS.\nfine.", True, "[nonstandard judge output: 'PASS.']"),
        ("**PASS**\nfine.", False, "[nonstandard judge output; lenient parse disagrees: '**PASS**']"),
        ("PASSED\nfine.", True, "[nonstandard judge output: 'PASSED']"),
        ("PASS/FAIL: FAIL\nhmm.", True, "[nonstandard judge output: 'PASS/FAIL: FAIL']"),
        # The verdict is read from the first line naming PASS or FAIL, so
        # a reason that mentions the other word doesn't hide a misgrade.
        (
            "**PASS**\nIt would FAIL only without a citation.",
            False,
            "[nonstandard judge output; lenient parse disagrees: '**PASS**']",
        ),
        ("Verdict:\nPASS", False, "[nonstandard judge output; lenient parse disagrees: 'VERDICT:']"),
        ("", False, "[nonstandard judge output: '']"),
    ],
)
def test_grade_judged_flags_nonstandard_output_without_changing_the_verdict(monkeypatch, verdict, passed, prefix):
    events = []
    monkeypatch.setattr("sec_agent.eval.eval_harness.complete", lambda backend, system_prompt, user_prompt, temperature=0.0: verdict)
    monkeypatch.setattr(eval_harness, "log_event", lambda category, **fields: events.append((category, fields)))
    got_passed, reason = grade_judged("Q?", "some answer", "some criteria")
    assert got_passed is passed
    if prefix is None:
        assert not reason.startswith("[nonstandard")
        assert events == []
    else:
        assert reason.startswith(prefix)
        assert events[0][0] == "judge_nonstandard_output"



# ---------------------------------------------------------------------------
# v2 grading: text, refusal and clarify types, plus the `accepted` post-pass
# check and the per-question tolerance.
# Deterministic checks live in _grade_by_type so gate evidence and the
# offline replay see the same verdict as the real grade.
# ---------------------------------------------------------------------------
_V2 = {"category": "cross-company", "steps": 1, "answer_source": "table", "trap": "look-alike", "needs_calculate": False}
_BANKS = [
    {"ticker": "JPM", "expected_value": 182.4, "expected_unit": "billion"},
    {"ticker": "BAC", "expected_value": 101.9, "expected_unit": "billion"},
]


def test_text_question_passes_on_an_accepted_variant_with_a_citation():
    q = {"type": "text", "accepted": ["PricewaterhouseCoopers LLP", "PwC"]}
    assert _grade_by_type(q, "Caterpillar's auditor is PwC [3].", None, []) == (True, "found accepted text")


@pytest.mark.parametrize(
    "answer, detail",
    [
        ("Caterpillar's auditor is PwC.", "has no citation marker"),
        ("Caterpillar's auditor is Deloitte [3].", "none of the accepted answers"),
    ],
)
def test_text_question_fails_without_a_citation_or_an_accepted_variant(answer, detail):
    passed, found = _grade_by_type({"type": "text", "accepted": ["PwC"]}, answer, None, [])
    assert passed is False and detail in found


def test_text_question_counts_a_multi_source_bracket_as_a_citation():
    assert _grade_by_type({"type": "text", "accepted": ["PwC"]}, "The auditor is PwC [1, 3].", None, [])[0] is True


def test_text_question_is_failed_when_the_gate_refused():
    passed, detail = _grade({"type": "text", "accepted": ["PwC"]}, _answered("PwC [1]", ["[1] claims ..."]))
    assert passed is False and "refused" in detail


def test_accepted_on_a_numeric_question_also_requires_the_period_text():
    q = {"type": "numeric", "expected_value": 72.4, "expected_unit": "billion", "accepted": ["January 31, 2026"]}
    assert _grade_by_type(q, "RPO was $72.4 billion as of Jan. 31, 2026 [1].", None, [])[0] is True
    passed, detail = _grade_by_type(q, "RPO was $72.4 billion [1].", None, [])
    assert passed is False and "none of the accepted answers" in detail


def _attributed(*pairs) -> list[dict]:
    """Attributions as claim_attributions returns them, one per (ticker, value in billions)."""
    return [
        {"citation_index": i, "value": v, "unit": "billion", "quote": "q", "tickers": [t]} for i, (t, v) in enumerate(pairs, 1)
    ]


_ANSWER = "- JPMorgan: $182.4 billion [1]\n- Bank of America: $101.9 billion [2]"
_SWAPPED = _attributed(("BAC", 182.4), ("JPM", 101.9))


def test_v1_comparison_keeps_its_grader_unchanged():
    # No category: v1. Claims citing the other bank's sources still pass.
    assert _grade_by_type({"type": "comparison", "expected": _BANKS}, _ANSWER, None, _SWAPPED) == (
        True,
        "found matching values for all 2 entities",
    )


def test_v2_comparison_fails_when_its_claims_cite_the_other_companys_sources():
    passed, detail = _grade_by_type({"type": "comparison", "tickers": ["JPM", "BAC"], "expected": _BANKS, **_V2}, _ANSWER, None, _SWAPPED)
    assert passed is False
    assert detail.endswith("value(s) not attributed to their company: JPM (182.4 billion), BAC (101.9 billion)")


def test_v2_comparison_passes_when_each_value_is_claimed_for_its_company():
    right = _attributed(("JPM", 182.4), ("BAC", 101.9))
    assert _grade_by_type({"type": "comparison", "tickers": ["JPM", "BAC"], "expected": _BANKS, **_V2}, _ANSWER, None, right) == (
        True,
        "found matching values for all 2 entities",
    )


@pytest.mark.parametrize("asked", [{"ticker": "AAPL"}, {"tickers": ["AAPL"]}], ids=["ticker", "one-item-tickers"])
def test_v2_comparison_charges_non_ticker_labels_to_the_questions_one_company(asked):
    expected = [
        {"ticker": "AAPL-cash", "expected_value": 30.3, "expected_unit": "billion"},
        {"ticker": "AAPL-buyback", "expected_value": 89.2, "expected_unit": "billion"},
    ]
    q = {"type": "comparison", "expected": expected, **asked, **_V2}
    answer = "Cash was $30.3 billion [1] and the buyback $89.2 billion [2]."
    assert _grade_by_type(q, answer, None, _attributed(("AAPL", 30.3), ("AAPL", 89.2)))[0] is True
    passed, detail = _grade_by_type(q, answer, None, _attributed(("AAPL", 30.3), ("MSFT", 89.2)))
    assert passed is False and detail.endswith("not attributed to their company: AAPL-buyback (89.2 billion)")


_TGT = {
    "type": "numeric",
    "ticker": "TGT",
    "expected_value": 106.6,
    "expected_unit": "billion",
    "forbidden_values": [{"value": 109.1, "unit": "billion"}],
    **_V2,
}
_TGT_ANSWER = "Target's revenue was $106.6 billion, not $109.1 billion [1]."


def test_v2_trap_value_claimed_for_the_asked_company_fails():
    passed, detail = _grade_by_type(_TGT, _TGT_ANSWER, None, _attributed(("TGT", 106.6), ("TGT", 109.1)))
    assert passed is False and detail.endswith("trap value(s) claimed: TGT (109.1 billion)")


@pytest.mark.parametrize(
    "attributions",
    [_attributed(("TGT", 106.6), ("WMT", 109.1)), _attributed(("TGT", 106.6))],
    ids=["claimed-for-another-company", "only-in-the-prose"],
)
def test_v2_trap_value_not_claimed_for_the_asked_company_passes(attributions):
    assert _grade_by_type(_TGT, _TGT_ANSWER, None, attributions)[0] is True


_TGT_SOURCE = {"text": "Total revenue was $106.6 billion.", "metadata": {"ticker": "TGT", "chunk_index": "0"}}
_TGT_CLAIM = {"citation_index": 1, "value": 106.6, "unit": "billion", "quote": "Total revenue was $106.6 billion"}
_TRAP_CLAIM = {"citation_index": 1, "value": 109.1, "unit": "billion", "quote": "Total revenue was $106.6 billion"}
_TGT_Q = {**_TGT, "id": "tgt", "question": "Target revenue?"}
_TGT_JUDGED = {**_TGT_Q, "type": "judged", "criteria": "States $106.6 billion."}


def _claimed(claims: list[dict], citation_warnings: list[str] | None = None) -> AgentResult:
    """An agent result for _grade whose `claims` cite the one TGT source."""
    return AgentResult(_TGT_ANSWER, [_TGT_SOURCE], citation_warnings or [], None, [], claims)


def test_v2_judged_question_fails_on_a_trap_value_after_a_judge_pass(monkeypatch):
    _capture_judge(monkeypatch)
    assert _grade(_TGT_JUDGED, _claimed([_TGT_CLAIM]))[0] is True
    passed, detail = _grade(_TGT_JUDGED, _claimed([_TRAP_CLAIM]))
    assert passed is False and detail.endswith("trap value(s) claimed: TGT (109.1 billion)")


def test_grade_does_not_trap_check_the_claims_of_a_refused_answer(monkeypatch):
    _capture_judge(monkeypatch)
    assert _grade(_TGT_JUDGED, _claimed([_TRAP_CLAIM], ["[1] claims ..."]))[0] is True


def _agent_result(monkeypatch, answer, warnings, withheld, claims):
    result = AgentResult(answer, [_TGT_SOURCE], warnings, withheld, [], claims)
    monkeypatch.setattr(eval_harness, "run_agent", lambda question, backend: result)


def test_run_one_records_the_attributed_claims_of_an_accepted_answer(monkeypatch):
    _agent_result(monkeypatch, "Target's revenue was $106.6 billion [1].", [], None, [_TGT_CLAIM])
    row = _run_one(_TGT_Q, "gemini", "gemini")
    assert row["passed"] is True
    assert row["claims"] == [{**_TGT_CLAIM, "tickers": ["TGT"]}]
    assert row["gate_withheld_claims"] is None


def test_run_one_regrades_a_withheld_answer_with_its_own_claims_and_stores_no_claims(monkeypatch):
    withheld = "Target's revenue was $106.6 billion, or $109.1 billion [1]."
    _agent_result(monkeypatch, "I can't confirm this answer...", ["bad"], withheld, [_TGT_CLAIM, _TRAP_CLAIM])
    row = _run_one(_TGT_Q, "gemini", "gemini")
    assert row["passed"] is False
    assert row["claims"] == []
    assert row["gate_withheld_claims"] == [{**_TGT_CLAIM, "tickers": ["TGT"]}, {**_TRAP_CLAIM, "tickers": ["TGT"]}]
    assert row["gate_withheld_would_have_passed"] is False
    assert row["gate_withheld_detail"].endswith("trap value(s) claimed: TGT (109.1 billion)")


def test_run_one_does_not_trap_check_an_answer_the_gate_refused(monkeypatch):
    # The user saw only the refusal, never the trap value.
    _capture_judge(monkeypatch)
    _agent_result(monkeypatch, "I can't confirm this answer...", ["bad"], "It was $109.1 billion [1].", [_TRAP_CLAIM])
    q = {**_TGT, "type": "refusal", "refusal_kind": "not_covered", "id": "tgt", "question": "Target revenue?"}
    row = _run_one(q, "gemini", "gemini")
    assert row["passed"] is True
    assert row["claims"] == []


def test_run_one_error_row_stores_no_claims(monkeypatch):
    def boom(question, backend):
        raise RuntimeError("network down")

    monkeypatch.setattr(eval_harness, "run_agent", boom)
    row = _run_one(_TGT_Q, "gemini", "gemini")
    assert row["claims"] == [] and row["gate_withheld_claims"] is None


def test_tolerance_override_widens_the_numeric_match():
    q = {"type": "numeric", "expected_value": 100, "expected_unit": "billion"}
    assert _grade_by_type(q, "It was $101.5 billion.", None, [])[0] is False
    assert _grade_by_type({**q, "tolerance": 0.02, "tolerance_note": "n"}, "It was $101.5 billion.", None, [])[0] is True


def test_a_widened_tolerance_still_checks_the_value_citation():
    # The claim match must widen with the grader's, or a miscited value in
    # the extra band finds no claim and skips the citation check.
    wrong_source = [{"text": "Net income was $10.0 billion."}]
    assert grade_numeric("Net income was $101.5 billion [1].", 100, "billion", wrong_source, 0.02)[0] is False
    right_source = [{"text": "Net income was $101.5 billion."}]
    assert grade_numeric("Net income was $101.5 billion [1].", 100, "billion", right_source, 0.02)[0] is True


def _capture_judge(monkeypatch) -> list[str]:
    prompts = []

    def fake_complete(backend, system_prompt, user_prompt, temperature=0.0):
        prompts.append(user_prompt)
        return "PASS\nok"

    monkeypatch.setattr(eval_harness, "complete", fake_complete)
    return prompts


def test_refusal_question_is_judged_on_its_kinds_template_even_when_gated(monkeypatch):
    prompts = _capture_judge(monkeypatch)
    q = {"type": "refusal", "question": "XOM 2030 revenue?", "refusal_kind": "not_yet_filed", "criteria": "No 2030 10-K."}
    passed, _ = _grade(q, _answered("That period hasn't been reported.", ["[1] claims ..."]))
    assert passed is True
    assert REFUSAL_CRITERIA["not_yet_filed"] + " For this question: No 2030 10-K." in prompts[0]


def test_clarify_question_is_judged_on_its_readings(monkeypatch):
    prompts = _capture_judge(monkeypatch)
    q = {"type": "clarify", "question": "Walmart's margin?", "readings": ["gross margin", "operating margin"]}
    assert _grade(q, _answered("Which margin do you mean?"))[0] is True
    assert "these readings: gross margin; operating margin." in prompts[0]


def test_citation_gate_evidence_regrades_a_withheld_text_answer():
    q = {"type": "text", "accepted": ["PwC"]}
    evidence = eval_harness._citation_gate_evidence(q, [], "The auditor is PwC [1].", [], [])
    assert evidence["gate_withheld_would_have_passed"] is True


def test_row_identity_carries_v2_tags_only_when_present():
    v1 = {"id": "a", "ticker": "AAPL", "question": "Q?", "type": "numeric"}
    assert eval_harness._row_identity(v1) == {"id": "a", "ticker": "AAPL", "question": "Q?", "type": "numeric"}
    v2 = {**v1, **_V2}
    assert eval_harness._row_identity(v2)["category"] == "cross-company"
    assert eval_harness._row_identity(v2)["trap"] == "look-alike"


def test_format_summary_adds_a_category_table_sized_to_the_longest_name():
    results = [
        _row(id="n1", category="numerical-reasoning"),
        _row(id="n2", category="extraction", passed=False, detail="no value"),
    ]
    lines = eval_harness.format_summary(results).splitlines()
    header = next(i for i, line in enumerate(lines) if line.startswith("category"))
    assert lines[header + 1].startswith("numerical-reasoning ")
    assert lines[header + 1].split()[1] == "1/1"
    assert lines[header + 2].split()[:2] == ["extraction", "0/1"]


def test_format_summary_has_no_category_table_for_v1_rows():
    assert "category" not in eval_harness.format_summary([_row()])


def test_load_questions_rejects_a_malformed_question(tmp_path):
    path = tmp_path / "questions.jsonl"
    path.write_text(json.dumps({"id": "q1", "ticker": "AAPL", "question": "Q?", "type": "numeric"}), encoding="utf-8")
    with pytest.raises(ValueError, match="'q1'.*expected_value"):
        load_questions(path)


def test_questions_provenance_hash_ignores_line_endings(tmp_path):
    lf, crlf = tmp_path / "lf.jsonl", tmp_path / "crlf.jsonl"
    lf.write_bytes(b'{"a": 1}\n{"b": 2}\n')
    crlf.write_bytes(b'{"a": 1}\r\n{"b": 2}\r\n')
    assert eval_harness._questions_provenance(lf)["sha256"] == eval_harness._questions_provenance(crlf)["sha256"]
    assert len(eval_harness._questions_provenance(lf)["sha256"]) == 12


def test_questions_provenance_path_is_root_relative():
    assert eval_harness._questions_provenance(eval_harness.QUESTIONS_PATH)["path"] == "eval/eval_questions.jsonl"


def test_questions_provenance_records_an_unreadable_file_without_raising(tmp_path, monkeypatch):
    events = []
    monkeypatch.setattr(eval_harness, "log_event", lambda category, **fields: events.append(category))
    assert eval_harness._questions_provenance(tmp_path / "gone.jsonl")["sha256"] is None
    assert events == ["eval_provenance_questions_failed"]


def test_collect_provenance_puts_the_questions_file_in_config(monkeypatch, tmp_path):
    _stub_provenance_parts(monkeypatch)
    monkeypatch.setattr(eval_harness, "prompt_fingerprint", lambda: {"agent": "fp"})
    path = tmp_path / "v2.jsonl"
    path.write_text("{}\n", encoding="utf-8")
    config = eval_harness._collect_provenance(path)["config"]
    assert config["questions"] == eval_harness._questions_provenance(path)


def test_git_state_checks_the_extra_questions_path_for_uncommitted_edits(monkeypatch):
    status_args = []

    def fake_git(*args):
        if args[0] == "rev-parse":
            return "abc1234\n"
        status_args.append(args)
        return "?? eval/v2_questions.jsonl\0"

    monkeypatch.setattr(eval_harness, "_git", fake_git)
    state = eval_harness._git_state(("eval/v2_questions.jsonl",))
    assert status_args[0][-1] == "eval/v2_questions.jsonl"
    assert state["dirty_files"] == ["eval/v2_questions.jsonl"]


@pytest.mark.parametrize("answer", ["Revenue was $5 billion [1].", "Revenue was $5 and $6 billion [1, 6]."])
def test_citation_pattern_counts_single_and_multi_source_markers(answer):
    assert eval_harness.CITATION_PATTERN.search(answer)
