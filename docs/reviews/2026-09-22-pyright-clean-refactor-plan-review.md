# Review: Pyright-clean refactor plan

> This reviews a **plan**, not a finished diff — `design-before-building`'s
> pre-implementation review pass, not `independent-review-pass`'s
> post-implementation code review. Adapted from this template's usual
> Pass 1/Pass 2 diff-review shape accordingly, per the template's own
> "use judgment" note for reviews that don't fit the single-diff case.

Plan: `docs/plans/2026-09-22-pyright-clean-refactor.md`. Makes `pyright`
basic mode fully clean repo-wide (117 errors, confined to 9 test/verify
files) via type-narrowing assertions, targeted `typing.cast`, one
comprehension rewrite, and one real dependency-mismatch fix. **Not yet
implemented** — execution is intended via a `/goal` autonomous run using
the plan's own pasteable `Task:`/`Verifier:` block, run separately by the
user.

## Independent plan review (before implementation)

Per `design-before-building`'s unconditional review floor, a
freshly-spawned subagent reviewed the plan against the actual code — not
the plan's own summary — before it was finalized: ran
`pyright --outputjson .` itself, read every flagged line across all 9
files directly, verified `agent.py`'s real `call_calculate`
implementation, and checked installed package metadata for the one
dependency-identity claim the plan made.

**Confirmed accurate**: every per-file error count and per-rule breakdown
(matched a fresh `pyright --outputjson .` run digit-for-digit),
`call_calculate`'s exactly-one-of-two-populated return contract (verified
directly against `agent.py:1064-1121` — every return path is either
`(None, <error str>)` or `({...}, None)`, no exception), the
flow-narrowing claim that a single bare `assert` suffices per function
(checked in every sampled function — flat arrange-act-assert bodies, no
branch/loop/reassignment breaking the assert's scope), and the
comprehension-to-loop rewrite's walrus-operator rejection (a
silent-exclude vs. loud-crash tradeoff, confirmed against
`verify_period_labels.py`'s own stated purpose).

**One real correction, incorporated before approval.** The original
draft explained `tests/manual/verify_mcp_server.py:204`'s
`reportArgumentType` error as the MCP SDK vendoring a duplicate `httpx`
module under an internal alias (`httpx2`), fixable with a scoped
`# pyright: ignore` plus a comment repeating that explanation. The
reviewer checked the installed packages directly and found this false:
`httpx2` is a real, separate, actively-maintained top-level PyPI package
(by httpx's own original author), and a genuine declared dependency of
`mcp==2.1.1` — not a vendored copy. An ignore comment repeating the
original claim would have shipped a factually wrong explanation into the
codebase. The plan was corrected to the proper fix instead: swap the
file's one `httpx.AsyncClient` construction to `httpx2.AsyncClient`
(confirmed API-compatible for this usage — accepts `headers=`,
implements the async context-manager protocol — via direct inspection of
the installed `httpx2` package). This removes the error rather than
suppressing it, and incidentally fixes a real, previously-undocumented
dependency-drift bug in the manual verify script.

**Two minor, non-blocking notes, both accepted as-is**: two already-frozen
historical docs (`docs/plans/2026-09-10-...md`,
`docs/reviews/2026-09-16-...md`) cite exact line numbers in files this
refactor will shift — acceptable per this project's convention that
those files are frozen historical snapshots, never edited after the
fact. The plan's single illustrated `call_calculate` example undersold
the diversity of the ~112 bare-assert sites (paired-tuple,
discarded-partner, and attribute-chain variants also exist) — already
enumerated in the plan's own "Approach" section, not an actual gap in
the design.

## Outcome

Plan approved with the httpx2 correction incorporated. Not implemented in
this session — the user will run the plan's pasteable `Task:`/`Verifier:`
block through `/goal` separately to drive the actual code changes. This
review file exists per `design-before-building`'s rule that a plan review
is carried into the repo as its own file before implementation begins,
independent of whether that implementation happens in the same session or
a later autonomous run.
