"""
Unit tests for calculate.py: operand grounding, the arithmetic, and the
result entry a calculation becomes.
"""

from sec_agent.agent.agent import _dispatch_tool_call
from sec_agent.agent.calculate import call_calculate, _calculation_as_result
from sec_agent.agent.tool_results import _format_results_block
from tests.agent.helpers import _fake_result, _valid_calculate_args, capture_events


# ---------------------------------------------------------------------------
# call_calculate() (2026-09-11) -- the two guarantees the calculate tool
# provides: operand GROUNDING (each operand must actually appear in its
# cited source, via the same _number_candidates() primitive
# _verify_one_claim already uses) and arithmetic CORRECTNESS (the
# operation runs in real Python, never trusted from the model). Returns
# (result_dict, None) on success, (None, error_message) on failure --
# richer than call_get_financial_fact's bare dict|None because calculate
# has several distinct failure reasons that each need their own specific,
# actionable message.
# ---------------------------------------------------------------------------
def test_call_calculate_percent_of():
    all_results = [
        _fake_result(text="R&D expense was $34,550 million for fiscal year 2025."),
        _fake_result(text="Gross profit was $195,201 million for fiscal year 2025."),
    ]
    result, error = call_calculate(_valid_calculate_args(), all_results)
    assert error is None
    assert result == {"value": 17.7, "unit": "percent"}


def test_call_calculate_percent_change():
    all_results = [
        _fake_result(text="Revenue was $81,615 million for the current quarter."),
        _fake_result(text="Revenue was $44,062 million for the prior-year quarter."),
    ]
    args = _valid_calculate_args(
        operation="percent_change", operand_a=81615.0, unit_a="million", operand_b=44062.0, unit_b="million"
    )
    result, error = call_calculate(args, all_results)
    assert error is None
    assert result == {"value": 85.2, "unit": "percent"}


def test_call_calculate_add():
    all_results = [
        _fake_result(text="Segment A revenue was $100 million."),
        _fake_result(text="Segment B revenue was $50 million."),
    ]
    args = _valid_calculate_args(operation="add", operand_a=100.0, unit_a="million", operand_b=50.0, unit_b="million")
    result, error = call_calculate(args, all_results)
    assert error is None
    assert result == {"value": 150_000_000.0, "unit": "raw"}


def test_call_calculate_subtract():
    all_results = [
        _fake_result(text="Total assets were $694,228 million."),
        _fake_result(text="Total liabilities were $300,000 million."),
    ]
    args = _valid_calculate_args(
        operation="subtract", operand_a=694228.0, unit_a="million", operand_b=300000.0, unit_b="million"
    )
    result, error = call_calculate(args, all_results)
    assert error is None
    assert result == {"value": 394_228_000_000.0, "unit": "raw"}


def test_call_calculate_multiply():
    all_results = [_fake_result(text="1000 shares outstanding."), _fake_result(text="$50 price per share.")]
    args = _valid_calculate_args(
        operation="multiply", operand_a=1000.0, unit_a="raw", operand_b=50.0, unit_b="raw"
    )
    result, error = call_calculate(args, all_results)
    assert error is None
    assert result == {"value": 50_000.0, "unit": "raw"}


def test_call_calculate_divide_rounds_to_two_decimals_like_formulas_py():
    all_results = [_fake_result(text="Current assets were $150 million."), _fake_result(text="Current liabilities were $100 million.")]
    args = _valid_calculate_args(
        operation="divide", operand_a=150.0, unit_a="million", operand_b=100.0, unit_b="million"
    )
    result, error = call_calculate(args, all_results)
    assert error is None
    assert result == {"value": 1.5, "unit": "raw"}


def test_call_calculate_handles_unit_scale_mismatch_via_normalize():
    # 34550 million and 195.201 billion are the same real quantities as
    # the percent_of test above (195201 million == 195.201 billion) --
    # normalize() must reconcile the scale mismatch before dividing.
    all_results = [
        _fake_result(text="R&D expense was $34,550 million."),
        _fake_result(text="Gross profit was $195.201 billion."),
    ]
    args = _valid_calculate_args(operand_b=195.201, unit_b="billion")
    result, error = call_calculate(args, all_results)
    assert error is None
    assert result == {"value": 17.7, "unit": "percent"}


def test_call_calculate_rejects_divide_by_zero():
    all_results = [_fake_result(text="Value was $100 million."), _fake_result(text="Value was $0 million.")]
    args = _valid_calculate_args(operand_a=100.0, unit_a="million", operand_b=0.0)
    result, error = call_calculate(args, all_results)
    assert result is None
    assert error is not None
    assert "zero" in error.lower()


def test_call_calculate_rejects_divide_by_zero_for_plain_divide_too():
    all_results = [_fake_result(text="Value was $100 million."), _fake_result(text="Value was $0 million.")]
    args = _valid_calculate_args(operation="divide", operand_a=100.0, unit_a="million", operand_b=0.0)
    result, error = call_calculate(args, all_results)
    assert result is None
    assert error is not None
    assert "zero" in error.lower()


