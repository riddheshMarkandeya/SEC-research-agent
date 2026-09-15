# Comment Overhaul — Round 2

## Context

Round 1 (2026-09-14, commit `f9978fe`) pointer-fixed 6 small, low-risk
main-source files. `BACKLOG.md` logged the remaining 13 main-source
files plus a full `tests/` pass as follow-ups, citing the original
inventory (`docs/decisions/2026-09-14-comment-audit-round1.md`) so this
round doesn't need to re-derive it.

Of the 13 remaining main-source files, three are qualitatively
different from the rest and don't belong in a "keep it small" round:
`agent.py` (2497 lines, ~45 blocks — the single largest file in the
codebase, needs its own dedicated pass), `xbrl_facts.py` (needs a
genuinely new `EXTRACT` write-up for its tag-selection investigation,
not just a pointer-fix — original content to write, not just verify),
and `numeric_utils.py` (a single ~100-line regex-design block that's
the single highest-value trim target in the codebase, per the original
inventory — deserves focused attention, not a spot in a 10-file batch).
**This plan covers only the other 10** — all confirmed
`ALREADY-DOCUMENTED` in the original inventory, no new investigative
writing expected. `agent.py`, `xbrl_facts.py`, and `numeric_utils.py`
get their own Round 3, logged as a new `BACKLOG.md` item at the end of
this round. `tests/` remains untouched, per its own existing item.

Same process as Round 1, already reviewed and working (confirmed via
Round 1's two-pass review, which found the mechanism sound and only
flagged two small execution issues, both fixed): confirm each block's
mapping to an existing `docs/decisions/*.md` file by reading it
directly, replace narration with a terse pointer, repoint anything
still citing the deleted `PROJECT_CONTEXT.md`, leave genuine terse WHY
comments untouched, and — per Round 1's review finding — check for
sibling comments in the same file that got a pointer, so a "found in
code review"-style tail doesn't get silently dropped in one place while
the block next to it gets pointer-fixed.

## Round-2 file selection

`llm_backends.py`, `retrieval.py`, `index_chunks.py`, `eval_harness.py`,
`table_grounding.py`, `analyze_citation_gate.py`, `chunk_documents.py`,
`edgar_ingest.py`, `discover_tags.py`, `query_chunks.py` — 10 files, but
individually small (`table_grounding.py`/`analyze_citation_gate.py` are
already described in the original inventory as "best-behaved... only
need the prose itself trimmed to shorter pointers, no new doc-writing
needed"; `discover_tags.py`/`query_chunks.py` are single-block,
module-docstring-only fixes).

## Real finding during execution: a missing decision file

`llm_backends.py`'s own creation (the whole "swappable LLM backend"
design) had NO decision file at all — only two plan docs
(`docs/plans/2026-08-20-swappable-llm-backend-design.md`,
`docs/plans/2026-08-20-swappable-llm-backend.md`), a gap the original
documentation-system migration missed. Wrote
`docs/decisions/2026-08-20-swappable-llm-backend.md` as a short
synthesis of both plans before pointer-fixing `llm_backends.py`'s module
docstring to it — this is the "genuinely undocumented content gets a new
decision file" branch of the per-block process, not scope creep.

## Per-block process (unchanged from Round 1)

1. Read the block in its real surrounding context.
2. Confirm the mapping by reading the target `docs/decisions/*.md` file
   directly.
3. Replace confirmed-mapped narration with a terse one-line pointer;
   repoint anything citing the deleted `PROJECT_CONTEXT.md`.
4. Delete pure WHAT-comments / dead action-item references.
5. Leave genuine terse WHY (`KEEP-AS-IS`) untouched.
6. If a block turns out genuinely undocumented: a substantial finding
   gets its own new dated `docs/decisions/*.md` file (see above); a
   small one-liner folds into a shared misc-findings file.
7. Once a file's confirmed pointers are in, re-scan for any sibling
   block with equivalent "found in review"-style narration mapping to
   the same or an adjacent decision file.
8. Never touch executable code — only comment and docstring lines.
9. **New this round**: also correct a module docstring that describes
   stale/inaccurate behavior, not just verbose history (same class of
   fix as Round 1's `period_labels.py` correction) — e.g.
   `eval_harness.py`'s docstring claimed "8 seed questions, scaffolding,
   not the full eval suite," long since untrue.

## Verification

- Full diff read of all 10 files confirming comment/docstring-only
  changes. A programmatic check (strip comments/docstrings from both
  HEAD and working-tree versions via Python's `tokenize` module, diff
  the remainder) confirmed byte-identical code across all 10 files.
- Full pytest suite: 634 passed, matching baseline.
- Full two-pass review (step 7, `.py` files touched): self-check plus a
  freshly-spawned subagent reviewing the diff for architecture/design/
  refactor quality, same as Round 1 — including verifying the new
  `docs/decisions/2026-08-20-swappable-llm-backend.md` file itself
  against the two plans it synthesizes.
- Updated `PROJECT_INDEX.md` with the new decision file plus this
  round's plan/review/decision entries.
- Updated `BACKLOG.md`: narrowed the "remaining main-source files" item
  down to the 3 files deferred to Round 3.

### Critical files
- `llm_backends.py`, `retrieval.py`, `index_chunks.py`, `eval_harness.py`,
  `table_grounding.py`, `analyze_citation_gate.py`, `chunk_documents.py`,
  `edgar_ingest.py`, `discover_tags.py`, `query_chunks.py` (the 10 files
  edited)
- `docs/decisions/2026-08-20-swappable-llm-backend.md` (new — fills a
  gap from the original documentation-system migration)
- `BACKLOG.md` (narrowed the follow-up to Round 3's 3 files)
- `PROJECT_INDEX.md` (new index lines)
- `docs/decisions/2026-09-14-comment-audit-round2.md`,
  `docs/plans/2026-09-14-comment-audit-round2.md`,
  `docs/reviews/2026-09-14-comment-audit-round2.md` (new)
