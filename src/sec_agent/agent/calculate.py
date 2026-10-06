"""
The calculate tool: grounds each operand in its cited source, runs the
arithmetic in Python, and returns a result entry the model can cite like
any other source.
"""

from sec_agent.verification.numeric_utils import normalize
from sec_agent.prompts import agent_messages as msg
from sec_agent.prompts.agent_tools import CALCULATE_TOOL_SCHEMA, CLAIM_UNITS
from sec_agent.agent.citations import number_candidates
from sec_agent.agent.tool_results import with_unit
from sec_agent.agent.tool_args import validate_tool_args


# ---------------------------------------------------------------------------
# calculate tool -- two independent guarantees: operand GROUNDING
# (_ground_operand, reusing number_candidates -- the same primitive
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
    failure. Reuses number_candidates() (not _quote_matches -- there's
    no quoted substring here, just a bare operand value) and the same
    tolerance constant (max(0.01*abs(norm), 0.05)) used by citations.py's
    claim checks.

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
    candidates = number_candidates(source_text)
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
        other_candidates = number_candidates(other_result["text"])
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


def calculation_as_result(result: dict, args: dict) -> dict:
    """Wraps a call_calculate() result in the same {text, metadata} shape
    every other all_results entry uses (mirrors fact_as_result) -- the
    whole design point of this tool is that its output flows through the
    SAME citation/verification machinery unchanged, the same way
    get_financial_fact's yoy_growth output already does. `text` renders
    the full expression so it's directly quotable by
    _quote_matches/number_candidates, and so the model can copy it into
    answer_text to satisfy the system prompt's disclosure requirement
    (state the computation, not just the bare result) -- proven
    end-to-end, not just asserted, by
    test_calculation_as_result_text_is_directly_quotable_end_to_end.

    metadata uses placeholder values the same way comparison_as_results
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

    formatted_value = with_unit(_format_computed_number(result["value"]), result["unit"])
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
