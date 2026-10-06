"""
Unit tests for fact_tools.py: call_get_financial_fact and
call_compare_financial_metric (argument checks, lookups via monkeypatched
xbrl_facts/formulas, unmet-request tracing, rejection logging) and the
result entries they produce.
"""

from sec_agent.agent.fact_tools import (
    call_compare_financial_metric,
    call_get_financial_fact,
    comparison_as_results,
    _format_fact_value,
)
from tests.agent.helpers import capture_events


# ---------------------------------------------------------------------------
# _format_fact_value (found in code review, 2026-08-25: "raw" is an
# internal numeric_utils.normalize() category label, not a
# natural-language unit -- get_asset_turnover's citation text shouldn't
# read "1.04 raw")
# ---------------------------------------------------------------------------
def test_format_fact_value_omits_unit_word_for_raw():
    assert _format_fact_value({"value": 1.04, "unit": "raw"}) == "1.04"


def test_format_fact_value_includes_unit_word_for_percent():
    assert _format_fact_value({"value": 31.2, "unit": "percent"}) == "31.2 percent"


# ---------------------------------------------------------------------------
# comparison_as_results (compare_financial_metric)
# ---------------------------------------------------------------------------
def test_comparison_as_results_one_entry_per_company_sorted_by_ticker():
    data = {
        "NVDA": {"value": 74.9, "unit": "percent", "period_end": "2026-04-26", "accession": "b"},
        "AAPL": {"value": 49.3, "unit": "percent", "period_end": "2026-03-28", "accession": "a"},
    }
    results = comparison_as_results(data, "gross_margin")
    assert [r["metadata"]["ticker"] for r in results] == ["AAPL", "NVDA"]
    assert "AAPL gross_margin = 49.3 percent" in results[0]["text"]
    assert results[0]["metadata"]["form"] == "XBRL frame data"
    assert results[0]["metadata"]["accessionNumber"] == "a"


def test_comparison_as_results_empty_dict_returns_empty_list():
    assert comparison_as_results({}, "revenue") == []


def test_comparison_as_results_uses_real_form_when_present():
    # Instant metrics (total_assets etc., 2026-09-07 redesign) resolve
    # via independent per-company get_metric() calls, which DO carry a
    # real form (10-K/10-Q) unlike frame-sourced duration-metric facts.
    data = {
        "AAPL": {
            "value": 359241000000,
            "unit": "USD",
            "period_end": "2025-09-27",
            "accession": "a",
            "form": "10-K",
        },
    }
    results = comparison_as_results(data, "total_assets")
    assert results[0]["metadata"]["form"] == "10-K"


# ---------------------------------------------------------------------------
# jsonschema's bool-exclusion from "integer" -- the recurring bug this whole
# redesign exists to fix structurally: isinstance(True, int) is True in
# Python, so the old hand-rolled `isinstance(fiscal_year, int)` check
# silently accepted a JSON boolean (2026-09-09 review, left open at the
# time). jsonschema's default type checker already excludes bool from
# "integer", so this is fixed as a side effect of the library switch.
# ---------------------------------------------------------------------------
def test_call_get_financial_fact_rejects_boolean_fiscal_year(monkeypatch):
    calls = []
    capture_events(monkeypatch, calls)

    result = call_get_financial_fact({"ticker": "AAPL", "metric": "revenue", "fiscal_year": True})

    assert result is None
    assert calls[-1][1]["reason"] == "invalid_fiscal_year_type"


def test_call_compare_financial_metric_rejects_boolean_fiscal_year(monkeypatch):
    calls = []
    capture_events(monkeypatch, calls)

    result = call_compare_financial_metric({"anchor_ticker": "AAPL", "metric": "revenue", "fiscal_year": True})

    assert result == {}
    assert calls[-1][1]["reason"] == "invalid_fiscal_year_type"


# ---------------------------------------------------------------------------
# call_get_financial_fact / call_compare_financial_metric
# (margin dispatch + yoy_growth boundary validation)
# ---------------------------------------------------------------------------
def test_call_get_financial_fact_dispatches_operating_margin(monkeypatch):
    # get_ratio() is the single generic dispatch point for every
    # RATIO_DEFINITIONS entry now -- unlike the old RATIO_METRIC_FUNCTIONS/
    # SINGLE_COMPANY_RATIO_FUNCTIONS dicts (which bound function objects
    # at import time, so a monkeypatch had to target the dict entry
    # itself), get_ratio is looked up fresh by bare name each call, so
    # patching agent.get_ratio directly is the correct seam -- same
    # pattern already used for get_yoy_growth/get_multi_year_average
    # below. Asserting the exact call args, not just the return value,
    # keeps this test meaningfully distinguishing "operating_margin" from
    # any other ratio, since the mock itself no longer does.
    calls = []
    monkeypatch.setattr(
        "sec_agent.agent.fact_tools.get_ratio",
        lambda ticker, ratio_name, fiscal_year, fiscal_period, period_end_date: calls.append(
            (ticker, ratio_name, fiscal_year, fiscal_period, period_end_date)
        )
        or {"value": 60.0, "unit": "percent"},
    )
    result = call_get_financial_fact(
        {"ticker": "NVDA", "metric": "operating_margin", "fiscal_year": 2026, "fiscal_period": "FY"}
    )
    assert result == {"value": 60.0, "unit": "percent"}
    assert calls == [("NVDA", "operating_margin", 2026, "FY", None)]


