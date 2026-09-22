# Review: Pyright-clean refactor diff

Plan: `docs/plans/2026-09-22-pyright-clean-refactor.md`. Closes the
117-error basic-mode pyright baseline across 9 test/verify files via
type-narrowing assertions, 4 `typing.cast` sites, 1 comprehension
rewrite, and the `httpx`→`httpx2` dependency fix. Test suite after this
diff: 707 passing (unchanged from before).

## Pass 1 — correctness and CLAUDE.md compliance (`/code-review`, medium effort)

Six independent angles reviewed the diff and the actual code it touches
(not just the hunks in isolation). Confirmed accurate: every
`assert x is not None` insertion sits in a flat, branch-free scope
where pyright's narrowing genuinely holds (traced full function
bodies, including `_RunningServer.__exit__`'s `self._proc` and the
`call_calculate` paired-assertion block); all 4 `cast(...)` sites wrap
values the code under test never actually introspects; the
comprehension→loop rewrite in `verify_period_labels.py` is
semantically faithful; no unrelated scope creep found anywhere in the
9 files.

One finding surfaced and resolved by cross-examination within the pass
itself: one angle initially characterized the `httpx`→`httpx2` swap as
an "undeclared-dependency substitution" whose justifying docs
"appear to be fabricated." Checked directly against this diff's own
doc trail (`docs/decisions/2026-09-22-pyright-clean-refactor.md`,
`docs/plans/2026-09-22-pyright-clean-refactor.md`,
`docs/reviews/2026-09-22-pyright-clean-refactor-plan-review.md`) —
none of the three ever claims `httpx2` is "a declared dependency of
the project"; each correctly scopes the claim to "`mcp==2.1.1`'s own
`Requires-Dist`," which `pip show mcp` confirms is accurate. The
"fabricated" characterization doesn't hold up. The underlying,
narrower observation — `httpx2` wasn't listed in this project's own
`requirements-dev.txt` despite being directly imported now — was real
and independently raised by a second angle too. `[Fixed]`: added an
explicit `httpx2==2.12.0` pin to `requirements-dev.txt` with a comment
explaining why, and a one-line comment at the import site in
`verify_mcp_server.py` warning a future reader/IDE not to "fix" it
back to `httpx` as a typo.

