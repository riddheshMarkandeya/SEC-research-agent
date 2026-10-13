# v2 judge template wording: reason about the question, latest-filing context, prose labels

**Date:** 2026-10-12

## Context

Build 4's batch 1 judge sanity pass (`tests/manual/verify_v2_judge_templates.py`, judge
`gemini-3.5-flash-lite`, 21 cases × 2 runs) gave 39/42 as expected. Each misjudgement hit 1 of 2
runs at temperature 0, so the wording allowed both readings:

| Template | Case | Expected → got | Judge's reason (abridged) |
|---|---|---|---|
| `not_covered` | the agent's canned citation-gate refusal on `v2-cost-net-sales-fy2025` | FAIL → PASS | "correctly refused… could not verify it from its sources rather than providing an estimate" |
| `not_yet_filed` | good refusal of Walmart fiscal 2029 citing the latest 10-Q (quarter ended July 31, 2026) | PASS → FAIL | looped on whether July 31, 2026 is in the future, conceded it isn't, verdict already FAIL |
| `clarify` | both Target margin readings in one prose sentence, each labelled | PASS → FAIL | "not… clearly labeling… in a structured manner" |

Root causes, read from the reasons:

1. The question's own detail said the answer "should say it can't answer from its sources",
   which the gate text nearly matches; `v2-cat-backlog-2020`'s detail had the same shape. The
   template also never required the reason to be about the question rather than the
   assistant's own failure (verification, turns).
2. The template didn't say citing a filing dated before today is expected context, so the judge
   compared the cited date against today. A hypothesis; the re-run tested it.
3. `clarify` said the answer "labels" each figure without saying prose labelling counts, and the
   system prompt's "be strict" pushed toward the stricter reading.

## Decision

- `prompts/judge_criteria.py`: a shared `REASON_ABOUT_QUESTION` clause on `not_covered`,
  `not_yet_filed` and `never_disclosed` (a refusal giving no reason about the company, period
  or figure, e.g. only that the assistant couldn't verify its answer or ran out of steps, does
  not pass). `not_yet_filed` adds that citing the latest available filing dated on or before
  today is expected, but that filing's figure given as the unreported period's still fails.
  `clarify` says naming the reading next to each figure in an ordinary sentence is enough, with
  no particular format required.
  `false_premise` is unchanged: it already requires correcting the premise.
- The two batch 1 details now name the actual reason ("Costco is not one of the companies whose
  filings are available…", "…isn't covered by the available filings").

## Why

The fix stays in the v2-only templates. `prompts/judge.py` contributes to #2 (its date rule and
verdict-first format let the verdict land before the reasoning), but it is v1's judge: changing it
moves v1's judge fingerprint and every v1 comparison. Reason-before-verdict there is the next
candidate if a misjudgement recurs, under its own plan.

A v1 `compare_prompt_versions` run spanning this commit prints a "judge_criteria fingerprint"
consistency warning. That's expected: v1 questions don't use these templates, and the `judge`
key is hashed separately.

## Files touched

- `src/sec_agent/prompts/judge_criteria.py`, `src/sec_agent/prompts/model_input_snapshot.json`
  (4 scenarios changed: `clarify` and three refusal kinds; `refusal_false_premise` unchanged)
- `eval/eval_questions_v2.jsonl` (two `criteria` details)
- `tests/manual/verify_v2_judge_templates.py`: the new cases listed under Verification,
  per-case run counts (10 for the 3 misjudged cases, 5 for negatives the new wording could
  loosen and for the new good cases, 2 otherwise: 113 calls), and a check that each question
  still exists with the kind its cases were written for

## Verification

- Sanity script, run 1 (22 cases): **89/89 as expected**, including 10/10 on each previously
  misjudged case and 5/5 on the new latest-10-Q negative.
- Code review then found that `not_yet_filed`'s "is expected" could make a judge require a
  citation. It became "is allowed but not required", and the CAT detail now fails a later year's
  backlog only when it's given as 2020's. Run 2 added cases: a terse refusal, the CAT
  period-not-covered refusal and gate/turns controls, a not-yet-filed refusal citing nothing,
  and a single clarify reading over two years.
- Run 2 (29 cases): **112/113**. Every refusal case matched. `clarify` "every reading labelled"
  failed in 1 of 10 runs, with the reason "without clearly labeling which figure belongs to which
  reading in the required straightforward format". The judge seems to have read the example
  sentence as a required format. The clarify wording was the same in both runs, so its residual
  error was about 1 in 20.
- With the user's approval, past the plan's one-revision limit, the example sentence was replaced
  by "Naming the reading next to each figure in an ordinary sentence is enough; no particular
  format is required". A clarify-only run 3 gave **32/32**, including 20/20 on "every reading
  labelled". The refusal templates were not re-run, since their text didn't change after run 2.
- Unit tests, full suite 1636 passed, ruff and pyright clean, `judge_criteria.py` 100% covered;
  `check_questions` on batch 1: 0 errors, 0 warnings.

## Related

- `docs/plans/2026-10-12-phase2-build4-v2-questions.md` (Addendum: the original 39/42 run)
- `docs/decisions/2026-09-17-fix-judge-hypothetical-date-bug.md` (the same judge date-reasoning family)
