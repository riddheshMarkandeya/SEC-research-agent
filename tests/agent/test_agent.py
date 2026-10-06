"""
Unit tests for agent.py: the turn rule (_next_turn_mode) and
run_agent()'s control flow. run_agent()'s model-facing behavior needs
a live backend (manual runs and tests/manual/), but its loop control flow
-- how it reacts to a scripted sequence of ModelTurns -- is deterministic,
so these tests drive it through monkeypatched BACKENDS entries.
"""

from contextlib import contextmanager

import pytest

from sec_agent.agent.agent import (
    _next_turn_mode,
    run_agent,
)
from sec_agent.agent.citations import CitationWarning
from sec_agent.llm import llm_backends
from sec_agent.llm.llm_backends import ModelTurn
from sec_agent.prompts.agent_messages import (
    BUDGET_EXHAUSTED_ANSWER,
    FINAL_TURN_SUBMIT_MESSAGE,
    NO_SUBMISSION_REFUSAL,
    NO_SUBMISSION_WARNING,
)
from sec_agent.prompts.agent_system import SYSTEM_PROMPT
from sec_agent.prompts.agent_tools import (
    AGENT_TOOL_SCHEMAS,
    CALCULATE_TOOL_SCHEMA,
    COMPARE_TOOL_SCHEMA,
    FACT_TOOL_SCHEMA,
    SEARCH_TOOL_SCHEMA,
    SUBMIT_TOOL_SCHEMA,
)
from tests.agent.helpers import capture_events


# ---------------------------------------------------------------------------
# _next_turn_mode: the one rule for every extra turn -- free while dispatch
# budget is left, forced while the reserve lasts, else none.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("calls_made", "reserve_left", "expected"),
    [
        (5, 2, "free"),
        (5, 0, "free"),
        (6, 2, "forced"),
        (7, 1, "forced"),
        (8, 0, None),
        (6, 0, None),
    ],
)
def test_next_turn_mode(calls_made, reserve_left, expected):
    assert _next_turn_mode(calls_made, reserve_left) == expected


def _repeating_backend(fake_start):
    """A BACKENDS entry whose every later turn (tool results, forced
    follow-ups, retries) repeats fake_start's own turn -- for tests that
    only care how the loop finalizes a model that keeps saying the same
    thing."""

    first_turn = []

    def start(question, system_prompt, tool_schemas):
        state, turn = fake_start(question, system_prompt, tool_schemas)
        first_turn.append(turn)
        return state, turn

    def repeat(*_args, **_kwargs):
        return first_turn[0]

    return start, repeat, repeat


# ---------------------------------------------------------------------------
# run_agent() -- loop control flow only, via a fake/scripted backend (see
# module docstring for why this is fair game for a unit test despite
# run_agent() otherwise being live-only)
# ---------------------------------------------------------------------------
def test_run_agent_sends_the_system_prompt_and_tool_schemas_in_order(monkeypatch):
    # Pins what the model is actually given at conversation start --
    # the exact SYSTEM_PROMPT object and the five schemas in the order
    # Gemini receives them -- so a prompt/schema move or reorder can't
    # silently change the model's input without this failing.
    captured = {}

    def fake_start(question, system_prompt, tool_schemas):
        captured["system_prompt"] = system_prompt
        captured["tool_schemas"] = tool_schemas
        return {}, ModelTurn(tool_calls=[], text="done")

    monkeypatch.setattr("sec_agent.agent.agent.BACKENDS", {"gemini": _repeating_backend(fake_start)})

    run_agent("What was Apple's revenue?", backend="gemini")

    assert captured["system_prompt"] is SYSTEM_PROMPT
    assert captured["tool_schemas"] == list(AGENT_TOOL_SCHEMAS)
    assert list(AGENT_TOOL_SCHEMAS) == [
        FACT_TOOL_SCHEMA, COMPARE_TOOL_SCHEMA, SEARCH_TOOL_SCHEMA, CALCULATE_TOOL_SCHEMA, SUBMIT_TOOL_SCHEMA
    ]


# ---------------------------------------------------------------------------
# citation hard-gate (Week 7): run_agent() must refuse, not just warn, when
# citation verification still fails after any applicable retry
# ---------------------------------------------------------------------------
def test_run_agent_refuses_a_text_answer_given_again_after_forcing(monkeypatch):
    # A text reply gets one forced submit_answer turn; text again means
    # there's nothing structured to verify, so the answer is refused with
    # the no-submission wording and the text kept for FP analysis.
    text_turn = ModelTurn(tool_calls=[], text="Apple's revenue was $100 billion [1].")
    followups = []

    def fake_start(question, system_prompt, tool_schemas):
        return {}, text_turn

    def fake_send_followup(state, text, force_tool=None):
        followups.append(force_tool)
        return text_turn

    log_calls = []
    capture_events(monkeypatch, log_calls)
    monkeypatch.setattr("sec_agent.agent.agent.BACKENDS", {"gemini": (fake_start, None, fake_send_followup)})

    answer, all_results, warnings, withheld_answer, details = run_agent("What was Apple's revenue?", backend="gemini")

    assert followups == ["submit_answer"]
    assert answer == NO_SUBMISSION_REFUSAL
    assert warnings == [NO_SUBMISSION_WARNING]
    assert [d["check"] for d in details] == ["no_submission"]
    assert withheld_answer == "Apple's revenue was $100 billion [1]."
    [refused] = [fields for category, fields in log_calls if category == "citation_gate_refused"]
    assert refused["checks"] == {"no_submission": 1}


