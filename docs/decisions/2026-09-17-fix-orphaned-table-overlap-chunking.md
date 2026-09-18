# Fix orphaned-table-fragment chunking bug found in the 44/47 baseline

**Date:** 2026-09-17

## Context

The 44/47 full eval baseline (`eval/eval_results/20260917T213518Z.json`)
had one remaining numeric-type failure, `nvda-inventory-turnover-fy2026`,
untriaged. Live reproduction found a genuine, previously-unknown bug in
`chunk_documents.py`'s `chunk_blocks()`: its 200-char raw-character
overlap carry-over can land mid-table, producing a chunk with an
orphaned `</TABLE>` (no matching `<TABLE>`) that
`table_grounding.py`'s paired-tag regex can't see — hiding a real table
row and, in the reproduced case, causing `locate_value()` to false-match
a different, coincidentally close cell instead. This can recur for any
table whose markdown crosses within 200 chars of a chunk boundary,
across the whole indexed corpus, not just the one NVIDIA table that
surfaced it. Two other baseline failures (`pltr-dividend-2019-refusal`,
`nvda-rd-expense-q4fy26-refusal`) were investigated in parallel and
assessed as judge over-strictness rather than an agent gap — see the
paired plan file; no code change was made for those two.

## Decision

Made `chunk_blocks()`'s overlap carry-over table-boundary-aware: if the
raw-sliced tail contains an orphaned `</TABLE>`, keep only what follows
it (`tail.find("</TABLE>")`, the first occurrence — not the last)
instead of carrying the corrupt fragment forward or dropping the whole
tail. Re-chunked and re-indexed the full corpus with the fix.

## Why

A first draft used `tail.rfind(...)` (last occurrence); code review
found this over-strips a fully valid second table when one happens to
fall in the same tail after the true orphan. There is provably at most
one orphaned close tag per tail, and it is always the *first*
`</TABLE>` substring in it (tables never nest, so anything fully
contained in the tail must open only after the orphan's table already
closed) — `find` therefore strips exactly the orphan and nothing else.
This was not a corruption risk in the `rfind` version (the dropped
table's content was already safe in the just-flushed chunk), but it
undermined the whole point of preserving overlap context, which is why
the fix keeps the more-precise version rather than the simpler one.

## Files touched

- `chunk_documents.py` — `chunk_blocks()` + its docstring.
- `tests/test_chunk_documents.py` — three new tests (single-table drop,
  trailing-prose preservation, adjacent-complete-table preservation).
- `.claude/rules/live-eval-verification.md`,
  `.claude/rules/plan-review-blast-radius.md` — added
  `chunk_documents.py`/`chunk_blocks()`.
- `chunks/**/*.jsonl`, `chroma_db/` — regenerated corpus (not
  hand-edited).
- `BACKLOG.md`, `PROJECT_INDEX.md` — updated per the documentation
  system.

## Verification

Full detail in `docs/reviews/2026-09-17-fix-orphaned-table-overlap-chunking.md`.
Summary: full test suite 684 passing; `ruff`/`pyright` zero violations;
corpus-wide scan confirms 0 chunks with unbalanced `<TABLE>` tags across
all 3,182 chunks (was previously at least one, confirmed by direct
inspection of the NVIDIA chunk that originally surfaced the bug).

**Full-baseline Gemini confirmation, obtained 2026-09-18 once the free
tier's daily quota reset**
(`eval/eval_results/20260918T194825Z.json`, 41/47): all three targeted
questions now pass (`nvda-inventory-turnover-fy2026`,
`pltr-dividend-2019-refusal`, `nvda-rd-expense-q4fy26-refusal`). 6
questions failed that were passing in the pre-fix 44/47 baseline;
checked each against its full historical pass/fail record across every
prior Gemini run rather than assumed — all 6 are already
well-established flaky questions with prior failures predating this
fix entirely (pass rates from 30% to 86% across 17-50 historical runs
each), and none show the bug's actual signature (a numerically-correct
table value rejected via a wrong-cell "quoted text doesn't appear in
source" mismatch) — their failures are unrelated causes (hallucinated
citation indices, uncovered inline numbers, retrieval misses with
clean citations). Concluded this is the project's already-documented
citation-gate/model non-determinism recurring, not a regression from
this fix.

## Related

Plan: `docs/plans/2026-09-17-fix-orphaned-table-overlap-chunking.md`.
Review: `docs/reviews/2026-09-17-fix-orphaned-table-overlap-chunking.md`.
Surfaced while triaging the same-day
`docs/decisions/2026-09-17-fix-judge-hypothetical-date-bug.md` baseline
result. Distinct from the pre-existing `BACKLOG.md` item on
`current_is_only_overlap`'s empty-block-merge edge case (a different,
currently-unreachable defect in the same function).
