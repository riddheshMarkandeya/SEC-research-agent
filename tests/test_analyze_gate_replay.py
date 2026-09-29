import hashlib
import json
from pathlib import Path

import pytest

import agent
import analyze_gate_replay as replay
import tracing
from analyze_gate_replay import (
    RunFilter,
    RunTrace,
    compare_failed,
    fidelity,
    format_summary,
    group_runs,
    grade,
    memoized,
    rebuild_results,
    replay_run,
    require_repo_root,
    summarize,
)


def _span(run_id, name, input=None, output=None, **overrides):
    return {
        "timestamp": "2026-09-20T00:00:00",
        "run_id": run_id,
        "as_type": "tool",
        "name": name,
        "input": input or {},
        "output": output,
        **overrides,
    }


def _run_agent(run_id, ts="2026-09-20T00:00:10", question="q?", **fields):
    """`fields` sets answer, warnings and checks (citation_checks)."""
    output = {"answer": fields.get("answer", "No numbers here."), "citation_warnings": fields.get("warnings") or [], "result_count": 0}
    if fields.get("checks") is not None:
        output["citation_checks"] = fields["checks"]
    return _span(run_id, "run_agent", {"question": question}, output, timestamp=ts, as_type="agent")


def _submit(run_id, answer_text="No numbers here.", claims=None):
    return _span(run_id, "submit_answer", {"answer_text": answer_text, "claims": claims or []}, {"checks": []})


@pytest.fixture
def capture(monkeypatch):
    """Registers the tracing globals with monkeypatch so the replay's own
    install step is undone after each test."""
    monkeypatch.setattr(tracing, "TRACING_ENABLED", tracing.TRACING_ENABLED)
    monkeypatch.setattr(tracing, "_write_local_log", tracing._write_local_log)
    replay.install_trace_capture()


# ---------------------------------------------------------------------------
# group_runs
# ---------------------------------------------------------------------------
def test_group_runs_keeps_tool_spans_in_file_order_including_after_last_submit():
    records = [
        _span("r1", "search_filings", {"query": "a", "ticker": "AAPL"}, {"result_count": 5}),
        _span("r1", "unmet_metric_request", as_type="span"),
        _submit("r1"),
        _span("r1", "get_financial_fact", {"metric": "revenue"}, {"found": True, "value": 1.0}),
        {"timestamp": "2026-09-20T00:00:05", "run_id": "r1", "category": "citation_retry"},
        {"timestamp": "2026-09-20T00:00:06", "run_id": None, "category": "auth_rejected"},
        _run_agent("r1", warnings=["bad"], checks={"quote_not_found": 1}),
    ]

    runs, counts = group_runs(records, {"r1": "qid-1"})

    assert len(runs) == 1
    run = runs[0]
    assert [s["name"] for s in run.tool_spans] == ["search_filings", "get_financial_fact"]
    assert run.final_submit["name"] == "submit_answer"
    assert (run.qid, run.question, run.logged_refused, run.logged_checks) == ("qid-1", "q?", True, {"quote_not_found": 1})
    assert counts == {"non_agent_runs": 0, "skipped_no_submit": 0, "skipped_no_output": 0, "skipped_prose_final": 0}


def test_group_runs_takes_the_last_of_several_submits():
    records = [
        _submit("r1", answer_text="first"),
        _submit("r1", answer_text="second"),
        _run_agent("r1", answer="second"),
    ]

    runs, _ = group_runs(records, {})

    assert runs[0].final_submit["input"]["answer_text"] == "second"
    assert runs[0].qid == "?"


def test_group_runs_counts_skips_and_non_agent_runs():
    records = [
        _span("mcp", "compare_financial_metric", {"metric": "m"}, {"found": True}),
        _span("prose", "search_filings", {"query": "a"}, {"result_count": 5}),
        _run_agent("prose"),
        _submit("crashed"),
        {**_run_agent("crashed"), "output": None},
    ]

    runs, counts = group_runs(records, {})

    assert runs == []
    assert counts == {"non_agent_runs": 1, "skipped_no_submit": 1, "skipped_no_output": 1, "skipped_prose_final": 0}


def test_group_runs_skips_a_run_whose_final_answer_is_not_a_submit():
    # A refused submit, then a prose reply that the prose checker passed.
    records = [_submit("r1", answer_text="submitted"), _run_agent("r1", answer="prose reply")]

    runs, counts = group_runs(records, {})

    assert runs == []
    assert counts["skipped_prose_final"] == 1