def test_run_agent_forces_submit_on_a_text_answer_at_the_budget_edge(monkeypatch):
    # The start turn already uses the whole budget, but the one reserved
    # final round trip is unspent, so the text still gets its forced
    # submit_answer turn -- here the model then submits.
    monkeypatch.setattr("sec_agent.agent.agent.MAX_TOOL_ITERATIONS", 1)
    followups = []

    def fake_start(question, system_prompt, tool_schemas):
        return {}, ModelTurn(tool_calls=[], text="Revenue was $100 billion.")

    def fake_send_followup(state, text, force_tool=None):
        followups.append(force_tool)
        return _submit_turn(answer_text="Revenue was $100 billion.")

    log_calls = []
    capture_events(monkeypatch, log_calls)
    monkeypatch.setattr("sec_agent.agent.agent.BACKENDS", {"gemini": (fake_start, None, fake_send_followup)})
    monkeypatch.setattr("sec_agent.agent.submission.verify_claims", lambda *a: [])

    answer, all_results, warnings, withheld_answer, _ = run_agent("What was Apple's revenue?", backend="gemini")

    assert followups == ["submit_answer"]
    assert answer == "Revenue was $100 billion."
    assert withheld_answer is None
    # Spending the reserve is logged like the pending-tool path's, with
    # no pending tools.
    [forced] = [fields for category, fields in log_calls if category == "final_turn_forced"]
    assert forced == {
        "backend": "gemini",
        "calls_made": 1,
        "pending_tools": [],
        "reserve_left": 1,
        "trigger": "text",
    }


def test_run_agent_refuses_a_text_answer_once_the_final_turn_is_spent(monkeypatch):
    # Budget exhausted with a tool call pending: the reserved final turn
    # forces submit_answer, the model answers in text anyway, and there's
    # nothing left to force with, so the text is refused straight away.
    monkeypatch.setattr("sec_agent.agent.agent.MAX_TOOL_ITERATIONS", 1)
    text_turn = ModelTurn(tool_calls=[], text="Revenue was $100 billion.")

    def fake_start(question, system_prompt, tool_schemas):
        return {}, ModelTurn(tool_calls=[{"name": "search_filings", "args": {}}], text=None)

    monkeypatch.setattr(
        "sec_agent.agent.agent.BACKENDS", {"gemini": (fake_start, lambda state, results, force_tool=None: text_turn, None)}
    )

    answer, all_results, warnings, withheld_answer, details = run_agent(
        "What was Apple's revenue?", backend="gemini", verbose=True
    )

    assert answer == NO_SUBMISSION_REFUSAL
    assert [d["check"] for d in details] == ["no_submission"]
    assert withheld_answer == "Revenue was $100 billion."


def test_run_agent_text_after_forcing_regates_a_submission_cached_by_the_retry(monkeypatch):
    # submit (claims fail) -> retry -> the model answers in text, is
    # forced, answers in text again. Its earlier submission is still its
    # last verifiable answer, so that is re-gated rather than refusing
    # with no_submission -- here it now passes.
    text_turn = ModelTurn(tool_calls=[], text="Let me restate: the value was 100.")

    def fake_start(question, system_prompt, tool_schemas):
        return {}, _submit_turn(answer_text="The value was 100.")

    monkeypatch.setattr(
        "sec_agent.agent.agent.BACKENDS",
        {"gemini": (fake_start, lambda state, results, force_tool=None: text_turn, lambda *a, **k: text_turn)},
    )
    verify_calls = []

    def fake_verify_claims(claims, all_results, question, answer_text):
        verify_calls.append(answer_text)
        if len(verify_calls) == 1:
            return [CitationWarning(check="quote_not_found", citation_index=1, value=100.0, unit="raw", message="bad", quote=None)]
        return []

    monkeypatch.setattr("sec_agent.agent.submission.verify_claims", fake_verify_claims)

    answer, all_results, warnings, withheld_answer, _ = run_agent("What was the value?", backend="gemini")

    assert verify_calls == ["The value was 100.", "The value was 100."]
    assert answer == "The value was 100."
    assert warnings == []
    assert withheld_answer is None


def test_run_agent_returns_generic_timeout_message_unchanged_when_iterations_exhausted(monkeypatch):
    # The iteration-budget-exhausted fallback (no cached submission to
    # fall back to) always passes warnings=[] into finalize_answer(), so this
    # locks in that routing it through the same choke point as every
    # other return site (code review, 2026-08-26) is a genuine no-op --
    # the generic message must still come back completely unchanged.
    monkeypatch.setattr("sec_agent.agent.agent.MAX_TOOL_ITERATIONS", 1)

    keeps_calling_tools = ModelTurn(tool_calls=[{"name": "search_filings", "args": {}}], text=None)

    def fake_start(question, system_prompt, tool_schemas):
        return {}, keeps_calling_tools

    monkeypatch.setattr("sec_agent.agent.agent.BACKENDS", {"gemini": _repeating_backend(fake_start)})

    answer, all_results, warnings, withheld_answer, _ = run_agent("What was Apple's revenue?", backend="gemini")

    assert answer == (
        "I wasn't able to finish answering within the allotted number of searches. "
        "Try asking a more specific or narrower question."
    )
    assert warnings == []
    assert withheld_answer is None


# ---------------------------------------------------------------------------
# Final-turn safety net (BACKLOG.md's MAX_TOOL_ITERATIONS zero-slack bug --
# docs/decisions/2026-09-16-final-turn-safety-net.md): when the dispatch budget
# is exhausted but the model is still actively requesting tool calls (not
# yet given up), the loop spends one reserved, submit-only round trip
# instead of immediately falling through to the generic timeout.
# ---------------------------------------------------------------------------
def test_run_agent_final_turn_safety_net_rescues_a_clean_refusal(monkeypatch):
    monkeypatch.setattr("sec_agent.agent.agent.MAX_TOOL_ITERATIONS", 2)

    keeps_calling_tools = ModelTurn(tool_calls=[{"name": "search_filings", "args": {}}], text=None)
    clean_refusal = _submit_turn(answer_text="I don't have enough data to answer.", claims=[])

    def fake_start(question, system_prompt, tool_schemas):
        return {}, keeps_calling_tools

    send_tool_results_calls = []

    def fake_send_tool_results(state, results, force_tool=None):
        send_tool_results_calls.append((results, force_tool))
        return clean_refusal if force_tool == "submit_answer" else keeps_calling_tools

    monkeypatch.setattr("sec_agent.agent.agent.BACKENDS", {"gemini": (fake_start, fake_send_tool_results, None)})
    monkeypatch.setattr(
        "sec_agent.agent.agent.dispatch_tool_call",
        lambda call, question, all_results, searched_tickers, verbose: "search result",
    )
    monkeypatch.setattr("sec_agent.agent.submission.verify_claims", lambda claims, all_results, question, answer_text: [])
    log_calls = []
    capture_events(monkeypatch, log_calls)

    answer, all_results, warnings, withheld_answer, _ = run_agent("What was the value?", backend="gemini")

    # One ordinary dispatch round trip (calls_made 1 -> 2), then exactly
    # one forced final-turn round trip once the budget is exhausted.
    assert len(send_tool_results_calls) == 2
    forced_results, forced_tool = send_tool_results_calls[-1]
    assert forced_tool == "submit_answer"
    assert len(forced_results) == 1  # one synthetic result per pending call in `other`
    assert forced_results[0]["name"] == "search_filings"
    assert answer == "I don't have enough data to answer."
    assert answer != (
        "I wasn't able to finish answering within the allotted number of searches. "
        "Try asking a more specific or narrower question."
    )
    assert warnings == []
    assert withheld_answer is None
    # Local-only debug event: the safety net engaging is now directly
    # queryable instead of only inferable from counting trace spans.
    assert (
        "final_turn_forced",
        {
            "backend": "gemini",
            "calls_made": 2,
            "pending_tools": ["search_filings"],
            "reserve_left": 1,
            "trigger": "pending_tools",
        },
    ) in log_calls


