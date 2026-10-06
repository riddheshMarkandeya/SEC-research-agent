# Close package 4 (not-available answer); fix the pltr-dividend criteria instead

**Date:** 2026-10-06

## Context

Package 4 of `docs/plans/2026-09-28-agent-improvement-map.md` was review S3, "a first-class
not-available answer" (`docs/plans/2026-09-28-structural-review.md`, S3 and C5), plus the gate
map's ticket "Tool-message citations on refusal questions". S3 came from 478 runs, all before
packages 1, 2, 5 and 3. In them the refusal questions searched until the budget ran out, and the
forced final turn made up filler claims the gate refused: 14 gate refusals and 7 judge fails.

Re-measured on 2026-10-06 (traces since 2026-10-03; reports `20261003T030904Z` to
`20261006T073606Z`):

- Both S3 target questions pass every graded run: `nvda-rd-expense-q4fy26-refusal` 8/8,
  `pltr-inventory-turnover-fy2025-refusal` 8/8. Forced turns still happen (5 of 14 and 8 of 12
  runs) but end in correctly cited answers. What's left is about 2 extra calls per run.
- The tool-message ticket's symptom is gone: no recent answer cites a tool message, and both
  latest answers have `citation_warnings: []`.
- The one failing refusal question, `pltr-dividend-2019-refusal` (38/68 all-time, 0/8 since
  09-19), is a grading problem. Its answers are correct and cited ("Palantir has never declared
  or paid any cash dividends on its capital stock [7]"), but the criteria asked the answer to
  "explicitly state that the provided filing excerpts do not contain information about dividends
  in 2019". The strict judge read that as a requirement, against the same criteria's "FAILS only
  if" line. The identical answer was graded FAIL 5 times and PASS once.

This revisits two recorded lines (`~/.claude/CLAUDE.md` §4): the map's package 4, and its
out-of-scope "Judge-criteria content failures with no gate or retrieval involvement"
(`agent-improvement-map.md`, Out of scope). The gate map already assigned this exact qid to
"judge criteria work" (`2026-09-28-gate-refusal-flakiness-map.md`, Out of scope). What changed:
it's now the only refusal-question failure, and package 4's own target has gone.

## Decision

User, 2026-10-06: rescope package 4 to the criteria fix, close S3 and the tool-message ticket
with the evidence above, then move on to package 6. S3's `not_available` schema and its
stop-searching prompt rule are not built.

The new criteria (`e8bd2a2`) pass any of: no dividend in 2019 ($0 counts), never paid or
declared one, or the filings don't report a 2019 figure, including that combined with a
"therefore none was paid" conclusion. They fail a nonzero per-share amount, or an answer that
doesn't address dividends (generic error, budget message, gate refusal, unrelated refusal), as
`ca52d68` did for nvda-rd. The `77b642b` EPS carve-out stays.

**Comparison guard.** `prompt_fingerprint()` covers `prompts/` only, so `compare_prompt_versions`
can't see a criteria change and fingerprint mode would pool old and new grades. Package 6's base
runs must come from `e8bd2a2` or later, or exclude this qid. A BACKLOG item hashes the questions
file into provenance.

**Reopen S3** if forced-turn refusals or judge fails come back on a refusal question, or if the
quota spent on forced turns becomes the binding limit.

## Why

S3 was a fix for a failure that the earlier packages removed. Building a schema field and a
prompt rule for about 2 calls per run would spend a prompt commit and a measurement for no
measured gain. The only live failure was the grader contradicting itself, and the
`ca52d68`/`77b642b` precedents fix that in the criteria, not in the agent.

## Files touched

- `eval/eval_questions.jsonl`: the `pltr-dividend-2019-refusal` criteria only.
- `tests/manual/verify_pltr_dividend_criteria.py`: new, re-runnable when the judge changes.
- Docs: the map, `BACKLOG.md`, `PROJECT_INDEX.md`.

## Verification

`tests/manual/verify_pltr_dividend_criteria.py` on `gemini-3.5-flash-lite`, same day:

- old criteria: 6/15 PASS on a deduped, hand-picked sample of correct stored answers;
- first new wording: 28/29 as expected; `20260907T004456Z` ("filings don't contain it ...
  therefore did not declare any") failed as speculation, so the wording now covers that form;
- final wording: 29/29 as expected. Sample 15/15 PASS; latest answer 5/5 PASS; two made-up
  nonzero dividends FAIL; gate refusal (`20260911T073808Z`) 3/3 FAIL; budget message
  (`20260817T232126Z`) 3/3 FAIL; EPS control PASS.

Live spot-check from clean `e8bd2a2`: 3/3 PASS, each `citation_warnings: []`
(`20261006T165628Z`, `20261006T165709Z`, `20261006T165749Z`).

## Related

- `docs/plans/2026-09-28-agent-improvement-map.md` (package 4, Out of scope)
- `docs/plans/2026-09-28-structural-review.md` (S3, C5)
- `docs/plans/2026-09-28-gate-refusal-flakiness-map.md` (Out of scope; the tool-message ticket
  is tracked in the improvement map)
- `ca52d68` (nvda-rd criteria fix; "a generic error fails"), `77b642b` (EPS carve-out),
  `e8bd2a2` (this criteria change)
