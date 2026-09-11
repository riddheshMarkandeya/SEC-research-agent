# Review: citation-gate FP/FN measurement instrumentation; Ollama demoted to secondary backend (2026-09-10)

Reviewing the change described in
`docs/plans/2026-09-10-citation-gate-measurement-instrumentation.md`.

## Pass 1: `/code-review` (high effort, 6 parallel agents) — correctness/compliance

Four real, confirmed issues, three fixed inline during the pass, one
deliberately deferred to `BACKLOG.md`.

**1. `_run_agent_impl`'s `backend` default was still frozen at
module-import time**, contradicting `PROJECT_CONTEXT.md`'s claim that
all three previously-hardcoded `backend: str = "ollama"` defaults now
resolve `config.DEFAULT_BACKEND` at call time. `run_agent`/`run_eval`
got the `backend = backend or DEFAULT_BACKEND` body-resolution fix;
`_run_agent_impl` still had a literal `= DEFAULT_BACKEND` parameter
default, which Python binds once at definition time. Currently latent
(the function has exactly one call site, inside `run_agent`, always
with an already-resolved backend), but the doc claim was false as
written. **Fixed**: made `backend` a required parameter with no
default — simpler than mirroring the dynamic-resolution pattern for a
private function nothing ever calls without an explicit value.

**2. Shared mutable list via `_EMPTY_CITATION_GATE_EVIDENCE`.** The
module-level dict's `"citation_warning_details": []` was one list
object, handed to every row via shallow `dict(...)`/`**` copies in two
call sites (`eval_harness.py`). Not currently triggered (nothing
mutates the list in place), but a classic dormant footgun for the next
edit that does. **Fixed**: replaced the constant with
`_empty_citation_gate_evidence()`, a function returning a fresh dict
(and fresh list) on every call.

**3. `complete()`'s Gemini branch read `resp.text` directly**, skipping
the empty-candidates/safety-filtered guard every other Gemini call site
(`_gemini_response_to_turn`) has — verified against the installed
`google-genai` v2.18.1 SDK source that this doesn't crash (`.text`
returns `None` cleanly on an empty-candidates response), but it silently
returns `""` instead of the informative, logged `RuntimeError` the rest
of the codebase raises for the identical case — an inconsistency with
this project's error-visibility standard (CLAUDE.md §4). **Fixed**:
routed through `_gemini_response_to_turn(resp)` instead of reading
`.text` directly; added `test_complete_gemini_raises_on_empty_candidates`
to lock it in.

**4. `_run_agent_impl`'s citation-retry fallback (`pre_retry_answer`) can
pair stale warnings with a grown `all_results`** if the retry's
follow-up makes further tool calls before hitting
`MAX_TOOL_ITERATIONS` — pre-existing since the 2026-08-24 retry design,
not introduced here. Newly relevant because
`eval_harness._citation_gate_evidence()` re-derives
`citation_warning_details` from the (grown) `retrieved` list, which
could disagree with the row's own `citation_warnings` (computed against
the smaller snapshot) in this narrow scenario. Doesn't affect the FP/FN
pass/fail classification (that's `grade_numeric`/`grade_comparison`-
based), only the diagnostic `false_positive_by_check` breakdown in that
one rare fallback path. **Deferred**: filed in `BACKLOG.md` as
`[bug (latent), Low, Standard]` — fixing `_run_agent_impl`'s retry logic
is out of this change's explicit scope (instrumentation only, no
verification-logic changes).

One incidental bug introduced and caught during the pass itself: fixing
finding 2 left a stale `**_EMPTY_CITATION_GATE_EVIDENCE` reference in
`run_eval()`'s exception handler (the renamed constant no longer
existed), which would have raised an uncaught `NameError` on any
per-question exception — exactly the "no partial report, no flush"
failure mode the surrounding broad `except Exception` exists to
prevent. Caught by a fresh line-by-line correctness pass before this
review concluded; fixed and confirmed via the existing
`test_run_eval_isolates_one_questions_exception_from_the_rest`
regression test, which exercises this exact path.

Also found (not a defect, a duplication smell): `_finalize_answer` and
`run_agent` independently accumulated the same `check -> count` dict
from `CitationWarning` lists with copy-pasted loops. **Fixed**:
extracted `_count_citation_checks()` (using `collections.Counter`,
not previously used anywhere in this codebase) shared by both.

No violations found in: TDD coverage (the `complete()` Ollama branch is
unit-tested; the Gemini branch has a genuine live-verification script,
`tests/manual/verify_complete.py`, re-run and passing after the fix
above); backlog tagging format (all new bullets carry correct
`**[type, priority, effort]**` tags); or any of the 5 hardcoded-`"ollama"`
call-site changes (traced across the whole repo, all correctly threaded).

One documentation-hygiene slip, unrelated to the code itself: the first
`BACKLOG.md` edit in this session duplicated a `### From the 2026-09-07
review...` section header via a copy-paste artifact in the edit's own
context string. Found by the CLAUDE.md-conventions-check agent; fixed.

## Pass 2: fresh subagent — architecture/design/performance/refactoring

No blocking issues. Confirmed the design fits the codebase: `CitationWarning`/
`AgentResult` match the existing `ModelTurn` NamedTuple idiom in
`llm_backends.py`; `analyze_citation_gate.py` follows the established
pure-function/manual-live-verification split; the `_run_agent_impl`
no-default vs. its two siblings' dynamic-resolution pattern is not an
inconsistency, since `_run_agent_impl` has exactly one call site with an
always-resolved backend (confirmed independently of pass 1's fix, same
conclusion). The double `collect_citation_warnings()` regex pass
(`_run_agent_impl` and `run_agent`'s span logging) was assessed and
judged negligible — regex over short answer text versus multi-second LLM
round trips.

Four minor, non-blocking observations, all either already covered or
addressed:

- Citation-warning structure gets independently rederived up to three
  times per refused row (`_finalize_answer`, `run_agent`'s span
  logging, `eval_harness._citation_gate_evidence`) rather than threaded
  through once. Safe today (pure, deterministic function); flagged as a
  coupling smell that would matter more if finding 4 above (the
  `pre_retry_answer` desync) ever widens. No fix applied — the
  alternative (widening `AgentResult`'s public shape for an internal
  logging/analysis detail) was already weighed and rejected in the
  design doc for good reason.
- The stress-question-suite/baseline-suite separation is convention-only,
  not enforced in code. **Added to `BACKLOG.md`**
  (`[design, Low, Trivial]`).
- Stress question 3's phrasing dependency (needs the model to place
  "U.S. GAAP" between the claim and its marker in one sentence) isn't
  pinned by an automated check — already covered by the existing
  `PROJECT_CONTEXT.md` entry documenting the exact confirmed reproduction
  text and by the Finding-1 `BACKLOG.md` item; no further action.
- `classify_row`/`summarize` assume `citation_warnings` and
  `citation_warning_details` stay in sync — this is the same
  already-backlogged `pre_retry_answer` desync (finding 4 above) viewed
  from the analyzer's side, not a new issue.

Two rounds, no new issues on the second round beyond what pass 1 already
found or what pass 2 itself resolved inline — stopping per CLAUDE.md's
review-loop cap.

## Verification after fixes

Full suite: 495 passed (up from 494 pre-review-pass, +1 for the new
`complete()` Gemini empty-candidates test). Live re-verification:
`tests/manual/verify_complete.py` re-run clean against real Gemini calls
after the `_gemini_response_to_turn` refactor.
