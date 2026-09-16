# Adopt `pyright` as this project's type checker (basic mode)

**Date:** 2026-09-15

## Context

Asked whether this project would benefit from strict static type
checking (mypy/Pyright/ty). No type checker was configured anywhere.
Sampling suggested the codebase was already 85-90% type-annotated
across core modules, with `NamedTuple`/`@dataclass` already used for
key result types — on that basis, Pyright in **strict** mode was chosen
initially, on the reasoning that the gap looked small and this session
runs inside VS Code (where Pyright/Pylance likely already surfaces
feedback live).

Strict mode's real baseline, measured by actually running it (not
estimated), was **4,655 errors** — far larger than the sampled estimate
implied. This wasn't a missing-annotations problem: ~94% of the errors
(4,366) fell into 7 "Unknown-type propagation" categories
(`reportUnknownVariableType` 971, `reportUnknownMemberType` 886,
`reportUnknownParameterType` 738, `reportUnknownLambdaType` 580,
`reportMissingParameterType` 565, `reportUnknownArgumentType` 461,
`reportMissingTypeArgument` 165). Strict mode's Unknown-propagation
checks cascade through this codebase's dict-shaped data flow (a bare
`dict` return type, or any call into a third-party function lacking
stubs, poisons every downstream variable as "Unknown") — exactly the
friction the original type-coverage research flagged as a risk. Even
scoped to just the 7 core modules named in this project's `CLAUDE.md`,
strict mode's baseline was still ~965 errors, nowhere near "a handful of
fixes."

Measured **basic** mode too, for a real comparison rather than a guess:
154 errors — the same order of magnitude as `ruff`'s own existing
155-violation baseline (`docs/decisions/2026-09-15-adopt-ruff-linter.md`),
with only ~35 in the 7 core modules and those genuinely useful catches
(e.g. `xbrl_facts.py`'s duration-window filters compared an `int | None`
with `<=` before narrowing out `None`).

## Decision

Adopted **Pyright in basic mode**, not strict. `pyright==1.1.414` and
`lxml-stubs==0.5.1` added to `requirements-dev.txt`; `[tool.pyright]`
added to `pyproject.toml` (`typeCheckingMode = "basic"`,
`pythonVersion = "3.13"`, `venv`/`venvPath` pointed at `.venv`,
generated/data directories excluded).

Fixed all ~37 basic-mode errors across the 7 core modules named in this
project's `CLAUDE.md` (`agent.py`, `xbrl_facts.py`, `retrieval.py`,
`llm_backends.py`, `formulas.py`, `index_chunks.py`, plus
`period_labels.py`/`companies.py`), and `tracing.py` (not in that list,
but small enough to clean up in the same pass — 3 errors). All fixes
were either genuine correctness improvements (a wrong `load_companies()`
return-type annotation that called `fiscal_year_end_month` a `str` when
it's an `int`; using `types.FunctionCallingConfigMode.ANY` instead of
the bare string `"ANY"`; a `TypeGuard[int]` on `_is_valid_int` so its
callers narrow properly; `.tolist()` on embedding/rerank-score tensors
before they reach code that expects plain lists) or narrow, one-line
`assert`s documenting an invariant pyright can't see across a function
boundary (e.g. `_load_bm25_index()` always sets both module globals it
touches) — never a behavior change. A small number of genuine
third-party stub/runtime mismatches (chromadb's `Where` type not
covering its own documented equality shorthand; google-genai's
`FunctionDeclaration.parameters` stub not advertising the dict shorthand
its own pydantic model accepts at runtime; langfuse's `as_type` being a
private, per-call-overloaded Literal with no public general type to
substitute) were left in place and suppressed with a narrow, commented
`# pyright: ignore[...]` rather than rewritten around.

