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
for the pre-commit-to-pre-push move). Nothing enforces `ruff check . --fix`
before committing anymore — run it manually as a matter of discipline;
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
for the pre-commit-to-pre-push move). Run `pyright .` manually before
committing as a matter of discipline — nothing enforces it until push
time anymore. `independent-review-pass` doesn't need its own separate
pyright step since the gate covers it. Revisiting strict mode is still
tracked as its own `BACKLOG.md` item.

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
blocking any push below either threshold. Run these manually before
committing as a matter of discipline — nothing enforces them until
push time anymore. Live-only lines (real HTTP/Chroma/LLM calls, per
`.claude/rules/live-code-tdd.md`) are marked
`# pragma: no cover` in source and excluded from both checks — this is
required, not optional, since without it the bar would either
chronically fail on legitimate changes to those functions or pressure
contributors toward mocking the network/DB itself, the exact
anti-pattern `tdd-live-code-carveout` rejects. See `BACKLOG.md` for the
remaining pre-existing gap tracked for opportunistic closure.

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

`.claude/settings.json` wires a `PreToolUse` hook
(`scripts/check_docs_sync.py`) that **blocks** (exit code 2) a `git
commit` when a new `docs/decisions/*.md` file is staged without
`PROJECT_INDEX.md` also staged. Only fires for commits through Claude
Code's own Bash tool, and only reliably catches staging/committing as
separate tool calls. See
`docs/decisions/2026-09-15-claude-md-restructure.md`.

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
