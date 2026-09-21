# Review: ruff-complexity-refactor

Plan: `docs/plans/2026-09-21-ruff-complexity-refactor.md`. Pure-relocation
refactor of 7 functions plus an E501 config/noqa resolution across
`agent.py`, `formulas.py`, `analyze_citation_gate.py`,
`tests/test_agent.py`, `tests/manual/verify_period_labels.py`,
`pyproject.toml`. Full suite before this diff: 707 passing.

## Pass 1 — plan review (independent subagent, before implementation)

Reviewed the `_run_agent_impl` decomposition design specifically —
this project's own tool-calling loop, named live-only code and
high-blast-radius core.

- `[Fixed]` **Blocking**: the first draft's uniform 3-way
  `(turn, result)` contract for all 5 extracted blocks treated
  `(None, None)` as "break." Traced against the real code: for the
  submit and no-tool-calls blocks, "guard false" means *fall through
  to the next check in the same iteration*, not break — only the
  budget-exhausted block genuinely has a break. A parent calling the
  first two unconditionally and treating `(None, None)` as break would
  terminate conversations prematurely on ordinary turns. Redesigned:
  all 4 guards stay inline in the parent; only guard-bodies (already
  known true) are extracted, each with a strict 2-way contract.
- `[Fixed]` A follow-up round on the corrected design found the
  supporting arithmetic wrong in two places (the plan claimed 4
  `calls_made += 1` sites, there are actually 5; claimed every flag has
  exactly one writer, but `retried_for_citations` has two by design) —
  both corrected in the plan's own prose, no design change needed.

## Pass 2 — code review (8 parallel finder angles, fresh, after implementation)

Run after all 11 ruff findings were resolved, `ruff check .`/`pyright`
clean, full suite green, and the first live baseline (39/47) obtained.

- `[Verified, no fix needed]` Removed-behavior audit (angle B) and a
  full line-by-line diff scan (angle A): traced every deletion against
  its replacement and every extracted function against
  `git show HEAD`'s original bodies — byte-for-byte identical logic
  everywhere, confirmed by the still-707-passing suite.
- `[Verified, no fix needed]` Cross-file tracer (angle C): every
  external call site of a changed function (`mcp_server.py`, various
  `tests/manual/verify_*.py`) still matches the unchanged public
  signatures and return contracts. One real finding folded into
  Pass 2's fixes below (the `pyproject.toml` comment-scope issue).
- `[Fixed]` `_AgentContext` was a plain mutable `@dataclass` despite
  its own docstring asserting no field is ever reassigned — this
  file's own established convention for exactly that shape
  (`CitationWarning`/`AgentResult` `NamedTuple`s,
  `table_grounding.py`'s frozen dataclasses) is immutability. Changed
  to `@dataclass(frozen=True)`.
- `[Deferred — logged to BACKLOG.md, not acted on]` A reuse-angle
  finding suggested replacing `_dispatch_tool_call`'s if-chain with a
  dict-based dispatch table (mirroring `mcp_server.py`/
  `llm_backends.py`'s own convention). This restates `BACKLOG.md`'s
  already-considered-and-rejected "not worth a registry at 4 tools"
  item — stood by per this project's "revisiting prior decisions"
  convention, since no new evidence was presented beyond re-noticing
  the pattern exists elsewhere.
- `[Verified, no fix needed]` An altitude-angle finding called
  `formulas.py`'s `_Period` NamedTuple "immediately unwrapped, no real
  benefit." Judged acceptable as-is: contained to one private call
  site, doesn't ripple across the codebase the way extending it to
  `get_metric()` would (explicitly out of scope per the plan), and
  matches this project's own convention of bundling related fields
  even where a consumer destructures them again.
- `[Fixed]` Simplification/altitude angles both flagged
  `_get_financial_fact_multi_year_average`'s parent-side guard as
  unrelated scope creep: the diff had rewritten two locals
  (`start_fiscal_year`/`end_fiscal_year`) into repeated inline
  `args.get(...)` calls, which no ruff finding required. Reverted to
  the original locals; the helper itself still takes `args` (genuinely
  needed to stay under `PLR0913` once the yoy_growth-conflict check
  and logging are accounted for — traced by hand that any real-values
  alternative needs 6 params, one over threshold).
- `[Fixed]` Three of `_dispatch_tool_call`'s four extracted helpers
  took a whole `call: dict` and re-derived `name`/`args`, though only
  `_dispatch_search_filings` (which alone also needs
  `searched_tickers`) genuinely needed that trick to fit under
  `PLR0913`. The other three now take `name`/`args` directly — fewer
  redundant dict lookups, and the signatures document their real
  inputs instead of an opaque `dict`.
- `[Fixed]` **The most consequential finding**: `_handle_submit_turn`/
  `_handle_no_tool_calls_turn` returned a positional
  `tuple[Any, AgentResult | None]` with an "exactly one non-`None`"
  convention enforced only by a docstring comment. Code review
  constructed the concrete failure mode: a future call site
  transposing the unpack order wouldn't even crash (`turn` is never
  `None` on the continue path), it would silently return a
  conversation-turn object as if it were the final `AgentResult`.
  Replaced with a named-field `_LoopStep` frozen dataclass
  (`next_turn`/`result`), removing the transposition risk at both
  current call sites structurally, not just by convention.
- `[Fixed]` `pyproject.toml`'s new `E501` per-file-ignore comment
  implied a narrower scope (single-line fixture dicts) than its actual
  reach (the `tests/*` glob also covers `tests/manual/`'s
  live-verification scripts, confirmed via an isolated-config probe).
  Comment corrected to state the full scope explicitly.
- `[Fixed]` The original inline comment explaining why
  `pre_retry_submit_args` caches raw args instead of pre-computed
  warnings (staleness avoidance if `all_results` grows before the
  retry budget runs out) was dropped during relocation into
  `_AgentLoopState`. Restored into that dataclass's own docstring.
- `[Verified, no fix needed]` Conventions angle: comment
  self-containment, error-handling/logging preservation, and the
  live-code-TDD carve-out's literal applicability (judged a reasonable
  spirit-preserving substitution — a live spot-check + one full
  baseline, not a new `tests/manual/verify_*.py` script, since this is
  claimed zero-logic-change relocation, not new behavior) all checked
  clean.

## Live verification

- Initial full 47-question baseline (`eval/eval_results/20260921T222521Z.json`):
  39/47. All 8 failures checked individually against
  `analyze_flakiness.py`'s historical pass-rate data — every one a
  well-established flaky question (24%-74% historical pass rate across
  17-61 prior runs), none a new failure signature. Diffed against the
  immediately-prior baseline (`20260919T003333Z.json`): only 2 new
  failures, both in that same historically-flaky set, and 1 question
  flipped to passing.
- Second, targeted live spot-check (`eval/eval_results/20260921T224555Z.json`,
  3 questions) run after the code-review round's fixes, specifically
  including `aapl-3yr-avg-operating-margin-fy2023-fy2025` (exercises
  the restructured multi-year-average path directly) — 3/3 passed.
  Deliberately not a second full baseline, per the standing "run the
  full 47-question baseline once, not repeatedly" instruction.

## Outcome

Shipped: all 11 ruff complexity findings resolved, all 146 `E501`
violations resolved (0 via mangling deliberately-long strings), `ruff
check .` and `pyright` both clean, full suite 707 passing throughout,
live baseline 39/47 (≥39/47 required, no regression). Review loop
closed after one round of code review (6 real findings fixed, 2
findings explicitly deferred with reasoning, re-verified via full
suite + a second targeted live spot-check) — did not need a second
round.