The remaining baseline is **117 errors, entirely in test files
(110: `test_formulas.py`, `test_xbrl_facts.py`, `test_agent.py`,
`test_llm_backends.py`, `test_mcp_server.py`, `test_edgar_ingest.py`)
and manual verify scripts (7: `verify_mcp_server.py`,
`verify_tracing.py`, `verify_period_labels.py`)** — not fixed now,
mirroring ruff's own "measure once, don't retroactively fix a
pre-existing baseline" precedent. Tracked in `BACKLOG.md`.

**Rollout stage**: `pyright <changed files>` scoped to files the
current change touches, run manually as part of step-7 review — same
stage as ruff, not a pre-commit gate yet.

## Why

**Basic over strict**: strict mode's baseline was ~30x ruff's own, and
~94% of it was Unknown-type-propagation noise from this codebase's
dict-heavy data flow rather than real gaps — fixing it fully would be a
Substantial, multi-day effort across every core module (not what
"strict from day one" was chosen on the assumption of), and leaving it
unfixed risked the tool's changed-files-scoped output staying too noisy
to act on even for a one-line diff in a heavily-affected file like
`agent.py`. Basic mode's 154-error baseline matched the original
85-90%-annotated estimate and this project's own ruff precedent almost
exactly.

**Fix now vs. defer**: the ~37 core-module errors were small and mostly
real (Optional-narrowing gaps, one wrong return-type annotation, one
literal-vs-enum mismatch) — proportionate to fix immediately, unlike
strict mode's baseline. The 117 remaining are entirely in tests/scripts,
lower-value to fix opportunistically (mocks and fixtures are the
dominant source of `reportOptionalSubscript`/`reportOptionalMemberAccess`
noise there) and left for the same "fix what's touched, not
retroactively" policy that governs ruff's own baseline.

**Ignore over rewrite for genuine stub mismatches**: in each case (the
3 covered above), the underlying SDK's *runtime* behavior already
accepts what the code passes (confirmed live, not assumed — see
Verification), and the "fix" would mean depending on a private
submodule (langfuse) or constructing a more complex object than the
SDK's own convenience shorthand already produces correctly
(google-genai, chromadb) — worse trades than a one-line, specifically-
coded ignore with a comment explaining why.

## Files touched

`requirements-dev.txt`, `pyproject.toml`, `CLAUDE.md`, `BACKLOG.md`,
`companies.py`, `period_labels.py` (untouched, only companies.py's
return type changed), `agent.py`, `xbrl_facts.py`, `formulas.py`,
`retrieval.py`, `llm_backends.py`, `index_chunks.py`, `tracing.py`.

## Verification

`pyright` run against the full repo three times (initial strict
baseline, basic-mode comparison, and the final post-fix basic-mode run)
— real output captured and counted each time, not estimated. Full
`pytest` suite (652 tests) green after every core-module edit. Live
spot-checks, since several edits touched live-code-carve-out modules
per `.claude/rules/live-code-tdd.md` and `.claude/rules/live-eval-verification.md`:
`retrieval.py`'s hybrid search + rerank pipeline run live end-to-end
(`python retrieval.py "What is Salesforce's remaining performance
obligation?" --ticker CRM`, correct results returned, exercising the
new `Where`-typed filter and the `.tolist()` conversions);
`xbrl_facts.get_metric()` run live for both a duration-based fact
(NVDA revenue, Q3) and an instant fact (NVDA total_assets, FY) to
confirm the walrus-operator narrowing in `_pick_entry`/
`_pick_entry_by_end_date` didn't change the duration-window filtering
logic; `formulas.get_multi_year_average()` run live (NVDA revenue,
FY2024-2026); a two-call live Gemini spot-check
(`_gemini_start` + `_gemini_send_followup(force_tool=...)`) confirming
`FunctionCallingConfigMode.ANY` and the `parameters=parameters` schema
conversion both work identically against the real API.

## Related

Paired with `docs/decisions/2026-09-15-evaluate-architecture-linters.md`
from the same session's tooling-evaluation request.
`docs/decisions/2026-09-15-adopt-ruff-linter.md` is the precedent this
decision's staged-rollout and baseline-debt handling both mirror.
