"""Static model-facing text for the agent model: the tool schemas it is
offered, and AGENT_TOOL_SCHEMAS, the exact list and order
agent._run_agent_impl sends. FACT and COMPARE are also listed to MCP
clients by mcp_server, and SEARCH through its MCP variant in prompts.mcp."""

# ruff: noqa: E501 -- the schemas' "description" values are deliberately
# long natural-language content shown to the model; splitting them into
# many short fragments adds no readability, so this module-level
# exception covers them.

from companies import COMPANIES
from formulas import RATIO_DEFINITIONS
from prompts.agent_system import (
    CROSS_COMPANY_RATIOS,
    DECIMAL_RATIOS,
    FACT_METRICS,
    PERCENT_RATIOS,
    SINGLE_COMPANY_ONLY_RATIOS,
)
from xbrl_facts import DEFAULT_METRIC_TAGS

SEARCH_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "search_filings",
        "description": (
            "Search SEC 10-K/10-Q filing excerpts from the five covered companies. Returns the most "
            "relevant excerpts, each headed with a citation number, ticker, form type and report date. "
            "Use it for narrative content (risk factors, MD&A, segment or product-line figures) and for "
            "any metric get_financial_fact doesn't cover or finds no data for. It returns filing text "
            "only, not structured XBRL values."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What to search for, as a natural-language question or phrase. Only used for a follow-up search against a company you've already searched — the first search against each company always uses the user's original question.",
                },
                "ticker": {
                    "type": "string",
                    "enum": list(COMPANIES.keys()),
                    "description": "Restrict the search to one company's filings. Omit only if genuinely unsure which company the question is about.",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
}

FACT_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "get_financial_fact",
        "description": (
            "Look up an exact structured value for one standard financial metric, for one "
            "company and one period. Specify the period ONE of two ways: (a) if the question "
            "gives a specific calendar date (e.g. 'the quarter ended April 26, 2026'), pass "
            "period_end_date and leave fiscal_year/fiscal_period out -- the tool converts it to "
            "the company's own fiscal labeling for you, which you should NOT try to compute "
            "yourself (a calendar date can fall in a different fiscal year than its calendar "
            "year for these companies). (b) if the question already states the period in fiscal "
            "terms (e.g. 'fiscal year 2026', 'the third quarter of fiscal year 2026'), pass "
            "fiscal_year and fiscal_period directly instead. Returns null if the company doesn't "
            "tag this metric or the period isn't recognized -- fall back to search_filings when "
            "that happens."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "enum": list(COMPANIES.keys())},
                "metric": {
                    "type": "string",
                    "enum": list(FACT_METRICS),
                    "description": (
                        f"Which metric to fetch. {', '.join(PERCENT_RATIOS)} are each computed as a ratio and "
                        f"returned as a percent; {', '.join(DECIMAL_RATIOS)} are also computed as a ratio but "
                        "returned as a plain decimal (e.g. 1.04), NOT a percent -- do not multiply it by 100 or "
                        "add a % sign; the rest are returned in USD."
                    ),
                },
                "period_end_date": {
                    "type": "string",
                    "description": "A calendar date 'YYYY-MM-DD' from the question (e.g. the quarter- or fiscal-year-end date stated). Preferred whenever the question states an actual date -- do not convert it to a fiscal year yourself.",
                },
                "fiscal_year": {
                    "type": "integer",
                    "description": "Only use this when the question states a fiscal year directly instead of a calendar date. The fiscal year as the company itself labels it -- do not guess this from a calendar date, use period_end_date instead.",
                },
                "fiscal_period": {
                    "type": "string",
                    "enum": ["FY", "Q1", "Q2", "Q3", "Q4"],
                    "description": "Only used together with fiscal_year. FY for a full fiscal year (from the 10-K), or Q1/Q2/Q3 for a quarter (from a 10-Q). Q4 is not separately available for most of these companies -- fall back to search_filings for Q4-specific figures.",
                },
                "yoy_growth": {
                    "type": "boolean",
                    "description": (
                        "Set true to get year-over-year percent growth of `metric` instead of its plain value "
                        "(e.g. 'revenue growth' questions). Only valid for the raw metrics, NOT for any ratio "
                        f"metric ({', '.join(sorted(RATIO_DEFINITIONS))}) -- returns null for that combination. "
                        "Compares the requested period to the SAME fiscal_period one year earlier automatically; "
                        "never compute growth yourself from two separate calls. The returned value IS the "
                        "answer -- do not also fetch the current and prior-period raw values afterward to "
                        "re-derive or double-check it."
                    ),
                },
                "start_fiscal_year": {
                    "type": "integer",
                    "description": "Only for a multi-year-average question (e.g. '3-year average operating margin from fiscal year 2023 through 2025'). Set together with end_fiscal_year, and leave fiscal_year/fiscal_period/period_end_date out -- averages `metric` across every fiscal year in the range (always full-year, FY). Never average multiple years yourself from separate calls, always use this. The returned average IS the answer -- do not also fetch each individual year's value afterward to show your work.",
                },
                "end_fiscal_year": {
                    "type": "integer",
                    "description": "The last fiscal year of a multi-year-average range -- see start_fiscal_year.",
                },
            },
            "required": ["ticker", "metric"],
            "additionalProperties": False,
        },
    },
}

