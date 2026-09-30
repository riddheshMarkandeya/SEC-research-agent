"""
Unit tests for submission.py: submission_warnings, _finalize_answer (the
verified answer or a refusal, and the citation_gate_refused log), the
retry and refusal messages, and _partition_submit_call.
"""

from typing import cast
from sec_agent.agent.submission import (
    AgentResult,
    _partition_submit_call,
    _finalize_answer,
    _format_claim_retry_message,
    _format_refusal_message,
    submission_warnings,
)
from sec_agent.agent.citations import CitationWarning
from sec_agent.prompts.agent_messages import (
    CITATION_RETRY_GUIDANCE,
)
from tests.agent.helpers import capture_events


def test_submission_warnings_invalid_args_returns_no_structured_answer():
    answer_text, warnings = submission_warnings({"answer_text": "The value was 100.", "claims": "not-a-list"}, [], "q")

    assert answer_text == "The value was 100."
    assert [w.check for w in warnings] == ["no_structured_answer"]


def test_submission_warnings_invalid_args_without_answer_text_yields_empty_text():
    answer_text, warnings = submission_warnings({}, [], "q")

    assert answer_text == ""
    assert [w.check for w in warnings] == ["no_structured_answer"]


def test_submission_warnings_valid_args_delegates_to_verify_claims(monkeypatch):
    seen = {}

    def fake_verify_claims(claims, all_results, question, answer_text):
        seen.update(claims=claims, all_results=all_results, question=question, answer_text=answer_text)
        return []

    monkeypatch.setattr("sec_agent.agent.submission.verify_claims", fake_verify_claims)
    claims = [{"value": 100.0, "unit": "raw", "citation_index": 1, "quote": "the reported value was 100"}]
    results = [{"text": "x"}]

    answer_text, warnings = submission_warnings({"answer_text": "It was 100 [1].", "claims": claims}, results, "q")

    assert (answer_text, warnings) == ("It was 100 [1].", [])
    assert seen == {"claims": claims, "all_results": results, "question": "q", "answer_text": "It was 100 [1]."}


def test_finalize_answer_passes_through_when_no_warnings():
    result = _finalize_answer("the answer", [], [], backend="gemini", retried=False)
    assert result == AgentResult("the answer", [], [], None, [])


def test_finalize_answer_refuses_when_warnings_present():
    warnings = [
        CitationWarning(
            check="quote_not_found",
            citation_index=1,
            value=100.0,
            unit="raw",
            message="[1] claims 100.0 ... doesn't appear",
            quote=None,
        )
    ]
    result = _finalize_answer("the answer", warnings, cast(list[dict], ["result"]), backend="gemini", retried=False)
    assert result.answer == _format_refusal_message(["[1] claims 100.0 ... doesn't appear"])
    assert result.results == ["result"]
    assert result.citation_warnings == ["[1] claims 100.0 ... doesn't appear"]
    assert result.citation_warning_details == [warnings[0]._asdict()]


# ---------------------------------------------------------------------------
# _finalize_answer -- withheld answer + citation_gate_refused logging
# (2026-09-10, added for the FP/FN gate-measurement work). The withheld
# answer preserves what the model actually said so it can later be
# re-graded against ground truth; nothing before this could recover it
# once the hard gate refused.
# ---------------------------------------------------------------------------
def test_finalize_answer_returns_the_withheld_answer_when_refusing():
    warnings = [
        CitationWarning(
            check="uncovered_number",
            citation_index=None,
            value=4.0,
            unit="percent",
            message="claims 4.0 (percent)...",
            quote=None,
        )
    ]
    result = _finalize_answer("the model's answer", warnings, [], backend="gemini", retried=True)
    assert result.withheld_answer == "the model's answer"
    assert result.answer != "the model's answer"  # the refusal text, not the raw answer


def test_finalize_answer_withheld_answer_is_none_when_passing():
    result = _finalize_answer("the model's answer", [], [], backend="gemini", retried=False)
    assert result.withheld_answer is None
    assert result.answer == "the model's answer"


# ---------------------------------------------------------------------------
# _finalize_answer -- citation_warning_details, AgentResult's 5th field
# (2026-09-10, see
# docs/plans/2026-09-10-structured-claims-citation-verification.md).
# Populated directly from the CitationWarnings _finalize_answer already
# holds, NOT re-derived by a second pass, so it always names the checks
# that actually refused the answer.
# ---------------------------------------------------------------------------
def test_finalize_answer_citation_warning_details_empty_when_passing():
    result = _finalize_answer("the answer", [], [], backend="gemini", retried=False)
    assert result.citation_warning_details == []


def test_finalize_answer_citation_warning_details_matches_the_actual_warnings():
    # Proves this field comes from the warnings _finalize_answer was
    # actually given, not re-derived. Also the
    # `quote` field's own presence in the resulting dict, proving it
    # survives the CitationWarning -> _asdict() -> report JSON path
    # unmodified (see Fix B's docstring rationale on verify_claims).
    warnings = [
        CitationWarning(
            check="quote_not_found",
            citation_index=2,
            value=42.0,
            unit="million",
            message="[2] quote not found",
            quote="the model's claimed quote text",
        )
    ]
    result = _finalize_answer("the answer", warnings, [], backend="gemini", retried=False)
    assert result.citation_warning_details == [
        {
            "check": "quote_not_found",
            "citation_index": 2,
            "value": 42.0,
            "unit": "million",
            "message": "[2] quote not found",
            "quote": "the model's claimed quote text",
        }
    ]


