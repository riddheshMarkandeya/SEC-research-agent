# Clean `pyright` basic mode + a `/goal` task for it

> Saved as a ready-to-execute plan, not yet implemented. Written for an
> autonomous `/goal` run to pick up later — see the task/verifier text
> at the bottom.

## Context

This mirrors the recent ruff cleanup
(`docs/plans/2026-09-21-ruff-complexity-refactor.md`,
`docs/decisions/2026-09-21-ruff-pre-commit-gate.md`): get a linter/type-
checker fully clean repo-wide, then use that to unblock a hard
pre-commit gate. `BACKLOG.md`'s "From the 2026-09-15 pyright adoption"
section carries the 117-error baseline as a standing, deliberately-
deferred item ("fix opportunistically") plus a note that migrating
pyright to a hard gate is blocked on that baseline clearing. This plan
clears it.

Current, freshly re-verified state (2026-09-22, `pyright --outputjson .`):
**50 files analyzed, 117 errors, 0 warnings**, all 117 confined to 9
files under `tests/`. The 7 core modules (`edgar_ingest.py`,
`xbrl_facts.py`, `index_chunks.py`, `retrieval.py`, `agent.py`,
`llm_backends.py`) plus `tracing.py` are already 0-error and must stay
that way — nothing in this plan touches them.

| File | Errors | Dominant rule |
|---|---|---|
| tests/test_formulas.py | 36 | reportOptionalSubscript (100%) |
| tests/test_xbrl_facts.py | 29 | reportOptionalSubscript (100%) |
| tests/test_agent.py | 26 | OptionalMemberAccess x10, OperatorIssue x10, ArgumentType x5, OptionalSubscript x1 |
| tests/test_llm_backends.py | 10 | OptionalMemberAccess x6, ArgumentType x3, OptionalSubscript x1 |
| tests/test_mcp_server.py | 5 | ArgumentType x2, OptionalMemberAccess x1, OptionalCall x2 |
| tests/manual/verify_mcp_server.py | 4 | — |
| tests/manual/verify_tracing.py | 3 | — |
| tests/manual/verify_period_labels.py | 2 | — |
| tests/test_edgar_ingest.py | 2 | — |

Root cause, confirmed by reading every one of the 117 flagged lines (not
sampled): test fixtures/mocks call something typed `X | None` (a
helper's return, an SDK model's Optional field, a dict `.get(...)`) and
then subscript/attribute-access/call/operate on the result on a later
line without narrowing.

## Decision / Design

**Pure type-narrowing, zero logic/behavior change**, in four categories.
No shared `not_none()` test helper — considered and rejected (see
below).

1. **~112 sites — bare `assert x is not None`**, inserted immediately
   after the Optional-returning call/expression, relying on pyright's
   flow-sensitive narrowing for the rest of the enclosing scope. Verified
   this holds in every sampled function (flat arrange-act-assert bodies,
   no intervening branches/loops/reassignment). Concrete shapes:
   - Simple sequential access: `result = get_gross_margin(...)`; add
     `assert result is not None`; before `result["value"]`.
   - Paired-tuple complementary assertion (`test_agent.py`'s
     `call_calculate` tests, ~24 sites / ~13 functions):
     `result, error = call_calculate(...)`; `assert result is None`;
     **add** `assert error is not None`; before `error.lower()`/
     `"x" in error`. Verified against `agent.py`'s actual
     `call_calculate` (lines 1064-1121): every return path is either
     `(None, <error str>)` or `({...}, None)` — exactly one populated,
     no exception.
   - Discarded-partner variant (`test_agent.py:1347`,
     `calc_result, _ = call_calculate(...)`): assert directly on
     `calc_result`.
   - Attribute chains (`test_llm_backends.py`'s SDK model objects like
     `tool.parameters.properties["claims"].items...`) and
     instance/module attributes set elsewhere (`verify_mcp_server.py`'s
     `self._proc`, set in `__init__`/`__enter__`, read in `__exit__`;
     `test_mcp_server.py`'s `mcp_server.main.callback`, a click
     attribute) — pyright narrows stable expression chains the same way
     it narrows simple names; one assert per chain suffices.
2. **4 sites — `typing.cast(...)`** (`test_agent.py:3140,3244`,
   `test_llm_backends.py:598,620`): a test passes a deliberately
   simplified stand-in (`["result"]`: `list[str]` where `list[dict]` is
   expected; `tools=["fake-tools"]` where `ToolListUnion | None` is
   expected) that the code under test never introspects — a type-shape
   correction, not an Optional-narrowing issue.
