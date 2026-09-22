# Adopt `pytest-cov`/`diff-cover` as this project's coverage tooling

**Date:** 2026-09-22

## Context

The user asked for coverage measurement plus an incremental, diff-scoped
enforcement policy: new/changed lines must clear 80% coverage going
forward (not a retroactive fix of existing code), with a 90% bar for
this project's already-named high-blast-radius core
(`.claude/rules/plan-review-blast-radius.md`'s 8-file list) — mirroring
this project's own twice-used adoption pattern for ruff and pyright.
No coverage tooling existed anywhere in this repo before this (no
`coverage`/`pytest-cov`/`diff_cover` installed, no `.coveragerc`/CI
config, zero mentions anywhere).

Two independent plan reviews found and fixed real problems in the
original design before implementation: an invented 10-file "critical
core" list that wasn't a real existing list (corrected to reuse
`plan-review-blast-radius.md`'s actual 8-file list); and the fact that
a coverage bar without live-only-line exclusions would be structurally
incompatible with this project's own `tdd-live-code-carveout` policy
(`retrieval.py`'s `bm25_search`/`vector_search`/`hybrid_search`,
`index_chunks.py`, and `edgar_ingest.py`'s `get_filing_list`/
`fetch_filing_html` are deliberately never unit-tested). Mid-implementation,
the user also stood up an `origin` GitHub remote for this repo
(previously nonexistent), which both resolved a standing `BACKLOG.md`
gap (`/security-review` couldn't run at all without one) and let
`diff-cover` use its own documented default mechanism
(`--compare-branch=origin/master`) instead of an untested local-ref
workaround.

## Decision

Installed `pytest-cov==7.1.0` and `diff-cover==10.6.0`
(`requirements-dev.txt`). Configured `[tool.coverage.run]`/
`[tool.coverage.report]` in `pyproject.toml`: line coverage (not
branch), sourced against the whole repo, excluding `.venv`, `tests/`
(confirmed the glob matches `tests/manual/` recursively too, mirroring
ruff's own `"tests/*"` per-file-ignore precedent), and the same
generated/data directories pyright already excludes.

Marked the actual live-only call sites `# pragma: no cover` in source,
identified by reading each of the 6 `live-code-tdd.md` files directly
against their real test files (not assumed): `xbrl_facts.py`'s
`fetch_frame` (its sibling `fetch_concept` is genuinely boundary-tested
via `monkeypatch.setattr(xbrl_facts.requests, "get", ...)` and needed
no exclusion — confirmed by reading `tests/test_xbrl_facts.py` directly
rather than assuming both functions were equivalent); `edgar_ingest.py`'s
`get_filing_list`, `fetch_filing_html`, and `main()`; `index_chunks.py`'s
`main()`; `retrieval.py`'s `_get_embed_model`, `_get_rerank_model`,
`_get_chroma_collection`, `_load_bm25_index`, `bm25_search`,
`vector_search`, `rerank`, `hybrid_search`, and `main()`. `agent.py` and
`llm_backends.py` needed zero exclusions — both are tested via genuine
boundary-mocking (`monkeypatch.setattr("llm_backends.requests.post",
fake_post)`, `BACKENDS` dict entries swapped for fakes) where the
functions' own lines actually execute against a fake target, not
whole-function replacement.

Measured the real, current full-repo baseline (not estimated):
**90% overall** (2,111 statements, 210 missed). Broken out by tier:
critical-core (the 8 blast-radius files) **93%** (1,434 statements, 98
missed) — already above the 90% target; ordinary files **83.5%** (677
statements, 112 missed) — already above the 80% target. Not
retroactively fixed regardless — see `BACKLOG.md`, mirroring the
155-violation ruff baseline and 117-error pyright baseline precedent.

Enforcement: `diff-cover coverage.xml --compare-branch=origin/master
--fail-under=80` repo-wide, plus a second invocation scoped via
`--include <8 critical-core paths> --fail-under=90` (confirmed
empirically: `--include`/`--exclude` take space-separated glob
arguments, not a comma-separated string — an easy mistake that silently
matched nothing on the first attempt).

**Rollout stage**: changed-files-scoped, `independent-review-pass`
prerequisite (alongside ruff/pyright) — not a pre-commit gate yet, per
explicit user direction after weighing the risk of hard-gating a
genuinely new, unvalidated tool from day one.

## Why

**Line vs. branch coverage**: mirrors pyright's own basic-vs-strict
"start simpler, measure the real baseline, escalate later if warranted"
reasoning. No coverage-blind-spot incident has been documented in this
project yet (coverage tooling didn't exist until now) — an earlier
draft's citation of `agent.py`'s `send_followup`-vs-`send_tool_results`
incident as the trigger case didn't actually hold up under review: that
bug was caught by independent plan review before implementation, never
run against a live API, so no coverage report (line or branch) was ever
involved. Revisiting branch coverage is a forward-looking consideration
in `BACKLOG.md`, not a reaction to a specific past miss.

**Reusing `plan-review-blast-radius.md`'s list, and extending that file
rather than creating a new one**: a second review round found the two
lists (an invented 10-file union vs. the real 8-file blast-radius list)
weren't just overlapping the way `live-code-tdd.md`/
`live-eval-verification.md`/`plan-review-blast-radius.md` genuinely are
(each with different total membership) — reusing the real list outright
was the correct fix, not a merge. That same review found a separate new
rule file for an identical 8-file list would create real drift risk
(`plan-review-blast-radius.md` is a living list that gets entries added
"the moment" a review surfaces one) for no real benefit, so the
coverage bar is a new, clearly-separate section in that same file
instead — see `.claude/rules/plan-review-blast-radius.md`'s own
`## Coverage bar` section.

**Live-only exclusion is required, not optional**: confirmed by direct
evidence, not assumption, that `retrieval.py`'s `bm25_search`/
`vector_search`/`hybrid_search` have zero unit tests (only
`tests/manual/verify_retrieval.py` exercises them, whose own module
docstring states mocking them "would only test the mock, not the
code"), `index_chunks.py` has no dedicated test file, and
`edgar_ingest.py`'s live functions are always replaced wholesale via
`monkeypatch.setattr`. Without excluding these lines, the coverage gate
would either chronically fail on any legitimate change to these
functions or pressure contributors toward exactly the anti-pattern
`tdd-live-code-carveout` rejects.

**Pre-commit-gate deferral, with a concrete trigger** (not left
open-ended, per a second review round's finding that "at or near the
targets" wasn't falsifiable): revisit once the exclusion-adjusted
full-repo baseline is within 5 percentage points of target — already
true today (93%/83.5% vs. 90%/80% targets) — AND at least 10 real diffs
have passed the review-time check with zero false-positive blocks
attributable to the live-only exclusions. The baseline condition is
already met; the second condition needs real usage first, which is the
actual reason this isn't a pre-commit gate today despite the numbers
already clearing the bar.

## Files touched

`requirements-dev.txt`, `pyproject.toml`, `CLAUDE.md`, `.gitignore`
(`.coverage`/`coverage.xml` generated artifacts), `.claude/rules/plan-review-blast-radius.md`,
`BACKLOG.md`, `PROJECT_INDEX.md`, and pragma comments in `xbrl_facts.py`,
`edgar_ingest.py`, `index_chunks.py`, `retrieval.py` (see Decision
above for the exact functions).

## Verification

`pytest --cov=. --cov-report=xml` run for real (707 passing, unchanged).
Confirmed the multi-line `hybrid_search(...)` signature's pragma
comment (on the first line, not the line with the closing `:`) still
excludes the whole function body — verified empirically via
`pytest --cov=retrieval --cov-report=term-missing`, which showed
`retrieval.py` at 100% after the exclusion. Confirmed `--include`/
`--exclude` need space-separated arguments by testing both the wrong
(comma-separated, silently matched nothing) and correct syntax side by
side. Confirmed `diff-cover` against an empty diff (`origin/master` ==
`HEAD`) reports "No lines with coverage information in this diff." and
exits 0, not an error. Confirmed diff-cover correctly detects a real
change: added a deliberately untested scratch function to `formulas.py`,
regenerated `coverage.xml`, and confirmed `diff-cover` reported exactly
25% coverage on the 4 new lines and exited 1 below the 80% threshold —
then reverted the scratch change. `ruff check .`/`pyright .`/full
`pytest -q` all clean after the real config/pragma changes.

## Related

`docs/decisions/2026-09-15-adopt-ruff-linter.md`,
`docs/decisions/2026-09-15-adopt-pyright.md` — the precedent this
decision's staged-rollout and baseline-debt handling both mirror.