def test_group_runs_refused_run_matches_the_withheld_answer():
    refused = {"timestamp": "2026-09-20T00:00:09", "run_id": "r1", "category": "citation_gate_refused"}
    records = [
        # Budget ran out after the retry: the cached pre-retry submit is re-gated.
        _submit("r1", answer_text="pre-retry"),
        _span("r1", "get_financial_fact", {"metric": "revenue"}, {"found": True, "value": 1.0}),
        {**refused, "withheld_answer": "pre-retry"},
        _run_agent("r1", warnings=["bad"], answer="refusal text"),
        _submit("r2", answer_text="prose-only final"),
        {**refused, "run_id": "r2", "withheld_answer": "prose"},
        _run_agent("r2", warnings=["bad"], answer="refusal text"),
        _submit("legacy", answer_text="last"),
        _run_agent("legacy", warnings=["bad"], answer="refusal text"),
        _submit("no-field", answer_text="kept"),
        {**refused, "run_id": "no-field"},
        _run_agent("no-field", warnings=["bad"], answer="refusal text"),
    ]

    runs, counts = group_runs(records, {})

    assert [(r.run_id, r.final_submit["input"]["answer_text"]) for r in runs] == [
        ("r1", "pre-retry"),
        ("legacy", "last"),
        ("no-field", "kept"),
    ]
    assert counts["skipped_prose_final"] == 1


def test_group_runs_skips_a_no_submission_refusal_even_when_a_submit_text_matches():
    # An earlier schema-invalid submit had no answer_text, and the final
    # text reply was empty, so both read as "". The logged no_submission
    # check says the run didn't end on a submit, so the text match is moot.
    refused = {"timestamp": "2026-09-20T00:00:09", "run_id": "r1", "category": "citation_gate_refused"}
    records = [
        _span("r1", "submit_answer", {"claims": []}, {"checks": []}),
        {**refused, "withheld_answer": ""},
        _run_agent("r1", warnings=["no submission"], answer="refusal text", checks={"no_submission": 1}),
    ]

    runs, counts = group_runs(records, {})

    assert runs == []
    assert counts["skipped_prose_final"] == 1


def test_group_runs_counts_only_non_agent_runs_inside_the_filter():
    records = [
        _span("mcp-old", "compare_financial_metric", timestamp="2026-09-01T00:00:00"),
        _span("mcp-new", "compare_financial_metric", timestamp="2026-09-20T00:00:00"),
    ]

    _, counts = group_runs(records, {}, RunFilter(since="2026-09-19"))
    _, by_id = group_runs(records, {}, RunFilter(run_ids={"x"}))

    assert counts["non_agent_runs"] == 1
    assert by_id["non_agent_runs"] == 0


def test_group_runs_filters_by_run_agent_timestamp_and_qid():
    records = [
        _submit("early"),
        _run_agent("early", ts="2026-09-18T23:00:00"),
        _submit("mid"),
        _run_agent("mid", ts="2026-09-19T05:00:00"),
        _submit("late"),
        _run_agent("late", ts="2026-09-21T00:00:00"),
        _submit("other"),
        _run_agent("other", ts="2026-09-19T06:00:00"),
    ]
    ids = {"early": "a", "mid": "a", "late": "a", "other": "b"}

    runs, _ = group_runs(records, ids, RunFilter(since="2026-09-19", until="2026-09-21", qids=["a"]))

    assert [r.run_id for r in runs] == ["mid"]


def test_group_runs_run_ids_restricts_to_that_set():
    records = [_submit("x"), _run_agent("x"), _submit("y"), _run_agent("y")]

    runs, _ = group_runs(records, {}, RunFilter(run_ids={"y"}))

    assert [r.run_id for r in runs] == ["y"]


def test_group_runs_legacy_run_without_citation_checks_has_none():
    records = [_submit("r1"), _run_agent("r1")]

    runs, _ = group_runs(records, {})

    assert runs[0].logged_checks is None
    assert runs[0].logged_refused is False


# ---------------------------------------------------------------------------
# rebuild_results
# ---------------------------------------------------------------------------
def _run(tool_spans, submit_input=None, result_count=None, qid="qid-1"):
    return RunTrace(
        run_id="r1",
        ts="2026-09-20T00:00:10",
        qid=qid,
        question="q?",
        tool_spans=tool_spans,
        final_submit=_span("r1", "submit_answer", submit_input or {"answer_text": "No numbers here.", "claims": []}),
        logged_refused=False,
        logged_checks={},
        logged_result_count=result_count,
    )


