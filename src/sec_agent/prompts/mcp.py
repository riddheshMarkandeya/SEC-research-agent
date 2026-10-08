"""Static model-facing text for MCP clients: the error strings the MCP
server's tool handlers return, and MCP_SEARCH_TOOL_SCHEMA, its own
search_filings schema. The fact and compare schemas it lists come from
prompts.agent_tools unchanged."""

from sec_agent.prompts.agent_system import COMPANY_COUNT
from sec_agent.prompts.agent_tools import SEARCH_TOOL_SCHEMA

FACT_NOT_AVAILABLE_ERROR = "not available for this company/metric/period"
COMPARISON_NOT_AVAILABLE_ERROR = "not available for this metric/period"
UNKNOWN_TOOL_TEMPLATE = "Unknown tool: {name!r}"

# The agent's search schema with MCP-true descriptions: MCP clients get
# no system prompt, and their query is searched as given (the agent loop
# substitutes the user's question on each company's first search).
# Parameters are otherwise identical, so validation behaves the same.
_search = SEARCH_TOOL_SCHEMA["function"]
_search_parameters = _search["parameters"]
MCP_SEARCH_TOOL_SCHEMA = {
    **SEARCH_TOOL_SCHEMA,
    "function": {
        **_search,
        "description": (
            f"Search SEC 10-K/10-Q filing excerpts from the {COMPANY_COUNT} covered companies. Returns the most "
            "relevant excerpts as a list of {text, source} objects, where source identifies the filing. "
            "Use it for narrative content (risk factors, MD&A, segment or product-line figures) and for "
            "any metric get_financial_fact doesn't cover or finds no data for. Pass ticker to restrict "
            "the search to one company. It returns filing text only, not structured XBRL values."
        ),
        "parameters": {
            **_search_parameters,
            "properties": {
                **_search_parameters["properties"],
                "query": {
                    **_search_parameters["properties"]["query"],
                    "description": "What to search for, as a natural-language question or phrase.",
                },
            },
        },
    },
}


# Hashed into prompts.prompt_fingerprint().
FINGERPRINTED = (
    "FACT_NOT_AVAILABLE_ERROR",
    "COMPARISON_NOT_AVAILABLE_ERROR",
    "UNKNOWN_TOOL_TEMPLATE",
    "MCP_SEARCH_TOOL_SCHEMA",
)
NOT_FINGERPRINTED = ()
