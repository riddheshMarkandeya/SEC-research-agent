"""
Unit tests for eval_harness.py. Covers the deterministic grading logic
(grade_numeric, grade_comparison, load_questions) plus grade_judged's
response-PARSING logic with a mocked Ollama call — the call itself isn't
made, only the "split PASS/FAIL + reason out of the model's reply" logic
is exercised. run_eval()'s end-to-end behavior (live retrieval + live
LLM calls) is exercised by manual runs (python eval_harness.py)
documented in PROJECT_CONTEXT.md, not here.

extract_numbers()/normalize() moved to numeric_utils.py (shared with
agent.py's verify_citations()) — see tests/test_numeric_utils.py.
"""

import json

import eval_harness
from agent import AgentResult
from eval_harness import (
    _grade,
    _select_questions,
    grade_comparison,
    grade_judged,
    grade_numeric,
    load_questions,
    run_eval,
    save_report,
)


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
        '{"id": "q1", "question": "A?"}\n'
        "\n"
        '{"id": "q2", "question": "B?"}\n',
        encoding="utf-8",
    )
    questions = load_questions(path)
    assert [q["id"] for q in questions] == ["q1", "q2"]


# ---------------------------------------------------------------------------
# _select_questions -- --ids / skip-flag filtering, kept separate from
# run_eval()'s live agent loop so it's testable without network/Ollama calls
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
# _grade — dispatch + Week 7 hard-gate short-circuit (found in code review,
# 2026-08-26: a refusal's own warning text repeats the claimed number, which
# grade_numeric's plain text scan could otherwise match as a false PASS)
# ---------------------------------------------------------------------------
def test_grade_fails_numeric_question_when_agent_refused_even_if_value_is_in_refusal_text():
    # Reproduces the exact false-positive shape found in review: the
    # refusal text contains the expected value as part of explaining
    # why the claim was rejected, which a naive grade_numeric() call
    # would still match.
    q = {"type": "numeric", "expected_value": 166000.0, "expected_unit": "raw"}
    refusal_text = (
        "I can't confirm this answer against the sources I retrieved -- "
        "the following claim(s) don't hold up under citation verification:\n"
        "- [1] claims 166000.0 (raw) but that value doesn't appear in the cited source"
    )
    warnings = ["[1] claims 166000.0 (raw) but that value doesn't appear in the cited source"]

    passed, detail = _grade(q, refusal_text, warnings, [])

    assert passed is False
    assert "refused" in detail.lower()


def test_grade_fails_comparison_question_when_agent_refused():
    q = {"type": "comparison", "expected": [{"ticker": "AAPL", "expected_value": 1.0, "expected_unit": "raw"}]}
    passed, detail = _grade(q, "some refusal text", ["[1] claims ... doesn't appear"], [])
    assert passed is False
    assert "refused" in detail.lower()


def test_grade_still_calls_grade_numeric_when_no_citation_warnings():
    q = {"type": "numeric", "expected_value": 72.4, "expected_unit": "billion"}
    passed, _ = _grade(q, "Total RPO was approximately $72.4 billion.", [], [])
    assert passed is True


def test_grade_does_not_short_circuit_judged_questions_with_citation_warnings(monkeypatch):
    # Judged refusal-style questions (e.g. nvda-rd-expense-q4fy26-refusal)
    # expect a refusal as the CORRECT answer -- grade_judged must still
    # run and decide based on its own criteria, not be pre-empted.
    monkeypatch.setattr(
        "eval_harness.complete",
        lambda backend, system_prompt, user_prompt, temperature=0.0: (
            "PASS\nCorrectly refused, no such data exists."
        ),
    )
    q = {
        "type": "judged",
        "question": "What was the R&D expense?",
        "criteria": "the answer should refuse, since no such figure exists",
    }
    passed, _ = _grade(q, "I can't confirm this...", ["[1] claims ... doesn't appear"], [])
    assert passed is True


def test_grade_raises_on_unknown_type():
    try:
        _grade({"type": "mystery", "id": "q1"}, "answer", [], [])
        assert False, "expected ValueError"
    except ValueError as e:
        assert "mystery" in str(e)


# ---------------------------------------------------------------------------
# grade_judged — mocked llm_backends.complete() (2026-09-10: routes through
# this rather than calling Ollama directly, so --judge-backend can be
# honored -- see
# docs/plans/2026-09-10-citation-gate-measurement-instrumentation.md).
# complete() itself still reuses each backend's existing retry/backoff/
# log_event machinery (found missing in code review 2026-09-06, when a
# raw requests.post here bypassed it entirely) -- these tests only cover
# the response-parsing logic and that grade_judged is wired up correctly.
# ---------------------------------------------------------------------------
def test_grade_judged_parses_pass(monkeypatch):
    monkeypatch.setattr(
        "eval_harness.complete",
        lambda backend, system_prompt, user_prompt, temperature=0.0: "PASS\nThe answer clearly satisfies the criteria.",
    )
    passed, reason = grade_judged("Q?", "some answer", "some criteria")
    assert passed is True
    assert reason == "The answer clearly satisfies the criteria."


