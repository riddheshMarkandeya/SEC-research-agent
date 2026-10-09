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

_VALUE = {
    "type": "object",
    "properties": {
        "ticker": {"type": "string"},
        "expected_value": {"type": "number"},
        "expected_unit": {"type": "string"},
    },
    "required": ["ticker", "expected_value", "expected_unit"],
    "additionalProperties": False,
}
_FORBIDDEN_VALUE = {
    "type": "object",
    "properties": {"value": {"type": "number"}, "unit": {"type": "string"}, "ticker": {"type": "string"}},
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
        "expected_unit": {"type": "string"},
        "expected": {"type": "array", "items": _VALUE, "minItems": 1},
        "criteria": {"type": "string", "minLength": 1},
        "accepted": _NON_EMPTY_STRINGS,
        "refusal_kind": {"enum": list(REFUSAL_KINDS)},
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
    ],
    # A per-question tolerance must say why the default 1% isn't enough.
    "dependentRequired": {"category": list(V2_TAGS), "tolerance": ["tolerance_note"]},
    "additionalProperties": False,
}


def _check_trap_tickers(question: dict, label: str) -> None:
    """A trap value is charged to the asked company unless it names
    another; a question asking about several companies has no single
    default, so each of its trap values must name one."""
    if "ticker" in question:
        return
    for i, trap in enumerate(question.get("forbidden_values", [])):
        if "ticker" not in trap:
            raise ValueError(
                f"malformed eval question {label} at $.forbidden_values[{i}]: names no ticker, "
                "and the question has no single ticker to default to"
            )


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
        _check_trap_tickers(question, label)
        if question["id"] in seen:
            raise ValueError(f"duplicate question id {question['id']!r}")
        seen.add(question["id"])