def test_run_agent_tool_calls_after_the_forced_final_turn_end_the_run(monkeypatch):
    # An uncooperative model keeps requesting tool calls even on the
    # forced final turn: forcing failed, so the run ends on the generic
    # budget message instead of spending the second reserve turn.
    monkeypatch.setattr("sec_agent.agent.agent.MAX_TOOL_ITERATIONS", 2)

    keeps_calling_tools = ModelTurn(tool_calls=[{"name": "search_filings", "args": {}}], text=None)

    def fake_start(question, system_prompt, tool_schemas):
        return {}, keeps_calling_tools

    send_tool_results_calls = []

    def fake_send_tool_results(state, results, force_tool=None):
        send_tool_results_calls.append((results, force_tool))
        return keeps_calling_tools  # never complies, whether forced or not

    monkeypatch.setattr("sec_agent.agent.agent.BACKENDS", {"gemini": (fake_start, fake_send_tool_results, None)})
    monkeypatch.setattr(
        "sec_agent.agent.agent.dispatch_tool_call",
        lambda call, question, all_results, searched_tickers, verbose: "search result",
    )

    answer, all_results, warnings, withheld_answer, _ = run_agent("What was the value?", backend="gemini")

    forced_calls = [c for c in send_tool_results_calls if c[1] == "submit_answer"]
    assert len(forced_calls) == 1  # spent exactly once, never repeated
    assert answer == (
        "I wasn't able to finish answering within the allotted number of searches. "
        "Try asking a more specific or narrower question."
    )
    assert warnings == []
    assert withheld_answer is None

def test_final_turn_submit_message_contains_no_deadline_pressure_language():
    # Regression guard against reintroducing the documented fabrication
    # scar (prompts.agent_messages.CITATION_RETRY_GUIDANCE's comment): a prior
    # "final attempt" framing pushed the model to fabricate an estimate
    # on nvda-rd-expense-q4fy26-refusal instead of refusing honestly.
    lowered = FINAL_TURN_SUBMIT_MESSAGE.lower()
    assert "final attempt" not in lowered
    assert "last chance" not in lowered
    assert "acceptable outcome" in lowered  # mirrors CITATION_RETRY_GUIDANCE's proven phrasing


# ---------------------------------------------------------------------------
# run_agent() -- submit_answer loop control (2026-09-10). See
# docs/plans/2026-09-10-structured-claims-citation-verification.md. All
# via the same scripted fake-backend harness used above (agent.BACKENDS
# monkeypatched) -- run_agent()'s actual model-facing behavior is
# exercised live by tests/manual/verify_submit_answer.py, not here; this
# is deterministic loop CONTROL FLOW given a scripted sequence of turns.
# ---------------------------------------------------------------------------
def _submit_turn(answer_text="The value was 100.", claims=None):
    claims = [{"value": 100.0, "unit": "raw", "citation_index": 1, "quote": "the reported value was 100"}] if claims is None else claims
    return ModelTurn(tool_calls=[{"name": "submit_answer", "args": {"answer_text": answer_text, "claims": claims}}], text=None)


def test_run_agent_spontaneous_submit_answer_with_valid_claims_passes(monkeypatch):
    def fake_start(question, system_prompt, tool_schemas):
        return {}, _submit_turn()

    monkeypatch.setattr("sec_agent.agent.agent.BACKENDS", {"gemini": (fake_start, None, None)})
    monkeypatch.setattr(
        "sec_agent.agent.submission.verify_claims", lambda claims, all_results, question, answer_text: []
    )

    answer, all_results, warnings, withheld_answer, _ = run_agent("What was the value?", backend="gemini")

    assert answer == "The value was 100."
    assert warnings == []
    assert withheld_answer is None


def test_run_agent_submit_answer_bad_claims_retries_on_gemini_then_succeeds(monkeypatch):
    first_submit = _submit_turn(answer_text="The value was 100.")
    corrected_submit = _submit_turn(answer_text="The value was 100, corrected.")

    def fake_start(question, system_prompt, tool_schemas):
        return {}, first_submit

    sent_results = []

    def fake_send_tool_results(state, results, force_tool=None):
        sent_results.append(results)
        return corrected_submit

    monkeypatch.setattr("sec_agent.agent.agent.BACKENDS", {"gemini": (fake_start, fake_send_tool_results, None)})

    verify_calls = iter(
        [
            [
                CitationWarning(
                    check="quote_not_found",
                    citation_index=1,
                    value=100.0,
                    unit="raw",
                    message="[1] quote not found",
                    quote=None,
                )
            ],
            [],
        ]
    )
    monkeypatch.setattr("sec_agent.agent.submission.verify_claims", lambda claims, all_results, question, answer_text: next(verify_calls))

    answer, all_results, warnings, withheld_answer, _ = run_agent("What was the value?", backend="gemini")

    assert answer == "The value was 100, corrected."
    assert warnings == []
    # The retry's corrective feedback was delivered as a submit_answer
    # TOOL RESULT (send_tool_results), not a plain follow-up turn -- keeps
    # the chat history well-formed (see the loop's own docstring on this).
    assert sent_results == [[{"name": "submit_answer", "content": sent_results[0][0]["content"]}]]
    assert "[1] quote not found" in sent_results[0][0]["content"]

