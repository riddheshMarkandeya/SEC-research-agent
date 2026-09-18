# Review: orphaned-table-overlap chunking fix

Plan: `docs/plans/2026-09-17-fix-orphaned-table-overlap-chunking.md`.
Fix to `chunk_documents.py`'s `chunk_blocks()`; full suite before this
diff: 683 passing.

## Plan review (independent subagent, before implementation)

Reviewed the initial plan (the `rfind`-based, single-orphan design)
against the real code: confirmed the bug mechanism, hand-verified the
new test's character arithmetic (flush point, tail boundaries) against
`chunk_documents.py` as it exists, and confirmed `table_grounding.py`'s
`_TABLE_BLOCK` regex genuinely can't see an unpaired `</TABLE>`.

- `[Fixed]` Missing entry in `.claude/rules/plan-review-blast-radius.md`
  — this bug is exactly the pattern that list exists to track (corpus-
  wide code, root-caused via a real eval regression), but the plan only
  proposed updating `live-eval-verification.md`. Added `chunk_documents.py`
  to both rule files.
- `[Fixed]` Off-by-one in the bug's real-data citation (`chunks/NVDA/
  0001045810-26-000021_chunks.jsonl` line 145 → line 146, `chunk_index`
  145 — verified directly against the file).

A follow-up focused review, after the plan was revised (per a user
question) to preserve trailing prose after the orphaned tag instead of
dropping the whole tail: re-verified the refined `tail.rfind(...)`-based
snippet was a correct drop-in replacement, re-derived the "remainder is
tag-free" safety proof independently, and hand-traced both new tests'
arithmetic (including the `.strip()` interaction in `chunk_blocks`'s
merge step). Found no issues beyond one cosmetic index-range slip in
the plan's prose (not the code).

## Code review (independent, after implementation — `/code-review medium`)

Eight finder angles run in parallel over the finished diff.

- `[Verified, no fix needed]` Reuse: `split_into_blocks()` already has a
  paired-tag regex (`<TABLE>...</TABLE>`) that could theoretically
  serve as a shared primitive instead of the new `count`/`find` logic.
  Not adopted — the new logic operates on a fixed 200-char string, and
  introducing a regex-based shared helper for a single, already-tested
  call site was judged more machinery than the fix needs at Standard
  tier.
- `[Verified, no fix needed]` Efficiency: three linear scans of a
  200-char string, once per ~2000-char flush, during offline ingestion
  — negligible next to embedding/indexing cost.
- `[Fixed]` **Simplification**: `rfind(...) + len(...)` slice rewritten
  as `tail.split("</TABLE>", 1)[-1]` (after the `find`-vs-`rfind` fix
  below made this the first-occurrence split); `current_is_only_overlap`
  computed once as `bool(current)` after the branch instead of set
  separately in each arm (the clean-tail arm's `current = tail` is
  always non-empty, so the two arms' flag logic was already identical).
- `[Deferred — filed to BACKLOG.md]` **Altitude**: the fix is hardcoded
  to `<TABLE>`/`</TABLE>` specifically rather than generalizing to any
  future atomic marker type `split_into_blocks()` might grow. Confirmed
  no second marker type exists in the live pipeline today, so this is
  debt, not a live gap — filed rather than speculatively generalized.
- `[Fixed]` **Correctness (blocking)** — found independently by two
  finder angles: `tail.rfind("</TABLE>")` finds the *last* close tag,
  not the orphan. When a fully self-contained second table falls within
  the same tail after the true orphan, `rfind` lands on that second
  table's own valid close tag, discarding a completely legitimate table
  along with the orphan. Root-caused and fixed by switching to
  `tail.find("</TABLE>")` (first occurrence), backed by a proof that at
  most one orphaned close tag can ever exist in a tail, and it is
  always the first `</TABLE>` substring in it (tables never nest or
  overlap, so anything fully contained in the tail must open after the
  orphan's table has already closed). Not a corruption risk even in the
  buggy version — the discarded table's content was already safely
  preserved in the just-flushed chunk — but a real, avoidable loss of
  the "context continuity" the overlap exists for, and the docstring's
  claim of correctness didn't actually hold once more than one table
  close appeared in the tail. A third regression test
  (`test_chunk_blocks_overlap_preserves_complete_table_after_the_orphan`)
  proves the corrected behavior.
- `[Verified, no fix needed]` Cross-file trace: `retrieval.py`'s
  `_rescue_demoted_table_chunk` reads the same `contains_table`
  metadata this fix changes the shape of for some chunks. This is an
  expected, inherent side effect of correcting real chunk boundaries,
  not a new bug — any fix to chunk composition can shift which chunk a
  metadata-driven heuristic favors. No code change; flagged for the
  deferred full-baseline re-run to actually observe, per its own
  existing purpose.
- `[Fixed]` Conventions: this decision/plan/review file set itself, and
  the `PROJECT_INDEX.md`/`BACKLOG.md` entries — the diff at review time
  had none yet; added in this same change.

## Live verification

- Direct real-data check: after re-chunking `./data` with the corrected
  fix, `chunks/NVDA/0001045810-26-000021_chunks.jsonl`'s "Total
  inventories" row (chunk_index 145) now lives in a chunk with `<TABLE>`
  opens == closes == 2 (previously opens=2, closes=3 — the orphan).
- Corpus-wide scan: all 3,182 chunks across all 5 tickers' 25 filings
  have `<TABLE>` count == `</TABLE>` count (0 unbalanced chunks) after
  the corrected re-chunk/re-index.
- `pytest` (full suite): 684 passing (683 baseline + 1 net new test —
  3 added for this fix, no existing test needed to change).
- `ruff check chunk_documents.py tests/test_chunk_documents.py --fix` /
  `pyright` (both files): zero violations before and after.
- **Full 47-question Gemini baseline attempt #1: blocked.** Hit
  `RESOURCE_EXHAUSTED` (free-tier `GenerateRequestsPerDayPerProjectPerModel`
  daily cap) on effectively every question — quota was already
  exhausted by six earlier full baseline runs the same day, before this
  task began. Per `.claude/rules/live-eval-verification.md`'s own
  existing rule, that run (`eval/eval_results/20260918T013618Z.json`)
  is invalid for before/after comparison and is not treated as one. A
  targeted retry (`--ids nvda-inventory-turnover-fy2026`) also failed
  identically (`eval/eval_results/20260918T020413Z.json`, and again on
  a later same-day retry, `20260918T021005Z.json`), confirming a
  genuine daily cap, not a transient rate limit.
- **Ollama substitute spot-check (while blocked) — inconclusive.**
  `eval_harness.py --backend ollama --ids nvda-inventory-turnover-fy2026`
  (`eval/eval_results/20260918T014014Z.json`) still failed, but for a
  reason unrelated to this fix: `qwen2.5:7b-instruct` computed the
  correct ratio ($62.5B ÷ $21.4B) but mislabeled it "293.7%" instead of
  a ratio, and never included the value in its structured
  `submit_answer` claims at all — a citation-coverage gap, not a
  table-grounding failure. Notably, it *did* correctly retrieve $21.4B
  for inventory (matching the real $21,403M value, no sign of the old
  wrong-cell mismatch), consistent with the fix working — just not a
  clean pass/fail signal for this exact question via this backend.
- **Full 47-question Gemini baseline, obtained the next day once quota
  reset: 41/47** (`eval/eval_results/20260918T194825Z.json`). All three
  targeted questions now pass. 6 questions failed that were passing in
  the pre-fix 44/47 baseline — checked each against its full historical
  pass/fail record across every prior Gemini run (not just the
  immediately-preceding one) before concluding anything:

  | Question | Historical pass rate | Failed pre-fix too? |
  |---|---|---|
  | `msft-segment-revenue-comparison-q3fy2026` | 9/30 (30%) | Yes (`20260917T053451Z`, `20260917T205406Z`) |
  | `pltr-inventory-turnover-fy2025-refusal` | 13/27 (48%) | Yes (`20260917T205406Z`) |
  | `crm-buyback-and-liquidity-q1fy27` | 13/21 (62%) | Yes (`20260916T220304Z`) |
  | `msft-three-segments-revenue-q3fy2026` | 13/17 (76%) | Yes |
  | `aapl-msft-employee-comparison` | 40/50 (80%) | Yes, flips both ways repeatedly |
  | `pltr-government-contract-risk` | 38/44 (86%) | Yes, occasional prior failures |

  All 6 are already well-established flaky questions with failures
  predating this fix entirely, and none show the bug's actual signature
  (a numerically-correct table value rejected via a wrong-cell "quoted
  text doesn't appear in source" mismatch) — their failure reasons are
  unrelated (hallucinated citation indices, uncovered inline numbers,
  clean-citation retrieval misses). Concluded this is the project's
  already-documented citation-gate/model non-determinism recurring on
  already-flaky questions, not a regression from this fix. The
  `retrieval.py` rescue-heuristic metadata shift flagged during code
  review shows no evidence of harm in this run either — none of the 6
  failures are attributable to it once the historical-flakiness check
  ruled out a chunking-caused explanation.

## Outcome

Shipped: the `find`-based fix, three regression tests, both rule-file
updates, and this decision/plan/review triple. The full-baseline
Gemini confirmation (41/47, all 3 targeted questions passing, no
evidence of regression) was obtained the following day once quota
reset — see Live verification above. Still open, filed to
`BACKLOG.md`:

- The pre-existing `table_grounding.locate_value` 1%-relative-tolerance,
  which is what let the original bug silently false-match a
  wrong-but-close cell instead of failing cleanly (a contributing
  factor, not itself fixed by this change).
- The fix's hardcoding to `<TABLE>`/`</TABLE>` specifically (altitude
  finding above) — worth revisiting only if `split_into_blocks()` ever
  grows a second atomic marker type.

Review loop closed after one round of code review (one blocking finding
fixed, verified clean on re-review by re-running the full test/lint/
type-check suite) — did not need a second round.
