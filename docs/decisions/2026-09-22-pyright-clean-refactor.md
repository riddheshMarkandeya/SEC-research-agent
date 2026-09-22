# Clean `pyright` basic mode repo-wide + a `/goal` task for it

**Date:** 2026-09-22

## Context

The user asked for a `/goal` task+verifier, mirroring the recent ruff
cleanup: refactor until `pyright` (basic mode) shows zero errors
repo-wide, verified by a clean pyright run, the full test suite
(exactly 707, no skips/deletions/additions), a live run of
`tests/manual/verify_mcp_server.py`, and an eval baseline ≥39/47 — run
once, only after pyright and pytest are already clean.
`docs/plans/2026-09-22-pyright-clean-refactor.md` has the full design;
this file is a short synthesis, not a re-telling.

## Decision

Closed the 117-error basic-mode pyright baseline across 9 test/verify
files via pure type-narrowing: ~112 bare `assert x is not None`
insertions (simple sequential access, paired-tuple complementary
assertions in `call_calculate` tests, attribute chains), 4
`typing.cast(...)` sites where a test passes a deliberately simplified
stand-in value, 1 comprehension-to-`for`-loop rewrite
(`verify_period_labels.py`, where a bare `assert` couldn't be inserted
inline), and 1 real fix rather than a suppression
(`verify_mcp_server.py`'s `httpx` → `httpx2` swap — see Why). Zero logic
change: no assertion, fixture value, mock behavior, or pass/fail
outcome changed anywhere. The 7 core modules
(`edgar_ingest.py`/`xbrl_facts.py`/`index_chunks.py`/`retrieval.py`/
`agent.py`/`llm_backends.py`) plus `tracing.py` were untouched and
re-verified individually clean at the end.

## Why

Full reasoning for each fix category is in the plan file. The one
noteworthy correction: the plan's first draft explained
`verify_mcp_server.py:204`'s pyright error as the MCP SDK vendoring a
duplicate `httpx` module under an internal alias, fixable with a scoped
`# pyright: ignore`. This project's mandatory independent plan review
(per `design-before-building`) checked the installed packages directly
and found this false — `httpx2` is a real, separate PyPI package
genuinely required by `mcp==2.1.1`, not a vendored copy. The plan was
corrected before implementation to the proper fix: swap the file's one
`httpx.AsyncClient` construction to `httpx2.AsyncClient` (confirmed
API-compatible via signature inspection), removing the error instead of
suppressing it and incidentally fixing a real, previously-undocumented
dependency-drift bug. See
`docs/reviews/2026-09-22-pyright-clean-refactor-plan-review.md`.

No shared `not_none()` test helper was introduced — considered and
rejected in the plan (reading all 117 flagged lines directly found only
one site that would have needed it, and that site got a loop-rewrite
instead, for reasons a helper call couldn't have preserved — see the
plan's "Design fork, resolved" section).

## Files touched

- `tests/test_formulas.py`, `tests/test_xbrl_facts.py` — bare
  `assert result is not None`/`assert entry is not None` insertions
  (36 and 29 errors respectively, all `reportOptionalSubscript`).
- `tests/test_agent.py` — paired-assertion insertions in the
  `call_calculate` test block; 2 `typing.cast(list[dict], ...)` sites.
- `tests/test_llm_backends.py` — SDK-model attribute-chain assertions;
  2 `typing.cast(Any, ...)` sites.
- `tests/test_mcp_server.py` — bare assertion plus
  `mcp_server.main.callback` attribute assertions.
- `tests/manual/verify_mcp_server.py` — `self._proc` assertion; the
  `httpx` → `httpx2` import and construction swap.
- `tests/manual/verify_tracing.py` — `obs2_input` assertion.
- `tests/manual/verify_period_labels.py` — comprehension → `for`-loop
  rewrite.
- `tests/test_edgar_ingest.py` — bare assertion.
- `PROJECT_INDEX.md`, `BACKLOG.md` — new `Recent` entries; resolved
  baseline item deleted, hard-pre-commit-gate item updated to note it's
  now unblocked.

## Verification

`pyright .`: 117 → 0 errors repo-wide (50 files analyzed). The 7 core
modules + `tracing.py` individually re-checked: still 0 errors each, no
regression. Full suite: 707 passing throughout (matching the
pre-refactor count exactly — no skips/deletions/additions, confirming
the zero-logic-change premise). Live: `tests/manual/verify_mcp_server.py`
run against a real local server — all checks passed, including the
authenticated round-trip that exercises the httpx2 swap
("request with correct token succeeds end-to-end (list_tools -> 3
tools)"), confirming the swap works, not just type-checks.

One full 47-question `eval_harness.py --backend gemini` baseline:
**38/47** — one below the plan's stated ≥39/47 target. Checked each of
the 9 failures individually against `analyze_flakiness.py`'s historical
data across 19 prior full-baseline runs before treating this as
anything other than a clean pass: every one of the 9 is a known,
pre-existing flaky question, several severely so —
`msft-segment-revenue-comparison-q3fy2026` (18% historical pass rate),
`pltr-dividend-2019-refusal` (26%), `nvda-rd-expense-q4fy26-refusal`
(29%), `crm-buyback-and-liquidity-q1fy27` (56%),
`msft-three-segments-revenue-q3fy2026` (67%),
`nvda-inventory-turnover-fy2026` (69%), `nvda-revenue-fy26-us-gaap`
(75%), `aapl-msft-employee-comparison` (89%),
`msft-rd-intensity-fy2025` (94%). Zero newly-failing questions. Combined
with `git status` confirming zero core-module files changed by this
refactor (only the 9 test/verify files above), this rules out a
regression: the observed score is ordinary live-model variance landing
on the unlucky side, not a consequence of this change. The user
reviewed this evidence and explicitly accepted 38/47 in place of a
second full-baseline run, per this project's quota-awareness guidance
(`.claude/rules/live-eval-verification.md`) against over-running full
baselines once the flakiness explanation is already evidenced rather
than merely asserted.

Independent review: one plan-review round before implementation (see
Why above) — this refactor's file list doesn't match
`.claude/rules/plan-review-blast-radius.md`'s frontmatter (source files
only), so the rule's escalated scrutiny didn't apply; the unconditional
plan-review floor still did. The mandatory post-implementation
five-pass review (`independent-review-pass`) found and fixed 2 real
issues on the finished diff — an undeclared `httpx2` import (now
pinned in `requirements-dev.txt` with an explanatory comment) and a
missing doc-convention disclaimer — plus surfaced a repo-wide gap
(`/security-review` cannot run here at all: no `origin` remote), filed
to `BACKLOG.md`. Full findings:
`docs/reviews/2026-09-22-pyright-clean-refactor.md`.

## Related

Plan: `docs/plans/2026-09-22-pyright-clean-refactor.md`. Plan review:
`docs/reviews/2026-09-22-pyright-clean-refactor-plan-review.md`. Diff
review: `docs/reviews/2026-09-22-pyright-clean-refactor.md`. Mirrors
`docs/decisions/2026-09-21-ruff-complexity-refactor.md`'s pattern
(clean the tool, then unblock a hard pre-commit gate via
`docs/decisions/2026-09-21-ruff-pre-commit-gate.md`'s precedent).
