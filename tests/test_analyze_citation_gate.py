"""
Unit tests for analyze_citation_gate.py -- entirely pure (loads/classifies
already-written report dicts, no network/LLM/filesystem beyond a synthetic
tmp_path JSON file for load_rows()), so this is full TDD, no live/manual
counterpart needed.
"""

import json

from analyze_citation_gate import classify_row, load_rows, summarize


def _row(**overrides):
    """A numeric-question row with every gate field present (the
    post-instrumentation schema, see eval_harness.py's
    _citation_gate_evidence()/_EMPTY_CITATION_GATE_EVIDENCE), plus
    whatever the caller overrides."""
    base = {
        "id": "q1",
        "ticker": "AAPL",
        "question": "What was it?",
        "type": "numeric",
        "passed": True,
        "detail": "found matching value: 100.0 (raw)",
        "has_citation": True,
        "citation_warnings": [],
        "answer": "The value was 100 [1].",
        "n_chunks_retrieved": 1,
        "withheld_answer": None,
        "gate_withheld_would_have_passed": None,
        "gate_withheld_detail": None,
        "citation_warning_details": [],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# classify_row
# ---------------------------------------------------------------------------
def test_classify_row_false_positive_when_gate_refused_a_correct_answer():
    row = _row(
        passed=False,
        has_citation=False,
        citation_warnings=["claims 100.0 (raw) but no citation marker appears anywhere near it..."],
        withheld_answer="The value was 100.",
        gate_withheld_would_have_passed=True,
        gate_withheld_detail="found matching value: 100.0 (raw)",
        citation_warning_details=[
            {"check": "uncited_claim", "citation_index": None, "value": 100.0, "unit": "raw", "message": "..."}
        ],
    )
    assert classify_row(row) == "false_positive"


def test_classify_row_true_positive_when_gate_correctly_refused_a_wrong_answer():
    row = _row(
        passed=False,
        has_citation=False,
        citation_warnings=["claims 999.0 (raw) but no citation marker appears anywhere near it..."],
        withheld_answer="The value was 999.",
        gate_withheld_would_have_passed=False,
        gate_withheld_detail="no value matching 100 raw found in answer",
        citation_warning_details=[
            {"check": "uncited_claim", "citation_index": None, "value": 999.0, "unit": "raw", "message": "..."}
        ],
    )
    assert classify_row(row) == "true_positive"


def test_classify_row_false_negative_candidate_when_gate_passed_a_wrong_cited_answer():
    row = _row(passed=False, has_citation=True, citation_warnings=[])
    assert classify_row(row) == "false_negative_candidate"


def test_classify_row_not_gate_attributable_for_a_correct_passing_answer():
    row = _row(passed=True, has_citation=True, citation_warnings=[])
    assert classify_row(row) == "not_gate_attributable"


def test_classify_row_not_gate_attributable_when_failed_with_no_citation_at_all():
    # Failed, but not because of a citation-grounding problem the gate
    # could ever have caught -- e.g. the model retrieved nothing relevant
    # and gave a plain uncited wrong answer. Distinct from the FN case,
    # which specifically requires has_citation=True.
    row = _row(passed=False, has_citation=False, citation_warnings=[])
    assert classify_row(row) == "not_gate_attributable"


def test_classify_row_excluded_for_judged_questions_regardless_of_other_fields():
    row = _row(type="judged", passed=False, has_citation=False)
    assert classify_row(row) == "excluded"


def test_classify_row_unknown_pre_instrumentation_for_a_legacy_row_missing_gate_fields():
    # A report written before 2026-09-10 has none of the 4 new keys at
    # all -- must be excluded from denominators, not crash and not be
    # silently counted as a pass.
    legacy_row = {
        "id": "q1",
        "ticker": "AAPL",
        "question": "What was it?",
        "type": "numeric",
        "passed": True,
        "detail": "found matching value: 100.0 (raw)",
        "has_citation": True,
        "citation_warnings": [],
        "answer": "The value was 100 [1].",
        "n_chunks_retrieved": 1,
    }
    assert classify_row(legacy_row) == "unknown_pre_instrumentation"


# ---------------------------------------------------------------------------
# summarize
# ---------------------------------------------------------------------------
def test_summarize_counts_and_rates_across_a_mixed_batch():
    rows = [
        _row(
            id="fp1",
            passed=False,
            has_citation=False,
            citation_warnings=["w"],
            withheld_answer="a",
            gate_withheld_would_have_passed=True,
            citation_warning_details=[{"check": "uncited_claim"}],
        ),
        _row(
            id="fp2",
            passed=False,
            has_citation=False,
            citation_warnings=["w"],
            withheld_answer="a",
            gate_withheld_would_have_passed=True,
            citation_warning_details=[{"check": "cited_claim_unsupported"}],
        ),
        _row(
            id="tp1",
            passed=False,
            has_citation=False,
            citation_warnings=["w"],
            withheld_answer="a",
            gate_withheld_would_have_passed=False,
            citation_warning_details=[{"check": "uncited_claim"}],
        ),
        _row(id="fn1", passed=False, has_citation=True, citation_warnings=[]),
        _row(id="pass1", passed=True, has_citation=True, citation_warnings=[]),
        _row(id="judged1", type="judged", passed=True),
        {
            "id": "legacy1",
            "type": "numeric",
            "passed": True,
            "has_citation": True,
            "citation_warnings": [],
        },
    ]

    summary = summarize(rows)

    assert summary["total_rows"] == 7
    assert summary["excluded_judged"] == 1
    assert summary["unknown_pre_instrumentation"] == 1
    assert summary["gate_refused"] == 3
    assert summary["false_positive"] == 2
    assert summary["true_positive"] == 1
    assert summary["false_positive_rate"] == 2 / 3
    assert summary["false_negative_candidate"] == 1
    assert summary["not_gate_attributable"] == 1
    assert summary["false_positive_by_check"] == {"uncited_claim": 1, "cited_claim_unsupported": 1}
    assert summary["false_positive_ids"] == ["fp1", "fp2"]
    assert summary["false_negative_candidate_ids"] == ["fn1"]


def test_summarize_false_positive_rate_is_none_when_gate_never_fired():
    rows = [_row(id="pass1", passed=True, has_citation=True, citation_warnings=[])]
    summary = summarize(rows)
    assert summary["gate_refused"] == 0
    assert summary["false_positive_rate"] is None


# ---------------------------------------------------------------------------
# load_rows
# ---------------------------------------------------------------------------
def test_load_rows_concatenates_results_across_multiple_report_files(tmp_path):
    report_a = tmp_path / "a.json"
    report_a.write_text(json.dumps({"backend": "gemini", "results": [_row(id="a1")]}), encoding="utf-8")
    report_b = tmp_path / "b.json"
    report_b.write_text(json.dumps({"backend": "gemini", "results": [_row(id="b1"), _row(id="b2")]}), encoding="utf-8")

    rows = load_rows([report_a, report_b])

    assert [r["id"] for r in rows] == ["a1", "b1", "b2"]