def test_call_get_financial_fact_dispatches_net_margin(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "sec_agent.agent.fact_tools.get_ratio",
        lambda ticker, ratio_name, fiscal_year, fiscal_period, period_end_date: calls.append(ratio_name)
        or {"value": 45.0, "unit": "percent"},
    )
    result = call_get_financial_fact(
        {"ticker": "NVDA", "metric": "net_margin", "fiscal_year": 2026, "fiscal_period": "FY"}
    )
    assert result == {"value": 45.0, "unit": "percent"}
    assert calls == ["net_margin"]


def test_call_get_financial_fact_dispatches_return_on_assets(monkeypatch):
    # return_on_assets/asset_turnover/cash_to_assets/inventory_turnover/
    # rd_intensity all have supports_cross_company=False in
    # RATIO_DEFINITIONS, but get_financial_fact supports every ratio
    # regardless of that flag -- same generic get_ratio() dispatch as
    # any other ratio, see formulas.get_return_on_assets's own docstring
    # for why there's no cross-company counterpart.
    calls = []
    monkeypatch.setattr(
        "sec_agent.agent.fact_tools.get_ratio",
        lambda ticker, ratio_name, fiscal_year, fiscal_period, period_end_date: calls.append(ratio_name)
        or {"value": 31.2, "unit": "percent"},
    )
    result = call_get_financial_fact(
        {"ticker": "AAPL", "metric": "return_on_assets", "fiscal_year": 2025, "fiscal_period": "FY"}
    )
    assert result == {"value": 31.2, "unit": "percent"}
    assert calls == ["return_on_assets"]


def test_call_get_financial_fact_dispatches_asset_turnover(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "sec_agent.agent.fact_tools.get_ratio",
        lambda ticker, ratio_name, fiscal_year, fiscal_period, period_end_date: calls.append(ratio_name)
        or {"value": 1.04, "unit": "raw"},
    )
    result = call_get_financial_fact(
        {"ticker": "NVDA", "metric": "asset_turnover", "fiscal_year": 2026, "fiscal_period": "FY"}
    )
    assert result == {"value": 1.04, "unit": "raw"}
    assert calls == ["asset_turnover"]


def test_call_get_financial_fact_dispatches_cash_to_assets(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "sec_agent.agent.fact_tools.get_ratio",
        lambda ticker, ratio_name, fiscal_year, fiscal_period, period_end_date: calls.append(ratio_name)
        or {"value": 4.9, "unit": "percent"},
    )
    result = call_get_financial_fact(
        {"ticker": "MSFT", "metric": "cash_to_assets", "fiscal_year": 2025, "fiscal_period": "FY"}
    )
    assert result == {"value": 4.9, "unit": "percent"}
    assert calls == ["cash_to_assets"]


def test_call_get_financial_fact_dispatches_inventory_turnover(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "sec_agent.agent.fact_tools.get_ratio",
        lambda ticker, ratio_name, fiscal_year, fiscal_period, period_end_date: calls.append(ratio_name)
        or {"value": 5.2, "unit": "raw"},
    )
    result = call_get_financial_fact(
        {"ticker": "NVDA", "metric": "inventory_turnover", "fiscal_year": 2026, "fiscal_period": "FY"}
    )
    assert result == {"value": 5.2, "unit": "raw"}
    assert calls == ["inventory_turnover"]


def test_call_get_financial_fact_dispatches_rd_intensity(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "sec_agent.agent.fact_tools.get_ratio",
        lambda ticker, ratio_name, fiscal_year, fiscal_period, period_end_date: calls.append(ratio_name)
        or {"value": 18.3, "unit": "percent"},
    )
    result = call_get_financial_fact(
        {"ticker": "NVDA", "metric": "rd_intensity", "fiscal_year": 2026, "fiscal_period": "FY"}
    )
    assert result == {"value": 18.3, "unit": "percent"}
    assert calls == ["rd_intensity"]


def test_call_get_financial_fact_rejects_yoy_growth_combined_with_single_company_ratio():
    # Same reasoning as the margin+yoy_growth rejection below -- "growth
    # of a ratio" has no current evidence/use case for these three
    # either, so it's rejected the same way rather than silently
    # computed or passed through to get_yoy_growth (which doesn't
    # support ratio metrics at all).
    result = call_get_financial_fact({"ticker": "NVDA", "metric": "asset_turnover", "yoy_growth": True})
    assert result is None


def test_call_get_financial_fact_dispatches_yoy_growth_for_raw_metric(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "sec_agent.agent.fact_tools.get_yoy_growth",
        lambda ticker, metric, fiscal_year, fiscal_period, period_end_date: calls.append((ticker, metric))
        or {"value": 10.0, "unit": "percent"},
    )
    result = call_get_financial_fact(
        {"ticker": "AAPL", "metric": "revenue", "yoy_growth": True, "fiscal_year": 2026, "fiscal_period": "Q3"}
    )
    assert result == {"value": 10.0, "unit": "percent"}
    assert calls == [("AAPL", "revenue")]


