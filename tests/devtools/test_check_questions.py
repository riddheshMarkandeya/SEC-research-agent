"""Unit tests for devtools/check_questions.py, the v2 authoring check.
Every check runs over in-memory questions, gold rows and chunks; the
XBRL fetch is a stub."""

import json

import pytest

from sec_agent.devtools import check_questions as cq


def _gold(qid="q1", part="value", accession="A1", anchor="Total net revenue | 182,447", **extra):
    return {"qid": qid, "part": part, "accession": accession, "report_date": "2025-12-31",
            "anchor": anchor, "own_period": True, "note": "", **extra}


def _chunk(accession, index, text, ticker="JPM"):
    return {"text": text, "metadata": {"accessionNumber": accession, "chunk_index": index, "ticker": ticker,
                                       "form": "10-K", "reportDate": "2025-12-31"}}


JPM_REVENUE = _chunk("A1", 3, "Income statement\nTotal net revenue | 182,447 | 177,556\nNet income | 57,048")
JPM_PRIOR = _chunk("A0", 3, "Total net revenue | 177,556 | 158,104")
BAC_REVENUE = _chunk("B1", 7, "Total revenue, net of interest expense | 101,887", ticker="BAC")


def _ctx(gold=(), chunks=(JPM_REVENUE, JPM_PRIOR, BAC_REVENUE), facts=None, other_ids=frozenset()):
    def fetch(ticker):
        if isinstance(facts, Exception):
            raise facts
        return (facts or {}).get(ticker, {"facts": {}})

    return cq.Context(chunks=list(chunks), gold=list(gold), fetch_facts=fetch, other_ids=other_ids)


def _numeric(**extra) -> dict:
    return {"id": "q1", "ticker": "JPM", "question": "What was JPMorgan's total net revenue for 2025?",
            "type": "numeric", "expected_value": 182447, "expected_unit": "million", **extra}


def _messages(findings, level=None):
    return [f.message for f in findings if level is None or f.level == level]


def _errors(question, ctx):
    return _messages(cq.check_question(question, ctx), cq.ERROR)


# ---------------------------------------------------------------------------
# 1. Anchors
# ---------------------------------------------------------------------------
def test_an_anchored_numeric_question_passes():
    assert _errors(_numeric(), _ctx([_gold()])) == []


def test_a_gold_part_without_rows_is_an_error():
    assert _errors(_numeric(), _ctx()) == ["part 'value': no gold rows"]


def test_a_row_whose_anchor_is_in_no_chunk_is_an_error():
    errors = _errors(_numeric(), _ctx([_gold(), _gold(anchor="Total net revenue | 182,448")]))
    assert errors == ["gold row 'value' (A1): anchor 'Total net revenue | 182,448' is in no chunk of its filing"]


def test_an_anchor_that_doesnt_show_the_figure_is_an_error():
    errors = _errors(_numeric(), _ctx([_gold(anchor="Net income | 57,048")]))
    assert errors == ["part 'value': no anchor shows 182447 million"]


def test_an_anchor_in_another_companys_filing_is_an_error():
    question = _numeric(expected_value=101887)
    errors = _errors(question, _ctx([_gold(accession="B1", anchor="interest expense | 101,887")]))
    assert errors == ["gold row 'value' (B1): its chunk is BAC's, not JPM's"]


def test_a_row_for_a_part_the_question_lacks_is_an_error():
    errors = _errors(_numeric(), _ctx([_gold(), _gold(part="vaule")]))
    assert errors == ["gold row part 'vaule' is not one of this question's parts (value)"]


def _growth_question(**extra):
    return _numeric(**{
        "expected_value": 2.8, "expected_unit": "percent",
        "derivation": {"operation": "percent_change",
                       "a": {"value": 182447, "unit": "million", "part": "revenue-2025"},
                       "b": {"value": 177556, "unit": "million", "part": "revenue-2024"}},
        **extra,
    })


GROWTH_GOLD = [_gold(part="revenue-2025"), _gold(part="revenue-2024", accession="A0", anchor="revenue | 177,556")]


def test_a_derived_value_needs_anchors_for_its_inputs_only():
    assert _errors(_growth_question(), _ctx(GROWTH_GOLD)) == []
    assert _errors(_growth_question(), _ctx(GROWTH_GOLD[:1])) == ["part 'revenue-2024': no gold rows"]
    assert _errors(_growth_question(), _ctx([*GROWTH_GOLD, _gold()])) == [
        "gold row part 'value' is not one of this question's parts (revenue-2024, revenue-2025)"
    ]


def _comparison(expected, **extra):
    return {"id": "q1", "tickers": ["JPM", "BAC"], "question": "q", "type": "comparison", "expected": expected,
            **extra}


