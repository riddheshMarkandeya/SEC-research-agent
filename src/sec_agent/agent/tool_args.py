"""
Tool-argument validation shared by every agent tool: the generic
jsonschema check (validate_tool_args) and the fiscal-year coercion and
rejection rules the fact and compare tools apply before it.
"""

import re
from typing import Any, TypeGuard

import jsonschema
import jsonschema.exceptions

from sec_agent.tracing import log_event

_INT_TYPE_VALIDATOR = jsonschema.Draft202012Validator({"type": "integer"})


def _is_valid_int(value: Any) -> TypeGuard[int]:
    """True if value is a JSON-Schema-valid "integer" -- an int but NOT a
    bool. jsonschema's default type checker already excludes bool from
    "integer" (JSON itself treats true/false as their own type, distinct
    from numbers), so this gets that exclusion for free instead of
    writing `isinstance(x, int) and not isinstance(x, bool)` by hand --
    the exact shape of bug (isinstance(True, int) is True in Python) that
    silently let fiscal_year=true through the old hand-rolled check. See
    docs/decisions/2026-09-09-schema-driven-arg-validation.md. Shared by
    _rejects_invalid_fiscal_year and the multi-year-average combo check
    below, both of which read fiscal_year-shaped args outside of
    validate_tool_args's generic pass (see call_get_financial_fact's
    skip_properties)."""
    return _INT_TYPE_VALIDATOR.is_valid(value)


def _rejects_invalid_fiscal_year(tool: str, args: dict) -> bool:
    """True (having already logged the rejection) if args["fiscal_year"]
    is present but not a valid int -- shared by call_get_financial_fact
    and call_compare_financial_metric, which otherwise would each
    hand-roll an identical check. A malformed
    fiscal_year doesn't crash any downstream lookup -- it just fails to
    match and returns None/{}, which used to get recorded as
    reason="no_data_for_ticker" via record_unmet_metric_request(),
    polluting that "should we add a formula for this" telemetry with a
    schema-violation false negative instead of a real data gap."""
    fiscal_year = args.get("fiscal_year")
    if fiscal_year is not None and not _is_valid_int(fiscal_year):
        log_event("tool_call_rejected", tool=tool, reason="invalid_fiscal_year_type", args=args)
        return True
    return False


# ASCII digits only (\d would also match other scripts' decimal digits),
# and no leading zero, so "0000" isn't read as year 0.
_YEAR_STRING = re.compile(r"[1-9][0-9]{3}")


def _coerce_year_args(tool: str, args: dict, fields: frozenset[str]) -> dict:
    """A copy of `args` with each year in `fields` given as a 4-digit
    string or a whole float turned into an int, or `args` itself when
    there is none. This is the only conversion of these fields: Gemini
    sends years as strings ("2025") despite the integer schema, and
    rejecting them cost the model turns; a whole float (2025.0) passes the
    schema but breaks the multi-year average's range() and shows as
    "FY2025.0". Anything else ("FY2025", "²²²²", "0000", "99999", 2025.5,
    a bool) is left for the usual checks to reject."""
    coerced = args
    for field in sorted(fields):
        value = args.get(field)
        if isinstance(value, str) and _YEAR_STRING.fullmatch(value):
            year = int(value)
        elif isinstance(value, float) and value.is_integer():
            year = int(value)
        else:
            continue
        if coerced is args:
            coerced = dict(args)
        coerced[field] = year
        log_event("tool_arg_coerced", tool=tool, field=field, value=value)
    return coerced


_VALIDATOR_KIND_PRIORITY = {"additionalProperties": 0, "required": 1, "type": 2, "enum": 3}


def _reason_for_error(error: jsonschema.exceptions.ValidationError) -> str:
    """Maps a jsonschema ValidationError to this project's own
    tool_call_rejected reason= taxonomy -- distinct, greppable-by-
    tool+reason values, not jsonschema's own vocabulary verbatim, since a
    couple of its violation kinds don't map 1:1 onto a single named
    property: additionalProperties covers every extra key at once (no
    single offending property), and required's offending property isn't
    exposed via error.path (the key doesn't exist in the instance, so
    there's nothing for a JSON pointer to point at)."""
    if error.validator == "additionalProperties":
        return "unrecognized_extra_argument"
    if error.validator == "required":
        return "missing_required_argument"
    prop = error.path[0] if error.path else "args"
    kind = "not_in_enum" if error.validator == "enum" else "wrong_type"
    return f"{prop}_{kind}"


