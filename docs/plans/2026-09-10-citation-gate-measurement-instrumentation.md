# Instrument the citation hard gate for FP/FN measurement; demote Ollama to a secondary backend

## Context

`verify_citations()` (`agent.py:996`) hard-gates every answer: any warning and
`_finalize_answer()` (`agent.py:1179`) **discards the model's answer** and
returns a refusal. The uncited-claim half of that check
(`_iter_uncited_claims`, `_SENTENCE_BREAK`, the marker-attachment rule) took
five review rounds to stabilize (see
`docs/reviews/2026-09-09-citation-gap-frame-ordering-retrieval-verify.md`)
and carries 51 of the 150 tests in `tests/test_agent.py`.

The user asked whether there's a better way, and prior-art research says yes:
nobody else reconstructs claim→source attribution by parsing prose. Gemini
emits it as structured `groundingSupports` metadata; Vertex's Check Grounding
API and RAGAS both segment claims with a model. The intended direction is
model-emitted structured claims — a `submit_answer` tool whose parameter
schema *is* the claims array, since Gemini cannot combine `response_schema`
with function calling ("Function calling with a response mime type:
'application/json' is unsupported"), making a tool schema the officially
recommended structured-output mechanism.

**That is a later phase.** Before rewriting a hard gate we need to know how
often it is currently wrong, and in which direction — a false positive here
silently withholds a *correct* answer, and nothing records that it happened.
Planning already turned up one confirmed false positive by inspection (see
Finding 1), which is exactly the argument for measuring rather than reasoning.

This phase delivers: instrumentation that measures the gate against ground
truth, an analysis script, eval questions designed to stress it, and the
Gemini-default switch that makes running those measurements practical.

**Out of scope, deliberately — do not build:** the `submit_answer`
structured-claims tool, the model-based veto before refusal, and any change to
the verification *logic* itself. Fixing the instrument mid-measurement would
invalidate the measurement.

Backend decision made by the user during planning: **demote Ollama, don't
delete it.** The "runs against a local LLM with no API key" capability is
deliberately retained; it just stops being the default and stops being
routinely tested/developed against. This is a real change to
`PROJECT_CONTEXT.md`'s "no paid APIs required" hard constraint (line 12) and
is being made deliberately rather than by drift. Gemini free tier is
`gemini-flash-lite-latest` at 30 RPM / 1500 RPD; a full 41-question eval run
is ~205 calls, about 14% of one day's quota.

## Findings that shape this plan

1. **A live false-positive refusal exists today.** Verified by executing the
   real regex, not by reading it:
   `'Revenue was $5 billion, as reported under U.S. GAAP [1].'` yields a
   sentence break at index 45 — *between* the claim and its marker — so the
   claim reads as unreachable, gets flagged uncited, and the answer is
   refused. The comment at `agent.py:877-880` claims the lowercase exclusion
   fixed the `U.S.` problem; it only fixed the *lowercase* follow-on
   (`U.S. sales`). A **capitalized** follow-on (`U.S. GAAP`, `U.S. Treasury`)
   still breaks, and "U.S. GAAP" is ubiquitous in SEC-filing answers. Review
   round 3 fixed the whitespace variant of this bug and missed the
   capitalization variant.

   **Do not fix it in this phase.** Stress question 3 below is designed to
   trigger it, which makes it a known-ground-truth case: if the analyzer
   classifies it as a false positive, the analyzer works. Log it in
   `BACKLOG.md`; fix it after the baseline exists.

2. **`log_event` alone cannot measure FP/FN — logs have no ground truth.**
   `eval_harness.py` does (`expected_value`/`expected`). So classification
   must happen in the eval harness, not in a trace-log reader.

3. **The evidence needed to classify an FP only exists inside `run_eval`.**
   Classifying requires re-grading the withheld answer against the retrieved
   *chunk texts*; the report stores only `n_chunks_retrieved`. Storing chunk
   texts would grow each committed report from ~20 KB to ~600 KB. So classify
   in-process, persist the verdict, and aggregate from the report later.

4. **`--backend gemini` does not get you off Ollama today.** `grade_judged()`
   (`eval_harness.py:150-172`) calls `ollama_call()` unconditionally, so 12 of
   41 questions still need a live local Ollama. Fixing this is a precondition
   for demoting Ollama, not a nice-to-have.

5. **Flipping the default to Gemini also silently enables the corrective
   retry** (`_CITATION_RETRY_BACKENDS = {"gemini"}`, `agent.py:1111`). Every
   post-flip measurement is therefore of the gate *after* self-correction, not
   first-pass. Must be documented up front, not discovered later.

6. Verified counts for blast radius: exactly **5** tests monkeypatch
   `agent.verify_citations` (`tests/test_agent.py` lines 1819, 1855, 1875,
   1946, 1961), **3** `_finalize_answer` call sites (`agent.py` 1356, 1369,
   1371), and **11** `run_agent` unpack sites (8 in `tests/test_agent.py`,
   plus `eval_harness.py:254`, `agent.py:1388`,
   `tests/manual/verify_tracing.py:126`).

## Design decisions

**Warnings stay `list[str]` on the wire.** Add `CitationWarning` (NamedTuple:
`check`, `citation_index`, `value`, `unit`, `message`) and
`collect_citation_warnings()`; `verify_citations()` becomes
`[w.message for w in collect_citation_warnings(...)]`. Every warning string
stays byte-identical. This is non-negotiable because `_format_refusal_message`
and `_format_citation_retry_message` interpolate warnings into **prompt
text** — changing them would change model behavior, i.e. perturb the very
population being measured. `check` is tagged at construction (one literal per
`warnings.append` site); inferring it from wording would be exactly the
fragility we're trying to remove.

**`run_agent` returns an `AgentResult` NamedTuple** — `(answer, results,
citation_warnings, withheld_answer)` — matching the existing `ModelTurn` idiom
in `llm_backends.py`. `withheld_answer` is `None` unless the gate refused
(not a copy of `answer`), so it doubles as the gate-decision flag and doesn't
bloat passing rows. Any 4th element breaks unpacking regardless of type, so
prefer the one that reads well afterward. The gate is not weakened:
`agent.main()` uses `result.answer` only, and `mcp_server.py` never calls
`run_agent`.

Rejected: appending the withheld answer to the refusal text (that *is*
defeating the gate); a bare 4th positional `str` (invites grabbing the wrong
one); folding it into `citation_warnings` (that element is truthiness-tested,
iterated, `json.dump`ed, and joined into prompt text).

**`_finalize_answer` fires the log event**, since it is already the single
choke point every return site routes through — the same argument that made it
exist. New signature: `(answer, warnings, all_results, *, backend, retried)`,
keyword-only so the two flags can't be swapped positionally. Emits
`log_event("citation_gate_refused", backend=, retried=, n_results=,
checks={counts}, warnings=[...], withheld_answer=)`.

`withheld_answer` goes to `log_event` **only, never to a span** —
`traced_span` dual-writes to Langfuse and the whole point of withholding is
that this text isn't trustworthy; it should not leave the machine. For
symmetry on the pass path, add `"citation_checks": {counts}` to the existing
`span.update(output=...)` in `run_agent` rather than emitting a second
per-answer event.

**Measurement definitions** (numeric/comparison rows only; judged rows are
excluded — no ground-truth number):

- **FP** = gate refused **and** re-grading the withheld answer with the
  existing `grade_numeric`/`grade_comparison` returns `True`. Reusing the
  grader verbatim means "would have passed" keeps its established meaning.
- **FN candidate** = gate passed **and** `passed is False` **and**
  `has_citation is True`. The `has_citation` term separates "stated a cited
  number that isn't the right one" from "declined / retrieved nothing." Both
  terms already exist in the report; no new field needed.
- **Known asymmetry — report it rather than hide it:**
  `value_is_citation_verified` returns `True` when a value has no citation at
  all, so a correct-but-uncited value classifies as FP even though the
  uncited-check arguably refused it correctly. Break FPs down by `check`
  (`cited_claim_unsupported` vs `uncited_claim`) so the two populations stay
  separable. That breakdown is the main output of the whole campaign, since it
  says which of the two checks to rewrite first.

**`complete()` helper in `llm_backends.py`** for the judge:
`complete(backend, system_prompt, user_prompt, temperature=0.0) -> str`.
Rejected threading `temperature` through the 3-callable `BACKENDS` protocol
(6 signatures changed for one caller that never uses tools or a second turn),
and rejected accepting Gemini's hardcoded 0.1 (judge determinism is what makes
eval runs comparable across weeks, and this campaign depends on that). The
Ollama branch reuses the existing `ollama_call`, preserving its retry/backoff/
logging; the Gemini branch creates a chat with **no `tools=`** and reuses
`_send_with_retry` unchanged (it has 5 tests built around the
`chat.send_message` shape, so switching to `client.models.generate_content`
would force a refactor for no gain). Two-branch `if`/`elif` with a `ValueError`
on unknown — not a second parallel registry dict.

