"""
Unit tests for analyze_flakiness.py -- entirely pure (loads/aggregates
already-written report dicts, no network/LLM beyond synthetic tmp_path
JSON files for load_rows()), so this is full TDD, no live/manual
counterpart needed.
"""

import json

import pytest

from sec_agent.devtools.analyze_flakiness import (
    ClassificationThresholds,
    _count_transitions,
    _trailing_fail_streak,
    _trailing_pass_streak,
    _wilson_interval,
    classify_history,
    format_summary,
    is_infra_error,
    load_reports,
    load_rows,
    summarize,
)


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
    """The shape eval_harness.py's _run_one() records from its broad
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
# ClassificationThresholds
# ---------------------------------------------------------------------------
def test_classification_thresholds_rejects_a_non_positive_window():
    # history[-window:] silently means "the whole list" for window<=0
    # (Python slicing: -0 == 0) -- reject rather than silently classify
    # on unbounded history when a caller asks for window=0.
    with pytest.raises(ValueError, match="window"):
        ClassificationThresholds(window=0)


def test_classification_thresholds_rejects_a_non_positive_min_appearances():
    with pytest.raises(ValueError, match="min_appearances"):
        ClassificationThresholds(min_appearances=0)


def test_classification_thresholds_rejects_a_non_positive_regression_streak():
    # regression_streak=0 would make fail_streak>=0 always true,
    # classifying even a perfect all-pass history as "regression".
    with pytest.raises(ValueError, match="regression_streak"):
        ClassificationThresholds(regression_streak=0)


def test_classification_thresholds_rejects_a_non_positive_flaky_min_transitions():
    with pytest.raises(ValueError, match="flaky_min_transitions"):
        ClassificationThresholds(flaky_min_transitions=0)


def test_classification_thresholds_rejects_a_solid_floor_outside_zero_one():
    with pytest.raises(ValueError, match="solid_floor"):
        ClassificationThresholds(solid_floor=1.5)


def test_classification_thresholds_rejects_a_mostly_failing_ceiling_outside_zero_one():
    with pytest.raises(ValueError, match="mostly_failing_ceiling"):
        ClassificationThresholds(mostly_failing_ceiling=1.5)


def test_classification_thresholds_rejects_a_mostly_failing_ceiling_not_below_solid_floor():
    # If the ceiling isn't strictly below the floor, every pass_rate the
    # ceiling check ever sees (already <solid_floor by branch order) is
    # automatically below the ceiling too -- silently eliminating the
    # "flaky" catch-all branch for every ambiguous case.
    with pytest.raises(ValueError, match="mostly_failing_ceiling"):
        ClassificationThresholds(solid_floor=0.80, mostly_failing_ceiling=0.80)


def test_classification_thresholds_rejects_a_non_positive_confidence_z():
    # _wilson_interval's margin flips sign for a negative z, returning an
    # inverted (lower > upper) interval.
    with pytest.raises(ValueError, match="confidence_z"):
        ClassificationThresholds(confidence_z=-1.96)


# ---------------------------------------------------------------------------
# _trailing_fail_streak / _trailing_pass_streak
# ---------------------------------------------------------------------------
def test_trailing_fail_streak_zero_when_last_run_passed():
    assert _trailing_fail_streak([False, False, True]) == 0


def test_trailing_fail_streak_counts_consecutive_fails_from_the_end():
    assert _trailing_fail_streak([True, True, False, False, False]) == 3


def test_trailing_fail_streak_full_length_when_all_fail():
    assert _trailing_fail_streak([False, False, False]) == 3


def test_trailing_pass_streak_zero_when_last_run_failed():
    assert _trailing_pass_streak([True, True, False]) == 0


def test_trailing_pass_streak_counts_consecutive_passes_from_the_end():
    assert _trailing_pass_streak([False, False, True, True, True]) == 3


def test_trailing_pass_streak_full_length_when_all_pass():
    assert _trailing_pass_streak([True, True, True]) == 3


# ---------------------------------------------------------------------------
# _count_transitions
# ---------------------------------------------------------------------------
def test_count_transitions_zero_for_all_pass():
    assert _count_transitions([True, True, True]) == 0


def test_count_transitions_single_blip_has_two_transitions():
    # A single isolated failure amid passes: pass->fail, fail->pass.
    assert _count_transitions([True, True, False, True, True]) == 2


def test_count_transitions_counts_each_pass_fail_flip():
    assert _count_transitions([True, False, True, False, True]) == 4


# ---------------------------------------------------------------------------
# _wilson_interval
# ---------------------------------------------------------------------------
def test_wilson_interval_matches_hand_computed_reference_value():
    # 19/20 -- a single isolated failure in a 20-run window -- has a 95%
    # Wilson lower bound of only ~0.76, well below a typical 0.80-0.85
    # solid floor even though the raw fraction (95%) looks fine; this is
    # exactly why Wilson isn't used to gate classification (see
    # classify_history's docstring).
    lower, upper = _wilson_interval(19, 20, z=1.96)
    assert lower == pytest.approx(0.7639, abs=1e-3)
    assert upper == pytest.approx(0.9911, abs=1e-3)


def test_wilson_interval_widens_as_total_shrinks_for_the_same_fraction():
    small_n_lower, small_n_upper = _wilson_interval(19, 20, z=1.96)
    large_n_lower, large_n_upper = _wilson_interval(95, 100, z=1.96)  # same 95% fraction, larger n
    assert (small_n_upper - small_n_lower) > (large_n_upper - large_n_lower)


def test_wilson_interval_degenerate_zero_total_does_not_raise():
    assert _wilson_interval(0, 0, z=1.96) == (0.0, 0.0)


# ---------------------------------------------------------------------------
# classify_history
# ---------------------------------------------------------------------------
def test_classify_history_insufficient_data_below_min_appearances():
    result = classify_history([True, True], ClassificationThresholds())
    assert result["classification"] == "insufficient-data"


def test_classify_history_all_pass_is_solid():
    result = classify_history([True] * 20, ClassificationThresholds())
    assert result["classification"] == "solid"


def test_classify_history_single_isolated_failure_at_the_min_appearances_boundary_is_still_solid():
    # The exact case independent review found broken at the original
    # solid_floor=0.85 default: 4/5 = 0.80 exactly.
    result = classify_history([True, True, True, True, False], ClassificationThresholds())
    assert result["classification"] == "solid"


def test_classify_history_single_isolated_failure_in_a_larger_window_is_still_solid():
    history = [True] * 9 + [False] + [True] * 10
    result = classify_history(history, ClassificationThresholds())
    assert result["classification"] == "solid"


def test_classify_history_alternating_pattern_is_flaky():
    result = classify_history([True, False] * 5, ClassificationThresholds())
    assert result["classification"] == "flaky"


def test_classify_history_all_pass_then_all_fail_is_regression():
    result = classify_history([True] * 10 + [False] * 10, ClassificationThresholds())
    assert result["classification"] == "regression"


def test_classify_history_recovery_after_a_long_failing_run_is_solid_not_regression():
    # The exact counterexample independent review found against the
    # original 5-branch design: a long-past outage, since fixed.
    history = [False] * 14 + [True] * 6
    result = classify_history(history, ClassificationThresholds())
    assert result["classification"] == "solid"


def test_classify_history_short_trailing_fail_run_below_streak_threshold_is_not_regression():
    history = [True] * 10 + [False] * 3  # streak 3 < default regression_streak 5
    result = classify_history(history, ClassificationThresholds())
    assert result["classification"] != "regression"


def test_classify_history_mostly_failing_scattered_with_no_clean_streak_falls_back_to_regression():
    history = [False, False, False, False, True, False, False, False, False]
    result = classify_history(history, ClassificationThresholds(min_appearances=5))
    assert result["classification"] == "regression"


def test_classify_history_longer_than_window_uses_only_the_windowed_tail():
    history = [False] * 30 + [True] * 20
    result = classify_history(history, ClassificationThresholds(window=20))
    assert result["classification"] == "solid"
    assert result["windowed_total"] == 20


def test_classify_history_window_can_make_a_long_all_time_history_read_as_insufficient_data():
    history = [True] * 10
    result = classify_history(history, ClassificationThresholds(window=3, min_appearances=5))
    assert result["classification"] == "insufficient-data"


def test_classify_history_custom_thresholds_change_the_outcome():
    history = [True] * 4 + [False]  # 4/5 = 0.80
    default_result = classify_history(history, ClassificationThresholds())
    assert default_result["classification"] == "solid"
    stricter_result = classify_history(history, ClassificationThresholds(solid_floor=0.95))
    assert stricter_result["classification"] != "solid"


def test_classify_history_exactly_regression_streak_fails_is_regression():
    history = [True] * 5 + [False] * 5  # exactly the default regression_streak
    result = classify_history(history, ClassificationThresholds())
    assert result["classification"] == "regression"


def test_classify_history_one_fewer_than_regression_streak_fails_is_not_regression():
    history = [True] * 5 + [False] * 4  # one fewer than the default regression_streak
    result = classify_history(history, ClassificationThresholds())
    assert result["classification"] != "regression"


def test_classify_history_exactly_flaky_min_transitions_is_flaky():
    # 3 transitions, pass_rate below the solid floor, no active streak.
    history = [True, True, False, True, True, False]
    assert _count_transitions(history) == 3
    result = classify_history(history, ClassificationThresholds(min_appearances=5))
    assert result["classification"] == "flaky"


def test_classify_history_one_fewer_than_flaky_min_transitions_is_not_flaky_by_oscillation():
    # 2 transitions (a single isolated blip) -- must be caught by the
    # solid-floor branch instead, not by oscillation.
    history = [True] * 4 + [False] + [True] * 15
    assert _count_transitions(history) == 2
    result = classify_history(history, ClassificationThresholds())
    assert result["classification"] == "solid"


def test_classify_history_pass_rate_exactly_at_solid_floor_is_solid():
    history = [True] * 4 + [False]  # 4/5 = 0.80, the default solid_floor exactly
    result = classify_history(history, ClassificationThresholds())
    assert result["windowed_pass_rate"] == pytest.approx(0.80)
    assert result["classification"] == "solid"


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
    assert summary["questions"]["q1"] == {
        "type": "numeric",
        "passed": 1,
        "total": 2,
        "pass_rate": 0.5,
        "history": [True, False],
    }


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
    assert summary["questions"]["q1"]["history"] == [True]
    assert summary["questions"]["q2"]["history"] == [False]


def test_summarize_includes_ordered_history_per_question():
    rows = [
        _row(id="q1", passed=True),
        _row(id="q1", passed=False),
        _row(id="q1", passed=True),
    ]
    summary = summarize(rows)
    assert summary["questions"]["q1"]["history"] == [True, False, True]


# ---------------------------------------------------------------------------
# format_summary
# ---------------------------------------------------------------------------
def _question_entry(qtype: str, history: list[bool]) -> dict:
    passed = sum(history)
    total = len(history)
    return {"type": qtype, "passed": passed, "total": total, "pass_rate": passed / total, "history": history}


def test_format_summary_has_a_regression_section_for_a_currently_broken_question():
    summary = {
        "questions": {"broken": _question_entry("numeric", [True] * 10 + [False] * 10)},
        "excluded_by_error_type": {},
    }
    output = format_summary(summary)
    assert "Regression" in output
    assert "broken" in output


def test_format_summary_has_a_flaky_section_for_an_alternating_question():
    summary = {
        "questions": {"unstable": _question_entry("numeric", [True, False] * 5)},
        "excluded_by_error_type": {},
    }
    output = format_summary(summary)
    assert "Flaky" in output
    assert "unstable" in output


def test_format_summary_has_a_solid_section_for_a_reliable_question():
    summary = {
        "questions": {"reliable": _question_entry("numeric", [True] * 20)},
        "excluded_by_error_type": {},
    }
    output = format_summary(summary)
    assert "Solid" in output
    assert "reliable" in output


def test_format_summary_has_an_insufficient_data_section_for_a_short_history():
    summary = {
        "questions": {"too_new": _question_entry("numeric", [True, True])},
        "excluded_by_error_type": {},
    }
    output = format_summary(summary)
    assert "Insufficient data" in output
    assert "too_new" in output  # NOT dropped, unlike the old hard min_appearances exclusion


def test_format_summary_each_question_appears_in_exactly_one_section():
    summary = {
        "questions": {
            "broken": _question_entry("numeric", [True] * 10 + [False] * 10),
            "unstable": _question_entry("numeric", [True, False] * 5),
            "reliable": _question_entry("numeric", [True] * 20),
            "too_new": _question_entry("numeric", [True, True]),
        },
        "excluded_by_error_type": {},
    }
    output = format_summary(summary)
    for qid in summary["questions"]:
        assert output.count(qid) == 1


def test_format_summary_still_reports_all_time_n_runs_alongside_windowed_numbers():
    history = [False] * 30 + [True] * 20  # 50 all-time runs, only last 20 windowed
    summary = {"questions": {"long_history": _question_entry("numeric", history)}, "excluded_by_error_type": {}}
    output = format_summary(summary)
    assert "all_time_n=50" in output


def test_format_summary_custom_thresholds_change_grouping():
    # 4/5 = 0.80 clears the default solid_floor but not a stricter one --
    # the single question's own section header changes accordingly.
    summary = {"questions": {"borderline": _question_entry("numeric", [True] * 4 + [False])}, "excluded_by_error_type": {}}

    default_output = format_summary(summary)
    assert "Solid" in default_output
    assert "Flaky" not in default_output

    stricter_output = format_summary(summary, ClassificationThresholds(solid_floor=0.95))
    assert "Flaky" in stricter_output
    assert "Solid" not in stricter_output


def test_format_summary_ci_label_reflects_the_actual_confidence_z_used():
    summary = {"questions": {"reliable": _question_entry("numeric", [True] * 20)}, "excluded_by_error_type": {}}

    default_output = format_summary(summary)
    assert "95% CI" in default_output

    custom_output = format_summary(summary, ClassificationThresholds(confidence_z=1.645))
    assert "90% CI" in custom_output
    assert "95% CI" not in custom_output


def test_format_summary_reports_excluded_error_types():
    summary = {"questions": {}, "excluded_by_error_type": {"ClientError": 3}}
    output = format_summary(summary, ClassificationThresholds(min_appearances=1))
    assert "Excluded 3 infra-error row(s)" in output
    assert "ClientError" in output


def test_format_summary_omits_excluded_line_when_nothing_was_excluded():
    summary = {
        "questions": {"q1": _question_entry("numeric", [True])},
        "excluded_by_error_type": {},
    }
    output = format_summary(summary, ClassificationThresholds(min_appearances=1))
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


# ---------------------------------------------------------------------------
# load_reports -- whole reports, keeping the report-level fields (backend,
# models, provenance) that load_rows drops; compare_prompt_versions.py
# groups by them.
# ---------------------------------------------------------------------------
def test_load_reports_keeps_report_level_fields(tmp_path):
    report = tmp_path / "a.json"
    report.write_text(
        json.dumps({"backend": "gemini", "provenance": {"git_sha": "abc"}, "results": [_row(id="a1")]}),
        encoding="utf-8",
    )

    [loaded] = load_reports([report])

    assert loaded["provenance"] == {"git_sha": "abc"}
    assert [r["id"] for r in loaded["results"]] == ["a1"]


def test_load_reports_wraps_a_bare_list_report(tmp_path):
    report = tmp_path / "old.json"
    report.write_text(json.dumps([_row(id="old1")]), encoding="utf-8")

    assert load_reports([report]) == [{"results": [_row(id="old1")]}]
