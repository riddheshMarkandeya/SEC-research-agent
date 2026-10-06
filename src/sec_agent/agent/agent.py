"""
Agent layer: gives the LLM a `search_filings` tool (wrapping
retrieval.hybrid_search) instead of pre-fetching context ourselves, so
the model decides what to search for, which ticker to restrict to (if
any), and whether to search again -- e.g. calling the tool twice, once
per company, for a cross-company comparison question. See
docs/decisions/2026-08-14-agent-v0-tool-calling.md for why this exists
and how tool-calling was verified against the real backend wire format.

Usage:
    python -m sec_agent.agent.agent "How many full-time employees does Apple have?"
    python -m sec_agent.agent.agent "Compare Apple's and Microsoft's effective tax rates." --verbose
"""

import argparse
from collections import Counter
from dataclasses import dataclass
from typing import Any, Literal

from sec_agent.agent.citations import CitationWarning
from sec_agent.agent.dispatch import dispatch_tool_call
from sec_agent.agent.submission import (
    NO_SUBMISSION_CITATION_WARNING,
    AgentResult,
    finalize_answer,
    format_claim_retry_message,
    partition_submit_call,
    submission_warnings,
)
from sec_agent.agent.tool_results import format_citation_key
from sec_agent.config import DEFAULT_BACKEND
from sec_agent.llm.llm_backends import BACKENDS, require_backend
from sec_agent.prompts import agent_messages as msg
from sec_agent.prompts.agent_system import SYSTEM_PROMPT
from sec_agent.prompts.agent_tools import AGENT_TOOL_SCHEMAS
from sec_agent.tracing import flush, log_event, traced_span

MAX_TOOL_ITERATIONS = 6
# Forced, submit-only turns allowed past MAX_TOOL_ITERATIONS, shared by
# every path that needs one: pending tool calls, a text reply, a failed
# submit. Two keeps the worst case at MAX_TOOL_ITERATIONS + 2 requests.
SUBMIT_RESERVE = 2

TurnMode = Literal["free", "forced"]
EndReason = Literal["no_turn_left", "forcing_failed"]
Ending = Literal["gate_refused", "cached", "no_submission", "budget_message"]


def _next_turn_mode(calls_made: int, reserve_left: int) -> TurnMode | None:
    """The one rule for whether the conversation gets another turn: a
    free one while dispatch budget is left, else a forced submit-only one
    while the reserve lasts, else none (the run ends)."""
    if calls_made < MAX_TOOL_ITERATIONS:
        return "free"
    if reserve_left > 0:
        return "forced"
    return None


def run_agent(question: str, backend: str | None = None, verbose: bool = False) -> AgentResult:
    """Thin traced wrapper around _run_agent_impl() -- a single choke
    point for the top-level span (Langfuse when configured, always the
    local JSONL log) regardless of which of _run_agent_impl's several
    internal return paths fires (see its own docstring). Adds no
    behavior change to the returned answer/results/citation_warnings for
    any existing caller/test; the 4th field (AgentResult.withheld_answer)
    is described in finalize_answer's own docstring.

    `backend=None` resolves to config.DEFAULT_BACKEND -- resolved HERE,
    inside the function body, rather than as a literal `= DEFAULT_BACKEND`
    parameter default: a parameter default is evaluated once at
    module-import time, so a literal default would freeze in whatever
    DEFAULT_BACKEND happened to be when agent.py was first imported and
    silently ignore any later change to it.

    `citation_checks` in the span output reads the per-check counts
    straight from `result.citation_warning_details` (AgentResult's 5th
    field) rather than re-deriving them from the answer text, so they
    always name the checks that actually refused it. The withheld answer text itself is never put in this span's
    output -- it goes to finalize_answer's log_event call only, which is
    local-JSONL-only by design (see tracing.log_event's docstring): the
    whole point of withholding it is that it isn't trustworthy, so it
    must not leave the machine via the Langfuse-forwarding path
    traced_span() offers."""
    backend = backend or DEFAULT_BACKEND
    with traced_span("agent", "run_agent", input={"question": question, "backend": backend}) as span:
        result = _run_agent_impl(question, backend, verbose)
        span.update(
            output={
                "answer": result.answer,
                "citation_warnings": result.citation_warnings,
                "citation_checks": dict(Counter(d["check"] for d in result.citation_warning_details)),
                "result_count": len(result.results),
            }
        )
        return result


