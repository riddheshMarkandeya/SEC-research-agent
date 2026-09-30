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
from typing import Any

from sec_agent.agent.citations import _NO_SUBMISSION_WARNING
from sec_agent.agent.dispatch import _dispatch_tool_call
from sec_agent.agent.submission import (
    AgentResult,
    _finalize_answer,
    _format_claim_retry_message,
    _partition_submit_call,
    submission_warnings,
)
from sec_agent.agent.tool_results import _format_citation_key
from sec_agent.config import DEFAULT_BACKEND
from sec_agent.llm.llm_backends import BACKENDS, require_backend
from sec_agent.prompts import agent_messages as msg
from sec_agent.prompts.agent_system import SYSTEM_PROMPT
from sec_agent.prompts.agent_tools import AGENT_TOOL_SCHEMAS
from sec_agent.tracing import flush, log_event, traced_span

MAX_TOOL_ITERATIONS = 6


def _should_retry_for_citations(citation_warnings: list[str], already_retried: bool) -> bool:
    """Whether run_agent() should give the model one corrective retry
    turn for its own unverified citation(s). True only when there's
    something to correct, the single retry (see
    _format_claim_retry_message below) hasn't already been spent this
    conversation -- capped at one retry, sharing run_agent()'s existing
    MAX_TOOL_ITERATIONS budget rather than a separate one."""
    return bool(citation_warnings) and not already_retried


def _should_force_final_submit(already_attempted: bool, calls_made: int) -> bool:
    """Whether run_agent() should spend its one reserved, submit-only
    final round trip: the dispatch budget is exhausted and the reserve
    is unspent. Two paths draw on it -- pending tool calls (answered with
    a synthetic "not run" result) and a text reply (a forced follow-up)
    -- and either way the next turn is forced to submit_answer, never a
    real dispatch call, so this is NOT a MAX_TOOL_ITERATIONS increase.
    Capped at one shot per conversation via already_attempted."""
    return not already_attempted and calls_made >= MAX_TOOL_ITERATIONS


