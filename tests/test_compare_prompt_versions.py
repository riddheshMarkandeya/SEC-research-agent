"""compare_prompt_versions.py -- compares eval runs of one prompt version
against another, implementing the prompt-audit roadmap's decision rule:
screen with fingerprint mode, replicate and attribute with explicit mode.
All tests use synthetic report files; no network or LLM calls."""

import json
from pathlib import Path

import pytest

import compare_prompt_versions as cpv


def _row(qid: str, passed: bool, answer: str | None = "an answer", withheld: bool = False) -> dict:
    return {"id": qid, "passed": passed, "answer": answer, "withheld_answer": withheld}


def _provenance(agent: str = "fpA", judge: str = "j1", sha: str = "sha1", dirty: bool = False, **extra) -> dict:
    return {
        "git_sha": sha,
        "git_dirty": dirty,
        "dirty_files": ["agent.py"] if dirty else [],
        "snapshot_verified": extra.pop("snapshot_verified", True),
        "config": extra.pop("config", {"gemini_model": "m1"}),
        "prompts": {"agent": agent, "judge": judge},
    }


def _write(tmp_path: Path, name: str, rows: list[dict], provenance: dict | None = None, model: str = "m1") -> Path:
    report: dict = {"backend": "gemini", "answer_model": model, "judge_model": model, "results": rows}
    if provenance is not None:
        report["provenance"] = provenance
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    return path


def _reports(tmp_path, specs):
    """specs: list of (name, {qid: passed}, provenance)."""
    paths = [
        _write(tmp_path, name, [_row(q, p) for q, p in results.items()], provenance)
        for name, results, provenance in specs
    ]
    return cpv.load(paths)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------
def test_truncate_at_infra_error_drops_that_row_and_everything_after():
    rows = [_row("a", True), _row("b", False, answer=None), _row("c", True)]
    kept, dropped = cpv.truncate_at_infra_error(rows)
    assert [r["id"] for r in kept] == ["a"]
    assert dropped == 2


def test_load_sorts_by_report_name_and_truncates(tmp_path):
    later = _write(tmp_path, "20260925T000000Z", [_row("a", True)], _provenance())
    earlier = _write(tmp_path, "20260924T000000Z", [_row("a", True), _row("b", True, answer=None)], _provenance())
    reports = cpv.load([later, earlier])
    assert [r.name for r in reports] == ["20260924T000000Z", "20260925T000000Z"]
    assert reports[0].dropped == 1
    assert reports[0].answer_model == "m1"


def test_legacy_list_reports_load_as_unstamped(tmp_path):
    path = tmp_path / "20260801T000000Z.json"
    path.write_text(json.dumps([_row("a", True)]), encoding="utf-8")
    [report] = cpv.load([path])
    assert report.provenance is None
    assert cpv.agent_fingerprint(report) is None


@pytest.mark.parametrize(
    ("provenance", "excluded"),
    [
        (_provenance(), False),
        (_provenance(dirty=True), True),
        (_provenance(snapshot_verified=False), True),
        (_provenance(snapshot_verified=None), True),
        (None, False),
    ],
)
def test_dirty_or_unverified_reports_are_excluded_unless_asked(tmp_path, provenance, excluded):
    [report] = cpv.load([_write(tmp_path, "r", [_row("a", True)], provenance)])
    assert cpv.is_excluded(report, include_dirty=False) is excluded
    assert cpv.is_excluded(report, include_dirty=True) is False


# ---------------------------------------------------------------------------
# Grouping (fingerprint mode)
# ---------------------------------------------------------------------------
def test_grouping_skips_unstamped_and_dirty_reports(tmp_path):
    reports = _reports(
        tmp_path,
        [
            ("20260924T010000Z", {"a": True}, _provenance("fpA")),
            ("20260924T020000Z", {"a": True}, None),
            ("20260924T030000Z", {"a": True}, _provenance("fpB", dirty=True)),
        ],
    )
    groups = cpv.group_by_fingerprint(reports, include_dirty=False)
    assert {k: [r.name for r in v] for k, v in groups.items()} == {"fpA": ["20260924T010000Z"]}


