"""
Agent layer: gives the LLM a `search_filings` tool (wrapping
retrieval.hybrid_search) instead of pre-fetching context ourselves, so
the model decides what to search for, which ticker to restrict to (if
any), and whether to search again -- e.g. calling the tool twice, once
per company, for a cross-company comparison question. See
docs/decisions/2026-08-14-agent-v0-tool-calling.md for why this exists
and how tool-calling was verified against the real backend wire format.

Usage:
    python agent.py "How many full-time employees does Apple have?"
    python agent.py "Compare Apple's and Microsoft's effective tax rates." --verbose
"""

import argparse
import re
from collections import Counter
from typing import NamedTuple

import jsonschema

from companies import load_companies
from config import DEFAULT_BACKEND
from formulas import (
    RATIO_DEFINITIONS,
    get_multi_year_average,
    get_ratio,
    get_ratio_all_companies,
    get_yoy_growth,
)
from llm_backends import BACKENDS
from numeric_utils import (
    QUOTE_COVERAGE_THRESHOLD,
    UNIT_MULTIPLIERS,
    extract_numbers,
    extract_numbers_with_spans,
    normalize,
    normalize_for_match,
    text_coverage,
)
from retrieval import hybrid_search
from table_grounding import extract_table_blocks, locate_value, quote_is_grounded
from tracing import flush, log_event, record_unmet_metric_request, traced_span
from xbrl_facts import DEFAULT_METRIC_TAGS, get_metric, get_metric_all_companies, is_metric_tagged

MAX_TOOL_ITERATIONS = 6
CHUNKS_PER_SEARCH = 5

# Tool-computed ratio metrics -- none of these are a single GAAP tag
# (see formulas.py's _compute_ratio_metric()), so each is computed from
# two raw metrics instead of returned raw for the model to divide.
# RATIO_DEFINITIONS (formulas.py) is the single source of truth for
# which ratios exist and how each is computed; get_ratio()/
# get_ratio_all_companies() (also formulas.py) dispatch through it
# generically -- see
# docs/decisions/2026-08-28-ratio-definitions-table-driven-registry.md
# for why this replaced two separate hand-maintained dicts. A ratio's
# `supports_cross_company` flag (in RATIO_DEFINITIONS) is what
# compare_financial_metric's dispatch below relies on to fall through to
# the same graceful "not supported" result any other unrecognized metric
# gets, for ratios like return_on_assets/asset_turnover/cash_to_assets/
# inventory_turnover/rd_intensity that don't have one.
#
# Derived once here rather than inline below, so the system prompt and
# both tool schemas stay accurate automatically as RATIO_DEFINITIONS
# grows -- the whole point of the table (see the decision file above) is
# a new ratio needing no prompt/schema text updated by hand.
_CROSS_COMPANY_RATIOS = sorted(name for name, d in RATIO_DEFINITIONS.items() if d.supports_cross_company)
_SINGLE_COMPANY_ONLY_RATIOS = sorted(name for name, d in RATIO_DEFINITIONS.items() if not d.supports_cross_company)
_PERCENT_RATIOS = sorted(name for name, d in RATIO_DEFINITIONS.items() if d.as_percent)
_DECIMAL_RATIOS = sorted(name for name, d in RATIO_DEFINITIONS.items() if not d.as_percent)

# The companies this agent is scoped to, read from companies.json (see
# companies.py) rather than hardcoded here — this used to be its own
# ticker->name dict, duplicating edgar_ingest.py's separate ticker->CIK
# dict under the same COMPANIES name, which is exactly the kind of
# two-copies-of-the-truth setup that drifts silently. Baked into the
# system prompt below rather than exposed as a "list_companies" tool —
# a handful of static facts don't justify a round trip, and every model
# tested so far already knows "Salesforce" -> CRM without help; this
# just makes explicit which companies are actually indexed.
COMPANIES = {ticker: info["name"] for ticker, info in load_companies().items()}

SYSTEM_PROMPT = f"""You are a financial research assistant answering questions about SEC filings for five companies:
{chr(10).join(f"- {ticker}: {name}" for ticker, name in COMPANIES.items())}

You have five tools:
- `get_financial_fact` searches structured XBRL data for a small set of standard financial metrics: {", ".join(sorted(DEFAULT_METRIC_TAGS) + sorted(RATIO_DEFINITIONS))}. Prefer this tool FIRST whenever the question asks for one of these specific metrics for a specific fiscal year or fiscal quarter, for ONE company — it returns an exact, unambiguous reported value instead of relying on you to find the right sentence in a filing excerpt. This tool ONLY returns a company's consolidated, company-wide total — it has NO way to get one segment's or one product line's figure (e.g. Microsoft's "Intelligent Cloud" segment, NVIDIA's "Compute & Networking" segment). If a question asks about a specific segment or product line, do NOT call this tool at all, not even to try — go straight to `search_filings` instead. It only works for the metrics listed above and returns "not available" if the company doesn't tag it or the period wasn't recognized — fall back to `search_filings` when that happens, or for anything else this tool doesn't cover (risk factors, narrative discussion, any metric not in the list above). Only pass the arguments this tool actually defines — never invent an extra filter argument (e.g. there is no `segment` parameter); an unrecognized argument is rejected outright, so search_filings instead if you need something this tool doesn't support. To ask for year-over-year growth of one of the raw metrics (not the ratios) instead of its plain value, add `yoy_growth: true` — never compute a growth percentage yourself from two separate calls to this tool, always use this flag; the returned growth value IS the answer, so once you have it, do not also fetch the current and prior-year raw values afterward to re-derive or double-check it. To ask for a multi-year average (e.g. "3-year average operating margin"), pass `start_fiscal_year` and `end_fiscal_year` instead of `fiscal_year`/`fiscal_period`/`period_end_date` — never average multiple years yourself from separate calls, always use these; likewise, the returned average IS the answer, so do not also fetch each individual year's value afterward to show your work.
- `compare_financial_metric` gets the SAME metric for ALL FIVE companies at once, for one period. Use this instead of calling `get_financial_fact` five times when a question asks you to compare or rank companies against each other (e.g. "which company had the highest gross margin", "compare revenue across all five companies") — one call instead of five. A company can be missing from the result if it doesn't tag that metric for that period; that's not an error, just note it's unavailable for that company. Note: {", ".join(_SINGLE_COMPANY_ONLY_RATIOS)} are NOT available on this tool (no cross-company version exists) — use `get_financial_fact` once per company for those instead.
- `search_filings` searches these companies' 10-K/10-Q filings for anything else. Call it once per company if a question spans more than one, and call it again with a different query if your first search doesn't turn up what you need.
- `calculate` performs ONE arithmetic operation (add, subtract, multiply, divide, percent_of, percent_change) over two numbers you've already seen in a result, and returns a new citable result with the computed value. Use this for ANY number you would otherwise have to work out yourself — never state a self-computed value directly, it will be refused, since there is nothing that states it for you to quote. Prefer a named ratio first when one exists (`get_financial_fact` with `yoy_growth: true`, or a registered ratio metric) — use `calculate` only for arithmetic those don't cover. Do NOT use it for a plain unit conversion (e.g. dividing by 1,000,000,000 to turn a raw dollar amount into billions) — the divisor is a bare constant with no citation to ground it against, so that call can never succeed; see rule 9 for how to restate a value in a different unit with no tool call at all. When you cite its result in your final answer, state the computation inline (e.g. "computed as $34,550M ÷ $195,201M = 17.7%") rather than presenting it as though the filing stated it directly.
- `submit_answer` delivers your final answer -- this is the ONLY way to answer; never reply with plain text instead. See rule 9 below.

Do not answer from prior knowledge about these companies; every answer must come from what a tool returns.

Rules:
1. Every factual or numeric claim in your final answer must end with a citation marker like [1] or [2] referring to a search result.
2. If your searches don't turn up enough information to answer, say so explicitly rather than guessing.
3. Do not combine or infer numbers that don't appear directly in a search result (e.g. don't compute a total unless a result states it) — this does not apply to `get_financial_fact`'s or `calculate`'s own output, both of which are already a single reported or tool-computed value.
4. Resolve company names to the right ticker yourself (e.g. "Salesforce" -> CRM) — don't ask the user to clarify.
5. Search results often report the same metric for several different periods in one excerpt — not just in tables, but within a single sentence, e.g. "the rate was 20% for the current quarter, and 18% for the same quarter last year." Before citing a number, check that its stated period exactly matches the period asked about, even when both numbers appear right next to each other in the same sentence — do not substitute a prior-year or prior-quarter value just because it's nearby.
6. For a question spanning multiple companies, you must query EVERY company mentioned — with `search_filings` if `get_financial_fact` didn't cover it — before writing your final answer. A `get_financial_fact` call returning "not available" for one company is not a reason to stop; it means try `search_filings` for that same company next, and you must still go on to query every other company the question asks about. Do not conclude a company's data is unavailable unless you have actually searched for it.
7. If `compare_financial_metric` returns fewer than all five companies, your final answer must explicitly name which companies were and weren't covered (e.g. "data was only available for AAPL and PLTR; the others hadn't filed a matching quarter yet") — do not phrase a conclusion as if it covers "all five companies" or similar when it only covers the ones that were actually returned.
8. ONLY when a single sentence combines facts from two or more DIFFERENT companies (e.g. comparing NVIDIA and Salesforce), put each citation marker immediately after the specific fact it supports, not bundled together at the end — write "NVIDIA's revenue was $81.6 billion [1], while Salesforce's was $11.1 billion [2]." not "NVIDIA's revenue was $81.6 billion, while Salesforce's was $11.1 billion [1][2]." This rule does not add any new requirement to single-company answers or to a refusal under rule 2 — never search for extra facts just to have something to cite per-sentence; a plain, single citation at the end of a normal sentence is already correct and needs no change.
9. Deliver your final answer ONLY by calling `submit_answer` -- never as plain text. Put the reader-facing answer in `answer_text` (citation markers there are for the reader, same as rules 1 and 8 above). For EVERY number in `answer_text`, add a matching entry to `claims`: the value, its unit, which numbered search result it comes from, and the exact supporting text copied verbatim from that result -- do not paraphrase or summarize the quote. A tool's own computed output (e.g. `get_financial_fact` with `yoy_growth: true`, `calculate`, or any ratio metric) is still a single, directly reported value -- quote that result's own text, the same as any other directly-stated number, per rule 3. If you need to combine, compare, or derive a number from values you've already seen (a difference, a ratio, a percentage change) despite rule 3 telling you not to work this out yourself -- call `calculate` FIRST and cite ITS result the same way as any other; never state a self-computed value directly, since there is nothing that states it for you to quote, and it will be refused. When `answer_text` includes a value derived via `calculate`, show the computation inline (e.g. "computed as $34,550M ÷ $195,201M = 17.7%") rather than presenting it as though the filing stated it directly. Restating an already-cited value in a DIFFERENT UNIT (e.g. a raw dollar amount as billions) is NOT a derivation and needs no `calculate` call at all -- state it directly with the new unit, citing the same result with the same verbatim quote as before; keep enough significant figures that the restated value stays within about 1% of the source figure (e.g. state $4,475,446,000 as "$4.48 billion", not "$4.4 billion" or "$4 billion" -- too coarse a rounding will be treated as an unsupported value and the whole answer refused). A number with no matching claim at all will be treated as ungrounded and the whole answer refused, so it is better to omit a number you can't support than to state it without a claim."""

