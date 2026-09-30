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
from typing import Any, NamedTuple

from sec_agent.sources.companies import COMPANIES
from sec_agent.config import DEFAULT_BACKEND
from sec_agent.llm.llm_backends import BACKENDS, require_backend
from sec_agent.verification.numeric_utils import (
    normalize,
)
from sec_agent.prompts import agent_messages as msg
from sec_agent.prompts.agent_system import SYSTEM_PROMPT
from sec_agent.prompts.agent_tools import (
    AGENT_TOOL_SCHEMAS,
    CALCULATE_TOOL_SCHEMA,
    CLAIM_UNITS,
    SEARCH_TOOL_SCHEMA,
    SUBMIT_TOOL_SCHEMA,
)
from sec_agent.retrieval.retrieval import hybrid_search
from sec_agent.tracing import flush, log_event, traced_span
from sec_agent.agent.tool_args import (
    _coerce_year_args,
    validate_tool_args,
    _FISCAL_YEAR_PROPS,
)
from sec_agent.agent.tool_results import (
    _format_results_block,
    _format_no_fact_message,
    _format_no_comparison_message,
    _format_citation_key,
)
from sec_agent.agent.citations import (
    _number_candidates,
    CitationWarning,
    _NO_SUBMISSION_WARNING,
    verify_claims,
)
from sec_agent.agent.fact_tools import (
    call_get_financial_fact,
    _with_unit,
    _fact_as_result,
    call_compare_financial_metric,
    _comparison_as_results,
)

MAX_TOOL_ITERATIONS = 6
CHUNKS_PER_SEARCH = 5


def _resolve_search_args(
    args: dict, fallback_query: str, searched_tickers: set[str | None]
) -> tuple[str, str | None]:
    """Extract (query, ticker) from a tool call's arguments.

    The model doesn't always include every schema-declared argument —
    observed in testing: it sometimes calls search_filings with only
    `ticker` and no `query`, despite `query` being marked required.

    The model's own `query` text is only trusted on a *retry* against a
    ticker already searched earlier in this conversation
    (`searched_tickers`) -- a deliberate refinement, not a first guess.
    The first search against each company always uses the original
    question verbatim instead, since the model's own first-pass queries
    are unreliable and no single query-phrasing instruction generalizes
    across companies. See docs/decisions/2026-08-14-agent-v0-tool-calling.md."""
    ticker = args.get("ticker")
    if ticker not in searched_tickers:
        return fallback_query, ticker
    return args.get("query") or fallback_query, ticker


# ---------------------------------------------------------------------------
# calculate tool -- two independent guarantees: operand GROUNDING
# (_ground_operand, reusing _number_candidates -- the same primitive
# _verify_one_claim already trusts for a submit_answer claim) and
# arithmetic CORRECTNESS (call_calculate runs the operation in real
# Python, never the model's own mental math, since LLM arithmetic is
# unreliable even when the model picks the right operation).
# ---------------------------------------------------------------------------
def _ground_operand(
    value: float, unit: str, citation_index: int, all_results: list[dict], operand_name: str
) -> str | None:
    """Checks one calculate operand actually appears in its cited source.
    Returns None if grounded, else a specific, actionable error message
    naming which operand and citation index failed -- the model can
    retry with a corrected value/citation rather than getting a generic
    failure. Reuses _number_candidates() (not _quote_matches -- there's
    no quoted substring here, just a bare operand value) and the same
    tolerance constant (max(0.01*abs(norm), 0.05)) used everywhere else
    in this file.

    On failure, distinguishes three real cases rather than returning one
    generic message for all of them -- a message that blames the wrong
    field sends the model's retry nowhere useful (see
    docs/reviews/2026-09-14-tool-turn-waste.md for the live case that
    motivated computing which correction actually applies, instead of a
    single generic message):
    - MISLABELED UNIT (correctable): the same bare value grounds under a
      DIFFERENT unit than the one claimed, in the SAME cited result --
      says so explicitly, naming the unit that actually matches, since
      that is the one field a generic message never mentions.
    - WRONG CITATION INDEX (correctable): the value grounds under its
      OWN claimed unit in a DIFFERENT already-retrieved result -- says
      so explicitly and names which result, rather than leaving this
      indistinguishable from the terminal case below.
    - GENUINELY UNGROUNDABLE (terminal, not correctable): the value
      grounds under NO unit in the cited result, and does not appear
      under its claimed unit in any OTHER retrieved result either --
      most commonly a literal conversion constant (e.g. dividing by
      1,000,000,000 to convert to billions), which by construction has
      no citation to ground against. Only NOW says explicitly that
      retrying won't help, since both alternatives above have actually
      been checked, not assumed -- this is the ModelRetry-vs-ToolFailed
      distinction (pydantic-ai's terminology) encoded in the message
      text; see CALCULATE_TOOL_SCHEMA's own description and system-
      prompt rule 9 for the actual fix (state a unit-converted value
      directly, no calculate call needed at all)."""
    if not (1 <= citation_index <= len(all_results)):
        return msg.OPERAND_BAD_CITATION_INDEX_TEMPLATE.format(
            operand_name=operand_name, citation_index=citation_index, result_count=len(all_results)
        )
    source_text = all_results[citation_index - 1]["text"]
    category, norm = normalize(value, unit)
    tolerance = max(0.01 * abs(norm), 0.05)
    candidates = _number_candidates(source_text)
    if any(c == category and abs(v - norm) <= tolerance for c, v in candidates):
        return None

    for other_unit in CLAIM_UNITS:
        if other_unit == unit:
            continue
        other_category, other_norm = normalize(value, other_unit)
        other_tolerance = max(0.01 * abs(other_norm), 0.05)
        if any(c == other_category and abs(v - other_norm) <= other_tolerance for c, v in candidates):
            return msg.OPERAND_WRONG_UNIT_TEMPLATE.format(
                operand_name=operand_name,
                value=value,
                unit=unit,
                citation_index=citation_index,
                other_unit=other_unit,
            )

    for other_index, other_result in enumerate(all_results, start=1):
        if other_index == citation_index:
            continue
        other_candidates = _number_candidates(other_result["text"])
        if any(c == category and abs(v - norm) <= tolerance for c, v in other_candidates):
            return msg.OPERAND_WRONG_CITATION_INDEX_TEMPLATE.format(
                operand_name=operand_name,
                value=value,
                unit=unit,
                citation_index=citation_index,
                other_index=other_index,
            )

    return msg.OPERAND_UNGROUNDABLE_TEMPLATE.format(
        operand_name=operand_name, value=value, unit=unit, citation_index=citation_index
    )