def test_grade_judged_parses_fail(monkeypatch):
    monkeypatch.setattr(
        "eval_harness.complete",
        lambda backend, system_prompt, user_prompt, temperature=0.0: "FAIL\nThe answer does not mention the required risk.",
    )
    passed, reason = grade_judged("Q?", "some answer", "some criteria")
    assert passed is False
    assert reason == "The answer does not mention the required risk."


def test_grade_judged_lowercase_pass_still_counts(monkeypatch):
    monkeypatch.setattr("eval_harness.complete", lambda backend, system_prompt, user_prompt, temperature=0.0: "pass\nfine.")
    passed, _ = grade_judged("Q?", "some answer", "some criteria")
    assert passed is True


def test_grade_judged_calls_complete_with_temperature_0(monkeypatch):
    # grade_judged wants stricter, more deterministic grading than
    # generation's default temperature 0.1, and never needs tool-calling
    # (complete() itself never passes tool_schemas -- see llm_backends.py).
    calls = []

    def fake_complete(backend, system_prompt, user_prompt, temperature=0.0):
        calls.append({"backend": backend, "temperature": temperature})
        return "PASS\nfine."

    monkeypatch.setattr("eval_harness.complete", fake_complete)
    grade_judged("Q?", "some answer", "some criteria")
    assert calls[0]["temperature"] == 0.0


def test_grade_judged_routes_to_the_requested_backend(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "eval_harness.complete",
        lambda backend, system_prompt, user_prompt, temperature=0.0: calls.append(backend) or "PASS\nfine.",
    )
    grade_judged("Q?", "some answer", "some criteria", backend="gemini")
    assert calls == ["gemini"]


def test_grade_judged_defaults_to_ollama_backend(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "eval_harness.complete",
        lambda backend, system_prompt, user_prompt, temperature=0.0: calls.append(backend) or "PASS\nfine.",
    )
    grade_judged("Q?", "some answer", "some criteria")
    assert calls == ["ollama"]


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


