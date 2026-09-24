"""Static model-facing text for the agent model: every fixed string and
template it reads besides the system prompt and tool schemas -- tool
results, no-data messages, tool-argument errors, citation-check
warnings, retry and final-turn messages, and the refusal texts (which
the eval judge also reads).

Templates are filled in at the call site with `.format(...)`, passing
already-computed keyword arguments. Where a message has conditional
parts, each part is its own constant and the choosing logic stays in
agent.py. Never call `.format` on text that already contains model- or
filing-supplied content (answers, quotes, chunks, warnings can contain
`{`); pass that content in as a keyword argument instead."""

# ---------------------------------------------------------------------------
# Tool results
# ---------------------------------------------------------------------------
# The header above each numbered result. agent._strip_citation_header
# reconstructs exactly this text to strip an echoed header from a quote,
# via agent._citation_header, so the two can't drift apart.
CITATION_HEADER_TEMPLATE = "[{i}] {ticker} {form} (reportDate={report_date})"
RESULT_BLOCK_TEMPLATE = "{header}\n{text}"
RESULT_BLOCK_SEPARATOR = "\n\n"
NO_SEARCH_RESULTS_MESSAGE = "(no matching filing excerpts found for this search)"

# A fact or calculate value with its unit. A "raw" value (a plain ratio
# or count) is shown bare instead, since "raw" is an internal label.
VALUE_WITH_UNIT_TEMPLATE = "{value} {unit}"
FACT_RESULT_TEMPLATE = "{metric} = {value} (structured XBRL data, not filing prose)"
COMPARISON_RESULT_TEMPLATE = "{ticker} {metric} = {value} (structured XBRL data, not filing prose)"
# Stands in for the form type of a compare_financial_metric row that
# came from XBRL frames data, which carries no form of its own.
COMPARISON_FRAME_FORM = "XBRL frame data"

# A calculate result. agent.verify_claims exempts the operands of a
# calculate result from its coverage check by taking only the text
# before the first "=" in CALCULATION_RESULT_TEMPLATE's rendering, so no
# expression template may contain "=", and nothing but the operands may
# put a number before the "=".
CALCULATION_PERCENT_CHANGE_EXPRESSION = "percentage change from {value_b} {unit_b} to {value_a} {unit_a}"
CALCULATION_PERCENT_OF_EXPRESSION = "{value_a} {unit_a} as a percentage of {value_b} {unit_b}"
CALCULATION_BINARY_EXPRESSION = "{value_a} {unit_a} {operation} {value_b} {unit_b}"
CALCULATION_RESULT_TEMPLATE = (
    "{expression} = {value} (computed value, not directly stated in any "
    "filing; operands from results [{idx_a}] and [{idx_b}])"
)
# Header fields for a calculate result, which has no filing of its own.
CALCULATION_FORM = "computed value"
CALCULATION_PLACEHOLDER = "N/A"

# ---------------------------------------------------------------------------
# No-data messages (get_financial_fact / compare_financial_metric)
# ---------------------------------------------------------------------------
# A bare "not found" leaves the model unaware WHY data is missing, and it
# then tends to trust noisy search results and fabricate instead of
# refusing -- so the Q4 and never-tagged cases each get an explanatory
# hint appended, joined by NO_DATA_HINT_SEPARATOR.
NO_FACT_TEMPLATE = (
    "(no structured data found for metric={metric!r} "
    "ticker={ticker!r} {fiscal_period!r} "
    "FY{fiscal_year!r} — try search_filings instead)"
)
NO_COMPARISON_TEMPLATE = (
    "(no structured data found for metric={metric!r} "
    "across companies for this period — try search_filings per company instead)"
)
NO_DATA_HINT_SEPARATOR = " "

Q4_NOT_DISCLOSED_HINT = (
    "No company files a separate quarterly report for Q4 -- only Q1-Q3 get a "
    "standalone 10-Q, so a discrete Q4 figure is never independently disclosed "
    "via XBRL; it only exists implicitly as FY minus Q1-Q3. Tell the user this "
    "figure isn't reported as a standalone figure, and stop there -- do not "
    "state, estimate, or mention ANY dollar amount in your answer, not for Q4, "
    "not the full fiscal year total, not from search results or any other "
    "period. Simply explain that quarterly figures aren't broken out this way."
)

