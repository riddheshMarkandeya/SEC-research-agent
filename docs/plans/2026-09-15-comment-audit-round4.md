# Comment Overhaul — Round 4 (`agent.py`)

## Context

Rounds 1-3 pointer-fixed 18 of the 19 originally-flagged main-source
files. `agent.py` (2497 lines, the largest file in the codebase) was
deferred repeatedly because it's denser than any other file — ~45+
blocks of old-style comments/docstrings that re-narrate decision
history inline (incident stories, "found live on <date>", rejected
alternatives, specific eval-question IDs) instead of pointing to the
`docs/decisions/*.md` file that already covers the same ground.

`agent.py` is qualitatively different from every file done so far:
several of its docstrings are also the closest thing this codebase has
to real architecture documentation for its most complex subsystem (the
tool-calling loop, structured-claims verification, table-grounded quote
checking, the calculate tool's operand-grounding). This round leans
hardest on the standard Round 2 (`table_grounding.py`) and Round 3
(`numeric_utils.py`'s regex block) already established: trim the
narration wrapper, keep the algorithmic "why is this shaped this way"
reasoning — even when a decision file also covers the same incident,
since the decision file documents the incident, not necessarily the
durable invariant a future maintainer needs.

## Decision / Design

Worked through the file top to bottom in four passes:

1. **Dead `PROJECT_CONTEXT.md` references** (5 spots): repointed each
   to the real decision file covering that content, or — for the one
   case quoting the project's own standing design principle rather than
   a one-time decision — to this project's own `CLAUDE.md` "design
   principles" section instead.
2. **Blocks citing `docs/plans/*.md` directly**: repointed each to its
   paired `docs/decisions/*.md` file, per Round 2's established pattern
   (a decision file is a shorter synthesis; the plan stays available for
   full mechanical detail on request).
3. **Remaining ALREADY-DOCUMENTED blocks**: confirmed each mapping by
   reading the target file directly, then pointer-fixed — module
   docstring, `_resolve_search_args`, `_format_no_fact_message`/
   `_format_no_comparison_message`, the validation helpers
   (`_is_valid_int`/`_rejects_invalid_fiscal_year`/`validate_tool_args`),
   `call_get_financial_fact`/`call_compare_financial_metric`,
   `_comparison_as_results`, the citation-marker/non-claim regex
   comments, `collect_citation_warnings`/`verify_citations`/
   `value_is_citation_verified`, the citation-retry section, and
   `_finalize_answer`.
4. **Judgment-call blocks** (the most careful work this round):
   `_ground_operand`'s three-case error-message taxonomy (kept in full —
   it's the load-bearing reason the function has three branches, not
   incident color; repointed the specific live-incident evidence to
   `docs/reviews/2026-09-14-tool-turn-waste.md`), `_SENTENCE_BREAK`'s
   regex-design comment (kept the "why lookaheads sit inside the
   pattern" reasoning, trimmed the "found in code review" framing),
   `validate_tool_args`'s `soft_required`/`skip_properties` carve-out
   semantics (kept in full as real API contract; trimmed the "broken 3
   times" historical framing), `_quote_grounded_in_source`'s
   table-authoritative-no-fallback design choice (kept), and
   `_iter_uncited_claims`'s "every reachable claim on one side, never
   both sides" contract (kept in full, only the dead `PROJECT_CONTEXT.md`
   citation and one `docs/plans` citation were repointed).

No EXTRACT findings — Round 3's inventory (done via direct full-file
reading after the Explore-agent inventory hit a session usage limit)
correctly predicted no orphaned decision-history content beyond what's
covered above. No DELETE candidates.

## Files and steps

1. Re-read `agent.py` in full (confirmed unchanged since Round 3's
   planning via `git diff HEAD -- agent.py`, empty).
2. Verify every candidate decision-file mapping by reading the target
   file directly.
3. Work through blocks in the four-pass order above.
4. Re-scan the whole file afterward via grep for `PROJECT_CONTEXT`,
   `docs/plans/`, `Week [0-9]`, and narration signal words ("found in",
   "found live", "confirmed live", "reverted", "tried and") to catch
   anything missed — caught and fixed 3 additional bare date-tag
   comments this pass turned up that weren't part of the original
   per-block plan.
5. Never touch executable code — only comment and docstring lines.

## Testing and verification

- `ast.parse()` confirmed the file still parses as valid Python.
- The programmatic tokenize-based check (reused from Rounds 2-3),
  confirming byte-identical code.
- Full pytest suite: 634 passed (matches the established baseline
  exactly).
- Full two-pass review (step 7): self-check plus a freshly-spawned
  subagent, specifically briefed to check both over-trimming
  (load-bearing reasoning deleted) and under-trimming (narration left
  in place) given this round's size and judgment-call density.
- Update `PROJECT_INDEX.md` (no new decision file needed this round —
  no EXTRACT findings).
- Update `BACKLOG.md`: remove the `agent.py` Round 4 item; the full
  `tests/` pass item is untouched.
- Write `docs/plans/2026-09-15-comment-audit-round4.md` (this file),
  `docs/reviews/2026-09-15-comment-audit-round4.md`,
  `docs/decisions/2026-09-15-comment-audit-round4.md` (plus
  `PROJECT_INDEX.md` lines).

## Related

`docs/decisions/2026-09-15-comment-audit-round4.md`,
`docs/reviews/2026-09-15-comment-audit-round4.md`,
`docs/decisions/2026-09-15-comment-audit-round3.md` (the round this
follows up on, including the "Round 4 backlog notes" that scoped this
round in advance). Follow-up work (the full `tests/` pass) logged in
`BACKLOG.md`.
