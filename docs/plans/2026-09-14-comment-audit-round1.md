# Comment Overhaul — Round 1 (small, low-risk batch)

## Context

The prior documentation-system overhaul logged a follow-up BACKLOG item
for a codebase comment audit, but that item undersold the real scope —
it only counted files that name-check `PROJECT_CONTEXT.md` by name. A
full inventory (two Explore passes, one over the main source tree, one
over `tests/`) found the problem is systemic: **19 main-source files**
and **25 test files** (`test_agent.py` alone has ~101 flagged comment
blocks; `test_table_grounding.py` is similarly dense) all carry
multi-line decision-history narration in comments/docstrings — incident
stories, rejected alternatives, "this used to do X" migration notes —
that duplicates content now properly homed in `docs/decisions/`.

The good news, confirmed during the inventory: almost every block
already maps by date/topic to one of the 56 `docs/decisions/*.md` files
created in the prior overhaul — the code just doesn't point to it yet
(and several still cite the now-deleted `PROJECT_CONTEXT.md` by name).
Only a small number of blocks are genuinely undocumented incidents.

Given the size of the full inventory, the user asked to work through a
smaller batch first to keep quality high, rather than attempt all ~44
files in one pass. **This plan covers only Round 1**: 6 small,
low-risk, mostly-already-documented main-source files. Everything else
(13 remaining main-source files, all of `tests/`) is logged as
follow-up `BACKLOG.md` items with the full inventory data attached, so
a future round doesn't need to re-derive it.

## Round-1 file selection

`companies.py`, `config.py`, `formulas.py`, `mcp_server.py`,
`period_labels.py`, `tracing.py` — chosen because the inventory found
these mostly `ALREADY-DOCUMENTED` (every flagged block maps cleanly to
an existing decision file), small (all under ~500 lines), and low risk
of needing a brand-new investigative write-up. This deliberately
excludes, for a later round: `agent.py` (2497 lines, ~45 blocks — needs
its own dedicated pass), `xbrl_facts.py` (needs a genuinely new
`EXTRACT` write-up for its tag-selection investigation), `numeric_utils.py`
(a single ~100-line regex-design block needing careful trimming),
`llm_backends.py`, `retrieval.py`, `index_chunks.py`, `eval_harness.py`,
`table_grounding.py`, `analyze_citation_gate.py`, `chunk_documents.py`,
`edgar_ingest.py`, `discover_tags.py`, `query_chunks.py`, and all of
`tests/`.

## Per-block process

Applied to every flagged block in the 6 files (this is a "code" change
per `~/.claude/CLAUDE.md` step 7's definition — a comment-only edit
inside a `.py` file still counts — so it gets the full two-pass review,
not just a self-check):

1. Read the block in its real surrounding context.
2. If it names, or clearly maps by date/topic to, an existing
   `docs/decisions/`/`docs/plans/`/`docs/reviews/` file: **confirm by
   reading that file** — don't trust the inventory's guess blindly, since
   several were flagged "verify mapping." Once confirmed, replace the
   block with a single terse pointer line (e.g.
   `# See docs/decisions/2026-08-17-centralized-env-config.md.`), per the
   comment-pointer policy already in `~/.claude/CLAUDE.md` step 3. If the
   existing text cites the now-deleted `PROJECT_CONTEXT.md`, repoint it
   to the real file instead of just deleting the reference.
3. If it's a dead action-item reference with no ongoing relevance
   (expected to be rare in this batch): delete outright.
4. If genuinely undocumented (not expected in this batch, but handle if
   found): per the user's approved policy, a substantial finding gets
   its own new dated `docs/decisions/*.md` file; a small, unrelated
   one-liner gets folded into one shared
   `docs/decisions/2026-09-14-comment-audit-round1-misc-findings.md`
   file rather than a tiny dedicated file of its own — then pointer-fix
   the comment either way.
5. Leave every `KEEP-AS-IS` block (terse, genuinely non-obvious WHY —
   not narration) untouched exactly as it is.
6. Never touch executable code — only comment and docstring lines.

## Known per-file dispositions (starting checklist — confirm each against the actual target file during implementation, don't rewrite from this list blindly)

- **`companies.py`**: module docstring + the schema-validation-KeyError
  block → `docs/decisions/2026-08-14-ticker-company-registry.md` and/or
  `docs/decisions/2026-09-09-schema-driven-arg-validation.md`. Pointer-fix both.