COMPARE_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "compare_financial_metric",
        "description": (
            "Get one financial metric for ALL FIVE covered companies at once, for the same "
            "period -- use this instead of calling get_financial_fact once per company for a "
            "comparison/ranking question. Anchor the period on whichever company the question "
            "mentions (or any one of the five if it doesn't specify a particular company's "
            "date) using the SAME period_end_date OR fiscal_year+fiscal_period rules as "
            "get_financial_fact; every other company's value for the closest matching period is "
            "returned automatically -- do not try to compute each company's own fiscal period "
            "yourself. A company may be missing from the result if it doesn't tag this metric "
            "for that period; that's not an error, just note it wasn't available for that one."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "anchor_ticker": {
                    "type": "string",
                    "enum": list(COMPANIES.keys()),
                    "description": "Whichever company's date/period you're anchoring on.",
                },
                "metric": {
                    "type": "string",
                    "enum": sorted(DEFAULT_METRIC_TAGS) + CROSS_COMPANY_RATIOS,
                    "description": (
                        f"Which metric to fetch for every company. {', '.join(CROSS_COMPANY_RATIOS)} are each "
                        "computed as a ratio and returned as a percent; the rest are returned in USD. "
                        f"({', '.join(SINGLE_COMPANY_ONLY_RATIOS)} are NOT available here -- no cross-company "
                        "version exists; use get_financial_fact per company instead.)"
                    ),
                },
                "period_end_date": {
                    "type": "string",
                    "description": "A calendar date 'YYYY-MM-DD' from the question, for the anchor company. Preferred whenever the question states an actual date.",
                },
                "fiscal_year": {
                    "type": "integer",
                    "description": "Only use this when the question states a fiscal year directly instead of a calendar date, in the anchor company's own fiscal labeling.",
                },
                "fiscal_period": {
                    "type": "string",
                    "enum": ["FY", "Q1", "Q2", "Q3", "Q4"],
                    "description": "Only used together with fiscal_year. FY for a full fiscal year, or Q1/Q2/Q3 for a quarter. Q4 is not separately available for most of these companies.",
                },
            },
            "required": ["anchor_ticker", "metric"],
            "additionalProperties": False,
        },
    },
}

# Deliberately NOT in mcp_server.py's _TOOL_SCHEMAS: this is a final-answer
# mechanism internal to agent.py's own tool-calling loop (the model's
# structured "here is my answer" instead of free text), not something an
# external MCP client would ever want to call itself.
#
# `unit`'s enum is exactly numeric_utils.normalize()'s vocabulary --
# "raw" and "percent" pass through normalize() unchanged (multiplier 1.0,
# UNIT_MULTIPLIERS.get(unit, 1.0)), "thousand"/"million"/"billion" are its
# declared keys. Keeping this list explicit rather than deriving it from
# UNIT_MULTIPLIERS.keys() because "raw"/"percent" aren't IN that dict (they're
# normalize()'s two special-cased categories) -- deriving would silently
# drop them, not add them.
CLAIM_UNITS = ["raw", "thousand", "million", "billion", "percent"]

SUBMIT_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "submit_answer",
        "description": (
            "Deliver your final answer. This is the ONLY way to answer -- do not reply with plain "
            "text instead. `answer_text` is what the user reads; `claims` is a structured list, one "
            "entry per citation marker in it, each tied to the specific search result it comes from. "
            "A claim that states a real number includes `value`/`unit`; a claim supporting a purely "
            "qualitative fact with no number (e.g. a risk-factor bullet) omits both -- either way, "
            "`citation_index` and `quote` are always required. A number with no matching claim will "
            "be treated as ungrounded and the whole answer refused. `claims` may be empty only for a "
            "refusal answer with nothing to cite at all."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "answer_text": {
                    "type": "string",
                    "description": (
                        "The full final answer, formatted for the user. You may still include [n] "
                        "citation markers here for readability, matching the search result numbering "
                        "-- they are for the reader, not for grounding, which claims below handles."
                    ),
                },
                "claims": {
                    "type": "array",
                    "description": "One entry per citation marker in answer_text, numeric or qualitative.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "value": {
                                "type": "number",
                                "description": (
                                    "The numeric value, e.g. 72.4 for $72.4 billion. Omit entirely "
                                    "(along with `unit`) for a qualitative claim with no real number."
                                ),
                            },
                            "unit": {
                                "type": "string",
                                "enum": CLAIM_UNITS,
                                "description": (
                                    "raw (a plain count/dollar amount with no scale word), thousand, "
                                    "million, billion, or percent. Omit entirely (along with `value`) "
                                    "for a qualitative claim with no real number."
                                ),
                            },
                            "citation_index": {
                                "type": "integer",
                                "description": "Which numbered search result (as shown to you, 1-based) this value comes from.",
                            },
                            "quote": {
                                "type": "string",
                                "description": (
                                    "The exact text from that search result supporting this value -- "
                                    "copy it verbatim, do not paraphrase or summarize it."
                                ),
                            },
                        },
                        "required": ["citation_index", "quote"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["answer_text", "claims"],
            "additionalProperties": False,
        },
    },
}