def test_call_get_financial_fact_rejects_yoy_growth_combined_with_margin_metric():
    # get_yoy_growth() doesn't support ratio metrics (see its own
    # docstring) -- caught here at the boundary, same reasoning as this
    # function's existing invalid-metric guard, rather than letting
    # xbrl_facts raise or silently compute something nonsensical.
    result = call_get_financial_fact({"ticker": "AAPL", "metric": "gross_margin", "yoy_growth": True})
    assert result is None


def test_call_get_financial_fact_dispatches_multi_year_average(monkeypatch):
    # Regression case: aapl-3yr-avg-operating-margin-fy2023-fy2025. With
    # no deterministic path before this existed, the model self-computed
    # an average from 3 separate calls (a rule-3 violation) or misparsed
    # the whole request as Q4-specific.
    calls = []
    monkeypatch.setattr(
        "sec_agent.agent.fact_tools.get_multi_year_average",
        lambda ticker, metric, start_fiscal_year, end_fiscal_year: calls.append(
            (ticker, metric, start_fiscal_year, end_fiscal_year)
        )
        or {"value": 31.1, "unit": "percent"},
    )
    result = call_get_financial_fact(
        {"ticker": "AAPL", "metric": "operating_margin", "start_fiscal_year": 2023, "end_fiscal_year": 2025}
    )
    assert result == {"value": 31.1, "unit": "percent"}
    assert calls == [("AAPL", "operating_margin", 2023, 2025)]


def test_call_get_financial_fact_ignores_malformed_fiscal_year_in_multi_year_average_request(monkeypatch):
    # Found in code review (round 2, 2026-09-09): the new §8 fiscal_year
    # type guard was placed before this branch even checks whether
    # start_fiscal_year/end_fiscal_year are present -- fiscal_year is
    # never read inside get_multi_year_average()'s call below, so a
    # stray malformed fiscal_year alongside a VALID start/end pair used
    # to wrongly reject the whole request instead of being ignored, the
    # same as it always was pre-fix.
    calls = []
    monkeypatch.setattr(
        "sec_agent.agent.fact_tools.get_multi_year_average",
        lambda ticker, metric, start_fiscal_year, end_fiscal_year: calls.append(
            (ticker, metric, start_fiscal_year, end_fiscal_year)
        )
        or {"value": 31.1, "unit": "percent"},
    )
    result = call_get_financial_fact(
        {
            "ticker": "AAPL",
            "metric": "operating_margin",
            "start_fiscal_year": 2023,
            "end_fiscal_year": 2025,
            "fiscal_year": "bogus",
        }
    )
    assert result == {"value": 31.1, "unit": "percent"}
    assert calls == [("AAPL", "operating_margin", 2023, 2025)]


def test_call_get_financial_fact_rejects_multi_year_average_combined_with_yoy_growth():
    # Nonsensical combination -- caught explicitly rather than silently
    # picking one, same discipline as the yoy_growth+margin rejection.
    result = call_get_financial_fact(
        {"ticker": "AAPL", "metric": "revenue", "start_fiscal_year": 2023, "end_fiscal_year": 2025, "yoy_growth": True}
    )
    assert result is None


def test_call_get_financial_fact_rejects_partial_multi_year_average_range(monkeypatch):
    # Only one of start/end given -- malformed, not a valid single-period
    # lookup either (fiscal_year/fiscal_period/period_end_date are all
    # absent), so this must reject rather than silently falling through
    # to a plain get_metric() call with fiscal_year=None.
    monkeypatch.setattr("sec_agent.agent.fact_tools.get_metric", lambda *a, **k: {"value": 999})
    result = call_get_financial_fact({"ticker": "AAPL", "metric": "revenue", "start_fiscal_year": 2023})
    assert result is None


def test_call_get_financial_fact_rejects_unrecognized_extra_argument(monkeypatch):
    # Regression case: nvda-segment-revenue-comparison-q1fy27. The model
    # invented a `segment` filter this tool doesn't support; the old code
    # silently ignored it (only ever read known keys via args.get(...)),
    # so both a "Compute & Networking" and a "Graphics" call silently
    # returned the SAME consolidated total -- a plausible-looking but
    # wrong value, not an error the model could react to. An unrecognized
    # key must reject the call entirely (falls through to the "no
    # structured data found -- try search_filings" message) rather than
    # silently succeeding with a misleading result.
    calls = []
    monkeypatch.setattr("sec_agent.agent.fact_tools.get_metric", lambda *a, **k: calls.append((a, k)) or {"value": 1})
    result = call_get_financial_fact(
        {"ticker": "NVDA", "metric": "revenue", "period_end_date": "2026-04-26", "segment": "Graphics"}
    )
    assert result is None
    assert calls == []  # never even reached the real lookup


def test_call_get_financial_fact_still_works_with_only_known_keys(monkeypatch):
    # Sanity check for the test above: a call using ONLY recognized keys
    # must still reach the real lookup, so the new guard isn't
    # accidentally rejecting legitimate calls too.
    monkeypatch.setattr("sec_agent.agent.fact_tools.get_metric", lambda *a, **k: {"value": 42})
    result = call_get_financial_fact(
        {"ticker": "AAPL", "metric": "revenue", "fiscal_year": 2026, "fiscal_period": "FY", "period_end_date": None}
    )
    assert result == {"value": 42}