**`--judge-backend` defaults to the answer backend**, not to
`DEFAULT_BACKEND`. Otherwise `--backend ollama` (the no-API-key path we're
deliberately keeping) would silently demand a Gemini key for its 12 judged
questions, breaking the one capability the user asked to preserve.
Self-grading bias (Gemini judging Gemini) is the accepted price;
`--judge-backend ollama` remains the cross-model check and `save_report`
already records `judge_model` per run, so every report is self-describing
about which regime produced it. Document this in the `grade_judged` docstring
and in `PROJECT_CONTEXT.md` — don't let it become tribal knowledge.

**Stress questions live in a separate `eval/citation_stress_questions.jsonl`**,
run via the existing `--questions` flag. Zero code change, keeps the
41-question baseline comparable against the ~17 committed historical reports,
and stops questions *designed* to fail from contaminating the headline pass
rate. Consequence: the analyzer must accept multiple report paths.

## Files and ordered steps

Test first at every step; the pre-commit hook runs the full suite, so each
step must be green before the next.

**1. Structured warnings** — `agent.py`, `tests/test_agent.py`

Tests: `check`/`citation_index` tagged correctly for each of the two checks
(`int` vs `None`); plus
`verify_citations(...) == [w.message for w in collect_citation_warnings(...)]`
on an input producing both kinds. Then add `CitationWarning` +
`collect_citation_warnings`; reduce `verify_citations` to the one-line map.
Both dedup sets and both loops move verbatim. All ~29 existing
`verify_citations` tests must pass untouched.

