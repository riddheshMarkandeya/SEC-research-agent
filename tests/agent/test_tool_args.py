"""
Unit tests for tool_args.py: validate_tool_args against every agent tool
schema, including the submit_answer and calculate payload shapes.
"""

from sec_agent.agent.tool_args import validate_tool_args
from sec_agent.prompts.agent_tools import (
    CALCULATE_TOOL_SCHEMA,
    FACT_TOOL_SCHEMA,
    SEARCH_TOOL_SCHEMA,
    SUBMIT_TOOL_SCHEMA,
)
from tests.agent.helpers import _valid_calculate_args, capture_events


# ---------------------------------------------------------------------------
# validate_tool_args -- the generic jsonschema-driven replacement for the
# hand-rolled per-tool extra-key/type/enum checks that broke three separate
# times across three review dates (2026-09-06, 2026-09-09, 2026-09-10). The
# schema-shape checks below exercise the generic function directly, walking
# each *_TOOL_SCHEMA's declared properties rather than one hand-written test
# per field -- the call_get_financial_fact/call_compare_financial_metric/
# _dispatch_tool_call tests in test_fact_tools.py/test_dispatch.py still cover the same schema-
# violation cases end-to-end (unrecognized_extra_argument, ticker_not_in_enum,
# etc.), so this section is additive, not a replacement for those.
# ---------------------------------------------------------------------------
def test_validate_tool_args_accepts_valid_args():
    assert validate_tool_args("get_financial_fact", FACT_TOOL_SCHEMA, {"ticker": "AAPL", "metric": "revenue"}) is False


def test_validate_tool_args_rejects_extra_argument(monkeypatch):
    calls = []
    capture_events(monkeypatch, calls)

    rejected = validate_tool_args(
        "get_financial_fact", FACT_TOOL_SCHEMA, {"ticker": "AAPL", "metric": "revenue", "segment": "Graphics"}
    )

    assert rejected is True
    assert calls == [("tool_call_rejected", {"tool": "get_financial_fact", "reason": "unrecognized_extra_argument", "args": {"ticker": "AAPL", "metric": "revenue", "segment": "Graphics"}})]


def test_validate_tool_args_rejects_missing_required_property(monkeypatch):
    calls = []
    capture_events(monkeypatch, calls)

    rejected = validate_tool_args("get_financial_fact", FACT_TOOL_SCHEMA, {"ticker": "AAPL"})

    assert rejected is True
    assert calls[0][1]["reason"] == "missing_required_argument"


def test_validate_tool_args_reason_names_property_and_violation_kind(monkeypatch):
    calls = []
    capture_events(monkeypatch, calls)

    validate_tool_args("get_financial_fact", FACT_TOOL_SCHEMA, {"ticker": 123, "metric": "revenue"})

    assert calls[0][1]["reason"] == "ticker_wrong_type"


def test_validate_tool_args_lets_metric_enum_violation_through():
    # The one deliberate carve-out: a recognized-shape-but-unsupported
    # metric name must NOT be a generic hard rejection -- callers route it
    # to record_unmet_metric_request instead (see call_get_financial_fact).
    rejected = validate_tool_args(
        "get_financial_fact", FACT_TOOL_SCHEMA, {"ticker": "AAPL", "metric": "effective_tax_rate"}
    )
    assert rejected is False


def test_validate_tool_args_still_rejects_wrong_typed_metric():
    # Contrast with the enum carve-out above: a wrong-TYPE metric (not a
    # string at all) is not the same carve-out and must still hard-fail.
    rejected = validate_tool_args("get_financial_fact", FACT_TOOL_SCHEMA, {"ticker": "AAPL", "metric": ["revenue"]})
    assert rejected is True


def test_validate_tool_args_soft_required_allows_missing_property():
    # search_filings' query: schema-required (encourages the model to
    # include it) but tolerated absent at runtime -- _resolve_search_args
    # substitutes the original question instead of rejecting.
    rejected = validate_tool_args(
        "search_filings", SEARCH_TOOL_SCHEMA, {"ticker": "AAPL"}, soft_required=frozenset({"query"})
    )
    assert rejected is False