def test_call_calculate_rejects_out_of_range_citation_index():
    all_results = [_fake_result(text="R&D expense was $34,550 million.")]
    args = _valid_calculate_args(citation_index_b=5)
    result, error = call_calculate(args, all_results)
    assert result is None
    assert error is not None
    assert "[5]" in error or "5" in error


def test_call_calculate_rejects_operand_not_grounded_in_cited_source():
    all_results = [
        _fake_result(text="R&D expense was $34,550 million."),
        _fake_result(text="Cost of revenue was $60,000 million."),  # doesn't contain 195201
    ]
    result, error = call_calculate(_valid_calculate_args(), all_results)
    assert result is None
    assert error is not None
    assert "operand_b" in error
    assert "[2]" in error


def test_call_calculate_rejects_operand_a_not_grounded_names_it_specifically():
    all_results = [
        _fake_result(text="Cost of revenue was $60,000 million."),  # doesn't contain 34550
        _fake_result(text="Gross profit was $195,201 million."),
    ]
    result, error = call_calculate(_valid_calculate_args(), all_results)
    assert result is None
    assert error is not None
    assert "operand_a" in error
    assert "[1]" in error


def test_call_calculate_operand_wrong_unit_names_the_correct_unit_not_the_value():
    # Regression test for the 2026-09-13 baseline finding (aapl-revenue-
    # growth-q3fy2026): a value mislabeled "billion" that's actually raw
    # got a message blaming the value/citation index, both correct --
    # the model's retry changed neither and failed identically twice.
    # The fixed message must name the UNIT specifically as the problem.
    all_results = [
        _fake_result(text="Revenue was $109,417,000,000."),
        _fake_result(text="Prior-year revenue was $94,036,000,000."),
    ]
    args = _valid_calculate_args(
        operation="percent_change",
        operand_a=109417000000,
        unit_a="billion",
        citation_index_a=1,
        operand_b=94036000000,
        unit_b="raw",
        citation_index_b=2,
    )
    result, error = call_calculate(args, all_results)
    assert result is None
    assert error is not None
    assert "operand_a" in error
    assert "billion" in error.lower()
    assert "raw" in error.lower()
    assert "unit" in error.lower()


def test_call_calculate_operand_wrong_citation_index_names_the_correct_result():
    # Regression guard for a review finding: an earlier version of the
    # terminal message claimed "a different citation index will not
    # help" without ever checking any OTHER already-retrieved result --
    # if the value actually lives in a different result (a plausible
    # citation-index transcription slip), that message would have been
    # false and would have told the model not to bother trying the fix
    # that actually works. operand_a (34550 million) is cited against
    # [1], which doesn't contain it, but genuinely lives in [2].
    all_results = [
        _fake_result(text="Cost of revenue was $60,000 million."),
        _fake_result(text="R&D expense was $34,550 million. Gross profit was $195,201 million."),
    ]
    args = _valid_calculate_args(citation_index_a=1)
    result, error = call_calculate(args, all_results)
    assert result is None
    assert error is not None
    assert "operand_a" in error
    assert "[2]" in error
    assert "citation index" in error.lower()


def test_call_calculate_operand_ungroundable_under_any_unit_says_not_retryable():
    # A literal conversion constant (e.g. 1,000,000,000 to convert to
    # billions) has no citation to ground against at all -- distinct
    # from the mislabeled-unit case above, this is a genuinely terminal
    # failure and the message must say so rather than invite a retry
    # that cannot succeed.
    all_results = [_fake_result(text="Revenue was $4,475,446,000.")]
    args = _valid_calculate_args(
        operation="divide",
        operand_a=4475446000,
        unit_a="raw",
        citation_index_a=1,
        operand_b=1000000000,
        unit_b="raw",
        citation_index_b=1,
    )
    result, error = call_calculate(args, all_results)
    assert result is None
    assert error is not None
    assert "operand_b" in error
    assert "not a retryable mistake" in error.lower() or "not retryable" in error.lower()


def test_call_calculate_rejects_mismatched_categories():
    all_results = [
        _fake_result(text="Growth was 20 percent."),
        _fake_result(text="Revenue was $100 million."),
    ]
    args = _valid_calculate_args(operand_a=20.0, unit_a="percent", operand_b=100.0, unit_b="million")
    result, error = call_calculate(args, all_results)
    assert result is None
    assert error is not None
    assert "percent" in error.lower() and "scale" in error.lower()


def test_call_calculate_rejects_malformed_args_via_schema():
    all_results = [_fake_result(), _fake_result()]
    args = _valid_calculate_args()
    del args["operand_a"]
    result, error = call_calculate(args, all_results)
    assert result is None
    assert error is not None


