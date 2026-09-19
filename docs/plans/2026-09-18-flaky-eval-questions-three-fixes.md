# Turn flaky eval questions into solid passes: three targeted fixes

## Context

Following the orphaned-table-overlap chunking fix (`docs/decisions/2026-09-17-fix-orphaned-table-overlap-chunking.md`,
41/47 live-confirmed), the next request was to investigate the eval
suite's flaky questions broadly and find what's fixable — reusing
`BACKLOG.md` items where they exist, creating new ones where they
don't.

## Investigation (three rounds, each correcting the last)

1. Scanned all 112 historical `eval/eval_results/*.json` files and
   computed a historical pass rate for every one of the 47 current
   questions. Flakiest: `msft-segment-revenue-comparison-q3fy2026`
   9/30 (30%), the three `five-company-*-ranking-fy2025` questions
   46-48% each, `pltr-inventory-turnover-fy2025-refusal` 48%. Found
   along the way: `ClientError: 429 RESOURCE_EXHAUSTED` (Gemini's
   free-tier daily quota) contaminates nearly every flaky question's
   failure history — an infra artifact, not a real signal.
2. Cross-referenced against `BACKLOG.md`/`docs/decisions`/`docs/reviews`.
   None of the flaky questions are untouched territory — all have prior
   history. `msft-segment-revenue-comparison-q3fy2026` has the deepest:
   5+ distinct root causes found and fixed over a month, yet it keeps
   failing via new/residual mechanisms. Its current standing item was
   explicitly blocked on a logging gap: `CitationWarning` captured the
   citation *index* but never the failing *quote text*.
3. A cluster of `gate_withheld_would_have_passed: True` rows (cases
   where the harness's own after-the-fact re-grade confirms the
   withheld answer's numeric content was objectively correct, yet the
   citation gate refused it) looked at first like a single widespread
   pattern matching a deferred `BACKLOG.md` item (`nvda-gross-margin-fy26`,
   2026-09-11 — "needs a decision once this pattern is confirmed to
   recur"). Direct code reading + re-checking the raw historical rows
   narrowed this considerably: most candidate instances were stale
   (pre-dating the structured-claims rollout), already-fixed (a
   since-resolved bare-letter-unit-abbreviation bug), or a different
   mechanism entirely. **One clean instance survives**:
   `aapl-operating-margin-q3fy2026` — a missing `claims[]` entry for a
   `calculate`-tool operand shown inline, a different, more precisely-
   scoped mechanism than the deferred item, which is left untouched.

User chose to proceed with all three fixes this surfaced, with the
riskiest one (A) done as a code-side fix rather than a prompt-side one.

## Design discussion: a distinct `claim_type: "computed"` schema, considered and set aside

Mid-session, before implementation, an alternative was raised: instead
of teaching the coverage check to recognize calculate-operands, give
the model an explicit second claim type ("computed claim") verified by
re-computation instead of quote-matching. Investigation found this
prior art is already substantially implemented: the comment above
`CALCULATE_TOOL_SCHEMA` (agent.py) documents the exact same prior art
(FinQA/ConvFinQA/TAT-QA's explicit-program pattern, PAL/Toolformer's
"don't trust LLM arithmetic") and explains that `calculate`'s result
was deliberately built to become "a normal `all_results` entry the
model cites like any other tool output — zero changes needed to
`verify_claims`/`_verify_one_claim`/`CitationWarning`." The real gap
was narrower: rule 9 *also* asks the model to restate operands in the
reader-facing prose, and that restatement — not the computed claim
itself — was what tripped the coverage scan. Formalizing a new schema
type would have re-solved an already-solved problem at the cost of a
system-prompt rewrite and a change to both backends' tool-calling
contract. Kept as a possible separate future item, not adopted here.

## Fix A: exempt grounded `calculate` operands from the coverage check

Root cause: `verify_claims()`'s coverage check scans the entire answer
text for numbers and demands each match a `claims[]` entry, with no
awareness that rule 9 tells the model to restate `calculate` operands
inline for human readability. Fix: recognize a successful `calculate`
call's own synthetic `all_results` entry (`chunk_index == "calculated"`)
and exempt its operands from the coverage check, mirroring the existing
`question_numbers` exemption pattern — no new parameters threaded
through the tool-dispatch loop, since `all_results` is already
`verify_claims()`'s own parameter.

Went through two rounds of revision during implementation review (see
paired review file): the first design threaded a new parameter through
`_dispatch_tool_call`/`_run_agent_impl`, breaking 13 existing test call
sites — replaced with the `all_results`-filtering approach above. A
follow-up round then found the replacement extracted from a calculated
entry's *entire* text, which silently also exempted the calculation's
own RESULT value (letting a derived number ship with zero `claims[]`
entry at all) — fixed by scoping extraction to only the text before the
entry's own `"="` (the operands), never the result after it.

## Fix B: capture the actual quote text in citation warnings

`CitationWarning` had no `quote` field — every quote-grounding failure
recorded only the citation *index*, not what the model actually quoted,
which is exactly what blocked `msft-segment-revenue-comparison-q3fy2026`'s
and `nvda-cost-of-revenue-fy2026`'s root causes for weeks. Added a
`quote: str | None` field, populated at the structured-claims path's
five quote-related checks (`_verify_numeric_claim`,
`_verify_qualitative_claim`); explicitly left `None` at every other
site, including the entire older prose-fallback path
(`_iter_citation_claims`/`_iter_uncited_claims`/`collect_citation_warnings`),
which has no comparable quote concept to capture at all (a separate,
lower-priority enhancement, filed to `BACKLOG.md`).
`citation_warning_details` (`eval_harness.py`) picks up the new field
automatically via its existing `[w._asdict() for w in warnings]`
serialization — no additional plumbing.

## Fix C: exclude quota-exhausted runs from flakiness analysis

`eval_harness.py`'s broad `except Exception` (a deliberate design,
unchanged) records `answer: None` for any API/network error, but
nothing downstream distinguished these infra-artifact rows from real
agent failures — exactly what inflated several questions' apparent
flakiness in this investigation's first pass. New standalone script,
`analyze_flakiness.py`, mirrors `analyze_citation_gate.py`'s
conventions with one deliberate deviation: its own loader tolerates
both this project's current dict-wrapped report format and 33 older
bare-list-format files (2026-08-14 through 2026-08-19) that would
otherwise crash `analyze_citation_gate.py`'s own unconditional
`report["results"]` access.

## Testing and verification

All three fixes are pure/deterministic given their inputs — full
red-green TDD, not the live-code manual-repro-script carve-out. Beyond
unit tests, `.claude/rules/live-eval-verification.md` (already covering
`agent.py`'s citation-verification functions) required a live
spot-check: `aapl-operating-margin-q3fy2026` re-run live against
Gemini, one run producing the exact inline-computation pattern
("computed as operating income of $35,695 million divided by total net
sales of $109,417 million") and passing cleanly with zero warnings — a
genuine live confirmation, not just a synthetic unit-test pass. A
separate live run's real citation-gate failure
(`nvda-crm-revenue-comparison`) incidentally confirmed Fix B: its saved
report now shows the actual claimed quote text for each failed check,
immediately surfacing a new, previously-invisible root cause (see
review file and `BACKLOG.md`). Full 47-question Gemini baseline: 40/47,
with all diffs versus the prior 41/47 baseline confirmed via the new
`analyze_flakiness.py` tool (and individual failure-reason inspection)
to be pre-existing, well-documented flakiness, not a regression.
