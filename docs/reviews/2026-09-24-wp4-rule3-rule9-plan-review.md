# Review: WP4 plan, rule 3 / rule 9 contradiction (one independent plan-review round)

Plan: `docs/plans/2026-09-24-wp4-rule3-rule9.md`. The plan rewrites SYSTEM_PROMPT rule 3 so
that it states the real contract, drops rule 9's "despite rule 3" clause (audit finding 3),
and screens the change under the roadmap's Decision rule against WP3's runs. This review
covers the plan only, before implementation. The suite had 920 tests at HEAD `c57e063`.

## Pass 1: self-check of the roadmap's Step 4 against HEAD `c57e063`
- [Verified] Rule 3 is at `prompts/agent_system.py:47` and rule 9 at `:53`. The clause
  text matches the roadmap.
- [Verified] Only `prompts/model_input_snapshot.json` pins the rule text. The snapshot
  test is the red step.
- [Fixed in plan] The `agent.verify_citations` docstring quotes the old rule 3, so it
  becomes false after the change. It gets its own docstring-only commit (4b), so that an
  attribute revert takes only the model-facing commit.
- [Fixed in plan] Today's quota can't cover the screen, so it waits for the 07:00 UTC
  reset.
- [Fixed in plan] The new rule 3 tells the model to derive numbers with `calculate`, so
  `nvda-rd-expense-q4fy26-refusal` could now compute Q4 as FY minus the nine-month
  year-to-date figure. That question is named as the one to watch.

## Round 1: independent subagent (the whole plan)

**Must-fix, adopted:**
- **The Q4 risk had no decision attached.** B is 2/3 on that question, so one C failure
  is a drop of only 0.33, below REGRESSED. Its rubric
  (`eval/eval_questions.jsonl:21`) also only forbids a figure presented "as if it were a
  directly reported fact". The screen couldn't catch the risk. The plan now overrides:
  any C run stating a derived Q4 value counts as flagged, and if that replicates, a
  BACKLOG item asks whether the rubric or the prompt is wrong.

**Should-fix, adopted:**
- **S1, the ratio tension.** The roadmap's rule 3 sends any "ratio, or percentage change"
  to `calculate`. That contradicts the calculate bullet's "Prefer a named ratio first" and
  the `yoy_growth` guidance. It shows already in B: `msft-cash-to-assets-fy2025` uses
  `calculate percent_of` in all 3 runs, although `cash_to_assets` is a registered ratio.
  The user chose to add the qualifier "that no tool reports directly", and the trace
  check also counts named-ratio calls against calculate ratio calls.
- **S2, the attribute mechanics.** Replicate and attribute use explicit mode, because
  reverting 4a restores `4f36a2b026cf`, which fingerprint mode would merge with B. A
  review fix that touches agent text is reverted together with 4a.
- **S3, the trace record shape.** Auth and rate-limit records have no `name`, so the
  script uses `.get`. The root `run_agent` record is written after its tools, so run_id is
  mapped to the question in a first pass. The B window, 01:40:57Z to 01:51:00Z, holds 39
  runs.
- **S4, candidate named explicitly.** The command passes `--candidate`, so a stray
  spot-check at another fingerprint can't become the default.

**Nits:**
- Adopted:
  - the docstring is at `agent.py:1259`;
  - the roadmap's rule 9 text also lowercases FIRST/ITS and drops the examples, which
    the decision file will note;
  - archived index lines go to the top of the newest-first `## Archive`;
  - today's usage is about 360–400, not 340;
  - the replicate budget is about 25 requests per question;
  - 4b keeps the question ID.
- Not adopted: "every number" as an over-constraint. Rule 9 already says "For EVERY
  number", and `verify_claims` exempts numbers from the question, dates and years.

**Confirmed:**
- the new text removes the contradiction, and rule 9's "per rule 3" stays true;
- nothing else in `prompts/`, `tests/`, `eval/` or `.claude/rules` refers to rule 3's
  content;
- the references to rule 9 hold;
- the text appears once, in the snapshot's `agent` section;
- `judge` and `mcp` don't hash the system prompt;
- B's reports are from `12554a4`, clean, with the snapshot verified;
- `--since` drops the WP2 reports;
- a docstring-only 4b leaves the fingerprint unchanged;
- 07:00 UTC is midnight Pacific in September;
- the other panel questions are low-risk.

## Outcome

The must-fix, all four should-fixes and six of the seven nits are folded into the plan
before approval. The one nit not adopted is recorded above with its reason. One user
decision was made: the rule 3 qualifier. Nothing was deferred.