def _fake_search(query, ticker, all_results):
    all_results.append({"text": f"{query}/{ticker}"})
    return f"[{len(all_results)}] {query}", 1


def test_rebuild_results_routes_search_and_hashes_content(capture):
    run = _run([_span("r1", "search_filings", {"query": "rev", "ticker": "AAPL"}, {"result_count": 5})])

    all_results, calls, error = rebuild_results(run, _fake_search)

    assert error is None
    assert all_results == [{"text": "rev/AAPL"}]
    assert calls == [
        {
            "tool": "search_filings",
            "content_sha256": hashlib.sha256(b"[1] rev").hexdigest(),
            "observed": {"result_count": 1},
            "logged": {"result_count": 5},
        }
    ]


def test_rebuild_results_captures_dispatch_span_output(capture, monkeypatch):
    seen = {}

    def fake_dispatch(name, args, question, all_results, verbose):
        seen.update(name=name, args=args, question=question, verbose=verbose)
        with tracing.traced_span("tool", name, input=args) as span:
            all_results.append({"text": "fact"})
            span.update(output={"found": True, "value": 42.0})
        tracing.record_unmet_metric_request("AAPL", "m", "no_data_for_ticker")
        return "fact block"

    monkeypatch.setattr(agent, "_dispatch_get_financial_fact", fake_dispatch)
    run = _run([_span("r1", "get_financial_fact", {"metric": "revenue"}, {"found": True, "value": 41.0})])

    all_results, calls, error = rebuild_results(run, _fake_search)

    assert error is None
    assert seen == {"name": "get_financial_fact", "args": {"metric": "revenue"}, "question": "q?", "verbose": False}
    assert calls[0]["observed"] == {"found": True, "value": 42.0}
    assert calls[0]["logged"] == {"found": True, "value": 41.0}


def test_rebuild_results_routes_calculate_and_compare(capture, monkeypatch):
    def fake_calculate(name, args, all_results, verbose):
        with tracing.traced_span("tool", name, input=args) as span:
            span.update(output={"found": False, "error": "no"})
        return "calc error"

    def fake_compare(name, args, question, all_results, verbose):
        with tracing.traced_span("tool", name, input=args) as span:
            span.update(output={"found": True, "companies": ["AAPL"]})
        return "compare block"

    monkeypatch.setattr(agent, "_dispatch_calculate", fake_calculate)
    monkeypatch.setattr(agent, "_dispatch_compare_financial_metric", fake_compare)
    run = _run(
        [
            _span("r1", "calculate", {"operation": "ratio"}, {"found": False, "error": "no"}),
            _span("r1", "compare_financial_metric", {"metric": "m"}, {"found": True, "companies": ["AAPL"]}),
        ]
    )

    _, calls, error = rebuild_results(run, _fake_search)

    assert error is None
    assert calls[0]["observed"] == {"found": False, "value": None}
    assert calls[1]["observed"] == {"found": True, "companies": ["AAPL"]}


def test_rebuild_results_reads_the_fields_the_real_dispatch_bodies_log(capture, monkeypatch):
    fact = {
        "value": 71.1,
        "unit": "percent",
        "form": "10-K",
        "filed": "2026-06-20",
        "period_end": "2026-03-31",
        "accession": "a-1",
    }
    monkeypatch.setattr("agent.call_get_financial_fact", lambda args, question=None: fact)
    monkeypatch.setattr("agent.call_compare_financial_metric", lambda args, question=None: {"AAPL": fact, "MSFT": fact})
    monkeypatch.setattr("agent.call_calculate", lambda args, all_results: ({"value": 17.7, "unit": "percent"}, None))
    calculate_args = {
        "operation": "percent_of",
        "operand_a": 34550.0,
        "citation_index_a": 1,
        "unit_a": "million",
        "operand_b": 195201.0,
        "citation_index_b": 2,
        "unit_b": "million",
    }
    run = _run(
        [
            _span("r1", "get_financial_fact", {"ticker": "NVDA", "metric": "gross_margin"}),
            _span("r1", "compare_financial_metric", {"metric": "gross_margin"}),
            _span("r1", "calculate", calculate_args),
        ]
    )

    all_results, calls, error = rebuild_results(run, _fake_search)

    assert error is None
    assert len(all_results) == 4
    assert [c["observed"] for c in calls] == [
        {"found": True, "value": 71.1},
        {"found": True, "companies": ["AAPL", "MSFT"]},
        {"found": True, "value": 17.7},
    ]