def run_agent(question: str, backend: str | None = None, verbose: bool = False) -> AgentResult:
    """Thin traced wrapper around _run_agent_impl() -- a single choke
    point for the top-level span (Langfuse when configured, always the
    local JSONL log) regardless of which of _run_agent_impl's several
    internal return paths fires (see its own docstring). Adds no
    behavior change to the returned answer/results/citation_warnings for
    any existing caller/test; the 4th field (AgentResult.withheld_answer)
    is described in _finalize_answer's own docstring.

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
    output -- it goes to _finalize_answer's log_event call only, which is
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
    """Mutable state threaded through _run_agent_impl()'s extracted
    helper functions below, in place of loose locals ping-ponging
    through each one's own signature. Per-field write ownership (so a
    future reader can see at a glance which helper may touch what):
    `calls_made` is written only by the parent loop's own central
    increment (once per iteration, whenever a helper hands back a new
    turn to continue with) -- no helper increments it itself.
    `forced_submit_attempted`/`pre_retry_submit_args`/
    `retried_for_citations` are each written by exactly one owning
    helper. `final_turn_attempted` is the one reserved final round trip,
    shared by two writers: _force_final_submit_turn (pending tool calls)
    and _handle_no_tool_calls_turn (a text reply), so whichever spends it
    first leaves none for the other.

    `pre_retry_submit_args` deliberately caches the RAW submit_answer
    args rather than pre-computed warnings: a pure function of
    (submit_args, all_results) can't go stale the way a cached warnings
    list could if all_results grows further before the budget runs out."""

    calls_made: int
    retried_for_citations: bool = False
    forced_submit_attempted: bool = False
    final_turn_attempted: bool = False
    pre_retry_submit_args: dict | None = None


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
    `frozen=True` (matching this file's own CitationWarning/AgentResult
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
    """Outcome of one _run_agent_impl() loop-body helper (currently
    _handle_submit_turn/_handle_no_tool_calls_turn): exactly one of
    `next_turn`/`result` is ever set -- the parent continues the loop
    with `next_turn` if set, else returns `result` immediately. Named
    fields instead of a positional `tuple[Any, AgentResult | None]`
    (an earlier version of this refactor used that shape) specifically
    so a future call site can't silently transpose the two -- code
    review flagged that a positional swap wouldn't even crash (`turn`
    is never `None` on the continue path, so `if result is not None`
    firing on every call after a swap would just silently return a
    conversation-turn object as if it were the final AgentResult)."""

    next_turn: Any = None
    result: AgentResult | None = None


def _handle_submit_turn(args: dict, ctx: _AgentContext, loop_state: _AgentLoopState) -> _LoopStep:
    """Body of _run_agent_impl()'s submit-answer branch -- called only
    once its own guard (a pure submission, or a mixed submit+search
    turn on the last allowed round trip) is already true, at which
    point the real code always either continues or returns, never
    falls through to a later check. Pure relocation, no logic change.
    Exactly one of the two return values is ever non-None."""
    with traced_span("tool", "submit_answer", input=args) as span:
        answer_text, warnings = submission_warnings(args, ctx.all_results, ctx.question)
        messages = [w.message for w in warnings]
        span.update(output={"warning_count": len(warnings), "checks": [w.check for w in warnings]})
        if (
            _should_retry_for_citations(messages, loop_state.retried_for_citations)
            and loop_state.calls_made < MAX_TOOL_ITERATIONS
        ):
            loop_state.retried_for_citations = True
            loop_state.pre_retry_submit_args = args
            log_event("citation_retry", backend=ctx.backend, warnings=messages)
            if ctx.verbose:
                print(f"  [citation retry] {messages}")
            feedback = _format_claim_retry_message(answer_text, warnings)
            turn = ctx.send_tool_results(ctx.conv_state, [{"name": "submit_answer", "content": feedback}])
            return _LoopStep(next_turn=turn)
        result = _finalize_answer(
            answer_text, warnings, ctx.all_results, backend=ctx.backend, retried=loop_state.retried_for_citations
        )
        return _LoopStep(result=result)


def _handle_no_tool_calls_turn(turn: Any, ctx: _AgentContext, loop_state: _AgentLoopState) -> _LoopStep:
    """Body of _run_agent_impl()'s `not turn.tool_calls` branch -- the
    model replied in text. The first time it gets one forced
    submit_answer-only follow-up, paid for by the dispatch budget or, once
    that's spent, by the one reserved final round trip -- the same reserve
    a pending tool call would get. After that there's nothing structured
    to verify: a submission cached by an earlier retry is re-gated as the
    model's last verifiable answer, otherwise the text is refused
    (_NO_SUBMISSION_WARNING). Exactly one of _LoopStep's two fields is
    ever set."""
    has_budget = loop_state.calls_made < MAX_TOOL_ITERATIONS
    if not loop_state.forced_submit_attempted and (
        has_budget or _should_force_final_submit(loop_state.final_turn_attempted, loop_state.calls_made)
    ):
        loop_state.forced_submit_attempted = True
        if not has_budget:
            loop_state.final_turn_attempted = True
            log_event("final_turn_forced", backend=ctx.backend, calls_made=loop_state.calls_made, pending_tools=[])
        if ctx.verbose:
            print("  [forcing submit_answer] model replied in text instead of calling a tool")
        turn = ctx.send_followup(ctx.conv_state, msg.FORCE_SUBMIT_MESSAGE, force_tool="submit_answer")
        return _LoopStep(next_turn=turn)
    cached = _finalize_cached_submission(ctx, loop_state)
    if cached is not None:
        return _LoopStep(result=cached)
    if ctx.verbose:
        print("  [refusing] model replied in text instead of calling submit_answer")
    result = _finalize_answer(
        turn.text or "",
        [_NO_SUBMISSION_WARNING],
        ctx.all_results,
        backend=ctx.backend,
        retried=loop_state.retried_for_citations,
    )
    return _LoopStep(result=result)


def _force_final_submit_turn(other: list[dict], ctx: _AgentContext, loop_state: _AgentLoopState) -> Any:
    """Body of _run_agent_impl()'s reserved, submit-only final round
    trip (BACKLOG.md's MAX_TOOL_ITERATIONS zero-slack bug) -- called
    only after the parent has already confirmed via
    _should_force_final_submit() that this turn IS being forced, so it
    always returns a new turn, never None, never a break. `other` is
    guaranteed non-empty here (an empty-tool-calls turn is already fully
    handled by the parent's own `if not turn.tool_calls:` branch), so
    every pending call gets answered with a synthetic "not run" result --
    via send_tool_results, not send_followup, since those calls are
    already recorded as pending/unanswered in the chat history and a
    bare followup turn on top of them is exactly the "dangling function
    call followed by a bare user turn" shape that's historically 400'd
    on Gemini (see _run_agent_impl's own docstring). force_tool
    hard-constrains the model's NEXT reply to submit_answer.

    Fires a `final_turn_forced` log event (local JSONL only, mirroring
    `_finalize_answer`'s `citation_gate_refused` -- diagnostic loop
    mechanics, not conversation content) whenever this safety net
    engages, since that was previously only visible under --verbose or
    inferable by counting trace spans. No `question` field: log_event()
    already tags every call with the current run's run_id, and
    run_agent()'s own outermost span already records the question under
    that same run_id, so repeating it here would just duplicate data
    already joinable through run_id."""
    loop_state.final_turn_attempted = True
    if ctx.verbose:
        print("  [final turn] dispatch budget exhausted with tool calls still pending -- forcing final submit")
    pending_tool_names = [c["name"] for c in other]
    log_event(
        "final_turn_forced",
        backend=ctx.backend,
        calls_made=loop_state.calls_made,
        pending_tools=pending_tool_names,
    )
    results = [{"name": name, "content": msg.FINAL_TURN_SUBMIT_MESSAGE} for name in pending_tool_names]
    return ctx.send_tool_results(ctx.conv_state, results, force_tool="submit_answer")


def _dispatch_pending_calls(other: list[dict], submit: dict | None, ctx: _AgentContext) -> Any:
    """Body of _run_agent_impl()'s ordinary tool-dispatch fallthrough --
    always returns a new turn. Pure relocation, no logic change."""
    results = [
        {
            "name": c["name"],
            "content": _dispatch_tool_call(c, ctx.question, ctx.all_results, ctx.searched_tickers, ctx.verbose),
        }
        for c in other
    ]
    if submit is not None:
        # Mixed turn with budget still remaining: dispatch the
        # searches, but the submission can't be trusted yet -- it
        # can't be grounded in results the model hasn't read.
        results.append({"name": "submit_answer", "content": msg.MIXED_TURN_RESUBMIT_MESSAGE})
    return ctx.send_tool_results(ctx.conv_state, results)


def _finalize_cached_submission(ctx: _AgentContext, loop_state: _AgentLoopState) -> AgentResult | None:
    """Re-gates the submission cached at retry time, if any (else None),
    against the run's current all_results, since searches after the retry
    may have added the sources it cites. The cached args may be the
    schema-invalid ones that triggered the retry, so they go back through
    the full gate, not straight to verify_claims."""
    if loop_state.pre_retry_submit_args is None:
        return None
    answer_text, warnings = submission_warnings(loop_state.pre_retry_submit_args, ctx.all_results, ctx.question)
    return _finalize_answer(
        answer_text, warnings, ctx.all_results, backend=ctx.backend, retried=loop_state.retried_for_citations
    )


def _finalize_after_budget_exhausted(ctx: _AgentContext, loop_state: _AgentLoopState) -> AgentResult:
    """Body of _run_agent_impl()'s post-loop fallback -- called once,
    after the while loop's own `break` exits it."""
    cached = _finalize_cached_submission(ctx, loop_state)
    if cached is not None:
        return cached
    return _finalize_answer(
        msg.BUDGET_EXHAUSTED_ANSWER,
        [],
        ctx.all_results,
        backend=ctx.backend,
        retried=loop_state.retried_for_citations,
    )


def _run_agent_impl(question: str, backend: str, verbose: bool = False) -> AgentResult:
    """Run the tool-calling loop until the model produces a final answer
    (no more tool calls) or MAX_TOOL_ITERATIONS is hit. `backend`
    selects which LLM answers (see llm_backends.BACKENDS) -- the loop
    itself, and every tool-dispatch branch inside _dispatch_tool_call,
    is identical regardless of which one is chosen. Returns an
    AgentResult: the answer text, every chunk retrieved across all tool
    calls (in the same global [n] order the model was shown them in —
    this is what lets the printed citation key line up with the model's
    citations), any citation-verification warnings, and the model's
    actual withheld answer text whenever the hard gate refused. Every
    return site routes through _finalize_answer(), which withholds the
    model's actual answer text in favor of a refusal whenever those
    warnings are non-empty.

    A final answer arrives one of two ways:

    - `submit_answer` (SUBMIT_TOOL_SCHEMA), the preferred path: claims
      are structured data (value/unit/citation_index/quote), verified by
      verify_claims() -- fuzzy quote grounding, value attribution, and a
      coverage cross-check -- instead of regex-parsed out of prose.
      Offered as a 4th tool alongside the other 3 from turn 1, under AUTO
      mode.
    - Plain text: a text reply first triggers ONE forced
      ANY+submit_answer-only follow-up turn (using the reserved final
      round trip if the budget is spent). Text again after that is
      refused, since there's no structured claim to verify -- see
      _handle_no_tool_calls_turn.

    Known simplification: no deduplication if two tool calls happen to
    surface the same chunk (e.g. two related queries against the same
    company). Fine for now — a duplicate citation is cosmetic, not a
    correctness problem — but worth revisiting if it gets noisy.

    One self-correction retry on unverified claims
    (retried_for_citations caps the conversation at one), sharing the
    MAX_TOOL_ITERATIONS budget. It delivers its feedback as a
    submit_answer tool RESULT instead of
    a plain follow-up turn -- keeps the chat history well-formed (a
    dangling function call followed by a bare user turn has historically
    400'd on Gemini) and needs no new plumbing, since it's exactly what
    send_tool_results already does."""
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
    loop_state = _AgentLoopState(calls_made=1)

    while True:
        submit, other = _partition_submit_call(turn.tool_calls)

        # A pure submission, OR a mixed submit+search turn that arrived
        # on the LAST allowed round trip: no budget left to dispatch the
        # extra searches and get a real resubmission back, so verify what
        # was actually submitted rather than discarding it below for the
        # generic timeout message.
        if submit is not None and (not other or loop_state.calls_made >= MAX_TOOL_ITERATIONS):
            step = _handle_submit_turn(submit["args"], ctx, loop_state)
            if step.result is not None:
                return step.result
            turn = step.next_turn
            loop_state.calls_made += 1
            continue

        if not turn.tool_calls:
            step = _handle_no_tool_calls_turn(turn, ctx, loop_state)
            if step.result is not None:
                return step.result
            turn = step.next_turn
            loop_state.calls_made += 1
            continue

        if loop_state.calls_made >= MAX_TOOL_ITERATIONS:
            if not _should_force_final_submit(loop_state.final_turn_attempted, loop_state.calls_made):
                break
            turn = _force_final_submit_turn(other, ctx, loop_state)
            loop_state.calls_made += 1
            continue

        turn = _dispatch_pending_calls(other, submit, ctx)
        loop_state.calls_made += 1

    return _finalize_after_budget_exhausted(ctx, loop_state)


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
        print(_format_citation_key(result.results))
    # No separate "Citation warnings:" print block: since the hard gate
    # (_finalize_answer), non-empty citation_warnings always
    # means `answer` IS the refusal message, which already lists every
    # warning verbatim -- printing them again here would just repeat
    # the same lines a second time.
    flush()


if __name__ == "__main__":
    main()
