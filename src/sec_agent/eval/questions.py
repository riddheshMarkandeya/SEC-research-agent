"""
The eval question-file schema, checked when the harness loads a file so a
malformed question fails before any quota is spent rather than mid-run.

Both suites share one schema. v1 questions (eval/eval_questions.jsonl)
carry no tags; a v2 question carries all five tags (category, steps,
answer_source, trap, needs_calculate), which the per-category report
reads. The schema is closed, so a misspelt key is an error rather than a
silently ignored field.
"""

import jsonschema
from jsonschema.exceptions import best_match

from sec_agent.eval.grading import entry_companies
from sec_agent.prompts.agent_tools import CLAIM_UNITS
from sec_agent.sources.companies import COMPANIES
from sec_agent.verification.numeric_utils import match_tolerance, normalize

CATEGORIES = (
    "extraction",
    "numerical-reasoning",
    "cross-period",
    "cross-company",
    "text-footnote",
    "refusal-trap",
    "ambiguous",
)
TRAPS = ("none", "look-alike", "fiscal-label", "false-premise", "not-disclosed", "out-of-corpus", "future-period")
REFUSAL_KINDS = ("not_covered", "not_yet_filed", "never_disclosed", "false_premise")
V2_TAGS = ("category", "steps", "answer_source", "trap", "needs_calculate")
# The `calculate` tool's operations: a derivation records the steps a
# correct answer takes with it, so the authoring check can redo them.
DERIVATION_OPERATIONS = ("add", "subtract", "multiply", "divide", "percent_of", "percent_change")

# A unit outside the claim enum could never match a claim, so a typo in
# a trap's unit would silently disable the trap.
_UNIT = {"enum": CLAIM_UNITS}
_DERIVATION_REF = {"$ref": "#/$defs/derivation"}
_DERIVATION_INPUT = {
    "oneOf": [
        # A figure printed in a filing; `part` names its gold rows.
        {
            "type": "object",
            "properties": {"value": {"type": "number"}, "unit": _UNIT, "part": {"type": "string", "minLength": 1}},
            "required": ["value", "unit", "part"],
            "additionalProperties": False,
        },
        # A number no filing prints, such as the 2 of an average.
        {
            "type": "object",
            "properties": {"value": {"type": "number"}, "unit": _UNIT, "constant": {"const": True}},
            "required": ["value", "unit", "constant"],
            "additionalProperties": False,
        },
        # An earlier step of a compound chain.
        {
            "type": "object",
            "properties": {"derivation": _DERIVATION_REF},
            "required": ["derivation"],
            "additionalProperties": False,
        },
    ]
}
# One `calculate` call, operands in the tool's operand_a/operand_b order.
_DERIVATION = {
    "type": "object",
    "properties": {"operation": {"enum": list(DERIVATION_OPERATIONS)}, "a": _DERIVATION_INPUT, "b": _DERIVATION_INPUT},
    "required": ["operation", "a", "b"],
    "additionalProperties": False,
}

_VALUE = {
    "type": "object",
    "properties": {
        # A label; it names the entry's company only when it is exactly a ticker.
        "ticker": {"type": "string"},
        # The companies a claim of this value must come from, when the
        # label isn't one ticker: ["JPM", "BAC"] for a gap between them.
        "companies": {"type": "array", "items": {"enum": sorted(COMPANIES)}, "minItems": 1, "uniqueItems": True},
        "expected_value": {"type": "number"},
        "expected_unit": _UNIT,
        "derivation": _DERIVATION_REF,
    },
    "required": ["ticker", "expected_value", "expected_unit"],
    "additionalProperties": False,
}
_FORBIDDEN_VALUE = {
    "type": "object",
    "properties": {"value": {"type": "number"}, "unit": _UNIT, "ticker": {"enum": sorted(COMPANIES)}},
    "required": ["value", "unit"],
    "additionalProperties": False,
}
_NON_EMPTY_STRINGS = {"type": "array", "items": {"type": "string", "minLength": 1}, "minItems": 1}


