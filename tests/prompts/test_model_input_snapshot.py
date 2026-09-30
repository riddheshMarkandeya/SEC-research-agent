"""Model-input snapshot: every string a model receives, rendered through
the real call sites with no network, compared against the committed
src/sec_agent/prompts/model_input_snapshot.json.

Why: prompts/ fingerprints hash constant values, which can't see a code
change that alters what a model reads without touching a constant (which
template agent.py picks, how llm_backends converts a schema, which fields
grade_judged fills in). This snapshot does. A change that alters model
input fails here until the snapshot is regenerated in the same commit,
and since prompts.prompt_fingerprint() hashes the snapshot's sections,
the fingerprint then changes with it.

Regenerate after reading the diff:
    UPDATE_SNAPSHOT=1 pytest tests/prompts/test_model_input_snapshot.py
"""

import asyncio
import difflib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from sec_agent.agent import citations, tool_results
from sec_agent.config import PROJECT_ROOT
from sec_agent.prompts import SNAPSHOT_PATH

# Stands in for the system prompt and tool schemas inside each scripted
# loop run: each run asserts its start call received exactly the recorded
# values, so repeating them six times would only bloat the diff.
SYSTEM_PROMPT_MARKER = "<agent.system_prompt>"
TOOL_SCHEMAS_MARKER = "<agent.tool_schemas>"

META = {
    "ticker": "AAPL",
    "form": "10-K",
    "reportDate": "2025-09-27",
    "filingDate": "2025-10-31",
    "accessionNumber": "0000320193-25-000079",
    "chunk_index": 3,
}
# Braces in source text and answers check that no template is formatted
# a second time after outside content has been substituted in.
SRC1 = "Total net sales were $100 million for fiscal year 2025, compared with prior-year results {braces}."
SRC2 = "Research and development expense was $200 million during the year, driven by headcount."
BAD_CALC = {"name": "calculate", "args": {"operation": "add"}}
FROZEN_NOW = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)

EXPECTED_KEYS = {
    "agent": {
        "system_prompt",
        "tool_schemas",
        "gemini_tool_declarations",
        "citation_header",
        "results_block_empty",
        "results_block",
        "fact_usd",
        "fact_raw",
        "comparison",
        "calc_result_percent_change",
        "calc_result_percent_of",
        "calc_result_add",
        "calc_result_divide",
        "calc_result_subtract",
        "ground_bad_index",
        "ground_wrong_unit",
        "ground_wrong_index",
        "ground_ungroundable",
        "calc_bad_schema",
        "calc_category_mismatch",
        "calc_divide_zero",
        "structured_warnings",
        "claim_retry",
        "refusal",
        "no_fact_empty",
        "no_fact_fy",
        "no_fact_q4",
        "no_fact_never_tagged",
        "no_fact_ratio_not_tagged_check",
        "no_fact_multi_year",
        "dispatch_no_fact_string_year",
        "no_comparison_empty",
        "no_comparison_q4_never_tagged",
        "never_tagged_hint",
        "search_bad_ticker",
        "search_bad_args",
        "loop_force_claimretry_refusal",
        "loop_text_after_force_refusal",
        "loop_mixed_turn",
        "loop_final_turn",
        "loop_budget_exhausted",
        "loop_submit_schema_mismatch",
    },
    "judge": {"judge"},
    "mcp": {"mcp_fact_missing", "mcp_compare_missing", "mcp_unknown_tool", "mcp_list_tools"},
}


def canonical_json(data) -> str:
    """The one serialisation used for the committed file and for
    comparing against it. No `default=`: a value JSON can't represent
    fails loudly instead of being written as its repr."""
    return json.dumps(data, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=1) + "\n"


def _results():
    return [
        {"text": SRC1, "metadata": dict(META)},
        {"text": SRC2, "metadata": dict(META, chunk_index=4)},
    ]