def test_save_report_records_the_actual_answering_model_per_backend(monkeypatch, tmp_path):
    # Found live (2026-08-25): the report only ever recorded the generic
    # "ollama"/"gemini" backend label, not which specific model actually
    # answered -- OLLAMA_MODEL_NAME/GEMINI_MODEL_NAME are both
    # configurable via .env and can change over time, so an old report
    # would otherwise become ambiguous about what really produced it.
    monkeypatch.setattr(eval_harness, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(eval_harness, "OLLAMA_MODEL_NAME", "fake-ollama-model")
    monkeypatch.setattr(eval_harness, "GEMINI_MODEL_NAME", "fake-gemini-model")

    with save_report([], backend="ollama").open(encoding="utf-8") as f:
        ollama_report = json.load(f)
    with save_report([], backend="gemini").open(encoding="utf-8") as f:
        gemini_report = json.load(f)

    assert ollama_report["answer_model"] == "fake-ollama-model"
    assert gemini_report["answer_model"] == "fake-gemini-model"


def test_save_report_records_the_judge_backends_model(monkeypatch, tmp_path):
    # Until 2026-09-10 grade_judged() always called Ollama directly
    # regardless of --backend, so judge_model was hardcoded to
    # OLLAMA_MODEL_NAME. It's now whichever backend actually judged --
    # this is an intentional behavior change (see
    # docs/plans/2026-09-10-citation-gate-measurement-instrumentation.md),
    # not a regression of the test this replaces.
    monkeypatch.setattr(eval_harness, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(eval_harness, "OLLAMA_MODEL_NAME", "fake-ollama-model")
    monkeypatch.setattr(eval_harness, "GEMINI_MODEL_NAME", "fake-gemini-model")

    with save_report([], backend="gemini", judge_backend="ollama").open(encoding="utf-8") as f:
        report = json.load(f)
    assert report["answer_model"] == "fake-gemini-model"
    assert report["judge_model"] == "fake-ollama-model"


def test_save_report_judge_backend_defaults_to_answer_backend(monkeypatch, tmp_path):
    monkeypatch.setattr(eval_harness, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(eval_harness, "OLLAMA_MODEL_NAME", "fake-ollama-model")

    with save_report([], backend="ollama").open(encoding="utf-8") as f:
        report = json.load(f)
    assert report["judge_model"] == "fake-ollama-model"


# ---------------------------------------------------------------------------
# run_eval — per-question exception isolation. run_eval()'s live agent
# loop is otherwise "live" (real retrieval/LLM calls, exercised by manual
# runs per this file's own top docstring), but once run_agent() is
# mocked, the loop's own control flow is pure/deterministic, so this one
# behavior gets a real unit test rather than only a manual check.
# ---------------------------------------------------------------------------
def test_run_eval_isolates_one_questions_exception_from_the_rest(monkeypatch, tmp_path):
    # Found in code review (2026-09-06): previously, one question raising
    # (e.g. run_agent() exhausting Ollama's retries) killed the whole
    # batch -- no partial report, no flush -- discarding every
    # already-graded result before it.
    questions_path = tmp_path / "questions.jsonl"
    questions_path.write_text(
        "\n".join(
            json.dumps(q)
            for q in [
                {"id": "q1", "question": "Q1?", "type": "numeric", "expected_value": 1, "expected_unit": "raw"},
                {"id": "q2", "question": "Q2?", "type": "numeric", "expected_value": 2, "expected_unit": "raw"},
                {"id": "q3", "question": "Q3?", "type": "numeric", "expected_value": 3, "expected_unit": "raw"},
            ]
        ),
        encoding="utf-8",
    )

    def fake_run_agent(question, backend):
        if question == "Q2?":
            raise RuntimeError("Ollama exhausted retries")
        return AgentResult(f"The answer is {question[1]}.", [], [], None, [])

    monkeypatch.setattr(eval_harness, "run_agent", fake_run_agent)
    flush_calls = []
    monkeypatch.setattr(eval_harness, "flush", lambda: flush_calls.append(1))

    results = run_eval(questions_path)

    assert [r["id"] for r in results] == ["q1", "q2", "q3"]
    assert results[0]["passed"] is True
    assert results[2]["passed"] is True
    assert results[1]["passed"] is False
    assert "RuntimeError" in results[1]["detail"]
    assert "Ollama exhausted retries" in results[1]["detail"]
    # Still flushes and returns a full (partial-failure) report rather
    # than losing everything to the one exception.
    assert flush_calls == [1]
    # The 4 gate-evidence fields (2026-09-10) must exist even on an
    # exception row -- schema consistency matters here because
    # analyze_citation_gate.py reads every row in a report uniformly.
    for r in results:
        assert r["withheld_answer"] is None
        assert r["gate_withheld_would_have_passed"] is None
        assert r["gate_withheld_detail"] is None
        assert r["citation_warning_details"] == []


# ---------------------------------------------------------------------------
# run_eval -- citation-gate evidence fields (2026-09-10, added for the
# FP/FN gate-measurement work, see
# docs/plans/2026-09-10-citation-gate-measurement-instrumentation.md).
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
            {"id": "q1", "question": "Q1?", "type": "numeric", "expected_value": expected_value, "expected_unit": expected_unit}
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
        )

    monkeypatch.setattr(eval_harness, "run_agent", fake_run_agent)

    results = run_eval(questions_path)

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
        )

    monkeypatch.setattr(eval_harness, "run_agent", fake_run_agent)

    results = run_eval(questions_path)

    assert results[0]["passed"] is False
    assert results[0]["withheld_answer"] == "The value was 999."
    assert results[0]["gate_withheld_would_have_passed"] is False


def test_run_eval_gate_fields_are_empty_when_the_gate_never_fired(monkeypatch, tmp_path):
    questions_path = _write_one_numeric_question(tmp_path)

    def fake_run_agent(question, backend):
        return AgentResult("The value was 100 [1].", [{"text": "value = 100 raw"}], [], None, [])

    monkeypatch.setattr(eval_harness, "run_agent", fake_run_agent)

    results = run_eval(questions_path)

    assert results[0]["passed"] is True
    assert results[0]["withheld_answer"] is None
    assert results[0]["gate_withheld_would_have_passed"] is None
    assert results[0]["gate_withheld_detail"] is None
    assert results[0]["citation_warning_details"] == []


def test_run_eval_backend_default_follows_config(monkeypatch, tmp_path):
    # 2026-09-10: run_eval()'s backend default used to be a literal
    # "ollama" bound at function-definition time, ignoring
    # config.DEFAULT_BACKEND entirely -- same fix as run_agent()'s
    # matching test in tests/test_agent.py.
    questions_path = _write_one_numeric_question(tmp_path)
    backends_seen = []

    def fake_run_agent(question, backend):
        backends_seen.append(backend)
        return AgentResult("The value was 100 [1].", [{"text": "value = 100 raw"}], [], None, [])

    monkeypatch.setattr(eval_harness, "run_agent", fake_run_agent)
    monkeypatch.setattr(eval_harness, "DEFAULT_BACKEND", "totally-custom-backend")

    run_eval(questions_path)

    assert backends_seen == ["totally-custom-backend"]
