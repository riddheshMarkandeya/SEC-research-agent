# Close the coverage baseline gap, turn on branch coverage, and move all checks to a pre-push gate

**Date:** 2026-09-22

## Context

Three related `BACKLOG.md` items from `docs/decisions/2026-09-22-adopt-pytest-coverage.md`'s adoption: revisit branch coverage, close the measured pre-existing baseline gap, and migrate the coverage-diff check to a hard gate. The user explicitly greenlit the gate migration ("we are satisfied with the current coverage"), then, mid-implementation, redirected the gate itself: move ALL checks (ruff, pyright, pytest, coverage) from `pre-commit` to a new `pre-push` hook, so commits stay fast and checks apply once, right before code reaches the remote.

Two independent plan reviews shaped this before implementation started: the first caught an invented "critical core" file list and the missing live-only-exclusion requirement in the original coverage-gap-closure draft; the second, after the pre-push redirect, caught that the redirect actually reverses **four** prior decisions, not the two initially named, and found a missing `.git/hooks/` file swap that would have silently left the old gate firing.

## Decision

**1. Closed the baseline gap.** Deleted `query_chunks.py` (0% coverage, superseded by `retrieval.py`'s `hybrid_search()` — confirmed via its own docstring, a decision doc's `Related` section, and a pre-existing separate `BACKLOG.md` item, all agreeing) and updated its remaining comment references in `config.py`, `index_chunks.py`, `.env.example`, `requirements.txt`. Added `tests/test_index_chunks.py` (new, 5 tests for `load_all_chunks`/`make_id`), 3 new tests in `tests/test_chunk_documents.py` (real pure-logic gaps in `reconstruct_document`/`split_by_sentences`/`split_prose_block`), 4 new tests in `tests/test_eval_harness.py` (`_grade_by_type`'s comparison-dispatch branch, `print_summary`, a `main()` orchestration test), and 3 new async tests in `tests/test_mcp_server.py` (`_handle_list_tools`/`_handle_call_tool`, using plain `asyncio.run()` — no `pytest-asyncio` added, since no test anywhere in this repo already uses one and neither coroutine needs an event-loop fixture). One incidental type-annotation fix: `eval_harness._grade_by_type`'s `retrieved` parameter was typed `list[dict]` but already forwarded to two functions accepting `list[dict] | None` — widened to match its real contract, surfaced by the new comparison-dispatch test.

Deliberately **not** pragma-excluded: `chunk_documents.py`'s `process_filing`/`main` (real local file I/O — `json.loads`, `Path.read_text`/`write_text` — not live-only by this project's own `tdd-live-code-carveout` definition, which only covers SEC HTTP/Chroma/LLM calls; an earlier draft proposed excluding these "for consistency" and independent review found that didn't hold up against what every other pragma in this codebase actually means). `mcp_server.py`'s ASGI middleware/`build_app` construction stays genuinely uncovered too — not pragma-excluded (`mcp_server.py` carries zero `# pragma: no cover` markers, confirmed directly, and isn't in `.claude/rules/live-code-tdd.md`'s list either), left as open pre-existing debt in `BACKLOG.md` rather than mislabeled as an intentional exclusion.

Measured result: **94% overall** (up from 90%; 2,069 statements after `query_chunks.py`'s removal, 116 missed). `index_chunks.py`/`eval_harness.py` now 100%. `chunk_documents.py` 80% (up from 78%), `mcp_server.py` 85% (up from 80%) — both partially closed, remaining gaps openly tracked in `BACKLOG.md` for opportunistic closure.

**2. Turned on branch coverage** (`[tool.coverage.run]`'s `branch = true`), after measuring the real impact first: repo-wide, branch mode added only 30 partial branches out of 714 total, aggregate barely moved — no pyright-strict-style noise blowup. Kept the 80%/90% diff-coverage thresholds unchanged (the aggregate doesn't move enough to justify recalibrating). Deliberately did **not** enable `diff-cover`'s own separate `--branch-coverage` flag — that's a second, independent escalation (penalizing partial branches on the diff-scoped lines a check actually reports on, not just what's measured into `coverage.xml`), and no diff-scoped partial-branch data has been measured, only this repo-wide historical snapshot. Verified manually: ran `diff-cover` against a real 5-commit historical diff under branch mode and confirmed sane, non-error output (95% diff coverage, 8 missing lines out of 191) before anything depended on it.

**3. Moved ALL checks from `pre-commit` to a new `pre-push` hook.** Deleted `githooks/pre-commit` and its installed copy `.git/hooks/pre-commit`. New `githooks/pre-push` (installed to `.git/hooks/pre-push`, executable bit set) reuses the existing `find_bin`/`run_check` helpers unchanged, running: `ruff check .`, `pyright .`, `pytest --cov=. --cov-report=xml -q` (replacing the old bare `pytest -q` — the suite doesn't run twice), then two `diff-cover` invocations (80% repo-wide, 90% `--include`-scoped to the 8 critical-core files). `scripts/check_docs_sync.py`'s separate `PreToolUse` hook (the doc/index staging-mismatch check) is unrelated, unaffected.

## Why

**This explicitly revisits four prior decisions**, not silently overrides them, per this project's own "revisiting prior decisions" convention:

1. `docs/decisions/2026-08-14-tdd-adoption-pre-commit-hook.md` — the original pytest-at-commit-time gate, predating ruff/pyright entirely.
2. `docs/decisions/2026-09-21-ruff-pre-commit-gate.md` — ruff hard-gated at commit time.
3. `docs/decisions/2026-09-22-pyright-pre-commit-gate.md` — pyright hard-gated at commit time.
4. `docs/decisions/2026-09-22-adopt-pytest-coverage.md`'s own explicit deferral — that same-day decision named a concrete trigger for hard-gating diff-cover at all (baseline near target AND >=10 real diffs passing cleanly first). Moving it into a hard gate hours later, with the second condition unmet, reverses that decision on zero new evidence about diff-cover's own reliability — the new evidence is entirely about commit-speed friction, not about diff-cover having proven itself.

What actually changed, for all four at once: real, felt commit-speed friction once a third (~13s) and then a fourth (~19-30s) check stacked onto every commit — evidence about *when* checks should run, not evidence that any individual tool needed less scrutiny.

**Real tradeoffs, stated explicitly rather than left implicit:**
- Bad commits (lint/type errors, failing tests, an undertested diff) can now accumulate locally across several commits before anything blocks — the gate only fires at push time, potentially across a large, hard-to-bisect batch. This is the direct, intended consequence of "commit fast, check at push," not an oversight.
- The fast-feedback discipline the original three gates were built for isn't automatically preserved by moving the enforcement mechanism — developers should keep running `ruff check .`/`pyright .`/`pytest` manually before committing, even though nothing enforces it anymore.
- `git push --no-verify` bypasses the new gate the same way `git commit --no-verify` bypassed the old ones — same escape-hatch discipline carries over: fix the issue, or bypass-and-file-a-`BACKLOG.md`-item for a genuine tooling false positive, never as a routine habit.

## Files touched

`query_chunks.py` (deleted), `config.py`, `index_chunks.py`, `.env.example`, `requirements.txt` (comment cleanup for the deletion), `tests/test_index_chunks.py` (new), `tests/test_chunk_documents.py`, `tests/test_eval_harness.py`, `tests/test_mcp_server.py` (new tests), `eval_harness.py` (one type-annotation fix), `pyproject.toml` (`branch = true`, rollout-stage comments for all three tools), `githooks/pre-commit` (deleted), `githooks/pre-push` (new), `.git/hooks/pre-commit` (deleted), `.git/hooks/pre-push` (new, executable), `CLAUDE.md` (three tool sections rewritten for pre-push + branch coverage), `requirements-dev.txt` (comment rename), `BACKLOG.md` (resolved items removed/rewritten), `PROJECT_INDEX.md` (new entry).

## Verification

Full suite: 722 passing (up from 707) throughout Step 1; `ruff check .`/`pyright .` clean after every fix, including the one `_grade_by_type` type-annotation correction. Coverage measured directly, not estimated, at each step (90% → 94% after gap closure; branch mode confirmed ~94% still, no regression). `diff-cover` spot-checked against a real historical diff under branch mode before the gate depended on it. The new pre-push hook verified via a scratch commit/push cycle: appended a deliberately under-tested function to `analyze_citation_gate.py`, confirmed `git commit` now succeeds immediately (no pre-commit checks left), then `git push` was blocked by the pre-push hook specifically at the diff-cover step (ruff/pyright/pytest all passed first) — confirmed via `git log` that nothing reached `origin` before the block — then reverted via `git reset --hard` to a SHA captured before the scratch commit, confirmed via `git status` first that no other work would be affected.

## Related

Amends `docs/decisions/2026-09-22-adopt-pytest-coverage.md` (branch-coverage choice, gate-timing decision) and revisits `docs/decisions/2026-08-14-tdd-adoption-pre-commit-hook.md`, `docs/decisions/2026-09-21-ruff-pre-commit-gate.md`, `docs/decisions/2026-09-22-pyright-pre-commit-gate.md` (all three hard-gate-at-commit decisions, now hard-gate-at-push instead).