def _when_type(qtype: str, required: list[str]) -> dict:
    # `required` in the condition: without it a question missing "type"
    # matches every branch and is reported for the wrong field.
    return {"if": {"required": ["type"], "properties": {"type": {"const": qtype}}}, "then": {"required": required}}


QUESTION_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string", "minLength": 1},
        "question": {"type": "string", "minLength": 1},
        "type": {"enum": ["numeric", "comparison", "judged", "text", "refusal", "clarify"]},
        "ticker": {"type": "string"},
        "tickers": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "skip": {"type": "boolean"},
        "expected_value": {"type": "number"},
        "expected_unit": _UNIT,
        "derivation": _DERIVATION_REF,
        "expected": {"type": "array", "items": _VALUE, "minItems": 1},
        "criteria": {"type": "string", "minLength": 1},
        "accepted": _NON_EMPTY_STRINGS,
        "refusal_kind": {"enum": list(REFUSAL_KINDS)},
        # Terms whose absence from the company's filings shows the value
        # was never disclosed; the authoring check searches for them.
        "absence_terms": _NON_EMPTY_STRINGS,
        "readings": {**_NON_EMPTY_STRINGS, "minItems": 2},
        "forbidden_values": {"type": "array", "items": _FORBIDDEN_VALUE, "minItems": 1},
        # Relative, like the default 1%: 0.02 widens it to 2%.
        "tolerance": {"type": "number", "exclusiveMinimum": 0},
        "tolerance_note": {"type": "string", "minLength": 1},
        "category": {"enum": list(CATEGORIES)},
        "steps": {"type": "integer", "minimum": 1},
        "answer_source": {"enum": ["table", "text", "both"]},
        "trap": {"enum": list(TRAPS)},
        "needs_calculate": {"type": "boolean"},
    },
    "required": ["id", "question", "type"],
    "anyOf": [{"required": ["ticker"]}, {"required": ["tickers"]}],
    "allOf": [
        _when_type("numeric", ["expected_value", "expected_unit"]),
        _when_type("comparison", ["expected"]),
        _when_type("judged", ["criteria"]),
        _when_type("text", ["accepted"]),
        _when_type("refusal", ["refusal_kind"]),
        _when_type("clarify", ["readings"]),
        {
            "if": {"required": ["refusal_kind"], "properties": {"refusal_kind": {"const": "never_disclosed"}}},
            "then": {"required": ["absence_terms"]},
        },
    ],
    # A per-question tolerance must say why the default 1% isn't enough.
    "dependentRequired": {"category": list(V2_TAGS), "tolerance": ["tolerance_note"]},
    "additionalProperties": False,
    "$defs": {"derivation": _DERIVATION},
}


def question_tickers(question: dict) -> list[str]:
    """The companies a question asks about across its `ticker` and
    `tickers` fields, sorted."""
    return sorted({*question.get("tickers", []), *([question["ticker"]] if "ticker" in question else [])})


def single_ticker(question: dict) -> str | None:
    """The one company a question asks about; None when it names several."""
    tickers = question_tickers(question)
    return tickers[0] if len(tickers) == 1 else None


def _check_trap_tickers(question: dict, label: str) -> None:
    """A trap value is charged to the asked company unless it names
    another; a question asking about several companies has no single
    default, so each of its trap values must name one."""
    if single_ticker(question) is not None:
        return
    for i, trap in enumerate(question.get("forbidden_values", [])):
        if "ticker" not in trap:
            raise ValueError(
                f"malformed eval question {label} at $.forbidden_values[{i}]: names no ticker, "
                "and the question has no single ticker to default to"
            )