def test_each_comparison_entry_is_anchored_in_its_own_companys_filing():
    question = _comparison([
        {"ticker": "JPM", "expected_value": 182447, "expected_unit": "million"},
        {"ticker": "BAC", "expected_value": 101887, "expected_unit": "million"},
    ])
    bac_row = _gold(part="BAC", accession="B1", anchor="interest expense | 101,887")
    assert _errors(question, _ctx([_gold(part="JPM"), bac_row])) == []
    swapped = _gold(part="JPM", accession="B1", anchor="interest expense | 101,887")
    assert "gold row 'JPM' (B1): its chunk is BAC's, not JPM's" in _errors(question, _ctx([swapped, bac_row]))


def test_a_text_answer_is_matched_against_its_accepted_variants():
    question = {"id": "q1", "ticker": "JPM", "question": "Who audits JPMorgan?", "type": "text",
                "accepted": ["PricewaterhouseCoopers LLP"]}
    chunk = _chunk("A1", 9, "/s/ PricewaterhouseCoopers LLP, New York")
    assert _errors(question, _ctx([_gold(anchor="PricewaterhouseCoopers LLP, New")], [chunk])) == []
    assert _errors(question, _ctx([_gold(anchor="/s/")], [chunk])) == [
        "part 'value': no anchor shows PricewaterhouseCoopers LLP"
    ]


def test_judged_rows_get_the_chunk_match_check_only():
    question = {"id": "q1", "ticker": "JPM", "question": "q", "type": "judged", "criteria": "c"}
    assert _errors(question, _ctx([_gold(part="JPM-numerator")])) == []
    assert _errors(question, _ctx([_gold(part="JPM-numerator", anchor="missing")])) == [
        "gold row 'JPM-numerator' (A1): anchor 'missing' is in no chunk of its filing"
    ]


# ---------------------------------------------------------------------------
# 2. Derivations
# ---------------------------------------------------------------------------
def _derivation_findings(question, level=None):
    return _messages(cq.check_derivations(question, _ctx()), level)


def test_a_derivation_that_recomputes_to_the_expected_value_passes_and_reports_its_spread():
    assert _derivation_findings(_growth_question(), cq.ERROR) == []
    assert _derivation_findings(_growth_question(), cq.WARN) == []
    [info] = _derivation_findings(_growth_question(), cq.INFO)
    assert info.startswith("derivation: rounding spread +/-0.000") and "default band +/-0.05" in info


def test_a_derivation_that_recomputes_to_another_value_is_an_error():
    assert _derivation_findings(_growth_question(expected_value=3.1), cq.ERROR) == [
        "derivation: recomputes to 2.8 percent, outside the grading band of the expected 3.1 percent"
    ]


def _average_revenue():
    # The average of two years' revenue: (182,447 + 177,556) / 2 = 180,001.5 million.
    return {
        "operation": "divide",
        "a": {"derivation": {"operation": "add",
                             "a": {"value": 182447, "unit": "million", "part": "revenue-2025"},
                             "b": {"value": 177556, "unit": "million", "part": "revenue-2024"}}},
        "b": {"value": 2, "unit": "raw", "constant": True},
    }


def test_a_compound_derivation_with_a_constant_recomputes():
    question = _numeric(expected_value=180.0, expected_unit="billion", derivation=_average_revenue())
    assert _derivation_findings(question, cq.ERROR) == []


def test_operands_of_mismatched_categories_are_an_error_as_in_the_tool():
    question = _growth_question()
    question["derivation"]["b"] = {"value": 4.2, "unit": "percent", "part": "margin"}
    assert _derivation_findings(question, cq.ERROR) == [
        "derivation: percent_change mixes a scale and a percent operand, which calculate refuses"
    ]


def test_a_zero_divisor_is_an_error_as_in_the_tool():
    question = _growth_question()
    question["derivation"]["b"]["value"] = 0
    assert _derivation_findings(question, cq.ERROR) == ["derivation: percent_change by zero, which calculate refuses"]


def _rounded_growth(**extra):
    # Billions to one decimal: each input is only known to +/-0.05 billion,
    # which moves the growth rate by about +/-0.057 points, past the 0.05 floor.
    return _numeric(
        expected_value=2.7, expected_unit="percent",
        derivation={"operation": "percent_change",
                    "a": {"value": 182.4, "unit": "billion", "part": "revenue-2025"},
                    "b": {"value": 177.6, "unit": "billion", "part": "revenue-2024"}},
        **extra,
    )


def test_a_spread_wider_than_the_default_band_needs_a_tolerance():
    [error] = _derivation_findings(_rounded_growth(), cq.ERROR)
    assert error.startswith("derivation: needs a tolerance (spread +/-0.057")
    # The exact 2.7027 sits off expected, so the far corner reaches past the spread.
    assert error.endswith(", reaching 0.0598 from expected)")