def test_run_agent_mixed_submit_and_search_turn_requests_resubmission(monkeypatch):
    mixed_turn = ModelTurn(
        tool_calls=[
            {"name": "submit_answer", "args": {"answer_text": "x", "claims": []}},
            {"name": "search_filings", "args": {"query": "revenue"}},
        ],
        text=None,
    )
    final_submit = _submit_turn(answer_text="The value was 100, now grounded.")

    def fake_start(question, system_prompt, tool_schemas):
        return {}, mixed_turn

    sent_results = []

    def fake_send_tool_results(state, results):
        sent_results.append(results)
        return final_submit

    monkeypatch.setattr("sec_agent.agent.agent.BACKENDS", {"gemini": (fake_start, fake_send_tool_results, None)})
    monkeypatch.setattr("sec_agent.agent.submission.verify_claims", lambda claims, all_results, question, answer_text: [])
    monkeypatch.setattr(
        "sec_agent.agent.agent.dispatch_tool_call", lambda call, question, all_results, searched_tickers, verbose: "search results here"
    )

    answer, all_results, warnings, withheld_answer, _ = run_agent("What was the value?", backend="gemini")

    assert answer == "The value was 100, now grounded."
    # Both the search result AND a resubmission request went back in the
    # same turn -- the model can't have grounded claims in results it
    # hasn't read yet.
    names_sent = [r["name"] for r in sent_results[0]]
    assert names_sent == ["search_filings", "submit_answer"]
    assert "resubmit" in sent_results[0][1]["content"].lower() or "again" in sent_results[0][1]["content"].lower()


def test_run_agent_mixed_submit_and_search_on_last_turn_salvages_the_submission(monkeypatch):
    # Regression test for the ordering edge case: a mixed submit+search
    # turn landing on the VERY LAST allowed round trip has no budget left
    # to dispatch the searches and get a clean resubmission back -- the
    # submission must still be verified, not discarded for the generic
    # timeout message.
    monkeypatch.setattr("sec_agent.agent.agent.MAX_TOOL_ITERATIONS", 1)
    mixed_turn = ModelTurn(
        tool_calls=[
            {"name": "submit_answer", "args": {"answer_text": "The value was 100.", "claims": []}},
            {"name": "search_filings", "args": {"query": "revenue"}},
        ],
        text=None,
    )

    def fake_start(question, system_prompt, tool_schemas):
        return {}, mixed_turn

    monkeypatch.setattr("sec_agent.agent.agent.BACKENDS", {"gemini": (fake_start, None, None)})
    monkeypatch.setattr("sec_agent.agent.submission.verify_claims", lambda claims, all_results, question, answer_text: [])

    answer, all_results, warnings, withheld_answer, _ = run_agent("What was the value?", backend="gemini")

    assert answer == "The value was 100."
    assert answer != (
        "I wasn't able to finish answering within the allotted number of searches. "
        "Try asking a more specific or narrower question."
    )


def test_run_agent_text_reply_on_gemini_forces_submit_answer(monkeypatch):
    text_turn = ModelTurn(tool_calls=[], text="Apple's revenue was $100 billion [1].")
    forced_submit = _submit_turn(answer_text="Apple's revenue was $100 billion [1].")

    def fake_start(question, system_prompt, tool_schemas):
        return {}, text_turn

    forced_calls = []

    def fake_send_followup(state, text, force_tool=None):
        forced_calls.append((text, force_tool))
        return forced_submit

    monkeypatch.setattr("sec_agent.agent.agent.BACKENDS", {"gemini": (fake_start, None, fake_send_followup)})
    monkeypatch.setattr("sec_agent.agent.submission.verify_claims", lambda claims, all_results, question, answer_text: [])

    answer, all_results, warnings, withheld_answer, _ = run_agent("What was Apple's revenue?", backend="gemini")

    assert answer == "Apple's revenue was $100 billion [1]."
    assert len(forced_calls) == 1
    assert forced_calls[0][1] == "submit_answer"  # force_tool was actually passed

def test_run_agent_malformed_submit_answer_args_produces_no_structured_answer_warning(monkeypatch):
    # Defensive boundary check (same belt-and-suspenders every other tool
    # gets via validate_tool_args) -- not expected in practice (both
    # backends called this correctly on every live run tried), but a
    # schema-invalid submit_answer call must still be handled, not crash.
    malformed_turn = ModelTurn(
        tool_calls=[{"name": "submit_answer", "args": {"answer_text": "The value was 100.", "claims": "not-a-list"}}],
        text=None,
    )

    def fake_start(question, system_prompt, tool_schemas):
        return {}, malformed_turn

    monkeypatch.setattr("sec_agent.agent.agent.BACKENDS", {"gemini": _repeating_backend(fake_start)})

    answer, all_results, warnings, withheld_answer, _ = run_agent("What was the value?", backend="gemini")

    assert len(warnings) == 1
    assert "schema" in warnings[0].lower()
    assert withheld_answer == "The value was 100."


