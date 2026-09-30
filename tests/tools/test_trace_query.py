"""
Tests for trace_query.py. Pure parsing of hand-written trace records (a
tmp_path JSONL file where a file is needed), so this is full TDD with no
live code.
"""

import json

import pytest

from sec_agent.tools.trace_query import (
    Filters,
    count_lines,
    field,
    get,
    kind,
    load,
    main,
    question_ids,
    record_lines,
    run_lines,
    select,
)

TS = "2026-09-26T08:53:{:02d}.000000+00:00"


def _span(sec, run_id, name, **fields):
    span = {"timestamp": TS.format(sec), "run_id": run_id, "as_type": "tool", "name": name, "input": {}}
    span.update({"output": None, "duration_ms": 1.0, "error": None}, **fields)
    span["is_root"] = span["as_type"] == "agent"
    return span


def _event(sec, run_id, category, **fields):
    return {"timestamp": TS.format(sec), "run_id": run_id, "category": category, **fields}


REJECTED = _event(
    3,
    "r1",
    "tool_call_rejected",
    tool="get_financial_fact",
    reason="invalid_fiscal_year_type",
    args={"ticker": "PLTR", "fiscal_year": "2025"},
)
UNMET = _span(
    4,
    "r1",
    "unmet_metric_request",
    as_type="span",
    input={"ticker": "PLTR", "metric": "inventory_turnover", "reason": "no_data_for_ticker"},
)


def test_kind_is_the_span_name_or_the_event_category():
    assert kind(_span(1, "r1", "search_filings")) == "search_filings"
    assert kind(UNMET) == "unmet_metric_request"
    assert kind(REJECTED) == "tool_call_rejected"


def test_get_reads_top_level_then_input_then_args():
    assert get(REJECTED, "reason") == "invalid_fiscal_year_type"
    assert get(UNMET, "reason") == "no_data_for_ticker"
    assert get(REJECTED, "fiscal_year") == "2025"
    assert get(_span(1, "r1", "get_financial_fact", input={"fiscal_year": 2025}), "fiscal_year") == 2025


def test_get_follows_a_dotted_path_and_returns_none_when_missing():
    record = _span(1, "r1", "get_financial_fact", output={"found": False, "detail": {"unit": "USD"}})
    assert get(record, "output.found") is False
    assert get(record, "output.detail.unit") == "USD"
    assert get(record, "nope") is None
    assert get(record, "output.nope.deeper") is None


def _write(tmp_path, records, extra_lines=()):
    path = tmp_path / "traces.jsonl"
    lines = [json.dumps(r) for r in records] + list(extra_lines)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _questions(tmp_path):
    path = tmp_path / "questions.jsonl"
    rows = [{"id": "pltr-inv", "question": "PLTR inventory turnover?"}, {"id": "nvda-q4", "question": "NVDA Q4 R&D?"}]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return path


def test_load_skips_and_counts_malformed_lines(tmp_path):
    path = _write(tmp_path, [REJECTED, UNMET], extra_lines=["{not json", "", "[1, 2]"])

    records, malformed = load(path)

    assert [kind(r) for r in records] == ["tool_call_rejected", "unmet_metric_request"]
    assert malformed == 2


def test_question_ids_maps_runs_by_their_root_span_even_when_it_is_written_last(tmp_path):
    records = [
        _span(1, "r1", "get_financial_fact"),
        _span(9, "r1", "run_agent", as_type="agent", input={"question": " PLTR inventory turnover? "}),
        _span(10, "r2", "run_agent", as_type="agent", input={"question": "Something not in the suite"}),
        _span(11, "r3", "search_filings"),
    ]

    ids = question_ids(records, _questions(tmp_path))

    assert ids == {"r1": "pltr-inv", "r2": "?"}


WINDOW = [
    _span(1, "r1", "get_financial_fact", input={"fiscal_year": 2025}, output={"found": False}),
    REJECTED,
    UNMET,
    _span(20, "r1", "run_agent", as_type="agent", input={"question": "PLTR inventory turnover?"}),
    _span(21, "r2", "search_filings", input={"ticker": "NVDA"}),
    _event(22, None, "rate_limited", client_ip="x"),
]
IDS = {"r1": "pltr-inv"}


def test_field_resolves_qid_and_kind_pseudo_fields():
    assert field(REJECTED, "qid", IDS) == "pltr-inv"
    assert field(WINDOW[4], "qid", IDS) == "?"
    assert field(REJECTED, "kind", IDS) == "tool_call_rejected"
    assert field(REJECTED, "reason", IDS) == "invalid_fiscal_year_type"


def test_select_time_window_is_since_inclusive_until_exclusive():
    picked = select(WINDOW, IDS, Filters(since=TS.format(3)[:19], until=TS.format(20)[:19]))
    assert picked == [REJECTED, UNMET]


