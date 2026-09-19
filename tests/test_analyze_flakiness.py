"""
Unit tests for analyze_flakiness.py -- entirely pure (loads/aggregates
already-written report dicts, no network/LLM beyond synthetic tmp_path
JSON files for load_rows()), so this is full TDD, no live/manual
counterpart needed.
"""

import json

from analyze_flakiness import format_summary, is_infra_error, load_rows, summarize


def _row(**overrides):
    """A normal, successfully-graded row (the common case), plus
    whatever the caller overrides."""
    base = {
        "id": "q1",
        "type": "numeric",
        "passed": True,
        "detail": "found matching value: 100.0 (raw)",
        "answer": "The value was 100 [1].",
    }
    base.update(overrides)
    return base


def _infra_error_row(qid="q1", exception="ClientError: 429 RESOURCE_EXHAUSTED. {...}"):
    """The shape eval_harness.py's run_eval() records from its broad
    except-Exception handler -- answer=None, detail=the exception repr."""
    return {"id": qid, "type": "numeric", "passed": False, "detail": exception, "answer": None}


# ---------------------------------------------------------------------------
# is_infra_error
# ---------------------------------------------------------------------------
def test_is_infra_error_true_when_answer_is_none():
    assert is_infra_error(_infra_error_row()) is True


def test_is_infra_error_false_for_a_normal_passing_row():
    assert is_infra_error(_row(passed=True)) is False


def test_is_infra_error_false_for_a_normal_failing_row_with_a_real_answer():
    # A genuine agent refusal still sets a real answer string (the
    # refusal message) -- only the broad except-Exception path leaves
    # answer=None.
    assert is_infra_error(_row(passed=False, answer="I can't confirm this answer...")) is False


# ---------------------------------------------------------------------------
# summarize
# ---------------------------------------------------------------------------
def test_summarize_computes_pass_rate_excluding_infra_error_rows():
    rows = [
        _row(id="q1", passed=True),
        _row(id="q1", passed=False),
        _infra_error_row(qid="q1"),  # must not count in either numerator or denominator
    ]
    summary = summarize(rows)
    assert summary["questions"]["q1"] == {"type": "numeric", "passed": 1, "total": 2, "pass_rate": 0.5}


def test_summarize_tracks_excluded_error_types_separately():
    rows = [
        _infra_error_row(qid="q1", exception="ClientError: 429 RESOURCE_EXHAUSTED. {...}"),
        _infra_error_row(qid="q2", exception="ClientError: 429 RESOURCE_EXHAUSTED. {...}"),
        _infra_error_row(qid="q3", exception="ConnectionError: timed out"),
    ]
    summary = summarize(rows)
    assert summary["questions"] == {}
    assert summary["excluded_by_error_type"] == {"ClientError": 2, "ConnectionError": 1}


def test_summarize_handles_a_detail_string_with_no_colon():
    row = _infra_error_row(exception="something went wrong")
    summary = summarize([row])
    assert summary["excluded_by_error_type"] == {"unknown": 1}


def test_summarize_keeps_questions_independent():
    rows = [_row(id="q1", passed=True), _row(id="q2", passed=False)]
    summary = summarize(rows)
    assert summary["questions"]["q1"]["pass_rate"] == 1.0
    assert summary["questions"]["q2"]["pass_rate"] == 0.0


# ---------------------------------------------------------------------------
# format_summary
# ---------------------------------------------------------------------------
def test_format_summary_ranks_flakiest_first():
    summary = {
        "questions": {
            "reliable": {"type": "numeric", "passed": 10, "total": 10, "pass_rate": 1.0},
            "flaky": {"type": "numeric", "passed": 3, "total": 10, "pass_rate": 0.3},
        },
        "excluded_by_error_type": {},
    }
    output = format_summary(summary, min_appearances=1)
    assert output.index("flaky") < output.index("reliable")


def test_format_summary_excludes_questions_below_min_appearances():
    summary = {
        "questions": {
            "well_measured": {"type": "numeric", "passed": 1, "total": 5, "pass_rate": 0.2},
            "too_few_runs": {"type": "numeric", "passed": 0, "total": 2, "pass_rate": 0.0},
        },
        "excluded_by_error_type": {},
    }
    output = format_summary(summary, min_appearances=5)
    assert "well_measured" in output
    assert "too_few_runs" not in output


def test_format_summary_reports_excluded_error_types():
    summary = {"questions": {}, "excluded_by_error_type": {"ClientError": 3}}
    output = format_summary(summary, min_appearances=1)
    assert "Excluded 3 infra-error row(s)" in output
    assert "ClientError" in output


def test_format_summary_omits_excluded_line_when_nothing_was_excluded():
    summary = {
        "questions": {"q1": {"type": "numeric", "passed": 1, "total": 5, "pass_rate": 0.2}},
        "excluded_by_error_type": {},
    }
    output = format_summary(summary, min_appearances=1)
    assert "Excluded" not in output


# ---------------------------------------------------------------------------
# load_rows
# ---------------------------------------------------------------------------
def test_load_rows_handles_dict_wrapped_reports(tmp_path):
    report = tmp_path / "a.json"
    report.write_text(json.dumps({"backend": "gemini", "results": [_row(id="a1"), _row(id="a2")]}), encoding="utf-8")

    rows = load_rows([report])

    assert [r["id"] for r in rows] == ["a1", "a2"]


def test_load_rows_handles_bare_list_reports(tmp_path):
    # This project's own pre-2026-08-21 report files -- no "backend"/
    # "results" wrapper at all, just a top-level JSON list.
    report = tmp_path / "old.json"
    report.write_text(json.dumps([_row(id="old1"), _row(id="old2")]), encoding="utf-8")

    rows = load_rows([report])

    assert [r["id"] for r in rows] == ["old1", "old2"]


def test_load_rows_concatenates_mixed_formats_across_files(tmp_path):
    old = tmp_path / "old.json"
    old.write_text(json.dumps([_row(id="old1")]), encoding="utf-8")
    new = tmp_path / "new.json"
    new.write_text(json.dumps({"backend": "gemini", "results": [_row(id="new1")]}), encoding="utf-8")

    rows = load_rows([old, new])

    assert [r["id"] for r in rows] == ["old1", "new1"]