def test_rebuild_results_stops_at_first_exception_and_reports_it(capture):
    def broken_search(query, ticker, all_results):
        raise RuntimeError("chroma down")

    run = _run(
        [
            _span("r1", "search_filings", {"query": "a"}, {"result_count": 5}),
            _span("r1", "search_filings", {"query": "b"}, {"result_count": 5}),
        ]
    )

    _, calls, error = rebuild_results(run, broken_search)

    assert calls == []
    assert error == "search_filings: RuntimeError: chroma down"


def test_rebuild_results_unknown_tool_is_an_error(capture):
    run = _run([_span("r1", "made_up_tool", {}, {})])

    _, _, error = rebuild_results(run, _fake_search)

    assert error is not None and error.startswith("made_up_tool: ValueError")


# ---------------------------------------------------------------------------
# fidelity
# ---------------------------------------------------------------------------
def _call(tool, observed, logged):
    return {"tool": tool, "content_sha256": "h", "observed": observed, "logged": logged}


def test_fidelity_matching_calls_and_total_is_clean():
    calls = [_call("search_filings", {"result_count": 5}, {"result_count": 5})]

    assert fidelity(calls, logged_result_count=5, rebuilt_count=5) == []


@pytest.mark.parametrize(
    "observed,logged",
    [
        ({"result_count": 4}, {"result_count": 5}),
        ({"found": True, "value": 2.0}, {"found": True, "value": 1.0}),
        ({"found": False, "value": None}, {"found": True, "value": 1.0}),
    ],
)
def test_fidelity_flags_any_observed_mismatch(observed, logged):
    drift = fidelity([_call("x", observed, logged)], logged_result_count=None, rebuilt_count=0)

    assert drift == [f"call 1 x: logged {logged}, replayed {observed}"]


def test_fidelity_flags_total_result_count_mismatch():
    assert fidelity([], logged_result_count=21, rebuilt_count=20) == ["result_count: logged 21, replayed 20"]


# ---------------------------------------------------------------------------
# grade and replay_run
# ---------------------------------------------------------------------------
def test_grade_only_numeric_and_comparison_questions(monkeypatch):
    monkeypatch.setattr("eval_harness._grade_by_type", lambda q, text, retrieved: (text == "right", "detail"))

    assert grade({"type": "numeric"}, "right", []) is True
    assert grade({"type": "comparison"}, "wrong", []) is False
    assert grade({"type": "judged"}, "right", []) is None
    assert grade(None, "right", []) is None


def test_replay_run_invalid_submit_is_refused_and_graded(capture, monkeypatch):
    monkeypatch.setattr("eval_harness._grade_by_type", lambda q, text, retrieved: (False, "detail"))
    run = _run(
        [_span("r1", "search_filings", {"query": "rev"}, {"result_count": 1})],
        submit_input={"claims": "not-a-list"},
        result_count=1,
    )

    record = replay_run(run, _fake_search, {"qid-1": {"type": "numeric"}})

    assert record["now_refused"] is True
    assert record["now_checks"] == {"no_structured_answer": 1}
    assert record["correct"] is False
    assert record["drift"] == []
    assert record["replay_error"] is None
    assert record["logged_refused"] is False


def test_replay_run_valid_submit_passes(capture):
    run = _run([], result_count=0)

    record = replay_run(run, _fake_search, {})

    assert (record["now_refused"], record["now_checks"], record["correct"]) == (False, {}, None)


def test_replay_run_error_leaves_verdict_empty(capture):
    run = _run([_span("r1", "made_up_tool", {}, {})])

    record = replay_run(run, _fake_search, {})

    assert record["replay_error"] is not None
    assert record["now_refused"] is None


# ---------------------------------------------------------------------------
# summarize, compare_failed, format_summary
# ---------------------------------------------------------------------------
def _record(run_id, logged, now, **overrides):
    """A replay record; `shas` in overrides sets the call hashes."""
    record = {
        "run_id": run_id,
        "qid": f"q-{run_id}",
        "logged_refused": logged,
        "logged_checks": {"c": 1} if logged else {},
        "now_refused": now,
        "now_checks": {"c": 1} if now else {},
        "now_messages": ["m"] if now else [],
        "correct": None,
        "calls": [{"content_sha256": sha} for sha in overrides.pop("shas", ("h",))],
        "replay_error": None,
        "drift": [],
    }
    return {**record, **overrides}


