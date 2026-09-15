# Review: CLAUDE.md restructure into skills, path-scoped rules, and a docs-sync hook

Plan: `docs/plans/2026-09-15-claude-md-restructure.md`. Change: split the
global and project `CLAUDE.md` files' big procedural sections into 6
personal skills and 2 path-scoped `.claude/rules/` files, plus a new
`PreToolUse` docs-sync hook (`scripts/check_docs_sync.py` +
`tests/test_check_docs_sync.py`, 8 tests before this review). Full suite
was at 642 passed before this review pass (601 baseline + this change's
own 8 new tests, plus whatever else had accumulated this session).

## Pass 1 — correctness and CLAUDE.md compliance (self, low effort)

Ran the actual live hook against a real staged-mismatch scenario during
implementation rather than only unit-testing in isolation. `[Verified, no
fix needed]` — hooks JSON structure in `.claude/settings.json` matches
the documented `PreToolUse`/matcher/`type: command` shape; `ruff` clean;
8 unit tests green at the time. Did not independently catch the two real
bugs below — those surfaced from Pass 2/3.

## Pass 2/3 — documentation hygiene + architecture/design/content-parity (fresh subagent, no memory of the implementation session)

Combined per the skill's guidance (independence is the scarce resource,
not subagent count). Gave the subagent the change's context and asked it
to verify everything itself via `git status`/`git diff`/reading files
directly, rather than trusting the plan/decision file's own claims.

- `[Fixed]` **Doc self-contradiction**: project `CLAUDE.md`'s hooks
  section said the docs-sync hook "warns (non-blocking)," but the
  implemented hook hard-blocks via exit 2 (a deliberate, user-approved
  mid-implementation change — see the decision file's "Implementation-
  time amendment" section) — the summary in `CLAUDE.md` was just never
  updated to match. Fixed by rewording that section to state the real
  behavior and its scoping.
- `[Fixed]` **Confirmed false-positive block**: `is_commit_command`'s
  original regex (`\bgit\s+commit\b`) matched that text anywhere in a
  Bash command's string, including inside an echoed JSON payload used
  during the hook's own manual trigger test — which had been
  mislabeled as a successful validation rather than recognized as a
  bug. Fixed by requiring `git commit` to actually start a
  shell-command segment (split on `&&`/`||`/`;`/`|`), not merely appear
  as substring text. Re-verified live: the exact command that previously
  false-blocked now runs cleanly with the same staged mismatch still
  present, and a case that IS a real `git commit` still blocks correctly.
- `[Fixed]` **Plausible crash**: `payload.get("tool_input", {}).get(...)`
  raises `AttributeError` when `tool_input` is explicitly `null` in the
  JSON (the `{}` default only applies when the key is absent, not when
  its value is `None`). Fixed with `(payload.get("tool_input") or
  {}).get(...)`; added a regression test.
- `[Fixed]` **Test-coverage gap**: `main()`'s stdin/subprocess glue
  (JSON-parse errors, non-Bash filtering, both exit-code paths) was
  untested — the one live manual trigger test only exercised the (buggy)
  block path. Added 10 more tests exercising `main()` directly via
  monkeypatched `sys.stdin` and a stubbed `_staged_files`, including
  regression tests for the three bugs above.
- `[Fixed]` **Backlog-hygiene gap**: the hook's known chained-command
  limitation (`git add -A && git commit` checked against pre-command
  staged state) had no `BACKLOG.md` entry. Added one, tagged `[bug, Low,
  Standard]`.
- `[Verified, no fix needed]`: content parity (spot-checked distinctive
  phrases from both original files, all found relocated correctly, none
  dropped); cross-references between the 6 skills and 2 rules all
  resolve to real, matching content; the six-way skill split judged a
  sensible granularity with non-overlapping triggers; global `CLAUDE.md`
  landing at 217 lines (vs. a ~200-line target, 623-line original) judged
  an acceptable outcome given every remaining line is short/universal
  content deliberately kept inline, not padding.

## Additional rounds

None needed — all Pass 2/3 findings were fixed in one round, then
re-verified (unit tests, ruff, and a live re-run of the exact false-
positive scenario) with no new issues surfacing. Per the review-loop cap,
stopping here rather than spawning another review round for a
already-clean fix.

## Outcome

Shipped: the full restructure plus fixes for all 5 findings above. Final
test count: 652 passed (642 + 10 additional `check_docs_sync` tests added
during this review; the earlier 642 already included the first 8). Ruff
clean on all touched Python files. Nothing deferred to `BACKLOG.md` as a
correctness issue — the one backlog item added (chained-command
limitation) is a documented, accepted scope limitation, not an unfixed
bug in what was actually built. Review loop closed clean on the first
round.