# ---------------------------------------------------------------------------
# Unmet-metric-request tracing (Week 7 guardrails, Langfuse): the
# specific "let evidence decide" requirement added 2026-08-28 -- record
# when a metric/ratio request comes back empty for a reason worth
# tracking, distinguishing "we don't know this metric at all" from "we
# know it, but this ticker has no data for it."
# ---------------------------------------------------------------------------
def test_call_get_financial_fact_records_unmet_request_for_unknown_metric(monkeypatch):
    calls = []
    monkeypatch.setattr("sec_agent.agent.fact_tools.record_unmet_metric_request", lambda *a, **k: calls.append((a, k)))

    result = call_get_financial_fact(
        {"ticker": "AAPL", "metric": "effective_tax_rate"}, question="What is AAPL's effective tax rate?"
    )

    assert result is None
    assert calls == [
        (
            ("AAPL", "effective_tax_rate"),
            {"reason": "unknown_metric", "question": "What is AAPL's effective tax rate?"},
        )
    ]


def test_call_get_financial_fact_records_unmet_request_with_no_data_for_ticker(monkeypatch):
    calls = []
    monkeypatch.setattr("sec_agent.agent.fact_tools.get_metric", lambda *a, **k: None)
    monkeypatch.setattr("sec_agent.agent.fact_tools.record_unmet_metric_request", lambda *a, **k: calls.append((a, k)))

    result = call_get_financial_fact({"ticker": "PLTR", "metric": "revenue"})

    assert result is None
    assert calls == [(("PLTR", "revenue"), {"reason": "no_data_for_ticker", "question": None})]


def test_call_get_financial_fact_does_not_record_unmet_request_on_success(monkeypatch):
    calls = []
    monkeypatch.setattr("sec_agent.agent.fact_tools.get_metric", lambda *a, **k: {"value": 42})
    monkeypatch.setattr("sec_agent.agent.fact_tools.record_unmet_metric_request", lambda *a, **k: calls.append((a, k)))

    result = call_get_financial_fact({"ticker": "AAPL", "metric": "revenue"})

    assert result == {"value": 42}
    assert calls == []


def test_call_get_financial_fact_does_not_record_unmet_request_on_boundary_rejection(monkeypatch):
    # Malformed/invented args (an unrecognized extra key here) are a
    # different problem than "this formula doesn't exist" -- they
    # shouldn't pollute the unmet-metric-request signal with noise from
    # the model not following the schema.
    calls = []
    monkeypatch.setattr("sec_agent.agent.fact_tools.record_unmet_metric_request", lambda *a, **k: calls.append((a, k)))

    result = call_get_financial_fact({"ticker": "NVDA", "metric": "revenue", "segment": "Graphics"})

    assert result is None
    assert calls == []


def test_call_get_financial_fact_records_unmet_request_when_yoy_growth_has_no_data(monkeypatch):
    # Found in code review: get_yoy_growth() returning None for a
    # genuine no-prior-period-data reason (not a schema violation, the
    # metric/args are perfectly valid) was silently invisible to the
    # unmet-metric-request signal -- unlike the plain-metric path just
    # above, which already records this.
    calls = []
    monkeypatch.setattr("sec_agent.agent.fact_tools.get_yoy_growth", lambda *a, **k: None)
    monkeypatch.setattr("sec_agent.agent.fact_tools.record_unmet_metric_request", lambda *a, **k: calls.append((a, k)))

    result = call_get_financial_fact({"ticker": "AAPL", "metric": "revenue", "yoy_growth": True})

    assert result is None
    assert calls == [(("AAPL", "revenue"), {"reason": "no_data_for_ticker", "question": None})]


def test_call_get_financial_fact_records_unmet_request_when_multi_year_average_has_no_data(monkeypatch):
    calls = []
    monkeypatch.setattr("sec_agent.agent.fact_tools.get_multi_year_average", lambda *a, **k: None)
    monkeypatch.setattr("sec_agent.agent.fact_tools.record_unmet_metric_request", lambda *a, **k: calls.append((a, k)))

    result = call_get_financial_fact(
        {"ticker": "AAPL", "metric": "operating_margin", "start_fiscal_year": 2023, "end_fiscal_year": 2025}
    )

    assert result is None
    assert calls == [(("AAPL", "operating_margin"), {"reason": "no_data_for_ticker", "question": None})]


def test_call_get_financial_fact_does_not_record_unmet_request_for_yoy_growth_ratio_rejection(monkeypatch):
    calls = []
    monkeypatch.setattr("sec_agent.agent.fact_tools.record_unmet_metric_request", lambda *a, **k: calls.append((a, k)))

    result = call_get_financial_fact({"ticker": "NVDA", "metric": "asset_turnover", "yoy_growth": True})

    assert result is None
    assert calls == []


