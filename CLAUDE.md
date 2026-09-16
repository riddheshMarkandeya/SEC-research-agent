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

The `independent-review-pass` skill's static-analysis requirement, named
concretely: this project uses **`ruff`** (`requirements-dev.txt`,
config in `pyproject.toml`'s `[tool.ruff]`/`[tool.ruff.lint]`). Rule
selection: `E`/`F`/`W` (standard hygiene) plus `C90`/`PLR0911`/
`PLR0912`/`PLR0913`/`PLR0915` (the modularity-relevant categories —
cyclomatic complexity, too-many-returns/branches/arguments/statements).
See `docs/decisions/2026-09-15-adopt-ruff-linter.md` for the full
rationale and the current 155-violation baseline (dominated by `E501`
on deliberately-long system-prompt/tool-schema strings and single-line
test-fixture dicts — low-value noise, not a real modularity signal;
the 11 `C90`/`PLR09xx` hits are the genuine ones, concentrated in
`agent.py`'s largest functions).

**Current rollout stage: changed-files-scoped, not a pre-commit gate.**
Run `ruff check <changed files> --fix` as part of every
`independent-review-pass` (apply safe auto-fixes; whatever remains in a
line the current change actually added or modified must be fixed by
hand before calling the work done; a violation in a touched file but on
an untouched line is pre-existing debt — leave it, log it to
`BACKLOG.md` once per file if not already tracked). Do **not** run
`ruff check .` unscoped and try to fix everything it finds — the
baseline is large and known, and fixing it wholesale is explicitly out
of scope until the migration below. **Migrate to a hard pre-commit
gate** (alongside the existing pytest hook) once enough of the codebase
is clean that a full-repo run wouldn't be dominated by pre-existing
debt — tracked as its own `BACKLOG.md` item until then.

## This project's type checker

The `independent-review-pass` skill's static-analysis requirement,
extended: this project also uses **`pyright`** in **basic mode**
(`requirements-dev.txt`, config in `pyproject.toml`'s `[tool.pyright]`).
Strict mode was tried first and rejected — its real baseline was 4,655
errors, ~94% Unknown-type-propagation noise from this codebase's
dict-shaped data flow, not real gaps. Basic mode's baseline (154 errors)
was comparable in scale to ruff's own 155-violation baseline; see
`docs/decisions/2026-09-15-adopt-pyright.md` for the full comparison and
rationale. The 7 core modules named in the live-code-TDD section above,
plus `tracing.py`, are clean under basic mode as of adoption; the
remaining baseline (117 errors) is entirely in test files and manual
verify scripts under `tests/`.

**Current rollout stage: changed-files-scoped, not a pre-commit gate** —
same stage and same migration trigger as ruff (see above): run
`pyright <changed files>` as part of every `independent-review-pass`;
a violation in a touched file but on an untouched line is pre-existing
debt, left in place. Do **not** run `pyright` unscoped across the whole
repo and try to fix everything it finds. **Migrate to a hard
pre-commit gate** alongside ruff's own eventual migration (tracked as
one shared `BACKLOG.md` item) once enough of the codebase is clean.
Revisiting strict mode is a separate, explicitly tracked `BACKLOG.md`
item — not automatic, since the last attempt showed it needs either a
real reduction in the codebase's untyped-dict data flow first, or a
scoped-down strict preset, neither of which happened in this adoption.

## This project's documentation system

The `documentation-backlog-hygiene` skill's five-artifact template,
named concretely here. As of the 2026-09-14 documentation-system
overhaul, this project moved from one continuously-appended narrative
changelog to one new dated file per decision, indexed rather than read
in full:

- **`PROJECT_INDEX.md`** (repo root) — the index: a short framing blurb,
  a trimmed Project Overview (Goal/Stack/Companies-in-scope — static
  facts only, deliberately no "current status" prose, which is exactly
  the kind of narrative that grew the old file to 5,703 lines), then a
  `## Recent` section with one reverse-chronological line per file in
  the three directories below. Read `Recent` in full at session start;
  follow a linked file only when it's relevant to the task at hand.
  Formerly `PROJECT_CONTEXT.md`, the old narrative changelog — renamed
  and repurposed, not appended to going forward. `Recent` is capped at
  **50 entries** (trimmed back to 40 whenever it's exceeded, oldest
  entries cut verbatim into `PROJECT_INDEX_ARCHIVE.md`) so the
  session-start read stays a fixed, small cost forever regardless of
  total project history — the same failure mode that produced this
  whole system, one level removed, caught before it recurred.
  `PROJECT_INDEX_ARCHIVE.md` is **never read in full**: grep it (ticker,
  module/file name, tool name, failure-mode phrase) when a topic might
  be older than what's in `Recent`.
- **`docs/decisions/YYYY-MM-DD-<slug>.md`** — one file per Standard+
  change, written once and never appended to; a later revisit writes a
  *new* file and cross-links back via its own `Related` section. Copy
  `docs/decisions/TEMPLATE.md` to start one.
- **`docs/plans/YYYY-MM-DD-<slug>.md`** — saved plans. Copy
  `docs/plans/TEMPLATE.md` to start one.
- **`docs/reviews/YYYY-MM-DD-<slug>.md`** — saved review findings. Copy
  `docs/reviews/TEMPLATE.md` to start one.
- **`BACKLOG.md`** — open items, tagged `**[type, priority, effort]**`
  per the skill's convention (legend at `BACKLOG.md`'s own top). When an
  item is done, delete its line entirely — no strikethrough, no
  "resolved" annotation kept.

**Before starting design/debugging work on a topic**: search
`PROJECT_INDEX.md`'s `Recent` section for prior work on the same
module/tool/failure mode (free — it's already in context from the
session-start read) and open the linked file if one looks relevant; if
the topic might be older than what's in `Recent`, grep
`PROJECT_INDEX_ARCHIVE.md` too rather than assuming it isn't there — the
same "check prior art" discipline the `design-before-building` skill
already applies to the outside world, extended to this project's own
history.

## This project's hooks

`.claude/settings.json` wires a `PreToolUse` hook
(`scripts/check_docs_sync.py`) that **blocks** (exit code 2) a `git
commit` when a new `docs/decisions/*.md` file is staged without
`PROJECT_INDEX.md` also staged — a mechanical safety net for the index
part of the documentation-hygiene convention above. Non-blocking wasn't
achievable (`PreToolUse` can't both allow a tool call and surface a
message to Claude in the same turn), so this is a real gate, scoped
narrowly to that one exact mismatch. It only fires for commits made
through Claude Code's own Bash tool, not commits run directly from a
terminal outside a session, and only reliably catches the case where
staging and committing are separate tool calls (a single chained
`git add -A && git commit` is checked against whatever was already
staged before that command ran). See
`docs/decisions/2026-09-15-claude-md-restructure.md`.

## Spot-check evals and live verification beyond TDD

The concrete rule for which files require a live eval spot-check after
any change, the Gemini free-tier quota-awareness note, and the
regression-recording convention now live in
`.claude/rules/live-eval-verification.md` — loaded automatically
whenever `numeric_utils.py`, `agent.py`, or `retrieval.py` is touched.

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
