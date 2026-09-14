# Stop the agent wasting turns re-deriving what a tool already gave it

## Context

The last full eval baseline (`eval/eval_results/20260913T224536Z.json`,
47 questions, 2026-09-13) passed 31 and failed 16. **Nine** end with the
same canned message — *"I wasn't able to finish answering within the
allotted number of searches"* — the largest failure cluster by far.

Reading every one of those nine traces in `trace_logs/traces.jsonl`
shows they are **not** a budget-size problem. The agent usually already
held the correct answer and spent its remaining turns re-deriving it:

| Question | Baseline run | What consumed the 5 dispatch turns |
|---|---|---|
| `pltr-revenue-2025` | `50a6c32741d4` | 1 fact (`4,475,446,000`) + 4 schema-rejected `calculate` |
| `crm-revenue-q1fy27` | `3b8dba133e98` | 1 fact (`11,133,000,000`) + 4 schema-rejected `calculate` |
| `aapl-revenue-growth-q3fy2026` | `5cc7bddbe216` | `yoy_growth` = **16.4** (the expected answer) on turn 1, then 2 fetches + 2 grounding-failed `calculate` re-deriving it |
| `aapl-3yr-avg-operating-margin` | `ca87bbfbb0cf` | average = **31.1** (the expected answer) on turn 1, then 4 successful calls re-deriving it |
| `nvda-rd-expense-q4fy26-refusal` | `4ba643aca0e6` | 5 fully successful calls, no turn left to submit |
| `pltr-inventory-turnover-refusal` | `75c1ec38dd90` | 5 fully successful calls, no turn left to submit |
| 3 × `five-company-*-ranking` | `83708a3fc248` et al. | 5 × `get_financial_fact` instead of 1 `compare_financial_metric` |

Four distinct mechanisms, each a tool-design problem rather than a
verifier bug — which is why the prior art below drives the plan.

### Mechanism 1 — `calculate` used for a unit conversion it can never satisfy (2 questions)

`pltr-revenue-2025` and `crm-revenue-q1fy27` each convert a raw dollar
figure to billions via `calculate(divide, operand_b: 1e9)` — four times
each, every call omitting the required `citation_index_b`, every one
rejected with the generic `"(your calculate call didn't match the
required schema)"`.

The model has **no valid way** to make this call: the divisor is a
literal constant that cannot be grounded. Verified by running
`call_calculate` — `citation_index_b: 1` gives *"operand_b=1000000000
(raw) was not found in result [1]"*; `citation_index_b: 2` gives *"[2]
is not a valid citation index."*

And the call is **unnecessary**. Verified against the real verifier: a
claim of `value: 4.48, unit: "billion"` quoting the raw source text
`"...was 4,475,446 (in thousands)..."` passes `verify_claims` with zero
warnings — `normalize()` already treats the two as the same quantity.
Corroborated live (run `52d68da34c75`): `62.475 billion` quoting
`"cost_of_revenue = 62475000000 USD"` recorded `warning_count: 0`.
Nothing in rule 9 or `CALCULATE_TOOL_SCHEMA` says a unit restatement
needs no calculation, and rule 9's *"for EVERY number in `answer_text`,
add a matching entry to `claims`"* pushes the other way.

A regression: `pltr-revenue-2025` answered in 1-2 turns on 2026-09-10
and 2026-09-11, and began failing from the working tree that became
commit `a136450` (the `calculate` tool).

### Mechanism 2 — the model re-derives a value a tool already returned whole (2 questions)

`aapl-3yr-avg` received `31.1` — the exact graded answer — from a single
`start_fiscal_year`/`end_fiscal_year` call on turn 1, then spent four
turns fetching the three per-year margins. `aapl-revenue-growth`
received `yoy_growth = 16.4` — again the exact graded answer — on turn 1,
then fetched both revenues and tried `percent_change` twice. Both are
the model corroborating a single structured answer it already had,
plausibly pushed by rule 9's per-number claim requirement plus rule 3.

`aapl-revenue-growth`'s two wasted `calculate` calls have a second,
separate cause worth fixing in the same pass: they failed with
`unit_a: "billion"` on a raw value. Verified:
`normalize(109417000000, "billion")` = `1.09417e+20`. The error message
they got back — *"operand_a=109417000000 was not found in result [2] --
double check the value and citation index"* — blames the value and the
citation index, **both of which were correct**. The model then changed
the one field the message never mentioned. This is a message pointing at
the wrong field, not evidence that specific messages fail.

### Mechanism 3 — the model ignores `compare_financial_metric` for rankings (3 questions)

