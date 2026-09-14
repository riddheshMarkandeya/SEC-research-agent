# Fix table-grounding regressions found by the live eval baseline

## Context

`table_grounding.py` (built earlier today per the prior plan, now superseded
by this one) replaced `_quote_matches`'s flat anchor-floor check with
structural table verification, and was merged/reviewed/tested (622 tests,
two independent review passes) — but its required live Gemini spot-check
was blocked by quota, so it was never actually exercised against real
model answers before today.

The user then asked to merge `eval/citation_stress_questions.jsonl` into
`eval/eval_questions.jsonl` (done, 47 questions) and run the full baseline.
That run (`eval/eval_results/20260913T211201Z.json`) surfaced two **real
regressions** in `table_grounding.py` itself. Mid-investigation, two
reactive patches were made directly against the running code without a
plan — the user stopped this and asked to **revert those patches, commit
the already-reviewed prior state, thoroughly diagnose the regressions, and
plan the real fix** before touching code again. This plan is that
diagnosis and fix design.

### What the eval run actually showed

A per-question diff against the last known-good baseline
(`eval/eval_results/20260912T225536Z.json`) found 8 flipped PASS→FAIL
questions. Six are confirmed pre-existing/unrelated (tool-budget
exhaustion with no citation attempt at all; the model quoting citation
*display* metadata that was never part of the real source text — the same
mechanism on two different questions; one already-documented latent
non-determinism bug). Two are real, `table_grounding.py`-caused
regressions, root-caused against the actual trace logs and real filing
chunks:

**Regression A — a genuinely faithful, byte-for-byte quote of an entire
table row (multiple independent values) gets refused.** CRM's remaining-
performance-obligation table (`chunks/CRM/0001108524-26-000060_chunks.jsonl`)
has one row: `| As of January 31, 2026 (1) | $35.1 | $37.3 | $72.4 |`
(Current/Noncurrent/Total — three genuinely different metrics, same row).
The model quoted this exact row verbatim for each of 3 claims; all 3 were
refused. Confirmed a second live instance on NVIDIA's segment table
(`chunks/NVDA/0001045810-26-000052_chunks.jsonl`): a 5-line verbatim quote
spanning the table's caption/header rows plus one data row, also refused.
Root cause: `quote_is_grounded`'s allowed-vocabulary check (row label +
group label + period header + the ONE cell's own value) has no path for
"this whole quote is genuinely, verbatim present in the source" — sibling
values in the same row are correctly excluded for misattribution
purposes, but that same exclusion also blocks a real multi-value
disclosure quoted honestly.

**Regression B — `locate_value`'s tolerance can return multiple cells, and
the per-cell check silently loses its own discriminating power on any cell
that isn't the "real" one.** MSFT's real Intelligent Cloud revenue
($34,681M) and Productivity & Business Processes revenue ($35,013M) are
~0.95% apart — both within the standard 1%-relative tolerance of a
$35,013M claim. `quote_is_grounded` compared a quote's numbers against
`cell.value`/`cell.unit` — the **caller's originally-claimed value**, not
the specific cell's own real content — so for the (wrong) Intelligent
Cloud cell, the check was comparing the claim against itself: trivially
always true. A quote like `"Intelligent Cloud Revenue $35,013"` (a real
value, falsely attributed to the wrong segment) wrongly grounded. Not
observed as a live eval failure in this run (no real question happened to
hit it), but independently confirmed via direct code execution as a live,
exploitable gap.

### The two reactive patches (to be reverted), and why they were wrong