3. **1 site — `verify_mcp_server.py:204`, a real fix, not a
   suppression** (corrected after independent review — see below): swap
   `import httpx` → `import httpx2` and its one construction site,
   `httpx.AsyncClient(headers=...)` → `httpx2.AsyncClient(headers=...)`.
   `mcp==2.1.1`'s `streamable_http_client()` declares
   `http_client: httpx2.AsyncClient | None` — `httpx2` is a real,
   separate, actively-maintained PyPI package (by httpx's original
   author, a genuine `Requires-Dist` of `mcp`), not a vendored
   duplicate. Confirmed `httpx2.AsyncClient` is a drop-in for this
   file's only usage: its `__init__` accepts `headers=`, and it
   implements `__aenter__`/`__aexit__`. This is the file's only `httpx`
   reference, so no other line changes.
4. **1 site — `verify_period_labels.py:203`, comprehension → `for`-loop
   rewrite**: `_duration_days(e)` returns `int | None` and is used
   inline in a comprehension filter clause, where a bare `assert` can't
   be inserted. Rewrite as an explicit loop with
   `assert duration is not None, f"..."` inside the body — **not** a
   walrus (`if (d := _duration_days(e)) is not None and ...`), which
   would silently exclude a malformed entry instead of crashing; this
   script's whole purpose is catching exactly that kind of data-shape
   surprise loudly.

### Design fork, resolved: bare `assert` vs. a shared `not_none()` helper

Considered a shared `def not_none(value: T | None) -> T: assert value is
not None; return value` helper for chained/inline-expression sites a
bare statement can't reach. Reading all 117 flagged lines directly found
exactly **one** such site (the comprehension above), and even that one
needs a loop-rewrite, not a helper call (a `not_none()`-wrapped filter
expression would change "crash" to "silently exclude," a real behavior
change). A helper introduced for zero remaining call sites would also
need an awkward home — `tests/conftest.py` is pytest-fixtures-only, and
`tests/manual/verify_period_labels.py` runs standalone via
`python tests/manual/verify_period_labels.py`, not through pytest.
Rejected on this project's own minimalism grounds (same shape of
argument the ruff refactor's decision doc already made for
`_fake_result`'s `PLR0913` finding).

### Independent plan review — one real correction incorporated

A fresh subagent reviewed this plan against the actual code (not the
summary) before it was finalized — see
`docs/reviews/2026-09-22-pyright-clean-refactor-plan-review.md` for the
full review. It confirmed the error counts, rule breakdowns,
`call_calculate`'s exactly-one-populated contract, and the
walrus-rejection reasoning all hold exactly as claimed. It also found
the original draft's explanation for `verify_mcp_server.py:204` was
factually wrong (a claimed httpx-vendoring artifact that's actually a
real, separate `httpx2` dependency) — corrected to the proper fix (item
3 above) instead of a scoped ignore repeating the wrong explanation.

Blast-radius check: `.claude/rules/plan-review-blast-radius.md`'s
frontmatter names source files only (`agent.py`, `llm_backends.py`,
`xbrl_facts.py`, `formulas.py`, `retrieval.py`, `numeric_utils.py`,
`eval_harness.py`, `chunk_documents.py`) — none of this plan's 9 touched
test/verify paths match, so the rule's *escalated* scrutiny doesn't
apply (the unconditional review floor above still did).

## Scope / Out of scope

In scope: the 9 test/verify files listed above, pure type-narrowing
additions plus the 5 non-narrowing fixes (4 `cast`, 1 dependency-import
correction) and the 1 comprehension rewrite. Zero logic change: no
assertion, fixture value, mock behavior, or pass/fail outcome changes
anywhere.

Deliberately not touched: the 7 core modules + `tracing.py` (already
0-error, must stay that way — verified individually at the end, not
just via the repo-wide count). No shared `not_none()` helper introduced
(see Decision above). The pyright-to-hard-pre-commit-gate migration
itself (`BACKLOG.md`'s second pyright item) — this plan's completion
unblocks it but doesn't perform it. Pyright strict mode (`BACKLOG.md`'s
third pyright item) — untouched, no new evidence presented.

## Files and steps

1. `tests/test_formulas.py` — ~36 bare `assert result is not None`/
   `assert entry is not None` insertions.