@dataclass
class _AgentLoopState:
    """Mutable state threaded through _run_agent_impl()'s helpers.

    `calls_made` is written only by the parent loop's increment, once per
    turn it continues with. `reserve_left` is spent only by _take_turn.
    `last_turn_forced` is copied by the parent from each _LoopStep, so it
    reflects the force_tool actually sent, not the turn mode: a text
    follow-up is forced even on a free turn. `retries` counts citation
    retries sent, for logs. `last_submit_args` is the latest failing
    submission's RAW args, re-gated when the run ends without a passing
    one: a pure function of (submit_args, all_results) can't go stale the
    way cached warnings could as all_results grows."""

    calls_made: int
    reserve_left: int
    retries: int = 0
    last_turn_forced: bool = False
    last_submit_args: dict | None = None


def _take_turn(loop_state: _AgentLoopState) -> TurnMode | None:
    """_next_turn_mode for the current state, spending a reserve turn when
    it returns "forced". A free turn is paid for by the parent loop's
    calls_made increment, like every other turn."""
    mode = _next_turn_mode(loop_state.calls_made, loop_state.reserve_left)
    if mode == "forced":
        loop_state.reserve_left -= 1
    return mode


@dataclass(frozen=True)
class _AgentContext:
    """Read-mostly context shared across _run_agent_impl()'s extracted
    helpers below, bundled purely to keep each helper's own signature
    under ruff's PLR0913 threshold -- question/backend/verbose never
    change during a conversation; all_results/searched_tickers are
    mutable but already passed by reference today (mutated in place via
    append/extend/add, never reassigned), so bundling them here doesn't
    change that. conv_state is the backend's own conversation handle;
    send_tool_results/send_followup are the two backend functions used
    to send it a reply -- both obtained once from BACKENDS[backend].
    `frozen=True` (matching citations.CitationWarning/submission.AgentResult
    NamedTuples and table_grounding.py's frozen dataclasses) enforces at
    the type level what the paragraph above already claims: no field is
    ever reassigned after construction -- mutating all_results'/
    searched_tickers' own contents in place is unaffected, since
    freezing a dataclass only blocks reassigning the attribute itself,
    not mutating the mutable object it points to."""

    question: str
    backend: str
    verbose: bool
    all_results: list[dict]
    searched_tickers: set[str | None]
    conv_state: Any
    send_tool_results: Any
    send_followup: Any


@dataclass(frozen=True)
class _LoopStep:
    """Outcome of one _run_agent_impl() loop-body helper: exactly one of
    `next_turn`/`result` is ever set -- the parent continues the loop
    with `next_turn` if set, else returns `result` immediately. `forced`
    says whether the send that produced `next_turn` carried
    force_tool=submit_answer. Named fields instead of a positional tuple
    so a call site can't silently transpose them: a swap wouldn't crash,
    it would return a conversation turn as if it were the AgentResult."""

    next_turn: Any = None
    result: AgentResult | None = None
    forced: bool = False


def _handle_submit_turn(args: dict, other: list[dict], ctx: _AgentContext, loop_state: _AgentLoopState) -> _LoopStep:
    """Body of _run_agent_impl()'s submit-answer branch -- called only
    once its own guard (a pure submission, or a mixed submit+search
    turn with no dispatch budget left) is already true. `other` is that
    mixed turn's non-submit calls (empty for a pure submission). A
    passing submission is the answer. A failing one is answered like any
    tool error, with a citation retry, for as long as _take_turn grants a
    turn; once it doesn't, the submission is refused."""
    with traced_span("tool", "submit_answer", input=args) as span:
        answer_text, warnings = submission_warnings(args, ctx.all_results, ctx.question)
        span.update(output={"warning_count": len(warnings), "checks": [w.check for w in warnings]})
        if warnings:
            loop_state.last_submit_args = args
            retry = _try_citation_retry(answer_text, warnings, other, ctx, loop_state)
            if retry is not None:
                return retry
            _log_turns_ended(ctx, loop_state, reason="no_turn_left", ending="gate_refused")
        result = finalize_answer(
            answer_text, warnings, ctx.all_results, backend=ctx.backend, retries=loop_state.retries
        )
        return _LoopStep(result=result)