**2. `AgentResult` + withheld answer + gate logging** — `agent.py`,
`tests/test_agent.py`, `tests/manual/verify_tracing.py`

Tests: `_finalize_answer` returns the withheld answer on refusal and `None` on
pass; fires `citation_gate_refused` with correct check counts (monkeypatch
`agent.log_event`); the span output contains no withheld text. Then implement,
and update the 11 unpack sites.

**Repoint the 5 tests that monkeypatch `agent.verify_citations` at
`collect_citation_warnings`** — once `_run_agent_impl` stops calling
`verify_citations`, those patches become silent no-ops that stay green while
testing nothing. Confirm each one *fails* when pointed at the wrong target.

**3. Eval harness gate fields** — `eval_harness.py`,
`tests/test_eval_harness.py`

Extend the existing `fake_run_agent` pattern (`tests/test_eval_harness.py:390`)
to return an `AgentResult` whose withheld answer contains the expected value
plus a supporting chunk; assert the row keeps `passed is False` (user-facing
verdict unchanged) but gains `gate_withheld_would_have_passed is True`. A
companion test with a wrong value asserts `False`. Then add four additive
report fields — `withheld_answer`, `gate_withheld_would_have_passed`,
`gate_withheld_detail`, `citation_warning_details` — populated only for refused
numeric/comparison rows.