# Deliberately NOT in mcp_server.py's _TOOL_SCHEMAS, same reasoning as
# SUBMIT_TOOL_SCHEMA above: citation_index_a/citation_index_b are only
# meaningful within one agent._run_agent_impl run's own all_results, not to a
# standalone MCP caller with no such list.
#
# A hand-computed value can never pass agent._verify_one_claim, which
# requires the claimed value to appear inside the quote. This tool is the
# route for derived numbers instead: each operand must appear in its cited
# source (agent._number_candidates, the same check claims use) and the
# operation runs in Python, never in the model's head. Its result is an
# ordinary all_results entry the model cites like any other tool output.
#
# Strictly binary (no N-ary sum): a 3-way total is two calls, the second
# citing the first call's result as an operand.
CALCULATE_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "calculate",
        "description": (
            "Performs ONE arithmetic operation over two numbers you have already seen in a "
            "prior result, and returns a new citable result with the computed value. Use this "
            "for any number you would otherwise have to work out yourself -- never state a "
            "self-computed value directly, it will be refused. Prefer a named ratio first when "
            "one exists (get_financial_fact with yoy_growth: true, or a registered ratio metric) "
            "-- use calculate only for arithmetic those don't "
            "cover. When you cite the result of a calculate call in your final answer, state the "
            "computation inline (e.g. 'computed as $34,550 million / $195,201 million = 17.7%') rather than "
            "presenting it as if the filing stated it directly. "
            "Do NOT use this for a plain unit conversion (e.g. dividing a raw dollar amount by "
            "1,000,000,000 to express it in billions) -- both operands must come from a result "
            "you've already seen and cited, and a bare conversion constant like 1,000,000,000 has "
            "no citation to ground it against, so that call can never succeed. Converting a value "
            "you already have to a different unit needs no tool call at all: just state it "
            "directly with the new unit (e.g. state $4,475,446,000 as '$4.48 billion'), citing the "
            "same result with the same verbatim quote as before -- see system-prompt rule 9."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["add", "subtract", "multiply", "divide", "percent_of", "percent_change"],
                    "description": (
                        "add/subtract/multiply/divide: the plain arithmetic operation, a op b. "
                        "percent_of: operand_a as a percentage of operand_b (a/b*100). "
                        "percent_change: percentage change FROM operand_b (the baseline/prior "
                        "value) TO operand_a (the new/current value) -- (a-b)/b*100."
                    ),
                },
                "operand_a": {"type": "number", "description": "The first operand, taken directly from a result you've already seen."},
                "citation_index_a": {
                    "type": "integer",
                    "description": "Which numbered result (1-based) operand_a came from.",
                },
                "unit_a": {
                    "type": "string",
                    "enum": CLAIM_UNITS,
                    "description": "operand_a's unit: raw, thousand, million, billion, or percent.",
                },
                "operand_b": {"type": "number", "description": "The second operand, taken directly from a result you've already seen."},
                "citation_index_b": {
                    "type": "integer",
                    "description": "Which numbered result (1-based) operand_b came from.",
                },
                "unit_b": {
                    "type": "string",
                    "enum": CLAIM_UNITS,
                    "description": "operand_b's unit: raw, thousand, million, billion, or percent.",
                },
            },
            "required": [
                "operation",
                "operand_a",
                "citation_index_a",
                "unit_a",
                "operand_b",
                "citation_index_b",
                "unit_b",
            ],
            "additionalProperties": False,
        },
    },
}

# The tools offered to the agent model, in the order it receives them.
AGENT_TOOL_SCHEMAS = (
    FACT_TOOL_SCHEMA,
    COMPARE_TOOL_SCHEMA,
    SEARCH_TOOL_SCHEMA,
    CALCULATE_TOOL_SCHEMA,
    SUBMIT_TOOL_SCHEMA,
)


# Hashed into prompts.prompt_fingerprint(). AGENT_TOOL_SCHEMAS holds all
# five schemas in the order the agent model receives them, so the
# individual schemas and CLAIM_UNITS (rendered into SUBMIT_TOOL_SCHEMA)
# are covered through it. What MCP clients see of these schemas,
# including their order, is covered by the snapshot's mcp section.
FINGERPRINTED = ("AGENT_TOOL_SCHEMAS",)
NOT_FINGERPRINTED = (
    "SEARCH_TOOL_SCHEMA",
    "FACT_TOOL_SCHEMA",
    "COMPARE_TOOL_SCHEMA",
    "CLAIM_UNITS",
    "SUBMIT_TOOL_SCHEMA",
    "CALCULATE_TOOL_SCHEMA",
)
