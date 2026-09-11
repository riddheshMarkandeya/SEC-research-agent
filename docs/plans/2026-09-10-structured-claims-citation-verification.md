# Replace the prose citation heuristic with model-emitted structured claims

## Context

The 2026-09-10 measurement campaign (`docs/plans/2026-09-10-citation-gate-measurement-instrumentation.md`,
`docs/reviews/` and `PROJECT_CONTEXT.md` of the same name) found that `agent.py`'s citation hard gate —
which regex-parses `[n]` markers out of free-text prose to reconstruct which numeric claim maps to which
source (`verify_citations()`/`collect_citation_warnings()`, agent.py ~834-1000) — fired 4 times across 45
real questions, and **all 4 were false positives**: a correct answer wrongly withheld, zero times catching
a genuinely bad one. Each traces to a specific regex/parsing limitation, all filed in `BACKLOG.md`:
a capitalized-abbreviation sentence-break bug (`U.S. GAAP`), a footnote-reference noise pattern (`"Note 1"`),
a citation-marker format blind spot (`[1, 5]` not recognized as a marker at all), and an ordinal-phrase
noise pattern (`"3-year"`). The conclusion recorded then: this isn't a heuristic worth patching bug-by-bug
anymore — replace prose-then-parse with the model emitting structured claims directly, via a `submit_answer`
tool whose parameter schema *is* the claims array (Gemini can't combine `response_schema` with function
calling, so a tool schema is the mechanism). This plan builds that replacement, plus the directly-related
BACKLOG items it resolves, obsoletes, or reshapes.

**Two decisions already made** (confirmed via `AskUserQuestion`): the prose-fallback path (kept as a
universal safety net — see below) keeps hard-gating rather than downgrading to warn-only; the model-based
veto BACKLOG item is deferred until after this redesign is measured, not built now — walking through the
4 measured false positives individually, all 4 either die structurally under this redesign or are fixed
directly by it, so there's no evidence yet that a veto is needed.