def _try_citation_retry(
    answer_text: str,
    warnings: list[CitationWarning],
    other: list[dict],
    ctx: _AgentContext,
    loop_state: _AgentLoopState,
) -> _LoopStep | None:
    """Sends a citation retry's feedback as the submit_answer tool result,
    if _take_turn grants a turn (else None, sending nothing). A reserve
    turn, past the budget, makes the next reply submit_answer only, since
    no search could run. Each pending call of a mixed turn gets a "not
    run" reply ahead of the feedback, since Gemini needs one function
    response per function call."""
    mode = _take_turn(loop_state)
    if mode is None:
        return None
    loop_state.retries += 1
    forced = mode == "forced"
    messages = [w.message for w in warnings]
    pending_tool_names = [c["name"] for c in other]
    log_event(
        "citation_retry",
        backend=ctx.backend,
        warnings=messages,
        calls_made=loop_state.calls_made,
        forced=forced,
        pending_tools=pending_tool_names,
        attempt=loop_state.retries,
        reserve_left=loop_state.reserve_left,
    )
    if ctx.verbose:
        print(f"  [citation retry {loop_state.retries}] {messages}")
    results = _not_run_results(pending_tool_names)
    results.append({"name": "submit_answer", "content": format_claim_retry_message(answer_text, warnings)})
    next_turn = ctx.send_tool_results(ctx.conv_state, results, force_tool="submit_answer" if forced else None)
    return _LoopStep(next_turn=next_turn, forced=forced)


def _not_run_results(tool_names: list[str]) -> list[dict]:
    """A "not run" tool result for each pending call the loop won't
    dispatch, so the reply still carries one function response per call."""
    return [{"name": name, "content": msg.FINAL_TURN_SUBMIT_MESSAGE} for name in tool_names]


def _log_forced_turn(ctx: _AgentContext, loop_state: _AgentLoopState, trigger: str, pending_tools: list[str]) -> None:
    """`final_turn_forced` for every forced non-retry send (local JSONL
    only: loop mechanics, not conversation content). `trigger` names the
    path: "text" for a text reply, "pending_tools" for tool calls past the
    budget. No `question` field: run_agent's span already records it
    under the same run_id."""
    log_event(
        "final_turn_forced",
        backend=ctx.backend,
        calls_made=loop_state.calls_made,
        pending_tools=pending_tools,
        reserve_left=loop_state.reserve_left,
        trigger=trigger,
    )


def _end_before_forcing(turn: Any, ctx: _AgentContext, loop_state: _AgentLoopState) -> _LoopStep | None:
    """The shared prelude of the two handlers that answer a non-submit
    reply with a forced send: ends the run instead when the previous send
    was already forced (forcing didn't work, so forcing again would only
    spend a request) or when _take_turn grants no turn. Tool calls only
    reach it past the budget; in budget they are dispatched. `turn` is
    the text reply, or None for tool calls. Returns None when a turn was
    taken and the caller should send."""
    if loop_state.last_turn_forced:
        return _LoopStep(result=_end_run(turn, ctx, loop_state, reason="forcing_failed"))
    if _take_turn(loop_state) is None:
        return _LoopStep(result=_end_run(turn, ctx, loop_state, reason="no_turn_left"))
    return None


def _handle_no_tool_calls_turn(turn: Any, ctx: _AgentContext, loop_state: _AgentLoopState) -> _LoopStep:
    """Body of _run_agent_impl()'s `not turn.tool_calls` branch -- the
    model replied in text. It gets a forced submit_answer-only follow-up,
    on a free turn or a reserve one, unless _end_before_forcing ends the
    run."""
    if (ended := _end_before_forcing(turn, ctx, loop_state)) is not None:
        return ended
    _log_forced_turn(ctx, loop_state, trigger="text", pending_tools=[])
    if ctx.verbose:
        print("  [forcing submit_answer] model replied in text instead of calling a tool")
    next_turn = ctx.send_followup(ctx.conv_state, msg.FORCE_SUBMIT_MESSAGE, force_tool="submit_answer")
    return _LoopStep(next_turn=next_turn, forced=True)