`agent.py:107` already says *"Use this instead of calling
`get_financial_fact` five times when a question asks you to compare or
rank companies."* It has never once been called on these questions.

This matters more than a wasted turn, because **the five-call path
returns the wrong answer**. Verified directly:

```
call_compare_financial_metric(anchor AAPL, operating_margin, FY2025)
  -> AAPL 32.0 | MSFT 45.6 | NVDA 60.4 | CRM 20.1 | PLTR 31.6   (one call)

call_get_financial_fact(CRM, operating_margin, fiscal_year=2026, FY)
  -> None        (and run 83708a3fc248 shows exactly this: found=False for CRM)
```

`five-company-operating-margin-ranking-fy2025` is graded on identifying
**CRM at ~20.1%** as the lowest — the value the one-call path returns and
the five-call path cannot retrieve at all. **Raising
`MAX_TOOL_ITERATIONS` would convert these three timeouts into
confidently wrong answers.** (Root cause of the CRM gap:
`fiscal_year=2026` returns `None` while `period_end_date='2026-01-31'`
returns 20.1. A separate real bug — not currently in `BACKLOG.md`; this
plan adds it.)

### Mechanism 4 — no slack for a legitimate final turn (2 questions)

The budget accounting is deterministic: `calls_made` starts at 1
(`agent.py:2272`), dispatch is gated on `calls_made <
MAX_TOOL_ITERATIONS` (`agent.py:2361`) and increments once per **round
trip**, not per tool call (`agent.py:2364-2382`) — exactly 5 dispatch
turns. The submit branch (`agent.py:2297`) precedes the gate, so a pure
`submit_answer` on turn 6 always lands (confirmed across 25 real runs).

So 6 is not "too tight" — it leaves *exactly zero slack*. `nvda-rd-expense`
and `pltr-inventory-turnover` are correct-refusal questions that each
made 5 fully successful calls, hit no errors at all, and died holding
everything needed to refuse. `pltr-inventory` correctly got
`inventory_turnover → found: False` (every call correctly scoped to
`PLTR`), then searched four times for inventory Palantir doesn't carry —
and *did* submit that refusal successfully on 2026-09-12 when the turns
fell right.

**Mechanism 4 is deliberately not fixed in this plan** — see Scope below.

Out of scope, tracked separately: the judge marking correct 2026-dated
answers as "future/hypothetical" (2 failures), bogus numeric claims on
qualitative answers (2), three residual `quote_not_found` refusals.

## Scope: this plan is prompt-and-message surface only

Mechanisms 1-3 (seven of the nine failures) are fixed by changing what
the model is *told* — system prompt, tool descriptions, and the text of
one error message. No change to the tool-calling loop.

Mechanism 4 needs a loop change (a final-turn safety net, or failed
calls not drawing on the answer budget), which touches the loop's most
entangled state — `calls_made`, `forced_submit_attempted`,
`retried_for_citations`, `pre_retry_submit_args` — and carries a real
wrong-answer risk of its own: run `f481b68f3467` dies holding four
margins and **no CRM**, so a forced final submit there would produce
four perfectly grounded numbers naming PLTR as lowest when the answer is
CRM. Grounded and wrong is exactly the failure mode used above to reject
raising the budget, and it would be hypocritical to wave it through for
a different mechanism.

Per `CLAUDE.md`'s escalation rule, that belongs in its own plan — and
the evidence for splitting is already in hand rather than something to
discover mid-implementation. It gets a `BACKLOG.md` item now
(`[bug, High, Substantial]`) and is designed after this task's re-run
shows what's actually left.

## Prior art

Read before designing, per `CLAUDE.md` step 1.

**Anthropic, [Writing effective tools for AI agents](https://www.anthropic.com/engineering/writing-tools-for-agents).**
(a) *"prompt-engineer your error responses to clearly communicate
specific and actionable improvements"*, including examples of correctly
formatted inputs. (b) Tool consolidation, with descriptions drawing
*clear boundaries from other tools* — `compare_financial_metric` already
is the consolidated tool, so Mechanism 3 is a boundary-description
failure, not a missing capability. The article's iteration method (run
real eval tasks, read transcripts for confusion, refine descriptions,
re-measure) is exactly this plan's loop.

**pydantic-ai's [`ModelRetry` vs `ToolFailed`](https://pydantic.dev/docs/ai/api/pydantic-ai/tools/).**
`ModelRetry` asks the model to correct arguments and retry; `ToolFailed`
reports *a terminal failure the model should adapt to instead of
retrying*, and does not consume the retry budget. Mechanism 1 is a
textbook terminal case — no valid call exists — currently phrased like a
correctable one.