# ---------------------------------------------------------------------------
# Agent: formatters and messages, called directly
# ---------------------------------------------------------------------------
def _render_result_formats(agent) -> dict:
    out = {
        "citation_header": tool_results._citation_header(7, META),
        "results_block_empty": tool_results._format_results_block([], 1),
        "results_block": tool_results._format_results_block(_results(), 3),
    }
    fact_usd = {
        "value": 123.0,
        "unit": "USD",
        "form": "10-K",
        "filed": "2025-10-31",
        "period_end": "2025-09-27",
        "accession": "acc-1",
    }
    fact_raw = dict(fact_usd, unit="raw", filed=None)
    out["fact_usd"] = agent._fact_as_result(fact_usd, {"metric": "revenue", "ticker": "AAPL"})
    out["fact_raw"] = agent._fact_as_result(fact_raw, {"metric": "asset_turnover", "ticker": "AAPL"})
    frame_fact = {"value": 5.0, "unit": "USD", "period_end": "2025-06-30", "accession": "acc-2"}
    out["comparison"] = agent._comparison_as_results({"MSFT": frame_fact, "AAPL": fact_usd}, "revenue")
    base = {
        "operand_a": 150.0,
        "unit_a": "million",
        "operand_b": 120.5,
        "unit_b": "million",
        "citation_index_a": 1,
        "citation_index_b": 2,
    }
    for op, res in [
        ("percent_change", {"value": 24.5, "unit": "percent"}),
        ("percent_of", {"value": 124.5, "unit": "percent"}),
        ("add", {"value": 270500000.0, "unit": "raw"}),
        ("divide", {"value": 1.24, "unit": "raw"}),
        ("subtract", {"value": 1e18, "unit": "raw"}),
    ]:
        out[f"calc_result_{op}"] = agent._calculation_as_result(res, dict(base, operation=op))
    return out


def _render_calculate_messages(agent) -> dict:
    r = _results()
    out = {
        "ground_bad_index": agent._ground_operand(100.0, "million", 9, r, "operand_a"),
        "ground_wrong_unit": agent._ground_operand(100.0, "billion", 1, r, "operand_a"),
        "ground_wrong_index": agent._ground_operand(200.0, "million", 1, r, "operand_b"),
        "ground_ungroundable": agent._ground_operand(1000000000.0, "raw", 1, r, "operand_b"),
        "calc_bad_schema": agent.call_calculate({"operation": "add"}, r),
    }
    pct = [{"text": "Gross margin was 45.5% and revenue was $100 million.", "metadata": dict(META)}]
    mismatch = {
        "operation": "add",
        "operand_a": 45.5,
        "unit_a": "percent",
        "citation_index_a": 1,
        "operand_b": 100.0,
        "unit_b": "million",
        "citation_index_b": 1,
    }
    out["calc_category_mismatch"] = agent.call_calculate(mismatch, pct)
    zero = [{"text": "Revenue was $100 million and other income was $0 million.", "metadata": dict(META)}]
    divide_zero = {
        "operation": "percent_change",
        "operand_a": 100.0,
        "unit_a": "million",
        "citation_index_a": 1,
        "operand_b": 0.0,
        "unit_b": "million",
        "citation_index_b": 1,
    }
    out["calc_divide_zero"] = agent.call_calculate(divide_zero, zero)
    return out


def _render_citation_warnings(agent) -> dict:
    r = _results()
    claims = [
        {"citation_index": 9, "value": 1.0, "unit": "million", "quote": "whatever"},
        {"citation_index": 1, "value": 100.0, "quote": "Total net sales were $100 million"},
        {"citation_index": 1, "value": 100.0, "unit": "million", "quote": "$100"},
        {
            "citation_index": 1,
            "value": 100.0,
            "unit": "million",
            "quote": "An entirely fabricated sentence about $100 million that is not there",
        },
        {
            "citation_index": 1,
            "value": 250.0,
            "unit": "million",
            "quote": "Total net sales were $100 million for fiscal year 2025",
        },
        {"citation_index": 1, "quote": "short"},
        {"citation_index": 2, "quote": "A qualitative quote that does not appear in the source at all"},
    ]
    structured = citations.verify_claims(claims, r, "What were Apple's sales?", "Sales were $777 million [1].")
    return {
        "structured_warnings": [w._asdict() for w in structured],
    }