def test_validate_tool_args_skip_properties_ignores_malformed_value():
    # get_financial_fact's fiscal_year: the multi-year-average request
    # shape never reads it, so a malformed value must be ignored generically
    # -- _rejects_invalid_fiscal_year only fires on the single-period path.
    rejected = validate_tool_args(
        "get_financial_fact",
        FACT_TOOL_SCHEMA,
        {"ticker": "AAPL", "metric": "revenue", "fiscal_year": "bogus"},
        skip_properties=frozenset({"fiscal_year", "start_fiscal_year", "end_fiscal_year"}),
    )
    assert rejected is False


def test_validate_tool_args_treats_null_optional_property_as_absent():
    # Found in code review: this diff's own period_end_date fix (adding
    # "null" to that one property's declared type after live testing)
    # was the first instance of a general problem, not a one-off -- every
    # other optional property had the same gap. search_filings' ticker is
    # optional (a broad, unsure search is valid) and the old hand-rolled
    # check explicitly tolerated `ticker: None` as "no filter"
    # (`if raw_ticker is not None and (...)`) -- an explicit JSON null
    # must be treated the same way now, not hard-rejected.
    rejected = validate_tool_args(
        "search_filings", SEARCH_TOOL_SCHEMA, {"query": "revenue", "ticker": None}, soft_required=frozenset({"query"})
    )
    assert rejected is False


def test_validate_tool_args_treats_null_required_property_as_missing():
    # The other half of the same fix: for a REQUIRED property, null must
    # still be rejected (as "missing", not "wrong type") -- not silently
    # tolerated just because it's declared.
    rejected = validate_tool_args("get_financial_fact", FACT_TOOL_SCHEMA, {"ticker": None, "metric": "revenue"})
    assert rejected is True


def test_validate_tool_args_still_rejects_null_valued_extra_key(monkeypatch):
    # additionalProperties: false must still catch an unrecognized key
    # even when its value happens to be null -- the key itself is the
    # problem, not its value, so it must not be silently stripped away
    # before validation runs.
    calls = []
    capture_events(monkeypatch, calls)

    rejected = validate_tool_args(
        "get_financial_fact", FACT_TOOL_SCHEMA, {"ticker": "AAPL", "metric": "revenue", "segment": None}
    )

    assert rejected is True
    assert calls[0][1]["reason"] == "unrecognized_extra_argument"


def test_validate_tool_args_skip_properties_still_allows_the_property_itself(monkeypatch):
    # additionalProperties: false must not treat a skip_propertied but
    # otherwise-declared property as an unrecognized extra key.
    calls = []
    capture_events(monkeypatch, calls)

    rejected = validate_tool_args(
        "get_financial_fact",
        FACT_TOOL_SCHEMA,
        {"ticker": "AAPL", "metric": "revenue", "fiscal_year": 2026},
        skip_properties=frozenset({"fiscal_year", "start_fiscal_year", "end_fiscal_year"}),
    )
    assert rejected is False
    assert calls == []


# ---------------------------------------------------------------------------
# SUBMIT_TOOL_SCHEMA (2026-09-10) -- the structured-claims final-answer
# tool, see docs/plans/2026-09-10-structured-claims-citation-verification.md.
# Same {"type":"function","function":{...}} envelope every existing tool
# uses, so validate_tool_args() (exercised above) is reusable verbatim --
# these tests exercise ITS acceptance/rejection of submit_answer's actual
# shape, not validate_tool_args itself again.
# ---------------------------------------------------------------------------
def _valid_claim(**overrides):
    claim = {"value": 100.0, "unit": "raw", "citation_index": 1, "quote": "the value was 100"}
    claim.update(overrides)
    return claim


def test_submit_tool_schema_accepts_a_valid_payload():
    args = {"answer_text": "The value was 100 [1].", "claims": [_valid_claim()]}
    assert validate_tool_args("submit_answer", SUBMIT_TOOL_SCHEMA, args) is False


def test_submit_tool_schema_accepts_empty_claims():
    # A refusal ("the sources don't support this") is a valid answer with
    # zero numeric claims -- claims: [] must stay legal, no minItems.
    args = {"answer_text": "I can't confirm this from the sources provided.", "claims": []}
    assert validate_tool_args("submit_answer", SUBMIT_TOOL_SCHEMA, args) is False


def test_submit_tool_schema_rejects_missing_answer_text():
    args = {"claims": []}
    assert validate_tool_args("submit_answer", SUBMIT_TOOL_SCHEMA, args) is True