def test_call_get_financial_fact_does_not_record_unmet_request_for_multi_year_average_yoy_growth_rejection(monkeypatch):
    calls = []
    monkeypatch.setattr("sec_agent.agent.fact_tools.record_unmet_metric_request", lambda *a, **k: calls.append((a, k)))

    result = call_get_financial_fact(
        {"ticker": "AAPL", "metric": "revenue", "start_fiscal_year": 2023, "end_fiscal_year": 2025, "yoy_growth": True}
    )

    assert result is None
    assert calls == []


def test_call_get_financial_fact_does_not_record_unmet_request_when_metric_is_missing(monkeypatch):
    # Found in code review: a missing `metric` key entirely (the model
    # not following the schema, per this function's own docstring) is a
    # boundary violation like the invented-extra-key case, not a "this
    # formula doesn't exist" signal -- metric=None must not pollute the
    # unmet-metric-request signal.
    calls = []
    monkeypatch.setattr("sec_agent.agent.fact_tools.record_unmet_metric_request", lambda *a, **k: calls.append((a, k)))

    result = call_get_financial_fact({"ticker": "AAPL"})

    assert result is None
    assert calls == []


def test_call_compare_financial_metric_does_not_record_unmet_request_when_metric_is_missing(monkeypatch):
    calls = []
    monkeypatch.setattr("sec_agent.agent.fact_tools.record_unmet_metric_request", lambda *a, **k: calls.append((a, k)))

    result = call_compare_financial_metric({"anchor_ticker": "AAPL"})

    assert result == {}
    assert calls == []


# ---------------------------------------------------------------------------
# tool_call_rejected local-only debug logging: distinct from
# record_unmet_metric_request above -- these are schema-violation
# boundary rejections (the model not following the tool's schema), a
# different debugging need than "this formula doesn't exist yet."
# ---------------------------------------------------------------------------
def test_call_get_financial_fact_logs_rejection_for_unrecognized_extra_argument(monkeypatch):
    calls = []
    capture_events(monkeypatch, calls)

    result = call_get_financial_fact({"ticker": "NVDA", "metric": "revenue", "segment": "Graphics"})

    assert result is None
    assert len(calls) == 1
    category, fields = calls[0]
    assert category == "tool_call_rejected"
    assert fields["tool"] == "get_financial_fact"
    assert fields["reason"] == "unrecognized_extra_argument"


def test_call_get_financial_fact_logs_rejection_for_unknown_ticker(monkeypatch):
    calls = []
    capture_events(monkeypatch, calls)

    result = call_get_financial_fact({"ticker": "NOT-A-REAL-TICKER", "metric": "revenue"})

    assert result is None
    assert len(calls) == 1
    category, fields = calls[0]
    assert category == "tool_call_rejected"
    assert fields["reason"] == "ticker_not_in_enum"


def test_call_get_financial_fact_logs_rejection_for_invalid_multi_year_average_combo(monkeypatch):
    calls = []
    capture_events(monkeypatch, calls)

    result = call_get_financial_fact({"ticker": "AAPL", "metric": "revenue", "start_fiscal_year": 2023})

    assert result is None
    assert len(calls) == 1
    category, fields = calls[0]
    assert category == "tool_call_rejected"
    assert fields["reason"] == "invalid_multi_year_average_combo"


def test_call_get_financial_fact_rejects_non_int_multi_year_average_years(monkeypatch):
    # A year string that isn't 4 digits stays a string, and would crash
    # formulas.py's end_fiscal_year - start_fiscal_year with a TypeError
    # if it reached the lookup, so it must be rejected here instead.
    calls = []
    capture_events(monkeypatch, calls)

    result = call_get_financial_fact(
        {"ticker": "AAPL", "metric": "revenue", "start_fiscal_year": "FY2023", "end_fiscal_year": "FY2025"}
    )

    assert result is None
    assert len(calls) == 1
    category, fields = calls[0]
    assert category == "tool_call_rejected"
    assert fields["reason"] == "invalid_multi_year_average_combo"


def test_call_get_financial_fact_rejects_non_int_fiscal_year(monkeypatch):
    # A non-year fiscal_year (e.g. "FY2025") doesn't crash -- the lookup
    # would just find no match -- but recording that as
    # reason="no_data_for_ticker" would pollute the "should we add a
    # formula for this" telemetry with a malformed call, not a data gap.
    calls = []
    capture_events(monkeypatch, calls)

    result = call_get_financial_fact({"ticker": "AAPL", "metric": "revenue", "fiscal_year": "FY2025"})

    assert result is None
    assert len(calls) == 1
    category, fields = calls[0]
    assert category == "tool_call_rejected"
    assert fields["reason"] == "invalid_fiscal_year_type"


def test_call_compare_financial_metric_rejects_non_int_fiscal_year(monkeypatch):
    # Parity with call_get_financial_fact above -- same fiscal_year
    # argument, same unvalidated read, same telemetry-pollution risk.
    calls = []
    capture_events(monkeypatch, calls)

    result = call_compare_financial_metric({"anchor_ticker": "AAPL", "metric": "revenue", "fiscal_year": "FY2025"})

    assert result == {}
    assert len(calls) == 1
    category, fields = calls[0]
    assert category == "tool_call_rejected"
    assert fields["reason"] == "invalid_fiscal_year_type"