def _render_retry_and_no_data(agent) -> dict:
    warning = citations.CitationWarning("uncovered_number", None, 1.0, "raw", "msg {x} one", None)
    out = {
        "claim_retry": agent._format_claim_retry_message("answer_text {braces}", [warning]),
        "refusal": agent._format_refusal_message(["a {b}", "c"]),
    }
    for name, args in [
        ("empty", {}),
        ("fy", {"metric": "revenue", "ticker": "AAPL", "fiscal_year": 2025}),
        ("q4", {"metric": "revenue", "ticker": "AAPL", "fiscal_year": 2025, "fiscal_period": "Q4"}),
        ("never_tagged", {"metric": "inventory", "ticker": "PLTR", "fiscal_year": 2025, "fiscal_period": "FY"}),
        ("ratio_not_tagged_check", {"metric": "gross_margin", "ticker": "PLTR", "period_end_date": "2025-12-31"}),
        ("multi_year", {"metric": "gross_margin", "ticker": "PLTR", "start_fiscal_year": 2023}),
    ]:
        out[f"no_fact_{name}"] = tool_results._format_no_fact_message(args)
    # Through the dispatcher, so the reply shows the year the lookup used
    # after a string year is converted.
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(agent, "get_ratio", lambda *a, **k: None)
        out["dispatch_no_fact_string_year"] = agent._dispatch_tool_call(
            {"name": "get_financial_fact", "args": {"metric": "gross_margin", "ticker": "PLTR", "fiscal_year": "2025"}},
            "q",
            [],
            set(),
            False,
        )
    for name, args in [
        ("empty", {}),
        ("q4_never_tagged", {"metric": "inventory", "anchor_ticker": "PLTR", "fiscal_period": "Q4"}),
    ]:
        out[f"no_comparison_{name}"] = tool_results._format_no_comparison_message(args)
    out["never_tagged_hint"] = tool_results._never_tagged_hint("PLTR", "inventory")
    out["search_bad_ticker"] = agent._dispatch_search_filings(
        {"name": "search_filings", "args": {"query": "x", "ticker": "ZZZZ"}}, "q", [], set(), False
    )
    out["search_bad_args"] = agent._dispatch_search_filings(
        {"name": "search_filings", "args": {"query": 5}}, "q", [], set(), False
    )
    return out


# ---------------------------------------------------------------------------
# Agent: scripted runs through _run_agent_impl at a fake backend
# ---------------------------------------------------------------------------
def _install_fake_backend(mp, agent, backend, start_turn, script) -> list[dict]:
    """Replaces agent.BACKENDS with a backend that returns `start_turn`
    and then each turn in `script`, recording what the loop sends."""
    from sec_agent.prompts.agent_system import SYSTEM_PROMPT
    from sec_agent.prompts.agent_tools import AGENT_TOOL_SCHEMAS

    capture = []
    turns = iter(script)

    def start(question, system_prompt, tool_schemas):
        assert system_prompt == SYSTEM_PROMPT
        assert tool_schemas == list(AGENT_TOOL_SCHEMAS)
        capture.append(
            {
                "call": "start",
                "question": question,
                "system_prompt": SYSTEM_PROMPT_MARKER,
                "tool_schemas": TOOL_SCHEMAS_MARKER,
            }
        )
        return {}, start_turn

    def send_tool_results(state, results, force_tool=None):
        capture.append({"call": "send_tool_results", "results": results, "force_tool": force_tool})
        return next(turns)

    def send_followup(state, text, force_tool=None):
        capture.append({"call": "send_followup", "text": text, "force_tool": force_tool})
        return next(turns)

    mp.setattr(agent, "BACKENDS", {backend: (start, send_tool_results, send_followup)})
    return capture


def _submit_turn(answer, claims):
    from sec_agent.llm.llm_backends import ModelTurn

    return ModelTurn(
        tool_calls=[{"name": "submit_answer", "args": {"answer_text": answer, "claims": claims}}], text=None
    )