def test_submit_tool_schema_rejects_claim_missing_quote():
    claim = _valid_claim()
    del claim["quote"]
    args = {"answer_text": "text", "claims": [claim]}
    assert validate_tool_args("submit_answer", SUBMIT_TOOL_SCHEMA, args) is True


def test_submit_tool_schema_rejects_claim_missing_citation_index():
    claim = _valid_claim()
    del claim["citation_index"]
    args = {"answer_text": "text", "claims": [claim]}
    assert validate_tool_args("submit_answer", SUBMIT_TOOL_SCHEMA, args) is True


def test_submit_tool_schema_accepts_a_qualitative_claim_with_no_value_or_unit():
    # 2026-09-15: value/unit are no longer required, so a citation marker
    # supporting a purely qualitative fact can validly omit both.
    claim = {"citation_index": 1, "quote": "the value was 100"}
    args = {"answer_text": "text [1].", "claims": [claim]}
    assert validate_tool_args("submit_answer", SUBMIT_TOOL_SCHEMA, args) is False


def test_submit_tool_schema_rejects_invented_claim_key():
    args = {"answer_text": "text", "claims": [_valid_claim(confidence=0.9)]}
    assert validate_tool_args("submit_answer", SUBMIT_TOOL_SCHEMA, args) is True


def test_submit_tool_schema_rejects_unknown_unit():
    args = {"answer_text": "text", "claims": [_valid_claim(unit="dollars")]}
    assert validate_tool_args("submit_answer", SUBMIT_TOOL_SCHEMA, args) is True


def test_submit_tool_schema_rejects_non_integer_citation_index():
    args = {"answer_text": "text", "claims": [_valid_claim(citation_index="1")]}
    assert validate_tool_args("submit_answer", SUBMIT_TOOL_SCHEMA, args) is True


def test_submit_tool_schema_excluded_from_mcp_server_tool_schemas():
    # mcp_server.py exposes the individual tools over MCP, not the LLM
    # agent loop -- submit_answer is a final-answer mechanism internal to
    # agent.py's own loop and must never be offered there.
    from sec_agent import mcp_server

    assert SUBMIT_TOOL_SCHEMA not in mcp_server._TOOL_SCHEMAS


# ---------------------------------------------------------------------------
# CALCULATE_TOOL_SCHEMA (2026-09-11) -- lets the model perform verified
# arithmetic instead of a self-computed value that can never pass
# verify_claims (see docs/plans/2026-09-11-calculate-tool-and-stress-questions.md).
# Same envelope every tool uses, so these tests exercise validate_tool_args'
# acceptance/rejection of calculate's actual shape, same style as
# SUBMIT_TOOL_SCHEMA's tests above.
# ---------------------------------------------------------------------------


def test_calculate_tool_schema_accepts_a_valid_payload():
    assert validate_tool_args("calculate", CALCULATE_TOOL_SCHEMA, _valid_calculate_args()) is False


def test_calculate_tool_schema_rejects_missing_operand():
    args = _valid_calculate_args()
    del args["operand_b"]
    assert validate_tool_args("calculate", CALCULATE_TOOL_SCHEMA, args) is True


def test_calculate_tool_schema_rejects_unknown_operation():
    assert validate_tool_args("calculate", CALCULATE_TOOL_SCHEMA, _valid_calculate_args(operation="square_root")) is True


def test_calculate_tool_schema_rejects_unknown_unit():
    assert validate_tool_args("calculate", CALCULATE_TOOL_SCHEMA, _valid_calculate_args(unit_a="dollars")) is True


def test_calculate_tool_schema_rejects_non_integer_citation_index():
    assert (
        validate_tool_args("calculate", CALCULATE_TOOL_SCHEMA, _valid_calculate_args(citation_index_a="1")) is True
    )


def test_calculate_tool_schema_rejects_invented_key():
    assert validate_tool_args("calculate", CALCULATE_TOOL_SCHEMA, _valid_calculate_args(confidence=0.9)) is True


def test_calculate_tool_schema_excluded_from_mcp_server_tool_schemas():
    # Same reasoning as submit_answer: citation_index_a/citation_index_b
    # are only meaningful within one _run_agent_impl run's own
    # all_results, not to a standalone MCP caller.
    from sec_agent import mcp_server

    assert CALCULATE_TOOL_SCHEMA not in mcp_server._TOOL_SCHEMAS
