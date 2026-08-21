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

import requests

from companies import load_companies
from config import OLLAMA_MODEL_NAME, OLLAMA_URL
from formulas import (
    get_gross_margin,
    get_gross_margin_all_companies,
    get_multi_year_average,
    get_net_margin,
    get_net_margin_all_companies,
    get_operating_margin,
    get_operating_margin_all_companies,
    get_yoy_growth,
)
from numeric_utils import UNIT_MULTIPLIERS, extract_numbers, normalize
from retrieval import hybrid_search
from xbrl_facts import DEFAULT_METRIC_TAGS, get_metric, get_metric_all_companies, is_metric_tagged

MAX_TOOL_ITERATIONS = 6
CHUNKS_PER_SEARCH = 5

# Tool-computed ratio metrics -- none of these are a single GAAP tag
# (see xbrl_facts.py's _compute_ratio_metric()), so each is computed
# from two raw metrics instead of returned raw for the model to divide.
# Each value is (single-company function, all-companies function),
# letting both dispatch functions and both tool schemas below derive
# from this one dict instead of maintaining three separately-typed
# copies of the same three metric names.
MARGIN_METRIC_FUNCTIONS = {
    "gross_margin": (get_gross_margin, get_gross_margin_all_companies),
    "operating_margin": (get_operating_margin, get_operating_margin_all_companies),
    "net_margin": (get_net_margin, get_net_margin_all_companies),
}

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
- `get_financial_fact` searches structured XBRL data for a small set of standard financial metrics: {", ".join(sorted(DEFAULT_METRIC_TAGS)) + ", " + ", ".join(sorted(MARGIN_METRIC_FUNCTIONS))}. Prefer this tool FIRST whenever the question asks for one of these specific metrics for a specific fiscal year or fiscal quarter, for ONE company — it returns an exact, unambiguous reported value instead of relying on you to find the right sentence in a filing excerpt. This tool ONLY returns a company's consolidated, company-wide total — it has NO way to get one segment's or one product line's figure (e.g. Microsoft's "Intelligent Cloud" segment, NVIDIA's "Compute & Networking" segment). If a question asks about a specific segment or product line, do NOT call this tool at all, not even to try — go straight to `search_filings` instead. It only works for the metrics listed above and returns "not available" if the company doesn't tag it or the period wasn't recognized — fall back to `search_filings` when that happens, or for anything else this tool doesn't cover (risk factors, narrative discussion, any metric not in the list above). Only pass the arguments this tool actually defines — never invent an extra filter argument (e.g. there is no `segment` parameter); an unrecognized argument is rejected outright, so search_filings instead if you need something this tool doesn't support. To ask for year-over-year growth of one of the raw metrics (not the margins) instead of its plain value, add `yoy_growth: true` — never compute a growth percentage yourself from two separate calls to this tool, always use this flag. To ask for a multi-year average (e.g. "3-year average operating margin"), pass `start_fiscal_year` and `end_fiscal_year` instead of `fiscal_year`/`fiscal_period`/`period_end_date` — never average multiple years yourself from separate calls, always use these.
- `compare_financial_metric` gets the SAME metric for ALL FIVE companies at once, for one period. Use this instead of calling `get_financial_fact` five times when a question asks you to compare or rank companies against each other (e.g. "which company had the highest gross margin", "compare revenue across all five companies") — one call instead of five. A company can be missing from the result if it doesn't tag that metric for that period; that's not an error, just note it's unavailable for that company.
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
                    "enum": sorted(DEFAULT_METRIC_TAGS) + sorted(MARGIN_METRIC_FUNCTIONS),
                    "description": "Which metric to fetch. gross_margin/operating_margin/net_margin are each computed as a ratio and returned as a percent; the rest are returned in USD.",
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
                    "description": "Set true to get year-over-year percent growth of `metric` instead of its plain value (e.g. 'revenue growth' questions). Only valid for the raw metrics, NOT for gross_margin/operating_margin/net_margin -- returns null for that combination. Compares the requested period to the SAME fiscal_period one year earlier automatically; never compute growth yourself from two separate calls.",
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
                    "enum": sorted(DEFAULT_METRIC_TAGS) + sorted(MARGIN_METRIC_FUNCTIONS),
                    "description": "Which metric to fetch for every company. gross_margin/operating_margin/net_margin are each computed as a ratio and returned as a percent; the rest are returned in USD.",
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
    the same Q4 reporting gap applies just as much to a cross-company
    comparison question as to a single-company one."""
    message = (
        f"(no structured data found for metric={args.get('metric')!r} "
        "across companies for this period — try search_filings per company instead)"
    )
    if args.get("fiscal_period") == "Q4":
        message += f" {_Q4_NOT_DISCLOSED_HINT}"
    return message


_FACT_ARG_KEYS = {
    "ticker",
    "metric",
    "fiscal_year",
    "fiscal_period",
    "period_end_date",
    "yoy_growth",
    "start_fiscal_year",
    "end_fiscal_year",
}


def _call_get_financial_fact(args: dict) -> dict | None:
    """This is a real system boundary, not just an internal call — the
    model doesn't reliably respect the schema. Found live: asked for
    "effective tax rate" (not a supported metric, not in the schema's
    enum) and called this with metric omitted entirely rather than
    picking a valid enum value or skipping the tool, which crashed the
    whole run with an unhandled ValueError from xbrl_facts._tag_for
    before this guard existed. Same class of issue as
    _resolve_search_args's docstring above (the model doesn't always
    include every schema-declared argument) — validate here, at the
    boundary, rather than trusting the schema was followed.

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
    concluded the two segments had equal revenue. Rejecting any
    unrecognized key outright (rather than silently ignoring it) turns
    that into a clean "not supported, try search_filings" fallback.

    `start_fiscal_year`/`end_fiscal_year` (both required together, and
    rejected if combined with yoy_growth) dispatch to
    get_multi_year_average() instead of a single-period lookup -- built
    after the model reached for self-computation on its own for a
    3-year-average question with no deterministic path (see that
    function's own docstring)."""
    if set(args) - _FACT_ARG_KEYS:
        return None
    ticker = args.get("ticker")
    metric = args.get("metric")
    if ticker not in COMPANIES or (metric not in DEFAULT_METRIC_TAGS and metric not in MARGIN_METRIC_FUNCTIONS):
        return None
    fiscal_year = args.get("fiscal_year")
    fiscal_period = args.get("fiscal_period", "FY")
    period_end_date = args.get("period_end_date")
    start_fiscal_year = args.get("start_fiscal_year")
    end_fiscal_year = args.get("end_fiscal_year")
    if start_fiscal_year is not None or end_fiscal_year is not None:
        if args.get("yoy_growth") or start_fiscal_year is None or end_fiscal_year is None:
            return None
        return get_multi_year_average(ticker, metric, start_fiscal_year, end_fiscal_year)
    if args.get("yoy_growth"):
        if metric in MARGIN_METRIC_FUNCTIONS:
            return None
        return get_yoy_growth(ticker, metric, fiscal_year, fiscal_period, period_end_date)
    if metric in MARGIN_METRIC_FUNCTIONS:
        single_company_fn, _ = MARGIN_METRIC_FUNCTIONS[metric]
        return single_company_fn(ticker, fiscal_year, fiscal_period, period_end_date)
    return get_metric(ticker, metric, fiscal_year, fiscal_period, period_end_date)


def _fact_as_result(fact: dict, args: dict) -> dict:
    """Wrap a get_financial_fact value in the same {text, metadata} shape
    hybrid_search results use, so it can share all_results/citation-key
    handling uniformly with search_filings results instead of needing a
    parallel code path."""
    return {
        "text": f"{args['metric']} = {fact['value']} {fact['unit']} (structured XBRL data, not filing prose)",
        "metadata": {
            "ticker": args["ticker"],
            "form": fact["form"],
            "filingDate": fact.get("filed") or fact["period_end"],
            "reportDate": fact["period_end"],
            "accessionNumber": fact["accession"],
            "chunk_index": "xbrl",
        },
    }


_COMPARE_ARG_KEYS = {"anchor_ticker", "metric", "fiscal_year", "fiscal_period", "period_end_date"}


def _call_compare_financial_metric(args: dict) -> dict[str, dict]:
    """Same boundary-validation reasoning as _call_get_financial_fact —
    don't trust the schema was followed, including rejecting an
    unrecognized extra key (e.g. an invented `segment` filter) rather
    than silently ignoring it. No yoy_growth here: there's no current
    evidence/use case for a cross-company YoY-growth comparison, so it
    isn't exposed on this tool (see MARGIN_METRIC_FUNCTIONS' comment and
    get_yoy_growth()'s docstring)."""
    if set(args) - _COMPARE_ARG_KEYS:
        return {}
    anchor_ticker = args.get("anchor_ticker")
    metric = args.get("metric")
    if anchor_ticker not in COMPANIES or (metric not in DEFAULT_METRIC_TAGS and metric not in MARGIN_METRIC_FUNCTIONS):
        return {}
    fiscal_year = args.get("fiscal_year")
    fiscal_period = args.get("fiscal_period", "FY")
    period_end_date = args.get("period_end_date")
    if metric in MARGIN_METRIC_FUNCTIONS:
        _, all_companies_fn = MARGIN_METRIC_FUNCTIONS[metric]
        return all_companies_fn(anchor_ticker, fiscal_year, fiscal_period, period_end_date)
    return get_metric_all_companies(anchor_ticker, metric, fiscal_year, fiscal_period, period_end_date)


def _comparison_as_results(data: dict[str, dict], metric: str) -> list[dict]:
    """Wrap a {ticker: fact} dict (from compare_financial_metric) as a
    list of {text, metadata} results, one per company, reusing the same
    shape _fact_as_result uses for a single company. Unlike a
    companyconcept entry, a frames entry doesn't carry a "form" field —
    there's genuinely no per-company form to report here, so "XBRL
    frame data" stands in for it rather than guessing 10-K vs. 10-Q."""
    results = []
    for ticker, fact in sorted(data.items()):
        results.append(
            {
                "text": f"{ticker} {metric} = {fact['value']} {fact['unit']} (structured XBRL data, not filing prose)",
                "metadata": {
                    "ticker": ticker,
                    "form": "XBRL frame data",
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

    Returns a list of human-readable warning strings (deduplicated),
    empty if nothing looks unverified."""
    warnings: list[str] = []
    seen: set[tuple[int, str]] = set()
    for n, value, unit, verified in _iter_citation_claims(answer_text, all_results):
        if verified:
            continue
        key = (n, f"{value}{unit}")
        if key in seen:
            continue
        seen.add(key)
        warnings.append(f"[{n}] claims {value} ({unit}) but that value doesn't appear in the cited source")
    return warnings


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


def _call_ollama(messages: list[dict]) -> dict:
    response = requests.post(
        OLLAMA_URL,
        json={
            "model": OLLAMA_MODEL_NAME,
            "messages": messages,
            "tools": [FACT_TOOL_SCHEMA, COMPARE_TOOL_SCHEMA, SEARCH_TOOL_SCHEMA],
            "stream": False,
            # Ollama defaults to a 4096-token context window regardless of
            # what the model actually supports, which is dangerously small
            # here: a single search returns up to 5 chunks (~3000 chars
            # each), so a comparison question's SECOND tool call already
            # risks silently truncating the first company's results out of
            # context before the model ever writes its final answer. Found
            # this by inspecting `ollama ps` output (context_length: 4096)
            # after a real comparison-question run behaved suspiciously —
            # worth checking before assuming a synthesis failure is a pure
            # model-capability limit rather than a truncation bug.
            "options": {"temperature": 0.1, "num_ctx": 8192},
        },
        timeout=240,
    )
    response.raise_for_status()
    return response.json()["message"]


def _dispatch_tool_call(
    call: dict, question: str, all_results: list[dict], searched_tickers: set[str | None], verbose: bool
) -> str:
    """Runs one normalized tool call ({"name", "args"} -- the
    ModelTurn.tool_calls shape from llm_backends.py) against the right
    tool, mutating all_results/searched_tickers in place, and returns
    the content string to send back to the model. Backend-agnostic by
    construction: it only ever sees the normalized shape, never
    Ollama's or Gemini's raw wire format, so the boundary validation
    inside _call_get_financial_fact/_call_compare_financial_metric
    (e.g. rejecting an invented `segment` argument) now protects both
    backends automatically instead of needing a second copy."""
    name = call["name"]
    args = call["args"]

    if name == "get_financial_fact":
        if verbose:
            print(f"  [tool call] get_financial_fact({args!r})")
        fact = _call_get_financial_fact(args)
        if fact is None:
            return _format_no_fact_message(args)
        start_index = len(all_results) + 1
        result = _fact_as_result(fact, args)
        all_results.append(result)
        return _format_results_block([result], start_index)

    if name == "compare_financial_metric":
        if verbose:
            print(f"  [tool call] compare_financial_metric({args!r})")
        data = _call_compare_financial_metric(args)
        if not data:
            return _format_no_comparison_message(args)
        start_index = len(all_results) + 1
        results = _comparison_as_results(data, args.get("metric", ""))
        all_results.extend(results)
        return _format_results_block(results, start_index)

    query, ticker = _resolve_search_args(args, fallback_query=question, searched_tickers=searched_tickers)
    searched_tickers.add(ticker)
    if verbose:
        print(f"  [tool call] search_filings(query={query!r}, ticker={ticker!r})")
    results = hybrid_search(query, ticker=ticker, top_k=CHUNKS_PER_SEARCH)
    start_index = len(all_results) + 1
    all_results.extend(results)
    return _format_results_block(results, start_index)


def run_agent(question: str, verbose: bool = False) -> tuple[str, list[dict], list[str]]:
    """Run the tool-calling loop until the model produces a final answer
    (no more tool calls) or MAX_TOOL_ITERATIONS is hit. Returns the
    answer text, every chunk retrieved across all tool calls (in the
    same global [n] order the model was shown them in — this is what
    lets the printed citation key line up with the model's citations),
    and any citation-verification warnings from verify_citations().

    Known simplification: no deduplication if two tool calls happen to
    surface the same chunk (e.g. two related queries against the same
    company). Fine for now — a duplicate citation is cosmetic, not a
    correctness problem — but worth revisiting if it gets noisy.

    No self-correction retry on an unverified citation — tried and
    reverted, see PROJECT_CONTEXT.md's "citation-verification retry
    loop" section for why (qwen2.5:7b-instruct couldn't reliably use the
    corrective feedback: it sometimes just gave up on a previously-
    correct refusal, and once even fabricated an estimate despite an
    explicit instruction not to). citation_warnings is still returned
    below and still worth surfacing/tracing — the model just isn't
    trusted to act on it itself yet."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]
    all_results: list[dict] = []
    searched_tickers: set[str | None] = set()

    for _ in range(MAX_TOOL_ITERATIONS):
        message = _call_ollama(messages)
        tool_calls = message.get("tool_calls") or []

        if not tool_calls:
            answer = message.get("content", "")
            return answer, all_results, verify_citations(answer, all_results)

        messages.append(message)

        for call in tool_calls:
            content = _dispatch_tool_call(
                {"name": call["function"]["name"], "args": call["function"]["arguments"]},
                question,
                all_results,
                searched_tickers,
                verbose,
            )
            messages.append({"role": "tool", "content": content})

    return (
        "I wasn't able to finish answering within the allotted number of searches. "
        "Try asking a more specific or narrower question.",
        all_results,
        [],
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question", help="question to answer")
    parser.add_argument("--verbose", action="store_true", help="print each tool call as it happens")
    args = parser.parse_args()

    answer, results, citation_warnings = run_agent(args.question, verbose=args.verbose)

    print(f"\nQ: {args.question}\n")
    print(answer)
    if results:
        print("\nSources:")
        print(_format_citation_key(results))
    if citation_warnings:
        print("\nCitation warnings:")
        for w in citation_warnings:
            print(f"  {w}")


if __name__ == "__main__":
    main()