def test_since_drops_older_reports_from_a_shared_fingerprint(tmp_path):
    # A revert restores the base fingerprint, so a re-baseline would
    # otherwise pool with the old runs.
    reports = _reports(
        tmp_path,
        [
            ("20260924T010000Z", {"a": True}, _provenance("fpA")),
            ("20260926T010000Z", {"a": True}, _provenance("fpA")),
        ],
    )
    groups = cpv.group_by_fingerprint(reports, include_dirty=False, since="20260925T000000Z")
    assert [r.name for r in groups["fpA"]] == ["20260926T010000Z"]


def test_default_pair_is_the_two_most_recent_fingerprints(tmp_path):
    reports = _reports(
        tmp_path,
        [
            ("20260924T010000Z", {"a": True}, _provenance("fpA")),
            ("20260924T020000Z", {"a": True}, _provenance("fpB")),
            ("20260924T030000Z", {"a": True}, _provenance("fpC")),
        ],
    )
    groups = cpv.group_by_fingerprint(reports, include_dirty=False)
    assert cpv.default_pair(groups) == ("fpB", "fpC")


def test_default_pair_with_one_group_has_no_base(tmp_path):
    reports = _reports(tmp_path, [("20260924T010000Z", {"a": True}, _provenance("fpA"))])
    assert cpv.default_pair(cpv.group_by_fingerprint(reports, include_dirty=False)) == (None, "fpA")


# ---------------------------------------------------------------------------
# Per-question comparison
# ---------------------------------------------------------------------------
def _runs(tmp_path, prefix, fingerprint, results_per_run):
    """One report per run; results_per_run: list of {qid: passed}."""
    return _reports(
        tmp_path,
        [(f"{prefix}{i}", results, _provenance(fingerprint)) for i, results in enumerate(results_per_run)],
    )


def _row_for(comparison, qid):
    return next(r for r in comparison.rows if r.qid == qid)


@pytest.mark.parametrize(
    ("base_passes", "cand_passes", "flags"),
    [
        ([True, True, True], [True, False, False], ["REGRESSED"]),  # 3/3 -> 1/3: drop 0.67
        ([True, True, False], [False, False, True], ["watch"]),  # 2/3 -> 1/3: drop 0.33
        ([True, False, False], [True, True, True], ["improved", "floor"]),  # base 1/3 is the floor
        ([True, True, True], [True, True, True], []),
    ],
)
def test_question_flags(tmp_path, base_passes, cand_passes, flags):
    base = _runs(tmp_path, "b", "fpA", [{"q": p} for p in base_passes])
    cand = _runs(tmp_path, "c", "fpB", [{"q": p} for p in cand_passes])
    assert _row_for(cpv.compare(base, cand), "q").flags == flags


def test_scaled_delta_and_within_one_pass_use_the_candidates_run_count(tmp_path):
    # Replicate step: B has 3 runs, the fresh candidate runs 6. B's rate
    # 2/3 predicts 4 of 6; 3 of 6 is within one pass, 2 of 6 is not.
    base = _runs(tmp_path, "b", "fpA", [{"q": True}, {"q": True}, {"q": False}])
    within = _runs(tmp_path, "c", "fpA", [{"q": p} for p in [True, True, True, False, False, False]])
    outside = _runs(tmp_path, "d", "fpA", [{"q": p} for p in [True, True, False, False, False, False]])
    row = _row_for(cpv.compare(base, within), "q")
    assert row.scaled_delta == pytest.approx(-1.0)
    assert row.within_one_pass is True
    assert _row_for(cpv.compare(base, outside), "q").within_one_pass is False


def test_withheld_answers_are_counted_per_side(tmp_path):
    base_path = _write(tmp_path, "b0", [_row("q", False, withheld=True)], _provenance("fpA"))
    cand_path = _write(tmp_path, "c0", [_row("q", True)], _provenance("fpB"))
    row = _row_for(cpv.compare(cpv.load([base_path]), cpv.load([cand_path])), "q")
    assert (row.base.withheld, row.candidate.withheld) == (1, 0)