def _force_final_submit_turn(other: list[dict], ctx: _AgentContext, loop_state: _AgentLoopState) -> _LoopStep:
    """Body of _run_agent_impl()'s tool-calls-past-the-budget branch: the
    model still wants to search, but no dispatch budget is left, so a
    reserve turn forces submit_answer instead. Every pending call (`other`
    is non-empty here) gets a synthetic "not run" result via
    send_tool_results, not send_followup: those calls are already pending
    in the chat history, and a bare followup turn on top of them is the
    "dangling function call followed by a bare user turn" shape that has
    400'd on Gemini. _end_before_forcing may end the run instead."""
    if (ended := _end_before_forcing(None, ctx, loop_state)) is not None:
        return ended
    pending_tool_names = [c["name"] for c in other]
    _log_forced_turn(ctx, loop_state, trigger="pending_tools", pending_tools=pending_tool_names)
    if ctx.verbose:
        print("  [final turn] dispatch budget exhausted with tool calls still pending -- forcing final submit")
    next_turn = ctx.send_tool_results(ctx.conv_state, _not_run_results(pending_tool_names), force_tool="submit_answer")
    return _LoopStep(next_turn=next_turn, forced=True)


def _dispatch_pending_calls(other: list[dict], submit: dict | None, ctx: _AgentContext) -> Any:
    """Body of _run_agent_impl()'s ordinary tool-dispatch fallthrough --
    always returns a new turn. Pure relocation, no logic change."""
    results = [
        {
            "name": c["name"],
            "content": dispatch_tool_call(c, ctx.question, ctx.all_results, ctx.searched_tickers, ctx.verbose),
        }
        for c in other
    ]
    if submit is not None:
        # Mixed turn with budget still remaining: dispatch the
        # searches, but the submission can't be trusted yet -- it
        # can't be grounded in results the model hasn't read.
        results.append({"name": "submit_answer", "content": msg.MIXED_TURN_RESUBMIT_MESSAGE})
    return ctx.send_tool_results(ctx.conv_state, results)


def _log_turns_ended(ctx: _AgentContext, loop_state: _AgentLoopState, reason: EndReason, ending: Ending) -> None:
    """`submit_turns_ended`: the run ended without a passing submission.
    `reason` is "no_turn_left" (budget and reserve spent) or
    "forcing_failed" (a text reply, or tool calls past the budget, after a
    forced send); `ending` is
    how it was finalized: "gate_refused" (the last submission failed),
    "cached" (an earlier failing submission re-gated), "no_submission"
    (a text reply refused) or "budget_message"."""
    log_event(
        "submit_turns_ended",
        backend=ctx.backend,
        calls_made=loop_state.calls_made,
        retries=loop_state.retries,
        reserve_left=loop_state.reserve_left,
        reason=reason,
        ending=ending,
    )


def _end_run(turn: Any, ctx: _AgentContext, loop_state: _AgentLoopState, reason: EndReason) -> AgentResult:
    """Finalizes a run that gets no further turn after a non-submit reply
    (`turn` is that text reply, or None for tool calls). The latest
    failing submission, re-gated against the current all_results, is the
    model's last verifiable answer, since searches after it may have added
    the sources it cites. Without one, a text reply is refused (nothing
    structured to verify) and pending tool calls get the generic
    budget-exhausted answer."""
    ending: Ending
    if loop_state.last_submit_args is not None:
        ending = "cached"
        # The cached args may be the schema-invalid ones that drew the
        # retry, so they go back through the full gate.
        answer, warnings = submission_warnings(loop_state.last_submit_args, ctx.all_results, ctx.question)
    elif turn is not None:
        ending = "no_submission"
        if ctx.verbose:
            print("  [refusing] model replied in text instead of calling submit_answer")
        answer, warnings = turn.text or "", [NO_SUBMISSION_CITATION_WARNING]
    else:
        ending = "budget_message"
        answer, warnings = msg.BUDGET_EXHAUSTED_ANSWER, []
    _log_turns_ended(ctx, loop_state, reason=reason, ending=ending)
    return finalize_answer(answer, warnings, ctx.all_results, backend=ctx.backend, retries=loop_state.retries)