def test_a_spread_wider_than_the_set_tolerance_is_an_error():
    question = _rounded_growth(tolerance=0.015, tolerance_note="n")
    [error] = _derivation_findings(question, cq.ERROR)
    assert error.startswith("derivation: spread +/-0.057") and "exceeds the tolerance 0.015" in error
    assert _derivation_findings(_rounded_growth(tolerance=0.03, tolerance_note="n"), cq.ERROR) == []
    assert _derivation_findings(_rounded_growth(tolerance=0.03, tolerance_note="n"), cq.WARN) == []


def test_a_tolerance_the_spread_doesnt_need_is_a_warning():
    assert _derivation_findings(_growth_question(tolerance=0.02, tolerance_note="n"), cq.WARN) == [
        "tolerance 0.02 is unneeded: the default band covers every derivation's exact result and spread"
    ]


def test_a_comparison_entrys_derivation_is_checked_and_named():
    entry = {"ticker": "JPM-growth", "companies": ["JPM"], "expected_value": 3.1, "expected_unit": "percent",
             "derivation": _growth_question()["derivation"]}
    question = _comparison([entry, {"ticker": "BAC", "expected_value": 101887, "expected_unit": "million"}])
    assert _derivation_findings(question, cq.ERROR) == [
        "expected 'JPM-growth' derivation: recomputes to 2.8 percent, outside the grading band of the expected "
        "3.1 percent"
    ]


def _growth_gap(a, b, expected, **extra):
    # The points by which growth a/1,000,000 outpaced b/1,000,000: the tool
    # rounds each growth rate to 1 decimal before subtracting.
    return _numeric(expected_value=expected, expected_unit="percent", derivation={
        "operation": "subtract",
        "a": {"derivation": {"operation": "percent_change", "a": {"value": a, "unit": "raw", "part": "a"},
                             "b": {"value": 1000000, "unit": "raw", "part": "base-a"}}},
        "b": {"derivation": {"operation": "percent_change", "a": {"value": b, "unit": "raw", "part": "b"},
                             "b": {"value": 1000000, "unit": "raw", "part": "base-b"}}},
    }, **extra)


# Tool: 4.2 - 2.8 = 1.4, as expected. Exact: 4.1502 - 2.849 = 1.3012.
EXACT_OUT = (1041502, 1028490, 1.4)
# Tool: 20.0 - 2.9 = 17.1, inside 17.0's band of +/-0.17. Exact: 20.04 - 2.88
# = 17.16, also inside, but an agent reports it as 17.2, which is outside.
ROUNDED_EXACT_OUT = (1200400, 1028800, 17.0)


@pytest.mark.parametrize(("case", "exact", "rounds_to"), [(EXACT_OUT, "1.3012", "1.3"),
                                                          (ROUNDED_EXACT_OUT, "17.1600", "17.2")])
def test_an_exact_result_outside_the_band_is_an_error_though_the_tool_lands_inside(case, exact, rounds_to):
    a, b, expected = case
    assert _derivation_findings(_growth_gap(a, b, expected), cq.ERROR) == [
        f"derivation: exact result {exact} percent (rounds to {rounds_to}) is outside the band of expected "
        f"{expected:g} percent: check expected_value, or set a tolerance"
    ]


@pytest.mark.parametrize(("case", "tolerance"), [(EXACT_OUT, 0.075), (ROUNDED_EXACT_OUT, 0.012)])
def test_a_tolerance_wide_enough_for_the_exact_result_is_needed_and_passes(case, tolerance):
    question = _growth_gap(*case, tolerance=tolerance, tolerance_note="n")
    assert _derivation_findings(question, cq.ERROR) == []
    assert _derivation_findings(question, cq.WARN) == []


def test_the_info_line_reports_the_exact_result():
    [info] = _derivation_findings(_growth_question(), cq.INFO)
    assert "exact result 2.7546 percent" in info


def test_a_wrong_expected_value_is_one_error_not_an_offset_error_too():
    a, b, _ = EXACT_OUT
    [error] = _derivation_findings(_growth_gap(a, b, 2.0), cq.ERROR)
    assert error.startswith("derivation: recomputes to 1.4 percent")


def test_an_offset_inside_a_comparison_entrys_derivation_is_named():
    gap = _growth_gap(*EXACT_OUT)
    entry = {"ticker": "JPM-gap", "companies": ["JPM"], "expected_value": 1.4, "expected_unit": "percent",
             "derivation": gap["derivation"]}
    question = _comparison([entry, {"ticker": "BAC", "expected_value": 101887, "expected_unit": "million"}])
    [error] = _derivation_findings(question, cq.ERROR)
    assert error.startswith("expected 'JPM-gap' derivation: exact result 1.3012 percent")