- **`config.py`**: module docstring ("used to be copy-pasted across
  files...") → `docs/decisions/2026-08-17-centralized-env-config.md`.
  The `DEFAULT_BACKEND` comment cites the dead `PROJECT_CONTEXT.md` plus
  `docs/plans/2026-09-10-...` → repoint to the real decision file.
- **`formulas.py`**: module docstring →
  `docs/decisions/2026-08-18-formulas-module-split.md`. The
  `_compute_ratio_metric`/`RATIO_DEFINITIONS` blocks →
  `docs/decisions/2026-08-25-formula-registry-roa-turnover-cash.md`. The
  `_compute_ratio_metric_all_companies` block →
  `docs/decisions/2026-08-28-ratio-definitions-table-driven-registry.md`.
  `get_multi_year_average`'s block → verify against
  `docs/decisions/2026-08-25-eval-growth-27-to-38-multi-statement-ranking.md`.
  The per-ratio-function docstrings ("built to answer aapl-...") are low
  priority — pointer-fix only if trivial, otherwise leave.
- **`mcp_server.py`**: module docstring →
  `docs/decisions/2026-08-25-mcp-server-week6.md`. The `_search_filings`
  hallucinated-ticker block → `docs/decisions/2026-09-09-schema-driven-arg-validation.md`.
  `_AuthRateLimitMiddleware`'s docstring →
  `docs/decisions/2026-09-01-mcp-server-auth-rate-limiting.md`. The
  shutdown-flush comment cites dead `PROJECT_CONTEXT.md` → repoint.
- **`period_labels.py`**: module docstring →
  `docs/decisions/2026-08-16-fiscal-period-labels-tried-and-reverted.md`.
  The rest of the file (`fiscal_year_label`, etc.) is `KEEP-AS-IS`.
- **`tracing.py`**: module docstring →
  `docs/decisions/2026-09-04-langfuse-tracing.md` and
  `docs/decisions/2026-09-05-local-jsonl-trace-log.md` (currently cites
  dead `PROJECT_CONTEXT.md` — repoint). The `_write_local_log` block →
  verify against `docs/decisions/2026-09-05-local-only-debug-events.md`.
  Remaining short blocks are `KEEP-AS-IS`.

## Verification

- **Diff scope check**: `git diff --stat` for the file list, then a full
  manual read of each of the 6 files' diffs (feasible at this size) to
  confirm only comment/docstring lines changed — zero logic/code lines
  touched.
- **Full pytest suite must stay green** (634 passed baseline). Comments
  shouldn't affect behavior, but this is the project's standing
  verification habit, and the pre-commit hook enforces it regardless.
- **Full two-pass review** (step 7, since `.py` files are touched): a
  self-check pass for correctness/compliance, plus a freshly-spawned
  subagent reviewing the diff for architecture/design/refactor quality —
  same pattern used throughout this project's `docs/reviews/`.
- Update `PROJECT_INDEX.md` with any new decision file(s) created (the
  misc-findings file, or a dedicated one for a real new finding).
- **Correct the existing BACKLOG.md item** (logged after the
  documentation-system overhaul, which undersold scope to only files
  that name-check `PROJECT_CONTEXT.md`): replace it with two properly-
  scoped follow-up items — (a) the remaining 13 main-source files, (b)
  the full `tests/` pass (25 files; flag `test_agent.py`'s ~101 blocks
  and `test_table_grounding.py` as the largest sub-tasks within it) —
  both citing this round's decision file for the full inventory data so
  a future round doesn't need to re-run the Explore passes.
- Write `docs/plans/2026-09-14-comment-audit-round1.md`,
  `docs/reviews/2026-09-14-comment-audit-round1.md` (two-pass review
  findings), and `docs/decisions/2026-09-14-comment-audit-round1.md`
  (plus `PROJECT_INDEX.md` lines for all three), same pattern as the
  documentation-system-overhaul task itself.

### Critical files
- `companies.py`, `config.py`, `formulas.py`, `mcp_server.py`,
  `period_labels.py`, `tracing.py` (the 6 files being edited)
- `BACKLOG.md` (correct the scope, add 2 properly-scoped follow-ups)
- `PROJECT_INDEX.md` (new index lines)
- `docs/decisions/2026-09-14-comment-audit-round1.md` (new),
  `docs/decisions/2026-09-14-comment-audit-round1-misc-findings.md` (new,
  only if a small stray finding actually turns up)
- `docs/plans/2026-09-14-comment-audit-round1.md`,
  `docs/reviews/2026-09-14-comment-audit-round1.md` (new)
