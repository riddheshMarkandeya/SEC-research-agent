# Fix 3 backlog items: uncited-claim detection, get_frame() ordering bug, retrieval.py verify script

## Context

Reviewing `BACKLOG.md` (now tagged `[type, priority, effort]`) for what to
pick up next, three items stood out as the best mix of real impact and
contained (Standard-tier) scope:

1. **`cash_to_assets` citation-verification gap** `[bug (latent), Low,
   Standard]` — this project's core trust guarantee is "every numeric
   claim must trace to a specific filing + section, or the agent
   refuses" (`PROJECT_CONTEXT.md`'s design principles). `verify_citations()`
   only enforces that for numbers that already sit near a `[n]` marker —
   a numeric claim with **no marker anywhere near it** is invisible to
   the scan entirely and sails through unrefused. Found live
   (`PROJECT_CONTEXT.md`'s 2026-08-25 "Formula registry extended"
   section): asked for `msft-cash-to-assets-fy2025`, the model
   self-computed the ratio from two separately-retrieved raw values in 2
   of 4 manual runs and stated the result with zero citation marker
   nearby — exactly the gap this fixes.
2. **`xbrl_facts.py`'s `get_frame()` ordering dependency**
   `[bug (latent), Low, Standard]` — a real correctness risk on the core
   financial-data-merge path: if two XBRL tags ever both report data for
   the same ticker/period, the result silently depends on Python's `set`
   iteration order (an implementation detail), and any real collision is
   currently swallowed with no signal that it happened.
3. **`retrieval.py` missing `tests/manual/verify_*.py` script**
   `[test-coverage, Low, Standard]` — the one live-only integration point
   in the codebase without the manual verification script this project's
   own TDD carve-out requires for exactly this kind of code (live Chroma
   + embedding + reranker calls that mocking would only test the mock
   of, not the code).

