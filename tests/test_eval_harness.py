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
from eval_harness import (
    _select_questions,
    grade_comparison,
    grade_judged,
    grade_numeric,
    load_questions,
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
# grade_judged — mocked Ollama call, testing only the response parsing
# ---------------------------------------------------------------------------
class _FakeResponse:
    def __init__(self, content: str):
        self._content = content

    def raise_for_status(self):
        pass

    def json(self):
        return {"message": {"content": self._content}}


def test_grade_judged_parses_pass(monkeypatch):
    monkeypatch.setattr(
        "eval_harness.requests.post",
        lambda *a, **k: _FakeResponse("PASS\nThe answer clearly satisfies the criteria."),
    )
    passed, reason = grade_judged("Q?", "some answer", "some criteria")
    assert passed is True
    assert reason == "The answer clearly satisfies the criteria."


def test_grade_judged_parses_fail(monkeypatch):
    monkeypatch.setattr(
        "eval_harness.requests.post",
        lambda *a, **k: _FakeResponse("FAIL\nThe answer does not mention the required risk."),
    )
    passed, reason = grade_judged("Q?", "some answer", "some criteria")
    assert passed is False
    assert reason == "The answer does not mention the required risk."


def test_grade_judged_lowercase_pass_still_counts(monkeypatch):
    monkeypatch.setattr(
        "eval_harness.requests.post",
        lambda *a, **k: _FakeResponse("pass\nfine."),
    )
    passed, _ = grade_judged("Q?", "some answer", "some criteria")
    assert passed is True


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


def test_save_report_records_judge_model_as_ollama_regardless_of_backend(monkeypatch, tmp_path):
    # grade_judged() always calls Ollama directly (see its own docstring/
    # PROJECT_CONTEXT.md) regardless of --backend -- the report should
    # say so explicitly rather than leaving it implicit and easy to miss.
    monkeypatch.setattr(eval_harness, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(eval_harness, "OLLAMA_MODEL_NAME", "fake-ollama-model")

    with save_report([], backend="gemini").open(encoding="utf-8") as f:
        gemini_report = json.load(f)

    assert gemini_report["judge_model"] == "fake-ollama-model"
