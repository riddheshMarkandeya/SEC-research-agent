# Citation-verification retry loop (revisited against swappable backends) — design

> Status: implemented and live-verified, 2026-08-25. Built
> backend-agnostic, live-verified against both backends (see Testing
> section's results below), then gated to Gemini only per the user's
> explicit decision after seeing the Ollama run: a single clean re-run
> didn't outweigh Week 5j's documented history for that backend, so
> `_CITATION_RETRY_BACKENDS = {"gemini"}` gates it in
> `_should_retry_for_citations()`.

## Motivation

Week 5j built and reverted this exact mechanism: when `run_agent()`'s
final answer had an unverified citation (per `verify_citations()`), feed
the model its own draft plus the warnings and let it retry once. The
mechanism triggered correctly and was capped at one retry as designed,
but `qwen2.5:7b-instruct` couldn't reliably act on the feedback —
`aapl-employees-fy25`'s retry gave up entirely instead of finding the
correct number among 4 other already-retrieved chunks, and
`crm-revenue-q1fy27`'s retry re-located the right passage but mislabeled
which citation index it belonged to. A first retry-message wording
("This is your final attempt — give a complete answer now") caused a
*worse* regression: the deadline framing pushed the model to fabricate
an estimated R&D figure on a previously-100%-reliable refusal question
(`nvda-rd-expense-q4fy26-refusal`). A second, reworded attempt (explicit
"an honest refusal is acceptable," "do not invent/estimate") reduced but
didn't fully fix that regression. Two fix attempts landing in the same
failure mode — same pattern as rule 8's own regression — was the
explicit trigger to stop guessing and revert, with a note to revisit
"once working with a more capable model."

The swappable-backend work (merged `863bf03`) is that model. Gemini
already produces fewer unverified citations with no retry loop at all
(2/27 vs. Ollama's 4/27, per `eval_results/20260821T025213Z.json`
/ `...T023051Z.json`), and generalizes the fix to every category of
local-model failure the project has found. Current live evidence for
*this* work specifically: the latest Gemini run still carries 2
warnings —

- `aapl-msft-tax-rate-comparison` — a real apparent misattribution: the
  answer states "$6,478 million" for Apple's tax provision, cited `[1]`,
  but `[1]`'s own text doesn't contain that number. This is the kind of
  case the retry loop should fix.
- `aapl-3yr-avg-operating-margin-fy2023-fy2025` — almost certainly
  checker noise, not a real claim: the answer's own phrase "3-year
  average" contributes the bare "3" that `_NON_CLAIM_PATTERN` doesn't
  strip (it only strips 4-digit years, not this). Documented here so
  this isn't mistaken for a target the retry mechanism is expected to
  resolve — it's an unrelated, already-known class of checker
  false-positive (see `agent.py`'s "known, accepted residual
  limitation" note).

## Out of scope

- `verify_citations()` / `value_is_citation_verified()` internals —
  untouched, already correct; this only adds a consumer of their output.
- More than one retry — matches Week 5j's cap; no evidence yet that a
  second retry would help, and each one costs a full live LLM round trip.
- A general "self-correct on any warning type" framework — scoped to
  citation warnings specifically, same as before.
- Fixing the `aapl-3yr-avg-operating-margin...` "3" false-positive —
  unrelated pre-existing checker-noise issue, not this design's job.

## Resolved: backend-agnostic build, gate Ollama out if evidence confirms it

Decided 2026-08-24: build `send_followup`/the retry branch
backend-agnostically (no special-case in the loop itself), live-verify
against **both** backends per the Testing section below, and add a
one-line gate (`if backend == "ollama": skip retry`) if Ollama actually
reproduces the old fabricate/give-up pattern — expected, based on Week
5j's history, but confirmed from this run's own evidence rather than
assumed from the prior one. Rationale: the shared-loop architecture
(`llm_backends.py`) has no clean capability signal to gate on besides
the backend name, and "the loop is identical regardless of which backend
is chosen" is the file's own stated design principle — so the gate, if
needed, belongs as a small, explicitly-justified exception added after
seeing the evidence, not built into the design up front.

## Architecture

### `llm_backends.py`

Add a third function per backend, `send_followup(state, text: str) ->
ModelTurn`, registered as the third element of each `BACKENDS` tuple
(`tuple[Callable, Callable, Callable]`). This is a genuinely new
capability `send_tool_results` can't express — a plain corrective
message, not a tool result — needed because the retry fires only after
the model has already stopped calling tools and produced a final answer.

- `_ollama_send_followup(state, text)`: append `{"role": "user",
  "content": text}` to `state["messages"]`, call `_ollama_call`, append
  the response, normalize via `_ollama_message_to_turn` — symmetric with
  `_ollama_send`.
- `_gemini_send_followup(state, text)`: `_send_with_retry(state, text)`
  — `chat.send_message` already accepts a plain string (this is exactly
  what `_gemini_start` does for the original question), so this reuses
  the existing retry-on-429/503 helper directly, then normalizes via
  `_gemini_response_to_turn`.

### `agent.py`

Two new pure, unit-tested helpers:

```python
def _should_retry_for_citations(citation_warnings: list[str], already_retried: bool) -> bool:
    return bool(citation_warnings) and not already_retried

def _format_citation_retry_message(answer: str, citation_warnings: list[str]) -> str:
    ...
```

`_format_citation_retry_message`'s wording directly targets Week 5j's two
documented failure modes:

- Explicitly tells the model to re-check the search results **already
  shown earlier in this conversation** for a valid supporting citation
  before concluding a value isn't supported — targets the
  "gave up instead of checking 4 already-retrieved chunks" failure.
  (The model still has full access to its own prior turns via
  conversation state; this just points it back at them instead of
  letting it assume nothing more is available.)
- Explicitly states that an honest "the sources shown don't support this
  claim" is a fully acceptable final answer.
- Explicitly forbids inventing, estimating, or approximating a
  replacement number.
- Deliberately contains **no** "final attempt" / deadline-pressure
  language — Week 5j root-caused that exact phrasing as the direct cause
  of a fabrication regression on a previously-reliable refusal question.
  A unit test asserts this phrasing is absent, as a standing regression
  guard.

`run_agent()`'s loop: when a turn has no tool calls (a final answer) and
`_should_retry_for_citations(...)` is true and the iteration budget
allows one more call, send the formatted retry message via
`send_followup` and loop back around — the resulting turn is handled by
the existing loop unchanged (it may itself contain tool calls, or another
final answer; either way the retry is capped at one attempt via a local
`retried` flag, shared against `MAX_TOOL_ITERATIONS` like every other
call).

## Error handling

None new. `send_followup` reuses each backend's existing transient-error
handling (`_send_with_retry`'s 429/503 backoff for Gemini) rather than
adding a second copy.

## Testing

Matches this project's established scope discipline and CLAUDE.md's TDD
carve-out (pure/deterministic logic gets full TDD; live model/network
calls are verified manually, not mocked):

- `tests/test_agent.py` (written first, before implementation):
  - `_should_retry_for_citations`: warnings + not-yet-retried → True;
    warnings + already-retried → False; no warnings → False regardless
    of the retried flag.
  - `_format_citation_retry_message`: contains each warning string;
    contains the previous answer text; contains language permitting a
    refusal; contains language forbidding invention/estimation; **does
    not** contain "final attempt" or equivalent deadline-pressure
    phrasing (regression guard for the exact Week 5j-diagnosed cause).
- `send_followup` (both backends) and `run_agent()`'s new retry branch:
  live-only, not unit tested directly — same convention as
  `_ollama_send`/`_gemini_send`/`_gemini_start` today (mocking a live
  LLM's corrective response would test the mock, not real model
  behavior).
- **Manual live verification** (the actual point of this work):
  1. Direct repro against the two current Gemini warnings: confirm
     `aapl-msft-tax-rate-comparison` gets either a corrected citation or
     an honest refusal instead of today's misattribution; confirm
     `aapl-3yr-avg-operating-margin...`'s "3" warning is unaffected
     either way (expected — it's unrelated checker noise, not a target).
  2. Full `eval_harness.py --backend gemini` re-run vs. the current
     baseline (`eval_results/20260821T025213Z.json`: 26/27, 2/27
     unverified) — expect the unverified count to drop, pass rate to
     hold or improve, no regressions.
  3. Full `eval_harness.py --backend ollama` re-run vs. its own baseline
     (`eval_results/20260821T023051Z.json`: 20/27) — checks whether the
     backend-agnostic retry reintroduces Week 5j's Ollama-specific
     fabricate/give-up failure even with the reworded message. If it
     does, add the one-line `backend == "ollama"` gate discussed above
     rather than reverting the whole mechanism again; if not, ship it
     backend-agnostic as built.

## Migration checklist

1. Add `send_followup` to both backends in `llm_backends.py`; extend
   `BACKENDS` tuples to 3-callables; update the one unpacking line in
   `agent.py`.
2. Write `_should_retry_for_citations` / `_format_citation_retry_message`
   tests first (TDD), confirm they fail, then implement both functions.
3. Wire the retry branch into `run_agent()`'s loop.
4. `pytest` full suite green.
5. Manual live verification per the Testing section (both backends);
   decide on the Ollama gate based on what that run actually shows.
6. Document the outcome in `PROJECT_CONTEXT.md` (new `###` section) and
   update "Next steps," regardless of whether the mechanism ships
   backend-agnostic, gated, or reverted again.