def test_questions_in_only_one_group_are_listed_and_left_out_of_totals(tmp_path):
    base = _runs(tmp_path, "b", "fpA", [{"shared": True, "gone": True}])
    cand = _runs(tmp_path, "c", "fpB", [{"shared": True, "new": False}])
    comparison = cpv.compare(base, cand)
    assert [r.qid for r in comparison.rows] == ["shared"]
    assert comparison.base_only == ["gone"]
    assert comparison.candidate_only == ["new"]
    assert comparison.total.runs == 1


# ---------------------------------------------------------------------------
# Panel total
# ---------------------------------------------------------------------------
def _panel(passing_per_question: dict[str, int], runs: int = 3) -> list[dict]:
    """Per-run results for a panel where question q passes in the first
    passing_per_question[q] runs."""
    return [{q: i < k for q, k in passing_per_question.items()} for i in range(runs)]


def test_total_regresses_when_expected_loss_reaches_the_threshold(tmp_path):
    # 13 questions x 3 runs = 39 candidate runs; ceil(0.14 x 39) = 6.
    questions = [f"q{i}" for i in range(13)]
    base = _runs(tmp_path, "b", "fpA", _panel(dict.fromkeys(questions, 3)))
    losing_six = {q: (2 if i < 6 else 3) for i, q in enumerate(questions)}  # 6 questions each lose one pass
    cand = _runs(tmp_path, "c", "fpB", _panel(losing_six))
    total = cpv.compare(base, cand).total
    assert (total.runs, total.threshold) == (39, 6)
    assert total.expected_loss == pytest.approx(6.0)
    assert total.regressed is True and total.counts is True


def test_total_stays_clear_one_pass_below_the_threshold(tmp_path):
    questions = [f"q{i}" for i in range(13)]
    base = _runs(tmp_path, "b", "fpA", _panel(dict.fromkeys(questions, 3)))
    losing_five = {q: (2 if i < 5 else 3) for i, q in enumerate(questions)}
    assert cpv.compare(base, _runs(tmp_path, "c", "fpB", _panel(losing_five))).total.regressed is False


def test_small_comparisons_report_the_total_without_failing_on_it(tmp_path):
    # Fewer than 20 candidate runs (a replicate of flagged questions only):
    # ceil(0.14 x N) is as low as 1, so one lost pass would trip it.
    base = _runs(tmp_path, "b", "fpA", [{"q": True}] * 3)
    cand = _runs(tmp_path, "c", "fpB", [{"q": True}, {"q": True}, {"q": False}])
    comparison = cpv.compare(base, cand)
    assert comparison.total.regressed is True
    assert comparison.total.counts is False
    assert cpv.exit_code(comparison) == 0


def test_exit_code_is_one_for_any_regressed_question(tmp_path):
    base = _runs(tmp_path, "b", "fpA", [{"q": True}] * 3)
    cand = _runs(tmp_path, "c", "fpB", [{"q": False}] * 3)
    assert cpv.exit_code(cpv.compare(base, cand)) == 1


# ---------------------------------------------------------------------------
# Consistency warnings
# ---------------------------------------------------------------------------
def test_warns_when_a_group_spans_several_shas(tmp_path):
    base = _reports(
        tmp_path,
        [
            ("b0", {"q": True}, _provenance("fpA", sha="s1")),
            ("b1", {"q": True}, _provenance("fpA", sha="s2")),
        ],
    )
    cand = _runs(tmp_path, "c", "fpB", [{"q": True}])
    assert any("SHA" in w and "base" in w for w in cpv.compare(base, cand).warnings)


def test_warns_on_judge_model_or_config_differences_within_and_between_groups(tmp_path):
    base = _reports(
        tmp_path,
        [
            ("b0", {"q": True}, _provenance("fpA", judge="j1")),
            ("b1", {"q": True}, _provenance("fpA", judge="j2")),
        ],
    )
    cand_path = _write(tmp_path, "c0", [_row("q", True)], _provenance("fpB", config={"gemini_model": "m2"}), "m2")
    warnings = cpv.compare(base, cpv.load([cand_path])).warnings
    text = "\n".join(warnings)
    assert "judge" in text and "answer_model" in text and "config" in text