def test_an_offset_past_a_set_tolerance_says_to_widen_it():
    [error] = _derivation_findings(_growth_gap(*EXACT_OUT, tolerance=0.02, tolerance_note="n"), cq.ERROR)
    assert error.endswith("check expected_value, or widen the tolerance")


def test_the_reported_rounding_is_half_up_on_the_decimal_digits():
    # As floats, 2.675 is just below and round() gives 2.67; a person reports 2.68.
    assert cq._round_half_up(2.675, 2) == 2.68
    assert cq._round_half_up(17.16, 1) == 17.2


def test_no_unneeded_tolerance_warning_when_the_tool_misses_a_tight_tolerance():
    # The tool's 180.0 billion misses 179.0's 0.1% band but fits the default 1% one.
    question = _numeric(expected_value=179.0, expected_unit="billion", tolerance=0.001, tolerance_note="n",
                        derivation=_average_revenue())
    [error] = _derivation_findings(question, cq.ERROR)
    assert error.startswith("derivation: recomputes to 180.001 billion")
    assert _derivation_findings(question, cq.WARN) == []


# ---------------------------------------------------------------------------
# 3. XBRL cross-check
# ---------------------------------------------------------------------------
def _fact(val, accn="A1", **extra):
    return {"start": "2025-01-01", "end": "2025-12-31", "val": val, "accn": accn, "form": "10-K", **extra}


def _facts(*entries, tag="Revenues"):
    return {"JPM": {"facts": {"us-gaap": {tag: {"units": {"USD": list(entries)}}}}}}


def test_an_anchored_figure_matching_a_fact_of_its_filing_names_the_tag():
    ctx = _ctx([_gold()], facts=_facts(_fact(182447000000), _fact(182447000000, accn="A9"), _fact(57048000000)))
    assert _messages(cq.check_xbrl(_numeric(), ctx)) == [
        "part 'value': XBRL us-gaap:Revenues = 182447000000 USD (2025-01-01..2025-12-31, 10-K)"
    ]


def test_a_fact_matches_within_the_figures_printed_precision():
    ctx = _ctx([_gold()], facts=_facts(_fact(182447400000), _fact(182447600000)))
    assert _messages(cq.check_xbrl(_numeric(), ctx)) == [
        "part 'value': XBRL us-gaap:Revenues = 182447400000 USD (2025-01-01..2025-12-31, 10-K)"
    ]


def test_no_matching_fact_is_reported_as_info():
    findings = cq.check_xbrl(_numeric(), _ctx([_gold()], facts=_facts(_fact(1))))
    assert [(f.level, f.message) for f in findings] == [
        (cq.INFO, "part 'value': no XBRL fact matched (text-only or untagged)")
    ]


def test_a_percentage_is_not_cross_checked():
    question = _numeric(expected_value=31.3, expected_unit="percent")
    assert cq.check_xbrl(question, _ctx([_gold(anchor="31.3%")], facts=_facts(_fact(31.3)))) == []


def test_a_fetch_failure_is_a_warning_naming_the_ticker():
    findings = cq.check_xbrl(_growth_question(), _ctx(GROWTH_GOLD, facts=OSError("disk full")))
    assert [(f.level, f.message) for f in findings] == [(cq.WARN, "XBRL cross-check skipped for JPM: disk full")]


def test_many_matching_facts_are_capped():
    facts = {"JPM": {"facts": {"us-gaap": {f"Tag{i}": {"units": {"USD": [_fact(182447000000)]}} for i in range(7)}}}}
    [info] = _messages(cq.check_xbrl(_numeric(), _ctx([_gold()], facts=facts)))
    assert info.count("us-gaap:Tag") == 5 and info.endswith("(+2 more)")


# ---------------------------------------------------------------------------
# 9. XBRL-only figures
# ---------------------------------------------------------------------------
XBRL_SOURCE = {"tag": "us-gaap:OperatingIncomeLoss", "accession": "A20", "start": "2020-01-01", "end": "2020-12-31"}


def _xbrl_only(**extra):
    return _numeric(**{"expected_value": 4553, "xbrl_source": XBRL_SOURCE, **extra})


def _fact_2020(val=4553000000, **extra):
    return {"start": "2020-01-01", "end": "2020-12-31", "val": val, "accn": "A20", "form": "10-K", **extra}


def _xbrl_findings(question, facts, chunks=(JPM_REVENUE,), gold=()):
    ctx = _ctx(list(gold), chunks=chunks, facts=facts)
    return [(f.level, f.message) for f in cq.check_question(question, ctx) if f.level != cq.INFO or "xbrl_source" in f.message]


def test_an_xbrl_only_figure_matching_its_fact_is_info():
    facts = _facts(_fact_2020(), _fact_2020(accn="A21"), tag="OperatingIncomeLoss")
    assert _xbrl_findings(_xbrl_only(), facts) == [
        (cq.INFO, "xbrl_source: us-gaap:OperatingIncomeLoss = 4553000000 USD (2020-01-01..2020-12-31, 10-K)")
    ]