# ---------------------------------------------------------------------------
# _calculation_as_result() -- wraps a call_calculate() result in the same
# {text, metadata} shape every other all_results entry uses, with `text`
# rendering the full expression so it's directly quotable by
# _quote_matches/_number_candidates (proven end-to-end below, not just
# asserted -- the whole point of this tool is that its output flows
# through verify_claims/_verify_one_claim completely unchanged).
# ---------------------------------------------------------------------------
def test_calculation_as_result_text_is_directly_quotable_end_to_end():
    all_results = [
        _fake_result(text="R&D expense was $34,550 million."),
        _fake_result(text="Gross profit was $195,201 million."),
    ]
    args = _valid_calculate_args()
    calc_result, error = call_calculate(args, all_results)
    assert error is None
    assert calc_result is not None
    entry = _calculation_as_result(calc_result, args)
    assert "17.7" in entry["text"]
    assert "percent" in entry["text"]

    # The whole point: a submit_answer claim citing this new result must
    # pass _verify_one_claim's existing, unchanged pipeline -- no new
    # verification code needed for calculate-sourced claims.
    all_results_with_calc = all_results + [entry]
    claim = {
        "value": 17.7,
        "unit": "percent",
        "citation_index": 3,
        "quote": entry["text"],
    }
    from sec_agent.agent.citations import _verify_one_claim

    assert _verify_one_claim(claim, all_results_with_calc) is None


def test_calculation_as_result_renders_percent_change_as_from_b_to_a():
    # percent_change reads operand_b as the old value and operand_a as the
    # new one, so the expression names them in that order.
    all_results = [
        _fake_result(text="Revenue was $81,615 million for the current quarter."),
        _fake_result(text="Revenue was $44,062 million for the prior-year quarter."),
    ]
    args = _valid_calculate_args(
        operation="percent_change", operand_a=81615.0, unit_a="million", operand_b=44062.0, unit_b="million"
    )
    calc_result, error = call_calculate(args, all_results)
    assert error is None
    assert calc_result is not None

    entry = _calculation_as_result(calc_result, args)

    assert entry["text"] == (
        "percentage change from 44062 million to 81615 million = 85.2 percent "
        "(computed value, not directly stated in any filing; operands from results [1] and [2])"
    )


def test_calculation_as_result_text_avoids_scientific_notation_for_large_values():
    # Found in code review, 2026-09-11: str()'s default formatting
    # switches to scientific notation ("1e+18") outside roughly
    # 1e16..1e-4, but NUMBER_PATTERN (numeric_utils.py) has no exponent
    # support -- a value in that range could never be re-extracted from
    # the very citation text this function generates, so a correct,
    # tool-computed value would be refused as ungrounded by the exact
    # gate this tool exists to satisfy. multiply of two billion-scale
    # operands is a realistic way to reach this range (e.g. a
    # shares-times-price-style question with unusually large operands).
    all_results = [
        _fake_result(text="Value A is 1 billion."),
        _fake_result(text="Value B is 1 billion."),
    ]
    args = _valid_calculate_args(
        operation="multiply", operand_a=1.0, unit_a="billion", operand_b=1.0, unit_b="billion"
    )
    calc_result, error = call_calculate(args, all_results)
    assert error is None
    assert calc_result is not None
    assert calc_result["value"] == 1e18  # sanity check on the premise

    entry = _calculation_as_result(calc_result, args)
    assert "e+" not in entry["text"].lower()
    assert "1000000000000000000" in entry["text"]

    # The real-world consequence: a claim citing this result must still
    # verify, the same end-to-end proof as the percent_of test above.
    all_results_with_calc = all_results + [entry]
    claim = {"value": 1e18, "unit": "raw", "citation_index": 3, "quote": entry["text"]}
    from sec_agent.agent.citations import _verify_one_claim

    assert _verify_one_claim(claim, all_results_with_calc) is None


def test_calculation_as_result_has_metadata_required_by_format_results_block():
    all_results = [
        _fake_result(text="R&D expense was $34,550 million."),
        _fake_result(text="Gross profit was $195,201 million."),
    ]
    args = _valid_calculate_args()
    calc_result, _ = call_calculate(args, all_results)
    assert calc_result is not None
    entry = _calculation_as_result(calc_result, args)
    # _format_results_block reads meta['ticker']/['form']/['reportDate'] --
    # a KeyError here would only surface live, the first time a
    # calculate result is ever rendered back to the model.
    block = _format_results_block([entry], 3)
    assert "[3]" in block


def test_dispatch_no_data_reply_names_the_converted_year_and_logs_once(monkeypatch):
    events = []
    capture_events(monkeypatch, events)
    monkeypatch.setattr("sec_agent.agent.fact_tools.get_ratio", lambda *a, **k: None)
    call = {"name": "get_financial_fact", "args": {"ticker": "NVDA", "metric": "gross_margin", "fiscal_year": "2025"}}

    content = _dispatch_tool_call(call, "q", [], set(), verbose=False)

    assert "'FY' FY2025" in content
    assert "FY'2025'" not in content
    assert [c for c, _ in events].count("tool_arg_coerced") == 1
