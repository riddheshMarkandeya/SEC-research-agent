# Schema-driven arg/input validation (tool args, LLM responses, companies.json)

## Context

`BACKLOG.md`'s highest-impact open item is a recurring bug pattern: three
tools in `agent.py` (`call_get_financial_fact`, `call_compare_financial_metric`,
and `search_filings`'s inline dispatch validation) each hand-check their
args against their own `*_TOOL_SCHEMA` declaration, and that hand-validation
has broken three separate times across three review dates (most recently:
`isinstance(fiscal_year, int)` silently accepts a JSON boolean, since
`isinstance(True, int)` is `True` in Python). There's also a live,
currently-undetected gap: `mcp_server.py`'s `_search_filings` handler does
zero ticker validation, unlike the `agent.py` dispatch path.

The user chose to fix this with a generic `jsonschema`-driven validator
rather than a 4th hand-rolled check (design fork resolved via
`AskUserQuestion`), then asked where else in the codebase the same
schema-validation approach would help. A follow-up Explore pass found two
more real trust-boundary gaps worth fixing in the same change (also
confirmed via `AskUserQuestion`): `llm_backends.py` indexes into the raw
LLM response (`c["function"]["name"]`, `resp.candidates[0]`) before any
shape check, and `companies.py`'s `load_companies()` has no runtime check
on `companies.json`'s shape, so a bad edit surfaces as a confusing
`KeyError` deep in an unrelated ticker/metric lookup instead of one clear
error at startup.

Two originally-considered items (the `xbrl_facts.py` `get_frame()` ordering
bug, and a `retrieval.py` manual verification script) were explicitly
descoped by the user to keep this change focused on schema validation —
they remain untouched in `BACKLOG.md` for later.

Explored via 3 parallel Explore agents, one Plan-agent design review, and
one further Explore pass on additional validation opportunities (full
findings folded into the design below).

## 1. Tool-arg schema validator (`agent.py`, `mcp_server.py`) — the core fix

**Library choice**: `jsonschema` (confirmed already installed transitively
via `chromadb`/`mcp`, but not a direct dependency — pin `jsonschema==4.26.0`,
current latest on PyPI, in `requirements.txt`). Chosen over hand-rolling
because `jsonschema`'s default type checker for `"integer"` already
excludes `bool` (`isinstance(x, int) and not isinstance(x, bool)`), fixing
the recurring bool/int bug as a side effect of the library switch. Confirmed
via a Plan-agent review (empirically, not just reasoning) that
`jsonschema.iter_errors` evaluates `type`/`enum` via plain equality/membership
checks, never by hashing the instance — safe against the same
non-hashable-value crash class (`ticker=["a","b"]`) the 2026-09-10 fix had
to specifically guard against.

**Design**:

- Add `"additionalProperties": false` to all three `*_TOOL_SCHEMA["function"]["parameters"]`
  dicts in `agent.py` (`SEARCH_TOOL_SCHEMA` agent.py:109-130,
  `FACT_TOOL_SCHEMA` agent.py:132-198, `COMPARE_TOOL_SCHEMA` agent.py:200-250+).
  Each schema now doubles as the single source of truth for both what's
  advertised to the LLM and what's enforced at runtime — replacing the
  hand-rolled `set(args) - _FACT_ARG_KEYS` / `_COMPARE_ARG_KEYS` extra-key
  checks.
- Add one generic function in `agent.py`, next to the schemas, matching the
  existing bool-return/log-as-side-effect style of `_rejects_invalid_fiscal_year`
  (agent.py:382-397):

  ```python
  def _validate_tool_args(tool: str, schema: dict, args: dict) -> bool:
      """True (having already logged the rejection) if args fails schema's
      parameter validation -- except a `metric` enum violation, which is
      allowed through so callers can route it to record_unmet_metric_request
      instead of a generic boundary rejection."""
      validator = jsonschema.Draft202012Validator(schema["function"]["parameters"])
      for error in sorted(validator.iter_errors(args), key=_error_priority):
          if error.validator == "enum" and list(error.path) == ["metric"]:
              continue
          reason = _reason_for_error(error)
          log_event("tool_call_rejected", tool=tool, reason=reason, args=args)
          return True
      return False
  ```

  `_reason_for_error(error)` maps jsonschema's error vocabulary to a new
  `reason=` taxonomy:
  - `additionalProperties` violations (one error covers all extra keys, no
    single offending property) → fixed literal `"unrecognized_extra_argument"`.
  - `required` violations (missing key lives in `error.message`, not
    `error.path`) → fixed literal `"missing_required_argument"` (don't
    over-engineer per-field granularity nobody asked for — the logged
    `args` dict already shows what's missing).
  - `type`/`enum` violations on a named property → `f"{error.path[0]}_{kind}"`,
    e.g. `ticker_not_in_enum`, `fiscal_year_wrong_type`.
  - Check whether any existing test constructs args violating two rules at
    once and asserts a specific one wins; `iter_errors`' iteration order
    isn't guaranteed to match the old hand-rolled priority order, so
    `_error_priority` may need a fixed priority (`additionalProperties` →
    `required` → `type` → `enum`) to preserve those expectations.
- **The one carve-out**: a `metric` value that's present and correctly
  typed but not in `DEFAULT_METRIC_TAGS`/`RATIO_DEFINITIONS` must NOT be a
  generic hard-rejection — today this case calls
  `record_unmet_metric_request(...)` (a "should we add support for this
  metric" telemetry signal) with `reason="unknown_metric"`, and 3 existing
  tests (`test_call_get_financial_fact_does_not_record_unmet_request_on_boundary_rejection`
  and 2 siblings) assert boundary rejections must never pollute that
  signal. `_validate_tool_args` explicitly skips an `enum`-only violation
  on `metric` and lets it fall through to each tool's existing
  metric-specific business logic unchanged (agent.py:486-497 /
  agent.py:615-623). A missing or wrong-typed `metric` still hard-fails
  generically (no bookkeeping needed).
- Keep as separate, post-generic-validation business-rule checks (not
  expressed in JSON Schema, to avoid `dependentSchemas`/`if-then-else`
  complexity leaking into the LLM-facing schema): the multi-year-average
  combo check (agent.py:503-518) and the yoy_growth-unsupported-for-ratio
  check (agent.py:531-536).
- Call `_validate_tool_args` first in `call_get_financial_fact`,
  `call_compare_financial_metric`, and the `search_filings` branch of
  `_dispatch_tool_call` (agent.py:991-1017) — before `_resolve_search_args()`'s
  `ticker in searched_tickers` set-membership check, preserving the
  ordering the 2026-09-10 fix already established.
- Fix `mcp_server.py`'s `_search_filings` handler (mcp_server.py:130-137) by
  calling the same `_validate_tool_args(..., SEARCH_TOOL_SCHEMA, args)`
  before proceeding — `get_financial_fact`/`compare_financial_metric`
  already get this validation "for free" via their existing delegation
  into `agent.py`'s now-validated `call_*` functions.
- **Do not** extract a shared `call_search_filings()` wrapper (considered
  and rejected): the two call sites' post-validation logic differs
  meaningfully (agent.py resolves `query`/tracks `searched_tickers`/falls
  back to the question; mcp_server.py calls `hybrid_search` directly with
  no fallback concept) — no real shared logic beyond "call the validator
  then branch," so a wrapper would be exactly the speculative abstraction
  CLAUDE.md's YAGNI principle rules out.

**Tests** (`tests/test_agent.py`, `tests/test_mcp_server.py`): the ~25
existing hand-written per-field validation tests get consolidated into a
smaller set of schema-driven parametrized cases (walking each schema's
declared properties) plus the tests that must remain bespoke: the
multi-year-average/yoy_growth combo tests, the metric-unmet-request
telemetry-purity tests, and the non-hashable-value crash guards (now
regression tests proving the generic path prevents the crash). Any test
asserting an exact old `reason=` string needs updating to the new
taxonomy — expected migration cost, not scope creep. Add a new test for
`mcp_server.py`'s previously-unvalidated `_search_filings` ticker check.

## 2. Validate the LLM response boundary (`llm_backends.py`)

Real gap: `_ollama_message_to_turn` (line 40) indexes `c["function"]["name"]`/
`c["function"]["arguments"]` with no check that `tool_calls` entries actually
have that shape; `_gemini_response_to_turn` (lines 206-209) indexes
`resp.candidates[0]` with no check that `candidates` is non-empty (a real
possibility — e.g. a safety-filtered response). Both currently crash with a
bare `KeyError`/`IndexError` *before* the tool-call ever reaches `agent.py`'s
dispatch/validation.

- **Ollama's raw response is a plain dict** (`response.json()["message"]`) —
  a genuine JSON-native boundary, so `jsonschema` is a clean fit. Add a
  small schema for the raw Ollama `message` shape (`content` optional
  string-or-null, `tool_calls` optional array of `{"function": {"name":
  string, "arguments": object}}`) and validate it in `_ollama_message_to_turn`
  before indexing into `tool_calls`. On failure, raise a clear `RuntimeError`
  naming what was malformed (this is a wire-format bug, not a recoverable
  per-request situation — fail loudly, don't swallow) plus a `log_event`
  call matching this module's existing `llm_retry` logging pattern.
- **Gemini's raw response is an SDK object, not a JSON dict** — `jsonschema`
  doesn't apply directly without first converting it, which is unwarranted
  ceremony for one field. Instead add a plain guard clause: `if not
  resp.candidates: raise RuntimeError(...)` before indexing `resp.candidates[0]`.
  This is a deliberate, documented exception to "use jsonschema for this
  boundary" — the input isn't JSON-serializable data at this point.
- **Both backends' *normalized* output is a plain dict/list** (`ModelTurn.tool_calls`,
  the `[{"name": str, "args": dict}]` shape documented in the module
  docstring, lines 30-34) — this is the one truly shared, JSON-native
  boundary, and it's exactly what `agent.py`'s `_dispatch_tool_call`
  actually consumes (`call["name"]`/`call["args"]`, agent.py:960-961). Add
  one shared schema + validation call (`_validate_tool_calls(backend,
  tool_calls)`) at the end of both `_ollama_message_to_turn` and
  `_gemini_response_to_turn`, right before constructing `ModelTurn(...)`.

**Tests** (new `tests/test_llm_backends.py` section, or extend if one
exists — confirm during implementation): malformed raw Ollama message
(missing `function` key, non-dict `arguments`) raises a clear error;
empty Gemini `candidates` raises a clear error; a malformed normalized
tool-call shape (e.g. `args` not a dict) is caught by the shared validator
regardless of which backend path produced it.

## 3. Validate `companies.json` at load time (`companies.py`)

Real gap: `load_companies()` (companies.py:21-26) does `json.loads(...)`
with zero shape check. Downstream, `agent.py:87`, `xbrl_facts.py:167`,
`period_labels.py:78`, and `edgar_ingest.py:186` all do raw
`info["name"]`/`info["cik"]`/`info["fiscal_year_end_month"]` indexing — a
malformed entry surfaces as a confusing `KeyError` in some unrelated
ticker/metric lookup instead of one clear error at startup.

- Add a schema (top-level object, `additionalProperties` = per-company
  object schema requiring `name` (string), `cik` (string),
  `fiscal_year_end_month` (integer, 1-12), `additionalProperties: false`
  on the per-company object too).
- Extract a small `_validate(data: dict) -> None` function that runs
  `jsonschema.validate(data, COMPANIES_SCHEMA)` and re-raises
  `jsonschema.ValidationError` as a plain `ValueError` with a message
  naming `companies.json` and the underlying `error.message` — a clear
  single failure at load/import time (`agent.py` imports `COMPANIES` at
  module level) rather than a mystery `KeyError` three layers down later.
  Catching the specific `jsonschema.ValidationError` type here (not a
  broad `except Exception`) per CLAUDE.md's error-handling guidance.
- Call `_validate(data)` inside `load_companies()` before returning.

**Tests** (`tests/test_companies.py`): call `_validate` directly (not via
the real file) with in-memory dicts — missing `cik`, wrong-typed
`fiscal_year_end_month`, an unexpected extra key — asserting each raises a
clear `ValueError`; one test confirms the real `companies.json` still
loads cleanly (regression guard against the schema itself being wrong).

## Explicitly out of scope (noted, not fixed here)

- `xbrl_facts.py`'s `get_metric()` (lines 353-386) does unchecked
  `entry["val"]`/`entry["end"]`/`entry["form"]`/`entry["accn"]` indexing on
  SEC API response entries — real but lower severity (SEC's schema is
  stable, surrounding code is already fairly defensive). **Add a new Low
  item to `BACKLOG.md`** for this during implementation, per CLAUDE.md's
  backlog-hygiene rule (log it the moment it's identified, not at wrap-up) —
  it was surfaced during this investigation but wasn't part of what the
  user chose to fix now.
- `eval_harness.py`'s `_select_questions` reads `q["id"]` before the
  per-question `try/except` that already contains most other malformed-question
  crashes — narrow, low-traffic (offline eval tool, not a live path). Also
  worth a `BACKLOG.md` line, not a fix, for the same reason.
- The `xbrl_facts.py` `get_frame()` ordering bug and the `retrieval.py`
  manual verification script (both originally scoped into this task) stay
  in `BACKLOG.md` untouched, per the user's explicit descoping request.

## Verification

- Run `pytest` (full suite) — must pass, including the pre-commit-hook
  gate. New/updated tests must fail before each fix and pass after
  (red-green).
- Manually spot-check both live paths aren't broken by the new validators:
  a real `python agent.py "..."` run (exercises `agent.py`'s dispatch +
  `llm_backends.py`'s Ollama path) and one MCP call via
  `tests/manual/verify_mcp_server.py` (exercises the `search_filings`
  fix). Confirm legitimate args still succeed, not just that bad args are
  now rejected.
- Per CLAUDE.md step 7: run `/code-review` (medium effort, given the
  size) for a correctness/compliance pass, then a separately-spawned
  fresh subagent for an architecture/design pass on the diff. Save
  findings to `docs/reviews/2026-09-09-<slug>.md`, fix what's found, and
  repeat both passes on the fix (capped at 2 rounds with no new issues).
- Update `PROJECT_CONTEXT.md` with a `###` write-up per CLAUDE.md step 6
  and remove this item from `BACKLOG.md` once done, while adding the two
  new out-of-scope items noted above.
