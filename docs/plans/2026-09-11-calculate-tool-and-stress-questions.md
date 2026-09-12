# A verifiable `calculate` tool, plus new citation-gate stress questions

## Context

Two related asks: (1) add more eval questions that actually stress the new
structured-claims citation verifier (`docs/plans/2026-09-10-structured-claims-citation-verification.md`,
committed as `a1ecb56`), and (2) decide whether the old prose-based fallback
checker's 2 known bugs are worth fixing now.

**Decision on (2), already made**: deprioritize both to lowest. The last
full measurement found 0/45 gate fires took the fallback path at all —
Ollama (the only backend that always uses it) is already a demoted
secondary backend, and Gemini's forced-submit mechanism means it almost
never falls back. No code change needed; `BACKLOG.md`'s existing Low/Standard
tags for both items already reflect this, confirmed correct as-is.

While designing new stress questions for (1), a real, more important problem
surfaced: **system-prompt rule 9 tells the model to verify a hand-computed
value (a ratio the formula registry doesn't cover) by quoting the raw inputs
it came from — but `_verify_one_claim`'s value-attribution check always
requires the claimed value itself to appear as a number *inside* the quote.**
Confirmed directly against the code (`agent.py:1425-1433`): a claim's quote is
run through `_number_candidates()` and the claim's own `value` must appear
there — quoting two raw inputs never produces a candidate equal to their
ratio. So *any* claim following rule 9's own guidance for a computed value is
guaranteed to fail with `value_not_in_quote`. This isn't a pre-existing known
issue — rule 9 was written and committed this session — and it explains all 3
self-computed-ratio refusals observed in testing (`aapl-rd-pct-gross-profit-fy2025`,
`msft-cash-to-assets-fy2025`, and the earlier NVIDIA `yoy_growth` regression).

Discussed with the user, including prior-art research (see below): confirmed
via `AskUserQuestion` to fix this with a new `calculate` tool (not a
"compute claim" schema extension), and to keep it as a fallback alongside
the existing formula registry rather than replacing it. This plan covers
both the `calculate` tool and the new stress questions.

## Prior art (researched, not assumed)

- **RAGAS faithfulness, Anthropic's Citations API, Google's Grounding
  API** — all confirmed via search to be span/quote-grounding only. Claude's
  Citations API explicitly requires citing "content it draws from directly";
  none of these have any notion of a verifiably-derived number. Adopting a
  more generic "attribution" framework would not have solved this — it's a
  known gap in that whole class of technique.
- **FinQA / ConvFinQA / TAT-QA** (financial numerical-reasoning QA
  benchmarks) solve exactly this: the model (or annotator) emits an explicit
  **program** — an operation (add/subtract/divide/...) over **operands**,
  each of which must trace back to a real extracted number — and a verifier
  mechanically re-executes the program and checks the operands' provenance.
  This is the "compute claim" idea, and it's established, not novel.
- **PAL (Program-Aided Language Models) / Toolformer**: LLMs are unreliable
  at actual arithmetic even when they pick the right operation; the fix is to
  offload the *calculation itself* to a real interpreter/tool rather than
  trust the model's mental math. PAL: ~72% vs 55–65% for chain-of-thought on
  GSM8K, specifically from removing arithmetic execution from the LLM's job.
- **Synthesis for this codebase**: this project's tool-calling loop already
  has the exact right shape for the PAL/Toolformer pattern — `get_financial_fact`'s
  `yoy_growth: true` flag already computes a derived percentage *server-side*
  and hands back a normal citable result (`agent.py:622-632`, `formulas.py:337-383`).
  A `calculate` tool generalizes that one existing precedent to ad hoc
  arithmetic, instead of inventing a new claim schema or verification path.

## Design: the `calculate` tool

A new 5th tool, dispatched through the existing `_dispatch_tool_call`
exactly like `get_financial_fact`/`compare_financial_metric` (not through
the `submit_answer`/`_partition_submit_call` machinery — it's an ordinary
intermediate tool call, not a terminal action). **Zero changes to
`verify_claims`/`_verify_one_claim`/`CitationWarning`** — the whole point is
that a `calculate` result becomes a normal `all_results` entry the model
cites in its final answer through the existing, unchanged claim-verification
pipeline, the same way an XBRL fact already does.

**Schema** (`CALCULATE_TOOL_SCHEMA`, same envelope every tool uses):

```python
CALCULATE_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "calculate",
        "description": (
            "Performs ONE arithmetic operation over two numbers you have already "
            "seen in a prior result, and returns a new citable result with the "
            "computed value. Use this for any number you would otherwise have to "
            "work out yourself -- never state a self-computed value directly, it "
            "will be refused. Prefer a named ratio first when one exists "
            "(get_financial_fact with yoy_growth: true, or a registered ratio "
            "metric via compare_financial_metric) -- use calculate only for "
            "arithmetic those don't cover."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["add", "subtract", "multiply", "divide", "percent_of", "percent_change"],
                    "description": (
                        "percent_of: operand_a as a percentage of operand_b (a/b*100). "
                        "percent_change: percentage change FROM operand_b (the baseline/prior "
                        "value) TO operand_a (the new/current value) -- (a-b)/b*100."
                    ),
                },
                "operand_a": {"type": "number"},
                "citation_index_a": {"type": "integer", "description": "Which numbered result operand_a came from."},
                "unit_a": {"type": "string", "enum": ["raw", "thousand", "million", "billion", "percent"]},
                "operand_b": {"type": "number"},
                "citation_index_b": {"type": "integer", "description": "Which numbered result operand_b came from."},
                "unit_b": {"type": "string", "enum": ["raw", "thousand", "million", "billion", "percent"]},
            },
            "required": ["operation", "operand_a", "citation_index_a", "unit_a", "operand_b", "citation_index_b", "unit_b"],
            "additionalProperties": False,
        },
    },
}
```

`unit_a`/`unit_b` reuse `_CLAIM_UNITS`'s exact vocabulary so `numeric_utils.normalize()`
handles scale mismatches for free (e.g. `34550 million` vs `34.55 billion` both
normalize to the same raw value before arithmetic runs).

**Two independent guarantees, matching the two things that can go wrong**:

1. **Operand grounding** (answers the user's "how do you know it's basic
   compute vs. a hallucinated number" question): `operand_a` must actually
   appear in `all_results[citation_index_a - 1]["text"]` — checked by
   reusing `_number_candidates()` (the exact same primitive `_verify_one_claim`
   already uses for regular claims) and `normalize()` for the category/tolerance
   comparison (`max(0.01 * abs(norm), 0.05)`, the same constant used everywhere
   else in this file — not re-derived). Same for `operand_b`/`citation_index_b`.
   An out-of-range citation index, or an operand not found in its cited
   source, fails the tool call with a specific message (no `all_results`
   mutation) — the model can retry with corrected values/citations.
2. **Arithmetic correctness**: the operation runs in real Python, not the
   model's head — a divide-by-zero is guarded explicitly; rounding follows
   `formulas.py`'s existing convention (`percent_of`/`percent_change` round
   to 1 decimal, matching `RatioDefinition(as_percent=True)`'s `round(x*100, 1)`;
   `add`/`subtract`/`multiply`/`divide` return the unrounded value, matching
   how raw dollar XBRL facts are already returned unrounded).

**New functions in `agent.py`** (near their existing counterparts):
- `call_calculate(args: dict, all_results: list[dict]) -> tuple[dict | None, str | None]`
  — deliberately a richer contract than `call_get_financial_fact`'s bare
  `dict | None`, because `calculate` has several distinct failure reasons
  (bad citation index, ungrounded operand A, ungrounded operand B, divide by
  zero) that each need their own specific, actionable message — unlike
  `get_financial_fact`'s single generic "not found." Success returns
  `({"value", "unit", "expression"}, None)`; failure returns `(None, message)`.
- `_calculation_as_result(result: dict, args: dict) -> dict` — mirrors
  `_fact_as_result`: `text` renders the full expression and result in a
  directly-quotable form (e.g. `"34550 million divide 195201 million = 17.7 percent (computed value, not directly stated in any filing; operands from results [2] and [5])"`),
  `metadata` uses placeholder `form`/`accession` values the same way
  `_comparison_as_results` already does for XBRL-frame-only rows
  (`fact.get("form", "XBRL frame data")`).
- New branch in `_dispatch_tool_call`, same 6-step shape as the
  `get_financial_fact` branch: trace span, call `call_calculate`, `None` →
  return the error message string (no `all_results` mutation), else append
  the result and return `_format_results_block`.
- Register `CALCULATE_TOOL_SCHEMA` in the `tool_schemas` list passed to
  `start()` (`agent.py`, alongside `FACT_TOOL_SCHEMA`/`COMPARE_TOOL_SCHEMA`/
  `SEARCH_TOOL_SCHEMA`/`SUBMIT_TOOL_SCHEMA`). **Deliberately excluded from
  `mcp_server._TOOL_SCHEMAS`**, same reasoning already applied to
  `submit_answer`: its citation indices are only meaningful within one
  `_run_agent_impl` run's own `all_results`, not to a standalone MCP caller.

**Composability, not a limitation**: `calculate` is strictly binary (2
operands) — no N-ary sum. A 3-way total is `calculate` twice, citing the
first call's own output as an operand of the second (its result is a normal
`all_results` entry like any other). This mirrors FinQA's own programs,
which chain binary operations rather than using N-ary ops.