A third angle noted the type-narrowing rewrites change the exception
*type* raised on an already-impossible path from `TypeError` to
`AssertionError` (`verify_period_labels.py`'s rewritten loop,
`test_llm_backends.py`'s `claims_schema.items` access) — confirmed
by two further angles to be cosmetic-only (no test asserts on
exception type at either site, and the paths are provably unreachable
given the data these scripts/tests actually exercise). `[Verified, no
fix needed]` — noted here for precision since "zero logic change" is
about assertion outcomes, not exception-class identity, and three
independent angles converged on flagging it.

## Pass 2/3 — documentation hygiene + architecture/design/modularity (fresh subagent, no memory of the implementation session)

Confirmed clean: every new/edited comment is self-contained (no
external-doc pointers); the two new doc files and the plan-review file
follow `documentation-backlog-hygiene`'s templates; `BACKLOG.md`'s
resolved item was deleted outright (no strikethrough); `PROJECT_INDEX.md`'s
new entry doesn't duplicate the decision file's content.

Two findings, both `[Fixed]`:
1. `docs/reviews/2026-09-22-pyright-clean-refactor-plan-review.md` was
   missing the "this reviews a plan, not a diff" disclaimer this
   project's own prior plan-only review
   (`docs/reviews/2026-09-17-mandatory-plan-review-floor.md`) already
   established as the convention for this exact situation — added the
   same blockquote for consistency.
2. The `httpx`→`httpx2` swap had no inline comment anywhere in the
   file, risking a future accidental revert (the two names differ by
   one character) — added, see Pass 1 above (same fix, found
   independently by both passes).

One item raised as a live disagreement, not a defect: whether the
plan's rejection of a shared `not_none()` test helper still holds
given ~112 call sites share the identical `x = f(...)` /
`assert x is not None` shape. A separate `/simplify`-pass angle
(below) independently re-examined this against the actual diff and
confirmed the original reasoning holds — a helper would only replace
`assert x is not None` with `x = not_none(x)` (no line-count
reduction) while adding an indirection pyright would need to model
specifically to preserve narrowing. `[Verified, no fix needed]` — the
2026-09-22 plan's decision stands, no new evidence overturns it.

## Pass 4 — security review

`/security-review` failed outright: this repo has no `origin` remote
configured at all (`git remote -v` empty, no `refs/remotes/origin/HEAD`),
and the skill's diff mechanism is hardcoded to
`git diff origin/HEAD...`. This is a repo-wide structural gap, not
specific to this diff — the tool cannot run in this repository at all
in its current state. Filed to `BACKLOG.md`.

Performed a manual security assessment in its place, given the diff's
small, mechanical scope: the only site with any security surface is
the `httpx`→`httpx2` swap. Confirmed `httpx2.AsyncClient`'s
construction defaults match `httpx`'s own secure defaults exactly
(`verify=True`, `follow_redirects=False`), and the one construction
site in this diff only passes `headers=...`, overriding neither — no
TLS-verification or redirect-following regression. Every other
changed line is a test-only assertion, cast, or a local-data
comprehension rewrite in an offline verify script with no network/auth
surface. No findings.

## Pass 5 — reuse, simplification, efficiency (`/simplify`)

Ran after Passes 1-3's fixes were already applied, so its 4 parallel
angles (Reuse, Simplification, Efficiency, Altitude) evaluated the
diff including the `httpx2` pin and comment. All four came back clean,
no edits made:

- **Reuse**: no shared narrowing helper exists anywhere in the repo to
  reuse; independently re-confirmed the plan's rejection of a
  `not_none()` helper holds (the repetition is deliberate, already
  reasoned through).
- **Simplification**: the comprehension→loop rewrite is already
  minimal for the constraint (bare `assert` can't live in a
  comprehension); no redundant asserts found (every pair asserts on
  distinct tuple-unpacked variables, not the same value twice).
- **Efficiency**: no re-invoked functions, no added sequential work,
  no closures/leaks; the loop rewrite calls `_duration_days()` exactly
  as many times as the original comprehension did.
- **Altitude**: every assert narrows a genuinely-Optional production
  signature (verified `call_calculate`'s tuple contract directly
  against `agent.py:1064-1121`, and confirmed production code already
  carries the identical assert at `agent.py:2400`) or a third-party
  stub's Optional field (`google-genai`'s `Schema`, click's
  `Command.callback`) this project doesn't control — nothing is a
  bandaid over a signature that should be retyped. Confirmed
  `requirements-dev.txt` (not `requirements.txt`) is the correct
  pin location: `httpx2` is imported only by a dev-only manual verify
  script, never by any production module. One low-value, explicitly
  not-worth-it observation: `verify_tracing.py`'s `_wait_for_observation`
  shares `call_calculate`'s paired-nullable-tuple shape and could
  collapse to one assert if redesigned as `Optional[tuple[...]]` —
  correctly judged not worth the churn for a one-time manual script.

A round where `/simplify` makes no edits is a clean round per this
skill's own rule — no second full round triggered.

## Outcome

Three real findings from Passes 1-3, all fixed: the `httpx2` pin added
to `requirements-dev.txt`, an explanatory comment added at its import
site (found independently by two passes), and the plan-review file's
missing "reviews a plan, not a diff" disclaimer added for consistency
with this project's own prior precedent. One mischaracterization
(a `/code-review` angle's claim that this diff's docs "fabricate" a
dependency claim) was checked directly against the actual doc text and
didn't hold up — recorded above rather than silently dropped. One live
disagreement (the `not_none()` helper) was independently re-examined
and the original design decision reaffirmed, not overturned. Pass 4
(`/security-review`) could not run at all — a repo-wide structural gap
(no `origin` remote), filed to `BACKLOG.md`; a manual security
assessment found no issues in this diff's one security-relevant site
(the `httpx2` swap's TLS/redirect defaults match `httpx`'s own).

Final state: `ruff check .` clean, `pyright .` 0 errors repo-wide,
full suite 707 passing (unchanged), `/simplify` clean on the
fixed diff. Review loop closed after one round.