`_grade`'s short-circuit at `eval_harness.py:233` is **untouched**; the gate
fields are purely additive evidence. `eval_harness` derives the structured
detail by calling `collect_citation_warnings(withheld_answer or answer_text,
retrieved)` rather than widening `AgentResult` again — a pure function of two
values it already holds.

**4. `analyze_citation_gate.py`** (new, pure, full TDD) +
`tests/test_analyze_citation_gate.py`

`classify_row()` over synthetic rows → `false_positive` / `true_positive` /
`false_negative_candidate` / `not_gate_attributable` / `excluded` (judged) /
`unknown_pre_instrumentation` for legacy rows missing the new keys. Legacy rows
must be excluded from denominators — not crash, and not counted as passes.
Then `summarize(rows)` → counts, rates, the FP-by-`check` breakdown, and the
offending question ids. CLI accepts N report paths.

Docstring must state that post-flip runs measure post-retry behavior
(Finding 5) and point at the existing `citation_retry` event in
`trace_logs/traces.jsonl` for the first-pass picture. Add a pointer line after
`Full report saved to ...` in `print_summary` — a `print`, not an import, so
the harness and analyzer stay uncoupled.

**5. `complete()` + judge backend** — `llm_backends.py`, `eval_harness.py`,
tests

Tests: `complete` passes `temperature=0.0` and empty tool schemas on the Ollama
branch (monkeypatch `ollama_call`); raises on an unknown backend;
`grade_judged` routes to the requested backend. The Gemini branch is live-only
— verify via `tests/manual/`, not a mocked SDK, per CLAUDE.md's carve-out.

Rewrite `test_save_report_records_judge_model_as_ollama_regardless_of_backend`
— it now asserts the wrong contract; this is an intentional behavior change,
not a regression. Extract `_model_name_for(backend)` and use it for both
`answer_model` and `judge_model`, removing the duplicated ternary.

**6. Flip the default** — `config.py:43` → `"gemini"`, `.env.example`, and the
three hardcoded `backend: str = "ollama"` defaults (`agent.py:1285`,
`agent.py:1297`, `eval_harness.py:245`) → `DEFAULT_BACKEND`. Both modules
already import it for their argparse defaults, so no new imports.

Test that `run_agent("q")` resolves via `DEFAULT_BACKEND` (a hardcoded
`"ollama"` would `KeyError` against a monkeypatched `BACKENDS`). No existing
test should need changing — if one does, understand it rather than silencing
it. Note the behavior change: `python agent.py "..."` now requires
`GEMINI_API_KEY`, for which `_get_gemini_client` already raises a clear
`RuntimeError`.

**7. Citation-stress questions** — new `eval/citation_stress_questions.jsonl`

Four shapes:

- **Self-computed ratio, no supporting tool** → drives `_iter_uncited_claims`.
  Must be a ratio *not* in `formulas.RATIO_DEFINITIONS`. Proposed: R&D expense
  as a percentage of gross profit — both legs are in `DEFAULT_METRIC_TAGS` so
  the model can fetch them, but nothing computes the ratio, forcing
  self-computation.
- **Several grounded numbers under one trailing citation** → the FP direction
  for `_iter_citation_claims`' flat backward window. Use a `comparison`-type
  question over a segment-revenue table; reuse figures already verified inside
  existing `judged` questions' `criteria` fields rather than re-researching.
- **Abbreviation-induced false break** → per Finding 1, the abbreviation must
  sit **between the number and its marker**, e.g. `"...revenue was $X million,
  as reported under U.S. GAAP [1]."` Phrase the question so the model echoes
  the standard *after* the figure. **Verify the live answer actually has that
  shape before committing the question** — if the model puts "U.S. GAAP"
  first, the question tests nothing.