def validate_tool_args(
    tool: str,
    schema: dict,
    args: dict,
    *,
    soft_required: frozenset = frozenset(),
    skip_properties: frozenset = frozenset(),
) -> bool:
    """True (having already logged the rejection) if args fails schema's
    parameter validation -- the generic replacement for what used to be
    a hand-rolled extra-key/type/enum check per tool. See
    docs/decisions/2026-09-09-schema-driven-arg-validation.md. `schema`
    is one of *_TOOL_SCHEMA, doing double duty as both what's advertised
    to the LLM and what's enforced here -- `additionalProperties: false`
    on each schema's `parameters` is what replaces the old
    `set(args) - _FACT_ARG_KEYS`-style checks.

    Two carve-outs exist because a handful of properties have runtime
    semantics a flat JSON Schema check can't safely express without
    leaking business logic into the LLM-facing schema:
    - `soft_required`: schema-advertised required properties the caller
      tolerates being absent at runtime instead of rejecting -- e.g.
      search_filings' `query`, which _resolve_search_args substitutes
      the original question for when the model omits it (observed live,
      not a bug -- see that function's own docstring).
    - `skip_properties`: properties whose declared type is only
      conditionally meaningful -- e.g. get_financial_fact's
      `fiscal_year`, which the multi-year-average request shape never
      reads at all, so a malformed value there must be ignored, not
      rejected (test_call_get_financial_fact_ignores_malformed_fiscal_year_in_multi_year_average_request).
      Their own type is still checked by the caller's own business logic
      instead (see _rejects_invalid_fiscal_year), just not generically
      here -- their sub-schema is swapped for `{}` (matches anything)
      rather than removed from `properties` entirely, so a present value
      still satisfies `additionalProperties: false`.

    A `metric` enum violation is ALSO always allowed through (regardless
    of skip_properties) so callers can route a recognized-shape-but-
    unsupported metric name to record_unmet_metric_request() instead of
    a silent generic boundary rejection -- see call_get_financial_fact's
    own metric-enum check right after this returns False.

    A declared-but-null-valued property (e.g. `{"ticker": None}`) is
    validated as though the key were absent, for any DECLARED property --
    an explicit JSON null for an unset optional argument is exactly as
    valid as omitting it (nothing in this codebase distinguishes the two
    afterwards; every reader uses `args.get(...)`, which returns None
    either way) and just as invalid as omitting it for a required one.
    Handled once, generically, here rather than enumerating
    `["string", "null"]` per property as each one would otherwise need
    it noticed separately (see the decision file above). An unrecognized
    EXTRA key is deliberately NOT
    stripped even if null-valued -- `additionalProperties: false` must
    still catch e.g. `{"segment": None}`, since the key itself is the
    problem, not its value."""
    params = schema["function"]["parameters"]
    if soft_required or skip_properties:
        params = dict(params)
        if soft_required:
            params["required"] = [r for r in params.get("required", []) if r not in soft_required]
        if skip_properties:
            params["properties"] = {
                name: ({} if name in skip_properties else sub_schema)
                for name, sub_schema in params["properties"].items()
            }
    # dict, not set -- a dict already preserves declaration order (used
    # below for property_order's tie-break) and `in` on a dict is an O(1)
    # key check same as a set, so routing through set() first would only
    # lose that ordering for no benefit (a set's iteration order is this
    # process's hash seed, not schema order).
    declared_properties = params.get("properties", {})
    instance = {k: v for k, v in args.items() if v is not None or k not in declared_properties}
    validator = jsonschema.Draft202012Validator(params)
    property_order = list(declared_properties)

    def priority(error):
        prop = error.path[0] if error.path else None
        prop_rank = property_order.index(prop) if prop in property_order else -1
        return (_VALIDATOR_KIND_PRIORITY.get(error.validator, 9), prop_rank)

    for error in sorted(validator.iter_errors(instance), key=priority):
        if error.validator == "enum" and list(error.path) == ["metric"]:
            continue
        log_event("tool_call_rejected", tool=tool, reason=_reason_for_error(error), args=args)
        return True
    return False


# fiscal_year/start_fiscal_year/end_fiscal_year are excluded from
# call_get_financial_fact's generic validate_tool_args pass -- see that
# function's call site and validate_tool_args's own docstring for why.
_FISCAL_YEAR_PROPS = frozenset({"fiscal_year", "start_fiscal_year", "end_fiscal_year"})


_COMPARE_FISCAL_YEAR_PROPS = frozenset({"fiscal_year"})
