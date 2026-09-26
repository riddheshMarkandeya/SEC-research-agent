# Review: WP5, segment-rule plain wording (commit d45156f)

Plan: `docs/plans/2026-09-24-wp5-segment-rule.md`. Commit 5a replaces "If a question asks
about a specific segment or product line, do NOT call this tool at all, not even to try —
go straight to `search_filings` instead." with "For a question about a specific segment or
product line, use `search_filings` instead of this tool." in SYSTEM_PROMPT's
`get_financial_fact` bullet. The snapshot was regenerated, and the agent fingerprint moved
from `d2131f5d5aae` to `5d3cea51c73b`.

The review ran the five-pass `independent-review-pass` over `a3965f3..d45156f` in 1 round.
Beforehand, ruff and pyright were clean and all 920 tests passed.

## Round 1

### Pass 1: correctness (`/code-review`, low)
- No findings.
- The bullet still reads coherently. The sentence before it (consolidated totals only)
  explains the routing, and the later "no `segment` parameter … rejected outright" still
  covers invented arguments.

### Passes 2 and 3: comments, docs and design (one fresh subagent)
- **Clean.** Outside `docs/`, nothing quotes the removed wording ("not even to try", "call
  this tool at all").
  - `agent.py`'s `segment` mentions are about rejecting invented arguments, a separate
    contract that still holds.
- **The new sentence agrees with the rest of the prompt surface:**
  - the search descriptions at `prompts/agent_tools.py:29` and `prompts/mcp.py:25`
    ("segment or product-line figures");
  - `FACT_TOOL_SCHEMA`, which doesn't mention segments;
  - `prompts/agent_messages.py`, which has no segment rejection message.
- **No contract fact was lost.**
- [Not adopted, nit] "instead of this tool" adds little. The plan review added it
  deliberately, so that "instead" has an object once "do NOT call this tool" is gone.
- [Pre-existing, filed] Later in the same bullet, "so search_filings instead" uses the tool
  name as a verb. It predates WP5, which doesn't touch it, so it is filed for WP8 with the
  all-caps wording (finding 8).
- Performance and modularity don't apply: the change is prompt text only.

### Pass 4: security (fresh subagent)
- No findings.
- The grounding controls are unchanged: consolidated totals only, no `segment` parameter,
  unrecognized arguments rejected, and uncited self-computed values refused.

### Pass 5: `/simplify` (reuse, simplification, efficiency, altitude)
- **No edits.** All wording suggestions were reported, not applied, because the text was
  about to be screened.
- [Not adopted] The simplification and reuse agents suggested folding the new sentence into
  the one before it ("… segment) — use `search_filings` for those"), or dropping "(e.g. there
  is no `segment` parameter)".
  - This is repeated guidance (audit finding 9), which WP8 files.
  - Changing it now would also change what the screen measures.
- Efficiency: SYSTEM_PROMPT is about 12 words shorter.
- Altitude: the right depth. Invented arguments are already rejected in code
  (`validate_tool_args`). Routing a segment question away from a consolidated lookup can
  only be done in the prompt, short of classifying questions in code.

## Outcome

The review closed clean after one round, with no fix commits and no model-facing change.
Two findings were not adopted, for the reasons above. The "so search_filings instead"
wording goes to BACKLOG with WP5's docs.