- **Date-heavy answer** → `_NON_CLAIM_PATTERN` noise (its own comment records
  12 warnings on one answer, 11 of them date noise). A two-period comparison
  forcing two full `Month D, YYYY` dates plus two figures, exercising both the
  month-name rule and the bare-`(19|20)\d{2}` rule.

Ground truth: **do not invent figures.** For `DEFAULT_METRIC_TAGS` metrics use
`xbrl_facts.get_metric(...)` (with `period_end_date=` when the question names a
calendar date — that's what `_pick_entry_by_end_date` exists for); for untagged
values (employee counts, segment revenue) read the real chunk via
`retrieval.hybrid_search`, the same procedure that produced
`aapl-employees-fy25`. Record metric, period, form, and accession in the
`PROJECT_CONTEXT.md` entry — JSONL has no comment syntax. Grading tolerance is
`max(1% × expected, 0.05)`, so round expected values the way the model would
state them. Per the live-code carve-out, run each question live once before
committing it, and write down what it did — a stress question that doesn't
reproduce its intended shape is worthless.

**8. Measurement run + docs** — see Verification and Documentation below.

## Verification

- Full suite green at every step (`python -m pytest -q`), 464 passing as the
  floor.
- Steps 1, 3, 4, and the pure halves of 5/6 are deterministic → real TDD, red
  first.
- Live-only paths get manual verification, not mocks: `complete()` on Gemini,
  and each new stress question run individually and written down.
- Baseline run: `python eval_harness.py --backend gemini` (41 questions) and
  `python eval_harness.py --questions eval/citation_stress_questions.jsonl
  --backend gemini`, then `python analyze_citation_gate.py` over both reports.
- **Self-validating acceptance test:** stress question 3 targets the Finding 1
  bug, which is confirmed by direct regex execution. If the analyzer does not
  classify it as a false positive, the instrumentation is wrong. This is the
  acceptance test for the whole measurement apparatus.
- Confirm `python eval_harness.py --backend gemini` completes with **no Ollama
  running** (Finding 4), and that `--backend ollama --judge-backend ollama`
  still works with no API key.
- Free-tier headroom: `gemini-flash-lite-latest` is 30 RPM / 1500 RPD; a
  41-question run is ~205 calls (~14% of daily quota). RPM is the only
  pressure and `_send_with_retry` already handles 429s.

## Documentation

- `PROJECT_CONTEXT.md`: one `###` section — the instrumentation, the backend
  demotion and its self-grading-bias caveat, the FP/FN definitions including
  the correct-but-uncited asymmetry, and the first measured numbers.
- `CLAUDE.md`: the step-7 workflow currently implies dual-backend spot-checks;
  narrow that to Gemini, noting Ollama remains supported but is no longer
  routinely tested.
- `BACKLOG.md`:
  - (a) the Finding 1 `U.S. GAAP` false positive — `[bug, High, Standard]`,
    with the repro string;
  - (b) structured-claims `submit_answer` phase — `[feature, Med, Substantial]`;
  - (c) model-based veto before refusal, gated on the measured FP rate —
    `[feature, Low, Standard]`;
  - (d) no reader for `traces.jsonl` — `[test-coverage, Low, Standard]`;
  - (e) the correct-but-uncited FP definitional question —
    `[design, Med, Standard]`.
- Run the two-pass review per CLAUDE.md step 7 and file
  `docs/reviews/2026-09-10-citation-gate-measurement-instrumentation.md`.

## Nothing here forecloses the next phase

`CitationWarning.check` is an open string vocabulary a fuzzy quote-match check
can extend; `withheld_answer` is exactly the input a model-based veto would
judge; and `classify_row`/`summarize` become the before/after yardstick for
whatever replaces the gate. The user's decision on quote-vs-chunk matching for
that phase, recorded here so it isn't relitigated: **fuzzy match, then
refuse** — normalize whitespace/casing and allow a similarity threshold, since
models paraphrase and re-wrap filing-table text constantly and an
exact-substring requirement on a hard gate would refuse a large share of
correct answers.