def test_call_get_financial_fact_converts_four_digit_year_string(monkeypatch):
    # Gemini sends fiscal_year as "2025" despite the integer schema; the
    # lookup must run with the int, and the conversion is logged.
    events, lookups = [], []
    capture_events(monkeypatch, events)
    monkeypatch.setattr("sec_agent.agent.fact_tools.get_metric", lambda *a, **k: lookups.append(a) or {"value": 1})
    args = {"ticker": "AAPL", "metric": "revenue", "fiscal_year": "2025", "fiscal_period": "FY"}

    result = call_get_financial_fact(args)

    assert result == {"value": 1}
    assert lookups == [("AAPL", "revenue", 2025, "FY", None)]
    assert events == [("tool_arg_coerced", {"tool": "get_financial_fact", "field": "fiscal_year", "value": "2025"})]
    assert args["fiscal_year"] == "2025"  # the caller's dict is untouched


def test_call_compare_financial_metric_converts_four_digit_year_string(monkeypatch):
    events, lookups = [], []
    capture_events(monkeypatch, events)
    monkeypatch.setattr(
        "sec_agent.agent.fact_tools.get_metric_all_companies", lambda *a, **k: lookups.append(a) or {"AAPL": {"value": 1}}
    )

    result = call_compare_financial_metric({"anchor_ticker": "AAPL", "metric": "revenue", "fiscal_year": "2025"})

    assert result == {"AAPL": {"value": 1}}
    assert lookups == [("AAPL", "revenue", 2025, "FY", None)]
    assert [(c, f["field"]) for c, f in events] == [("tool_arg_coerced", "fiscal_year")]


def test_call_get_financial_fact_converts_multi_year_string_years(monkeypatch):
    events, lookups = [], []
    capture_events(monkeypatch, events)
    monkeypatch.setattr("sec_agent.agent.fact_tools.get_multi_year_average", lambda *a, **k: lookups.append(a) or {"value": 1})

    result = call_get_financial_fact(
        {"ticker": "AAPL", "metric": "revenue", "start_fiscal_year": "2023", "end_fiscal_year": "2025"}
    )

    assert result == {"value": 1}
    assert lookups == [("AAPL", "revenue", 2023, 2025)]
    assert [f["field"] for _, f in events] == ["end_fiscal_year", "start_fiscal_year"]


def test_call_get_financial_fact_converts_whole_float_years(monkeypatch):
    # A whole float passes the integer schema, but range() in the
    # multi-year average raises TypeError on it.
    events, lookups = [], []
    capture_events(monkeypatch, events)
    monkeypatch.setattr("sec_agent.agent.fact_tools.get_multi_year_average", lambda *a, **k: lookups.append(a) or {"value": 1})

    result = call_get_financial_fact(
        {"ticker": "AAPL", "metric": "revenue", "start_fiscal_year": 2023.0, "end_fiscal_year": 2025.0}
    )

    assert result == {"value": 1}
    assert [type(year) for year in lookups[0][2:]] == [int, int]
    assert [(f["field"], f["value"]) for _, f in events] == [("end_fiscal_year", 2025.0), ("start_fiscal_year", 2023.0)]


def test_call_get_financial_fact_still_rejects_non_year_values(monkeypatch):
    # Only four ASCII digits without a leading zero convert. "²²²²".isdigit()
    # is True, but int() can't parse it; "0000" or a short or long digit
    # string isn't a year.
    events, lookups = [], []
    capture_events(monkeypatch, events)
    monkeypatch.setattr("sec_agent.agent.fact_tools.get_metric", lambda *a, **k: lookups.append(a) or {"value": 1})

    for fiscal_year in [True, "FY2026", " 2025", "²²²²", "99999", "0", "0000", "0999", 2025.5, [2026]]:
        events.clear()
        result = call_get_financial_fact({"ticker": "AAPL", "metric": "revenue", "fiscal_year": fiscal_year})

        assert result is None, fiscal_year
        assert [f["reason"] for c, f in events if c == "tool_call_rejected"] == ["invalid_fiscal_year_type"]
        assert not [c for c, _ in events if c == "tool_arg_coerced"], fiscal_year
    assert lookups == []


def test_call_get_financial_fact_rejects_non_hashable_ticker_without_crashing(monkeypatch):
    # Found in code review (2026-09-06): `ticker not in COMPANIES` raises
    # TypeError for an unhashable value (e.g. a list) instead of the
    # graceful rejection every other malformed-argument case gets.
    calls = []
    capture_events(monkeypatch, calls)

    result = call_get_financial_fact({"ticker": ["AAPL"], "metric": "revenue"})

    assert result is None
    assert len(calls) == 1
    category, fields = calls[0]
    assert category == "tool_call_rejected"
    assert fields["reason"] == "ticker_wrong_type"


def test_call_get_financial_fact_rejects_non_hashable_metric_without_crashing(monkeypatch):
    calls = []
    capture_events(monkeypatch, calls)

    result = call_get_financial_fact({"ticker": "AAPL", "metric": ["revenue"]})

    assert result is None
    assert len(calls) == 1
    category, fields = calls[0]
    assert category == "tool_call_rejected"
    assert fields["reason"] == "metric_wrong_type"