1. Added an *unconditional* "exact substring of the whole source wins"
   fast path to `agent._quote_grounded_in_source`, ahead of table analysis.
   This fixed Regression A's two real cases — but a fresh independent
   review, and direct verification against the real MSFT chunk, confirmed
   it **reopens the row-splice attack the whole feature was built to
   close**: a claim of `$50,780` (Productivity's real 9-month operating
   income) citing a quote that is nothing but a raw, contiguous slice of
   the source crossing from Productivity's own row into Intelligent
   Cloud's label row (`"$50,780 |\n| Intelligent Cloud |  |  |  |  |\n| R"`)
   is now accepted with **zero warnings**. Verified directly:
   `_verify_one_claim` returns `None` for this claim. The same
   unconditional shortcut also reopens cross-segment steal and wrong-period
   misattribution whenever the fabricated text happens to be a real
   contiguous span (which a spliced/adjacent quote often is, since rows
   are just adjacent lines in the raw source). Digit-inflation stays
   blocked, but only via the separate downstream `value_not_in_quote`
   check, not by the mechanism credited.
2. Changed `quote_is_grounded`'s numeric comparison to use `cell.cell_text`
   (the specific cell's own real content) instead of `cell.value`/`cell.unit`,
   and removed those now-dead fields from `GroundedCell`. **This one is
   independently confirmed correct** by both a fresh review pass and direct
   testing — it closes Regression B with no side effects, and nothing else
   in the codebase read the removed fields. Recorded here for completeness;
   step 0 below reverts it anyway per the user's explicit request, and it
   gets reintroduced as part of the redesign.

### The deeper root cause

An independent review of the whole approach (not just the two named bugs)
found the underlying design is fragile, not merely under-tested:
`quote_is_grounded`'s allowed-vocabulary set is a narrow whitelist (row
label + group label + period header + the cell's own value) that rejects
almost *any* other word — an ordinary connective ("was", "segment"), a
caption word ("(In millions)"), or a rounded restatement ("$34.7 billion"
for a cell reading "$34,681") all fail today. This is only safe in
practice because `SUBMIT_TOOL_SCHEMA`'s own instructions tell the model to
quote verbatim — a prompt-level dependency, not a structural guarantee.
Regressions A and B are two instances of this same underlying fragility,
not independent one-off bugs.

A third case surfaced the same fragility from a different angle:
`msft-segment-revenue-comparison-q3fy2026` quoted an entire multi-period
row (`Revenue | $35,013 | $29,944 | 17% | $102,149 | $87,698 | 16%`, from
MSFT's *other*, more complex segment table) for a single claimed value,
and was refused — while an equivalent quote that happened to preserve the
row's empty pipe-cells would pass via the (now-reverted) exact-substring
shortcut. The accept/reject boundary was accidental formatting fidelity,
not a deliberate design choice. Confirmed on the real table that this
specific cell's own `period_header` is already `None` (the table's own
colspan-loss defeats column mapping there), so tolerating same-row,
different-period content trades away a defense that is already inert on
this exact table — consistent with this feature's own already-accepted
residual limitation ("a claim whose value is a real cell, quoted with no
contradicting period token, stays accepted — the error lives in the
answer text, not the quote").

### Decision (per user, 2026-09-13)

Full redesign, not a narrow patch: replace `quote_is_grounded`'s
word-vocabulary check with a **region-scoped reuse of the existing,
already-tested `_quote_matches` coverage/anchor logic** — matched against
a small permitted region (this cell's own governing group-label row, if
any, plus this cell's own data row — their *raw, verbatim source text*,
not a reconstruction from parsed cells) instead of the whole document.
This is what removes the ad hoc exact-substring shortcut entirely (a
verbatim multi-value row quote now naturally hits `_quote_matches`'s own
exact-substring fast path, but ONLY within the narrow region — a splice
into a different row/group is outside that region and cannot match), fixes
Regression B by construction (comparing against the specific matched
cell's own row text, never a separate "value" field), and resolves the
third case the same way Regression A resolves (same-row content is, by
definition, inside the permitted region).

## Step 0 — Revert and commit (prerequisite, before any redesign work)

1. Revert `table_grounding.py` and `agent.py` to their state immediately
   after the original two-pass review (before today's eval-triggered
   firefighting): `GroundedCell` regains `value`/`unit` fields;
   `quote_is_grounded` goes back to comparing against `cell.value`/
   `cell.unit`; `agent._quote_grounded_in_source` loses the unconditional
   exact-substring fast path. Remove the two regression tests added for
   Regression B during firefighting
   (`test_locate_value_finds_both_cells_within_the_standard_tolerance`,
   `test_rejects_cross_segment_steal_against_the_second_tolerance_matched_cell`)
   — they get reintroduced properly once the redesign is in.
2. Run the full suite to confirm this matches the state that actually
   produced today's eval run (622 → 620 tests, all green).
3. Commit this state (everything from today up through the eval merge and
   the original, reviewed `table_grounding.py` feature) as a checkpoint,
   per the user's explicit request — this is the clean baseline the
   redesign builds on, and it's also the honest historical record of what
   was actually live-tested.
4. Do **not** commit the two reactive-patch changes or their tests —
   they're superseded by the redesign below, not landed first and revised.

## Step 1 — Redesign `table_grounding.py`'s matching core

### Retain raw row text, not just parsed cells

`_Row` needs the original source line(s) verbatim, not just the split
`cells` list, so a "permitted region" can be built from real text rather
than a reconstruction that might not byte-match the source (pipes,
spacing, etc.). Add a `raw_text: str` field to `_Row`, populated from the
actual line(s) `extract_table_blocks` already iterates.

### Build a per-cell permitted region

For a `GroundedCell`, the permitted region is:
`(governing group-label row's raw_text, if any) + "\n" + (this cell's own
data row's raw_text)` — nothing else. Explicitly NOT included: other data
rows in the same group (a `Revenue` claim shouldn't ground on a
`Cost of revenue` row's content either), other groups entirely, and
header/caption rows above the group (their colspan-loss already makes
them unreliable, per the existing `_period_header_index` finding).

### Replace `quote_is_grounded`'s body

Instead of building a word-count allowlist, call a (reused or lightly
adapted) version of `agent._quote_matches`'s coverage/anchor logic with
`source` = the permitted region instead of the whole chunk. Concretely:
either import and call `_quote_matches` directly (accepting the minor
layering of `table_grounding` depending on a matching primitive that
currently lives in `agent.py` — likely means promoting `_quote_matches`'s
core coverage logic, or at least its constants, to `numeric_utils.py` or
its own small shared home, mirroring the earlier `normalize_for_match`
extraction, to avoid `table_grounding.py` importing from `agent.py` and
creating a cycle), or re-derive an equivalent small coverage check
in-module using the same constants. Reuse the tested logic; do not
hand-roll a second one.

**Open implementation question, to resolve empirically during TDD, not
decided here**: whether the existing `_QUOTE_ANCHOR_CHARS=30` anchor floor
still makes sense once the search space is already narrowed to a
single-row-plus-label region. The anchor floor's original purpose was
blocking a fabricated quote assembled from scattered fragments of a large
document — with the region already this small, that assembly space barely
exists, so a pure coverage threshold (no anchor requirement) may be
sufficient and is worth testing first; keep the anchor as a fallback if
testing shows scattered-fragment assembly is still possible within a
single row (e.g., a row with many short, repeated tokens).

### `locate_value` changes

Keep the existing tolerance-based cell location logic (that's not what's
being replaced) but stop threading `value`/`unit` into `GroundedCell` —
carry `raw_text`-derived context instead, consistent with the region
design above.

## Step 2 — Tests (TDD, full red-green, pure logic)

Write these against real filing text (already in `tests/test_table_grounding.py`
and `tests/test_agent.py` as fixtures — MSFT segment table, AAPL geography
table; add CRM's RPO table and NVIDIA's segment table as new real
fixtures, extracted the same way as the existing ones, not paraphrased):

**Must now accept** (previously-refused real cases):
1. CRM's full RPO row, verbatim, grounding each of the 3 independent claims
   (35.1/37.3/72.4 billion).
2. NVIDIA's 5-line segment-table quote (caption + header rows + one data
   row), verbatim, grounding both claims (74550/7065 million).
3. MSFT's table-47 multi-period row for one claimed value (the third,
   previously-ambiguous case) — now consistent with (1)/(2) rather than
   contingent on incidental pipe-formatting.
4. Everything the original 17 `table_grounding.py` tests already covered
   (short-label segment quotes, all 4 metric rows, no-group-label case).

**Must still reject** (re-verify each explicitly against the redesigned
mechanism, not assumed from the old design):
5. Row-splice across a row boundary — the exact reproduction that broke
   the reactive patch (`"$50,780 |\n| Intelligent Cloud |..."` and
   variants) — this is the single most important regression test in this
   whole change, since it's what the reactive patch got wrong.
6. Cross-segment steal, including via the near-tolerance duplicate-cell
   path (Regression B's real shape: Intelligent Cloud vs. Productivity's
   $35,013).
7. Wrong-period/wrong-column misattribution (`"2025 Productivity...
   Revenue $35,013"`).
8. Digit-inflation / sign-insertion.
9. Full suite green throughout.

## Step 3 — Wiring and docs

- `agent._quote_grounded_in_source`: remove the unconditional
  exact-substring shortcut entirely (superseded — the redesigned
  `quote_is_grounded` handles verbatim quotes correctly within its own
  scoped region). Keep the "value not in any table cell → fall through to
  `_quote_matches`" behavior unchanged.
- Correct `docs/plans/2026-09-12-structure-aware-table-quote-grounding.md`
  is left as historical record (do not edit — it documents what was true
  when written); this new plan supersedes it going forward. Save this
  plan to `docs/plans/2026-09-13-table-grounding-region-scoped-matching.md`
  once approved.
- `docs/reviews/` — new review file recording this regression's diagnosis
  and fix, per CLAUDE.md step 7 (two-pass review applies again since this
  touches `_verify_one_claim`'s dependency chain).
- `BACKLOG.md`/`PROJECT_CONTEXT.md` — changelog entry for the regression,
  its root cause, and the redesign; update or remove the two "known
  limitations" items filed against the original design if this redesign
  changes their status.

## Step 4 — Verification

1. Full test suite green.
2. Targeted live spot-checks against the exact regressed questions:
   `eval_harness.py --backend gemini --ids crm-rpo-fy26,nvda-segment-revenue-comparison-q1fy27,msft-segment-revenue-comparison-q3fy2026,msft-three-segments-revenue-q3fy2026`
   (the last one is the original reported bug — must stay passing).
3. Full baseline re-run (`eval_harness.py --backend gemini`, no filter)
   once the above targeted check is clean — this is the actual, final
   confirmation this project's own rules require for a broad change to
   `_verify_one_claim`'s dependencies, and it's still owed from the
   original feature.
4. Two-pass independent review of the redesign (self + fresh subagent),
   same discipline as the original feature and this regression
   investigation — this module has now twice produced a real bug past a
   first review, so the review pass matters here, not as a formality.

## Files

- `table_grounding.py` — core redesign (raw row text, permitted-region
  construction, `quote_is_grounded` replacement).
- Possibly a small shared home for `_quote_matches`'s coverage/anchor
  logic (or its constants) if `table_grounding.py` needs to call it
  without creating a circular import with `agent.py` — mirrors how
  `normalize_for_match` was already extracted to `numeric_utils.py` for
  the same reason.
- `agent.py` — remove the reactive exact-substring shortcut from
  `_quote_grounded_in_source`.
- `tests/test_table_grounding.py`, `tests/test_agent.py` — new fixtures
  (CRM RPO table, NVIDIA segment table) and the accept/reject tests above.
- `BACKLOG.md`, `PROJECT_CONTEXT.md`, `docs/reviews/2026-09-13-*.md`.