def test_run_agent_submit_answer_retry_exhausting_budget_reverifies_against_current_all_results(monkeypatch):
    # This is the actual proof that the cached-answer staleness bug
    # is closed structurally for the submit_answer path, not
    # just described as closed: caches the RAW submit_args (not
    # pre-computed warnings) and re-runs verify_claims against whatever
    # all_results actually is by the time the budget runs out -- here,
    # grown by one more search dispatched AFTER the retry fired.
    # MAX_TOOL_ITERATIONS bumped by 1 again (3, was already bumped once
    # for the citation-retry mechanism) to make room for the final-turn
    # safety net's own reserved round trip (2026-09-16) without changing
    # what this test is actually regression-testing.
    monkeypatch.setattr("sec_agent.agent.agent.MAX_TOOL_ITERATIONS", 3)
    first_submit = _submit_turn(answer_text="The value was 100.")
    retry_makes_new_search = ModelTurn(tool_calls=[{"name": "search_filings", "args": {"query": "more"}}], text=None)
    another_search_turn = ModelTurn(tool_calls=[{"name": "search_filings", "args": {"query": "even more"}}], text=None)
    # The model ignores the forced final-turn nudge too (Gemini's real
    # hard constraint isn't exercised by this fake), so the run ends by
    # re-gating the cached submission, which this test verifies.
    ignores_forced_nudge = ModelTurn(tool_calls=[{"name": "search_filings", "args": {"query": "still"}}], text=None)

    def fake_start(question, system_prompt, tool_schemas):
        return {}, first_submit

    responses = iter([retry_makes_new_search, another_search_turn, ignores_forced_nudge])

    def fake_send_tool_results(state, results, force_tool=None):
        return next(responses)

    monkeypatch.setattr("sec_agent.agent.agent.BACKENDS", {"gemini": (fake_start, fake_send_tool_results, None)})
    monkeypatch.setattr(
        "sec_agent.agent.agent.dispatch_tool_call",
        lambda call, question, all_results, searched_tickers, verbose: all_results.append({"text": "extra"}) or "search result",
    )

    verify_calls = []

    def fake_verify_claims(claims, all_results, question, answer_text):
        verify_calls.append(len(all_results))
        return (
            []
            if len(all_results) > 0
            else [
                CitationWarning(
                    check="quote_not_found", citation_index=1, value=100.0, unit="raw", message="bad", quote=None
                )
            ]
        )

    monkeypatch.setattr("sec_agent.agent.submission.verify_claims", fake_verify_claims)

    answer, all_results, warnings, withheld_answer, _ = run_agent("What was the value?", backend="gemini")

    # Called once at retry-decision time (0 results, fails) and once more
    # at the exhausted-budget fallback (1 result by then, passes) --
    # proving the re-check sees the CURRENT all_results, not a stale
    # snapshot from when the retry fired.
    assert verify_calls == [0, 1]
    assert warnings == []
    assert answer == "The value was 100."


def test_run_agent_invalid_submit_then_exhausted_budget_refuses_instead_of_crashing(monkeypatch):
    # A schema-invalid submit triggers the corrective retry, which caches
    # those invalid args; if the run then ends without a submit, the
    # cached re-gate must put them back through the same boundary check, not
    # index their missing keys.
    monkeypatch.setattr("sec_agent.agent.agent.MAX_TOOL_ITERATIONS", 3)
    invalid_submit = ModelTurn(tool_calls=[{"name": "submit_answer", "args": {"claims": "not-a-list"}}], text=None)
    search_turn = ModelTurn(tool_calls=[{"name": "search_filings", "args": {"query": "more"}}], text=None)

    def fake_start(question, system_prompt, tool_schemas):
        return {}, invalid_submit

    def fake_send_tool_results(state, results, force_tool=None):
        return search_turn

    monkeypatch.setattr("sec_agent.agent.agent.BACKENDS", {"gemini": (fake_start, fake_send_tool_results, None)})
    monkeypatch.setattr(
        "sec_agent.agent.agent.dispatch_tool_call",
        lambda call, question, all_results, searched_tickers, verbose: all_results.append({"text": "extra"}) or "search result",
    )

    answer, all_results, warnings, withheld_answer, details = run_agent("What was the value?", backend="gemini")

    assert [d["check"] for d in details] == ["no_structured_answer"]
    assert withheld_answer == ""


# ---------------------------------------------------------------------------
# Citation-retry slot: a citation retry runs whether or not dispatch budget
# is left. Past the budget it's forced to submit_answer, since no search could run.
# ---------------------------------------------------------------------------
_SEARCH_TURN = ModelTurn(tool_calls=[{"name": "search_filings", "args": {"query": "more"}}], text=None)
_BAD = CitationWarning(check="quote_not_found", citation_index=1, value=100.0, unit="raw", message="bad", quote=None)
_MIXED_TURN = ModelTurn(
    tool_calls=[
        {"name": "submit_answer", "args": {"answer_text": "The value was 100.", "claims": []}},
        {"name": "search_filings", "args": {"query": "revenue"}},
    ],
    text=None,
)


def _install_scripted_backend(monkeypatch, start_turn, replies, payloads=None):
    """BACKENDS entry that starts with `start_turn` and answers each later
    send with the next of `replies`. Returns the list of sends, each
    (kind, [result names], force_tool), plus the start, as one request each.
    Each send_tool_results call's full results also go to `payloads`, if given."""
    sends = []
    replies = iter(replies)

    def start(question, system_prompt, tool_schemas):
        sends.append(("start", [], None))
        return {}, start_turn

    def send_tool_results(state, results, force_tool=None):
        sends.append(("tool_results", [r["name"] for r in results], force_tool))
        if payloads is not None:
            payloads.append(results)
        return next(replies)

    def send_followup(state, text, force_tool=None):
        sends.append(("followup", [], force_tool))
        return next(replies)

    monkeypatch.setattr("sec_agent.agent.agent.BACKENDS", {"gemini": (start, send_tool_results, send_followup)})
    monkeypatch.setattr(
        "sec_agent.agent.agent.dispatch_tool_call",
        lambda call, question, all_results, searched_tickers, verbose: "search result",
    )
    return sends


def _verify_sequence(monkeypatch, outcomes):
    """verify_claims returning each of `outcomes` in turn; returns its call log."""
    calls = []
    outcomes = iter(outcomes)

    def fake_verify_claims(claims, all_results, question, answer_text):
        calls.append(answer_text)
        return next(outcomes)

    monkeypatch.setattr("sec_agent.agent.submission.verify_claims", fake_verify_claims)
    return calls


