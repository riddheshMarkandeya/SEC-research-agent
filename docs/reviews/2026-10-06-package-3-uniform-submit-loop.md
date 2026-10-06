# Review: package 3, uniform submit loop

Plan: `docs/plans/2026-10-05-package-3-uniform-submit-loop.md`. The change replaces the loop's
four per-path flags with one turn rule and a shared reserve of 2. It ran 1261 tests after
the fixes. Its review depth was Substantial (about 640 changed lines in the critical core).

## Rounds 1–3

The full findings and their dispositions are in the plan's `## Review log`. In summary:
- **Round 1** (`/code-review high`, `arch-reviewer` sonnet, `security-reviewer`, `/simplify`).
  It found one behaviour bug: an in-budget tool-call reply to a forced follow-up ended the run,
  and master would have dispatched it. That's fixed, and the forcing-failed rule now applies to
  tool calls only past the budget. Other fixes were to the manual script's injection counting,
  to stale names and comments, and to `Literal`-typing `reason`/`ending`. Disputed: the
  "dead" no-turn-left branches, which are live when `SUBMIT_RESERVE = 0`. The tests now drive
  them through the real loop.
- **Round 2** (delta, same passes minus simplify): docstring, label and test-name fixes only.
  No behaviour bugs.
- **Round 3** (`/code-review low`, `security-reviewer`): clean. Review closed.

Deferred: none. Skipped (optional): the simplify suggestions listed in the plan.

## Live verification

- **Base panel** (13 questions 3×, master `63114b9`): `20261005T184557Z`, `20261005T184953Z`,
  `20261005T185250Z`, each 13/13.
- **Candidate panel** (`af59ce2`): `20261006T071859Z`, `20261006T072200Z`,
  `20261006T072502Z`. In explicit mode it gave 39/39 vs 39/39, no REGRESSED, watch or floor
  flags, and 0.0 expected passes lost (threshold 6).
- **Full 48** (`20261006T073606Z`): 46/48, against package 5's 44/48 (`20261003T030904Z`). Both
  remaining failures are carried over from package 5 and are wrong model answers, not gate
  refusals:
  - `pltr-dividend-2019-refusal`: "never declared or paid any cash dividends" instead of saying
    there's no 2019 data.
  - `msft-segment-revenue-comparison-q3fy2026`: "information insufficient". This is the chronic
    failure tracked in the BACKLOG watch list.
- **Re-mine** (`analyze_gate_replay`, window 07:25:05Z–07:37Z): 48 replayed, 0 refused then
  and now, 0 drift. `citation_retry` fired in 3 runs, all `attempt: 1`, for
  `pltr-dividend-2019-refusal`, `msft-segment-revenue-comparison-q3fy2026` (forced, reserve 0
  after) and `nvda-revenue-yoy-growth-q1fy27` (passed). No run used a second attempt, so the
  plan's success test (a run refused after its first retry and rescued by the second) wasn't
  exercised live.
- An earlier candidate attempt on 2026-10-05 was discarded: another session switched the
  checkout's branch mid-panel. The rerun used a dedicated worktree.

## Outcome

Package 3 shipped on `package-3-submit-loop` (`e2cd401`). It raises the score from 44/48 to
46/48 with no new failures and no new refusal class. Open: a watch item for the first live
second retry (`[test-coverage, Low, Trivial]`). The review closed clean in round 3.
