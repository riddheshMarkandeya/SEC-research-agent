"""
The submit_answer gate: splits a submission out of a turn, verifies its
claims, and builds the final AgentResult -- the verified answer, or a
refusal with the withheld text -- plus the retry and refusal messages.
"""

from collections import Counter
from typing import NamedTuple

from sec_agent.prompts import agent_messages as msg
from sec_agent.prompts.agent_tools import SUBMIT_TOOL_SCHEMA
from sec_agent.tracing import log_event
from sec_agent.agent.citations import (
    CitationWarning,
    verify_claims,
)
from sec_agent.agent.tool_args import validate_tool_args


# The model answered in text even after a forced submit_answer turn:
# there's no structured submission to verify, so the answer is refused
# rather than trusted unchecked.
NO_SUBMISSION_CITATION_WARNING = CitationWarning(
    check="no_submission",
    citation_index=None,
    value=None,
    unit=None,
    message=msg.NO_SUBMISSION_WARNING,
    quote=None,
)


def _bulleted(warnings: list[str]) -> str:
    """One WARNING_BULLET_TEMPLATE line per warning -- the list format
    shared by both retry messages and the refusal."""
    return "\n".join(msg.WARNING_BULLET_TEMPLATE.format(warning=w) for w in warnings)


def format_claim_retry_message(answer_text: str, warnings: list["CitationWarning"]) -> str:
    """Builds the corrective message for a citation retry after a
    submit_answer call whose claims don't verify. The hard-won wording
    lives in CITATION_RETRY_GUIDANCE (see its own comment for the live
    failure modes each property closes). Delivered as a submit_answer tool RESULT
    (types.Part.from_function_response), not a plain follow-up turn --
    see the loop's own comment for why a dangling function call followed
    by a bare user turn is worth avoiding."""
    return msg.CLAIM_RETRY_TEMPLATE.format(
        warnings_block=_bulleted([w.message for w in warnings]),
        answer_text=answer_text,
        guidance=msg.CITATION_RETRY_GUIDANCE,
    )


def _format_refusal_message(warnings: list[str]) -> str:
    """Hard-gate refusal, returned by finalize_answer() below in place
    of an answer whose citations still don't check out after any
    applicable retry. Implements the project's design principle
    "Every numeric claim must trace to a specific filing + section, or
    the agent refuses" -- this is what actually withholds the answer
    rather than only surfacing warnings next to it."""
    return msg.REFUSAL_TEMPLATE.format(warnings_block=_bulleted(warnings))


def partition_submit_call(tool_calls: list[dict]) -> tuple[dict | None, list[dict]]:
    """Splits one turn's normalized tool_calls into (the submit_answer
    call, if present, else None) and (every OTHER call, in order). Lets
    the loop tell a pure submission from a mixed submit+search turn
    without giving dispatch_tool_call's return type a str|Terminal
    union just to encode "this call ends the conversation" -- the loop
    already knows which call that is from this partition alone.

    At most one call is ever treated as the submission: if a turn somehow
    includes more than one submit_answer call (no real-world reason to,
    but not schema-forbidden), only the FIRST is returned as `submit`;
    any additional ones land in `other`, where the loop's mixed-turn
    handling will tell the model to resubmit once instead of silently
    picking one arbitrarily."""
    submit = None
    other = []
    for call in tool_calls:
        if call["name"] == "submit_answer" and submit is None:
            submit = call
        else:
            other.append(call)
    return submit, other


AgentResult = NamedTuple(
    "AgentResult",
    [
        ("answer", str),  # what a real caller may show a user (the refusal text if the gate fired)
        ("results", list[dict]),
        ("citation_warnings", list[str]),  # unchanged shape/strings -- every existing caller's contract
        ("withheld_answer", str | None),  # the model's actual answer text iff the gate refused it, else None
        ("citation_warning_details", list[dict]),  # [w._asdict() for w in warnings] -- see finalize_answer
    ],
)


def count_citation_checks(warnings: list["CitationWarning"]) -> dict[str, int]:
    """How many warnings each check (`CitationWarning.check`) produced --
    shared by finalize_answer's log event and the gate replay tool's
    comparison, so both count checks the same way."""
    return dict(Counter(w.check for w in warnings))


def submission_warnings(
    args: dict, all_results: list[dict], question: str
) -> tuple[str, list["CitationWarning"]]:
    """The hard gate's verdict on one submit_answer call: its answer
    text and the warnings that would refuse it (empty means it passes).
    Every gate call site goes through here, and so does the offline
    replay, so the replayed verdict can't drift from the live one.

    Schema-invalid args get the same boundary check every other tool
    gets, and they refuse like any other failed claim. The warning's
    value/unit are sentinels (0.0/raw) because it isn't about any one
    numeric claim."""
    if validate_tool_args("submit_answer", SUBMIT_TOOL_SCHEMA, args):
        answer_text = args.get("answer_text") or ""
        return answer_text, [
            CitationWarning(
                check="no_structured_answer",
                citation_index=None,
                value=0.0,
                unit="raw",
                message=msg.SUBMIT_INVALID_ARGS_WARNING,
                quote=None,
            )
        ]
    answer_text = args["answer_text"]
    return answer_text, verify_claims(args["claims"], all_results, question, answer_text)


def finalize_answer(
    answer: str, warnings: list["CitationWarning"], all_results: list[dict], *, backend: str, retries: int
) -> AgentResult:
    """Single choke point for every run_agent() return site: withholds
    `answer` in favor of a refusal (see _format_refusal_message) whenever
    citation warnings remain, so the hard gate can't be bypassed by a
    return site that forgets to check. `citation_warnings` is still
    returned either way, even though the refusal text already embeds
    them inline -- callers other than main() (e.g. eval_harness.py's
    _grade()) use the raw list directly rather than re-parsing it out of
    the answer text.

    `withheld_answer` preserves what the model actually said whenever the gate refuses,
    since re-grading that text against ground truth is the only way to
    tell a correct-but-wrongly-refused answer (a false positive) from a
    genuinely bad one. Also fires a `citation_gate_refused` log event
    (local JSONL only, never Langfuse -- see log_event's own docstring)
    whenever it refuses, since this is the one place a real answer gets
    thrown away. `backend`/`retries` are keyword-only so they can't be
    swapped positionally. The event logs `retries` (citation retries
    sent this run) and also `retried`, the bool older traces carry.

    `citation_warning_details` is populated directly from `warnings`
    here -- NOT re-derived by a second pass elsewhere -- so every
    consumer sees exactly the checks that refused the answer.

    A refusal made only of no_submission warnings gets
    NO_SUBMISSION_REFUSAL instead of REFUSAL_TEMPLATE: nothing was
    submitted, so saying claims failed verification would be false. Mixed
    with any claim warning, the claims wording is the true one."""
    messages = [w.message for w in warnings]
    details = [w._asdict() for w in warnings]
    if not warnings:
        return AgentResult(answer, all_results, messages, None, details)

    log_event(
        "citation_gate_refused",
        backend=backend,
        retried=retries > 0,
        retries=retries,
        n_results=len(all_results),
        checks=count_citation_checks(warnings),
        warnings=messages,
        withheld_answer=answer,
    )
    if all(w.check == NO_SUBMISSION_CITATION_WARNING.check for w in warnings):
        refusal = msg.NO_SUBMISSION_REFUSAL
    else:
        refusal = _format_refusal_message(messages)
    return AgentResult(refusal, all_results, messages, answer, details)