def test_run_agent_retries_after_the_forced_final_turn_and_forces_submit(monkeypatch):
    monkeypatch.setattr("sec_agent.agent.agent.MAX_TOOL_ITERATIONS", 1)
    sends = _install_scripted_backend(
        monkeypatch, _SEARCH_TURN, [_submit_turn("The value was 100."), _submit_turn("The value was 100, fixed.")]
    )
    _verify_sequence(monkeypatch, [[_BAD], []])
    log_calls = []
    capture_events(monkeypatch, log_calls)

    answer, _, warnings, withheld_answer, _ = run_agent("What was the value?", backend="gemini")

    assert sends[1:] == [
        ("tool_results", ["search_filings"], "submit_answer"),
        ("tool_results", ["submit_answer"], "submit_answer"),
    ]
    assert answer == "The value was 100, fixed."
    assert warnings == []
    assert withheld_answer is None
    [retry] = [fields for category, fields in log_calls if category == "citation_retry"]
    assert retry["calls_made"] == 2
    assert retry["forced"] is True
    assert retry["pending_tools"] == []


def test_run_agent_retries_a_submit_landing_exactly_at_the_budget(monkeypatch):
    monkeypatch.setattr("sec_agent.agent.agent.MAX_TOOL_ITERATIONS", 2)
    sends = _install_scripted_backend(
        monkeypatch, _SEARCH_TURN, [_submit_turn("The value was 100."), _submit_turn("The value was 100, fixed.")]
    )
    _verify_sequence(monkeypatch, [[_BAD], []])

    answer, *_ = run_agent("What was the value?", backend="gemini")

    assert sends[1:] == [
        ("tool_results", ["search_filings"], None),
        ("tool_results", ["submit_answer"], "submit_answer"),
    ]
    assert answer == "The value was 100, fixed."


def test_run_agent_in_budget_retry_is_not_forced(monkeypatch):
    sends = _install_scripted_backend(
        monkeypatch, _submit_turn("The value was 100."), [_submit_turn("The value was 100, fixed.")]
    )
    _verify_sequence(monkeypatch, [[_BAD], []])
    log_calls = []
    capture_events(monkeypatch, log_calls)

    run_agent("What was the value?", backend="gemini")

    assert sends[1:] == [("tool_results", ["submit_answer"], None)]
    [retry] = [fields for category, fields in log_calls if category == "citation_retry"]
    assert retry["calls_made"] == 1
    assert retry["forced"] is False


def test_run_agent_mixed_turn_at_the_budget_edge_retries_and_answers_every_pending_call(monkeypatch):
    # Gemini needs one function response per function call, so the pending
    # search gets a "not run" reply alongside the retry feedback.
    monkeypatch.setattr("sec_agent.agent.agent.MAX_TOOL_ITERATIONS", 1)
    payloads = []
    sends = _install_scripted_backend(
        monkeypatch, _MIXED_TURN, [_submit_turn("The value was 100, fixed.")], payloads=payloads
    )
    _verify_sequence(monkeypatch, [[_BAD], []])
    log_calls = []
    capture_events(monkeypatch, log_calls)

    answer, *_ = run_agent("What was the value?", backend="gemini")

    assert sends[1:] == [("tool_results", ["search_filings", "submit_answer"], "submit_answer")]
    [results] = payloads
    assert results[0]["content"] == FINAL_TURN_SUBMIT_MESSAGE
    assert "bad" in results[1]["content"]
    assert answer == "The value was 100, fixed."
    [retry] = [fields for category, fields in log_calls if category == "citation_retry"]
    assert retry["pending_tools"] == ["search_filings"]


def test_run_agent_tool_call_after_a_forced_mixed_edge_retry_ends_the_run(monkeypatch):
    # The forced retry already sent the "not run" replies, so a tool call
    # after it is a forcing failure: the run ends instead of drawing a
    # forced final turn.
    monkeypatch.setattr("sec_agent.agent.agent.MAX_TOOL_ITERATIONS", 1)
    sends = _install_scripted_backend(monkeypatch, _MIXED_TURN, [_SEARCH_TURN])
    verify_calls = _verify_sequence(monkeypatch, [[_BAD], [_BAD]])

    answer, _, _, withheld_answer, _ = run_agent("What was the value?", backend="gemini")

    assert sends[1:] == [("tool_results", ["search_filings", "submit_answer"], "submit_answer")]
    assert verify_calls == ["The value was 100.", "The value was 100."]
    assert withheld_answer == "The value was 100."


def test_run_agent_tool_call_after_a_retry_past_the_spent_final_turn_regates_the_cached_answer(monkeypatch):
    monkeypatch.setattr("sec_agent.agent.agent.MAX_TOOL_ITERATIONS", 1)
    sends = _install_scripted_backend(monkeypatch, _SEARCH_TURN, [_submit_turn("The value was 100."), _SEARCH_TURN])
    verify_calls = _verify_sequence(monkeypatch, [[_BAD], []])

    answer, *_ = run_agent("What was the value?", backend="gemini")

    assert len(sends) == 3  # start, forced final turn, retry -- nothing after
    assert verify_calls == ["The value was 100.", "The value was 100."]
    assert answer == "The value was 100."


def test_run_agent_tool_call_after_a_forced_retry_ends_the_run(monkeypatch):
    # A bad submit exactly at the budget gets a forced retry; a tool call
    # after it is a forcing failure, so the run ends on the cached answer
    # instead of drawing another forced round trip.
    monkeypatch.setattr("sec_agent.agent.agent.MAX_TOOL_ITERATIONS", 2)
    sends = _install_scripted_backend(monkeypatch, _SEARCH_TURN, [_submit_turn("The value was 100."), _SEARCH_TURN])
    verify_calls = _verify_sequence(monkeypatch, [[_BAD], [_BAD]])

    answer, _, _, withheld_answer, _ = run_agent("What was the value?", backend="gemini")

    assert sends[1:] == [
        ("tool_results", ["search_filings"], None),
        ("tool_results", ["submit_answer"], "submit_answer"),
    ]
    assert verify_calls == ["The value was 100.", "The value was 100."]
    assert withheld_answer == "The value was 100."


