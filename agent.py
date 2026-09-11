"""
Week 5 — Agent layer: tool-calling over hybrid_search
-----------------------------------------------------------
answer.py (Week 3) is a single-shot pipeline: the caller must already
know which ticker to search (`--ticker CRM`). That's exactly the gap
Week 3's residual finding flagged — an unfiltered, un-scoped query like
"how many employees does the company have" doesn't reliably surface the
right chunk, even though the *retrieval* is fine once properly scoped.
The fix isn't better retrieval, it's a layer that figures out *which*
company(ies) a question is about before searching — that's what an
agent with a callable search tool does, and a hardcoded pipeline can't.

This file gives the LLM a `search_filings` tool (wrapping
retrieval.hybrid_search) instead of pre-fetching context ourselves. The
model decides what to search for, which ticker to restrict to (if any),
and whether it needs to search again — e.g. calling the tool twice, once
per company, to answer a comparison question across two of the five
covered companies. This is real tool-calling via Ollama's OpenAI-style
`tools` API (verified against qwen2.5:7b-instruct's actual wire format
before writing this: `arguments` comes back as a parsed dict, and the
follow-up tool-result message needs only `{"role": "tool", "content":
...}` — no `tool_call_id` required, unlike OpenAI's API).

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
from numeric_utils import UNIT_MULTIPLIERS, extract_numbers, extract_numbers_with_spans, normalize
from retrieval import hybrid_search
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
# generically, replacing what used to be two separate dicts here
# (RATIO_METRIC_FUNCTIONS for cross-company-capable ratios,
# SINGLE_COMPANY_RATIO_FUNCTIONS for the rest) -- collapsed once that
# split turned out to be pure duplication of information already in
# formulas.py's own table (see PROJECT_CONTEXT.md's "ratio-formula
# registration" section for the full reasoning). A ratio's
# `supports_cross_company` flag (in RATIO_DEFINITIONS) is what
# compare_financial_metric's dispatch below relies on to fall through to
# the same graceful "not supported" result any other unrecognized metric
# gets, for ratios like return_on_assets/asset_turnover/cash_to_assets/
# inventory_turnover/rd_intensity that don't have one.
#
# Derived once here rather than inline below, so the system prompt and
# both tool schemas stay accurate automatically as RATIO_DEFINITIONS
# grows -- the whole point of the table (see PROJECT_CONTEXT.md's
# "ratio-formula registration" section) is a new ratio needing no
# prompt/schema text updated by hand.
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

You have three tools:
- `get_financial_fact` searches structured XBRL data for a small set of standard financial metrics: {", ".join(sorted(DEFAULT_METRIC_TAGS) + sorted(RATIO_DEFINITIONS))}. Prefer this tool FIRST whenever the question asks for one of these specific metrics for a specific fiscal year or fiscal quarter, for ONE company — it returns an exact, unambiguous reported value instead of relying on you to find the right sentence in a filing excerpt. This tool ONLY returns a company's consolidated, company-wide total — it has NO way to get one segment's or one product line's figure (e.g. Microsoft's "Intelligent Cloud" segment, NVIDIA's "Compute & Networking" segment). If a question asks about a specific segment or product line, do NOT call this tool at all, not even to try — go straight to `search_filings` instead. It only works for the metrics listed above and returns "not available" if the company doesn't tag it or the period wasn't recognized — fall back to `search_filings` when that happens, or for anything else this tool doesn't cover (risk factors, narrative discussion, any metric not in the list above). Only pass the arguments this tool actually defines — never invent an extra filter argument (e.g. there is no `segment` parameter); an unrecognized argument is rejected outright, so search_filings instead if you need something this tool doesn't support. To ask for year-over-year growth of one of the raw metrics (not the ratios) instead of its plain value, add `yoy_growth: true` — never compute a growth percentage yourself from two separate calls to this tool, always use this flag. To ask for a multi-year average (e.g. "3-year average operating margin"), pass `start_fiscal_year` and `end_fiscal_year` instead of `fiscal_year`/`fiscal_period`/`period_end_date` — never average multiple years yourself from separate calls, always use these.
- `compare_financial_metric` gets the SAME metric for ALL FIVE companies at once, for one period. Use this instead of calling `get_financial_fact` five times when a question asks you to compare or rank companies against each other (e.g. "which company had the highest gross margin", "compare revenue across all five companies") — one call instead of five. A company can be missing from the result if it doesn't tag that metric for that period; that's not an error, just note it's unavailable for that company. Note: {", ".join(_SINGLE_COMPANY_ONLY_RATIOS)} are NOT available on this tool (no cross-company version exists) — use `get_financial_fact` once per company for those instead.
- `search_filings` searches these companies' 10-K/10-Q filings for anything else. Call it once per company if a question spans more than one, and call it again with a different query if your first search doesn't turn up what you need.

Do not answer from prior knowledge about these companies; every answer must come from what a tool returns.

Rules:
1. Every factual or numeric claim in your final answer must end with a citation marker like [1] or [2] referring to a search result.
2. If your searches don't turn up enough information to answer, say so explicitly rather than guessing.
3. Do not combine or infer numbers that don't appear directly in a search result (e.g. don't compute a total unless a result states it) — this does not apply to `get_financial_fact`'s own output, which is already a single reported or tool-computed value.
4. Resolve company names to the right ticker yourself (e.g. "Salesforce" -> CRM) — don't ask the user to clarify.
5. Search results often report the same metric for several different periods in one excerpt — not just in tables, but within a single sentence, e.g. "the rate was 20% for the current quarter, and 18% for the same quarter last year." Before citing a number, check that its stated period exactly matches the period asked about, even when both numbers appear right next to each other in the same sentence — do not substitute a prior-year or prior-quarter value just because it's nearby.
6. For a question spanning multiple companies, you must query EVERY company mentioned — with `search_filings` if `get_financial_fact` didn't cover it — before writing your final answer. A `get_financial_fact` call returning "not available" for one company is not a reason to stop; it means try `search_filings` for that same company next, and you must still go on to query every other company the question asks about. Do not conclude a company's data is unavailable unless you have actually searched for it.
7. If `compare_financial_metric` returns fewer than all five companies, your final answer must explicitly name which companies were and weren't covered (e.g. "data was only available for AAPL and PLTR; the others hadn't filed a matching quarter yet") — do not phrase a conclusion as if it covers "all five companies" or similar when it only covers the ones that were actually returned.
8. ONLY when a single sentence combines facts from two or more DIFFERENT companies (e.g. comparing NVIDIA and Salesforce), put each citation marker immediately after the specific fact it supports, not bundled together at the end — write "NVIDIA's revenue was $81.6 billion [1], while Salesforce's was $11.1 billion [2]." not "NVIDIA's revenue was $81.6 billion, while Salesforce's was $11.1 billion [1][2]." This rule does not add any new requirement to single-company answers or to a refusal under rule 2 — never search for extra facts just to have something to cite per-sentence; a plain, single citation at the end of a normal sentence is already correct and needs no change."""

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
                        "never compute growth yourself from two separate calls."
                    ),
                },
                "start_fiscal_year": {
                    "type": "integer",
                    "description": "Only for a multi-year-average question (e.g. '3-year average operating margin from fiscal year 2023 through 2025'). Set together with end_fiscal_year, and leave fiscal_year/fiscal_period/period_end_date out -- averages `metric` across every fiscal year in the range (always full-year, FY). Never average multiple years yourself from separate calls, always use this.",
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


def _resolve_search_args(
    args: dict, fallback_query: str, searched_tickers: set[str | None]
) -> tuple[str, str | None]:
    """Extract (query, ticker) from a tool call's arguments.

    The model doesn't always include every schema-declared argument —
    observed in testing: it sometimes calls search_filings with only
    `ticker` and no `query`, despite `query` being marked required.

    The model's own `query` text is only trusted on a *retry* against a
    ticker already searched earlier in this conversation
    (`searched_tickers`). The first search against each company always
    uses the original question verbatim instead. Found by testing, not
    assumed: the model's self-written first-pass queries were the direct
    cause of two separate eval failures — a too-vague query ("Microsoft
    ... Q4 2025") buried the correct chunk among annual-report decoys,
    while a too-literal one (the exact calendar date) over-matched an
    unrelated financial-statement table instead of the prose paragraph
    that never repeats that date. Different companies phrase the same
    fact differently in their filings, so no single query-phrasing
    instruction generalized across both — but the user's own original
    question, which already contains the metric name and the period in
    their own words, retrieved the right chunk in every case tested. A
    retry search (the model deciding its first attempt came up short)
    still gets to use its own query, since that's a deliberate
    refinement rather than a first guess."""
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
    hint below is unit-testable without a live Ollama round-trip. Found
    live: a bare "not found, try search_filings" message left the model
    unaware this was a structural reporting gap rather than a retrieval
    miss, so it trusted noisy search results back and fabricated a wrong-
    quarter number instead of refusing (nvda-rd-expense-q4fy26-refusal).

    The never-tagged hint below is the same principle applied to a
    different structural gap: asked for Palantir's inventory turnover,
    the model got only as far as "I can't compute this ratio" without
    ever saying WHY (no inventory line item at all, not just an
    unavailable period), and filled the gap with an unrelated cost-of-
    revenue figure instead (pltr-inventory-turnover-fy2025-refusal)."""
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
    silently let fiscal_year=true through the old hand-rolled check
    (2026-09-09 review). Shared by _rejects_invalid_fiscal_year and the
    multi-year-average combo check below, both of which read
    fiscal_year-shaped args outside of validate_tool_args's generic pass
    (see call_get_financial_fact's skip_properties)."""
    return _INT_TYPE_VALIDATOR.is_valid(value)


def _rejects_invalid_fiscal_year(tool: str, args: dict) -> bool:
    """True (having already logged the rejection) if args["fiscal_year"]
    is present but not a valid int -- shared by call_get_financial_fact
    and call_compare_financial_metric, which otherwise each hand-rolled
    an identical check (found in code review, 2026-09-10). A malformed
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
    a hand-rolled extra-key/type/enum check per tool, duplicated three
    times and broken three separate times across three review dates
    (most recently: a hand-rolled `isinstance(fiscal_year, int)` silently
    accepting a JSON boolean). `schema` is one of *_TOOL_SCHEMA, doing
    double duty as both what's advertised to the LLM and what's enforced
    here -- `additionalProperties: false` on each schema's `parameters`
    is what replaces the old `set(args) - _FACT_ARG_KEYS`-style checks.

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
    Found in code review: this diff's own period_end_date fix (added
    "null" to that one property's declared type after live testing showed
    it) was the first instance of the general problem, not a one-off --
    every other optional property (`ticker`, `fiscal_period`,
    `yoy_growth`, ...) had the exact same gap, just not yet observed live.
    Handling it once, generically, here closes the whole class instead of
    enumerating `["string", "null"]" per property as each one is
    separately noticed. An unrecognized EXTRA key is deliberately NOT
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
    # lose that ordering for no benefit (found in code review: an earlier
    # version did exactly that, making priority()'s tie-break silently
    # dependent on this process's hash seed instead of schema order).
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
    model doesn't reliably respect the schema. Found live: asked for
    "effective tax rate" (not a supported metric, not in the schema's
    enum) and called this with metric omitted entirely rather than
    picking a valid enum value or skipping the tool, which crashed the
    whole run with an unhandled ValueError from xbrl_facts._tag_for
    before this guard existed. Same class of issue as
    _resolve_search_args's docstring above (the model doesn't always
    include every schema-declared argument) — validated generically by
    validate_tool_args at the boundary, rather than trusting the schema
    was followed (required/type/enum/no-extra-keys); this function only
    layers the business rules a flat schema check can't express.

    `yoy_growth=True` combined with a margin metric is rejected the same
    way: get_yoy_growth() only supports the raw tagged metrics (see its
    own docstring for why), so that combination isn't just unsupported,
    it's meaningless -- caught here rather than passed through.

    An unrecognized EXTRA key is a different, newer-found shape of the
    same "don't trust the schema" lesson: asked to compare NVIDIA's
    Compute & Networking segment against its Graphics segment, the model
    invented a `segment` filter this tool has never supported. The old
    code only ever read known keys (`args.get(...)`), so the invented
    key was silently dropped -- both "segment" calls quietly returned
    the SAME consolidated total instead of erroring, and the model
    concluded the two segments had equal revenue. validate_tool_args's
    `additionalProperties: false` check rejects any unrecognized key
    outright now (rather than silently ignoring it), turning that into a
    clean "not supported, try search_filings" fallback.

    `start_fiscal_year`/`end_fiscal_year` (both required together, and
    rejected if combined with yoy_growth) dispatch to
    get_multi_year_average() instead of a single-period lookup -- built
    after the model reached for self-computation on its own for a
    3-year-average question with no deterministic path (see that
    function's own docstring). Supported for every RATIO_DEFINITIONS
    metric -- formulas._get_annual_value() dispatches any of them
    generically (see its own docstring).

    `question` (optional -- only agent.py's tool-dispatch path has one;
    mcp_server.py's direct callers don't) is passed through to
    record_unmet_metric_request() purely for observability, see below.

    Week 7 guardrails (Langfuse): records an unmet-metric-request event
    when `metric` isn't recognized at all (reason="unknown_metric" --
    the "should we add a formula for this" signal) or when it's a
    recognized metric/ratio but the underlying lookup -- get_metric(),
    get_ratio(), get_yoy_growth(), or get_multi_year_average(), all four
    genuine-data-lookup paths below -- found no data for this
    ticker/period (reason="no_data_for_ticker" -- the same shape of gap
    already found for inventory_turnover/AAPL/MSFT). Deliberately NOT
    recorded for boundary rejections above (malformed/invented args,
    invalid yoy_growth/multi-year-average combinations) -- those are a
    schema-violation problem, not a "this formula doesn't exist yet"
    problem, and would just be noise on the signal. Found in code
    review: the yoy_growth/multi-year-average paths were initially
    missed, only the plain get_metric()/get_ratio() path recorded this
    at first."""
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
        # branch never reads it, so a value here is irrelevant (found in
        # round-2 review, 2026-09-09).
        if args.get("yoy_growth") or not _is_valid_int(start_fiscal_year) or not _is_valid_int(end_fiscal_year):
            log_event(
                "tool_call_rejected", tool="get_financial_fact", reason="invalid_multi_year_average_combo", args=args
            )
            return None
        result = get_multi_year_average(ticker, metric, start_fiscal_year, end_fiscal_year)
        if result is None:
            record_unmet_metric_request(ticker, metric, reason="no_data_for_ticker", question=question)
        return result
    # Checked AFTER the multi-year-average branch above (found in round-2
    # review, 2026-09-09): that branch never reads fiscal_year at all, so
    # checking it any earlier would wrongly reject a valid multi-year-
    # average request over a stray, irrelevant fiscal_year value -- this
    # must only gate the two branches below, which are the only ones
    # that actually use it.
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

    Same Week 7 Langfuse unmet-metric-request tracing as
    call_get_financial_fact -- see that function's docstring. The
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
    # anchor_ticker not in result (not just `not result`) matters since
    # 2026-09-07: instant metrics resolve each company independently
    # with no requirement that the requested anchor itself has data
    # (e.g. PLTR doesn't tag inventory but AAPL/MSFT do) -- found in
    # code review, a non-empty-but-anchor-missing result used to record
    # no signal at all that the specific company asked about has no
    # data, even though everyone else's data is genuinely returned.
    if not result or anchor_ticker not in result:
        record_unmet_metric_request(anchor_ticker, metric, reason="no_data_for_ticker", question=question)
    return result


def _comparison_as_results(data: dict[str, dict], metric: str) -> list[dict]:
    """Wrap a {ticker: fact} dict (from compare_financial_metric) as a
    list of {text, metadata} results, one per company, reusing the same
    shape _fact_as_result uses for a single company. A frames entry
    (duration metrics) doesn't carry a "form" field — "XBRL frame data"
    stands in for it rather than guessing 10-K vs. 10-Q. Instant metrics
    (total_assets etc., 2026-09-07 redesign) resolve independently per
    company via get_metric(), which DOES carry a real form — used when
    present via fact.get(...) instead of always hardcoding the frame
    fallback label."""
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


_CITATION_MARKER = re.compile(r"\[(\d+)\]")
_CITATION_WINDOW_CHARS = 150

# Text that looks number-shaped but isn't a claim to verify -- stripped
# from the claim window before extraction, not from numeric_utils.py's
# shared extract_numbers() itself, since grade_numeric() doesn't have
# this false-positive problem (it only needs ONE number in the whole
# answer to match, so spurious extras there are harmless noise, not
# wrong verdicts) and stripping this there could hide a genuine
# date/form-shaped ground-truth value in some future question type.
# Three patterns, all found live, not anticipated up front:
#   - Dates ("June 27, 2026" -> 27, 2026) were the single biggest source
#     of noise on a real multi-sentence answer (12 warnings for one
#     answer, only 1 of them the actual misgrounded value).
#   - Bare year-like numbers ("fiscal Q3 2025" -> the 2025 survives the
#     date pattern above since it's not glued to a month name) -- a
#     standalone 1900-2099 number next to a citation is virtually always
#     a period label, not a numeric claim.
#   - "10-K"/"10-Q" (the only two form types this project ingests, see
#     edgar_ingest.py's FORM_TYPES) were producing a "claims 10.0 (raw)"
#     warning on the majority of a 21-question eval run's answers --
#     the model routinely writes "the 10-Q filing [1]" in its own prose,
#     and "10" isn't glued to a preceding letter (there's a space before
#     it), so the digit-glued-to-letter fix in numeric_utils.py doesn't
#     catch it.
_NON_CLAIM_PATTERN = re.compile(
    r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+\d{1,2},?\s+\d{4}\b|\b\d{4}-\d{2}-\d{2}\b|\b(?:19|20)\d{2}\b|\b10-[KQ]\b",
    re.IGNORECASE,
)


def _source_number_candidates(source_text: str) -> list[tuple[str, float]]:
    """Every (category, comparable_number) a source chunk's text could
    plausibly support -- not just each number under its own immediately-
    adjacent unit, but also each bare/raw number under any unit word the
    chunk mentions ANYWHERE.

    SEC filing tables routinely state a unit once in a caption
    ("Remaining performance obligation consisted of the following (in
    billions):") and leave the actual cell values bare ("$72.4"), so a
    per-cell extract_numbers() reads $72.4 as 72.4 raw, not 72.4
    billion. Found live: this produced a false "claims 72.4 (billion)
    but that value doesn't appear in the cited source" warning on
    crm-rpo-fy26 -- a question that PASSED with the exact correct
    answer, not one of the intentionally-hard formula-gap questions, so
    this false positive would have undermined trust in the checker for
    exactly the simple, correctly-answered questions it should be most
    reliable on. This only ADDS candidate interpretations (a raw number
    can still also match as raw) -- it never removes a way for a
    genuine mismatch to be caught."""
    numbers = extract_numbers(source_text)
    candidates = [normalize(v, u) for v, u in numbers]
    text_lower = source_text.lower()
    for caption_unit in UNIT_MULTIPLIERS:
        if caption_unit in text_lower:
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

        source_normalized = _source_number_candidates(all_results[n - 1]["text"])
        for value, unit in claimed:
            category, norm = normalize(value, unit)
            tolerance = max(0.01 * abs(norm), 0.05)
            verified = any(c == category and abs(sn - norm) <= tolerance for c, sn in source_normalized)
            yield n, value, unit, verified


# Sentence-ending punctuation followed by whitespace signals a break
# UNLESS what comes after that whitespace is a citation marker
# ("...total. [1]" is one sentence, not two) or a lowercase letter (an
# abbreviation like "U.S." continuing mid-clause, not a real sentence
# start) -- found in code review: without the lowercase exclusion, "...
# primarily from U.S. sales [1]" registered a false break, making a
# correctly-cited claim look unreachable from its own marker and
# wrongly refusing an otherwise-correct answer.
#
# Both lookaheads deliberately sit INSIDE the pattern (matching only the
# punctuation character itself, zero-width beyond it) rather than
# consuming "\s+" before checking what follows -- found in code review:
# an earlier version (`r"[.!?]\s+(?![\[a-z])"`) let the greedy `\s+`
# backtrack to a SHORTER whitespace match whenever the maximal one
# failed the lookahead, so "billion.  [1]" (two spaces) still registered
# a false break by matching only the first space and finding the SECOND
# space didn't look like "[" or a letter either -- the exact same false-
# refusal bug the lookahead was built to prevent, just triggered by
# extra whitespace instead of an abbreviation. `(?!\s*[\[a-z])` checks
# ALL possible amounts of trailing whitespace at once (a negative
# lookahead has no successful match to backtrack away from), so it's
# immune to this regardless of how much whitespace follows.
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
    never enters that loop at all. Found live (PROJECT_CONTEXT.md's
    2026-08-25 "Formula registry extended" section, msft-cash-to-assets-
    fy2025): the model self-computed a ratio from two separately-
    retrieved raw values and stated the result with no citation marker
    nearby, in 2 of 4 manual runs -- an answer that sailed through
    unrefused despite violating the same "every numeric claim must trace
    to a source" principle _iter_citation_claims() enforces for the
    cited case.

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
    docs/plans/2026-09-09-citation-gap-frame-ordering-retrieval-verify.md
    and its matching docs/reviews/ file for the full history of designs
    tried and rejected against this codebase's own existing test cases.

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
    docs/plans/2026-09-10-citation-gate-measurement-instrumentation.md):
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
    # Two dedup sets, deliberately not one -- found in code review, in
    # two rounds: a single value+unit-only key (fixing the cross-loop
    # duplicate below) ALSO collapsed two genuinely different,
    # independently-broken citations that happen to share a value --
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

    Motivated by a real, observed case (see PROJECT_CONTEXT.md,
    aapl-revenue-growth-q3fy2026): asked for a computed ratio (YoY
    revenue growth) with no supporting tool, the model retrieved two raw
    dollar figures via get_financial_fact, self-computed a percentage
    from them in its own reasoning text (violating rule 3, "don't
    combine or infer numbers"), and cited both dollar-figure sources for
    a percentage that appears in NEITHER of them. Built to catch exactly
    that shape of problem — confirmed live against the real question,
    which is also where the date-noise and duplicate-warning issues
    below were found and fixed, not assumed.

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
    states the right number but attaches it to the wrong source. Found
    live, not hypothetical: aapl-employees-fy25 used to "pass" (166,000
    appears in the answer) even though its citation actually points at a
    chunk about debt notes and share repurchases, not employee count —
    the wrong-chunk citation is exactly the kind of silent misgrounding
    verify_citations() already catches for OTHER claims; this is what
    wires that same check into what decides pass/fail for the specific
    value a question is graded on.

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


# Backends allowed to get the citation-verification retry (see
# _should_retry_for_citations below). Gated to Gemini only, decided
# 2026-08-25 after live-verifying both backends: this exact mechanism
# was already tried against Ollama once and reverted (Week 5j -- see
# docs/plans/2026-08-24-citation-retry-loop-design.md) after
# qwen2.5:7b-instruct proved unable to reliably act on the corrective
# feedback (giving up on an already-correct answer, or fabricating an
# estimate under retry pressure). A fresh live re-run this time showed
# no regression, but a single run can't outweigh that documented
# history against Ollama's own known run-to-run noise -- so the retry
# stays scoped to the backend it was actually re-verified for.
_CITATION_RETRY_BACKENDS = {"gemini"}


def _should_retry_for_citations(citation_warnings: list[str], already_retried: bool, backend: str) -> bool:
    """Whether run_agent() should give the model one corrective retry
    turn for its own unverified citation(s). True only when there's
    something to correct, the single retry (see
    _format_citation_retry_message below) hasn't already been spent this
    conversation -- capped at one retry, same as the original Week 5j
    design, sharing run_agent()'s existing MAX_TOOL_ITERATIONS budget
    rather than a separate one -- and `backend` is one this retry is
    actually enabled for (see _CITATION_RETRY_BACKENDS above)."""
    return bool(citation_warnings) and not already_retried and backend in _CITATION_RETRY_BACKENDS


def _format_citation_retry_message(answer: str, citation_warnings: list[str]) -> str:
    """Builds the corrective follow-up message for a one-time citation
    retry (see run_agent() and docs/plans/2026-08-24-
    citation-retry-loop-design.md). Revisits Week 5j's reverted attempt,
    with wording that directly targets the two live failure modes that
    caused that revert:

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


def _format_refusal_message(warnings: list[str]) -> str:
    """Week 7 hard-gate refusal, returned by _finalize_answer() below in
    place of an answer whose citations still don't check out after any
    applicable retry. Implements the project's own design principle
    (PROJECT_CONTEXT.md): "Every numeric claim must trace to a specific
    filing + section, or the agent refuses" -- previously
    verify_citations()'s findings were only ever surfaced as warnings
    alongside the (still-returned) answer; this is what actually
    withholds it."""
    warnings_block = "\n".join(f"- {w}" for w in warnings)
    return (
        "I can't confirm this answer against the sources I retrieved -- "
        f"the following claim(s) don't hold up under citation verification:\n{warnings_block}\n\n"
        "Rather than give you a number I can't verify, I'm refusing this answer."
    )


AgentResult = NamedTuple(
    "AgentResult",
    [
        ("answer", str),  # what a real caller may show a user (the refusal text if the gate fired)
        ("results", list[dict]),
        ("citation_warnings", list[str]),  # unchanged shape/strings -- every existing caller's contract
        ("withheld_answer", str | None),  # the model's actual answer text iff the gate refused it, else None
    ],
)


def _count_citation_checks(warnings: list["CitationWarning"]) -> dict[str, int]:
    """How many warnings each check (`CitationWarning.check`) produced --
    shared by _finalize_answer's log event and run_agent's span output
    below so the two don't independently hand-roll the same accumulation
    loop (found in code review, 2026-09-10)."""
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

    Added 2026-09-10 for the citation-gate FP/FN measurement work (see
    docs/plans/2026-09-10-citation-gate-measurement-instrumentation.md):
    `withheld_answer` preserves what the model actually said whenever the
    gate refuses, since re-grading that text against ground truth is the
    only way to tell a correct-but-wrongly-refused answer (a false
    positive) from a genuinely bad one. Nothing before this could recover
    that text once refused. Also fires a `citation_gate_refused` log
    event (local JSONL only, never Langfuse -- see log_event's own
    docstring) whenever it refuses, since this is the one place a real
    answer gets thrown away and, until now, nothing recorded that it
    happened. `backend`/`retried` are keyword-only so the two flags can't
    be swapped positionally."""
    messages = [w.message for w in warnings]
    if not warnings:
        return AgentResult(answer, all_results, messages, None)

    log_event(
        "citation_gate_refused",
        backend=backend,
        retried=retried,
        n_results=len(all_results),
        checks=_count_citation_checks(warnings),
        warnings=messages,
        withheld_answer=answer,
    )
    return AgentResult(_format_refusal_message(messages), all_results, messages, answer)


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

    # soft_required={"query"}: query is schema-required (encourages the
    # model to include it), but _resolve_search_args below tolerates it
    # being absent by substituting the original question -- observed
    # live, not a bug (see that function's own docstring) -- so a
    # missing query must not be a hard rejection here.
    #
    # Checked BEFORE _resolve_search_args() runs (round-2 review
    # finding, 2026-09-10), not after -- that function's own `ticker not
    # in searched_tickers` (a set) already crashes on a non-hashable
    # ticker like a list, the exact unhashable-ticker crash class
    # validate_tool_args is also safe against (jsonschema's type/enum
    # checks use plain equality, never hashing the instance).
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
    is new (2026-09-10, see _finalize_answer's docstring).

    `backend=None` resolves to config.DEFAULT_BACKEND -- resolved HERE,
    inside the function body, rather than as a literal `= DEFAULT_BACKEND`
    parameter default (2026-09-10): a parameter default is evaluated once
    at module-import time, so a literal default would freeze in whatever
    DEFAULT_BACKEND happened to be when agent.py was first imported and
    silently ignore any later change to it -- the exact bug the previous
    hardcoded `= "ollama"` default had, just with an extra layer of
    indirection that made it easy to miss.

    `citation_checks` in the span output re-derives the per-check counts
    from whichever text was actually checked (the withheld answer if the
    gate refused, else the returned answer) via collect_citation_warnings
    -- deliberately NOT parsed out of the warning strings themselves,
    which would reintroduce exactly the wording-inference fragility this
    whole change is trying to move away from. Re-deriving here (rather
    than threading _finalize_answer's own already-computed dict back out
    through AgentResult) is a deliberate, cheap tradeoff: it's one more
    regex pass over already-short answer text, in exchange for not
    growing AgentResult's public shape for an internal span-logging
    detail. _count_citation_checks() is shared with _finalize_answer so
    the two don't hand-roll the same accumulation loop independently.
    The withheld answer text itself is never put in this span's output
    -- it goes to _finalize_answer's log_event call only, which is
    local-JSONL-only by design (see tracing.log_event's docstring): the
    whole point of withholding it is that it isn't trustworthy, so it
    must not leave the machine via the Langfuse-forwarding path
    traced_span() offers."""
    backend = backend or DEFAULT_BACKEND
    with traced_span("agent", "run_agent", input={"question": question, "backend": backend}) as span:
        result = _run_agent_impl(question, backend, verbose)
        checked_text = result.withheld_answer if result.withheld_answer is not None else result.answer
        span.update(
            output={
                "answer": result.answer,
                "citation_warnings": result.citation_warnings,
                "citation_checks": _count_citation_checks(collect_citation_warnings(checked_text, result.results)),
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
    citations), any citation-verification warnings from
    collect_citation_warnings(), and (2026-09-10) the model's actual
    withheld answer text whenever the hard gate refused. Week 7 hard
    gate: every return site routes through _finalize_answer(), which
    withholds the model's actual answer text in favor of a refusal
    (_format_refusal_message()) whenever those warnings are non-empty --
    so a non-empty `citation_warnings` means AgentResult.answer IS the
    refusal, not the (unverifiable) original, which is preserved
    separately as AgentResult.withheld_answer instead.

    Known simplification: no deduplication if two tool calls happen to
    surface the same chunk (e.g. two related queries against the same
    company). Fine for now — a duplicate citation is cosmetic, not a
    correctness problem — but worth revisiting if it gets noisy.

    One self-correction retry on an unverified citation, revisited
    2026-08-24 against the swappable-backend layer (originally tried
    and reverted in Week 5j -- see PROJECT_CONTEXT.md and
    docs/plans/2026-08-24-citation-retry-loop-design.md).
    Gated to Gemini only (see _CITATION_RETRY_BACKENDS) -- decided
    2026-08-25 after live-verifying both backends showed no regression
    on this particular run, but Ollama's documented history with this
    exact mechanism (and its own run-to-run noise) wasn't outweighed by
    one clean re-run."""
    start, send_tool_results, send_followup = BACKENDS[backend]
    tool_schemas = [FACT_TOOL_SCHEMA, COMPARE_TOOL_SCHEMA, SEARCH_TOOL_SCHEMA]
    state, turn = start(question, SYSTEM_PROMPT, tool_schemas)
    all_results: list[dict] = []
    searched_tickers: set[str | None] = set()
    calls_made = 1
    retried_for_citations = False
    # Preserved so a citation retry that consumes the last iteration
    # budget can't discard an already-produced, merely-warned answer in
    # favor of the generic timeout message below -- found in code
    # review (2026-08-25): if the retry's own follow-up turn made a NEW
    # tool call instead of just re-answering, the loop used to hit the
    # iteration cap on that tool call and fall through to the timeout
    # return, throwing away a perfectly usable prior answer.
    pre_retry_answer: tuple[str, list[CitationWarning]] | None = None

    while True:
        if not turn.tool_calls:
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
            for c in turn.tool_calls
        ]
        turn = send_tool_results(state, results)
        calls_made += 1

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

    answer, results, _, _ = run_agent(args.question, backend=args.backend, verbose=args.verbose)

    print(f"\nQ: {args.question}\n")
    print(answer)
    if results:
        print("\nSources:")
        print(_format_citation_key(results))
    # No separate "Citation warnings:" print block: since the Week 7
    # hard gate (_finalize_answer), non-empty citation_warnings always
    # means `answer` IS the refusal message, which already lists every
    # warning verbatim -- printing them again here would just repeat
    # the same lines a second time.
    flush()


if __name__ == "__main__":
    main()