2. `tests/test_xbrl_facts.py` — ~29 bare assert insertions.
3. `tests/test_agent.py` — ~24 `assert error is not None` insertions in
   the `call_calculate` block; 3 `assert calc_result is not None`
   insertions (lines 1288/1328/1348); 2 `typing.cast(list[dict], ...)`
   at lines 3140/3244.
4. `tests/test_llm_backends.py` — attribute-chain assert insertions
   (one with an intermediate local variable for the deepest chain); 2
   `typing.cast(Any, ...)` at lines 598/620.
5. `tests/test_mcp_server.py` — bare assert insertions; 2
   `assert mcp_server.main.callback is not None` insertions.
6. `tests/manual/verify_mcp_server.py` — 1
   `assert self._proc is not None` in `_RunningServer.__exit__`; the
   `httpx` → `httpx2` swap (import + line 204's construction).
7. `tests/manual/verify_tracing.py` — 1
   `assert obs2_input is not None` insertion.
8. `tests/manual/verify_period_labels.py` — comprehension-to-for-loop
   rewrite.
9. `tests/test_edgar_ingest.py` — 1 bare assert insertion.
10. Documentation, once verification below passes:
    `docs/decisions/2026-09-22-<slug>.md`, a `PROJECT_INDEX.md` entry
    for it, and `BACKLOG.md`: delete the resolved 117-error baseline
    item and update the "migrate to hard pre-commit gate" item to note
    it's now unblocked.

## Testing and verification

Run after each file, not just at the end — this is a zero-logic-change
refactor, so nothing should regress mid-way:

- `pyright .` — trending to 0; must reach exactly 0 by the end.
- `pytest` — full suite must stay at exactly 707 passing throughout (no
  skips/deletions/additions at any point).

At the end, in order:

1. `pyright .` exits 0, repo-wide.
2. `pyright edgar_ingest.py xbrl_facts.py index_chunks.py retrieval.py
   agent.py llm_backends.py tracing.py` still individually shows 0
   errors (explicit re-check that the untouched core stayed clean).
3. `pytest` (full suite) exits 0, exactly 707 passing.
4. `python tests/manual/verify_mcp_server.py` run once, live, against a
   real local server — confirms the httpx2 swap actually works
   end-to-end (this file is a live-only manual-verify script;
   type-checking clean isn't sufficient proof it still runs).
5. Exactly once, not before and not repeated while iterating:
   `python eval_harness.py --backend gemini` (full 47-question
   baseline) — must score **>=39/47**.

## The `/goal` task + verifier

Composed for pasting into `/goal` (1659 characters, under the
3500-character limit):

```
Task: Per docs/plans/2026-09-22-pyright-clean-refactor.md, close the 117-error
basic-mode pyright baseline (9 test files only; edgar_ingest.py, xbrl_facts.py,
index_chunks.py, retrieval.py, agent.py, llm_backends.py, tracing.py untouched)
via: bare `assert x is not None` at ~112 sites right after the Optional-
returning call/expression, relying on pyright's flow narrowing for the rest of
that scope; `typing.cast(...)` at 4 sites where a test passes a deliberately
simplified stand-in value (list[str] for list[dict]/ToolListUnion); swap
`httpx`->`httpx2` (import + the one AsyncClient(...) construction) in
verify_mcp_server.py, since mcp==2.1.1's streamable_http_client genuinely
expects httpx2.AsyncClient (a real separate PyPI package, not a vendored
duplicate -- confirmed via package metadata + signature inspection: headers=
kwarg and async context-manager protocol both present) rather than a
suppressed error; and a comprehension-to-for-loop rewrite in
verify_period_labels.py (bare assert can't sit inside a comprehension, and
must still crash loudly, not silently filter, on an unexpected None). No
test's assertions, fixtures, skips, or pass/fail outcomes change.
Verifier: `pyright .` exits 0 repo-wide, AND `pyright edgar_ingest.py
xbrl_facts.py index_chunks.py retrieval.py agent.py llm_backends.py
tracing.py` still shows 0 errors. `pytest` (full suite) exits 0 with exactly
707 tests passing (no skips, deletions, or additions). `python
tests/manual/verify_mcp_server.py` run once live, confirming the httpx2 swap
works end-to-end. Then, exactly once (not before, not repeatedly): `python
eval_harness.py --backend gemini` scores >=39/47.
```
