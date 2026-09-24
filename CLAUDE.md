# Development Workflow — SEC Research Agent (project-specific additions)

See `~/.claude/CLAUDE.md` for the general workflow (scope tiers, SE
principles, error handling, git-as-inspection-tool, revisiting prior
decisions, pushing back with reasoning) plus the situational skills it
points to (`design-before-building`, `tdd-live-code-carveout`,
`debugging-discipline`, `documentation-backlog-hygiene`,
`independent-review-pass`, `ui-implementation-guidelines`) — read that
first. This file covers only what's specific to this project, layered on
top of those generic rules. For how this file got its current shape, or
any other past decision, search `PROJECT_INDEX.md`'s `Recent` section
(and `PROJECT_INDEX_ARCHIVE.md` if it's older) rather than looking here
— this file describes current rules only.

## This project's live-code TDD carve-out

The concrete list of which files count as "live-only code" under the
`tdd-live-code-carveout` skill, and the manual-repro-script convention
for them, now lives in `.claude/rules/live-code-tdd.md` — loaded
automatically whenever `edgar_ingest.py`, `xbrl_facts.py`,
`index_chunks.py`, `retrieval.py`, `agent.py`, or `llm_backends.py` is
touched.

No UI exists in this project today; if one is added, name its concrete
live-only surfaces in a new rule file scoped to those paths and apply
the `ui-implementation-guidelines` skill in full before starting that
work.

## This project's linter

Uses **`ruff`** (`requirements-dev.txt`; config in `pyproject.toml`'s
`[tool.ruff]`/`[tool.ruff.lint]`). Rules: `E`/`F`/`W` plus
`C90`/`PLR0911`/`PLR0912`/`PLR0913`/`PLR0915` (modularity/complexity).
History: `docs/decisions/2026-09-15-adopt-ruff-linter.md`,
`2026-09-21-ruff-complexity-refactor.md`.

**Current stage: hard pre-push gate** — `ruff check .` must be 0
errors full-repo; `githooks/pre-push` blocks any push that introduces a
new violation anywhere, not just in touched files (see
`docs/decisions/2026-09-21-ruff-pre-commit-gate.md`,
`docs/decisions/2026-09-22-coverage-baseline-close-and-hard-gate.md`
for the pre-commit-to-pre-push move). Nothing enforces `ruff check .`
before committing anymore — see "Manual checks before committing" below.
`independent-review-pass` doesn't need its own separate ruff step
since the gate covers it, just later than a commit now.

## This project's type checker

Uses **`pyright`** in **basic mode** (`requirements-dev.txt`; config
in `pyproject.toml`'s `[tool.pyright]`). Strict mode was tried and
rejected (~94% noise from dict-shaped data flow) — see
`docs/decisions/2026-09-15-adopt-pyright.md`.

**Current stage: hard pre-push gate** — `pyright .` must be 0 errors
full-repo; `githooks/pre-push` blocks any push that introduces a new
error anywhere, not just in touched files (see
`docs/decisions/2026-09-22-pyright-pre-commit-gate.md`,
`docs/decisions/2026-09-22-coverage-baseline-close-and-hard-gate.md`
for the pre-commit-to-pre-push move). Nothing enforces `pyright .`
before committing anymore — see "Manual checks before committing" below.
`independent-review-pass` doesn't need its own separate pyright step
since the gate covers it. Revisiting strict mode is still tracked as
its own `BACKLOG.md` item.

## This project's test coverage

Uses **`pytest-cov`**/**`diff-cover`** (`requirements-dev.txt`; config
in `pyproject.toml`'s `[tool.coverage.run]`/`[tool.coverage.report]`).
Branch coverage (since 2026-09-22, after measuring the real impact
first — see `docs/decisions/2026-09-22-coverage-baseline-close-and-hard-gate.md`,
amending `docs/decisions/2026-09-22-adopt-pytest-coverage.md`'s
original line-coverage choice). `diff-cover`'s own separate
`--branch-coverage` flag is deliberately not enabled.

**Current stage: hard pre-push gate** — `pytest --cov=. --cov-report=xml`
then `diff-cover coverage.xml --compare-branch=origin/master --fail-under=80`
(ordinary files) and `--include <critical-core paths> --fail-under=90`
(critical-core files — see `.claude/rules/plan-review-blast-radius.md`'s
`## Coverage bar` section for the exact list, reused from that file's
own `paths:`, not restated here) all run in `githooks/pre-push`,
blocking any push below either threshold. Nothing enforces these before
committing anymore — see "Manual checks before committing" below.
Live-only lines (real HTTP/Chroma/LLM calls, per
`.claude/rules/live-code-tdd.md`) are marked
`# pragma: no cover` in source and excluded from both checks — this is
required, not optional, since without it the bar would either
chronically fail on legitimate changes to those functions or pressure
contributors toward mocking the network/DB itself, the exact
anti-pattern `tdd-live-code-carveout` rejects. See `BACKLOG.md` for the
remaining pre-existing gap tracked for opportunistic closure.

## Manual checks before committing

Since `docs/decisions/2026-09-22-coverage-baseline-close-and-hard-gate.md`
moved every code check to `githooks/pre-push`, only the docs-index check
(see "This project's hooks" below) runs at commit time — a commit that
fails lint, type checks or tests is only caught the next time someone
pushes, possibly several commits later, across a batch that's harder to
bisect. Run all four manually before every commit, as a matter of
discipline, not because anything currently enforces it:

- `ruff check .` (add `--fix` to auto-apply the mechanical subset)
- `pyright .`
- `pytest --cov=. --cov-report=term-missing -q`
- Compare the printed per-file coverage against the 80%/90% diff-scoped
  bar `githooks/pre-push` enforces at push time (ordinary files vs. the
  critical-core list above) — `diff-cover` itself only runs at push, but
  a rough read of which lines you just added/changed against the
  `Missing` column catches most shortfalls before they reach that gate.

`--no-verify` bypasses either hook (`git push --no-verify` for pre-push,
`git commit --no-verify` for pre-commit). Same rule for both: fix the
issue, or bypass and file a `BACKLOG.md` item for a genuine tooling
false positive, never as a routine habit.

## This project's comment hygiene

Every new or edited comment must be self-contained, per global
`CLAUDE.md`'s rule (never a pointer/link to an external doc — see
`docs/decisions/2026-09-15-revoke-comment-pointer-convention.md`). No
tool measures this mechanically, so there's no gate to run or migrate
to; it's changed-files-scoped permanently. A pre-existing comment in a
touched file is left alone unless the function/block it's attached to
is otherwise meaningfully touched. Audit history:
`docs/decisions/2026-09-15-comment-audit-concluded.md`.

## This project's documentation system

The `documentation-backlog-hygiene` skill's five-artifact template,
named concretely here:

- **`PROJECT_INDEX.md`** (repo root) — the index: a short framing blurb,
  a trimmed Project Overview (static facts only, no "current status"
  prose), then a `## Recent` section with one reverse-chronological
  line per file in the three directories below. Read `Recent` in full
  at session start; follow a linked file only when relevant. Capped at
  **50 entries** (trimmed to 40 when exceeded, oldest cut verbatim into
  `PROJECT_INDEX_ARCHIVE.md`, which is grepped, never read in full).
- **`docs/decisions/YYYY-MM-DD-<slug>.md`** — one file per Standard+
  change, written once and never appended to; a revisit writes a *new*
  file and cross-links back via `Related`. Copy
  `docs/decisions/TEMPLATE.md` to start one.
- **`docs/plans/YYYY-MM-DD-<slug>.md`** — saved plans. Copy
  `docs/plans/TEMPLATE.md`.
- **`docs/reviews/YYYY-MM-DD-<slug>.md`** — saved review findings. Copy
  `docs/reviews/TEMPLATE.md`.
- **`BACKLOG.md`** — open items, tagged `**[type, priority, effort]**`
  (legend at its own top). When done, delete the line entirely.

**Keeping `.claude/rules/*.md` current**: living lists (`live-code-tdd.md`,
`live-eval-verification.md`, `plan-review-blast-radius.md`), not
one-time snapshots. When a plan or code review finds a real issue not
already covered by one of these rules, add it to the relevant rule
file as part of that same change.

**Before design/debugging work**: search `PROJECT_INDEX.md`'s `Recent`
for prior work on the same module/tool/failure mode, and grep
`PROJECT_INDEX_ARCHIVE.md` if it might be older.

## This project's hooks

Git hooks live in `githooks/`. A fresh clone runs
`git config core.hooksPath githooks` once. No Claude Code hooks are used.

`githooks/pre-commit` runs `scripts/check_docs_health.py` against the
staged tree:

- **Blocks** when a `docs/decisions|plans|reviews/*.md` file has no
  entry (a line ending `` → `<path>` ``) in `PROJECT_INDEX.md` or its
  archive.
- **Blocks** when an entry names a file that doesn't exist.
- **Warns** when `## Recent` is over its 50-entry cap.
- **Fails open**, with a warning, if git or the index can't be read, or
  no Python 3.10+ interpreter is found.

It checks the whole staged tree, so a miss committed by a path that
skips pre-commit (`--no-verify`, merge, rebase, cherry-pick) is caught
by the next ordinary commit. `githooks/pre-push` runs the code checks
above. See `docs/decisions/2026-09-23-docs-index-pre-commit.md`.

## Context management (trial)

Project-local trial; promotion to global `CLAUDE.md` is tracked in
`BACKLOG.md`. `showClearContextOnPlanAccept` is on, so an approved plan
can be implemented from a cleared context holding only the plan text:

- **Plans are self-contained.** Before `ExitPlanMode`, fold the
  plan-review findings and the user's decisions into the plan. Step 1 of
  every approved plan saves it to `docs/plans/` from `TEMPLATE.md`.
- **Implementation → review boundary.** In interactive Standard+ tasks,
  once implementation is done and the full suite passes, stop before
  `independent-review-pass` and give the user a ready-to-paste
  `/compact Keep: plan file path, decisions and why, files changed, review passes done/pending. Drop: exploration, dead ends.`
  In `/goal` or other autonomous runs, note the line and continue.

## Spot-check evals and live verification beyond TDD

The concrete rule for which files require a live eval spot-check after
any change, the Gemini free-tier quota-awareness note, and the
regression-recording convention now live in
`.claude/rules/live-eval-verification.md` — loaded automatically
whenever `numeric_utils.py`, `agent.py`, or `retrieval.py` is touched.

## Independent plan review for high-blast-radius changes

Per `design-before-building`'s non-tier-gated exception: the concrete
list of which functions count as this project's high-blast-radius core
— where a change gets the one independent-subagent plan-review step
even at Standard tier — now lives in
`.claude/rules/plan-review-blast-radius.md`, loaded automatically
whenever `agent.py`, `llm_backends.py`, `xbrl_facts.py`, `formulas.py`,
`retrieval.py`, or `numeric_utils.py` is touched. Every entry there is
grounded in a real incident, not a speculative "this file feels
important" argument — see that file for which.

## This project's design principles

Standing rules this project holds itself to, not point-in-time decisions
— migrated here from the old `PROJECT_CONTEXT.md`'s "Design principles
to carry forward" section:

- **Citations are non-negotiable.** In finance, "trust me" isn't good
  enough. Every numeric claim must trace to a specific filing + section,
  or the agent refuses.
- **Evals before agent.** Measure first, then iterate.
- **Narrow scope, checkable outputs.** Numeric answers with exact
  figures are far easier to grade objectively than open-ended summaries.
- **Document failure modes.** The write-up value is in "here's what
  broke and how I found it," not "here's clean code."
