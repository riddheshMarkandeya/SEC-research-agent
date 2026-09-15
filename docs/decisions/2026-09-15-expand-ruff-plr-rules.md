# Expand ruff's PLR selection: add PLR0402, add scoped PLR2004

**Date:** 2026-09-15

## Context

The user asked whether the full Pylint-Refactor (`PLR`) rule family —
currently only `PLR0911`/`0912`/`0913`/`0915` are selected, per
`docs/decisions/2026-09-15-adopt-ruff-linter.md` — was worth adopting
wholesale, rather than guessing from rule names.

## Decision

Ran `ruff check --select PLR --statistics .` (full `PLR` family) to get
real numbers rather than assume. Of 106 total hits, only 3 rule codes
were net-new beyond what's already selected: `PLR2004`
magic-value-comparison (97), `PLR0917` too-many-positional-arguments (2),
`PLR0402` manual-from-import (1).

Adopted two of the three:

- **`PLR0402`** — added outright. The one hit (`mcp_server.py` importing
  `mcp.types as types` instead of `from mcp import types`) was
  auto-fixed; zero remaining findings, zero noise.
- **`PLR2004`** — added, scoped away from `tests/` via
  `[tool.ruff.lint.per-file-ignores]`. 93 of 97 hits were in `tests/`
  (assertions comparing to literal expected values — the normal,
  idiomatic pytest pattern, not a real finding). The remaining 5
  real-source hits were fixed, not deferred:
  - `xbrl_facts.py`:128,342 — `resp.status_code == 404` → `resp.status_code
    == http.HTTPStatus.NOT_FOUND` (stdlib named constant, no new
    constant needed).
  - `llm_backends.py`:305,307 — `attempt == 3` (Gemini retry-exhaustion
    check) → introduced `RETRY_ATTEMPTS = 4` and used it consistently
    in the loop bound, `max_attempts=`, and both comparisons — this
    Gemini retry loop had simply never gotten the same treatment as the
    Ollama retry loop three functions above it, which already has an
    `OLLAMA_RETRY_ATTEMPTS` constant for the identical pattern.
  - `numeric_utils.py`:75 — `len(digits) > 2` (footnote/reference-marker
    detection) → introduced `_MAX_REFERENCE_MARKER_DIGITS = 2` with a
    one-line comment, next to the function's other constant
    (`_BARE_YEAR_STRING`).

**Not adopted: `PLR0917`.** Its 2 hits are the exact same 2 functions
`PLR0913` already flags (`formulas.py:_compute_ratio_metric`,
`tests/test_agent.py:_fake_result`) — zero net-new signal in this
codebase, so not worth the extra selected rule.

## Why

Same reasoning as the original ruff-adoption decision, applied one
category deeper: don't select a rule family by name or reputation,
measure its actual hit rate and signal/noise ratio in *this* codebase
first. `PLR2004`'s 97-hit raw count looked alarming but was 96% the
same "big number, mostly deliberate/idiomatic" shape as `E501`'s 144
hits in the original baseline (test fixtures and HTTP-status-code
checks, not real magic-number smells) — scoping it away from `tests/`
rather than rejecting it outright, or accepting the noise, gets the
real signal (5 hits) without the false one (93 hits). Fixed those 5
immediately rather than logging them to `BACKLOG.md` as baseline debt
(unlike the original 155-violation baseline): the fixes were each a few
minutes and either used an existing stdlib constant or matched an
established local pattern already used three functions away — cheap
enough that deferring would just be process overhead for its own sake.

## Files touched

`pyproject.toml` (select list, new `per-file-ignores` section),
`xbrl_facts.py` (2 lines, `http.HTTPStatus.NOT_FOUND`), `llm_backends.py`
(new `RETRY_ATTEMPTS` constant, 4 call sites), `numeric_utils.py` (new
`_MAX_REFERENCE_MARKER_DIGITS` constant, 1 call site).

## Verification

`ruff check .` before/after: `PLR0402` and `PLR2004` both at 0 remaining
findings; total violation count back to the pre-existing 155 baseline
(unchanged categories: `E501`×144, `C901`×5, `PLR0911`×2, `PLR0912`×1,
`PLR0913`×2, `PLR0915`×1). Full test suite: 652 passed, unchanged by
the constant-extraction refactors (confirmed by re-running after each
file's edit, not just once at the end).

## Related

Amends the rule selection made in
`docs/decisions/2026-09-15-adopt-ruff-linter.md`. Review:
`docs/reviews/2026-09-15-expand-ruff-plr-rules.md` (clean, no findings).
A broader survey of *other* ruff rule categories (bugbear, bandit,
flake8-simplify, etc.), requested in the same conversation, is reported
separately rather than folded into this file — see `BACKLOG.md` for what
came out of that survey as of this writing.