def _run(overrides, backend, start_turn, script, expected_calls=None) -> dict:
    """One isolated scripted run. `overrides` (agent attribute -> value)
    are patched in a per-run MonkeyPatch context, so e.g. a
    MAX_TOOL_ITERATIONS override can't leak into the next scenario."""
    from sec_agent.agent import agent

    with pytest.MonkeyPatch.context() as run_mp:
        for name, value in (overrides or {}).items():
            run_mp.setattr(agent, name, value)
        capture = _install_fake_backend(run_mp, agent, backend, start_turn, script)
        result = agent._run_agent_impl("What were sales?", backend)
    if expected_calls is not None:
        assert [c["call"] for c in capture] == expected_calls, capture
    return {
        "capture": capture,
        "answer": result.answer,
        "warnings": result.citation_warnings,
        "withheld": result.withheld_answer,
    }


def _render_loop_runs(agent) -> dict:
    from sec_agent.llm.llm_backends import ModelTurn

    bad_submit = _submit_turn("Sales were $777 million {x} [1].", [])
    prose = ModelTurn(tool_calls=[], text="Sales were $777 million {x} in total.")
    mixed = ModelTurn(
        tool_calls=[BAD_CALC, {"name": "submit_answer", "args": {"answer_text": "x", "claims": []}}], text=None
    )
    calc_turn = ModelTurn(tool_calls=[BAD_CALC], text=None)
    broken_submit = ModelTurn(tool_calls=[{"name": "submit_answer", "args": {"answer_text": "hi"}}], text=None)

    final_turn = _run(
        {"MAX_TOOL_ITERATIONS": 2},
        "gemini",
        calc_turn,
        [calc_turn, _submit_turn("I cannot answer.", [])],
        ["start", "send_tool_results", "send_tool_results"],
    )
    assert final_turn["capture"][-1]["force_tool"] == "submit_answer"
    return {
        "loop_force_claimretry_refusal": _run(
            None,
            "gemini",
            ModelTurn(tool_calls=[], text="plain prose"),
            [bad_submit, bad_submit],
            ["start", "send_followup", "send_tool_results"],
        ),
        "loop_text_after_force_refusal": _run(None, "gemini", prose, [prose], ["start", "send_followup"]),
        "loop_mixed_turn": _run(
            None,
            "gemini",
            mixed,
            [_submit_turn("No data was found.", [])],
            ["start", "send_tool_results"],
        ),
        "loop_final_turn": final_turn,
        "loop_budget_exhausted": _run({"MAX_TOOL_ITERATIONS": 1}, "gemini", calc_turn, [calc_turn]),
        "loop_submit_schema_mismatch": _run(None, "gemini", broken_submit, [broken_submit]),
    }


def _render_agent() -> dict:
    from sec_agent.agent import agent
    from sec_agent.llm.llm_backends import _gemini_declaration_fields
    from sec_agent.prompts.agent_system import SYSTEM_PROMPT
    from sec_agent.prompts.agent_tools import AGENT_TOOL_SCHEMAS

    out = {
        "system_prompt": SYSTEM_PROMPT,
        "tool_schemas": list(AGENT_TOOL_SCHEMAS),
        "gemini_tool_declarations": [_gemini_declaration_fields(s) for s in AGENT_TOOL_SCHEMAS],
    }
    for part in (
        _render_result_formats,
        _render_calculate_messages,
        _render_citation_warnings,
        _render_retry_and_no_data,
        _render_loop_runs,
    ):
        rendered = part(agent)
        assert not set(rendered) & set(out), set(rendered) & set(out)
        out.update(rendered)
    return out


# ---------------------------------------------------------------------------
# Judge and MCP
# ---------------------------------------------------------------------------
def _render_judge(mp) -> dict:
    from sec_agent.eval import eval_harness

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return FROZEN_NOW

    captured = []

    def fake_complete(backend, system, user, temperature=None):
        captured.append({"system": system, "user": user, "temperature": temperature})
        return "PASS\nok"

    mp.setattr(eval_harness, "datetime", FrozenDatetime)
    mp.setattr(eval_harness, "complete", fake_complete)
    eval_harness.grade_judged("Q {q}?", "Answer {a} [1].", "Criteria {c}", backend="gemini")
    return {"judge": captured}