def test_select_by_run_qid_and_kind():
    assert select(WINDOW, IDS, Filters(runs=["r2"])) == [WINDOW[4]]
    # qid comes from the whole-file map, so a record before its run's root span still matches.
    assert select(WINDOW, IDS, Filters(qids=["pltr-inv"], until=TS.format(5)[:19])) == WINDOW[:3]
    assert select(WINDOW, IDS, Filters(kinds=["unmet_metric_request", "rate_limited"])) == [UNMET, WINDOW[5]]


def test_select_where_matches_any_record_shape_as_a_string():
    # fiscal_year is in a span's input and in a rejection event's args; 2025 and "2025" both match.
    assert select(WINDOW, IDS, Filters(where=[("fiscal_year", "2025")])) == [WINDOW[0], REJECTED]
    assert select(WINDOW, IDS, Filters(where=[("reason", "no_data_for_ticker")])) == [UNMET]
    assert select(WINDOW, IDS, Filters(where=[("output.found", "False"), ("qid", "pltr-inv")])) == [WINDOW[0]]


def test_record_lines_pick_fields_add_the_qid_and_end_with_a_total():
    lines = record_lines([REJECTED, UNMET], IDS, fields=["kind", "qid", "reason", "fiscal_year"])

    assert [json.loads(line) for line in lines[:2]] == [
        {"kind": "tool_call_rejected", "qid": "pltr-inv", "reason": "invalid_fiscal_year_type", "fiscal_year": "2025"},
        {"kind": "unmet_metric_request", "qid": "pltr-inv", "reason": "no_data_for_ticker", "fiscal_year": None},
    ]
    assert lines[2] == "-- 2 of 2 records"


def test_record_lines_whole_record_by_default_truncated_and_limited():
    long = _span(1, "r1", "search_filings", output="x" * 500)

    lines = record_lines([long, long, long], IDS, max_chars=20, limit=2)

    first = json.loads(lines[0])
    assert first["qid"] == "pltr-inv" and first["name"] == "search_filings"
    assert first["output"] == '"' + "x" * 19 + "..."
    assert len(lines) == 3 and lines[2] == "-- 2 of 3 records"


def test_record_lines_are_ascii_only():
    record = _span(1, "r1", "get_financial_fact", input={"fiscal_year": "²²²²"})
    assert record_lines([record], IDS, fields=["fiscal_year"])[0].isascii()


def test_count_lines_group_by_one_key_or_several_most_common_first():
    records = [REJECTED, UNMET, UNMET, WINDOW[4]]

    assert count_lines(records, IDS, ["kind"]) == [
        "2  unmet_metric_request",
        "1  tool_call_rejected",
        "1  search_filings",
        "-- 3 of 3 groups, 4 records",
    ]
    assert count_lines(records, IDS, ["qid", "reason"])[:2] == [
        "2  pltr-inv | no_data_for_ticker",
        "1  pltr-inv | invalid_fiscal_year_type",
    ]


def test_count_lines_say_how_many_groups_were_cut():
    records = [REJECTED, UNMET, UNMET, WINDOW[4]]

    assert count_lines(records, IDS, ["kind"], limit=1) == [
        "2  unmet_metric_request",
        "-- 1 of 3 groups, 4 records",
    ]


def test_run_lines_show_each_runs_tool_sequence_with_markers_and_event_counts():
    records = [
        _span(21, "r2", "search_filings", input={"ticker": "NVDA"}),  # a root tool span: no run_agent
        _span(1, "r1", "get_financial_fact", input={"fiscal_year": "2025", "fiscal_period": "FY"}),
        REJECTED,
        _span(5, "r1", "get_financial_fact", input={"fiscal_year": 2025}, output={"found": False}),
        UNMET,
        _span(6, "r1", "search_filings", input={"query": "x"}, error="boom"),
        _span(7, "r1", "submit_answer", input={"answer_text": "a"}),
        _span(8, "r1", "run_agent", as_type="agent", input={"question": "PLTR inventory turnover?"}),
        _event(22, None, "rate_limited", client_ip="x"),
    ]

    assert run_lines(records, IDS) == [
        "09-26T08:53:01 r1 pltr-inv: get_financial_fact(fy='2025',fp='FY') > get_financial_fact(fy=2025)[nodata]"
        " > search_filings[err] > submit_answer [+tool_call_rejected x1, unmet_metric_request x1]",
        "09-26T08:53:21 r2 ?: search_filings(NVDA)",
        "09-26T08:53:22 (no run) ?: [+rate_limited x1]",
        "-- 3 of 3 runs",
    ]


def test_run_lines_name_the_ticker_metric_and_yoy_flag_and_cap_the_run_count():
    records = [
        _span(1, "r1", "get_financial_fact", input={"ticker": "NVDA", "metric": "revenue", "yoy_growth": True}),
        _span(2, "r2", "compare_financial_metric", input={"anchor_ticker": "AAPL", "metric": "revenue"}),
        _span(3, "r3", "search_filings"),
    ]

    assert run_lines(records, IDS, limit=2) == [
        "09-26T08:53:01 r1 pltr-inv: get_financial_fact(NVDA,revenue,yoy)",
        "09-26T08:53:02 r2 ?: compare_financial_metric(AAPL,revenue)",
        "-- 2 of 3 runs",
    ]