def call_calculate(args: dict, all_results: list[dict]) -> tuple[dict | None, str | None]:
    """Runs one calculate tool call: grounds both operands against their
    cited sources, then performs the arithmetic in real Python. Returns
    (result, None) on success, (None, message) on failure -- a richer
    contract than call_get_financial_fact's bare dict|None, because
    calculate has several distinct failure reasons (bad citation index,
    an ungrounded operand, a category mismatch, divide by zero) that each
    need their own specific message, unlike get_financial_fact's single
    generic "not found."

    This is the ONLY way, per system-prompt rule 9, to state a
    hand-computed value at all: a self-computed number with no calculate
    call behind it fails verify_claims's coverage check
    (uncovered_number), and a claim quoting raw inputs for a derived
    value can never pass _verify_one_claim's value-attribution check (it
    requires the claimed VALUE itself to appear inside the quote, not
    just the inputs it was derived from) -- confirmed by tracing the
    actual code, not assumed; see this tool's own design doc.

    Both operands must be the same normalize() category (both "percent"
    or both "scale") -- add/subtract of mismatched categories is
    meaningless, and percent's own scale (a bare number, not a fraction)
    makes multiply/divide against a differently-categorized operand an
    unresolvable ambiguity rather than a real use case worth supporting.
    `add`/`subtract` preserve the shared input category in their result
    unit; `multiply`/`divide` always return "raw" (a ratio or product is
    not itself a percentage, regardless of what was fed into it, and
    `divide` rounds to 2 decimals matching formulas.py's own decimal-ratio
    convention); `percent_of`/`percent_change` always return "percent" by
    definition, rounded to 1 decimal matching formulas.py's
    RatioDefinition(as_percent=True) convention."""
    if validate_tool_args("calculate", CALCULATE_TOOL_SCHEMA, args):
        return None, msg.CALCULATE_INVALID_ARGS_MESSAGE

    operation = args["operation"]
    value_a, unit_a, idx_a = args["operand_a"], args["unit_a"], args["citation_index_a"]
    value_b, unit_b, idx_b = args["operand_b"], args["unit_b"], args["citation_index_b"]

    error = _ground_operand(value_a, unit_a, idx_a, all_results, "operand_a")
    if error:
        return None, error
    error = _ground_operand(value_b, unit_b, idx_b, all_results, "operand_b")
    if error:
        return None, error

    category_a, norm_a = normalize(value_a, unit_a)
    category_b, norm_b = normalize(value_b, unit_b)
    if category_a != category_b:
        return None, msg.CALCULATE_CATEGORY_MISMATCH_TEMPLATE.format(
            operation=operation, category_a=category_a, category_b=category_b
        )

    if operation in ("divide", "percent_of", "percent_change") and norm_b == 0:
        return None, msg.CALCULATE_ZERO_DIVISOR_TEMPLATE.format(operation=operation.replace("_", " "))

    value, unit = _apply_calculate_operation(operation, category_a, norm_a, norm_b)
    return {"value": value, "unit": unit}, None