def _render_mcp(mp) -> dict:
    from mcp import types

    from sec_agent import mcp_server

    mp.setattr(mcp_server, "call_get_financial_fact", lambda args: None)
    mp.setattr(mcp_server, "call_compare_financial_metric", lambda args: {})
    unknown = asyncio.run(
        mcp_server._handle_call_tool(None, types.CallToolRequestParams(name="nope {x}", arguments={}))
    )
    listed = asyncio.run(mcp_server._handle_list_tools(None, None))
    return {
        "mcp_fact_missing": mcp_server._get_financial_fact({"ticker": "AAPL", "metric": "revenue"}),
        "mcp_compare_missing": mcp_server._compare_financial_metric({"anchor_ticker": "AAPL", "metric": "revenue"}),
        "mcp_unknown_tool": {
            "is_error": unknown.is_error,
            "text": [c.text for c in unknown.content if isinstance(c, types.TextContent)],
        },
        "mcp_list_tools": [
            {"name": t.name, "description": t.description, "inputSchema": t.input_schema} for t in listed.tools
        ],
    }


def render_model_inputs() -> dict:
    """Builds the whole snapshot in one call, so the result never depends
    on test order or selection. Tracing is disabled (no trace-log or
    Langfuse writes) and is_metric_tagged is stubbed (no SEC calls)."""
    from sec_agent import tracing

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(tracing, "TRACE_LOG_PATH", "")
        mp.setattr(tracing, "TRACING_ENABLED", False)
        mp.setattr(tool_results, "is_metric_tagged", lambda ticker, metric: False)
        return {"agent": _render_agent(), "judge": _render_judge(mp), "mcp": _render_mcp(mp)}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_snapshot_has_every_expected_scenario_and_none_is_empty():
    rendered = render_model_inputs()
    assert {section: set(entries) for section, entries in rendered.items()} == EXPECTED_KEYS
    empty = [
        (section, key)
        for section, entries in rendered.items()
        for key, value in entries.items()
        if value in (None, "", [], {})
    ]
    assert not empty, empty


def test_model_input_matches_committed_snapshot():
    rendered = canonical_json(render_model_inputs())
    if os.environ.get("UPDATE_SNAPSHOT") == "1":
        SNAPSHOT_PATH.write_text(rendered, encoding="utf-8", newline="\n")
    committed = canonical_json(json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8")))
    if rendered != committed:
        diff = "".join(
            difflib.unified_diff(
                committed.splitlines(keepends=True),
                rendered.splitlines(keepends=True),
                "committed",
                "rendered",
                n=2,
            )
        )
        pytest.fail(
            "What a model receives has changed. If intended, regenerate the snapshot in the same "
            "commit (UPDATE_SNAPSHOT=1 pytest tests/prompts/test_model_input_snapshot.py) after reading "
            f"this diff:\n{diff[:6000]}"
        )


def test_render_is_identical_across_hash_seeds():
    # Two renders in one process share a hash seed, so an unsorted set
    # join would only show up across processes. One child with a seed
    # different from this process's is enough.
    script = (
        "import sys; sys.path[:0] = [sys.argv[1], sys.argv[2]]; "
        "import test_model_input_snapshot as t; "
        "sys.stdout.buffer.write(t.canonical_json(t.render_model_inputs()).encode('utf-8'))"
    )
    seed = "1" if os.environ.get("PYTHONHASHSEED") == "0" else "0"
    proc = subprocess.run(
        [sys.executable, "-c", script, str(PROJECT_ROOT / "src"), str(Path(__file__).resolve().parent)],
        capture_output=True,
        env=dict(os.environ, PYTHONHASHSEED=seed),
        cwd=PROJECT_ROOT,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", errors="replace")
    assert proc.stdout.decode("utf-8") == canonical_json(render_model_inputs())