def test_run_agent_text_after_a_forced_retry_regates_the_cached_answer_without_a_followup(monkeypatch):
    monkeypatch.setattr("sec_agent.agent.agent.MAX_TOOL_ITERATIONS", 2)
    sends = _install_scripted_backend(
        monkeypatch,
        _SEARCH_TURN,
        [_submit_turn("The value was 100."), ModelTurn(tool_calls=[], text="thinking")],
    )
    verify_calls = _verify_sequence(monkeypatch, [[_BAD], []])

    answer, *_ = run_agent("What was the value?", backend="gemini")

    assert sends[1:] == [
        ("tool_results", ["search_filings"], None),
        ("tool_results", ["submit_answer"], "submit_answer"),
    ]
    assert verify_calls == ["The value was 100.", "The value was 100."]
    assert answer == "The value was 100."


def test_run_agent_never_complying_model_stays_within_max_plus_two_requests(monkeypatch):
    # Worst case: text at the budget draws the forced follow-up, its bad
    # submit draws the forced retry, and a tool call after that ends the run.
    max_iterations = 1
    monkeypatch.setattr("sec_agent.agent.agent.MAX_TOOL_ITERATIONS", max_iterations)
    sends = _install_scripted_backend(
        monkeypatch, ModelTurn(tool_calls=[], text="thinking"), [_submit_turn("The value was 100."), _SEARCH_TURN]
    )
    _verify_sequence(monkeypatch, [[_BAD], [_BAD]])

    _, _, _, withheld_answer, _ = run_agent("What was the value?", backend="gemini")

    assert sends[1:] == [
        ("followup", [], "submit_answer"),
        ("tool_results", ["submit_answer"], "submit_answer"),
    ]
    assert len(sends) == max_iterations + 2
    assert withheld_answer == "The value was 100."


def test_run_agent_rejects_an_unknown_backend_by_name(monkeypatch):
    # e.g. a leftover DEFAULT_BACKEND=ollama in a local .env after that
    # backend was removed -- the error must say which backends exist,
    # not surface as a bare KeyError.
    monkeypatch.setattr("sec_agent.agent.agent.DEFAULT_BACKEND", "ollama")

    with pytest.raises(ValueError, match="'ollama'.*gemini"):
        run_agent("What was Apple's revenue?")


def test_run_agent_backend_default_follows_config(monkeypatch):
    # A caller that omits `backend` must resolve to whatever
    # config.DEFAULT_BACKEND currently is, not a value bound at
    # function-definition time -- a made-up backend name registered in
    # BACKENDS (the one dict agent.py and llm_backends.py share) proves it.
    def fake_start(question, system_prompt, tool_schemas):
        return {}, _submit_turn(answer_text="The value was 100.")

    monkeypatch.setattr("sec_agent.agent.agent.DEFAULT_BACKEND", "totally-custom-backend")
    monkeypatch.setitem(llm_backends.BACKENDS, "totally-custom-backend", _repeating_backend(fake_start))
    monkeypatch.setattr("sec_agent.agent.submission.verify_claims", lambda claims, all_results, question, answer_text: [])

    answer, all_results, warnings, withheld_answer, _ = run_agent("What was the value?")

    assert answer == "The value was 100."


def test_run_agent_does_not_send_withheld_answer_to_the_span(monkeypatch):
    # traced_span() dual-writes to Langfuse when configured; the withheld
    # answer is exactly the text the hard gate decided NOT to trust, so
    # it must never leave the machine via that path -- log_event() (local
    # JSONL only, see tracing.py) is the only place it's allowed to go
    # (see finalize_answer's own tests in test_submission.py).
    final_answer_turn = ModelTurn(tool_calls=[], text="Apple's revenue was $100 billion [1].")

    def fake_start(question, system_prompt, tool_schemas):
        return {}, final_answer_turn

    monkeypatch.setattr("sec_agent.agent.agent.BACKENDS", {"gemini": _repeating_backend(fake_start)})

    captured_outputs = []

    class _FakeSpan:
        def update(self, **kwargs):
            captured_outputs.append(kwargs)

    @contextmanager
    def fake_traced_span(as_type, name, input=None):
        yield _FakeSpan()

    monkeypatch.setattr("sec_agent.agent.agent.traced_span", fake_traced_span)

    answer, all_results, warnings, withheld_answer, _ = run_agent("What was Apple's revenue?", backend="gemini")

    assert withheld_answer == "Apple's revenue was $100 billion [1]."
    assert len(captured_outputs) == 1
    output = captured_outputs[0]["output"]
    assert "Apple's revenue was $100 billion [1]." not in str(output)
    assert output["citation_checks"] == {"no_submission": 1}


# ---------------------------------------------------------------------------
# Uniform submit loop: a failing submit is answered like any tool error for
# as long as _next_turn_mode grants a turn, and a non-submit reply to a
# forced send ends the run.
# ---------------------------------------------------------------------------
_RETRY = ("tool_results", ["submit_answer"], None)
_FORCED_RETRY = ("tool_results", ["submit_answer"], "submit_answer")


def _events(log_calls, category):
    return [fields for name, fields in log_calls if name == category]


def test_run_agent_retries_every_failing_submit_inside_the_budget(monkeypatch):
    sends = _install_scripted_backend(
        monkeypatch,
        _submit_turn("The value was 100."),
        [_submit_turn("The value was 100."), _submit_turn("The value was 100."), _submit_turn("Fixed.")],
    )
    _verify_sequence(monkeypatch, [[_BAD], [_BAD], [_BAD], []])
    log_calls = []
    capture_events(monkeypatch, log_calls)

    answer, *_ = run_agent("What was the value?", backend="gemini", verbose=True)

    assert sends[1:] == [_RETRY, _RETRY, _RETRY]
    assert answer == "Fixed."
    retries = _events(log_calls, "citation_retry")
    assert [r["attempt"] for r in retries] == [1, 2, 3]
    assert [r["forced"] for r in retries] == [False, False, False]
    assert [r["reserve_left"] for r in retries] == [2, 2, 2]