def test_no_warnings_for_consistent_groups(tmp_path):
    base = _runs(tmp_path, "b", "fpA", [{"q": True}] * 2)
    cand = _runs(tmp_path, "c", "fpB", [{"q": True}] * 2)
    assert cpv.compare(base, cand).warnings == []


# ---------------------------------------------------------------------------
# Output and CLI
# ---------------------------------------------------------------------------
def test_format_comparison_shows_groups_rows_total_and_warnings(tmp_path):
    base = _runs(tmp_path, "b", "fpA", [{"q": True}] * 3)
    cand = _runs(tmp_path, "c", "fpB", [{"q": False}] * 3)
    text = cpv.format_comparison(cpv.compare(base, cand), base, cand)
    assert "fpA" in text and "fpB" in text
    assert "3/3" in text and "0/3" in text and "REGRESSED" in text
    assert "REGRESSED-TOTAL" in text


def test_main_fingerprint_mode_compares_the_two_latest_groups(tmp_path, capsys):
    for i, passed in enumerate([True, True, True]):
        _write(tmp_path, f"20260924T00000{i}Z", [_row("q", passed)], _provenance("fpA"))
    for i, passed in enumerate([False, False, False]):
        _write(tmp_path, f"20260925T00000{i}Z", [_row("q", passed)], _provenance("fpB"))
    code = cpv.main([str(p) for p in sorted(tmp_path.glob("*.json"))])
    out = capsys.readouterr().out
    assert code == 1
    assert "base fpA" in out and "candidate fpB" in out


def test_main_with_one_group_prints_its_table_and_exits_zero(tmp_path, capsys):
    for i, passed in enumerate([True, False, True]):
        _write(tmp_path, f"20260924T00000{i}Z", [_row("q", passed)], _provenance("fpA"))
    code = cpv.main([str(p) for p in tmp_path.glob("*.json")])
    out = capsys.readouterr().out
    assert code == 0
    assert "fpA" in out and "2/3" in out


def test_main_explicit_mode_compares_the_given_files(tmp_path, capsys):
    base = [_write(tmp_path, f"b{i}", [_row("q", True)], _provenance("fpA")) for i in range(3)]
    cand = [_write(tmp_path, f"c{i}", [_row("q", True)], None) for i in range(3)]
    args = ["--base-files", *map(str, base), "--candidate-files", *map(str, cand)]
    assert cpv.main(args) == 0
    assert "3/3" in capsys.readouterr().out


def test_main_with_no_stamped_reports_says_so(tmp_path, capsys):
    _write(tmp_path, "r", [_row("q", True)], None)
    assert cpv.main([str(tmp_path / "r.json")]) == 0
    assert "No stamped" in capsys.readouterr().out


def test_main_rejects_an_unknown_fingerprint(tmp_path, capsys):
    _write(tmp_path, "r", [_row("q", True)], _provenance("fpA"))
    assert cpv.main([str(tmp_path / "r.json"), "--candidate", "nope"]) == 2
    assert "nope" in capsys.readouterr().out


def test_format_comparison_lists_one_sided_questions_and_dropped_rows(tmp_path):
    base_path = _write(tmp_path, "b0", [_row("shared", True), _row("gone", True)], _provenance("fpA"))
    cand_path = _write(
        tmp_path, "c0", [_row("shared", True), _row("new", True), _row("late", True, answer=None)], _provenance("fpB")
    )
    base, cand = cpv.load([base_path]), cpv.load([cand_path])
    text = cpv.format_comparison(cpv.compare(base, cand), base, cand)
    assert "only in base (left out of the total): gone" in text
    assert "only in candidate (left out of the total): new" in text
    assert "1 row(s) dropped at infra errors" in text


def test_main_explicit_mode_needs_both_sides(tmp_path, capsys):
    base = _write(tmp_path, "b0", [_row("q", True)], _provenance("fpA"))
    assert cpv.main(["--base-files", str(base)]) == 2
    assert "both" in capsys.readouterr().out