def test_call_get_financial_fact_logs_rejection_for_yoy_growth_unsupported_for_ratio(monkeypatch):
    calls = []
    capture_events(monkeypatch, calls)

    result = call_get_financial_fact({"ticker": "NVDA", "metric": "asset_turnover", "yoy_growth": True})

    assert result is None
    assert len(calls) == 1
    category, fields = calls[0]
    assert category == "tool_call_rejected"
    assert fields["reason"] == "yoy_growth_unsupported_for_ratio"


def test_call_get_financial_fact_logs_rejection_for_missing_metric(monkeypatch):
    calls = []
    capture_events(monkeypatch, calls)

    result = call_get_financial_fact({"ticker": "AAPL"})

    assert result is None
    assert len(calls) == 1
    category, fields = calls[0]
    assert category == "tool_call_rejected"
    assert fields["reason"] == "missing_required_argument"


def test_call_compare_financial_metric_logs_rejection_for_missing_metric(monkeypatch):
    calls = []
    capture_events(monkeypatch, calls)

    result = call_compare_financial_metric({"anchor_ticker": "AAPL"})

    assert result == {}
    assert len(calls) == 1
    category, fields = calls[0]
    assert category == "tool_call_rejected"
    assert fields["reason"] == "missing_required_argument"


def test_call_get_financial_fact_does_not_log_rejection_on_success(monkeypatch):
    calls = []
    monkeypatch.setattr("sec_agent.agent.fact_tools.get_metric", lambda *a, **k: {"value": 42})
    capture_events(monkeypatch, calls)

    result = call_get_financial_fact({"ticker": "AAPL", "metric": "revenue"})

    assert result == {"value": 42}
    assert calls == []


def test_call_compare_financial_metric_logs_rejection_for_unrecognized_extra_argument(monkeypatch):
    calls = []
    capture_events(monkeypatch, calls)

    result = call_compare_financial_metric({"anchor_ticker": "NVDA", "metric": "revenue", "segment": "Graphics"})

    assert result == {}
    assert len(calls) == 1
    category, fields = calls[0]
    assert category == "tool_call_rejected"
    assert fields["tool"] == "compare_financial_metric"
    assert fields["reason"] == "unrecognized_extra_argument"


def test_call_compare_financial_metric_logs_rejection_for_unknown_ticker(monkeypatch):
    calls = []
    capture_events(monkeypatch, calls)

    result = call_compare_financial_metric({"anchor_ticker": "NOT-A-REAL-TICKER", "metric": "revenue"})

    assert result == {}
    assert len(calls) == 1
    category, fields = calls[0]
    assert category == "tool_call_rejected"
    assert fields["reason"] == "anchor_ticker_not_in_enum"


def test_call_compare_financial_metric_rejects_non_hashable_ticker_without_crashing(monkeypatch):
    # Mirrors call_get_financial_fact's matching test — found in the same
    # code-review pass (2026-09-06).
    calls = []
    capture_events(monkeypatch, calls)

    result = call_compare_financial_metric({"anchor_ticker": ["AAPL"], "metric": "revenue"})

    assert result == {}
    assert len(calls) == 1
    category, fields = calls[0]
    assert category == "tool_call_rejected"
    assert fields["reason"] == "anchor_ticker_wrong_type"


def test_call_compare_financial_metric_rejects_non_hashable_metric_without_crashing(monkeypatch):
    calls = []
    capture_events(monkeypatch, calls)

    result = call_compare_financial_metric({"anchor_ticker": "AAPL", "metric": ["revenue"]})

    assert result == {}
    assert len(calls) == 1
    category, fields = calls[0]
    assert category == "tool_call_rejected"
    assert fields["reason"] == "metric_wrong_type"


def test_call_compare_financial_metric_does_not_log_rejection_on_success(monkeypatch):
    calls = []
    monkeypatch.setattr("sec_agent.agent.fact_tools.get_metric_all_companies", lambda *a, **k: {"AAPL": {"value": 1}})
    capture_events(monkeypatch, calls)

    result = call_compare_financial_metric({"anchor_ticker": "AAPL", "metric": "revenue"})

    assert result == {"AAPL": {"value": 1}}
    assert calls == []


def test_call_compare_financial_metric_records_unmet_request_for_unknown_metric(monkeypatch):
    calls = []
    monkeypatch.setattr("sec_agent.agent.fact_tools.record_unmet_metric_request", lambda *a, **k: calls.append((a, k)))

    result = call_compare_financial_metric({"anchor_ticker": "AAPL", "metric": "effective_tax_rate"})

    assert result == {}
    assert calls == [(("AAPL", "effective_tax_rate"), {"reason": "unknown_metric", "question": None})]


def test_call_compare_financial_metric_records_unmet_request_with_no_data_for_ticker(monkeypatch):
    calls = []
    monkeypatch.setattr("sec_agent.agent.fact_tools.get_metric_all_companies", lambda *a, **k: {})
    monkeypatch.setattr("sec_agent.agent.fact_tools.record_unmet_metric_request", lambda *a, **k: calls.append((a, k)))

    result = call_compare_financial_metric({"anchor_ticker": "AAPL", "metric": "revenue"})

    assert result == {}
    assert calls == [(("AAPL", "revenue"), {"reason": "no_data_for_ticker", "question": None})]


