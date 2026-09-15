# Comment Overhaul — Round 3 (`xbrl_facts.py`, `numeric_utils.py`)

## Context

Round 1 (6 files) and Round 2 (10 files) pointer-fixed 16 of the 19
flagged main-source files from the original comment-audit inventory
(`docs/decisions/2026-09-14-comment-audit-round1.md`). The remaining 3
— `agent.py`, `xbrl_facts.py`, `numeric_utils.py` — were bundled as a
single "Round 3" backlog item needing "dedicated" attention rather than
a routine batch. Three fresh Explore-agent inventories (one per file)
confirmed why, and revealed the bundle was mis-sized: `xbrl_facts.py`
(607 lines) and `numeric_utils.py` (360 lines) together have ~15
flagged blocks, comparable to a normal round, but `agent.py` (2497
lines, the largest file in the codebase) turned out to have ~45+
narrated blocks on its own — denser than Round 2's entire 10-file batch
combined. The `agent.py` inventory agent itself hit a session usage
limit partway through and had to be finished by direct reading.

Confirmed with the user given this size mismatch: **Round 3 covers only
`xbrl_facts.py` and `numeric_utils.py`.** `agent.py` is deferred to its
own Round 4, logged in `BACKLOG.md` with the disposition notes gathered
during this round's inventory preserved below, so Round 4 doesn't need
to re-derive them.

## Decision / Design

Same process as Rounds 1-2: confirm each flagged block's mapping to an
existing `docs/decisions/*.md` file by reading it directly, replace
narration with a terse one-line pointer, repoint anything citing the
deleted `PROJECT_CONTEXT.md`, leave genuine terse WHY comments
untouched. One addition this round: `xbrl_facts.py` had one genuinely
undocumented investigation (an incremental XBRL metric-tag-selection
methodology, spanning 6 metrics) that needed a brand-new decision file
rather than a pointer to an existing one — same "EXTRACT" disposition
Round 1/2 established for genuinely new findings.

### `xbrl_facts.py`

Wrote `docs/decisions/2026-09-15-xbrl-tag-selection-methodology.md`,
synthesizing the removed 44-line comment block above
`DEFAULT_METRIC_TAGS`: the "HTTP 200 only means EVER tagged, not still
current" lesson (found via a live CRM comparison-question test after a
first pass that checked only status codes), the resulting
default-tag-plus-per-company-override design, and the same verification
methodology re-applied to 5 metrics added since (`GrossProfit`,
`OperatingIncomeLoss`, `Assets`, `CashAndCashEquivalentsAtCarryingValue`,
`InventoryNet` — the last one's PLTR/CRM 404s being a real business-model
fact, not a data gap). Replaced the removed block with a short
structural comment plus a pointer to the new file.

Everything else in the file was `ALREADY-DOCUMENTED` — 13 more blocks
(module docstring, `_duration_days`, `is_metric_tagged`, `_latest_entry`,
`_pick_entry_by_end_date`, `get_metric`'s empty-string handling, the
`fetch_frame`/`get_frame` module comments, the `sorted()`/same-tag-
duplicate/designated-tag comments, `get_metric_all_companies`) each
confirmed against its target `docs/decisions/*.md` file before being
pointer-fixed.

### `numeric_utils.py`

No EXTRACT — every historically-narrated block traced to an existing
decision file. The headline item was the ~130-line `NUMBER_PATTERN`
design comment (lines 14-143), confirmed ~85-90% pure historical
narration matching `docs/decisions/2026-08-17-citation-verification-pass.md`
and `docs/decisions/2026-09-11-negative-number-support.md` almost
verbatim. Collapsed to roughly 30 lines, keeping only what's genuinely
load-bearing for a future maintainer: the digit group is intentionally
uncapped, parenthesized negatives are a real accounting convention, the
bare-year/reference-number carve-outs exist and why, and — most
important — that a spaced-hyphen or Unicode-minus subtraction is **not**
handled by the regex at all and needs the Python-level
`_is_negative()`/`_preceded_by_number()` functions. `_looks_like_reference_number`'s
internal pointer ("see NUMBER_PATTERN's own comment") was repointed to
the decision file directly, since the internal target it referenced
would otherwise go stale. 5 more blocks (`_is_negative`,
`QUOTE_COVERAGE_THRESHOLD`, `normalize_for_match`, plus two smaller
ones) confirmed against their targets and pointer-fixed. `text_coverage`'s
docstring and `extract_numbers_with_spans`' docstring were judged
genuine algorithmic/API-contract explanation rather than incident
narration and left mostly `KEEP-AS-IS`, per this project's standing
rule that "why is this shaped this way" reasoning survives even when a
decision file also covers the same ground.

## Files and steps

1. Verify each candidate mapping by reading the target `docs/decisions/*.md` file.
2. Write `docs/decisions/2026-09-15-xbrl-tag-selection-methodology.md`.
3. Edit `xbrl_facts.py` and `numeric_utils.py` (comments/docstrings only).
4. Re-scan both files for stale `PROJECT_CONTEXT.md` references or
   dangling internal cross-references.
5. Verify (see below), then update `PROJECT_INDEX.md` and `BACKLOG.md`.
6. Write this plan, the paired review, and the round's own decision file.

## Testing and verification

- Full `git diff` read of both files, confirming every hunk touches only
  comment/docstring/blank-line content.
- A programmatic tokenize-based check (Python's `tokenize` module strips
  comments and docstrings from both the `HEAD` and working-tree versions
  of each file, then diffs the remainder) — reused the script built in
  Round 2, confirming byte-identical code in both files.
- Full pytest suite: 634 passed (matches the established baseline
  exactly).
- Full two-pass review (step 7, `.py` files touched): self-check plus a
  freshly-spawned subagent — see the paired review file.

## Related

`docs/decisions/2026-09-15-comment-audit-round3.md`,
`docs/reviews/2026-09-15-comment-audit-round3.md`,
`docs/decisions/2026-09-15-xbrl-tag-selection-methodology.md` (new,
extracted this round), `docs/decisions/2026-09-14-comment-audit-round2.md`
(the round this follows up on). Follow-up work (`agent.py` Round 4, the
full `tests/` pass) logged in `BACKLOG.md`.