def _check_entry_companies(question: dict, label: str) -> None:
    """An entry's companies must be among the question's, or no correct
    answer can pass it. Grading goes by `companies`, so a ticker label
    beside it must agree, or failures would name the wrong company."""
    tickers = question_tickers(question)
    for i, entry in enumerate(question.get("expected", [])):
        where = f"malformed eval question {label} at $.expected[{i}]"
        if "companies" in entry and entry["ticker"] in COMPANIES and entry["companies"] != [entry["ticker"]]:
            raise ValueError(
                f"{where}: label {entry['ticker']!r} is a ticker, but companies names {', '.join(entry['companies'])}"
            )
        outside = entry_companies(entry, tickers) - set(tickers)
        if outside:
            raise ValueError(f"{where}: {', '.join(sorted(outside))} is not one of the question's companies")


def _bands_overlap(a: tuple[float, str], b: tuple[float, str], tolerance: float | None) -> bool:
    """Whether some value would match both (value, unit)s under the
    graders' rule: same unit category, and each within its tolerance."""
    (category_a, norm_a), (category_b, norm_b) = normalize(*a), normalize(*b)
    reach = match_tolerance(norm_a, tolerance) + match_tolerance(norm_b, tolerance)
    return category_a == category_b and abs(norm_a - norm_b) <= reach


def _check_trap_values(question: dict, label: str) -> None:
    """A correct answer must never count as a trap hit, so no value may
    match both a trap and an expected value claimed from that trap's
    company alone. A numeric question about several companies doesn't
    say whose its value is, so it's compared with every trap."""
    tickers = question_tickers(question)
    default = single_ticker(question)
    expected: list[tuple[set[str] | None, float, str]] = [
        (entry_companies(e, tickers), e["expected_value"], e["expected_unit"])
        for e in question.get("expected", [])
    ]
    if "expected_value" in question:
        expected.append(({default} if default else None, question["expected_value"], question["expected_unit"]))
    for i, trap in enumerate(question.get("forbidden_values", [])):
        company = trap.get("ticker", default)
        for companies, value, unit in expected:
            if companies in ({company}, None) and _bands_overlap(
                (trap["value"], trap["unit"]), (value, unit), question.get("tolerance")
            ):
                raise ValueError(
                    f"malformed eval question {label} at $.forbidden_values[{i}]: {trap['value']} {trap['unit']} "
                    f"overlaps the grading tolerance of the expected {value} {unit}, so a correct answer "
                    "could count as a trap hit"
                )


# Fields one question type alone may carry. Checked here rather than in
# the schema, whose error for such a rule doesn't name the field.
_TYPE_ONLY_FIELDS = {"absence_terms": "refusal", "derivation": "numeric"}


def _check_type_only_fields(question: dict, label: str) -> None:
    for key, qtype in _TYPE_ONLY_FIELDS.items():
        if key in question and question["type"] != qtype:
            raise ValueError(f"malformed eval question {label} at $.{key}: only a {qtype} question has one")


_VALIDATOR = jsonschema.Draft202012Validator(QUESTION_SCHEMA)


def validate_questions(questions: list[dict]) -> None:
    """Raises ValueError naming the first malformed question (by id, or
    by 1-based position when it has none) and what is wrong with it, or
    the first duplicated id."""
    seen: set[str] = set()
    for position, question in enumerate(questions, start=1):
        label = repr(question["id"]) if isinstance(question, dict) and "id" in question else f"question {position}"
        # best_match, as jsonschema.validate() uses: the first error found
        # is often a vague anyOf one rather than the field to fix.
        error = best_match(_VALIDATOR.iter_errors(question))
        if error is not None:
            where = "" if error.json_path == "$" else f" at {error.json_path}"
            raise ValueError(f"malformed eval question {label}{where}: {error.message}")
        _check_type_only_fields(question, label)
        _check_trap_tickers(question, label)
        _check_entry_companies(question, label)
        _check_trap_values(question, label)
        if question["id"] in seen:
            raise ValueError(f"duplicate question id {question['id']!r}")
        seen.add(question["id"])