def test_an_xbrl_only_figure_matches_within_its_printed_precision():
    facts = _facts(_fact_2020(4553400000), tag="OperatingIncomeLoss")
    assert [level for level, _ in _xbrl_findings(_xbrl_only(), facts)] == [cq.INFO]


def test_an_xbrl_only_figure_the_fact_disagrees_with_is_an_error():
    facts = _facts(_fact_2020(4600000000), tag="OperatingIncomeLoss")
    assert _xbrl_findings(_xbrl_only(), facts) == [
        (cq.ERROR, "xbrl_source: us-gaap:OperatingIncomeLoss in A20 (2020-01-01..2020-12-31) is 4600000000 USD, "
                   "not 4553 million")
    ]


@pytest.mark.parametrize("fact, tag", [
    (_fact_2020(accn="A21"), "OperatingIncomeLoss"),
    (_fact_2020(), "Revenues"),
    (_fact_2020(start="2020-10-01"), "OperatingIncomeLoss"),
])
def test_no_fact_for_the_sources_tag_filing_and_period_is_an_error(fact, tag):
    assert _xbrl_findings(_xbrl_only(), _facts(fact, tag=tag)) == [
        (cq.ERROR, "xbrl_source: no us-gaap:OperatingIncomeLoss fact in A20 for 2020-01-01..2020-12-31")
    ]


def test_an_instant_source_does_not_match_a_duration_fact_of_the_same_end():
    source = {k: v for k, v in XBRL_SOURCE.items() if k != "start"}
    facts = _facts(_fact_2020(), tag="OperatingIncomeLoss")
    assert _xbrl_findings(_xbrl_only(xbrl_source=source), facts) == [
        (cq.ERROR, "xbrl_source: no us-gaap:OperatingIncomeLoss fact in A20 for 2020-12-31")
    ]


def test_later_filings_disagreeing_on_the_sources_fact_are_a_warning():
    # The fact tool may answer from a later filing's comparative column. A
    # second, disagreeing fact in the source filing itself isn't another filing's.
    facts = _facts(_fact_2020(), _fact_2020(accn="A21"), _fact_2020(4600000000, accn="A22"),
                   _fact_2020(4553000, accn="A20"),
                   _fact_2020(1, accn="A22", start="2020-10-01"), tag="OperatingIncomeLoss")
    assert _xbrl_findings(_xbrl_only(), facts)[1:] == [
        (cq.WARN, "xbrl_source: another filing reports us-gaap:OperatingIncomeLoss for 2020-01-01..2020-12-31 "
                  "as 4600000000 USD (A22), which the fact tool may return instead")
    ]


def test_unreadable_facts_leave_an_xbrl_only_figure_unverified_which_is_an_error():
    assert _xbrl_findings(_xbrl_only(), OSError("disk full")) == [
        (cq.ERROR, "xbrl_source: JPM's XBRL facts couldn't be read, so the figure is unverified: disk full")
    ]


def test_an_xbrl_only_figure_needs_a_single_company():
    question = {k: v for k, v in _xbrl_only(tickers=["JPM", "BAC"]).items() if k != "ticker"}
    assert _xbrl_findings(question, {}) == [
        (cq.ERROR, "xbrl_source: the question names several companies, so whose facts to read is unclear")
    ]


def test_a_gold_row_on_an_xbrl_only_question_is_an_error():
    facts = _facts(_fact_2020(), tag="OperatingIncomeLoss")
    gold = [_gold(anchor="Net income | 57,048")]
    assert [m for level, m in _xbrl_findings(_xbrl_only(), facts, gold=gold) if level == cq.ERROR] == [
        "gold row 'value' (A1): an XBRL-only figure takes no gold rows"
    ]


def test_an_xbrl_only_figure_printed_in_its_companys_chunks_is_a_warning():
    printed = _chunk("A7", 2, "Operating profit | 4,553 | 6,647")
    elsewhere = _chunk("B7", 2, "Operating profit | 4,553", ticker="BAC")
    facts = _facts(_fact_2020(), tag="OperatingIncomeLoss")
    assert _xbrl_findings(_xbrl_only(), facts, chunks=(JPM_REVENUE, elsewhere))[1:] == []
    assert _xbrl_findings(_xbrl_only(), facts, chunks=(JPM_REVENUE, printed))[1:] == [
        (cq.WARN, "xbrl_source: the figure is printed in A7#2; if that's this line item and period, it isn't "
                  "XBRL-only, so give it a gold row instead")
    ]


# ---------------------------------------------------------------------------
# 4. Absence
# ---------------------------------------------------------------------------
def _never_disclosed(terms, ticker="JPM"):
    return {"id": "q1", "ticker": ticker, "question": "q", "type": "refusal", "refusal_kind": "never_disclosed",
            "absence_terms": terms}