def test_run_agent_spends_both_reserve_turns_on_retries_past_the_budget(monkeypatch):
    monkeypatch.setattr("sec_agent.agent.agent.MAX_TOOL_ITERATIONS", 1)
    sends = _install_scripted_backend(
        monkeypatch, _submit_turn("The value was 100."), [_submit_turn("The value was 100."), _submit_turn("Fixed.")]
    )
    _verify_sequence(monkeypatch, [[_BAD], [_BAD], []])
    log_calls = []
    capture_events(monkeypatch, log_calls)

    answer, *_ = run_agent("What was the value?", backend="gemini")

    assert sends[1:] == [_FORCED_RETRY, _FORCED_RETRY]
    assert answer == "Fixed."
    retries = _events(log_calls, "citation_retry")
    assert [(r["attempt"], r["forced"], r["reserve_left"]) for r in retries] == [(1, True, 1), (2, True, 0)]


def test_run_agent_text_after_an_unforced_retry_gets_another_forced_followup(monkeypatch):
    # The follow-up cap is gone: the retry before the second text reply
    # wasn't forced, so forcing hasn't failed yet.
    text = ModelTurn(tool_calls=[], text="thinking")
    sends = _install_scripted_backend(
        monkeypatch, text, [_submit_turn("The value was 100."), text, _submit_turn("Fixed.")]
    )
    _verify_sequence(monkeypatch, [[_BAD], []])
    log_calls = []
    capture_events(monkeypatch, log_calls)

    answer, *_ = run_agent("What was the value?", backend="gemini", verbose=True)

    assert sends[1:] == [("followup", [], "submit_answer"), _RETRY, ("followup", [], "submit_answer")]
    assert answer == "Fixed."
    forced = _events(log_calls, "final_turn_forced")
    assert [(f["trigger"], f["calls_made"], f["reserve_left"]) for f in forced] == [("text", 1, 2), ("text", 3, 2)]


def test_run_agent_always_failing_submits_stay_within_max_plus_two_requests(monkeypatch):
    max_iterations = 3
    monkeypatch.setattr("sec_agent.agent.agent.MAX_TOOL_ITERATIONS", max_iterations)
    sends = _install_scripted_backend(
        monkeypatch, _submit_turn("Attempt 0."), [_submit_turn(f"Attempt {n}.") for n in range(1, 5)]
    )
    _verify_sequence(monkeypatch, [[_BAD]] * 5)
    log_calls = []
    capture_events(monkeypatch, log_calls)

    _, _, warnings, withheld_answer, _ = run_agent("What was the value?", backend="gemini")

    assert sends[1:] == [_RETRY, _RETRY, _FORCED_RETRY, _FORCED_RETRY]
    assert len(sends) == max_iterations + 2
    assert warnings == ["bad"]
    assert withheld_answer == "Attempt 4."
    [ended] = _events(log_calls, "submit_turns_ended")
    assert ended == {
        "backend": "gemini",
        "calls_made": 5,
        "retries": 4,
        "reserve_left": 0,
        "reason": "no_turn_left",
        "ending": "gate_refused",
    }
    [refused] = _events(log_calls, "citation_gate_refused")
    assert (refused["retries"], refused["retried"]) == (4, True)


@pytest.mark.parametrize(
    ("reply", "ending"),
    [
        (ModelTurn(tool_calls=[], text="thinking"), "no_submission"),
        (_SEARCH_TURN, "budget_message"),
    ],
)
def test_run_agent_non_submit_reply_to_a_forced_send_past_the_budget_ends_the_run(monkeypatch, reply, ending):
    monkeypatch.setattr("sec_agent.agent.agent.MAX_TOOL_ITERATIONS", 1)
    sends = _install_scripted_backend(monkeypatch, _SEARCH_TURN, [reply])
    log_calls = []
    capture_events(monkeypatch, log_calls)

    run_agent("What was the value?", backend="gemini")

    assert sends[1:] == [("tool_results", ["search_filings"], "submit_answer")]
    [ended] = _events(log_calls, "submit_turns_ended")
    assert (ended["reason"], ended["ending"], ended["reserve_left"]) == ("forcing_failed", ending, 1)


def test_run_agent_tool_calls_after_an_in_budget_forced_followup_are_dispatched(monkeypatch):
    # Dispatch budget is left, so a search reply to the forced follow-up is
    # an ordinary turn, not a forcing failure that reports the budget spent.
    text = ModelTurn(tool_calls=[], text="thinking")
    payloads = []
    sends = _install_scripted_backend(
        monkeypatch, text, [_SEARCH_TURN, _submit_turn("The value was 100.")], payloads=payloads
    )
    _verify_sequence(monkeypatch, [[]])
    log_calls = []
    capture_events(monkeypatch, log_calls)

    answer, *_ = run_agent("What was the value?", backend="gemini")

    assert sends[1:] == [("followup", [], "submit_answer"), ("tool_results", ["search_filings"], None)]
    assert payloads == [[{"name": "search_filings", "content": "search result"}]]
    assert answer == "The value was 100."
    assert _events(log_calls, "submit_turns_ended") == []


@pytest.mark.parametrize(
    ("first_turn", "answer", "ending"),
    [
        (ModelTurn(tool_calls=[], text="thinking"), NO_SUBMISSION_REFUSAL, "no_submission"),
        (_SEARCH_TURN, BUDGET_EXHAUSTED_ANSWER, "budget_message"),
    ],
)
def test_run_agent_with_no_reserve_ends_at_the_budget_without_a_send(monkeypatch, first_turn, answer, ending):
    monkeypatch.setattr("sec_agent.agent.agent.MAX_TOOL_ITERATIONS", 1)
    monkeypatch.setattr("sec_agent.agent.agent.SUBMIT_RESERVE", 0)
    sends = _install_scripted_backend(monkeypatch, first_turn, [])
    log_calls = []
    capture_events(monkeypatch, log_calls)

    result = run_agent("What was the value?", backend="gemini")

    assert sends[1:] == []
    assert result.answer == answer
    [ended] = _events(log_calls, "submit_turns_ended")
    assert (ended["reason"], ended["ending"]) == ("no_turn_left", ending)