def _apply_calculate_operation(operation: str, category: str, norm_a: float, norm_b: float) -> tuple[float, str]:
    """The 6-way arithmetic dispatch for call_calculate() -- pure
    relocation (no logic change), extracted to keep the parent's own
    branch count under ruff's C901 threshold. `category` is the shared
    normalize() category both operands were already confirmed to share
    (see call_calculate's own category-mismatch check above) -- only
    needed here to decide add/subtract's result unit."""
    if operation == "add":
        return norm_a + norm_b, ("percent" if category == "percent" else "raw")
    if operation == "subtract":
        return norm_a - norm_b, ("percent" if category == "percent" else "raw")
    if operation == "multiply":
        return norm_a * norm_b, "raw"
    if operation == "divide":
        return round(norm_a / norm_b, 2), "raw"
    if operation == "percent_of":
        return round(norm_a / norm_b * 100, 1), "percent"
    return round((norm_a - norm_b) / norm_b * 100, 1), "percent"  # percent_change


def _format_computed_number(value: float) -> str:
    """Renders a float as plain fixed-point text, never scientific
    notation -- str()'s default formatting switches to "1e+18"-style
    notation outside roughly 1e16..1e-4 (multiply of two billion-scale
    operands reaches this easily: 1e9 * 1e9 = 1e18), but NUMBER_PATTERN
    (numeric_utils.py) has no exponent support at all. A value in that
    range could never be re-extracted from the very citation text this
    module generates, silently defeating the whole point of a citable
    computed result -- guarded by
    test_calculation_as_result_text_avoids_scientific_notation_for_large_values.
    `.6f` gives 6 decimal places of precision (matching this project's
    finest existing rounding, RatioDefinition(as_percent=True)'s 1 decimal
    place, with headroom); trailing zeros and a bare trailing "." are
    stripped for a clean integer-looking value like "150000000" rather
    than "150000000.000000"."""
    text = f"{value:.6f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _calculation_as_result(result: dict, args: dict) -> dict:
    """Wraps a call_calculate() result in the same {text, metadata} shape
    every other all_results entry uses (mirrors _fact_as_result) -- the
    whole design point of this tool is that its output flows through the
    SAME citation/verification machinery unchanged, the same way
    get_financial_fact's yoy_growth output already does. `text` renders
    the full expression so it's directly quotable by
    _quote_matches/_number_candidates, and so the model can copy it into
    answer_text to satisfy the system prompt's disclosure requirement
    (state the computation, not just the bare result) -- proven
    end-to-end, not just asserted, by
    test_calculation_as_result_text_is_directly_quotable_end_to_end.

    metadata uses placeholder values the same way _comparison_as_results
    already does for XBRL-frame-only rows (fact.get("form", "XBRL frame
    data")) -- a pure computation has no filing of its own to attribute."""
    operation = args["operation"]
    value_a, unit_a = _format_computed_number(args["operand_a"]), args["unit_a"]
    value_b, unit_b = _format_computed_number(args["operand_b"]), args["unit_b"]
    idx_a, idx_b = args["citation_index_a"], args["citation_index_b"]

    if operation == "percent_change":
        expression_template = msg.CALCULATION_PERCENT_CHANGE_EXPRESSION
    elif operation == "percent_of":
        expression_template = msg.CALCULATION_PERCENT_OF_EXPRESSION
    else:
        expression_template = msg.CALCULATION_BINARY_EXPRESSION
    expression = expression_template.format(
        value_a=value_a, unit_a=unit_a, value_b=value_b, unit_b=unit_b, operation=operation
    )

    formatted_value = _with_unit(_format_computed_number(result["value"]), result["unit"])
    return {
        "text": msg.CALCULATION_RESULT_TEMPLATE.format(
            expression=expression, value=formatted_value, idx_a=idx_a, idx_b=idx_b
        ),
        "metadata": {
            "ticker": msg.CALCULATION_PLACEHOLDER,
            "form": msg.CALCULATION_FORM,
            "filingDate": msg.CALCULATION_PLACEHOLDER,
            "reportDate": msg.CALCULATION_PLACEHOLDER,
            "accessionNumber": msg.CALCULATION_PLACEHOLDER,
            "chunk_index": "calculated",
        },
    }


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