def test_absence_terms_found_nowhere_are_recorded_as_info():
    findings = cq.check_absence(_never_disclosed(["branch count"]), _ctx())
    assert [(f.level, f.message) for f in findings] == [
        (cq.INFO, "absence term 'branch count': in none of 2 JPM chunks (2 filings); 0 hits in other companies' chunks")
    ]


def test_an_absence_term_in_the_companys_own_chunks_is_an_error():
    findings = cq.check_absence(_never_disclosed(["TOTAL  NET\nrevenue"]), _ctx())
    errors = _messages(findings, cq.ERROR)
    assert errors == [
        "absence term 'TOTAL  NET\\nrevenue': found in 2 JPM chunks, e.g. A1#3: "
        "'income statement total net revenue 182 447 177 556 net income 57 048'"
    ]


def test_hits_in_other_companies_chunks_are_counted_not_errors():
    findings = cq.check_absence(_never_disclosed(["interest expense"]), _ctx())
    assert _messages(findings, cq.ERROR) == []
    assert _messages(findings, cq.INFO)[0].endswith("1 hits in other companies' chunks")


def test_absence_with_no_chunks_of_the_company_is_an_error():
    assert _messages(cq.check_absence(_never_disclosed(["x"], ticker="WMT"), _ctx()), cq.ERROR) == [
        "absence: no chunks for WMT, so nothing was searched"
    ]


# ---------------------------------------------------------------------------
# 5-8. Tickers, entry companies, traps beside the answer, id collisions
# ---------------------------------------------------------------------------
def test_a_graded_question_about_an_uncovered_company_is_an_error():
    assert cq.check_tickers(_numeric(ticker="ACME"), _ctx()) == [
        cq.Finding(cq.ERROR, "ticker ACME is not in companies.json, so no filing can ground its answer")
    ]
    refusal = {"id": "q1", "ticker": "ACME", "question": "q", "type": "refusal", "refusal_kind": "not_covered"}
    assert cq.check_tickers(refusal, _ctx()) == []
    trapped = {**refusal, "forbidden_values": [{"value": 1.0, "unit": "billion"}]}
    assert len(cq.check_tickers(trapped, _ctx())) == 1


def test_a_multi_company_entry_without_a_ticker_label_must_list_its_companies():
    gap = {"ticker": "revenue-gap", "expected_value": 80.6, "expected_unit": "billion"}
    question = _comparison([{"ticker": "JPM", "expected_value": 182447, "expected_unit": "million"}, gap])
    assert cq.check_entry_companies(question, _ctx()) == [
        cq.Finding(cq.ERROR, "expected 'revenue-gap': its label isn't a ticker and it lists no companies, "
                             "so a claim of it must cite all of BAC, JPM")
    ]
    gap["companies"] = ["JPM", "BAC"]
    assert cq.check_entry_companies(question, _ctx()) == []
    single = {**question, "tickers": ["JPM"], "expected": [{**gap, "companies": ["JPM"]}]}
    del single["expected"][0]["companies"]
    assert cq.check_entry_companies(single, _ctx()) == []


def test_a_trap_printed_beside_the_answer_is_a_warning():
    question = _numeric(forbidden_values=[{"value": 177556, "unit": "million"}, {"value": 99, "unit": "billion"}])
    assert cq.check_traps_beside_answer(question, _ctx([_gold()])) == [
        cq.Finding(cq.WARN, "trap 177556 million is printed in gold chunk A1#3: a correct answer may state it "
                            "for context and fail")
    ]


def test_an_id_used_in_the_other_question_file_is_an_error():
    assert cq.check_id_collision(_numeric(), _ctx(other_ids=frozenset({"q1"}))) == [
        cq.Finding(cq.ERROR, "id 'q1' is already used in the v1 question file, and gold rows and reports are keyed by id")
    ]
    assert cq.check_id_collision(_numeric(), _ctx()) == []


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _write_jsonl(path, records):
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return path


@pytest.fixture
def files(tmp_path):
    chunks_dir = tmp_path / "chunks"
    (chunks_dir / "JPM").mkdir(parents=True)
    _write_jsonl(chunks_dir / "JPM" / "A1_chunks.jsonl", [JPM_REVENUE, JPM_PRIOR])
    gold = _write_jsonl(tmp_path / "gold.jsonl", [_gold(qid="v2-revenue"), _gold(qid="v2-bad", anchor="missing")])
    questions = _write_jsonl(tmp_path / "questions.jsonl", [_numeric(id="v2-revenue"), _numeric(id="v2-bad")])

    def run(*extra):
        argv = ["--questions", str(questions), "--gold", str(gold), "--chunks-dir", str(chunks_dir), *extra]
        return cq.main(argv, fetch_facts=lambda ticker: {"facts": {}})

    return run


