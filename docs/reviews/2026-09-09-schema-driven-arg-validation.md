# Review: schema-driven arg/input validation (2026-09-09)

Reviewing the change described in `docs/plans/2026-09-09-schema-driven-arg-validation.md`.

## Pass 1: `/code-review` (medium effort) — correctness/compliance

One real, confirmed regression, found in three places (same root cause):

1. **`agent.py`** — `SEARCH_TOOL_SCHEMA`'s `ticker` property had no `null`
   type option (unlike `period_end_date`, which this same diff had
   already made nullable). An explicit `ticker: null` — previously
   tolerated by the old hand-rolled check (`if raw_ticker is not None and
   (...)`) as "no ticker filter" — hard-failed the new generic validator
   and short-circuited the search entirely.
2. **`mcp_server.py`** — the same gap broke the MCP `_search_filings`
   entry point, which reuses the identical schema and call shape.
3. **`agent.py`** — `FACT_TOOL_SCHEMA`'s `fiscal_period` (and
   `yoy_growth`) were likewise typed without `null` and not in
   `skip_properties`, so `fiscal_period: null` hard-rejected
   `get_financial_fact` calls that used to silently proceed with
   `fiscal_period=None`.

**Root cause**: the `period_end_date` nullable fix was applied as a
one-off, per-property patch after live testing surfaced it, rather than
recognizing the general problem — every optional property has the same
gap, since nothing downstream distinguishes "key absent" from "key
present with an explicit JSON null" (every reader uses `args.get(...)`,
which returns `None` either way).

**Fix applied**: replaced the per-property `["string", "null"]` patches
(reverted `period_end_date` back to plain `"string"`) with one general
rule inside `_validate_tool_args`: a declared property whose value is
`None` is validated as though the key were absent. This correctly
converts a null on a **required** property into a `missing_required_argument`
rejection (matching the old behavior for e.g. `ticker: null` on
`get_financial_fact`) and a null on an **optional** property into "no
violation" (matching the old tolerant behavior for e.g. `ticker: null` on
`search_filings`). An unrecognized extra key is deliberately NOT stripped
even when null-valued, so `additionalProperties: false` still catches
e.g. `{"segment": None}` — the key itself is the problem, not its value.

Regression tests added (`tests/test_agent.py`): null optional property
tolerated, null required property still rejected, null-valued extra key
still rejected, plus two end-to-end regression tests through
`call_get_financial_fact`/`_dispatch_tool_call` directly. Full suite:
440 passed after the fix (was 435 before this pass; the 5 new tests are
the ones added here).

## Pass 2: architecture/design (fresh subagent)

Findings from a subagent with no memory of the implementation session,
given the diff and plan context cold.

1. **[Fixed] Nondeterministic tie-break ordering.** `_validate_tool_args`'s
   `priority()` tie-break routed `property_order` through
   `set(params.get("properties", {}))` (introduced by pass 1's null-handling
   fix), losing the dict's declaration order and making same-kind
   multi-violation tie-breaks depend on the process's hash seed instead of
   schema order. No test currently exercises a two-properties-same-kind
   case, so this hadn't surfaced as a flaky test yet, but it's a real
   regression from the plan's stated "fixed priority" design. Fixed:
   removed the `set(...)` wrapper — `in` on a dict is already O(1), so
   there was no reason to convert away from the order-preserving dict in
   the first place.
2. **[Fixed] Underscore-prefixed name used as cross-module production
   infrastructure.** `_validate_tool_args` is imported by `mcp_server.py`
   as real shared infrastructure (not test white-boxing, the only other
   place this codebase imports underscored names across modules), which
   signals "internal, don't import this" while actually being part of the
   module's real contract now. Renamed to `validate_tool_args` throughout
   `agent.py`, `mcp_server.py`, and `tests/test_agent.py`.
3. **[Deferred, filed to BACKLOG.md]** `_dispatch_tool_call`'s
   `search_filings` branch re-derives ticker validity by hand
   (`isinstance`/`COMPANIES` membership) a second time, after
   `validate_tool_args` already checked the same thing internally via the
   schema, just to decide which rejection message to show. A real
   residual instance of the exact "hand-rolled check duplicating the
   schema" pattern this whole redesign set out to eliminate, but fixing it
   cleanly means changing `validate_tool_args`'s return type across all 4
   call sites for a 2-line message-selection convenience — out of
   proportion to what this change needs right now. Filed as a Low item.
4. **Acknowledged, not fixed.** A fresh `jsonschema.Draft202012Validator`
   is built on every `validate_tool_args` call rather than cached at
   module scope (unlike `llm_backends.py`'s two new validators). Reviewer's
   own assessment: negligible cost given this is a low-QPS local agent
   loop and the schemas are tiny — not worth a special-case fix on its
   own. Left as-is.

Everything else the reviewer checked came back clean: the
`soft_required`/`skip_properties` carve-outs are proportionate to three
concrete, documented needs rather than speculative abstraction;
`call_get_financial_fact`/`call_compare_financial_metric`'s docstrings
read correctly against the refactored code; `companies.py`'s per-call
re-validation is pre-existing "read fresh every call" design, not new
overhead worth flagging.

## Round 2 (re-review after fixes)

Re-ran `/code-review` (medium) and a second fresh architecture-review
subagent against the fixed diff.

**`/code-review` round 2**: one real, actionable gap — this Substantial-
tier change had no `PROJECT_CONTEXT.md` changelog entry yet, violating
CLAUDE.md step 6. Fixed: added the "Schema-driven arg/input validation
redesign (2026-09-09)" section. Two other findings were raised but
deliberately not acted on: (a) `validate_tool_args` hardcodes the
literal property name `"metric"` for its enum carve-out instead of
taking it as a parameter like `soft_required`/`skip_properties` do —
acknowledged as a real inconsistency, but generalizing it now for a
hypothetical 4th tool that doesn't exist yet would be exactly the
speculative abstraction CLAUDE.md's YAGNI principle rules out; (b) the
per-call validator-construction cost — the same finding as round 1's
architecture pass, restating rather than a new issue, so left as-is per
the same reasoning (negligible given LLM-inference-dominated latency) and
because a repeated finding with no clean fix is this project's own
stated stopping condition for the review loop.

**Architecture round 2** (fresh subagent, told what round 1 already
found/fixed so it wouldn't re-flag the same things): confirmed the
rename is complete with no stray references anywhere, confirmed no other
ordering-sensitive `set()` conversion was introduced elsewhere in the
diff, and found `validate_tool_args`'s body still readable end-to-end
despite two rounds of patches (the null-handling docstring paragraph is
dense but accurate). No new findings. Explicitly assessed the diff as
"clean... ready to close without a third round."

Both passes converged on no new issues — stopping here per CLAUDE.md's
two-round cap. Full suite: 440 passed.