def test_run_lines_show_non_ascii_args_escaped():
    record = _span(1, "r1", "get_financial_fact", input={"fiscal_year": "²²²²"})
    assert run_lines([record], IDS)[0] == "09-26T08:53:01 r1 pltr-inv: get_financial_fact(fy='\\xb2\\xb2\\xb2\\xb2')"


def test_count_and_run_lines_escape_control_characters_from_model_text():
    # A terminal escape sequence in a model-supplied argument must not reach the terminal raw.
    record = _span(1, "r1", "search_filings", input={"ticker": "\x1b[2J", "query": "q"})

    assert count_lines([record], IDS, ["ticker"])[0] == "1  \\x1b[2J"
    assert run_lines([record], IDS)[0] == "09-26T08:53:01 r1 pltr-inv: search_filings(\\x1b[2J)"


def _argv(tmp_path, *args):
    trace = _write(tmp_path, WINDOW, extra_lines=["{broken"])
    return [*args, "--file", str(trace), "--questions", str(_questions(tmp_path))]


def test_main_counts_by_qid_and_reports_malformed_lines_on_stderr(tmp_path, capsys):
    main(_argv(tmp_path, "counts", "--by", "qid", "--since", "2026-09-26T08:53:02"))

    out, err = capsys.readouterr()
    # r1's root span is at :20, so its earlier records still carry its qid.
    assert out.splitlines() == ["3  pltr-inv", "2  ?", "-- 2 of 2 groups, 5 records"]
    assert "1 malformed" in err


def test_main_records_picks_fields(tmp_path, capsys):
    main(_argv(tmp_path, "records", "--kind", "tool_call_rejected", "--fields", "qid, reason"))

    assert capsys.readouterr().out.splitlines() == [
        '{"qid": "pltr-inv", "reason": "invalid_fiscal_year_type"}',
        "-- 1 of 1 records",
    ]


def test_main_runs_filters_by_qid(tmp_path, capsys):
    main(_argv(tmp_path, "runs", "--qid", "pltr-inv"))

    assert capsys.readouterr().out.splitlines() == [
        "09-26T08:53:01 r1 pltr-inv: get_financial_fact(fy=2025)[nodata] [+tool_call_rejected x1, unmet_metric_request x1]",
        "-- 1 of 1 runs",
    ]


def test_main_rejects_a_where_without_equals(tmp_path):
    with pytest.raises(SystemExit):
        main(_argv(tmp_path, "counts", "--where", "reason"))


def test_main_needs_the_subcommand_first(tmp_path):
    # An option's value can equal a subcommand name (--kind runs), so the subcommand is
    # never looked for anywhere but first.
    for argv in (["--kind", "tool_call_rejected", "counts"], ["--kind", "runs"]):
        with pytest.raises(SystemExit):
            main(_argv(tmp_path, *argv))


def test_main_where_ignores_spaces_around_the_equals_sign(tmp_path, capsys):
    main(_argv(tmp_path, "counts", "--where", "reason = invalid_fiscal_year_type", "--by", "qid, reason"))

    assert capsys.readouterr().out.splitlines()[0] == "1  pltr-inv | invalid_fiscal_year_type"


def test_main_rejects_a_non_canonical_time_and_a_negative_limit(tmp_path):
    # "2026-09-26 08:53" sorts before every "T" timestamp that day, and a trailing Z sorts
    # after the fractional seconds, so either would silently select the wrong window.
    for bad in (["--since", "2026-09-26 08:53"], ["--until", "2026-09-26T08:53:00Z"], ["--limit", "-1"]):
        with pytest.raises(SystemExit):
            main(_argv(tmp_path, "records", *bad))


def test_main_reports_an_unreadable_trace_file_without_a_traceback(tmp_path, capsys):
    not_utf8 = tmp_path / "latin1.jsonl"
    not_utf8.write_bytes(b'{"name": "caf\xe9"}\n')
    for path in (tmp_path / "missing.jsonl", not_utf8):
        with pytest.raises(SystemExit) as exited:
            main(["counts", "--file", str(path)])

        assert exited.value.code == 1
        assert "cannot read" in capsys.readouterr().err


def test_main_without_the_questions_file_shows_every_qid_as_unknown(tmp_path, capsys):
    trace = _write(tmp_path, WINDOW)

    main(["counts", "--by", "qid", "--file", str(trace), "--questions", str(tmp_path / "missing.jsonl")])

    out, err = capsys.readouterr()
    assert out.splitlines() == ["6  ?", "-- 1 of 1 groups, 6 records"]
    assert "cannot read" in err
