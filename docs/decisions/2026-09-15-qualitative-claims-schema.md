# Fix the qualitative-claims placeholder-value false-refusal bug

**Date:** 2026-09-15

## Context

Eval baseline was 36/47 (76.6%) as of the 2026-09-14 run. Of the 11
failures, 3 (`aapl-ai-risk`, `crm-ai-risk`, `pltr-government-contract-risk`)
shared one root cause, confirmed directly against a real
`submit_answer` trace in `trace_logs/traces.jsonl` (run `7803e5daa727`):
on a purely qualitative question ("What risks does Apple describe
related to artificial intelligence?"), the model produced a good,
correctly cited, well-organized answer with no numbers in it at all —
but `SUBMIT_TOOL_SCHEMA`'s `claims` item schema required `value`/`unit`
on every entry, so the model invented a placeholder (`value: 1`) for
each qualitative bullet's citation. `_verify_one_claim` then correctly
rejected every claim (none of the quoted risk-factor paragraphs contain
a standalone "1"), and the all-or-nothing citation gate refused an
otherwise-correct answer. This exact shape recurred across two separate
baselines (2026-09-13 and 2026-09-14), making it a real recurring bug
class, not a one-off.

## Decision

Made `value`/`unit` optional in `SUBMIT_TOOL_SCHEMA`'s claims item
(keeping `citation_index`/`quote` required). A claim with no `value` is
now treated as qualitative and verified by checking its quote is
genuinely present in the cited source — no number-matching, since
there's none to match. `_verify_one_claim` was split into a dispatcher
plus `_verify_numeric_claim`/`_verify_qualitative_claim`, with a new
`malformed_claim` guard for a claim supplying only one of value/unit.
`CitationWarning.value`/`.unit` were widened to `Optional`. Both the
tool's schema description and system-prompt rule 9 were rewritten to
explain the new qualitative-claim shape explicitly.

Result: all 3 target questions pass cleanly (zero citation warnings),
confirmed via a targeted live re-run and directly inspecting the
resulting trace — the model now correctly omits `value`/`unit` for
qualitative claims. Full 47-question baseline: **37/47 (78.7%)**, up
from 36/47. The net gain is +1, not the fix's own +3, because 5
unrelated failures appeared elsewhere in this run (3 turn-budget
exhaustions on different questions, 2 new `uncovered_number` cases on
otherwise-correct numeric answers) while 3 previously-failing
turn-budget questions happened to pass this time — ordinary run-to-run
non-determinism in already-tracked, unrelated failure modes (see
`BACKLOG.md`'s `MAX_TOOL_ITERATIONS` item), not a regression from this
change. Logged the 2 new `uncovered_number` observations to
`BACKLOG.md` as a fresh, low-priority, not-yet-investigated finding
rather than silently dropping them.

## Why

Two fixes were possible (`BACKLOG.md` left this as an open fork): a
prompt-only fix (tell the model to omit qualitative citations from
`claims` entirely) or a schema fix (give qualitative claims a legal,
verified shape). Presented three real options via `AskUserQuestion`
(prompt-only; optional value/unit fields; a stricter JSON-Schema
`oneOf`) rather than picking unilaterally — the user chose optional
fields. Reasoning: (1) this project has already seen a prompt-only fix
fail to reliably change model behavior on a similar bug (the
3+-company ranking-routing issue, reverted after 4 failed wording
attempts) and has a demonstrated preference for closing a recurring
bug class at the code level instead; (2) a prompt-only fix would leave
qualitative citations completely unverified, while this fix gives them
a real grounding check they didn't have before (a fabricated
qualitative citation is now caught, not silently trusted); (3) `oneOf`
was rejected since this codebase uses no `oneOf`/`anyOf` in any tool
schema today and Gemini's function-calling schema translation is
already known to reject some standard JSON-Schema features
(`additionalProperties`) — building on another unverified, more exotic
schema feature was an avoidable risk. `dependentRequired` (value and
unit required together) was considered for the malformed-claim case for
the same reason, and also rejected for the same unverified-against-
Gemini risk; a per-claim runtime check was used instead.

An independent review of the plan (before implementation) found and
closed 3 real gaps the initial draft missed: a self-contradictory tool
description, warning messages that would have rendered literal
`"None (None)"` text, and a real `KeyError` crash risk from a claim
supplying only one of value/unit. A follow-up independent review (after
implementation) found and fixed one more: `verify_claims`'s own
docstring had gone stale relative to the new qualitative branch.

## Files touched

`agent.py` (`SUBMIT_TOOL_SCHEMA`, system prompt rule 9, `CitationWarning`,
`_verify_one_claim` split into `_verify_one_claim`/`_verify_numeric_claim`/
`_verify_qualitative_claim`, `verify_claims`), `tests/test_agent.py`
(9 new tests), `PROJECT_INDEX.md`, `BACKLOG.md`.

## Verification

Full `pytest` suite green (661 passed, up from 652 with the new tests).
`ruff`/`pyright` clean on every line this change added or modified.
Targeted live re-run (`eval_harness.py --backend gemini --ids
aapl-ai-risk,crm-ai-risk,pltr-government-contract-risk`): 3/3 pass, zero
citation warnings, real trace confirms the model omits value/unit as
instructed. Full 47-question baseline re-run: 37/47 (78.7%), the 3
target questions absent from the failure list. Independent review (plan
review before implementation, `/code-review` and a second independent
architecture/documentation pass after) found and fixed 4 real issues
total across both stages.

## Related

Supersedes the `[bug, Med, Standard]` placeholder-integer item in
`BACKLOG.md`'s "From the 2026-09-14 tool-turn-waste fix" section (now
deleted). Builds on
`docs/decisions/2026-09-10-structured-claims-citation-verification.md`'s
original `claims`-array design.