def _bulleted(warnings: list[str]) -> str:
    """One WARNING_BULLET_TEMPLATE line per warning -- the list format
    shared by both retry messages and the refusal."""
    return "\n".join(msg.WARNING_BULLET_TEMPLATE.format(warning=w) for w in warnings)


def _format_claim_retry_message(answer_text: str, warnings: list["CitationWarning"]) -> str:
    """Builds the corrective message for the one-time retry after a
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
    """Hard-gate refusal, returned by _finalize_answer() below in place
    of an answer whose citations still don't check out after any
    applicable retry. Implements the project's design principle
    "Every numeric claim must trace to a specific filing + section, or
    the agent refuses" -- this is what actually withholds the answer
    rather than only surfacing warnings next to it."""
    return msg.REFUSAL_TEMPLATE.format(warnings_block=_bulleted(warnings))


def _partition_submit_call(tool_calls: list[dict]) -> tuple[dict | None, list[dict]]:
    """Splits one turn's normalized tool_calls into (the submit_answer
    call, if present, else None) and (every OTHER call, in order). Lets
    the loop tell a pure submission from a mixed submit+search turn
    without giving _dispatch_tool_call's return type a str|Terminal
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
        ("citation_warning_details", list[dict]),  # [w._asdict() for w in warnings] -- see _finalize_answer
    ],
)


def _count_citation_checks(warnings: list["CitationWarning"]) -> dict[str, int]:
    """How many warnings each check (`CitationWarning.check`) produced --
    shared by _finalize_answer's log event and run_agent's span output
    below so the two don't independently hand-roll the same accumulation
    loop."""
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


def _finalize_answer(
    answer: str, warnings: list["CitationWarning"], all_results: list[dict], *, backend: str, retried: bool
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
    thrown away. `backend`/`retried` are keyword-only so the two flags
    can't be swapped positionally.

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
        retried=retried,
        n_results=len(all_results),
        checks=_count_citation_checks(warnings),
        warnings=messages,
        withheld_answer=answer,
    )
    if all(w.check == _NO_SUBMISSION_WARNING.check for w in warnings):
        refusal = msg.NO_SUBMISSION_REFUSAL
    else:
        refusal = _format_refusal_message(messages)
    return AgentResult(refusal, all_results, messages, answer, details)


def _dispatch_tool_call(
    call: dict, question: str, all_results: list[dict], searched_tickers: set[str | None], verbose: bool
) -> str:
    """Runs one normalized tool call ({"name", "args"} -- the
    ModelTurn.tool_calls shape from llm_backends.py) against the right
    tool, mutating all_results/searched_tickers in place, and returns
    the content string to send back to the model. Backend-agnostic by
    construction: it only ever sees the normalized shape, never a
    backend's raw wire format, so the boundary validation inside
    call_get_financial_fact/call_compare_financial_metric (e.g.
    rejecting an invented `segment` argument) protects every backend
    without a second copy."""
    name, args = call["name"], call["args"]

    if name == "get_financial_fact":
        return _dispatch_get_financial_fact(name, args, question, all_results, verbose)
    if name == "compare_financial_metric":
        return _dispatch_compare_financial_metric(name, args, question, all_results, verbose)
    if name == "calculate":
        return _dispatch_calculate(name, args, all_results, verbose)
    return _dispatch_search_filings(call, question, all_results, searched_tickers, verbose)


def _dispatch_get_financial_fact(name: str, args: dict, question: str, all_results: list[dict], verbose: bool) -> str:
    """get_financial_fact branch body of _dispatch_tool_call() -- pure
    relocation (no logic change), extracted to keep the parent's own
    branch/return count under ruff's C901/PLR0911 thresholds. Takes
    `name`/`args` directly (the parent already has both split out) --
    at 5 params this doesn't need the whole-`call`-dict trick
    _dispatch_search_filings below uses, since that one alone needs a
    6th param (searched_tickers)."""
    if verbose:
        print(f"  [tool call] get_financial_fact({args!r})")
    with traced_span("tool", name, input=args) as span:
        # Converted here too, not only inside call_get_financial_fact, so
        # the no-data reply names the year the lookup actually used.
        args = _coerce_year_args(name, args, _FISCAL_YEAR_PROPS)
        fact = call_get_financial_fact(args, question=question)
        if fact is None:
            span.update(output={"found": False})
            return _format_no_fact_message(args)
        start_index = len(all_results) + 1
        result = _fact_as_result(fact, args)
        all_results.append(result)
        span.update(output={"found": True, "value": fact.get("value")})
        return _format_results_block([result], start_index)


