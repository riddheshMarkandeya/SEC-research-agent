"""Static model-facing text for MCP clients: the error strings the MCP
server's tool handlers return. (The tool schemas it lists come from
prompts.agent_tools.)"""

FACT_NOT_AVAILABLE_ERROR = "not available for this company/metric/period"
COMPARISON_NOT_AVAILABLE_ERROR = "not available for this metric/period"
UNKNOWN_TOOL_TEMPLATE = "Unknown tool: {name!r}"