def test_call_compare_financial_metric_does_not_record_unmet_request_on_success(monkeypatch):
    calls = []
    monkeypatch.setattr("sec_agent.agent.fact_tools.get_metric_all_companies", lambda *a, **k: {"AAPL": {"value": 1}})
    monkeypatch.setattr("sec_agent.agent.fact_tools.record_unmet_metric_request", lambda *a, **k: calls.append((a, k)))

    result = call_compare_financial_metric({"anchor_ticker": "AAPL", "metric": "revenue"})

    assert result == {"AAPL": {"value": 1}}
    assert calls == []


def test_call_compare_financial_metric_records_unmet_request_when_anchor_missing_from_partial_result(monkeypatch):
    # Found in code review (2026-09-07): instant metrics (total_assets
    # etc.) resolve each company independently with no requirement that
    # the requested anchor itself has data -- e.g. PLTR doesn't tag
    # inventory but AAPL/MSFT do. Without this, `if not result:` never
    # fires for a non-empty-but-anchor-missing result, so the caller
    # asked about PLTR specifically and gets a silently PLTR-less
    # comparison with zero signal anywhere that PLTR's own data is
    # missing.
    calls = []
    monkeypatch.setattr("sec_agent.agent.fact_tools.get_metric_all_companies", lambda *a, **k: {"AAPL": {"value": 1}, "MSFT": {"value": 2}})
    monkeypatch.setattr("sec_agent.agent.fact_tools.record_unmet_metric_request", lambda *a, **k: calls.append((a, k)))

    result = call_compare_financial_metric({"anchor_ticker": "PLTR", "metric": "inventory"})

    # Other companies' data is still returned -- genuinely useful partial
    # info -- but the anchor-specific gap is now signaled too.
    assert result == {"AAPL": {"value": 1}, "MSFT": {"value": 2}}
    assert calls == [(("PLTR", "inventory"), {"reason": "no_data_for_ticker", "question": None})]


def test_call_compare_financial_metric_rejects_unrecognized_extra_argument(monkeypatch):
    calls = []
    monkeypatch.setattr("sec_agent.agent.fact_tools.get_metric_all_companies", lambda *a, **k: calls.append((a, k)) or {"NVDA": {}})
    result = call_compare_financial_metric({"anchor_ticker": "NVDA", "metric": "revenue", "segment": "Graphics"})
    assert result == {}
    assert calls == []


def test_call_compare_financial_metric_gracefully_rejects_single_company_only_ratio():
    # return_on_assets/asset_turnover/cash_to_assets/inventory_turnover/
    # rd_intensity all have supports_cross_company=False in
    # RATIO_DEFINITIONS -- "asset_turnover" IS a recognized ratio name so
    # it passes compare_financial_metric's own boundary check (unlike
    # the old design, where it wasn't in RATIO_METRIC_FUNCTIONS at all
    # and was rejected right there), but get_ratio_all_companies() checks
    # the flag internally and returns the same graceful {} any other
    # unsupported metric gets, rather than a crash. This is deliberate
    # scoping (see formulas.get_return_on_assets's docstring for why
    # there's no cross-company version yet), not an oversight -- this
    # test locks in that it stays graceful regardless of which layer
    # does the rejecting.
    result = call_compare_financial_metric({"anchor_ticker": "AAPL", "metric": "asset_turnover"})
    assert result == {}


def test_call_compare_financial_metric_dispatches_operating_margin(monkeypatch):
    # get_ratio_all_companies() is the single generic dispatch point for
    # every cross-company-capable RATIO_DEFINITIONS entry now -- see
    # test_call_get_financial_fact_dispatches_operating_margin above for
    # why agent.get_ratio_all_companies is the correct monkeypatch seam.
    calls = []
    monkeypatch.setattr(
        "sec_agent.agent.fact_tools.get_ratio_all_companies",
        lambda ticker, ratio_name, fiscal_year, fiscal_period, period_end_date: calls.append(ratio_name)
        or {"NVDA": {"value": 60.0}},
    )
    result = call_compare_financial_metric({"anchor_ticker": "NVDA", "metric": "operating_margin"})
    assert result == {"NVDA": {"value": 60.0}}
    assert calls == ["operating_margin"]


def test_call_compare_financial_metric_dispatches_net_margin(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "sec_agent.agent.fact_tools.get_ratio_all_companies",
        lambda ticker, ratio_name, fiscal_year, fiscal_period, period_end_date: calls.append(ratio_name)
        or {"NVDA": {"value": 45.0}},
    )
    result = call_compare_financial_metric({"anchor_ticker": "NVDA", "metric": "net_margin"})
    assert result == {"NVDA": {"value": 45.0}}
    assert calls == ["net_margin"]


def test_call_get_financial_fact_tolerates_null_fiscal_period(monkeypatch):
    # Regression case for validate_tool_args's null-optional-property fix,
    # exercised through the real call site rather than validate_tool_args
    # directly.
    monkeypatch.setattr("sec_agent.agent.fact_tools.get_metric", lambda *a, **k: {"value": 42})
    result = call_get_financial_fact({"ticker": "AAPL", "metric": "revenue", "fiscal_period": None})
    assert result == {"value": 42}