def test_main_exits_0_when_the_selected_questions_have_no_errors(files, capsys):
    assert files("--ids", "v2-revenue") == 0
    out = capsys.readouterr().out
    assert "INFO  v2-revenue: part 'value': no XBRL fact matched" in out
    assert out.rstrip().endswith("1 questions checked: 0 errors, 0 warnings")


def test_main_exits_1_on_any_error(files, capsys):
    assert files() == 1
    out = capsys.readouterr().out
    assert "ERROR v2-bad: gold row 'value' (A1): anchor 'missing' is in no chunk of its filing" in out
    assert out.rstrip().endswith("2 questions checked: 2 errors, 0 warnings")


@pytest.mark.parametrize(
    "extra, message",
    [
        (["--ids", "v2-nope"], "unknown question id v2-nope"),
        (["--chunks-dir", "no-such-dir"], "no chunk files"),
        (["--gold", "no-such-gold.jsonl"], "no-such-gold.jsonl"),
    ],
)
def test_main_exits_2_on_a_read_failure(files, capsys, extra, message):
    assert files(*extra) == 2
    assert message in capsys.readouterr().err


def test_main_exits_2_on_a_malformed_question_file(tmp_path, capsys):
    bad = _write_jsonl(tmp_path / "q.jsonl", [{"id": "x", "ticker": "JPM", "question": "q", "type": "essay"}])
    assert cq.main(["--questions", str(bad)], fetch_facts=lambda ticker: {}) == 2
    assert "malformed eval question 'x'" in capsys.readouterr().err


def test_main_exits_2_on_a_usage_error(capsys):
    with pytest.raises(SystemExit) as e:
        cq.main([])
    assert e.value.code == 2


def test_a_compound_derivations_parts_are_its_anchored_inputs_at_any_depth():
    question = _numeric(expected_value=180.0, expected_unit="billion", derivation={
        "operation": "divide",
        "a": {"derivation": {"operation": "add",
                             "a": {"value": 182447, "unit": "million", "part": "revenue-2025"},
                             "b": {"value": 177556, "unit": "million", "part": "revenue-2024"}}},
        "b": {"value": 2, "unit": "raw", "constant": True},
    })
    assert _errors(question, _ctx(GROWTH_GOLD)) == []


@pytest.mark.parametrize("question", [
    {"id": "q1", "ticker": "JPM", "question": "q", "type": "refusal", "refusal_kind": "false_premise"},
    {"id": "q1", "ticker": "JPM", "question": "q", "type": "clarify", "readings": ["annual", "quarterly"]},
], ids=["refusal", "clarify"])
def test_refusal_and_clarify_rows_get_the_chunk_match_and_company_checks_only(question):
    # A false premise's correct figure, or a clarify question's readings,
    # are labelled by hand under any part name; none is required.
    assert _errors(question, _ctx()) == []
    assert _errors(question, _ctx([_gold(part="correct-figure")])) == []
    assert _errors(question, _ctx([_gold(part="annual", anchor="missing")])) == [
        "gold row 'annual' (A1): anchor 'missing' is in no chunk of its filing"
    ]
    bac_row = _gold(part="correct-figure", accession="B1", anchor="101,887")
    assert _errors(question, _ctx([bac_row])) == ["gold row 'correct-figure' (B1): its chunk is BAC's, not JPM's"]


def test_a_spread_whose_range_reaches_a_zero_divisor_is_unbounded():
    # 10 / (2 - 1): each input printed to the unit, so the divisor spans 0 to 2.
    question = _numeric(expected_value=10, expected_unit="raw", derivation={
        "operation": "divide",
        "a": {"value": 10, "unit": "raw", "constant": True},
        "b": {"derivation": {"operation": "subtract",
                             "a": {"value": 2, "unit": "raw", "part": "x"},
                             "b": {"value": 1, "unit": "raw", "part": "y"}}},
    })
    [error] = _derivation_findings(question, cq.ERROR)
    assert error.startswith("derivation: needs a tolerance (spread +/-inf")


def test_main_checking_the_v1_file_itself_reports_no_id_collisions(tmp_path, capsys):
    from sec_agent.config import QUESTIONS_PATH

    chunks_dir = tmp_path / "chunks" / "JPM"
    chunks_dir.mkdir(parents=True)
    _write_jsonl(chunks_dir / "A1_chunks.jsonl", [JPM_REVENUE])
    gold = _write_jsonl(tmp_path / "gold.jsonl", [])
    argv = ["--questions", str(QUESTIONS_PATH), "--gold", str(gold), "--chunks-dir", str(tmp_path / "chunks")]
    cq.main(argv, fetch_facts=lambda ticker: {"facts": {}})
    out = capsys.readouterr().out
    assert "48 questions checked" in out and "already used" not in out