**System prompt changes** (`agent.py` `SYSTEM_PROMPT`):
- Add a `calculate` bullet alongside the other 4 tools' descriptions ("five
  tools" instead of "four").
- Reword rule 9: remove the now-proven-unworkable "quote the result(s) it
  came from, not the number itself" guidance for hand-computed values;
  replace with: call `calculate` for any number you'd otherwise work out
  yourself, cite its result like any other; a self-computed value with no
  `calculate` call behind it is still refused. Keep the existing guidance
  that a tool's own computed output (`yoy_growth`, a registered ratio) is
  already a directly-reported value per rule 3 — `calculate` is
  specifically the fallback for what those don't cover, not a replacement
  for them.
- **New disclosure requirement, raised by the user during planning**: the
  `calculate` tool's own two guarantees (operand grounding + correct
  arithmetic) only prove the number is *right* — they don't make the
  reader-facing `answer_text` disclose that it was *computed* rather than
  directly stated by the filing. Add an explicit rule: when `answer_text`
  includes a value derived via `calculate`, it must show the computation
  inline (e.g. "computed as $34,550M ÷ $195,201M = 17.7%"), not present it
  as if the filing stated it directly. **Prompt-level only, no new hard
  gate** — confirmed via `AskUserQuestion`: this is a transparency concern,
  not a correctness one (correctness is already guaranteed by the tool
  itself), and a code-enforced check would mean re-introducing
  answer_text pattern-matching for what `calculate`'s own returned
  `text` already makes trivial for the model to comply with (the full
  expression is right there to copy into prose) — same trust level as the
  existing citation-marker formatting rules (1, 8), which are also
  prompt-only. Verify this lands correctly during Phase B's live
  verification (read the actual `answer_text` produced for both motivating
  questions, confirm it names the formula, not just the result) — since
  this is exactly the kind of thing that looks right on paper but needs a
  real run to confirm, per this session's own rule-9 precedent.

