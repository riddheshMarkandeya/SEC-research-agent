# Development Workflow — SEC Research Agent (project-specific additions)

Read `~/.claude/CLAUDE.md` first: it has the general workflow and the skills it points to. This
file adds only what's specific to this project and describes current rules. Past decisions,
including how this file got its shape, are in `PROJECT_INDEX.md`'s `Recent` section (grep
`PROJECT_INDEX_ARCHIVE.md` for older ones) and in commit message bodies (`git log --grep`).

## Path-scoped rules (`.claude/rules/`)

These load automatically when a file matching their `paths:` frontmatter is read; each file's
own frontmatter is the only list of those paths. **After a compaction they are summarized away,
so re-read the ones that apply.**

- `live-code-tdd.md`: which files are live-only code under `tdd-live-code-carveout`, and the
  manual-repro-script convention for them.
- `live-eval-verification.md`: which files need a live eval spot-check after any change, the
  Gemini free-tier quota note, and how to record regressions.
- `plan-review-blast-radius.md`: this project's high-blast-radius core. Every entry comes from a
  real incident. A plan touching it gets deeper plan-review scrutiny, a diff touching it gets
  `arch-reviewer` on Opus, and its `paths:` frontmatter doubles as the 90% critical-core
  coverage list (mirrored in `githooks/pre-push`).

These are living lists. When a plan or code review finds a real issue that none of them covers,
add it to the right file in the same change.

No UI exists yet. If one is added, name its live-only surfaces in a new rule file scoped to those
paths, and apply `ui-implementation-guidelines` in full before starting.

## Code checks: all are hard pre-push gates

`githooks/pre-push` blocks any push that adds a violation **anywhere in the repo**, not just in
touched files. Nothing enforces these at commit time. All the tools are pinned in
`requirements-dev.txt`.

- **Lint: `ruff`.** Config lives in `pyproject.toml` `[tool.ruff]`/`[tool.ruff.lint]`. Rules:
  `E`/`F`/`W` plus the complexity rules `C90`/`PLR0911`/`PLR0912`/`PLR0913`/`PLR0915`.
  `ruff check .` must report 0 errors.
- **Types: `pyright` in basic mode.** Config lives in `pyproject.toml` `[tool.pyright]`.
  `pyright .` must report 0 errors. Strict mode was tried and rejected: about 94% of its errors
  were noise from dict-shaped data flow. Revisiting it is a `BACKLOG.md` item.
- **Coverage: `pytest-cov` + `diff-cover`.** Config lives in `pyproject.toml`
  `[tool.coverage.*]`. It measures branch coverage; `diff-cover`'s own `--branch-coverage` flag
  is deliberately left off. The gate runs `pytest --cov=. --cov-report=xml`, then `diff-cover
  coverage.xml --compare-branch=origin/master` with two bars: `--fail-under=80` for ordinary
  files and `--include <critical-core paths> --fail-under=90` for the critical-core list in
  `plan-review-blast-radius.md`.
- **Live-only lines** (real HTTP, Chroma or LLM calls, per `.claude/rules/live-code-tdd.md`) are
  marked `# pragma: no cover` and excluded from both bars. This is
  required: without it the bar either keeps failing on legitimate changes or pushes people toward
  mocking the network or DB, which `tdd-live-code-carveout` rejects. The remaining pre-existing
  gap is tracked in `BACKLOG.md`.
- `independent-review-pass` needs no separate ruff or pyright step: the manual pre-commit checks
  below satisfy its prerequisites, and the gate backs them up.

**Before every commit, run these by hand.** A commit that fails lint, types or tests is otherwise
only caught at the next push, across a batch that's harder to bisect:

- `ruff check .` (add `--fix` for the mechanical subset)
- `pyright .`
- `pytest --cov=. --cov-report=term-missing -q`
- then compare the `Missing` column for the lines you changed against the 80%/90% bar.