**Prior art / two facts that shape the whole design**, verified live against the installed SDKs this
session (not assumed from docs):
- **Gemini can genuinely force a specific tool call.** `google-genai` 2.18.1's `types.GenerateContentConfig.tool_config
  = types.ToolConfig(function_calling_config=types.FunctionCallingConfig(mode="ANY",
  allowed_function_names=["submit_answer"]))` is a hard constraint, not a bias — confirmed against the SDK's
  own field docs. But `Chat.send_message(config=...)` **replaces** the chat's config wholesale
  (`method_config = config if config else self._config`, verified by reading `google/genai/chats.py` directly) —
  it does not merge, so a forced turn must re-supply `tools`/`system_instruction`/`temperature` too, not just
  `tool_config`.
- **Ollama has no forcing mechanism at all** (`tool_choice` unsupported/ignored, confirmed via Ollama's own
  docs and GitHub issues #8421/#11171), and qwen2.5-class models are documented (ollama#7051 and others) to
  sometimes emit tool-call-shaped JSON as **plain assistant text** instead of using the tool-calling channel —
  i.e. it can bypass structured output by construction-mismatch, not just by choice.

## Design decisions

**Offer `submit_answer` as a 4th tool to BOTH backends from turn 1 under AUTO mode; force `ANY` (Gemini
only) only if the model replies with text instead of calling any tool.** This is the existing
`not turn.tool_calls` branch — nothing new to detect. Rejected forcing on every turn (costs +1 round trip
on every question, and asks the model to re-derive structured claims from prose it already committed to —
relocating the exact parsing problem being eliminated, just inside the model). The decisive reason for
offering it to Ollama too, not gating tool availability by backend: **the prose fallback can't be deleted
regardless** — Gemini's own `ANY` mode is documented to occasionally still return text, and the forced
follow-up can itself fail or exhaust the iteration budget. Once the fallback must exist for Gemini anyway,
gating Ollama out of the structured path buys nothing and would be the first place `agent.py` branches on
backend for *capability* rather than *policy* — every existing backend gate (`_CITATION_RETRY_BACKENDS`,
`complete()`) is policy, not capability, and `llm_backends.py`'s module docstring states backend-agnosticism
as a deliberate invariant.

**Consequence for the 4 regex-bug BACKLOG items: deprioritized, not obsoleted.** The prose pipeline
(`verify_citations`, `collect_citation_warnings`, `_iter_citation_claims`, `_iter_uncited_claims`,
`_SENTENCE_BREAK`) stays exactly as-is as the fallback path for both backends — none of its ~37 existing
tests need to change. The `U.S. GAAP` sentence-break and `[1, 5]` marker bugs become fallback-path-only
(drop priority, since Gemini should rarely take that path) — leave them in `BACKLOG.md`, don't fix now.
The `"3-year"` and `"Note 1"` noise patterns get fixed as part of this work anyway, because the *new*
coverage cross-check (below) inherits the same noise problem and a much better fix exists for free (see
next section) — so add the two Trivial regex patterns as a small bonus while touching that code.

**`submit_answer` schema** — same `{"type":"function","function":{...}}` envelope every existing tool
uses, so `validate_tool_args()` (agent.py:445-536) is reusable verbatim with zero changes to that function:

```python
SUBMIT_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "submit_answer",
        "description": "...",
        "parameters": {
            "type": "object",
            "properties": {
                "answer_text": {"type": "string"},
                "claims": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "value": {"type": "number"},
                            "unit": {"type": "string", "enum": ["raw", "thousand", "million", "billion", "percent"]},
                            "citation_index": {"type": "integer"},
                            "quote": {"type": "string"},
                        },
                        "required": ["value", "unit", "citation_index", "quote"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["answer_text", "claims"],
            "additionalProperties": False,
        },
    },
}
```

`unit`'s enum is exactly `numeric_utils.normalize()`'s existing vocabulary — `normalize(claim["value"],
claim["unit"])` consumes it with zero translation, so `numeric_utils.py` needs no changes at all. `claims: []`
must stay legal (no `minItems`) — a refusal with zero numeric claims is a valid answer, and this is what
resolves the `value_is_citation_verified` "no citation = verified" design-question BACKLOG item *at the gate*
without touching that function: empty claims + numberless prose passes; empty claims + a number in the prose
fails coverage. **Critical wire-format fix needed first**: `_to_gemini_tool()` (llm_backends.py:232-253)
strips `additionalProperties` only at the top level of `parameters` (`{k: v for k, v in
fn["parameters"].items() if k != "additionalProperties"}`) — `claims.items.additionalProperties` would
reach Gemini unstripped and reproduce the exact live `400 INVALID_ARGUMENT` that function's own docstring
already documents fixing once. The strip must become recursive. Verified directly against the current file,
not assumed — this is the single most likely thing to break on first live run if missed.

**Verification: three checks, all reusing existing project machinery.**

1. **Quote grounding** (fuzzy, stdlib-only — `difflib.SequenceMatcher`, already how this project prefers to
   avoid new dependencies for a problem a few lines of stdlib solves). Normalize both source and quote via
   `unicodedata.normalize("NFKC", ...)` + casefold + collapsed whitespace (kills curly quotes/en-dashes Gemini
   re-renders). Exact-substring fast path, else a **coverage** ratio — `sum(block.size for block in
   get_matching_blocks()) / len(quote)` — not `SequenceMatcher.ratio()`, which scores a short quote against a
   long chunk near zero even on exact containment; coverage is the right relation for "is the quote *in* the
   source." Threshold ~0.90 plus a longest-contiguous-block floor (guards against a fabricated quote assembled
   from scattered real words inflating coverage via a common subsequence). **`autojunk=False` is mandatory** —
   `SequenceMatcher`'s autojunk heuristic activates above ~200 characters and can silently collapse a real
   match against filing-chunk-length text; this needs its own regression test. Reject quotes below ~15
   normalized characters (a 2-character quote matches everything).
2. **Value attribution** — generalize the existing `_source_number_candidates(text)` (agent.py) into
   `_number_candidates(text, *, unit_source=None)`, reinterpreting bare numbers in `text` under a unit word
   found in `unit_source` (defaulting to `text`, preserving today's Ollama-path behavior byte-for-byte).
   Then check the claim's `(value, unit)` appears among `_number_candidates(claim["quote"],
   unit_source=all_results[n-1]["text"])`. Routing the caption-unit leniency through `unit_source` keeps the
   documented live `crm-rpo-fy26` fix (a bare `$72.4` under an "(in billions)" table caption) working
   unchanged. This is strictly stronger than today's check too: it verifies the value is in the *quoted
   sentence*, not just somewhere in the whole chunk — closing a wrong-period-substitution gap
   (system-prompt rule 5) the old chunk-wide check couldn't see.
3. **Coverage cross-check** — scan `answer_text` for numbers (`numeric_utils.extract_numbers()`, no new mode
   needed) and require each to match some claim's normalized `(value, unit)`. **New noise-filter rule,
   better than pattern-whack-a-mole**: a number that appears in the *question itself* is not a claim the
   agent is asserting — `_run_agent_impl` already has `question` in scope. This one rule kills `"3-year"`
   (echoed from "3-year average operating margin"), most date/fiscal-year echoes, and similar noise at once.
   Keep `_NON_CLAIM_PATTERN` as a second layer and add the `Note N` and `N-year`/`N-day` patterns from
   BACKLOG while touching this code (Trivial, and now protects a check that's on the hot path). Accepted
   tradeoff: if a user asks "was revenue $50 billion?" and the model answers "yes" with no claim, the
   question-echo rule lets it through uncovered — a deliberate backstop-against-omission choice, not a second
   grounding check, favored over reintroducing a noise-pattern class.

**Failure vocabulary reuses `CitationWarning` verbatim** (agent.py, added this session) with a new closed
`check` set: `citation_out_of_range` · `quote_too_short` · `quote_not_found` · `value_not_in_quote` ·
`uncovered_number` · `no_structured_answer`. This is what keeps `analyze_citation_gate.py` needing zero
changes (see below) and gives its `false_positive_by_check` breakdown five named causes instead of two.
One related fix: today `_iter_citation_claims` silently *ignores* an out-of-range citation index (treated as
fine); the new check makes it an explicit `citation_out_of_range` failure instead.

**Loop control flow** — `_run_agent_impl` (agent.py:1435-1520) restructures around a new
`_partition_submit_call(tool_calls) -> (dict | None, list[dict])`:

```
while True:
    submit, other = _partition_submit_call(turn.tool_calls)
    if submit is not None and not other:
        -> verify claims; retry once if it fails and backend is gemini; else _finalize_answer
    if not turn.tool_calls:
        -> gemini: one forced ANY+submit_answer-only follow-up turn; ollama: prose fallback (today's path, unchanged)
    if calls_made >= MAX_TOOL_ITERATIONS:
        break
    -> dispatch `other`, send results  (mixed submit_answer + search in one turn: dispatch the searches,
       return a tool-result telling the model to resubmit once it's read them — it can't have grounded
       claims in results it hasn't seen yet)
```

**Critical ordering fix**: the terminal-submit check must run *before* the `calls_made >= MAX_TOOL_ITERATIONS`
cap check. Today's cap check runs after the `not turn.tool_calls` branch, which is fine today because a
final answer is always *text* and gets handled in that first branch. Once a final answer can arrive as a
`submit_answer` tool call (which is non-empty `tool_calls`, so the first branch doesn't fire), a submission
on the last allowed round trip would otherwise be silently discarded and replaced by the generic timeout
message — verified as a real bug against the actual current code, not hypothetical.

`_dispatch_tool_call`'s `-> str` return type stays **unchanged** — no `str | Terminal` union invented just
to encode termination; the loop itself knows which call is submit_answer via the partition step.
`MAX_TOOL_ITERATIONS` stays at 6 — the happy path costs the same as today (the turn spent on `submit_answer`
replaces the turn that would've been spent on prose), so bumping it now would confound the before/after
comparison; revisit only if the re-measurement shows real budget pressure.

**Wire-format changes needed in `llm_backends.py`** to support the forced follow-up (internal only —
`agent.py` still treats backend `state` as opaque, per the existing invariant):
- `_gemini_start` must return the chat's `config` alongside the chat object (today it's discarded — `state`
  is the bare `chat`), since a forced turn needs to re-supply the *whole* config, not just `tool_config`
  (confirmed: `send_message(config=...)` replaces, not merges).
- `_send_with_retry(chat, message)` gains an optional `config` parameter.
- `_ollama_send`/`_ollama_send_followup`/`_gemini_send`/`_gemini_send_followup` gain a keyword-only
  `force_tool: str | None = None`. Gemini builds the forced `tool_config`; Ollama's docstring documents that
  the parameter is accepted but has no effect (no `tool_choice` support at all, per the verified GitHub
  issues) — the caller doesn't need a backend-specific branch to know whether forcing is possible.

**Retry mechanism — deliver as a tool result, not a user turn; delete `pre_retry_answer` rather than fix
it.** When claim verification fails, send `types.Part.from_function_response(name="submit_answer",
response={"result": feedback})` — exactly what `send_tool_results` already does, so this needs zero new
plumbing and keeps the chat history well-formed (a dangling function call followed by a bare user turn has
historically 400'd on Gemini). `_format_claim_retry_message(failures)` names each failing claim concretely
("you claimed 215938 million citing [3], but the quoted text doesn't appear in source [3]") and reuses,
via an extracted shared constant, the three hard-won properties of the existing
`_format_citation_retry_message`: point back at results already shown, no deadline/final-attempt framing,
honest refusal explicitly acceptable, inventing a replacement number explicitly forbidden. Gated by the
existing `_CITATION_RETRY_BACKENDS = {"gemini"}` (no new set). **`pre_retry_answer`'s existing staleness bug
(BACKLOG, `_run_agent_impl`'s retry fallback pairing stale warnings with a grown `all_results`) is closed
structurally, not patched**: cache the raw `submit_args` instead of pre-computed warnings, and re-verify
against the *current* `all_results` at the exhausted-budget fallback site — a pure function of
`(submit_args, all_results)` can't go stale the way a cached warnings list could. Remove that BACKLOG item
with a `PROJECT_CONTEXT.md` note once done, per CLAUDE.md step 6.

**`AgentResult` gains a 5th field: `citation_warning_details: list[dict]`**, populated by `_finalize_answer`
from the `CitationWarning`s it already holds (`[w._asdict() for w in warnings]`) — the four existing fields
(`answer`, `results`, `citation_warnings: list[str]`, `withheld_answer`) keep their exact current semantics.
This is required, not optional: without it, `eval_harness._citation_gate_evidence()` (which currently
re-derives `citation_warning_details` by calling `collect_citation_warnings()` — the *prose* checker — on
`withheld_answer`) would silently disagree with whatever actually refused a structured-path answer, leaving
`analyze_citation_gate.summarize()`'s `false_positive_by_check` empty on exactly the rows the campaign exists
to explain. With the 5th field, `_citation_gate_evidence` consumes it directly instead of re-deriving, drops
its `collect_citation_warnings` import, and **`analyze_citation_gate.py` needs zero changes** — new failures
serialize into the same `CitationWarning`/dict shape with the same `check` key, so the exact same 45-question
campaign and script re-run and compare directly. `run_agent`'s span logging (agent.py, currently re-deriving
`citation_checks` via its own `collect_citation_warnings` call as a documented tradeoff) also switches to the
5th field, removing that redundant regex pass. Two call sites currently 4-tuple-unpack `run_agent()` and
must switch to attribute access instead (`agent.main()`, `eval_harness.py`'s `run_eval`) — more robust to
future fields than positional unpacking, and consistent with how `result.withheld_answer` is already read.

**Citation markers stay in `answer_text`, model-written, purely cosmetic — not rendered programmatically.**
The claims array carries no character offsets into `answer_text`, so programmatic rendering means inferring
marker position in prose — the exact problem being eliminated, moved to the output side. Keeps
`eval_harness.CITATION_PATTERN`-based `has_citation` and `value_is_citation_verified` measuring the same
thing before and after, so the re-run campaign compares like with like (this matters concretely:
`has_citation` feeds `classify_row`'s `false_negative_candidate` branch). A wrong or missing marker now
breaks nothing — that's the point of moving verification off of them entirely. System-prompt rules 1 and 8
stay, reframed as reader-facing formatting guidance; add a rule stating `submit_answer` is the only way to
deliver a final answer and every number in `answer_text` should have a matching claim.

## Files and ordered steps

Test first per CLAUDE.md: pure logic gets full red/green TDD; live-only paths get a
`tests/manual/verify_*.py` script, not a mock. Full suite must stay green at every step (495 passing as the
floor).

**Phase A — unblock the wire format (highest-risk unknowns, do first)**

1. **`llm_backends.py`: recursive `additionalProperties` strip.** Red test: a schema with a nested
   `items.additionalProperties` still carries it through `_to_gemini_tool` today. Fix: make the strip
   recurse over dicts/lists instead of one top-level dict comprehension.
2. **`llm_backends.py`: Gemini state carries its config.** `_gemini_start` returns `{"chat": chat, "config":
   config}` instead of the bare chat object; update `_gemini_send`/`_gemini_send_followup` to read from it.
   Purely internal (agent.py still sees opaque `state`). Existing Gemini tests in `tests/test_llm_backends.py`
   must stay green; add one asserting the config round-trips through state.
3. **`llm_backends.py`: `force_tool` support.** `_send_with_retry` gains an optional `config` param; the four
   `*_send*` functions gain keyword-only `force_tool: str | None = None`. Red test: a fake chat object
   capturing the config passed to it, asserting `tools`/`system_instruction`/`temperature`/`tool_config` are
   ALL present on a forced turn (this is the regression test for the replace-not-merge finding).

**Phase B — the verifier (pure logic, full TDD, `agent.py` + `tests/test_agent.py`)**

4. **`SUBMIT_TOOL_SCHEMA` + `validate_tool_args` acceptance.** Tests: valid payload accepted; `claims: []`
   accepted; missing `quote` rejected; invented per-claim key rejected; bad `unit` enum rejected;
   non-integer `citation_index` rejected. Confirm `mcp_server._TOOL_SCHEMAS` (explicit 3-tuple) still
   excludes it deliberately.
5. **`_normalize_for_match` + `_quote_matches`.** Tests: exact-modulo-whitespace; NFKC curly-quote/en-dash
   normalization; a realistic paraphrase above threshold; unrelated text below threshold; short-quote
   rejection; and the **autojunk regression** (a >200-char source containing the quote verbatim must still
   match — fails silently if `autojunk=False` is forgotten).
6. **`_number_candidates(text, *, unit_source=None)`.** Tests: caption-unit reinterpretation via
   `unit_source` (the `crm-rpo-fy26` case); a same-sentence wrong-period substitution fails
   `value_not_in_quote`; an equivalence test asserting old `_source_number_candidates(t)` callers behave
   byte-identically (proves the Ollama prose path is untouched).
7. **`verify_claims(claims, all_results, question, answer_text) -> list[CitationWarning]`.** Tests: empty
   claims + empty answer passes; each of the six new `check` values individually; the `crm-rpo-fy26` caption
   case still passes; coverage check catches an omitted number; question-echo covers `"3-year"`-shaped
   noise; `Note 1` and existing date/year/`10-K` noise still filtered (add the two new `_NON_CLAIM_PATTERN`
   entries here).

**Phase C — the loop**

8. **`tests/manual/verify_submit_answer.py`** (live-code carve-out — write and run *before* the loop
   rewrite, since its result decides whether the AUTO-first assumption holds in practice). Checks: Gemini
   honors forced `ANY`+`allowed_function_names` (print the raw turn); Gemini spontaneously chooses
   `submit_answer` under AUTO without forcing; Ollama offered all 4 tools — record which of {calls it
   correctly, emits tool-call-shaped JSON as plain text, answers in ordinary prose} it actually does.
9. **`_partition_submit_call` + loop restructure.** Red test first for the ordering bug: a fake backend
   returning `submit_answer` on the 6th round trip must not fall through to the timeout message. Then: mixed
   submit+search turn handling; text-only reply triggers the forced follow-up on gemini and the prose
   fallback (unchanged) on ollama; the prose fallback still hard-gates correctly (per the confirmed
   decision). Reuse the existing fake-backend test harness already in `tests/test_agent.py`.
10. **Retry path.** `_format_claim_retry_message` + shared wording constant (repoint the existing
    `_format_citation_retry_message` property tests at the shared constant so one set covers both messages).
    Delete `pre_retry_answer`; cache `submit_args`; re-verify against current `all_results` at the
    exhausted-budget site. Regression test: a retry turn that appends to `all_results` before exhausting the
    budget re-verifies against the grown list, not stale warnings — this closes the BACKLOG staleness item.
11. **`AgentResult`'s 5th field.** `_finalize_answer` populates `citation_warning_details`; `run_agent`'s
    span consumes it instead of re-deriving; `agent.main()` and `eval_harness.py`'s `run_eval` switch from
    tuple-unpacking to attribute access; `_citation_gate_evidence` consumes the field directly, dropping its
    `collect_citation_warnings` import. Test: `analyze_citation_gate.summarize()` produces a non-empty
    `false_positive_by_check` on a synthetic structured-refusal row (pure test, existing test file).
12. **System prompt update, `BACKLOG.md`/`PROJECT_CONTEXT.md` housekeeping, then the live re-measurement**:
    `eval_harness.py --backend gemini` over the 41 baseline questions and the 4 existing stress questions,
    then `analyze_citation_gate.py` on both new reports, compared directly against `20260910T212525Z.json` /
    `20260910T211730Z.json` (the pre-redesign baseline). Update the two-pass review per CLAUDE.md step 7.

**BACKLOG.md housekeeping to land in step 12**: remove the `pre_retry_answer` staleness item (closed
structurally) and the `value_is_citation_verified` "no citation = verified" item (resolved at the gate by
`claims: []` being explicitly legal) with `PROJECT_CONTEXT.md` notes; downgrade the `U.S. GAAP` and
`[1, 5]`-marker regex bugs to fallback-path-only (still real, lower priority); fix the `"3-year"`/`Note N`
noise patterns directly (folded into step 7); update the veto item's sizing note to point at fresh
post-redesign numbers instead of the old ones, per the confirmed decision to defer it; note that the 4
existing stress questions in `eval/citation_stress_questions.jsonl` were purpose-built for the old regex
bugs and 2 of them will now pass trivially (good acceptance evidence, but they stop being stress tests for
this system) — file a new backlog item for stress questions targeting the *new* failure modes (a heavily
paraphrased quote near the coverage threshold, a number in prose omitted from `claims`, a chunk with both
the asked-for period and a prior period).

## Verification

- Full suite green at every step; ~35 new tests, ~10 existing ones updated (5-field `AgentResult`, the
  deleted `pre_retry_answer` test rewritten, the repointed retry-message property tests), **zero of the
  ~37 existing prose-verification tests need to change** — the fallback path they cover is untouched.
- Phase A is the highest-risk, do-first section: both the config-replace-not-merge behavior and the
  recursive-strip requirement are independently verified against the actual installed SDK/current code this
  session, not assumed from docs — but the *forced-turn-actually-works-live* claim still needs step 8's
  live run before the loop rewrite depends on it.
- Live verification, no mocks, per the carve-out: `tests/manual/verify_submit_answer.py` (step 8) confirms
  Gemini's forcing mechanism and records Ollama's actual real-world behavior when offered the new tool.
- The acceptance test for the whole redesign: re-run the exact same 45-question corpus
  (`eval_harness.py --backend gemini`, baseline + stress) and confirm via `analyze_citation_gate.py` (zero
  code changes needed) that the false-positive rate drops from the measured 100% — specifically that
  `nvda-revenue-fy26-us-gaap` and `crm-buyback-and-liquidity-q1fy27` (the two structurally-eliminated causes)
  now pass cleanly, and that `aapl-3yr-avg-operating-margin-fy2023-fy2025` resolves as a true negative
  (correctly grounded, not refused) rather than the prior false positive.
- Confirm the prose fallback path is actually rarely taken by Gemini in the re-measurement (informs whether
  the "keep hard-gating" decision needs revisiting later — not now).