**This plan adopts the distinction but splits it in two**, deliberately:

- **The classification lands here**, in Step 2, computed rather than
  guessed: an operand value that matches under no unit in any result is
  a literal constant (terminal); one that matches under a *different*
  unit is a mislabel (correctable). Full TDD. This is the hard,
  testable half, and it is what makes the message correct.
- **The runtime acting on it lands in the follow-up loop plan.** A
  structural signal means widening `_dispatch_tool_call`'s return type,
  and that only pays for itself if the loop then *does* something
  different — not charging `calls_made` (pydantic-ai's actual payoff,
  and the same work as Mechanism 4's budget change), dropping
  `calculate` from the schemas mid-run, or jumping to a forced
  submission. All three are loop changes with Mechanism 4's own risks.
  A widened type whose only consumer logs it would be exactly the
  speculative abstraction `CLAUDE.md` step 3 rules out.

For the record, `agent.py:1961-1967` is **not** a precedent against
this: that decision declined a `str|Terminal` union for encoding *"this
call ends the conversation"*, because for `submit_answer` the loop
already knows that from `_partition_submit_call`. Here the loop cannot
know it — only the tool can. The earlier draft of this plan cited it as
a blocking precedent; that was an overstatement, corrected here.

**Loop detection via action deduplication** was evaluated and
**rejected** for this task. It applies to only 2 of the 9 failures, and
saves no turn on its own — the round trip is already spent when the
duplicate arrives. It belongs with the Mechanism 4 loop work if at all.

## Step 0 — commit the finished table-grounding work first

8 modified + 4 untracked files from the completed, fully-reviewed
table-grounding redesign. Per `CLAUDE.md` step 9, commit before touching
anything here. Full suite green first (631 passing, confirmed).

## Step 1 — a unit restatement is not a calculation (Mechanism 1)

Two prompt surfaces in `agent.py`:

- **`CALCULATE_TOOL_SCHEMA`'s `description`** (~`agent.py:378`): both
  operands must come from results already seen; converting a value
  between raw/thousand/million/billion is *not* arithmetic. Per
  Anthropic's guidance, add a correct example call and an explicit "when
  NOT to use this tool" line naming unit conversion.
- **System-prompt rule 9** (~`agent.py:123`): restating an already-cited
  value in a different unit needs no tool call — state it with the
  converted unit, cite the same result with the same verbatim quote.
  **Include the precision caveat**: verification uses a 1%-relative
  tolerance. Measured against a `4,475,446,000` source: `4.475446` /
  `4.48` / `4.5` / `4.47` verify; `4.4` and `4.0` are refused with
  `value_not_in_quote`. Saying "just restate it" without this trades a
  timeout for a hard-gate refusal.

**Why relaxing this is safe** (worth recording given the 2026-09-13
incident where a fix reopened a worse hole): the verifier independently
bounds it — a *derived* value quoting an unrelated raw source still
fails (`55.3 percent` quoting `"net_income = 2475446000 USD"` →
`value_not_in_quote`). This lets the model skip a call it never needed;
it cannot create a grounding hole.

## Step 2 — a tool's answer is the answer (Mechanism 2)

Add a rule-9 line: when a tool returns the exact quantity asked for —
including `get_financial_fact` with `yoy_growth: true` or with
`start_fiscal_year`/`end_fiscal_year` — that value **is** the answer;
submit it, do not fetch its components to show the work. This is the
only cheap lever that touches `aapl-3yr-avg`.

Separately, fix the misleading message in `_ground_operand`
(`agent.py:965-988`): on failure, re-check the cited source for the
operand's value **under the other units**, and when one matches, say so
— *"result [2] contains 109417000000; you labeled it `billion`, which
means 109,417,000,000 billion. Did you mean `raw`?"* This is also the
one place the retryable/terminal distinction can be **computed** rather
than guessed: a value found under no unit in any result is a literal
constant and genuinely terminal (verified: `1000000000` appears nowhere
in run `50a6c32741d4`'s sole result). Note a naive "not found →
terminal" rule would wrongly terminalize the `aapl` case — the unit
re-check is what separates them.

Pure deterministic logic: full red-green TDD in `tests/test_agent.py`
for the `_ground_operand` message (unit-mismatch case, true-literal-
constant case, valid case unchanged).

## Step 3 — draw the tool boundary for rankings, narrowly (Mechanism 3)

Strengthen `agent.py:107` and `get_financial_fact`'s own description so
a ranking across companies routes to `compare_financial_metric`.

**Scope the wording carefully** — a broad "always use
`compare_financial_metric` to compare" would regress five questions that
currently **pass** (verified against the baseline):
`nvda-revenue-two-quarter-comparison` (one company, two quarters),
`aapl-msft-tax-rate-comparison` and `aapl-msft-employee-comparison`
(metrics not in the enum at all),
`aapl-msft-total-assets-comparison` (two companies, two as-of dates),
and `msft-three-segments-revenue-q3fy2026` (segments — `agent.py:106`
deliberately routes those straight to `search_filings`, and it is the
question the 2026-09-13 table-grounding redesign was validated on).

The evidence says over-application is the live risk, not
under-application: the only three real-question traces that ever used
`compare_financial_metric` were a *two-company* question. So the rule
must be conditioned on **three or more companies** and **a metric in
the supported enum**, and must leave the segment guidance untouched.

## Verification

LLM round-trips are live-only code under this project's `CLAUDE.md`
carve-out: write `tests/manual/verify_tool_turn_waste.py` **first**,
asserting on the tool-call *sequence* (not just the final answer) to
reproduce the waste, then change the prompts, then re-run.

- Full unit suite green throughout (631 → higher with new tests).
- Targeted live eval — **not** a full baseline; the Gemini free tier
  caps at 500/day and has been exhausted twice. Ten questions: the
  seven targets, plus three regression guards for Step 3's wording:

  ```
  python eval_harness.py --backend gemini --ids \
    pltr-revenue-2025,crm-revenue-q1fy27,aapl-revenue-growth-q3fy2026,\
    aapl-3yr-avg-operating-margin-fy2023-fy2025,\
    five-company-operating-margin-ranking-fy2025,\
    five-company-gross-margin-ranking-fy2025,five-company-net-margin-ranking-fy2025,\
    nvda-revenue-two-quarter-comparison,aapl-msft-total-assets-comparison,\
    msft-three-segments-revenue-q3fy2026
  ```

  `-operating-margin-` is the load-bearing ranking question: its correct
  answer *requires* CRM, so it alone distinguishes "finished within
  budget" from "actually right." The last three must still pass —
  without them the targeted run cannot see Step 3's regression risk.
- Full 47-question baseline only as final confirmation once the targeted
  run is clean — the system prompt is shared by all 47.
- Two-pass review per `CLAUDE.md` step 7 → `docs/reviews/2026-09-14-tool-turn-waste.md`.
- `PROJECT_CONTEXT.md` entry and `BACKLOG.md` updates the same session:
  close `:69` (which already concluded *"would need prompt-engineering,
  not a verifier change"*); update `:71` (its clause (b) said *"revisit
  only if this recurs in a full baseline"* — it has, as
  `aapl-revenue-growth`); add items for the Mechanism 4 loop work
  (`[bug, High, Substantial]`), the CRM fiscal-year-label bug
  (`[bug, Med, Standard]`), and the four out-of-scope clusters.
  `BACKLOG.md:123`'s `validate_tool_args` return-type refactor is
  **not** touched here — it was in an earlier draft of this plan and was
  dropped: it cannot be closed without changing the `search_filings`
  ticker branch, which is unrelated to any of these nine failures.

## Addendum — actual execution deviated from Step 3 (2026-09-14)

Step 3 was attempted exactly as planned (narrowed to 3+ companies, a
metric in the enum, segment guidance untouched) and, after a first live
failure, strengthened further with an explicit reassurance sentence
about anchor-based closest-period matching being correct even when the
question states each company's own distinct fiscal year/period-end
date. **Both wordings failed identically, live, three times in a row**
— the model kept calling `get_financial_fact` five times regardless,
same as the untouched baseline. Per `CLAUDE.md`'s "fails twice in the
same way" rule, this was brought back to the user rather than tried a
fourth way; the user chose one more targeted attempt, which also failed
the same way on the third try. All Step 3 wording was then reverted to
the original, unmodified text — shipping unproven wording risked the
exact regressions this plan worried about, for zero measured benefit.

Mechanism 3 is unresolved and filed to `BACKLOG.md` with this evidence,
including the working hypothesis for WHY three attempts failed: the
target question spells out each company's own distinct fiscal year and
period-end date explicitly, which may read to the model as needing
exact per-company values rather than the tool's anchor-and-closest-match
approximation, no matter how the guidance is worded. See
`docs/reviews/2026-09-14-tool-turn-waste.md` for the full record.
