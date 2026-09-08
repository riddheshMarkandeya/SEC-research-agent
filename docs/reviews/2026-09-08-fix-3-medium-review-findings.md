# Layered review — 3 Medium fixes from the 2026-09-06 review (2026-09-08)

**Scope:** the diff fixing `docs/reviews/2026-09-06-full-codebase-review.md`'s
§5 (`chunk_documents.py` final-flush tail filter), §7 (`edgar_ingest.py`
unguarded `get_filing_list()`), and §9 (`formulas.py` zero-denominator
guard). See `PROJECT_CONTEXT.md`'s matching 2026-09-08 section for what
shipped and how it was verified.

**Method:** two independent passes per CLAUDE.md step 7 — (1) the
`/code-review` skill at medium effort on the working-tree diff, and (2)
a freshly-spawned subagent with no memory of the implementation
session, given the diff and asked to judge architecture fit,
simplicity, performance, and refactoring opportunities on their own
merits.

**Status:** all findings below are FIXED, same day, before the diff was
considered done. Two rounds were run per CLAUDE.md's repeat-until-clean
rule: round 1 (below, findings #1-#2) on the original diff; round 2 (a
second `/code-review` pass plus 4 fresh angle-subagents) on the fixed
diff surfaced one more real gap (#3) and confirmed everything else,
closing the loop.

---

## Findings

### 1. `edgar_ingest.py`'s new `except` clause was narrower than its own justification (found independently by both passes)

**`/code-review` (pass 1):** the first fix caught only
`requests.RequestException` around `get_filing_list(cik)`, but that
function's body can also raise `ValueError`/`json.JSONDecodeError` (a
malformed JSON body from `resp.json()`) or `KeyError` (an unexpected
submissions schema from `data["filings"]["recent"]`) — either would
still propagate uncaught and abort ingestion for every subsequent
company, the exact regression the fix was meant to close.

**Fresh-subagent architecture pass (pass 2), same diff, no context from
pass 1:** independently flagged the same gap, and went further —
pointed out that even the broadened `except (requests.RequestException,
ValueError, KeyError)` tuple could still miss a `TypeError` (e.g. if
SEC ever returned `recent["form"]` as a non-sequence), and that the
fix's own comment claimed parity with the per-filing catch three lines
below it ("the same per-item resilience the per-filing loop just below
already has") without actually matching it — that catch is a bare
`except Exception`.

Two independent review angles converging on the same under-broad catch
was a strong signal it was real, not noise — the same pattern the
2026-09-07 review of the `get_metric_all_companies()` redesign also hit.

**Fix:** switched to a broad, commented `except Exception`, matching
the per-filing catch's own established pattern in this file rather than
enumerating types — a deliberate case of CLAUDE.md's error-handling
carve-out ("a boundary where many different failure types should all
degrade the same way"). Added a `ValueError` test case
(`test_main_continues_to_next_company_when_get_filing_list_hits_malformed_json`)
alongside the existing `ConnectionError`/`KeyError` ones so more than
one exception type is actually exercised, not just asserted about in a
docstring.

### 2. `tests/test_edgar_ingest.py`'s malformed-schema test claimed `ValueError` coverage it didn't have (found by `/code-review`)

The original single "malformed schema" test's docstring described
covering both the `ValueError` and `KeyError` cases, but the fake only
ever raised `KeyError` — the `ValueError` claim was untested. Fixed by
splitting into two tests sharing one helper
(`_assert_main_survives_get_filing_list_failure`), one raising
`ValueError("Expecting value")` and one raising `KeyError("filings")`,
so each claimed failure mode has its own real assertion.

### 3. `chunk_blocks()`'s mid-loop overflow-close branch had no test for genuine (non-overlap) short content (found in round 2 by a fresh removed-behavior-auditor subagent)

The round-1 fix added `test_chunk_blocks_keeps_short_final_block_with_genuine_content`, which covers the guarantee "a genuine short block is never dropped just for being short" — but only at the *final* flush. The mid-loop close (`if current and not current_is_only_overlap: chunks.append(current)`, reached when a block would overflow `MAX_CHUNK_CHARS`) exercises the identical flag-check logic on a different code path, and had no test of its own confirming genuine short content survives *there* too. Old (pre-fix) behavior would have silently dropped such a chunk in this branch as well, for the same reason as the final-flush case — a regression that reintroduced a length check in just this one branch would have passed the full suite undetected.

**Fix:** added `test_chunk_blocks_keeps_short_genuine_content_closed_out_mid_document` (a short first block, never touched by the overlap-reset, closed out mid-loop by a following oversized table) and confirmed by hand that the pre-fix length-heuristic logic does silently drop it (simulated the old `chunk_blocks()` body standalone — it returns 1 chunk instead of 2, losing the short paragraph entirely).

---

## Round 2: other findings raised, not requiring a code change

- **`formulas.py` now has 3 independently-written same-shape zero-denominator guards** (`get_yoy_growth`, `_compute_ratio_metric`, `_compute_ratio_metric_all_companies`) with no shared `_safe_ratio()` helper. Real duplication, but CLAUDE.md section 3 explicitly permits deferring extraction for a Standard-tier fix ("doesn't need the surrounding code refactored"). Added to `BACKLOG.md` as a Low design note for whenever a 4th call site needs the same guard.
- **A hypothetical empty-string block would incorrectly clear `current_is_only_overlap`** (`f"{overlap}\n\n{''}".strip()` collapses back to just the overlap value, but the flag still gets set to `False` on that merge). Not currently reachable — `split_into_blocks()` never produces empty blocks — so this is a documented assumption, not a live bug. Added to `BACKLOG.md` as a Low latent-fragility note.
- Both `/code-review` (round 2) and a dedicated cross-file-tracer subagent independently confirmed no caller anywhere assumes a `ZeroDivisionError` propagates from the ratio functions, and that `agent.py`'s existing `None`/missing-key handling already covers the new degrade-to-`None`/skip-this-company paths with no change needed on the caller side.

## Areas reviewed with no findings

- `chunk_documents.py`'s `current_is_only_overlap` flag design (both
  passes): confirmed as the minimal correct fix — the fresh-subagent
  pass independently re-derived that a naive length-based check at the
  final flush would fail `test_chunk_blocks_keeps_short_final_block_with_genuine_content`
  (a genuine short final block reached via the overflow-reset branch
  can be shorter than `OVERLAP_CHARS`), confirming the flag approach
  over the simpler-looking alternative was the right call, not
  over-engineering. No performance concerns (O(1) extra state per loop
  iteration in an offline batch pipeline over ~25 filings).
- `formulas.py`'s two zero-denominator guards: both passes found these
  correctly mirror `get_yoy_growth()`'s existing pattern, with tests
  exercising both the single-company (`None`) and cross-company
  (per-company exclusion) paths.