def _dispatch_compare_financial_metric(
    name: str, args: dict, question: str, all_results: list[dict], verbose: bool
) -> str:
    """compare_financial_metric branch body of _dispatch_tool_call() --
    same reasoning as _dispatch_get_financial_fact() above."""
    if verbose:
        print(f"  [tool call] compare_financial_metric({args!r})")
    with traced_span("tool", name, input=args) as span:
        data = call_compare_financial_metric(args, question=question)
        if not data:
            span.update(output={"found": False})
            return _format_no_comparison_message(args)
        start_index = len(all_results) + 1
        results = _comparison_as_results(data, args.get("metric", ""))
        all_results.extend(results)
        span.update(output={"found": True, "companies": sorted(data)})
        return _format_results_block(results, start_index)


def _dispatch_calculate(name: str, args: dict, all_results: list[dict], verbose: bool) -> str:
    """calculate branch body of _dispatch_tool_call() -- same reasoning
    as _dispatch_get_financial_fact() above."""
    if verbose:
        print(f"  [tool call] calculate({args!r})")
    with traced_span("tool", name, input=args) as span:
        calc_result, error = call_calculate(args, all_results)
        if calc_result is None:
            assert error is not None  # call_calculate's contract: exactly one of the two is None
            span.update(output={"found": False, "error": error})
            return error
        start_index = len(all_results) + 1
        result = _calculation_as_result(calc_result, args)
        all_results.append(result)
        span.update(output={"found": True, "value": calc_result.get("value")})
        return _format_results_block([result], start_index)


def _dispatch_search_filings(
    call: dict, question: str, all_results: list[dict], searched_tickers: set[str | None], verbose: bool
) -> str:
    """search_filings branch body of _dispatch_tool_call() -- same
    reasoning as _dispatch_get_financial_fact() above; also absorbs the
    validate_tool_args/ticker-rejection guard this branch runs first.
    Unlike its three siblings, takes the whole `call` dict rather than
    `name`/`args` split out -- this branch alone needs `searched_tickers`
    too, which would put a split signature at 6 positional args, over
    PLR0913's threshold.

    soft_required={"query"}: query is schema-required (encourages the
    model to include it), but _resolve_search_args below tolerates it
    being absent by substituting the original question -- observed
    live, not a bug (see that function's own docstring) -- so a
    missing query must not be a hard rejection here.

    Checked BEFORE _resolve_search_args() runs, not after -- that
    function's own `ticker not in searched_tickers` (a set) would
    crash on a non-hashable ticker like a list, the exact unhashable-
    ticker crash class validate_tool_args is safe against (jsonschema's
    type/enum checks use plain equality, never hashing the instance)."""
    name, args = call["name"], call["args"]
    if validate_tool_args("search_filings", SEARCH_TOOL_SCHEMA, args, soft_required=frozenset({"query"})):
        raw_ticker = args.get("ticker")
        if raw_ticker is not None and (not isinstance(raw_ticker, str) or raw_ticker not in COMPANIES):
            # A hallucinated ticker gets its own actionable message
            # (names the bad value, lists valid ones) rather than a
            # generic one -- unlike get_financial_fact/
            # compare_financial_metric's boundary rejections, this is
            # the one case validate_tool_args's caller has enough
            # schema/enum context in hand to do that cheaply.
            return msg.SEARCH_INVALID_TICKER_TEMPLATE.format(ticker=raw_ticker, valid_tickers=sorted(COMPANIES))
        return msg.SEARCH_INVALID_ARGS_MESSAGE
    query, ticker = _resolve_search_args(args, fallback_query=question, searched_tickers=searched_tickers)
    searched_tickers.add(ticker)
    if verbose:
        print(f"  [tool call] search_filings(query={query!r}, ticker={ticker!r})")
    with traced_span("tool", name, input={"query": query, "ticker": ticker}) as span:
        content, result_count = run_search(query, ticker, all_results)
        span.update(output={"result_count": result_count})
        return content


def run_search(query: str, ticker: str | None, all_results: list[dict]) -> tuple[str, int]:
    """Runs one already-validated, already-resolved search, appends its
    chunks to `all_results`, and returns the content block the model
    receives plus the chunk count. Public so an offline replay of a
    traced run, which has only the resolved query/ticker, rebuilds
    exactly what the live dispatch built."""
    results = hybrid_search(query, ticker=ticker, top_k=CHUNKS_PER_SEARCH)
    start_index = len(all_results) + 1
    all_results.extend(results)
    return _format_results_block(results, start_index), len(results)


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