NEVER_TAGGED_HINT_TEMPLATE = (
    "{ticker} does not report {metric!r} in its financial statements at all -- for some "
    "metrics (e.g. inventory) this is because it genuinely doesn't apply to the company's "
    "business model (a software/services company with no physical goods has nothing to "
    "report there), not because this specific period is missing. Do not fabricate, "
    "estimate, or infer a value for it; state plainly that this metric isn't reported for "
    "this company, and explain why if the reason is evident (e.g. the business model)."
)

# ---------------------------------------------------------------------------
# calculate: operand-grounding and argument errors
# ---------------------------------------------------------------------------
# Each grounding failure names the field actually at fault (unit vs.
# citation index), because a message blaming the wrong field sends the
# model's retry nowhere useful. Only the last one says retrying won't
# help, since by then both correctable cases have been ruled out.
OPERAND_BAD_CITATION_INDEX_TEMPLATE = (
    "(operand {operand_name}: [{citation_index}] is not a valid citation index -- "
    "results are numbered 1-{result_count})"
)
OPERAND_WRONG_UNIT_TEMPLATE = (
    "({operand_name}={value} is not a {unit} value in result [{citation_index}] -- "
    "that result's own number matches {value} interpreted as {other_unit} instead; "
    "double check {operand_name}'s UNIT specifically)"
)
OPERAND_WRONG_CITATION_INDEX_TEMPLATE = (
    "({operand_name}={value} ({unit}) is not in result [{citation_index}] -- "
    "it matches result [{other_index}] instead; double check {operand_name}'s "
    "CITATION INDEX specifically, not its value or unit)"
)
OPERAND_UNGROUNDABLE_TEMPLATE = (
    "({operand_name}={value} ({unit}) does not appear under ANY unit in result [{citation_index}], "
    "nor under this same unit in any other result you've retrieved -- this is not a retryable mistake. "
    "If this is a unit-conversion constant (e.g. dividing by 1,000,000,000 to convert to billions), do "
    "not use calculate for that at all -- state the converted value directly instead, citing the same "
    "source, per system-prompt rule 9. Otherwise, this operand simply isn't grounded in anything you've "
    "retrieved.)"
)
CALCULATE_INVALID_ARGS_MESSAGE = "(your calculate call didn't match the required schema)"
CALCULATE_CATEGORY_MISMATCH_TEMPLATE = (
    "(cannot {operation} a {category_a} value and a {category_b} value -- "
    "both operands must be the same kind of quantity)"
)
# {operation} is the operation name with underscores replaced by spaces.
CALCULATE_ZERO_DIVISOR_TEMPLATE = "(cannot {operation}: operand_b is zero)"

# ---------------------------------------------------------------------------
# search_filings argument errors
# ---------------------------------------------------------------------------
SEARCH_INVALID_TICKER_TEMPLATE = (
    "(ticker={ticker!r} is not a recognized company — "
    "try one of {valid_tickers} or omit the ticker filter)"
)
SEARCH_INVALID_ARGS_MESSAGE = "(search_filings arguments were invalid — check the tool schema)"

# ---------------------------------------------------------------------------
# Citation-check warnings (agent.CitationWarning.message)
# ---------------------------------------------------------------------------
# The model reads these inside the retry messages below, and the user
# and the eval judge read them inside REFUSAL_TEMPLATE.
CITED_CLAIM_UNSUPPORTED_TEMPLATE = "[{n}] claims {value} ({unit}) but that value doesn't appear in the cited source"
UNCITED_CLAIM_TEMPLATE = (
    "claims {value} ({unit}) but no citation marker appears anywhere "
    "near it to trace the claim to a source"
)
CITATION_OUT_OF_RANGE_TEMPLATE = "[{n}] is not a valid citation index -- results are numbered 1-{result_count}"
MALFORMED_CLAIM_TEMPLATE = (
    "[{n}] must include BOTH value and unit for a numeric claim, or omit both for a qualitative one"
)
NUMERIC_QUOTE_TOO_SHORT_TEMPLATE = "[{n}] claims {value} ({unit}) but its quote {quote!r} is too short to verify"
QUOTE_NOT_FOUND_TEMPLATE = "[{n}] claims {value} ({unit}) but the quoted text doesn't appear in source [{n}]"
VALUE_NOT_IN_QUOTE_TEMPLATE = "[{n}] claims {value} ({unit}) but that value doesn't appear in the quoted text"
QUALITATIVE_QUOTE_TOO_SHORT_TEMPLATE = "[{n}]'s quote {quote!r} is too short to verify"
QUALITATIVE_QUOTE_NOT_FOUND_TEMPLATE = "[{n}]'s quote doesn't appear in source [{n}]"
UNCOVERED_NUMBER_TEMPLATE = "claims {value} ({unit}) but no claim in your submit_answer call covers it"
SUBMIT_INVALID_ARGS_WARNING = "your submit_answer call didn't match the required schema (answer_text/claims)"

