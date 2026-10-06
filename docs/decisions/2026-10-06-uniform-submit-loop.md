# Uniform submit loop: one turn rule with a shared reserve, no one-retry cap

**Date:** 2026-10-06

## Context

The agent loop had four flags, each giving one extra turn type its own cap: one citation retry
per conversation, one forced follow-up after a text reply, one reserved forced turn past
`MAX_TOOL_ITERATIONS`, and a cached pre-retry submission. Since package 1 every failed submit
gets a retry, so the refusals left are second failures. In the 135 runs from 2026-10-01T07:00Z,
17 retried and 4 were still refused after the retry. The one-retry cap was the only thing
stopping a second attempt. Review S2 asked for one "submit attempts left" rule in place of the
flags. This is package 3 of the improvement map.

## Decision

One rule decides every extra turn: the turns left are the budget left plus `reserve_left`
(`SUBMIT_RESERVE = 2` forced turns past the budget). A failed submit, a text reply and pending
tool calls past the budget all draw from that pool, so repeated failing submits each get a
retry. One rule takes precedence: if a forced send gets anything but a submit back (text, or
tool calls past the budget), the run ends on the cached submission. The worst case stays
`MAX_TOOL_ITERATIONS + 2` requests. The gate and every model-visible string are unchanged.
New log fields: `citation_retry.attempt`/`reserve_left`, `final_turn_forced.trigger`,
`citation_gate_refused.retries`, and a `submit_turns_ended` event for both ending paths.

## Why

- **This revisits the one-retry cap** from `2026-08-24-citation-retry-loop-design.md` and
  `2026-09-30-citation-retry-own-slot.md`. What changed: package 1 closed the no-retry gap, so
  the cap became the binding limit on the remaining refusals.
- **A shared reserve of 2, not a per-path cap** (user, 2026-10-05). It keeps the request bound
  that the old flags gave, while letting any mix of retries, follow-ups and final turns use it.
  A pure refactor with no extra retries was the alternative. It was rejected because it leaves
  the 4 refusals untouched.
- **"Forcing failed, the run ends"** keeps two existing behaviours without per-conversation
  flags. It ends a run on text right after a forced send, and on a tool call right after a
  forced send past the budget. Forcing again would just burn a request.
- Accepted risk: a second retry might reward guessing a new quote. The gate still checks every
  quote, so the worst outcome is a refusal, never a wrong answer.

## Files touched

`src/sec_agent/agent/agent.py`, `src/sec_agent/agent/submission.py`,
`src/sec_agent/devtools/analyze_citation_gate.py`,
`src/sec_agent/prompts/model_input_snapshot.json`, `tests/agent/test_agent.py`,
`tests/agent/test_submission.py`, `tests/prompts/test_model_input_snapshot.py`,
`tests/manual/verify_uniform_submit_loop.py` (commit `e2cd401`).

## Verification

- Offline: 1261 passed, ruff and pyright clean, 100% diff coverage on `src/sec_agent/agent/*`.
  Gate replay identical. The manual script showed a refusal after one retry on master, and a
  second retry with two accepted forced submits after the change.
- Panel 3× at `af59ce2` against the base 3× at `63114b9` (explicit mode): 39/39 vs 39/39, no
  flags.
- Full 48 run (`20261006T073606Z`): 46/48, against package 5's 44/48 (`20261003T030904Z`). No new
  failures. Two questions that failed in package 5 now pass: `crm-ai-risk` and
  `nvda-revenue-yoy-growth-q1fy27`. Two questions still fail on wrong model answers, with no
  gate refusal: `pltr-dividend-2019-refusal` and `msft-segment-revenue-comparison-q3fy2026`.
  Gate replay over the run: 0 refused, 0 drift.
- **Not shown live:** 3 runs retried, and all 3 needed only the first attempt. So no live run
  has used a second retry yet, and that path is covered by unit tests and the manual script
  only (BACKLOG watch item).

## Related

- Plan, plan review and review log: `docs/plans/2026-10-05-package-3-uniform-submit-loop.md`
- Review: `docs/reviews/2026-10-06-package-3-uniform-submit-loop.md`
- Revisits: `docs/decisions/2026-09-30-citation-retry-own-slot.md`,
  `docs/plans/2026-08-24-citation-retry-loop-design.md`
- Map: `docs/plans/2026-09-28-agent-improvement-map.md` (package 3)