# ---------------------------------------------------------------------------
# Review round 1
# ---------------------------------------------------------------------------
def test_a_part_name_reused_for_another_figure_is_an_error():
    question = _numeric(expected_value=6.0, derivation={
        "operation": "subtract",
        "a": {"value": 10.0, "unit": "million", "part": "x"},
        "b": {"value": 4.0, "unit": "million", "part": "x"},
    })
    assert "part 'x' names two figures: 10 million and 4 million" in _errors(question, _ctx())


def test_a_part_name_reused_for_the_same_figure_is_fine():
    question = _numeric(expected_value=0.0, derivation={
        "operation": "subtract",
        "a": {"value": 182447, "unit": "million", "part": "x"},
        "b": {"value": 182447, "unit": "million", "part": "x"},
    })
    assert _messages(cq.check_anchors(question, _ctx([_gold(part="x")]))) == []


def test_a_derivation_with_no_anchored_input_is_an_error():
    question = _numeric(expected_value=5, expected_unit="raw", derivation={
        "operation": "add", "a": {"value": 2, "unit": "raw", "constant": True},
        "b": {"value": 3, "unit": "raw", "constant": True},
    })
    assert _derivation_findings(question, cq.ERROR) == ["derivation: no input is anchored, so nothing ties it to a filing"]


def test_a_derivation_in_another_category_than_expected_reports_no_spread():
    question = _growth_question(expected_unit="million")
    findings = cq.check_derivations(question, _ctx())
    assert [f.level for f in findings] == [cq.ERROR]
    assert findings[0].message.startswith("derivation: recomputes to 2.8 percent")


def test_no_unneeded_tolerance_warning_when_a_derivation_could_not_be_assessed():
    entry = {"ticker": "JPM-growth", "companies": ["JPM"], "expected_value": 2.8, "expected_unit": "percent",
             "derivation": _growth_question()["derivation"]}
    broken = {**entry, "ticker": "BAC-growth", "companies": ["BAC"],
              "derivation": {**entry["derivation"], "b": {"value": 0, "unit": "million", "part": "zero"}}}
    question = _comparison([entry, broken], tolerance=0.02, tolerance_note="n")
    assert _derivation_findings(question, cq.WARN) == []


def test_an_absence_term_matches_across_punctuation_and_unicode_variants():
    chunk = _chunk("A1", 1, "Non‑interest income | 12,000 and the bank’s branch count")
    ctx = _ctx(chunks=[chunk])
    errors = _messages(cq.check_absence(_never_disclosed(["non-interest income", "bank's branch"]), ctx), cq.ERROR)
    assert len(errors) == 2


def test_a_trap_is_only_flagged_beside_an_answer_from_its_own_company():
    question = _comparison(
        [{"ticker": "JPM", "expected_value": 182447, "expected_unit": "million"},
         {"ticker": "BAC", "expected_value": 101887, "expected_unit": "million"}],
        forbidden_values=[{"value": 177556, "unit": "million", "ticker": "BAC"}],
    )
    gold = [_gold(part="JPM"), _gold(part="BAC", accession="B1", anchor="interest expense | 101,887")]
    assert cq.check_traps_beside_answer(question, _ctx(gold)) == []
    question["forbidden_values"][0]["ticker"] = "JPM"
    assert len(cq.check_traps_beside_answer(question, _ctx(gold))) == 1


def test_a_text_question_about_an_uncovered_company_is_an_error():
    question = {"id": "q1", "ticker": "ACME", "question": "q", "type": "text", "accepted": ["x"]}
    assert len(cq.check_tickers(question, _ctx())) == 1


@pytest.mark.parametrize("operation", ["add", "subtract", "multiply", "divide", "percent_of", "percent_change"])
def test_the_spreads_exact_arithmetic_agrees_with_the_tool_where_rounding_is_moot(operation):
    from sec_agent.agent.calculate import _apply_calculate_operation

    # 150 and 120 give results the tool's rounding leaves unchanged.
    assert cq._EXACT_OPERATIONS[operation](150, 120) == _apply_calculate_operation(operation, "scale", 150, 120)[0]


def test_a_part_name_reused_across_companies_is_an_error():
    derivation = {"operation": "add", "a": {"value": 5.0, "unit": "billion", "part": "net_income"},
                  "b": {"value": 1.0, "unit": "billion", "constant": True}}
    question = _comparison([
        {"ticker": "JPM", "expected_value": 6.0, "expected_unit": "billion", "derivation": derivation},
        {"ticker": "BAC", "expected_value": 6.0, "expected_unit": "billion", "derivation": derivation},
    ])
    assert "part 'net_income' is used for JPM and BAC" in _messages(cq.check_anchors(question, _ctx()))