# ---------------------------------------------------------------------------
# Retry, forced-submit and final-turn messages
# ---------------------------------------------------------------------------
# One bullet per warning, joined with "\n", in the retry and refusal
# messages.
WARNING_BULLET_TEMPLATE = "- {warning}"

# Shared by both retry messages below so their wording can't drift apart.
# Do not change these properties -- each one closes a failure mode seen
# live when this retry was first tried:
# - It points the model back at results ALREADY shown before it concludes
#   nothing supports a claim (a retry once gave up without checking the
#   other already-retrieved chunks).
# - It has NO deadline or "final attempt" language, says an honest
#   refusal is a completely acceptable outcome, and forbids inventing or
#   estimating a replacement number (a "final attempt" framing once pushed
#   the model to fabricate an estimate on a question whose correct answer
#   is a refusal).
CITATION_RETRY_GUIDANCE = (
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

# Retry after a plain-text answer, sent as a follow-up turn.
CITATION_RETRY_TEMPLATE = (
    "Your previous answer had at least one citation that doesn't hold up:\n"
    "{warnings_block}\n\n"
    "Your previous answer was:\n"
    "{answer}\n\n"
    "{guidance}"
)

# Retry after a submit_answer call, sent as that call's tool result.
CLAIM_RETRY_TEMPLATE = (
    "Your previous submit_answer call had at least one claim that doesn't hold up:\n"
    "{warnings_block}\n\n"
    "Your previous answer_text was:\n"
    "{answer_text}\n\n"
    "{guidance}\n\n"
    "Call submit_answer again with the corrected answer_text and claims."
)

# Sent when the model replies in plain text instead of calling a tool,
# i.e. when it already believes it's done.
FORCE_SUBMIT_MESSAGE = "Please provide your final answer now by calling submit_answer."

# Sent as the tool result for each pending call when the tool-call budget
# runs out mid-flow, so it must read sensibly as "this request was not
# run". Unlike FORCE_SUBMIT_MESSAGE's case, the model here was cut off
# and has most likely not reasoned about coverage yet, hence the rule 6/7
# check. Same constraints as CITATION_RETRY_GUIDANCE: no "final attempt"
# or deadline language, an honest refusal is a completely acceptable
# outcome, and never guess or estimate.
FINAL_TURN_SUBMIT_MESSAGE = (
    "No more tool calls are available for this question -- nothing else will be "
    "dispatched, so this request was not run. Call submit_answer now using only what "
    "you've already retrieved above.\n\n"
    "Before you do, check rule 6: did you actually get data for every company, "
    "period, or quantity this question asks about? If something is missing or came "
    "back unavailable, do not present a partial result as if it fully answers the "
    "question -- name what's missing per rule 7, or refuse per rule 2 if the missing "
    "piece could change the answer (e.g. you can't rank or compare without it). An "
    "honest refusal, or an answer that explicitly says what you could and couldn't "
    "verify, is a completely acceptable outcome here -- do not guess, estimate, or "
    "invent a value for anything you didn't actually retrieve."
)

# Tool result for a submit_answer call made in the same turn as other
# tool calls: the submission can't be grounded in results the model
# hasn't read yet.
MIXED_TURN_RESUBMIT_MESSAGE = (
    "You also requested new searches in this same turn; their results are included "
    "above. Read them, then call submit_answer again with your final answer."
)

# ---------------------------------------------------------------------------
# Final answers the agent substitutes for the model's own
# ---------------------------------------------------------------------------
# Replaces an answer whose citations still don't check out.
REFUSAL_TEMPLATE = (
    "I can't confirm this answer against the sources I retrieved -- "
    "the following claim(s) don't hold up under citation verification:\n{warnings_block}\n\n"
    "Rather than give you a number I can't verify, I'm refusing this answer."
)
BUDGET_EXHAUSTED_ANSWER = (
    "I wasn't able to finish answering within the allotted number of searches. "
    "Try asking a more specific or narrower question."
)
