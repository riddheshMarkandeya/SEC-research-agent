# Review: context-management trial + SessionStart docs-health audit

Plan: `docs/plans/2026-09-23-context-management-hooks.md`. Adds
`showClearContextOnPlanAccept`, two trial CLAUDE.md rules, and
`scripts/check_docs_health.py` wired as a SessionStart hook; trims the
index's `## Recent` to 40. Suite before this diff: 766 tests.

Pre-review gate: `ruff check .` clean, `pyright .` 0 errors, 791 passed.

## Round 1

### Pass 1 — correctness (`/code-review`, medium)

- **[Fixed]** `main()` caught only `OSError`. A non-UTF-8 index (e.g. saved
  by PowerShell's `Set-Content`) raises `UnicodeDecodeError`, which would
  crash the hook with exit 1 and nothing in the session. It now degrades to
  reported context like `OSError`. Regression test added, red first.
- Verified, no fix needed: quoted `${CLAUDE_PROJECT_DIR}` with spaces, CRLF
  index, the `## Recent` inside a blockquote, `json.dumps` escaping of
  non-ASCII.

### Passes 2+3 — doc/comment hygiene, architecture (one fresh subagent)

- **[Fixed, Low→real]** An index entry matched any backticked occurrence of
  the path, so a backticked mention in another entry's prose counted as
  indexed. Now only the backticked path after a line's trailing `→` counts
  (all 152 existing entries use that form). Regression test added, red
  first.
- **[Fixed, Med]** The decision file retold the plan review's PostToolUse
  rejection and the script's docstrings; cut to a synthesis that links out.
- **[Fixed, Low]** Two new index lines carried reasoning; trimmed.
- **[Fixed, Low]** Test docstring described process ("get full TDD").
- **[Fixed, Low]** Decision file cited a mid-edit "54 entries" count.
- Verified clean: index trim lost nothing (149 at HEAD + 3 new = 152, 0
  removed per `comm`, 15 moved verbatim in order); comments self-contained;
  BACKLOG tags valid; CLAUDE.md claims match the code; the script follows
  `check_docs_sync.py`'s idiom; no shared helper warranted; performance
  trivial for a per-session hook.

### Pass 4 — security (fresh subagent, OWASP-style checklist)

No high-confidence findings. Checked: hook-command quoting/injection, fixed
file reads with no traversal, no eval/subprocess/deserialization, file
contents never injected into context (only doc paths, counts and a local
exception message), output built with `json.dumps`.

### Pass 5 — `/simplify` (reuse, simplification, efficiency, altitude)

- Reuse, efficiency: clean.
- Simplification, applied: `unindexed_docs` loop → comprehension; the two
  prose-mention tests merged into one parametrized test; the `startswith`
  label test folded into the over-cap test; a `_context(out)` test helper;
  `_make_repo(archive_text=None)` instead of write-then-unlink; the
  non-UTF-8 fixture reduced to `b"\x81"`.
- Simplification, skipped: dropping backslash normalization in
  `unindexed_docs`. `_list_docs` already returns POSIX paths, but the pure
  function accepting either form was a plan-review requirement.
- **[Deferred — filed to BACKLOG.md, `design, Low, Standard`]** Altitude: a
  `githooks/pre-commit` running `unindexed_docs` on staged files would fix
  the chained-commit miss at its root and give "indexed" one definition
  instead of two. It changes `check_docs_sync.py` and runs against the
  2026-09-22 move of all checks to pre-push, so it's the user's call.

Gate re-run after pass 5: `ruff` clean, `pyright` 0 errors (after typing
`_make_repo`'s `archive_text: str | None`), 792 passed, 100% line and branch
coverage on `check_docs_health.py`.

## Round 2 (on round 1's fixes)

- Pass 1 (`/code-review`, low): clean.
- Passes 2+3 (fresh subagent): three Low doc findings, all **[Fixed]**.
  - The decision file still said "backticked entry", the old matching rule.
  - Its entry counts went stale once this review's own index line was added.
    They're now stated as taken at trim time.
  - Two paragraphs weren't re-wrapped after edits: the script docstring and
    the CLAUDE.md hooks paragraph.
  - Verified: every `- ` line in the index (41) and archive (112) ends in the
    `→` + backticked-path form, so the stricter regex has no false positives.
    The one other `→` hit is a prose line that doesn't end that way.
- Pass 4 (fresh subagent): no high-confidence findings. The regex has no
  nested quantifiers (linear time), and exception text reaches context only
  through `json.dumps`.
- Pass 5 (`/simplify`): no edits. Two proposals were skipped.
  - Move TEMPLATE/backslash handling into `_list_docs`: skipped, same
    disposition as round 1.
  - `RECENT_CAP`/`RECENT_TRIM_TARGET` duplicate CLAUDE.md's numbers: the only
    fix would be a pointer comment, which the comment rule forbids.

**Loop stopped after round 2, short of the two-clean-rounds cap.** Round 2's
only findings were doc wording and wrapping. Its only code change was
re-wrapping a docstring, which `ruff`, `pyright` and the suite re-verified. A
third five-pass round over a docstring re-wrap was judged not worth it. This
is flagged to the user rather than silently skipped.

## Live verification

Superseded: the SessionStart hook was replaced by a pre-commit check before
live verification. See `docs/decisions/2026-09-23-docs-index-pre-commit.md`.

## Outcome

- **Shipped:** the setting, the trial rules, and the SessionStart audit.
  `ruff` is clean, `pyright` reports 0 errors, and 792 tests pass (766
  before; 26 new). `check_docs_health.py` has 100% line and branch coverage,
  and the audit is silent on the real repo.
- **Open in `BACKLOG.md`:**
  - `design, Low, Standard`: consolidate into a git pre-commit hook. The
    user took this up immediately, which replaced the SessionStart hook.
  - `design, Low, Trivial`: promote the trial rules to global.