Explored this session: one fresh Explore agent for the citation-gap
(found the exact scan mechanism and the `PROJECT_CONTEXT.md` motivating
case), one Plan-agent design pass specifically on how to detect an
uncited claim (the one genuinely open design question among the three),
plus two Explore agents from earlier this same session already covered
`get_frame()` and `retrieval.py`'s live half in full. Verified directly
(not just via the Plan agent's claims): `numeric_utils.py`'s
`NUMBER_PATTERN`/`extract_numbers()`, `agent.py`'s `_NON_CLAIM_PATTERN`,
`_format_refusal_message()`, and `value_is_citation_verified()`'s own
docstring (confirms it deliberately treats an uncited value as fine for
eval-grading purposes, so it must NOT consume the new check).

## 1. Detect uncited numeric claims (`agent.py`, `numeric_utils.py`)

**Design**: a claim's "uncited" status is determined by distance to the
nearest `[n]` marker in the untouched original text (not sentence
splitting — ruled out: financial text is full of sentence-boundary-like
periods that aren't ones, e.g. "$109.4 billion", "U.S.", "10-K/10-Q",
and this file already needed `_NON_CLAIM_PATTERN` just for the
non-sentence-aware noise). Symmetric to the existing backward-only
window, using the same `_CITATION_WINDOW_CHARS` (150) constant — a
claim within that distance of *any* marker (before or after) is treated
as "near a citation" (and, if genuinely near one, already gets checked
for accuracy by the existing `_iter_citation_claims` path); anything
farther from every marker is uncited.

- **`numeric_utils.py`**: add `extract_numbers_with_spans(text) ->
  list[tuple[float, str, int, int]]` (value, unit, start, end — using
  `match.start(1)`/`match.end(1)`, the digit group) as the position-aware
  sibling of the existing `extract_numbers()`. Rewrite `extract_numbers()`
  as a one-line wrapper dropping the spans, so `eval_harness.py`'s
  existing call site is untouched.
- **`agent.py`**: add `_iter_uncited_claims(answer_text: str)` — a plain
  generator, no I/O:
  ```python
  def _iter_uncited_claims(answer_text: str):
      non_claim_spans = [m.span() for m in _NON_CLAIM_PATTERN.finditer(answer_text)]
      marker_starts = [m.start() for m in _CITATION_MARKER.finditer(answer_text)]
      for value, unit, start, end in extract_numbers_with_spans(answer_text):
          if any(s <= start < e for s, e in non_claim_spans):
              continue
          if any(abs(start - ms) <= _CITATION_WINDOW_CHARS for ms in marker_starts):
              continue
          yield value, unit
  ```
  Deliberately operates on the **untouched original `answer_text`**
  throughout (never a sliced/re-stripped substring) — `_iter_citation_claims`
  can get away with string mutation because it only ever needs positions
  *relative to* an already-sliced window; this function needs positions
  relative to the whole text to measure distance to markers, so mutating
  the string would silently drift the offsets.
- **`verify_citations()`**: add a second loop consuming
  `_iter_uncited_claims(answer_text)`, appending warnings shaped
  `f"claims {value} ({unit}) but no citation marker appears anywhere
  near it to trace the claim to a source"` — no `[n]` prefix (there is
  none), but close enough to the existing `"claims {value} ({unit})
  but ..."` grammar that `_format_refusal_message()` (which just does
  `f"- {w}"` per warning, no per-warning parsing, confirmed by reading
  it directly) renders both kinds identically in one bullet list.
  Dedupe key uses a `"uncited"` sentinel instead of `n` (there's no `n`
  to key on).
- **Deliberately NOT touched**: `_iter_citation_claims()` and
  `value_is_citation_verified()` — the latter's own docstring explicitly
  states it treats a value with no citation as fine ("nothing to
  contradict a plain-text match"), since `eval_harness.py`'s grading
  already separately checks the number appears in the answer text at
  all; wiring the new check in there would change eval-grading semantics
  this task isn't scoped to touch.

**False-positive check** (done against the actual regex, not assumed):
`NUMBER_PATTERN`'s `(?<!\w)` lookbehind already rejects letter-glued
digits like `Q3`/`Q1-Q3`/`FY2026`, so `_Q4_NOT_DISCLOSED_HINT`/
`_never_tagged_hint()` text poses no risk. `_NON_CLAIM_PATTERN` already
strips full dates, bare years, and `10-K`/`10-Q` mentions before the
scan. **Real residual risk, accepted at Standard-tier scope**: a claim
whose own marker sits >150 chars away in an unusually long sentence will
now be flagged where it previously wasn't — same tuning risk the
existing window already carries in the other direction; revisit the
constant from real eval-run false positives if one shows up, the same
way `_NON_CLAIM_PATTERN` itself was built iteratively.

**Tests** (`tests/test_agent.py`, `tests/test_numeric_utils.py` if that
file exists, else add coverage in `test_agent.py`): pure/deterministic
logic, full TDD. New cases: a bare uncited numeric claim gets flagged; a
claim within 150 chars of a marker (either direction) is NOT flagged by
the new check (still handled by the existing path); the exact
`msft-cash-to-assets`-shaped case (self-computed percent, zero markers
in the sentence) is flagged; `_Q4_NOT_DISCLOSED_HINT`/date/form-type text
embedded in an answer doesn't trip it; `_format_refusal_message()`
renders an uncited-only warning list sensibly. Also add an integration
test alongside the existing `test_run_agent_refuses_when_ollama_answer_has_unverified_citation`-style
tests (~agent.py:1655) confirming `run_agent()` now refuses an
otherwise-clean answer containing a bare uncited number.

## 2. Fix `get_frame()`'s ordering dependency (`xbrl_facts.py`)

`xbrl_facts.py:429-461`. Two changes:

- Make iteration deterministic: `tags_in_play = sorted({_tag_for(ticker,
  metric) for ticker in companies})` instead of iterating the bare set.
- On a genuine collision (a ticker already in `results` when a second
  tag also reports it), don't silently `continue` — log it via
  `log_event` (matching this project's `tracing.py` pattern) with both
  tags and both values, so a real conflict is visible instead of
  silently swallowed. This is the CLAUDE.md-mandated logging-at-a-
  decision-point case: today nothing would tell a future debugging
  session two tags disagreed.

**Test**: extend `tests/test_xbrl_facts.py`, sibling to the existing
`test_get_frame_merges_across_distinct_tags_for_divergent_metrics` —
construct two tags both reporting the same ticker/CIK with different
`val`s, assert (a) the deterministic winner (first tag in sorted order),
and (b) `log_event` fires with the conflict details (monkeypatched,
matching this file's existing pattern). Pure/deterministic logic once
`fetch_frame`/`load_companies` are mocked — a real red-green unit test,
not a manual script.

## 3. Add `tests/manual/verify_retrieval.py`

Follows `tests/manual/verify_period_labels.py`'s conventions (real local
data, no API-key gating — unlike `verify_tracing.py`/`verify_mcp_server.py`,
which gate on Langfuse/MCP auth):

- Module docstring + the `sys.path.insert(0, ...)` shim every existing
  script needs, usage `python tests/manual/verify_retrieval.py` from
  repo root.
- Before running anything, check the Chroma collection and `./chunks/`
  exist (matching `verify_tracing.py`'s clean-skip spirit and
  `_load_bm25_index()`'s existing "run chunk_documents.py first"
  `RuntimeError` message) — print a clear setup-needed message and exit
  cleanly rather than a raw traceback if the index hasn't been built.
- Exercise `bm25_search`, `vector_search`, `hybrid_search`, and `rerank`
  end-to-end with a few real known queries, report in
  `verify_period_labels.py`'s checked/confirmed/problems style
  (informational, not a hard `assert`-and-exit-1 gate, since result
  quality is a judgment call, not an exact match).

## Verification (all 3 items)

- Run `pytest` (full suite) — must pass, including the pre-commit-hook
  gate. New/updated tests fail before each fix and pass after (red-green).
- Run `python tests/manual/verify_retrieval.py` from repo root against
  the real local Chroma index — the live-verification step for item 3.
- **Spot-check eval on both backends** (`eval_harness.py --ids ... --backend
  ollama` / `--backend gemini`), same discipline as the schema-validator
  session — that live check is what caught a real Gemini-breaking
  regression unit tests alone couldn't have found. Pick ~6-7 questions
  covering: a plain numeric fact (sanity baseline), a question that
  exercises `get_frame()` via `compare_financial_metric` on a
  duration-type metric (item 2's path), the `msft-cash-to-assets-fy2025`
  question itself (item 1's original motivating case — check whether it
  now either cites correctly or refuses instead of silently passing
  uncited), a `judged`/`search_filings` question, and a refusal-type
  question (confirm the new check doesn't turn an already-correct
  refusal into a different one for the wrong reason). Read the results
  for any *new* refusal on a question that previously passed cleanly —
  that would mean the uncited-claim check is over-firing and needs its
  window/pattern tuned, not just accepted.
- Run `python tests/manual/verify_mcp_server.py` — confirms item 2's
  `get_frame()` fix doesn't break real MCP `get_financial_fact`/
  `compare_financial_metric` calls (both route through `xbrl_facts.py`
  for duration-type metrics), and is cheap enough to run after any
  change touching that module regardless.
- Per CLAUDE.md step 7: `/code-review` (medium effort) then a
  separately-spawned fresh architecture subagent. Save findings to
  `docs/reviews/2026-09-09-<slug>.md`, fix what's found, repeat both
  passes on the fix (capped at 2 rounds with no new issues).
- Update `PROJECT_CONTEXT.md` with a `###` write-up per CLAUDE.md step 6
  and remove all three items from `BACKLOG.md` once done.