_COUNTS = {"non_agent_runs": 0, "skipped_no_submit": 0, "skipped_no_output": 0, "skipped_prose_final": 0}


def test_summarize_against_logged_verdicts():
    records = [
        _record("a", True, False, correct=True),
        _record("b", True, False, correct=False),
        _record("c", True, False),
        _record("d", False, True, correct=True),
        _record("e", True, True, logged_checks={"c": 1}, now_checks={"d": 1}, drift=["x"]),
        _record("f", True, True, logged_checks=None, now_checks={"d": 1}),
        _record("h", True, True, logged_checks={"c": 1}, now_checks={"d": 1}),
        _record("g", None, None, replay_error="boom"),
    ]

    s = summarize(records)

    assert (s["replayed"], s["refused_then"], s["refused_now"]) == (7, 6, 4)
    assert s["recovered"] == {"correct": ["q-a (a)"], "wrong": ["q-b (b)"], "ungraded": ["q-c (c)"]}
    assert s["newly_refused"] == {"correct": ["q-d (d)"], "wrong": [], "ungraded": []}
    assert s["check_changes"] == ["q-h (h)"]
    assert s["drifted_changes"] == ["q-e (e)"]
    assert s["drifted"] == ["q-e (e)"]
    assert s["errored"] == ["q-g (g)"]
    assert s["tool_drift"] == [] and s["only_in_base"] == [] and s["only_in_candidate"] == []
    assert compare_failed(s) is True


def test_summarize_against_baseline_uses_its_verdicts_and_hashes():
    base = [
        _record("a", False, True, drift=["sources changed"]),
        _record("b", False, False, shas=("h1", "h2")),
        _record("gone", False, False),
    ]
    cand = [
        _record("a", False, False, drift=["sources changed"]),
        _record("b", False, False, shas=("h1", "h3")),
        _record("new", False, False),
    ]

    s = summarize(cand, base)

    assert s["recovered"]["ungraded"] == ["q-a (a)"]
    assert s["tool_drift"] == ["q-b (b)"]
    assert s["only_in_base"] == ["q-gone (gone)"]
    assert s["only_in_candidate"] == ["q-new (new)"]


def test_summarize_against_baseline_flags_a_changed_warning_message():
    base = [_record("a", True, True)]
    cand = [_record("a", True, True, now_messages=["reworded"])]

    s = summarize(cand, base)

    assert s["check_changes"] == ["q-a (a)"]
    assert compare_failed(s) is True


def test_identical_baseline_does_not_fail():
    records = [_record("a", True, True), _record("b", False, False)]

    s = summarize(records, records)

    assert compare_failed(s) is False


def test_format_summary_names_the_buckets():
    s = summarize([_record("a", True, False, correct=False)])

    text = format_summary(s, {**_COUNTS, "non_agent_runs": 2, "skipped_prose_final": 4})

    assert "Replayed: 1" in text
    assert "Recovered (refused -> passed): 1 (0 correct, 1 wrong, 0 ungraded)" in text
    assert "q-a (a)" in text
    assert "non-agent 2" in text
    assert "prose final 4" in text


# ---------------------------------------------------------------------------
# memoized, require_repo_root, main
# ---------------------------------------------------------------------------
def test_memoized_calls_once_per_key_and_returns_independent_copies():
    calls = []

    def search(query, ticker=None, top_k=5):
        calls.append((query, ticker, top_k))
        return [{"metadata": {"ticker": ticker}}]

    cached = memoized(search)
    first = cached("q", ticker="AAPL", top_k=5)
    first[0]["metadata"]["ticker"] = "mutated"
    second = cached("q", ticker="AAPL", top_k=5)
    cached("q", ticker="MSFT", top_k=5)

    assert calls == [("q", "AAPL", 5), ("q", "MSFT", 5)]
    assert second == [{"metadata": {"ticker": "AAPL"}}]


def test_require_repo_root_rejects_other_directories(tmp_path):
    with pytest.raises(SystemExit):
        require_repo_root(tmp_path)
    require_repo_root(Path(replay.__file__).resolve().parent)


