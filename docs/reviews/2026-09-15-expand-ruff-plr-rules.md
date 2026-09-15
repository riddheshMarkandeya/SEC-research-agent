# Review: Expand ruff's PLR selection (PLR0402, scoped PLR2004)

Plan: none (Standard-tier config change, no separate plan file). Change:
add `PLR0402`/scoped `PLR2004` to `pyproject.toml`, fix the 5 resulting
real findings in `xbrl_facts.py`/`llm_backends.py`/`numeric_utils.py`.
Full suite was at 652 passed before this review.

## Pass 1 — correctness and CLAUDE.md compliance (self, low effort)

`[Verified, no fix needed]` — ruff clean on all touched files both
before and after; full suite green (652); `per-file-ignores` behavior
spot-checked manually against a nested `tests/manual/` file before
handing to Pass 2/3.

## Pass 2/3 — documentation hygiene + architecture/design (fresh subagent, no memory of the implementation session)

Combined per the skill's guidance. Gave the subagent the diff and asked
it to verify everything itself (ran the diffs, re-ran tests/ruff, tested
the `per-file-ignores` glob empirically rather than trusting the claim).

- `[Verified, no fix needed]` **Correctness**: `RETRY_ATTEMPTS`/
  `_MAX_REFERENCE_MARKER_DIGITS` extractions preserve behavior exactly,
  all call sites updated; `http.HTTPStatus.NOT_FOUND == 404` confirmed
  as a real, safe `IntEnum` equivalence with no downstream
  logging/formatting risk; `mcp_server.py`'s `PLR0402` auto-fix doesn't
  break any of its 7 `types.X` usages.
- `[Verified, no fix needed]` **The one thing worth actually testing**:
  whether `"tests/*"` in `per-file-ignores` matches nested files like
  `tests/manual/verify_mcp_server.py`, or only files directly under
  `tests/`. Subagent ran it both ways (real config vs. `--isolated`) and
  confirmed the pattern does match recursively — raised as an explicit
  risk in the review brief specifically so it would be verified
  empirically rather than assumed either way.
- `[Verified, no fix needed]` **Documentation hygiene**: decision file
  matches `TEMPLATE.md`'s skeleton; `PROJECT_INDEX.md` line is a proper
  one-liner in the right position; the new `BACKLOG.md` section's inline
  detail (specific hit counts/locations for the still-undecided
  `S113`/`B905` question) was judged appropriate rather than a
  hygiene violation, since no decision file exists yet for that
  undecided work to point to instead.
- `[Verified, no fix needed]` **Architecture/design**: fixing the 5 real
  findings immediately (rather than deferring to `BACKLOG.md`, unlike
  the original 155-violation baseline) judged a reasonable, justified
  departure — a real difference in kind (minutes-each fixes using
  existing patterns/stdlib) not just a smaller instance of the same
  baseline-debt situation. No naming collision or `IntEnum` comparison
  risk found.

## Additional rounds

None needed — first round closed with zero findings.

## Outcome

Shipped as reviewed, no fixes required by this pass. Final test count:
652 passed (unchanged — this change was a pure refactor of constant
extraction plus config, no new behavior). Nothing added to `BACKLOG.md`
from this review (the pre-existing entry from the broader rule-category
survey is separate, unrelated to this review's findings). Review loop
closed clean on the first round.