SEARCH_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "search_filings",
        "description": "Search SEC 10-K/10-Q filing excerpts for one of the five covered companies.",
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
                    "enum": sorted(DEFAULT_METRIC_TAGS) + sorted(RATIO_DEFINITIONS),
                    "description": (
                        f"Which metric to fetch. {', '.join(_PERCENT_RATIOS)} are each computed as a ratio and "
                        f"returned as a percent; {', '.join(_DECIMAL_RATIOS)} are also computed as a ratio but "
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
                    "enum": sorted(DEFAULT_METRIC_TAGS) + _CROSS_COMPANY_RATIOS,
                    "description": (
                        f"Which metric to fetch for every company. {', '.join(_CROSS_COMPANY_RATIOS)} are each "
                        "computed as a ratio and returned as a percent; the rest are returned in USD. "
                        f"({', '.join(_SINGLE_COMPANY_ONLY_RATIOS)} are NOT available here -- no cross-company "
                        "version exists yet; use get_financial_fact per company instead.)"
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

# See docs/decisions/2026-09-10-structured-claims-citation-verification.md.
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
_CLAIM_UNITS = ["raw", "thousand", "million", "billion", "percent"]

SUBMIT_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "submit_answer",
        "description": (
            "Deliver your final answer. This is the ONLY way to answer -- do not reply with plain "
            "text instead. `answer_text` is what the user reads; `claims` is a structured list of "
            "every numeric fact in it, each tied to the specific search result it comes from. Every "
            "number stated in `answer_text` must have a matching entry in `claims` -- a number with "
            "no matching claim will be treated as ungrounded and the whole answer refused. `claims` "
            "may be empty for a qualitative or refusal answer with no numbers to ground."
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
                    "description": "One entry per numeric fact stated in answer_text.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "value": {"type": "number", "description": "The numeric value, e.g. 72.4 for $72.4 billion."},
                            "unit": {
                                "type": "string",
                                "enum": _CLAIM_UNITS,
                                "description": "raw (a plain count/dollar amount with no scale word), thousand, million, billion, or percent.",
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
                        "required": ["value", "unit", "citation_index", "quote"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["answer_text", "claims"],
            "additionalProperties": False,
        },
    },
}

# See docs/decisions/2026-09-11-calculate-tool-and-stress-questions.md.
# Deliberately NOT in mcp_server.py's _TOOL_SCHEMAS, same reasoning as
# SUBMIT_TOOL_SCHEMA above: citation_index_a/citation_index_b are only
# meaningful within one _run_agent_impl run's own all_results, not to a
# standalone MCP caller with no such list.
#
# Built after finding that system-prompt rule 9's original guidance for a
# hand-computed value ("quote the result(s) it came from, not the number
# itself") was structurally unverifiable: _verify_one_claim's value-
# attribution check always requires the claimed VALUE to appear as a
# number candidate inside the quote, so a claim quoting two raw inputs for
# their ratio could never pass. Prior art (FinQA/ConvFinQA/TAT-QA
# financial numerical-reasoning benchmarks) solves this with an explicit
# PROGRAM -- an operation over operands that trace back to real extracted
# data, mechanically re-executed and checked -- and PAL/Toolformer add the
# separate finding that LLM arithmetic itself is unreliable, so the
# calculation should run in real code, not the model's head. This tool
# combines both: operand grounding (each operand must actually appear in
# its cited source, via the same _number_candidates() primitive
# _verify_one_claim already uses) and arithmetic correctness (the
# operation runs in Python, never trusted from the model). Its result
# becomes a normal all_results entry the model cites like any other tool
# output -- zero changes needed to verify_claims/_verify_one_claim/
# CitationWarning, since a calculate result is directly quotable the same
# way get_financial_fact's yoy_growth output already is.
#
# Strictly binary (no N-ary sum) -- composable instead: a 3-way total is
# calculate twice, citing the first call's own result as an operand of the
# second, mirroring how FinQA's own programs chain binary operations
# rather than using N-ary ops.
CALCULATE_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "calculate",
        "description": (
            "Performs ONE arithmetic operation over two numbers you have already seen in a "
            "prior result, and returns a new citable result with the computed value. Use this "
            "for any number you would otherwise have to work out yourself -- never state a "
            "self-computed value directly, it will be refused. Prefer a named ratio first when "
            "one exists (get_financial_fact with yoy_growth: true, or a registered ratio metric "
            "via compare_financial_metric) -- use calculate only for arithmetic those don't "
            "cover. When you cite the result of a calculate call in your final answer, state the "
            "computation inline (e.g. 'computed as $34,550M / $195,201M = 17.7%') rather than "
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
                    "enum": _CLAIM_UNITS,
                    "description": "operand_a's unit: raw, thousand, million, billion, or percent.",
                },
                "operand_b": {"type": "number", "description": "The second operand, taken directly from a result you've already seen."},
                "citation_index_b": {
                    "type": "integer",
                    "description": "Which numbered result (1-based) operand_b came from.",
                },
                "unit_b": {
                    "type": "string",
                    "enum": _CLAIM_UNITS,
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


def _format_results_block(results: list[dict], start_index: int) -> str:
    """Format one search call's results as numbered excerpts, continuing
    the numbering from start_index rather than restarting at [1] — so
    citation numbers stay globally consistent across multiple tool calls
    within the same conversation."""
    if not results:
        return "(no matching filing excerpts found for this search)"

    blocks = []
    for offset, r in enumerate(results):
        i = start_index + offset
        meta = r["metadata"]
        header = f"[{i}] {meta['ticker']} {meta['form']} (reportDate={meta['reportDate']})"
        blocks.append(f"{header}\n{r['text']}")
    return "\n\n".join(blocks)


_Q4_NOT_DISCLOSED_HINT = (
    "No company files a separate quarterly report for Q4 -- only Q1-Q3 get a "
    "standalone 10-Q, so a discrete Q4 figure is never independently disclosed "
    "via XBRL; it only exists implicitly as FY minus Q1-Q3. Tell the user this "
    "figure isn't reported as a standalone figure, and stop there -- do not "
    "state, estimate, or mention ANY dollar amount in your answer, not for Q4, "
    "not the full fiscal year total, not from search results or any other "
    "period. Simply explain that quarterly figures aren't broken out this way."
)


def _never_tagged_hint(ticker: str, metric: str) -> str | None:
    """None unless `ticker` genuinely never tags `metric` at all (as
    opposed to just not having it for the specific period asked about)
    -- see xbrl_facts.is_metric_tagged()'s own docstring. Scoped to raw
    DEFAULT_METRIC_TAGS metrics only: is_metric_tagged()/_tag_for() only
    understand those names, and would raise for a margin metric name
    like "gross_margin" (not itself a GAAP tag) rather than telling us
    anything meaningful about it."""
    if metric not in DEFAULT_METRIC_TAGS or ticker not in COMPANIES:
        return None
    if is_metric_tagged(ticker, metric):
        return None
    return (
        f"{ticker} does not report {metric!r} in its financial statements at all -- for some "
        "metrics (e.g. inventory) this is because it genuinely doesn't apply to the company's "
        "business model (a software/services company with no physical goods has nothing to "
        "report there), not because this specific period is missing. Do not fabricate, "
        "estimate, or infer a value for it; state plainly that this metric isn't reported for "
        "this company, and explain why if the reason is evident (e.g. the business model)."
    )


def _format_no_fact_message(args: dict) -> str:
    """Built as its own function (not inlined at the call site) so the Q4
    hint below is unit-testable without a live Ollama round-trip -- both
    hints exist because a bare "not found" message leaves the model
    unaware WHY the data is missing, causing it to trust noisy search
    results and fabricate instead of refusing. See
    docs/decisions/2026-08-18-q4-refusal-fix.md and
    docs/decisions/2026-08-19-fixing-6-accumulated-eval-findings.md."""
    message = (
        f"(no structured data found for metric={args.get('metric')!r} "
        f"ticker={args.get('ticker')!r} {args.get('fiscal_period')!r} "
        f"FY{args.get('fiscal_year')!r} — try search_filings instead)"
    )
    if args.get("fiscal_period") == "Q4":
        message += f" {_Q4_NOT_DISCLOSED_HINT}"
    never_tagged = _never_tagged_hint(args.get("ticker"), args.get("metric"))
    if never_tagged:
        message += f" {never_tagged}"
    return message


def _format_no_comparison_message(args: dict) -> str:
    """compare_financial_metric counterpart to _format_no_fact_message --
    the same Q4 reporting gap and never-tagged-concept gap both apply
    just as much to a cross-company comparison question as to a
    single-company one. The never-tagged hint only reflects the anchor
    company (args' `anchor_ticker`, this tool's ticker key), not every
    company in the comparison -- same scoping limit _never_tagged_hint()
    itself already documents, not a new one introduced here."""
    message = (
        f"(no structured data found for metric={args.get('metric')!r} "
        "across companies for this period — try search_filings per company instead)"
    )
    if args.get("fiscal_period") == "Q4":
        message += f" {_Q4_NOT_DISCLOSED_HINT}"
    never_tagged = _never_tagged_hint(args.get("anchor_ticker"), args.get("metric"))
    if never_tagged:
        message += f" {never_tagged}"
    return message


_INT_TYPE_VALIDATOR = jsonschema.Draft202012Validator({"type": "integer"})


def _is_valid_int(value) -> bool:
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


def call_get_financial_fact(args: dict, question: str | None = None) -> dict | None:
    """This is a real system boundary, not just an internal call — the
    model doesn't reliably respect the schema (e.g. it has called this
    with `metric` omitted entirely, or invented an unsupported `segment`
    filter). Validated generically by validate_tool_args at the boundary
    rather than trusting the schema was followed; this function only
    layers the business rules a flat schema check can't express. See
    docs/decisions/2026-08-19-fixing-6-accumulated-eval-findings.md and
    docs/decisions/2026-09-09-schema-driven-arg-validation.md.

    `yoy_growth=True` combined with a margin metric is rejected the same
    way: get_yoy_growth() only supports the raw tagged metrics (see its
    own docstring for why), so that combination isn't just unsupported,
    it's meaningless -- caught here rather than passed through.

    `start_fiscal_year`/`end_fiscal_year` (both required together, and
    rejected if combined with yoy_growth) dispatch to
    get_multi_year_average() instead of a single-period lookup (see that
    function's own docstring). Supported for every RATIO_DEFINITIONS
    metric -- formulas._get_annual_value() dispatches any of them
    generically (see its own docstring).

    `question` (optional -- only agent.py's tool-dispatch path has one;
    mcp_server.py's direct callers don't) is passed through to
    record_unmet_metric_request() purely for observability, see below.

    Records an unmet-metric-request event (see
    docs/decisions/2026-09-04-langfuse-tracing.md) when `metric` isn't
    recognized at all (reason="unknown_metric" -- the "should we add a
    formula for this" signal) or when it's a recognized metric/ratio but
    the underlying lookup -- get_metric(), get_ratio(), get_yoy_growth(),
    or get_multi_year_average(), all four genuine-data-lookup paths
    below -- found no data for this ticker/period
    (reason="no_data_for_ticker"). Deliberately NOT recorded for boundary
    rejections above (malformed/invented args, invalid yoy_growth/
    multi-year-average combinations) -- those are a schema-violation
    problem, not a "this formula doesn't exist yet" problem, and would
    just be noise on the signal."""
    if validate_tool_args("get_financial_fact", FACT_TOOL_SCHEMA, args, skip_properties=_FISCAL_YEAR_PROPS):
        return None
    ticker = args["ticker"]
    metric = args["metric"]
    if metric not in DEFAULT_METRIC_TAGS and metric not in RATIO_DEFINITIONS:
        # A recognized-shape-but-unsupported metric name (the one
        # violation validate_tool_args deliberately lets through) --
        # this belongs on the unmet-metric-request signal, not a local-
        # only tool_call_rejected event, since it's real evidence a
        # formula might be worth adding.
        record_unmet_metric_request(ticker, metric, reason="unknown_metric", question=question)
        return None
    fiscal_period = args.get("fiscal_period", "FY")
    period_end_date = args.get("period_end_date")
    start_fiscal_year = args.get("start_fiscal_year")
    end_fiscal_year = args.get("end_fiscal_year")
    if start_fiscal_year is not None or end_fiscal_year is not None:
        # Deliberately does not check plain fiscal_year here -- this
        # branch never reads it, so a value here is irrelevant.
        if args.get("yoy_growth") or not _is_valid_int(start_fiscal_year) or not _is_valid_int(end_fiscal_year):
            log_event(
                "tool_call_rejected", tool="get_financial_fact", reason="invalid_multi_year_average_combo", args=args
            )
            return None
        result = get_multi_year_average(ticker, metric, start_fiscal_year, end_fiscal_year)
        if result is None:
            record_unmet_metric_request(ticker, metric, reason="no_data_for_ticker", question=question)
        return result
    # Checked AFTER the multi-year-average branch above: that branch
    # never reads fiscal_year at all, so checking it any earlier would
    # wrongly reject a valid multi-year-average request over a stray,
    # irrelevant fiscal_year value -- this must only gate the two
    # branches below, which are the only ones that actually use it.
    if _rejects_invalid_fiscal_year("get_financial_fact", args):
        return None
    fiscal_year = args.get("fiscal_year")
    if args.get("yoy_growth"):
        if metric in RATIO_DEFINITIONS:
            log_event(
                "tool_call_rejected", tool="get_financial_fact", reason="yoy_growth_unsupported_for_ratio", args=args
            )
            return None
        result = get_yoy_growth(ticker, metric, fiscal_year, fiscal_period, period_end_date)
        if result is None:
            record_unmet_metric_request(ticker, metric, reason="no_data_for_ticker", question=question)
        return result
    if metric in RATIO_DEFINITIONS:
        result = get_ratio(ticker, metric, fiscal_year, fiscal_period, period_end_date)
    else:
        result = get_metric(ticker, metric, fiscal_year, fiscal_period, period_end_date)
    if result is None:
        record_unmet_metric_request(ticker, metric, reason="no_data_for_ticker", question=question)
    return result


def _format_fact_value(fact: dict) -> str:
    """Renders a fact's value for citation text. "raw" (the unit for any
    RATIO_DEFINITIONS entry with as_percent=False, e.g. asset_turnover/
    inventory_turnover) is an internal normalize()-category label from
    numeric_utils.py, not a natural-language unit -- omitted here so a
    plain ratio reads as "1.04", not the internal-sounding "1.04 raw"."""
    if fact["unit"] == "raw":
        return str(fact["value"])
    return f"{fact['value']} {fact['unit']}"


def _fact_as_result(fact: dict, args: dict) -> dict:
    """Wrap a get_financial_fact value in the same {text, metadata} shape
    hybrid_search results use, so it can share all_results/citation-key
    handling uniformly with search_filings results instead of needing a
    parallel code path."""
    return {
        "text": f"{args['metric']} = {_format_fact_value(fact)} (structured XBRL data, not filing prose)",
        "metadata": {
            "ticker": args["ticker"],
            "form": fact["form"],
            "filingDate": fact.get("filed") or fact["period_end"],
            "reportDate": fact["period_end"],
            "accessionNumber": fact["accession"],
            "chunk_index": "xbrl",
        },
    }


def call_compare_financial_metric(args: dict, question: str | None = None) -> dict[str, dict]:
    """Same boundary-validation reasoning as call_get_financial_fact —
    don't trust the schema was followed; validate_tool_args generically
    rejects an unrecognized extra key (e.g. an invented `segment` filter)
    rather than silently ignoring it. No yoy_growth here: there's no
    current evidence/use case for a cross-company YoY-growth comparison,
    so it isn't exposed on this tool (see get_yoy_growth()'s docstring).
    A ratio with `supports_cross_company=False` (return_on_assets/
    asset_turnover/cash_to_assets/inventory_turnover/rd_intensity) still
    passes this function's own boundary check (it's a real, known ratio
    name -- COMPARE_TOOL_SCHEMA's own metric enum is narrower, only
    _CROSS_COMPANY_RATIOS, but validate_tool_args lets any metric-enum
    violation through regardless of which schema declared it, deferring
    to this same broader RATIO_DEFINITIONS check), but
    get_ratio_all_companies() checks the flag internally and returns the
    same graceful `{}` any other unsupported metric gets -- see
    RATIO_DEFINITIONS' own comment for why there's no cross-company
    version of those five yet.

    Same unmet-metric-request tracing as call_get_financial_fact -- see
    that function's docstring. The
    `supports_cross_company=False` case above also lands in the generic
    `reason="no_data_for_ticker"` bucket rather than a third reason
    value: a human looking at the metric name in the Langfuse dashboard
    can already tell that case apart, not worth the extra complexity."""
    if validate_tool_args(
        "compare_financial_metric", COMPARE_TOOL_SCHEMA, args, skip_properties=frozenset({"fiscal_year"})
    ):
        return {}
    anchor_ticker = args["anchor_ticker"]
    metric = args["metric"]
    if metric not in DEFAULT_METRIC_TAGS and metric not in RATIO_DEFINITIONS:
        # See call_get_financial_fact's matching guard: a recognized-
        # shape-but-unsupported metric name belongs on the unmet-metric-
        # request signal, not a local-only tool_call_rejected event.
        record_unmet_metric_request(anchor_ticker, metric, reason="unknown_metric", question=question)
        return {}
    if _rejects_invalid_fiscal_year("compare_financial_metric", args):
        return {}
    fiscal_year = args.get("fiscal_year")
    fiscal_period = args.get("fiscal_period", "FY")
    period_end_date = args.get("period_end_date")
    if metric in RATIO_DEFINITIONS:
        result = get_ratio_all_companies(anchor_ticker, metric, fiscal_year, fiscal_period, period_end_date)
    else:
        result = get_metric_all_companies(anchor_ticker, metric, fiscal_year, fiscal_period, period_end_date)
    # anchor_ticker not in result (not just `not result`) matters:
    # instant metrics resolve each company independently with no
    # requirement that the requested anchor itself has data (e.g. PLTR
    # doesn't tag inventory but AAPL/MSFT do) -- a non-empty-but-anchor-
    # missing result must still record that the specific company asked
    # about has no data, even though everyone else's data is genuinely
    # returned. See
    # docs/decisions/2026-09-07-fix-get-metric-all-companies-instant-metrics.md.
    if not result or anchor_ticker not in result:
        record_unmet_metric_request(anchor_ticker, metric, reason="no_data_for_ticker", question=question)
    return result


def _comparison_as_results(data: dict[str, dict], metric: str) -> list[dict]:
    """Wrap a {ticker: fact} dict (from compare_financial_metric) as a
    list of {text, metadata} results, one per company, reusing the same
    shape _fact_as_result uses for a single company. A frames entry
    (duration metrics) doesn't carry a "form" field — "XBRL frame data"
    stands in for it rather than guessing 10-K vs. 10-Q. Instant metrics
    resolve independently per company via get_metric(), which DOES carry
    a real form — used when present via fact.get(...) instead of always
    hardcoding the frame fallback label. See
    docs/decisions/2026-09-07-fix-get-metric-all-companies-instant-metrics.md."""
    results = []
    for ticker, fact in sorted(data.items()):
        results.append(
            {
                "text": f"{ticker} {metric} = {_format_fact_value(fact)} (structured XBRL data, not filing prose)",
                "metadata": {
                    "ticker": ticker,
                    "form": fact.get("form", "XBRL frame data"),
                    "filingDate": fact["period_end"],
                    "reportDate": fact["period_end"],
                    "accessionNumber": fact["accession"],
                    "chunk_index": "xbrl",
                },
            }
        )
    return results


# ---------------------------------------------------------------------------
# calculate tool -- see CALCULATE_TOOL_SCHEMA's own comment and
# docs/decisions/2026-09-11-calculate-tool-and-stress-questions.md for
# the full design reasoning. Two independent guarantees: operand GROUNDING
# (_ground_operand, reusing _number_candidates -- the same primitive
# _verify_one_claim already trusts for a submit_answer claim) and
# arithmetic CORRECTNESS (call_calculate runs the operation in real
# Python, never the model's own mental math, per the PAL/Toolformer
# finding that LLM arithmetic itself is unreliable even when the model
# picks the right operation).
# ---------------------------------------------------------------------------
def _ground_operand(value: float, unit: str, citation_index: int, all_results: list[dict], operand_name: str) -> str | None:
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
        return (
            f"(operand {operand_name}: [{citation_index}] is not a valid citation index -- "
            f"results are numbered 1-{len(all_results)})"
        )
    source_text = all_results[citation_index - 1]["text"]
    category, norm = normalize(value, unit)
    tolerance = max(0.01 * abs(norm), 0.05)
    candidates = _number_candidates(source_text)
    if any(c == category and abs(v - norm) <= tolerance for c, v in candidates):
        return None

    for other_unit in _CLAIM_UNITS:
        if other_unit == unit:
            continue
        other_category, other_norm = normalize(value, other_unit)
        other_tolerance = max(0.01 * abs(other_norm), 0.05)
        if any(c == other_category and abs(v - other_norm) <= other_tolerance for c, v in candidates):
            return (
                f"({operand_name}={value} is not a {unit} value in result [{citation_index}] -- "
                f"that result's own number matches {value} interpreted as {other_unit} instead; "
                f"double check {operand_name}'s UNIT specifically)"
            )

    for other_index, other_result in enumerate(all_results, start=1):
        if other_index == citation_index:
            continue
        other_candidates = _number_candidates(other_result["text"])
        if any(c == category and abs(v - norm) <= tolerance for c, v in other_candidates):
            return (
                f"({operand_name}={value} ({unit}) is not in result [{citation_index}] -- "
                f"it matches result [{other_index}] instead; double check {operand_name}'s "
                "CITATION INDEX specifically, not its value or unit)"
            )

    return (
        f"({operand_name}={value} ({unit}) does not appear under ANY unit in result [{citation_index}], "
        "nor under this same unit in any other result you've retrieved -- this is not a retryable mistake. "
        "If this is a unit-conversion constant (e.g. dividing by 1,000,000,000 to convert to billions), do "
        "not use calculate for that at all -- state the converted value directly instead, citing the same "
        "source, per system-prompt rule 9. Otherwise, this operand simply isn't grounded in anything you've "
        "retrieved.)"
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
        return None, "(your calculate call didn't match the required schema)"

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
        return None, (
            f"(cannot {operation} a {category_a} value and a {category_b} value -- "
            "both operands must be the same kind of quantity)"
        )

    if operation in ("divide", "percent_of", "percent_change") and norm_b == 0:
        return None, f"(cannot {operation.replace('_', ' ')}: operand_b is zero)"

    if operation == "add":
        value, unit = norm_a + norm_b, ("percent" if category_a == "percent" else "raw")
    elif operation == "subtract":
        value, unit = norm_a - norm_b, ("percent" if category_a == "percent" else "raw")
    elif operation == "multiply":
        value, unit = norm_a * norm_b, "raw"
    elif operation == "divide":
        value, unit = round(norm_a / norm_b, 2), "raw"
    elif operation == "percent_of":
        value, unit = round(norm_a / norm_b * 100, 1), "percent"
    else:  # percent_change
        value, unit = round((norm_a - norm_b) / norm_b * 100, 1), "percent"

    return {"value": value, "unit": unit}, None


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
        expression = f"percentage change from {value_b} {unit_b} to {value_a} {unit_a}"
    elif operation == "percent_of":
        expression = f"{value_a} {unit_a} as a percentage of {value_b} {unit_b}"
    else:
        expression = f"{value_a} {unit_a} {operation} {value_b} {unit_b}"

    formatted_result_value = _format_computed_number(result["value"])
    formatted_value = formatted_result_value if result["unit"] == "raw" else f"{formatted_result_value} {result['unit']}"
    return {
        "text": (
            f"{expression} = {formatted_value} (computed value, not directly stated in any "
            f"filing; operands from results [{idx_a}] and [{idx_b}])"
        ),
        "metadata": {
            "ticker": "N/A",
            "form": "computed value",
            "filingDate": "N/A",
            "reportDate": "N/A",
            "accessionNumber": "N/A",
            "chunk_index": "calculated",
        },
    }


_CITATION_MARKER = re.compile(r"\[(\d+)\]")
_CITATION_WINDOW_CHARS = 150

# Broader than _CITATION_MARKER on purpose: matches a comma-separated
# multi-source bracket like "[1, 3, 5]" too, not just a single-index
# "[1]". _CITATION_MARKER can't just be widened to cover this -- the OLD
# prose pipeline below (_iter_citation_claims/_iter_uncited_claims) walks
# it marker-by-marker via finditer() and reads group(1) as ONE index, so
# widening it would break that per-index logic, not just the pattern.
# This one exists solely for verify_claims()'s coverage check, which
# only needs to strip citation-marker-SHAPED text before scanning for
# numbers -- it never reads the indices out (a bracket's own bare digits
# would otherwise be extracted as spurious uncovered-number claims). See
# docs/decisions/2026-09-10-structured-claims-citation-verification.md.
_ANY_CITATION_BRACKET = re.compile(r"\[\s*\d+(?:\s*,\s*\d+)*\s*\]")

# Text that looks number-shaped but isn't a claim to verify -- stripped
# from the claim window before extraction, not from numeric_utils.py's
# shared extract_numbers() itself, since grade_numeric() doesn't have
# this false-positive problem (it only needs ONE number in the whole
# answer to match, so spurious extras there are harmless noise, not
# wrong verdicts) and stripping this there could hide a genuine
# date/form-shaped ground-truth value in some future question type.
# Four patterns, each found live rather than anticipated up front -- see
# docs/decisions/2026-08-17-citation-verification-pass.md (dates, bare
# years, 10-K/10-Q) and docs/decisions/2026-09-10-structured-claims-citation-verification.md
# (Note N, N-year/N-day) for the corpus evidence behind each:
#   - Dates ("June 27, 2026" -> 27, 2026), the single biggest noise
#     source on a real multi-sentence answer.
#   - Bare year-like numbers ("fiscal Q3 2025" -> the 2025 survives the
#     date pattern above since it's not glued to a month name) -- a
#     standalone 1900-2099 number next to a citation is virtually always
#     a period label, not a numeric claim.
#   - "10-K"/"10-Q" (the only two form types this project ingests, see
#     edgar_ingest.py's FORM_TYPES) -- "10" isn't glued to a preceding
#     letter (there's a space before it), so the digit-glued-to-letter
#     fix in numeric_utils.py doesn't catch it.
#   - "Note 1"/"Note 12" (a footnote/financial-statement-note reference)
#     and "3-year"/"5-day" (an ordinal/count phrase, often echoing the
#     question's own wording, e.g. "3-year average operating margin") --
#     a bare `1` or `3` from either shape sitting near a real citation
#     would otherwise be treated as its own spurious claim.
_NON_CLAIM_PATTERN = re.compile(
    r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+\d{1,2},?\s+\d{4}\b|\b\d{4}-\d{2}-\d{2}\b|\b(?:19|20)\d{2}\b|\b10-[KQ]\b"
    r"|\bNote\s+\d+\b|\b\d+-(?:year|day)s?\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Structured-claims quote grounding -- verifies a submit_answer claim's
# `quote` genuinely appears in its cited source chunk, allowing for
# reformatting/paraphrase but not fabrication. See
# docs/decisions/2026-09-10-structured-claims-citation-verification.md
# for the full design reasoning behind every choice below.
# ---------------------------------------------------------------------------
_QUOTE_MIN_CHARS = 15  # a 2-character quote like "$5" would match almost any source trivially
# Lives in numeric_utils.QUOTE_COVERAGE_THRESHOLD, alongside
# text_coverage(), so table_grounding.py's region-scoped check can share
# the identical threshold. Kept as an alias, not a second constant, since
# every existing call site in this module refers to it by this name. See
# docs/decisions/2026-09-13-table-grounding-region-scoped-matching.md.
_QUOTE_COVERAGE_THRESHOLD = QUOTE_COVERAGE_THRESHOLD
_QUOTE_ANCHOR_CHARS = 30  # a real quote's whole span usually appears as one long contiguous match
# A bare-number quote (no surrounding prose -- e.g. quoting an XBRL fact's
# raw value directly, "391035000000") needs a different length bar than
# prose: DIGIT count, not character count, is what makes a number
# specific enough to trust -- a 12-character bare number is under
# _QUOTE_MIN_CHARS (15) despite being an unambiguous, correct quote,
# and a 6+ digit number is astronomically unlikely to match by
# coincidence even though it's short as text. See
# docs/decisions/2026-09-10-structured-claims-citation-verification.md.
_BARE_NUMBER_MIN_DIGITS = 6


# Lives in numeric_utils.normalize_for_match so table_grounding.py can
# share the exact same implementation without a circular import
# (table_grounding is imported BY agent.py, so it can't import back from
# agent.py). Kept as an alias, not re-exported under a new name, since
# every existing call site and test in this module refers to it as
# `_normalize_for_match`. See
# docs/decisions/2026-09-12-structure-aware-table-quote-grounding.md.
_normalize_for_match = normalize_for_match


def _quote_is_long_enough(quote_norm: str) -> bool:
    """Shared length gate for a normalized quote, used by both
    _quote_matches() and _verify_one_claim()'s own pre-check -- both
    call sites must share this exactly, not each run their own plain
    len(quote_norm) < _QUOTE_MIN_CHARS check, or one could silently miss
    the digit-count exception below and reproduce the exact bare-XBRL-
    number false positive that exception exists to fix. See
    _BARE_NUMBER_MIN_DIGITS's own comment for why a short-as-text bare
    number can still be long/specific enough to trust."""
    digit_count = sum(ch.isdigit() for ch in quote_norm)
    return len(quote_norm) >= _QUOTE_MIN_CHARS or digit_count >= _BARE_NUMBER_MIN_DIGITS


def _quote_matches(quote: str, source: str) -> bool:
    """True if `quote` is genuinely present in `source`, allowing for
    reformatting/paraphrase but not fabrication.

    A quote shorter than _QUOTE_MIN_CHARS (normalized) is rejected
    outright -- too short to tell a real match from a coincidence.

    Exact-substring match (after normalization) is the fast path.
    Otherwise falls back to a COVERAGE ratio via difflib.SequenceMatcher
    -- deliberately NOT .ratio(), which scores a short quote against a
    much longer chunk near zero even on exact containment (ratio is
    symmetric -- 2*matches/(len(a)+len(b)) -- but "is the quote IN the
    source" is not a symmetric relationship: it cares only how much of
    the QUOTE is covered, not how much of the source is). Coverage is
    the sum of matched-block lengths divided by the quote's own length.

    `autojunk=False` is mandatory, not a style choice: SequenceMatcher's
    autojunk heuristic is keyed off len(b) -- here, the QUOTE
    (quote_norm is passed as the third/`b` argument below, source_norm
    as the second/`a`), not the source chunk. Once a quote reaches 200+
    normalized characters, autojunk treats any character appearing in
    more than ~1% of IT as "popular" junk excluded from the initial
    anchor search -- effectively every common letter in ordinary prose
    -- and match quality collapses silently (no error, just a wrong low
    score) whenever the quote also isn't a clean exact substring of the
    source. Covered by a dedicated regression test (which actually
    exercises this by building a 200+ character QUOTE, not just a long
    source -- an earlier version of that test got this backwards), not
    assumed to stay correct.

    The `longest`-contiguous-block floor guards the coverage metric's one
    real weakness: get_matching_blocks() finds a common SUBSEQUENCE, not
    a single contiguous match, so a fabricated quote assembled from words
    scattered across the source could otherwise accumulate high coverage
    from many small, unrelated fragments. Requiring one long contiguous
    run makes that construction much harder to pass by accident.

    Length gate accepts EITHER _QUOTE_MIN_CHARS of prose OR
    _BARE_NUMBER_MIN_DIGITS of digits -- see that constant's own comment
    for why a short-as-text bare number can still be long/specific
    enough to trust (e.g. a bare XBRL value like "391035000000" is 12
    characters, under 15, but is exactly the kind of quote this exists
    to accept, not reject).

    The actual coverage/anchor computation is numeric_utils.text_coverage
    (lives there so table_grounding.py can share the identical logic
    against a narrower region, without a circular import back to this
    module -- see
    docs/decisions/2026-09-13-table-grounding-region-scoped-matching.md)
    -- this function is now just that primitive plus the
    length gate and this module's own anchor-floor threshold."""
    quote_norm = _normalize_for_match(quote)
    if not _quote_is_long_enough(quote_norm):
        return False
    exact, coverage, longest = text_coverage(quote, source)
    if exact:
        return True
    return coverage >= _QUOTE_COVERAGE_THRESHOLD and longest >= min(_QUOTE_ANCHOR_CHARS, len(quote_norm))


def _number_candidates(text: str, *, unit_source: str | None = None) -> list[tuple[str, float]]:
    """Every (category, comparable_number) `text` could plausibly
    support -- not just each number under its own immediately-adjacent
    unit, but also each bare/raw number reinterpreted under any unit
    word mentioned ANYWHERE in `unit_source` (defaulting to `text`
    itself, which is byte-for-byte the original, single-argument
    behavior this generalizes -- see below).

    SEC filing tables routinely state a unit once in a caption
    ("Remaining performance obligation consisted of the following (in
    billions):") and leave the actual cell values bare ("$72.4"), so a
    per-cell extract_numbers() reads $72.4 as 72.4 raw, not 72.4
    billion -- a real, correctly-answered question was once wrongly
    refused this way (see
    docs/decisions/2026-09-10-structured-claims-citation-verification.md).
    This only ADDS candidate interpretations (a raw number can still
    also match as raw) -- it never removes a way for a genuine mismatch
    to be caught.

    `unit_source` is what lets the structured-claims verifier check a claim's short
    `quote` (which usually won't itself restate a caption-only unit)
    against its cited chunk's full text as the place the caption lives,
    without requiring the model to have copied the caption into the
    quote. The old prose-verification path (_iter_citation_claims below)
    still calls this with a single argument, so unit_source defaults to
    `text` and that path's behavior is completely unchanged."""
    source = text if unit_source is None else unit_source
    numbers = extract_numbers(text)
    candidates = [normalize(v, u) for v, u in numbers]
    source_lower = source.lower()
    for caption_unit in UNIT_MULTIPLIERS:
        if caption_unit in source_lower:
            candidates.extend(normalize(v, caption_unit) for v, u in numbers if u == "raw")
    return candidates


def _iter_citation_claims(answer_text: str, all_results: list[dict]):
    """Shared walk over every numeric claim found near a citation marker
    in `answer_text` — yields (citation_index, claimed_value,
    claimed_unit, verified) for each one, where `verified` is whether
    the claim's own cited source text actually contains a matching
    number. verify_citations() and value_is_citation_verified() are both
    just different ways of consuming this same walk: the former collects
    every unverified claim into warning strings, the latter checks
    whether a single target value's claims are ever verified.

    For each citation marker, only the text since the previous citation
    marker (capped at _CITATION_WINDOW_CHARS) is checked, so a claim
    isn't accidentally "verified" by a number attributed to an earlier
    citation elsewhere in the same sentence. Known limitation: an answer
    that shows multi-step derivation work *between* a claim and its
    citation (e.g. a LaTeX-style calculation block) can still smuggle
    the correct intermediate numbers into that window and dodge
    detection — this is a best-effort heuristic, not an exhaustive
    grounding check."""
    window_start = 0
    for match in _CITATION_MARKER.finditer(answer_text):
        n = int(match.group(1))
        window = answer_text[max(window_start, match.start() - _CITATION_WINDOW_CHARS) : match.start()]
        window_start = match.end()
        if not (1 <= n <= len(all_results)):
            continue

        claimed = extract_numbers(_NON_CLAIM_PATTERN.sub("", window))
        if not claimed:
            continue

        source_normalized = _number_candidates(all_results[n - 1]["text"])
        for value, unit in claimed:
            category, norm = normalize(value, unit)
            tolerance = max(0.01 * abs(norm), 0.05)
            verified = any(c == category and abs(sn - norm) <= tolerance for c, sn in source_normalized)
            yield n, value, unit, verified


# Sentence-ending punctuation followed by whitespace signals a break
# UNLESS what comes after that whitespace is a citation marker
# ("...total. [1]" is one sentence, not two) or a lowercase letter (an
# abbreviation like "U.S." continuing mid-clause, not a real sentence
# start -- without this exclusion, "... primarily from U.S. sales [1]"
# registers a false break, wrongly refusing an otherwise-correct answer).
#
# Both lookaheads deliberately sit INSIDE the pattern (matching only the
# punctuation character itself, zero-width beyond it) rather than
# consuming "\s+" before checking what follows -- a version that
# consumes "\s+" first (`r"[.!?]\s+(?![\[a-z])"`) lets the greedy `\s+`
# backtrack to a SHORTER whitespace match whenever the maximal one fails
# the lookahead, so "billion.  [1]" (two spaces) still registers a false
# break via the first space alone. `(?!\s*[\[a-z])` checks ALL possible
# amounts of trailing whitespace at once (a negative lookahead has no
# successful match to backtrack away from), so it's immune to this
# regardless of how much whitespace follows. See
# docs/decisions/2026-09-09-citation-gap-frame-ordering-retrieval-verify.md.
#
# Residual, deliberately-not-fixed gaps this still doesn't catch: a
# marker with NO whitespace after the preceding period at all
# ("[1].Revenue...", judged too rare in real LLM output -- and too easy
# to over-fix into misreading a decimal point like "109.4" as a break --
# to be worth the added complexity); and a genuine new sentence that
# happens to start with a lowercase word (rare in real prose, and a
# false NEGATIVE -- silently missing a break -- rather than the false
# POSITIVE (wrongly refusing a correct answer) the lowercase exception
# exists to prevent, so accepted as the safer side to err on.
_SENTENCE_BREAK = re.compile(r"[.!?](?=\s)(?!\s*[\[a-z])")


def _iter_uncited_claims(answer_text: str):
    """Yields (value, unit) for every numeric claim in `answer_text` that
    has NO citation marker attached to it -- the counterpart gap
    _iter_citation_claims() above can't see, since that walk is driven
    entirely by _CITATION_MARKER matches: a claim with no marker nearby
    never enters that loop at all. See
    docs/decisions/2026-09-09-citation-gap-frame-ordering-retrieval-verify.md
    for the real, observed case (msft-cash-to-assets-fy2025) this closes
    -- a self-computed value stated with no citation marker nearby sailed
    through unrefused despite violating the same "every numeric claim
    must trace to a source" principle _iter_citation_claims() enforces
    for the cited case.

    Current contract: each marker attaches to EVERY REACHABLE claim on
    ONE side of it -- all reachable claims immediately before it (the
    dominant "$X [1]." convention), or, only if NONE is reachable on
    that side, all reachable claims immediately after it (the "Per
    source [1], $X" convention). Never both sides for the same marker.
    A claim is "reachable" from a marker if it's within
    _CITATION_WINDOW_CHARS and no sentence boundary (_SENTENCE_BREAK,
    with an exception for a period immediately followed by a marker --
    "...total. [1]" is one sentence, not two) separates them.

    "Every reachable claim," not just the nearest one, matters: a marker
    attaching to only its single nearest claim (an earlier version of
    this function) broke a common, legitimate phrasing -- "Revenue grew
    from $10 million to $12 million, a 20% increase [1]." states THREE
    numbers all genuinely grounded in one source, and attaching [1] to
    only the last one (20%) left the other two unattached to any
    citation at all, wrongly flagged as uncited even though they're
    correct. Covering the whole reachable side lets _iter_citation_claims()
    above independently verify each one against the source for accuracy
    (unaffected by this function) while this function only answers "does
    it have a citation at all." "Never both sides" is still what keeps
    the original bug fixed: "$20 billion [1], representing approximately
    4.0% of total assets" has one claim on each side of [1], and the
    4.0% (an ungrounded, self-computed figure, not a second grounded
    fact) must stay unattached -- see
    docs/decisions/2026-09-09-citation-gap-frame-ordering-retrieval-verify.md
    for the full history of designs tried and rejected against this
    codebase's own existing test cases.

    Two implementation notes:
    - Operates on the UNTOUCHED original answer_text throughout, never a
      sliced/re-stripped substring -- unlike _iter_citation_claims(),
      which only needs positions relative to an already-sliced window,
      this function measures distance/sentence-membership in the whole
      text, so re-slicing would silently drift the offsets.
    - marker_spans excludes the bare digit INSIDE a "[n]" marker itself
      from candidate claims -- NUMBER_PATTERN also matches it (documented
      harmless noise for extract_numbers()'s other callers), but left in
      here it would count as its own unverifiable claim whenever it's
      the LAST marker in the answer."""
    non_claim_spans = [m.span() for m in _NON_CLAIM_PATTERN.finditer(answer_text)]
    marker_spans = [m.span() for m in _CITATION_MARKER.finditer(answer_text)]
    # Computed once on the untouched full text, not via a range-restricted
    # search per claim/marker pair -- pos/endpos-restricted re.search()
    # makes a lookahead assertion (the "(?!\[)" above) unable to see past
    # endpos, so a break's own trailing-marker exception would silently
    # misfire if checked with the search range clipped right before that
    # marker. Precomputing on the full string sidesteps that entirely.
    sentence_breaks = [m.start() for m in _SENTENCE_BREAK.finditer(answer_text)]

    def _reachable(lo: int, hi: int) -> bool:
        return (hi - lo) <= _CITATION_WINDOW_CHARS and not any(lo <= b < hi for b in sentence_breaks)

    excluded_spans = non_claim_spans + marker_spans
    claims = [
        (value, unit, start, end)
        for value, unit, start, end in extract_numbers_with_spans(answer_text)
        if not any(s <= start < e for s, e in excluded_spans)
    ]

    covered_spans = set()
    for m_start, m_end in marker_spans:
        before = [(s, e) for _, _, s, e in claims if e <= m_start and _reachable(e, m_start)]
        if before:
            covered_spans.update(before)
            continue
        after = [(s, e) for _, _, s, e in claims if s >= m_end and _reachable(m_end, s)]
        covered_spans.update(after)

    for value, unit, start, end in claims:
        if (start, end) not in covered_spans:
            yield value, unit


CitationWarning = NamedTuple(
    "CitationWarning",
    [
        ("check", str),  # "cited_claim_unsupported" | "uncited_claim"
        ("citation_index", int | None),  # the [n] this warning is about, or None for the uncited check
        ("value", float),
        ("unit", str),
        ("message", str),  # the exact string verify_citations() has always returned for this warning
    ],
)


def collect_citation_warnings(answer_text: str, all_results: list[dict]) -> list["CitationWarning"]:
    """Structured counterpart to verify_citations() below -- same two
    checks, same dedup, same warning text, but tagged with WHICH check
    produced each one and what citation index (if any) it's about.
    verify_citations() is now a one-line `.message` projection of this.

    Added for the citation-gate FP/FN measurement work (see
    docs/decisions/2026-09-10-citation-gate-measurement-instrumentation.md):
    that work needs to break false positives down by which of the two
    checks fired, and inferring that from a warning string's wording
    would be exactly the kind of fragility the rest of this file's
    comments warn against. Tag at construction instead.

    `message` MUST stay byte-identical to what this function used to
    return as a bare string -- _format_refusal_message() and
    _format_citation_retry_message() interpolate these into prompt text
    sent back to the model, so changing the wording would change model
    behavior and perturb the very population the measurement work is
    trying to observe."""
    # Two dedup sets, deliberately not one: a single value+unit-only key
    # (fixing the cross-loop duplicate below) ALSO collapses two
    # genuinely different, independently-broken citations that happen to
    # share a value --
    # "$99 million [1]. ... $99 million [2]." with neither source
    # containing 99 -- into one warning, silently dropping that [2] is
    # ALSO broken. `seen_citation_keys` keeps citation-claims' own dedup
    # precise (index + value, so different citation indices stay
    # distinct); `seen_values` is value+unit only, populated by
    # citation-claims and checked by the uncited-claims loop below, for
    # the DIFFERENT problem that loop exists to solve: with two
    # sentences like "Total costs were $30 million. Total revenue was
    # $50 million [1]." (source backs only $50M), _iter_citation_claims's
    # flat backward window (no sentence-boundary awareness, unlike
    # _iter_uncited_claims) still attributes the unrelated "$30 million"
    # to [1] and flags it as misattributed, while _iter_uncited_claims
    # separately (and also correctly, by ITS OWN sentence-aware
    # definition) finds no marker actually reachable from "30" and would
    # flag it as uncited too -- the same claim occurrence producing two
    # different, redundant messages. citation-claims (more specific/
    # actionable) runs first and wins the wording in that case.
    warnings: list[CitationWarning] = []
    seen_citation_keys: set[tuple[str, str]] = set()
    seen_values: set[str] = set()
    for n, value, unit, verified in _iter_citation_claims(answer_text, all_results):
        if verified:
            continue
        citation_key = (str(n), f"{value}{unit}")
        if citation_key in seen_citation_keys:
            continue
        seen_citation_keys.add(citation_key)
        seen_values.add(f"{value}{unit}")
        warnings.append(
            CitationWarning(
                check="cited_claim_unsupported",
                citation_index=n,
                value=value,
                unit=unit,
                message=f"[{n}] claims {value} ({unit}) but that value doesn't appear in the cited source",
            )
        )
    for value, unit in _iter_uncited_claims(answer_text):
        value_key = f"{value}{unit}"
        if value_key in seen_values:
            continue
        seen_values.add(value_key)
        warnings.append(
            CitationWarning(
                check="uncited_claim",
                citation_index=None,
                value=value,
                unit=unit,
                message=(
                    f"claims {value} ({unit}) but no citation marker appears anywhere "
                    "near it to trace the claim to a source"
                ),
            )
        )
    return warnings


def verify_citations(answer_text: str, all_results: list[dict]) -> list[str]:
    """Cheap, deterministic check for one specific silent-misgrounding
    pattern: a numeric claim attributed to a citation whose own cited
    source text doesn't contain that number. No model call needed —
    reuses the same number-extraction/normalization eval_harness.py's
    numeric grading already does (now in numeric_utils.py), applied to
    the cited result's text instead of a ground-truth expected value.

    Motivated by a real, observed case (see
    docs/decisions/2026-08-17-citation-verification-pass.md,
    aapl-revenue-growth-q3fy2026): asked for a computed ratio with no
    supporting tool, the model self-computed a percentage from two raw
    dollar figures (violating rule 3, "don't combine or infer numbers")
    and cited both dollar-figure sources for a percentage that appears
    in NEITHER of them. Built to catch exactly that shape of problem.

    Also flags a numeric claim with NO citation marker anywhere near it
    at all -- see _iter_uncited_claims()'s own docstring for the second
    real, observed case (msft-cash-to-assets-fy2025) this closes.

    Returns a list of human-readable warning strings (deduplicated),
    empty if nothing looks unverified. Thin wrapper around
    collect_citation_warnings() -- see that function for the actual
    logic; this one exists because most callers only need the message,
    not which check produced it."""
    return [w.message for w in collect_citation_warnings(answer_text, all_results)]


def value_is_citation_verified(value: float, unit: str, answer_text: str, all_results: list[dict]) -> bool:
    """Whether `value` is properly grounded everywhere it's cited in
    `answer_text` — the targeted counterpart to verify_citations() above,
    used by eval_harness.py to check ONE specific expected value instead
    of scanning every claim in the answer.

    Built for eval_harness.py's grade_numeric()/grade_comparison(): they
    only check whether the expected value appears somewhere in the
    answer text, which can't tell a correctly-cited answer from one that
    states the right number but attaches it to the wrong source -- the
    wrong-chunk-citation case is exactly the kind of silent misgrounding
    verify_citations() already catches for OTHER claims; this wires that
    same check into what decides pass/fail for the specific value a
    question is graded on. See
    docs/decisions/2026-08-18-citation-verification-wired-into-eval-gate.md.

    Returns True if `value` is never attached to a citation at all
    (nothing to contradict a plain-text match), or if AT LEAST ONE of
    its citations is properly grounded — a redundant second, wrong
    citation for an otherwise-correct value shouldn't fail the check.
    Returns False only if every citation attached to it fails
    verification."""
    target_category, target_norm = normalize(value, unit)
    tolerance = max(0.01 * abs(target_norm), 0.05)

    matches = []
    for _, claimed_value, claimed_unit, verified in _iter_citation_claims(answer_text, all_results):
        category, norm = normalize(claimed_value, claimed_unit)
        if category == target_category and abs(norm - target_norm) <= tolerance:
            matches.append(verified)
    return True if not matches else any(matches)


def _quote_grounded_in_source(value: float, unit: str, quote: str, source_text: str) -> bool:
    """Whether `quote` genuinely supports a claimed (value, unit) against
    `source_text` -- table-aware where possible, falling back to the
    flat-text _quote_matches() otherwise.

    If the claimed value can be located in a parsed table cell in
    `source_text`, that structural check is AUTHORITATIVE: it decides
    the outcome, with no fallback to _quote_matches() even if the
    structural check fails -- a deliberate design choice, not a default.
    _quote_matches's flat coverage/anchor-floor check accepts several
    real misattributions on this exact table shape whenever a segment
    label happens to be long enough (wrong fiscal period, a 10x-inflated
    value, a nine-month figure misquoted as a quarterly one), so letting
    it rescue a structural rejection would silently reopen exactly the
    holes this module closes. See
    docs/decisions/2026-09-12-structure-aware-table-quote-grounding.md.

    `quote_is_grounded()` matches against a tightly-scoped per-cell
    region (the table's own leading caption/header rows, plus the cell's
    own governing group label, plus the cell's own data row -- see
    table_grounding.GroundedCell) rather than a fixed word-vocabulary
    list, so a genuinely faithful multi-value row quote (e.g. a table row
    stating Current/Noncurrent/Total together) isn't wrongly refused for
    citing sibling-column content, while still rejecting the row-splice/
    cross-segment-steal attacks this module exists to block (verified
    directly, not assumed -- see tests/test_table_grounding.py). See
    docs/decisions/2026-09-13-table-grounding-region-scoped-matching.md
    for the region-scoped redesign this reflects.

    If the value isn't in any table cell (no table in this source, or a
    genuinely prose-stated value), that's not evidence of anything --
    it falls through to the ordinary flat-text check unchanged."""
    cells = locate_value(extract_table_blocks(source_text), value, unit)
    if cells:
        return any(quote_is_grounded(quote, cell) for cell in cells)
    return _quote_matches(quote, source_text)


def _verify_one_claim(claim: dict, all_results: list[dict]) -> "CitationWarning | None":
    """Checks one submit_answer claim against its own cited source:
    citation index in range, quote long enough to mean anything, quote
    genuinely present in that source (_quote_grounded_in_source -- see
    its own docstring for the table-aware/flat-text split), and the
    claimed value actually attributable to that quote specifically (via
    _number_candidates, using the FULL source chunk as unit_source so a
    caption-only unit still resolves -- see that function's own
    docstring). Returns None when all four pass. Checked in this order
    deliberately: each later check assumes the earlier ones already
    held (there's no source to check a value against until the index is
    known valid; no point fuzzy-matching a quote too short to mean
    anything)."""
    n = claim["citation_index"]
    value, unit, quote = claim["value"], claim["unit"], claim["quote"]
    if not (1 <= n <= len(all_results)):
        return CitationWarning(
            check="citation_out_of_range",
            citation_index=n,
            value=value,
            unit=unit,
            message=f"[{n}] is not a valid citation index -- results are numbered 1-{len(all_results)}",
        )
    source_text = all_results[n - 1]["text"]
    if not _quote_is_long_enough(_normalize_for_match(quote)):
        return CitationWarning(
            check="quote_too_short",
            citation_index=n,
            value=value,
            unit=unit,
            message=f"[{n}] claims {value} ({unit}) but its quote {quote!r} is too short to verify",
        )
    if not _quote_grounded_in_source(value, unit, quote, source_text):
        return CitationWarning(
            check="quote_not_found",
            citation_index=n,
            value=value,
            unit=unit,
            message=f"[{n}] claims {value} ({unit}) but the quoted text doesn't appear in source [{n}]",
        )
    category, norm = normalize(value, unit)
    tolerance = max(0.01 * abs(norm), 0.05)
    quote_candidates = _number_candidates(quote, unit_source=source_text)
    if not any(c == category and abs(v - norm) <= tolerance for c, v in quote_candidates):
        return CitationWarning(
            check="value_not_in_quote",
            citation_index=n,
            value=value,
            unit=unit,
            message=f"[{n}] claims {value} ({unit}) but that value doesn't appear in the quoted text",
        )
    return None


def verify_claims(claims: list[dict], all_results: list[dict], question: str, answer_text: str) -> list["CitationWarning"]:
    """Structured-claims counterpart to collect_citation_warnings() above,
    used when the model answers via submit_answer (SUBMIT_TOOL_SCHEMA)
    instead of free-text prose with [n] markers. See
    docs/decisions/2026-09-10-structured-claims-citation-verification.md
    for the full design.

    Two passes: first, each claim is checked independently against its
    own cited source (_verify_one_claim) -- citation index in range,
    quote long enough, quote genuinely present in that source, and the
    claimed value attributable to that specific quote. Second, a
    COVERAGE cross-check scans `answer_text` for numbers and requires
    each to match some claim's normalized (value, unit) within the same
    1%-relative/0.05-floor tolerance grade_numeric() uses -- this is what
    stops the model from writing an ungrounded number in prose while
    conveniently leaving it out of `claims` to dodge the first pass.

    A number that also appears in `question` is exempt from the coverage
    check: it's the model repeating what the user asked, not a claim the
    model is asserting (kills "3-year"-shaped noise and date/fiscal-year
    echoes at the source, without needing a claims entry for them) -- an
    accepted tradeoff, see the decision file above. `_NON_CLAIM_PATTERN`
    (dates, bare years, 10-K/10-Q, Note N, N-year/N-day) is stripped from
    both `question` and `answer_text` before extraction, same noise
    filter collect_citation_warnings() already relies on."""
    warnings = [w for w in (_verify_one_claim(c, all_results) for c in claims) if w is not None]

    claimed_normalized = [normalize(c["value"], c["unit"]) for c in claims]
    question_numbers = extract_numbers(_NON_CLAIM_PATTERN.sub("", question))
    # Strip [n]/[n, m, ...] citation markers before extracting --
    # otherwise a bare digit INSIDE a marker (e.g. the "1" in "[1]", or
    # each of 1/3/5 in a multi-source "[1, 3, 5]") is itself picked up as
    # its own spurious uncovered claim. _ANY_CITATION_BRACKET (not
    # _CITATION_MARKER) specifically to also catch the multi-index form
    # -- see that constant's own comment.
    answer_numbers = extract_numbers(_NON_CLAIM_PATTERN.sub("", _ANY_CITATION_BRACKET.sub("", answer_text)))

    def _covered(category: str, norm: float, tolerance: float) -> bool:
        if any(c == category and abs(v - norm) <= tolerance for c, v in claimed_normalized):
            return True
        for q_value, q_unit in question_numbers:
            q_category, q_norm = normalize(q_value, q_unit)
            if q_category == category and abs(q_norm - norm) <= tolerance:
                return True
        return False

    seen_uncovered: set[tuple[str, float]] = set()
    for value, unit in answer_numbers:
        category, norm = normalize(value, unit)
        if _covered(category, norm, max(0.01 * abs(norm), 0.05)):
            continue
        key = (category, norm)
        if key in seen_uncovered:
            continue
        seen_uncovered.add(key)
        warnings.append(
            CitationWarning(
                check="uncovered_number",
                citation_index=None,
                value=value,
                unit=unit,
                message=f"claims {value} ({unit}) but no claim in your submit_answer call covers it",
            )
        )
    return warnings


# Backends allowed to get the citation-verification retry (see
# _should_retry_for_citations below). Gated to Gemini only -- this exact
# mechanism was already tried against Ollama once and reverted after
# qwen2.5:7b-instruct proved unable to reliably act on the corrective
# feedback (giving up on an already-correct answer, or fabricating an
# estimate under retry pressure); a single clean Gemini re-run can't
# outweigh that documented Ollama history against its own known
# run-to-run noise, so the retry stays scoped to the backend it was
# actually re-verified for. See
# docs/decisions/2026-08-18-citation-retry-loop-v1-tried-reverted.md and
# docs/decisions/2026-08-25-citation-retry-loop-gemini-gated.md.
_CITATION_RETRY_BACKENDS = {"gemini"}


def _should_retry_for_citations(citation_warnings: list[str], already_retried: bool, backend: str) -> bool:
    """Whether run_agent() should give the model one corrective retry
    turn for its own unverified citation(s). True only when there's
    something to correct, the single retry (see
    _format_citation_retry_message below) hasn't already been spent this
    conversation -- capped at one retry, sharing run_agent()'s existing
    MAX_TOOL_ITERATIONS budget rather than a separate one -- and
    `backend` is one this retry is actually enabled for (see
    _CITATION_RETRY_BACKENDS above)."""
    return bool(citation_warnings) and not already_retried and backend in _CITATION_RETRY_BACKENDS


# Shared wording so the prose-retry message below and the structured-
# claims retry message (_format_claim_retry_message, for submit_answer)
# can't drift apart -- both target the same two live failure modes
# documented on _format_citation_retry_message below, and there's no
# reason a future wording tweak to one should silently leave the other
# behind.
_CITATION_RETRY_GUIDANCE = (
    "Before answering again, check whether any of the search results ALREADY "
    "shown earlier in this conversation actually support each flagged claim -- "
    "the right source may already be there under a different citation number. "
    "If you find proper support, restate the claim with the correct citation. "
    "If, after checking, a value genuinely isn't supported by any result shown, "
    "say so plainly and refuse that specific claim instead of guessing -- an "
    "honest answer that the sources don't support it is a completely acceptable "
    "outcome here. Do not invent, estimate, or approximate a number to replace "
    "an unverified one."
)


def _format_citation_retry_message(answer: str, citation_warnings: list[str]) -> str:
    """Builds the corrective follow-up message for a one-time citation
    retry (see run_agent() and
    docs/decisions/2026-08-18-citation-retry-loop-v1-tried-reverted.md).
    The wording (_CITATION_RETRY_GUIDANCE above) directly targets the two
    live failure modes that caused the v1 revert -- removing either
    property from the wording would silently reopen the failure mode it
    exists to prevent:

    1. aapl-employees-fy25's retry gave up entirely instead of checking
       the 4 OTHER already-retrieved chunks for a valid citation -- so
       this message explicitly points the model back at the search
       results ALREADY shown earlier in the conversation before it
       concludes nothing supports the claim.
    2. A "this is your final attempt" framing pushed the model to
       fabricate an estimate on a previously-100%-reliable refusal
       question (nvda-rd-expense-q4fy26-refusal) -- so this message
       deliberately contains NO deadline/final-attempt language, states
       an honest refusal is a fully acceptable outcome, and explicitly
       forbids inventing or estimating a replacement number."""
    warnings_block = "\n".join(f"- {w}" for w in citation_warnings)
    return (
        "Your previous answer had at least one citation that doesn't hold up:\n"
        f"{warnings_block}\n\n"
        "Your previous answer was:\n"
        f"{answer}\n\n"
        f"{_CITATION_RETRY_GUIDANCE}"
    )


def _format_claim_retry_message(answer_text: str, warnings: list["CitationWarning"]) -> str:
    """Structured-claims counterpart to _format_citation_retry_message
    above, used for a submit_answer retry instead of a prose one -- see
    docs/decisions/2026-09-10-structured-claims-citation-verification.md.
    Reuses the exact same hard-won guidance via _CITATION_RETRY_GUIDANCE
    so both retry flavors stay consistent by construction, not by
    copy-paste discipline. Delivered as a submit_answer tool RESULT
    (types.Part.from_function_response), not a plain follow-up turn --
    see the loop's own comment for why a dangling function call followed
    by a bare user turn is worth avoiding."""
    warnings_block = "\n".join(f"- {w.message}" for w in warnings)
    return (
        "Your previous submit_answer call had at least one claim that doesn't hold up:\n"
        f"{warnings_block}\n\n"
        "Your previous answer_text was:\n"
        f"{answer_text}\n\n"
        f"{_CITATION_RETRY_GUIDANCE}\n\n"
        "Call submit_answer again with the corrected answer_text and claims."
    )


def _format_refusal_message(warnings: list[str]) -> str:
    """Hard-gate refusal, returned by _finalize_answer() below in place
    of an answer whose citations still don't check out after any
    applicable retry. Implements this project's own standing design
    principle (see CLAUDE.md, "This project's design principles"):
    "Every numeric claim must trace to a specific filing + section, or
    the agent refuses" -- previously verify_citations()'s findings were
    only ever surfaced as warnings alongside the (still-returned)
    answer; this is what actually withholds it."""
    warnings_block = "\n".join(f"- {w}" for w in warnings)
    return (
        "I can't confirm this answer against the sources I retrieved -- "
        f"the following claim(s) don't hold up under citation verification:\n{warnings_block}\n\n"
        "Rather than give you a number I can't verify, I'm refusing this answer."
    )


# Backends allowed to FORCE a submit_answer call when the model replies
# with plain text instead of any tool call. A separate set
# from _CITATION_RETRY_BACKENDS above -- currently identical membership,
# but the two represent different policies (which backends get a
# citation retry vs. which backends get forced tool choice) that could
# diverge later, and conflating them would make a future change to one
# silently change the other. Gemini only: confirmed via design research
# that `types.FunctionCallingConfig(mode="ANY", ...)` is a genuine hard
# constraint on Gemini, while Ollama has no tool_choice/tool_config
# equivalent at all (neither its native /api/chat nor its OpenAI-
# compatible endpoint support it -- Ollama issues #8421, #11171) --
# `force_tool` is still accepted by Ollama's *_send* functions for
# interface uniformity, it just has no effect there.
_FORCED_SUBMIT_BACKENDS = {"gemini"}

_FORCE_SUBMIT_MESSAGE = "Please provide your final answer now by calling submit_answer."


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

    `withheld_answer` (see
    docs/decisions/2026-09-10-citation-gate-measurement-instrumentation.md)
    preserves what the model actually said whenever the gate refuses,
    since re-grading that text against ground truth is the only way to
    tell a correct-but-wrongly-refused answer (a false positive) from a
    genuinely bad one. Also fires a `citation_gate_refused` log event
    (local JSONL only, never Langfuse -- see log_event's own docstring)
    whenever it refuses, since this is the one place a real answer gets
    thrown away. `backend`/`retried` are keyword-only so the two flags
    can't be swapped positionally.

    `citation_warning_details` is populated directly from `warnings`
    here -- NOT re-derived by a second
    pass elsewhere -- so `eval_harness._citation_gate_evidence()` can stop
    calling collect_citation_warnings() (the PROSE checker) on a refusal
    that might have come from the STRUCTURED checker instead, which could
    otherwise silently disagree with what actually refused it."""
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
    return AgentResult(_format_refusal_message(messages), all_results, messages, answer, details)


def _format_citation_key(all_results: list[dict]) -> str:
    lines = []
    for i, r in enumerate(all_results, start=1):
        meta = r["metadata"]
        lines.append(
            f"  [{i}] {meta['ticker']} {meta['form']} filed {meta['filingDate']} "
            f"(reportDate={meta['reportDate']}, accession={meta['accessionNumber']}, "
            f"chunk={meta['chunk_index']})"
        )
    return "\n".join(lines)


def _dispatch_tool_call(
    call: dict, question: str, all_results: list[dict], searched_tickers: set[str | None], verbose: bool
) -> str:
    """Runs one normalized tool call ({"name", "args"} -- the
    ModelTurn.tool_calls shape from llm_backends.py) against the right
    tool, mutating all_results/searched_tickers in place, and returns
    the content string to send back to the model. Backend-agnostic by
    construction: it only ever sees the normalized shape, never
    Ollama's or Gemini's raw wire format, so the boundary validation
    inside call_get_financial_fact/call_compare_financial_metric
    (e.g. rejecting an invented `segment` argument) now protects both
    backends automatically instead of needing a second copy."""
    name = call["name"]
    args = call["args"]

    if name == "get_financial_fact":
        if verbose:
            print(f"  [tool call] get_financial_fact({args!r})")
        with traced_span("tool", name, input=args) as span:
            fact = call_get_financial_fact(args, question=question)
            if fact is None:
                span.update(output={"found": False})
                return _format_no_fact_message(args)
            start_index = len(all_results) + 1
            result = _fact_as_result(fact, args)
            all_results.append(result)
            span.update(output={"found": True, "value": fact.get("value")})
            return _format_results_block([result], start_index)

    if name == "compare_financial_metric":
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

    if name == "calculate":
        if verbose:
            print(f"  [tool call] calculate({args!r})")
        with traced_span("tool", name, input=args) as span:
            calc_result, error = call_calculate(args, all_results)
            if calc_result is None:
                span.update(output={"found": False, "error": error})
                return error
            start_index = len(all_results) + 1
            result = _calculation_as_result(calc_result, args)
            all_results.append(result)
            span.update(output={"found": True, "value": calc_result.get("value")})
            return _format_results_block([result], start_index)

    # soft_required={"query"}: query is schema-required (encourages the
    # model to include it), but _resolve_search_args below tolerates it
    # being absent by substituting the original question -- observed
    # live, not a bug (see that function's own docstring) -- so a
    # missing query must not be a hard rejection here.
    #
    # Checked BEFORE _resolve_search_args() runs, not after -- that
    # function's own `ticker not in searched_tickers` (a set) would
    # crash on a non-hashable ticker like a list, the exact unhashable-
    # ticker crash class validate_tool_args is safe against (jsonschema's
    # type/enum checks use plain equality, never hashing the instance).
    if validate_tool_args("search_filings", SEARCH_TOOL_SCHEMA, args, soft_required=frozenset({"query"})):
        raw_ticker = args.get("ticker")
        if raw_ticker is not None and (not isinstance(raw_ticker, str) or raw_ticker not in COMPANIES):
            # A hallucinated ticker gets its own actionable message
            # (names the bad value, lists valid ones) rather than a
            # generic one -- unlike get_financial_fact/
            # compare_financial_metric's boundary rejections, this is
            # the one case validate_tool_args's caller has enough
            # schema/enum context in hand to do that cheaply.
            return f"(ticker={raw_ticker!r} is not a recognized company — try one of {sorted(COMPANIES)} or omit the ticker filter)"
        return "(search_filings arguments were invalid — check the tool schema)"
    query, ticker = _resolve_search_args(args, fallback_query=question, searched_tickers=searched_tickers)
    searched_tickers.add(ticker)
    if verbose:
        print(f"  [tool call] search_filings(query={query!r}, ticker={ticker!r})")
    with traced_span("tool", name, input={"query": query, "ticker": ticker}) as span:
        results = hybrid_search(query, ticker=ticker, top_k=CHUNKS_PER_SEARCH)
        start_index = len(all_results) + 1
        all_results.extend(results)
        span.update(output={"result_count": len(results)})
        return _format_results_block(results, start_index)


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
    silently ignore any later change to it -- the exact bug the previous
    hardcoded `= "ollama"` default had, just with an extra layer of
    indirection that made it easy to miss.

    `citation_checks` in the span output reads the per-check counts
    straight from `result.citation_warning_details` (AgentResult's 5th
    field) rather than re-deriving them by calling
    collect_citation_warnings() (the PROSE checker) a second time on the
    withheld/returned text -- that would silently disagree with whatever
    ACTUALLY refused the answer once a structured-path refusal exists
    (collect_citation_warnings can't see a
    quote_not_found/value_not_in_quote/etc. failure at all -- those only
    ever come from verify_claims()). Reading the field _finalize_answer
    already computed removes both that risk and the redundant regex
    pass. The withheld answer text itself is never put in this span's
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

    A final answer arrives one of two ways (see
    docs/decisions/2026-09-10-structured-claims-citation-verification.md):

    - `submit_answer` (SUBMIT_TOOL_SCHEMA), the preferred path: claims
      are structured data (value/unit/citation_index/quote), verified by
      verify_claims() -- fuzzy quote grounding, value attribution, and a
      coverage cross-check -- instead of regex-parsed out of prose.
      Offered as a 4th tool alongside the other 3 from turn 1, under AUTO
      mode, for BOTH backends (not gated by backend): Gemini's own
      forcing mode can itself occasionally still return text, and a
      forced follow-up can fail or exhaust the budget, so the prose
      fallback below can never be fully deleted regardless of backend --
      once that's true, gating Ollama out of the structured path the
      model might spontaneously use anyway buys nothing. Confirmed live
      (tests/manual/verify_submit_answer.py) that BOTH backends call it
      correctly and spontaneously in practice.
    - Plain text, the fallback: verified by the original,
      completely-unchanged prose pipeline (collect_citation_warnings()).
      For Ollama this is the ONLY path, since it has no forcing
      mechanism at all (confirmed: neither its native nor OpenAI-
      compatible API supports tool_choice). For Gemini, a text reply
      instead triggers ONE forced ANY+submit_answer-only follow-up turn
      first (_FORCED_SUBMIT_BACKENDS) before ever falling back to prose
      -- so Gemini only reaches the prose path if forcing itself didn't
      produce a clean submission.

    Known simplification: no deduplication if two tool calls happen to
    surface the same chunk (e.g. two related queries against the same
    company). Fine for now — a duplicate citation is cosmetic, not a
    correctness problem — but worth revisiting if it gets noisy.

    One self-correction retry on an unverified citation/claim, shared
    across whichever path produced the answer (retried_for_citations
    caps the whole conversation at one retry total, not one per path).
    Gated to Gemini only -- see _CITATION_RETRY_BACKENDS's own comment
    and docs/decisions/2026-08-18-citation-retry-loop-v1-tried-reverted.md
    / docs/decisions/2026-08-25-citation-retry-loop-gemini-gated.md for
    why. The structured-claims retry reuses this same gate and budget,
    just delivers its feedback as a submit_answer tool RESULT instead of
    a plain follow-up turn -- keeps the chat history well-formed (a
    dangling function call followed by a bare user turn has historically
    400'd on Gemini) and needs no new plumbing, since it's exactly what
    send_tool_results already does."""
    start, send_tool_results, send_followup = BACKENDS[backend]
    tool_schemas = [FACT_TOOL_SCHEMA, COMPARE_TOOL_SCHEMA, SEARCH_TOOL_SCHEMA, CALCULATE_TOOL_SCHEMA, SUBMIT_TOOL_SCHEMA]
    state, turn = start(question, SYSTEM_PROMPT, tool_schemas)
    all_results: list[dict] = []
    searched_tickers: set[str | None] = set()
    calls_made = 1
    retried_for_citations = False
    forced_submit_attempted = False
    # Pending-retry snapshots for the exhausted-budget fallback at the
    # bottom -- at most one is ever set, since retried_for_citations caps
    # the whole conversation at one retry regardless of which path fires
    # it. pre_retry_submit_args caches the RAW submit_answer args rather
    # than pre-computed warnings -- a pure function of (submit_args,
    # all_results) can't go stale the way a cached warnings list could if
    # all_results grows before the budget runs out. See
    # docs/reviews/2026-09-10-citation-gate-measurement-instrumentation.md.
    # pre_retry_answer itself is UNCHANGED -- it still exists for the
    # untouched prose-fallback path.
    pre_retry_submit_args: dict | None = None
    pre_retry_answer: tuple[str, list[CitationWarning]] | None = None

    while True:
        submit, other = _partition_submit_call(turn.tool_calls)

        # A pure submission, OR a mixed submit+search turn that arrived
        # on the LAST allowed round trip: no budget left to dispatch the
        # extra searches and get a real resubmission back, so verify what
        # was actually submitted rather than discarding it below for the
        # generic timeout message.
        if submit is not None and (not other or calls_made >= MAX_TOOL_ITERATIONS):
            args = submit["args"]
            with traced_span("tool", "submit_answer", input=args) as span:
                if validate_tool_args("submit_answer", SUBMIT_TOOL_SCHEMA, args):
                    # Defensive, not expected in practice (Gemini/Ollama
                    # both called this correctly on every live run tried
                    # -- see tests/manual/verify_submit_answer.py) -- same
                    # belt-and-suspenders boundary check every other tool
                    # already gets. value/unit are sentinel-valued
                    # (0.0/raw): this warning isn't about a specific
                    # numeric claim.
                    answer_text = args.get("answer_text") or ""
                    warnings = [
                        CitationWarning(
                            check="no_structured_answer",
                            citation_index=None,
                            value=0.0,
                            unit="raw",
                            message="your submit_answer call didn't match the required schema (answer_text/claims)",
                        )
                    ]
                else:
                    answer_text = args["answer_text"]
                    warnings = verify_claims(args["claims"], all_results, question, answer_text)
                messages = [w.message for w in warnings]
                span.update(output={"warning_count": len(warnings), "checks": [w.check for w in warnings]})
                if _should_retry_for_citations(messages, retried_for_citations, backend) and calls_made < MAX_TOOL_ITERATIONS:
                    retried_for_citations = True
                    pre_retry_submit_args = args
                    log_event("citation_retry", backend=backend, warnings=messages)
                    if verbose:
                        print(f"  [citation retry] {messages}")
                    feedback = _format_claim_retry_message(answer_text, warnings)
                    turn = send_tool_results(state, [{"name": "submit_answer", "content": feedback}])
                    calls_made += 1
                    continue
                return _finalize_answer(answer_text, warnings, all_results, backend=backend, retried=retried_for_citations)

        if not turn.tool_calls:
            if backend in _FORCED_SUBMIT_BACKENDS and not forced_submit_attempted and calls_made < MAX_TOOL_ITERATIONS:
                forced_submit_attempted = True
                if verbose:
                    print("  [forcing submit_answer] model replied in text instead of calling a tool")
                turn = send_followup(state, _FORCE_SUBMIT_MESSAGE, force_tool="submit_answer")
                calls_made += 1
                continue
            # Prose fallback -- the original, completely unchanged
            # pipeline. The only path for Ollama (never forced); for
            # Gemini, only reached if forcing itself didn't produce a
            # clean submission (documented as occasionally possible).
            answer = turn.text or ""
            warnings = collect_citation_warnings(answer, all_results)
            messages = [w.message for w in warnings]
            if _should_retry_for_citations(messages, retried_for_citations, backend) and calls_made < MAX_TOOL_ITERATIONS:
                retried_for_citations = True
                pre_retry_answer = (answer, warnings)
                log_event("citation_retry", backend=backend, warnings=messages)
                if verbose:
                    print(f"  [citation retry] {messages}")
                turn = send_followup(state, _format_citation_retry_message(answer, messages))
                calls_made += 1
                continue
            return _finalize_answer(answer, warnings, all_results, backend=backend, retried=retried_for_citations)

        if calls_made >= MAX_TOOL_ITERATIONS:
            break

        results = [
            {"name": c["name"], "content": _dispatch_tool_call(c, question, all_results, searched_tickers, verbose)}
            for c in other
        ]
        if submit is not None:
            # Mixed turn with budget still remaining: dispatch the
            # searches, but the submission can't be trusted yet -- it
            # can't be grounded in results the model hasn't read.
            results.append(
                {
                    "name": "submit_answer",
                    "content": (
                        "You also requested new searches in this same turn; their results are included "
                        "above. Read them, then call submit_answer again with your final answer."
                    ),
                }
            )
        turn = send_tool_results(state, results)
        calls_made += 1

    if pre_retry_submit_args is not None:
        answer_text = pre_retry_submit_args["answer_text"]
        warnings = verify_claims(pre_retry_submit_args["claims"], all_results, question, answer_text)
        return _finalize_answer(answer_text, warnings, all_results, backend=backend, retried=retried_for_citations)

    if pre_retry_answer is not None:
        answer, warnings = pre_retry_answer
        return _finalize_answer(answer, warnings, all_results, backend=backend, retried=retried_for_citations)

    return _finalize_answer(
        "I wasn't able to finish answering within the allotted number of searches. "
        "Try asking a more specific or narrower question.",
        [],
        all_results,
        backend=backend,
        retried=retried_for_citations,
    )


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