def test_finalize_answer_logs_citation_gate_refused_with_check_counts(monkeypatch):
    log_calls = []
    capture_events(monkeypatch, log_calls)
    warnings = [
        CitationWarning(
            check="quote_not_found",
            citation_index=1,
            value=100.0,
            unit="raw",
            message="[1] claims 100.0...",
            quote=None,
        ),
        CitationWarning(
            check="uncovered_number",
            citation_index=None,
            value=4.0,
            unit="percent",
            message="claims 4.0 (percent)...",
            quote=None,
        ),
    ]
    _finalize_answer("the model's answer", warnings, cast(list[dict], ["result"]), backend="gemini", retried=True)

    assert len(log_calls) == 1
    category, fields = log_calls[0]
    assert category == "citation_gate_refused"
    assert fields["backend"] == "gemini"
    assert fields["retried"] is True
    assert fields["n_results"] == 1
    assert fields["checks"] == {"quote_not_found": 1, "uncovered_number": 1}
    assert fields["warnings"] == ["[1] claims 100.0...", "claims 4.0 (percent)..."]
    assert fields["withheld_answer"] == "the model's answer"


def test_finalize_answer_does_not_log_when_passing(monkeypatch):
    log_calls = []
    capture_events(monkeypatch, log_calls)
    _finalize_answer("the model's answer", [], [], backend="gemini", retried=False)
    assert log_calls == []


def test_format_refusal_message_includes_each_warning():
    warnings = [
        "[1] claims 6478.0 (million) but that value doesn't appear in the cited source",
        "[2] claims 42.0 (raw) but that value doesn't appear in the cited source",
    ]
    message = _format_refusal_message(warnings)
    for w in warnings:
        assert w in message


def test_format_refusal_message_reads_as_a_refusal():
    message = _format_refusal_message(["[1] claims ... doesn't appear"]).lower()
    assert "refus" in message or "can't confirm" in message or "can't verify" in message


def test_format_claim_retry_message_tells_model_to_recheck_shown_sources_first():
    # Targets the aapl-employees-fy25 failure mode from Week 5j: the
    # retry gave up entirely instead of checking the 4 OTHER
    # already-retrieved chunks for a valid citation.
    message = _format_claim_retry_message("answer", [])
    assert "already" in message.lower()


def test_format_claim_retry_message_permits_an_honest_refusal():
    message = _format_claim_retry_message("answer", [])
    assert "refus" in message.lower() or "acceptable" in message.lower()


def test_format_claim_retry_message_forbids_inventing_or_estimating():
    message = _format_claim_retry_message("answer", [])
    assert "invent" in message.lower() or "estimat" in message.lower()


def test_format_claim_retry_message_never_uses_final_attempt_deadline_pressure():
    # Regression guard for the exact Week 5j-diagnosed cause of a
    # fabrication regression: wording like "this is your final attempt"
    # pushed the model to fabricate an estimate on a previously-reliable
    # refusal question. Must never reappear in this message.
    message = _format_claim_retry_message("answer", [])
    lowered = message.lower()
    assert "final attempt" not in lowered
    assert "last chance" not in lowered


# ---------------------------------------------------------------------------
# _format_claim_retry_message (2026-09-10) -- structured-claims retry
# wording, built around CITATION_RETRY_GUIDANCE.
# ---------------------------------------------------------------------------
def test_format_claim_retry_message_includes_each_warning():
    warnings = [
        CitationWarning(
            check="quote_not_found", citation_index=1, value=100.0, unit="raw", message="[1] quote missing", quote=None
        ),
        CitationWarning(
            check="value_not_in_quote", citation_index=2, value=42.0, unit="raw", message="[2] value missing", quote=None
        ),
    ]
    message = _format_claim_retry_message("the answer", warnings)
    assert "[1] quote missing" in message
    assert "[2] value missing" in message


def test_format_claim_retry_message_includes_the_previous_answer():
    message = _format_claim_retry_message("Apple's revenue was $100 billion.", [])
    assert "Apple's revenue was $100 billion." in message


def test_format_claim_retry_message_includes_the_shared_guidance():
    assert CITATION_RETRY_GUIDANCE in _format_claim_retry_message("answer", [])


def test_format_claim_retry_message_tells_model_to_call_submit_answer_again():
    message = _format_claim_retry_message("answer", [])
    assert "submit_answer" in message


# ---------------------------------------------------------------------------
# _partition_submit_call (2026-09-10) -- splits a turn's tool_calls into
# the submit_answer call (if any) and every other call, so the loop can
# tell a pure submission from a mixed submit+search turn without a
# str|Terminal union return type on _dispatch_tool_call. See
# docs/plans/2026-09-10-structured-claims-citation-verification.md.
# ---------------------------------------------------------------------------
def test_partition_submit_call_pure_submission():
    submit_call = {"name": "submit_answer", "args": {"answer_text": "x", "claims": []}}
    submit, other = _partition_submit_call([submit_call])
    assert submit is submit_call
    assert other == []


def test_partition_submit_call_no_submission():
    search_call = {"name": "search_filings", "args": {"query": "revenue"}}
    submit, other = _partition_submit_call([search_call])
    assert submit is None
    assert other == [search_call]


def test_partition_submit_call_mixed_turn():
    submit_call = {"name": "submit_answer", "args": {"answer_text": "x", "claims": []}}
    search_call = {"name": "search_filings", "args": {"query": "revenue"}}
    submit, other = _partition_submit_call([submit_call, search_call])
    assert submit is submit_call
    assert other == [search_call]


def test_partition_submit_call_empty():
    assert _partition_submit_call([]) == (None, [])