def _write_jsonl(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


@pytest.fixture
def trace_env(tmp_path, monkeypatch, capture):
    monkeypatch.setattr(replay, "install_trace_capture", lambda: None)
    trace_file = tmp_path / "traces.jsonl"
    _write_jsonl(
        trace_file,
        [
            _span("r1", "search_filings", {"query": "rev", "ticker": "AAPL"}, {"result_count": 1}),
            _span("r1", "submit_answer", {"claims": "not-a-list"}, {"checks": ["no_structured_answer"]}),
            _run_agent("r1", question="What was it?", warnings=["bad"], checks={"no_structured_answer": 1}),
        ],
    )
    questions = tmp_path / "questions.jsonl"
    _write_jsonl(questions, [{"id": "q-one", "question": "What was it?", "type": "judged"}])
    return tmp_path, ["--file", str(trace_file), "--questions", str(questions)]


def test_main_writes_report_and_compare_detects_tool_drift(trace_env, monkeypatch, capsys):
    tmp_path, common = trace_env
    monkeypatch.setattr(replay, "install_live_search", lambda: _fake_search)
    base = tmp_path / "base.json"

    assert replay.main([*common, "--out", str(base)]) == 0
    report = json.loads(base.read_text(encoding="utf-8"))
    assert report["header"]["since"] is None
    assert [r["qid"] for r in report["runs"]] == ["q-one"]
    assert report["runs"][0]["now_checks"] == {"no_structured_answer": 1}
    assert "Replayed: 1" in capsys.readouterr().out

    assert replay.main([*common, "--compare", str(base), "--out", str(tmp_path / "same.json")]) == 0

    def other_search(query, ticker, all_results):
        all_results.append({"text": "changed"})
        return "different text", 1

    monkeypatch.setattr(replay, "install_live_search", lambda: other_search)
    assert replay.main([*common, "--compare", str(base), "--out", str(tmp_path / "drift.json")]) == 1
    assert "Tool-result drift: 1" in capsys.readouterr().out


def test_main_compare_rejects_filters(trace_env, tmp_path):
    _, common = trace_env
    with pytest.raises(SystemExit):
        replay.main([*common, "--compare", str(tmp_path / "base.json"), "--since", "2026-09-19"])


def test_summarize_baseline_error_counts_as_errored():
    base = [_record("a", False, None, replay_error="boom")]

    s = summarize([_record("a", False, False)], base)

    assert s["errored"] == ["q-a (a)"]
    assert s["replayed"] == 0
    assert compare_failed(s) is True


def test_summarize_same_error_on_both_sides_is_not_a_difference():
    base = [_record("a", False, None, replay_error="boom"), _record("b", False, None, replay_error="boom")]
    cand = [_record("a", False, None, replay_error="boom"), _record("b", False, None, replay_error="other")]

    s = summarize(cand, base)

    assert s["errored_unchanged"] == ["q-a (a)"]
    assert s["errored"] == ["q-b (b)"]
    assert "Errored the same way in both: q-a (a)" in format_summary(s, _COUNTS)
    assert compare_failed(summarize(cand[:1], base[:1])) is False


def test_format_summary_reports_new_cache_files():
    counts = {**_COUNTS, "new_cache_files": ["AAPL_x.json"]}

    assert "New xbrl_cache files (live SEC fetches): 1" in format_summary(summarize([]), counts)


def test_main_prints_progress(trace_env, monkeypatch, capsys):
    tmp_path, common = trace_env
    monkeypatch.setattr(replay, "install_live_search", lambda: _fake_search)
    monkeypatch.setattr(replay, "_PROGRESS_EVERY", 1)

    replay.main([*common, "--out", str(tmp_path / "r.json")])

    assert "[replay] 1/1" in capsys.readouterr().err


def test_main_defaults_the_report_into_the_trace_log_directory(trace_env, monkeypatch):
    tmp_path, common = trace_env
    monkeypatch.setattr(replay, "install_live_search", lambda: _fake_search)
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    monkeypatch.setattr(replay.config, "TRACE_LOG_PATH", str(log_dir / "traces.jsonl"))

    replay.main(common)

    assert len(list(log_dir.glob("replay-*.json"))) == 1


def test_main_rejects_a_missing_out_directory_before_replaying(trace_env, monkeypatch):
    tmp_path, common = trace_env

    def fail():
        raise AssertionError("replay started")

    monkeypatch.setattr(replay, "install_live_search", fail)
    with pytest.raises(SystemExit):
        replay.main([*common, "--out", str(tmp_path / "missing" / "r.json")])