## Does the eval grader need to change?

Checked directly against `eval_harness.py`'s actual code (not assumed):
**no grader changes needed**, for a specific, traced-through reason — worth
recording since it's not obvious on first look.

`grade_numeric()` filters candidate numbers by *category* first
(`normalize()`'s `percent` vs `scale`) before checking value/tolerance —
a computed-disclosure answer like "R&D was $34,550 million [2] ... computed
as $34,550M ÷ $195,201M = 17.7% [6]" has three numbers, but only one
(`17.7`) is in the `percent` category, so there's no ambiguity about which
one `grade_numeric` is matching against.

The citation-verification step (`value_is_citation_verified`, which walks
`_iter_citation_claims`) already has the exact leniency this needs, and it
predates this plan — it returns `True` if **any** occurrence of the target
value near **any** marker verifies against its cited source, specifically
*because* "a redundant second, wrong citation for an otherwise-correct
value shouldn't fail the check" (existing docstring, `agent.py:1368`). Traced
through by hand with realistic disclosure phrasing: the `calculate` result's
own text contains the full expression ("...= 17.7 percent"), so the `[n]`
marker the model attaches right after stating "17.7%... computed as..."
lands in a citation window whose cited chunk *does* contain a matching
percent value — verifies correctly with zero code changes, using the same
machinery that already grades every other question.

`JUDGE_SYSTEM_PROMPT` is generic and criteria-driven ("the criteria must be
clearly satisfied by the answer text") — no judged question today involves
a `calculate`-derived value, and none of the reasoning above requires
touching it.

**One real risk, not a code gap**: `_iter_citation_claims` only looks back
`_CITATION_WINDOW_CHARS` (150 chars) from each marker. If the model's
disclosure phrasing is verbose enough to push the stated value more than
150 characters before its own marker, `value_is_citation_verified` could
miss it. This is exactly the kind of thing to actually check with real
output in Phase B, not assume — read the live `answer_text` for both
motivating questions and confirm the marker lands close enough to the
disclosed computation, not just that a marker exists somewhere in the
answer.

## Files and ordered steps

TDD per CLAUDE.md: `call_calculate`'s grounding/arithmetic logic is pure —
full red/green TDD. The dispatch branch and prompt wording are live-code-adjacent
(dispatch mirrors an existing, already-tested pattern; prompt wording needs
live verification per the carve-out, since rule 9's own wording already
needed one correction this session after looking right on paper).

**Phase A — the `calculate` tool (pure logic, full TDD)**

1. `CALCULATE_TOOL_SCHEMA` + `validate_tool_args` acceptance tests (valid
   payload; missing field rejected; bad `operation` enum rejected; extra key
   rejected) — mirrors the existing `SUBMIT_TOOL_SCHEMA` acceptance tests.
2. `call_calculate()`: tests for each of the 6 operations computing
   correctly; divide-by-zero (`divide`, `percent_of`, `percent_change` with
   `operand_b == 0`) returns a clear error, no crash; an operand not found in
   its cited source's `_number_candidates()` returns a specific error naming
   which operand/index; an out-of-range citation index returns a specific
   error; a unit-scale mismatch (`34550 million` vs `34.55 billion`) is
   handled correctly via `normalize()`; rounding matches `formulas.py`'s
   convention.
3. `_calculation_as_result()`: the returned `text` is directly quotable by
   `_quote_matches`/`_number_candidates` (a dedicated test constructs a
   result and asserts a `submit_answer` claim citing it would pass
   `_verify_one_claim` end-to-end — proves the "reuses the whole existing
   pipeline unchanged" claim, not just asserts it).
4. `_dispatch_tool_call`'s new branch: success appends to `all_results` and
   returns the formatted block; failure returns the error string with zero
   `all_results` mutation — mirrors the existing `get_financial_fact`
   dispatch tests' shape.

**Phase B — system prompt + live verification**

5. `tests/manual/verify_calculate.py` (new, live-code carve-out): re-run
   `aapl-rd-pct-gross-profit-fy2025`'s and `msft-cash-to-assets-fy2025`'s
   real questions live and confirm the model now calls `calculate` and
   produces a verified (non-refused), correct answer. If the model doesn't
   reach for `calculate` on the first prompt wording, iterate the wording
   (documented precedent: rule 9 needed one correction already this
   session) — re-run after each change, don't assume it works from reading
   the prompt alone. Also confirm two things the grader analysis above
   depends on, by reading the actual output: (a) `answer_text` visibly
   discloses the formula, not just the bare result; (b) the disclosed
   value's own `[n]` marker sits close enough to it that
   `_iter_citation_claims`'s 150-char backward window actually reaches it
   — a real risk identified by tracing the grading code, not yet observed
   live either way.

**Phase C — new eval questions**

6. Once Phase B confirms `calculate` works live, add to
   `eval/citation_stress_questions.jsonl`:
   - Re-verify `aapl-rd-pct-gross-profit-fy2025` (already present) now
     passes cleanly instead of refusing.
   - A new entry for `msft-cash-to-assets-fy2025`'s shape (currently only in
     the general `eval_questions.jsonl`, not tracked as a dedicated stress
     case) — same self-computed-ratio pattern, now expected to pass.
   - **Independent of `calculate`**, using real data already gathered this
     session from live `hybrid_search`/`xbrl_facts` calls — these stress
     the verifier's *other* new-failure-mode gaps (BACKLOG's existing
     item calling for exactly this):
     - `aapl-iphone-net-sales-q3fy2026`: "What were Apple's iPhone net sales
       for the three months ended June 27, 2026?" (expected 54252 million).
       Source is a bare pipe-table row with 4 columns (3-month/9-month ×
       current/prior year) and no natural-language sentence stating this
       number — stresses both same-chunk multi-period value attribution
       and table-only quote grounding (will the model's `quote` stay a
       literal substring of the table row, or reformat it into prose and
       risk `_quote_matches`'s coverage threshold).
     - `msft-us-revenue-q3fy2026`: "What was Microsoft's revenue in the
       United States for the three months ended March 31, 2026?" (expected
       42336 million) — same metric with 4 nearby numbers (3mo curr/prior,
       9mo curr/prior) in one table row, a second independent case of the
       same attribution stress.
     - `nvda-revenue-yoy-growth-q1fy27`: "According to NVIDIA's quarterly
       filing commentary, what was the year-over-year percentage growth in
       total revenue for the quarter ended April 26, 2026?" (expected 85
       percent) — source sentence states TWO percentages next to each
       other ("up 85% from a year ago and up 20% sequentially"); tests
       whether the verifier could be fooled into accepting the wrong one
       (a plausible false-negative shape never yet observed in this
       project's measurements) if the model ever confuses YoY with
       sequential.
   - Each new question individually live-verified before being committed to
     the file, per this project's existing carve-out and documented
     precedent (`nvda-revenue-fy26-us-gaap` needed 2 reword iterations
     originally) — ground truth values already sourced from real
     `xbrl_facts`/`hybrid_search` calls this session, not invented.

**Phase D — housekeeping and review**

7. `BACKLOG.md`: remove/resolve the Rule 9 gap once fixed (with a
   `PROJECT_CONTEXT.md` note per CLAUDE.md step 6); add a one-line
   confirmation that the 2 fallback-path bugs were reviewed and
   deliberately kept at Low priority (decision + reasoning, not a re-explanation);
   note the new stress questions' purpose.
8. `PROJECT_CONTEXT.md`: new changelog entry — the `calculate` tool, the
   prior-art research backing it, and the new eval questions with their
   live-verified results.
9. Layered review per CLAUDE.md step 7: `/code-review` pass, then a fresh
   architecture-review subagent (no memory of this implementation) — same
   process just run for the structured-claims work, scaled to this smaller
   change's size.

## Verification

- Full test suite green at every step (558 passing today, floor).
- Live verification, no mocks, per the carve-out: `verify_calculate.py`
  confirms the tool actually gets used correctly by the real model on the
  two real questions that motivated this work, not just that the pure logic
  is correct in isolation.
- Each new eval question individually live-verified before being added to
  `citation_stress_questions.jsonl` — confirms it actually reproduces its
  target failure/success shape, not just that the ground-truth value is
  correct on paper.
- Acceptance test: `aapl-rd-pct-gross-profit-fy2025` and the new
  `msft-cash-to-assets-fy2025`-shaped question both pass cleanly
  post-`calculate`, where both previously refused, **and** their actual
  `answer_text` visibly discloses the computation (states the formula/inputs,
  not just the bare result) — checked by reading the real live output, not
  assumed from the prompt wording. The 3 new attribution/quote-grounding
  stress questions each produce a clear, understood outcome (pass, or a
  specific, explained failure) — not an ambiguous or flaky result.