def _run_agent_impl(question: str, backend: str, verbose: bool = False) -> AgentResult:
    """Run the tool-calling loop until the model produces a final answer
    or runs out of turns. `backend` selects which LLM answers (see
    llm_backends.BACKENDS). Returns an AgentResult: the answer text, every
    chunk retrieved across all tool calls (in the same global [n] order the
    model was shown them in, so the printed citation key lines up with the
    model's citations), any citation-verification warnings, and the
    model's withheld answer text whenever the hard gate refused. Every
    return site routes through finalize_answer(), which withholds the
    model's answer in favor of a refusal whenever warnings remain.

    The answer arrives as a `submit_answer` call: claims are structured
    data (value/unit/citation_index/quote) checked by verify_claims()
    instead of regex-parsed out of prose.

    Every extra turn follows one rule (_next_turn_mode): a free turn while
    MAX_TOOL_ITERATIONS budget is left, else a forced submit-only turn
    from the SUBMIT_RESERVE, else none. Each path draws on it the same way:
    - a failing submission gets a citation retry, delivered as the
      submit_answer tool RESULT (a dangling function call followed by a
      bare user turn has 400'd on Gemini);
    - a text reply gets a forced submit_answer follow-up;
    - tool calls past the budget get "not run" results and a forced submit.
    A text reply to a forced send, or tool calls past the budget in reply
    to one, ends the run: forcing didn't work, so forcing again would only
    spend a request. So does running out of turns. Either way _end_run
    re-gates the latest failing submission if there is one.

    Known simplification: no deduplication if two tool calls happen to
    surface the same chunk (e.g. two related queries against the same
    company). Fine for now — a duplicate citation is cosmetic, not a
    correctness problem — but worth revisiting if it gets noisy."""
    require_backend(backend)
    start, send_tool_results, send_followup = BACKENDS[backend]
    conv_state, turn = start(question, SYSTEM_PROMPT, list(AGENT_TOOL_SCHEMAS))
    ctx = _AgentContext(
        question=question,
        backend=backend,
        verbose=verbose,
        all_results=[],
        searched_tickers=set(),
        conv_state=conv_state,
        send_tool_results=send_tool_results,
        send_followup=send_followup,
    )
    loop_state = _AgentLoopState(calls_made=1, reserve_left=SUBMIT_RESERVE)

    while True:
        submit, other = partition_submit_call(turn.tool_calls)

        # A pure submission, OR a mixed submit+search turn with no budget
        # left to dispatch the extra searches: verify what was actually
        # submitted (then retry or finalize) rather than discarding it.
        if submit is not None and (not other or loop_state.calls_made >= MAX_TOOL_ITERATIONS):
            step = _handle_submit_turn(submit["args"], other, ctx, loop_state)
        elif not turn.tool_calls:
            step = _handle_no_tool_calls_turn(turn, ctx, loop_state)
        elif loop_state.calls_made >= MAX_TOOL_ITERATIONS:
            step = _force_final_submit_turn(other, ctx, loop_state)
        else:
            step = _LoopStep(next_turn=_dispatch_pending_calls(other, submit, ctx))

        if step.result is not None:
            return step.result
        turn = step.next_turn
        loop_state.last_turn_forced = step.forced
        loop_state.calls_made += 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question", help="question to answer")
    parser.add_argument(
        "--backend", choices=list(BACKENDS), default=DEFAULT_BACKEND, help="which LLM backend to use"
    )
    parser.add_argument("--verbose", action="store_true", help="print each tool call as it happens")
    args = parser.parse_args()

    result = run_agent(args.question, backend=args.backend, verbose=args.verbose)

    print(f"\nQ: {args.question}\n")
    print(result.answer)
    if result.results:
        print("\nSources:")
        print(format_citation_key(result.results))
    # No separate "Citation warnings:" print block: since the hard gate
    # (finalize_answer), non-empty citation_warnings always
    # means `answer` IS the refusal message, which already lists every
    # warning verbatim -- printing them again here would just repeat
    # the same lines a second time.
    flush()


if __name__ == "__main__":
    main()