`--no-verify` bypasses either hook (`git push --no-verify`, `git commit --no-verify`). The same
rule covers both: fix the issue. Bypass only for a genuine tooling false positive, and file a
`BACKLOG.md` item when you do. Never use it as a habit.

## Comment hygiene

Every new or edited comment follows the global self-contained-comment rule. No tool can measure
this, so it stays scoped to changed files permanently. Leave a pre-existing comment in a touched
file alone unless the function or block it's attached to is meaningfully changed.

## Documentation system

This project's version of the records from `documentation-backlog-hygiene`:

- **`PROJECT_INDEX.md`**: a framing blurb, a static Project Overview, then `## Recent`, with one
  reverse-chronological line per file in the three `docs/` directories below.
  - Read `Recent` in full at session start; follow links only when relevant.
  - Cap: **50 entries**. When exceeded, trim to 40 and move the oldest lines verbatim into
    `PROJECT_INDEX_ARCHIVE.md`. Grep the archive; never read it in full.
- **Commit message body**: the default record of a change (why / verified / follow-ups).
- **`docs/decisions/YYYY-MM-DD-<slug>.md`**: only for a change that passes the ADR gate (hard to
  reverse, surprising, a real trade-off), plus every live-found regression, which is exempt from
  the gate (`live-eval-verification.md`). Write it once and never append. A revisit writes a new
  file that links back under `Related`.
- **`docs/plans/YYYY-MM-DD-<slug>.md`**: saved plans, for Substantial or multi-session work only.
  The plan review and review log live inside the plan.
- **Exemption from the decision, plan and review rules here**: the prompt-audit roadmap's work packages
  (`docs/plans/2026-09-24-prompt-audit-roadmap.md`, WP5–WP8) keep the per-WP plan, review and
  decision files that roadmap specifies, because later WPs read their eval baselines from them.
- **`docs/reviews/YYYY-MM-DD-<slug>.md`**: only for Substantial work, or when a finding is
  deferred or disputed.
- Start each of these three from its directory's `TEMPLATE.md`.
- **`BACKLOG.md`**: open items tagged `**[type, priority, effort]**` (legend at its top). Delete
  an item's line when it's done. **Grep it by tag or keyword; don't read it whole.** It's 40KB+.

**Before design or debugging work**, search `Recent` for prior work on the same module, tool or
failure mode, and grep the archive if the work might be older. Also run `git log --grep=<module>`:
Standard changes leave no index line, only a commit body.

## Hooks

Git hooks live in `githooks/`. A fresh clone runs `git config core.hooksPath githooks` once. No
Claude Code hooks are used.

`githooks/pre-commit` runs `scripts/check_docs_health.py` on the staged tree:

- **Blocks** when a `docs/decisions|plans|reviews/*.md` file has no `` → `<path>` `` entry in
  `PROJECT_INDEX.md` or its archive.
- **Blocks** when an entry names a file that doesn't exist.
- **Warns** when `## Recent` is over 50 entries.
- **Fails open** with a warning when git or the index can't be read, or when no Python 3.10+ is
  found.

It checks the whole staged tree, so a miss that skipped pre-commit (`--no-verify`, merge, rebase,
cherry-pick) is caught by the next ordinary commit. `githooks/pre-push` runs the code checks above.

## Design principles

- **Citations are non-negotiable.** In finance, "trust me" isn't good enough. Every numeric
  claim must trace to a specific filing and section, or the agent refuses.
- **Evals before agent.** Measure first, then iterate.
- **Narrow scope, checkable outputs.** Numeric answers with exact figures are far easier to grade
  objectively than open-ended summaries.
- **Document failure modes.** The value of the write-up is "here's what broke and how I found it",
  not "here's clean code".

# Compact instructions

In addition to the global Compact instructions, the summary must also keep exact eval figures:
pass counts, agent hashes, commit SHAs of eval snapshots, and Gemini quota state.
