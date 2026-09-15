# Documentation/Changelog/Backlog System Overhaul

## Context

`PROJECT_CONTEXT.md` has grown to 5,703 lines and ~65 sections as one
continuous chronological narrative that is only ever appended to, never
trimmed. It's currently read in full at the start of every session. The
user wants a system modeled on how this session's own auto-memory works:
a small index (like `MEMORY.md`) with one-line entries pointing to
individual files (like the memory files, or like this project's existing
`docs/plans/`/`docs/reviews/` convention), loaded on demand rather than
all at once. Separately, code comments across the repo have accumulated
the same problem — multi-line decision-history narrations embedded in
docstrings and comments (confirmed via audit: `agent.py`, `xbrl_facts.py`,
`mcp_server.py`, `companies.py`, `config.py` all do this) instead of
living in a changelog/plan/review doc.

**Sequencing decision (explicit answer to "what should be done first"):**
the documentation-system redesign must happen first, because the
comment-rewrite task's whole purpose is to *extract* decision-history
content out of comments and *into* the new decision-doc system — that
target has to exist before extraction has anywhere to go. This plan
covers **only** the documentation-system redesign, its `CLAUDE.md`
instruction updates, and migrating `PROJECT_CONTEXT.md`'s existing
content into the new system. The full-codebase comment audit/rewrite is
a deliberately separate, later task/session.

User decisions already made (not re-litigated here):
1. **Unified single index** — one file lists every decision, plan, and
   review as a one-line linked entry, mirroring `MEMORY.md`.
2. **Repurpose `PROJECT_CONTEXT.md` in place, but rename it** — new name:
   **`PROJECT_INDEX.md`** (keeps the "file everyone reads first"
   continuity; `INDEX` signals the new skim-and-jump contract, unlike
   `HISTORY.md` which still implies a narrative, or `DECISIONS_INDEX.md`
   which undersells that it also indexes plans/reviews).
3. **Migrate the full existing history now**, not deferred.
4. **Comment policy**: terse one-line pointers to a decision doc (e.g.
   `# rationale: docs/decisions/2026-09-12-<slug>.md`) are allowed;
   retelling the incident inline is not. (Instruction-only in this plan —
   the actual codebase comment pass is the deferred follow-up.)

**Prior art checked:** Architecture Decision Records (Nygard's original
4-section format, and the fuller MADR variant) are the standard
industry pattern for exactly this problem — a small, dated, per-decision
file. Changesets (a widely-used JS release-management tool) is an even
closer analog: a lightweight per-change markdown file, written while the
change is fresh, later aggregated into a generated changelog — direct
validation that the file-per-decision model is proven, not a novel risk.
Two things adopted from this research: (1) real template files, not just
a prose-described shape (see below); (2) a lean, Nygard-style decision
skeleton over MADR's fuller one, since a paired plan/review already
carries deeper alternatives-analysis when one exists. One thing
deliberately rejected: ADR's standard `NNNN-title.md` numbered-file
convention — diverging in favor of the existing `YYYY-MM-DD-<slug>.md`
scheme already used by `docs/plans/`/`docs/reviews/`, so all three
correlate by date/filename without a separate counter to maintain.

**What this trades away (from independent review):** `docs/plans/` and
`docs/reviews/` already run this exact on-demand-file pattern
successfully with zero index today — extending it with a third
`docs/decisions/` directory is low-novelty. The index file itself is the
one genuinely new component (nothing analogous exists for plans/reviews
today), and it introduces a **recurring sync cost**: every future
decision/plan/review needs its index line added by hand, forever, or the
index silently goes stale. This is the real ongoing price of this
design, not "five artifact types instead of four" — accepted as worth it
given the alternative (a 5,703-line file everyone reads in full) is
worse, but worth naming explicitly rather than treating the index as free.

## New file/directory layout

- **`PROJECT_INDEX.md`** (repo root, `git mv` from `PROJECT_CONTEXT.md`
  to preserve history) — contents, top to bottom:
  1. A short framing blurb: this file is an index, not a changelog; read
     it in full at session start, follow links for detail.
  2. A trimmed **Project Overview**: Goal, Stack, Companies-in-scope,
     one-line current-phase status — static onboarding facts a fresh
     session still needs, kept in place and maintained, not appended to.
  3. **The index proper**: one reverse-chronological line per file that
     exists in `docs/decisions/`, `docs/plans/`, `docs/reviews/`, tagged
     by type, e.g.:
     `- 2026-09-13 [decision] Table-grounding region-scoped redesign — fixes two live eval regressions → docs/decisions/2026-09-13-table-grounding-region-scoped-matching.md`
  4. Nothing else — no inline reasoning, no "Next steps" (that's
     `BACKLOG.md`), no "Design principles" (moves to project `CLAUDE.md`).
- **New directory `docs/decisions/YYYY-MM-DD-<slug>.md`** — one file per
  decision, same convention as `docs/plans/`/`docs/reviews/`. Reuse an
  existing plan/review's slug when a decision pairs with one, so the
  three artifacts correlate by filename alone.
- **Template files, one per artifact type** (`docs/decisions/TEMPLATE.md`,
  `docs/plans/TEMPLATE.md`, `docs/reviews/TEMPLATE.md`) — reversal from
  "describe the shape in prose only." Real-world ADR tooling (MADR,
  adr-tools) ships literal copyable template files, not just a prose
  description, and that's the concrete gap here too: `docs/plans/` and
  `docs/reviews/` already have a consistent structure (verified against
  one representative pair: Context → diagnosis → Decision → Steps →
  Files for plans; title → Pass 1 (self) → Pass 2 (fresh subagent) →
  Live verification → Outcome for reviews) — extract each as an actual
  template file rather than leaving it convention-only.
  **Derive each template from at least 3-4 representative files per
  directory, not just one** — spanning different dates (early/mid/late
  in the 12 plans / 13 reviews on disk) and different change types (a
  bug-fix-driven plan vs. a feature/redesign-driven plan; a review with
  findings vs. a clean pass) — before locking the template's section
  list, so it reflects what's actually common across real files rather
  than one file's idiosyncrasies. If the sampled files disagree on
  structure, use judgment on which sections are load-bearing vs.
  incidental, and note any section made optional in the template because
  it didn't appear in every sample. `docs/decisions/` gets a new
  template with the skeleton below (no existing files to sample from,
  since the directory doesn't exist yet — this one is designed, not
  extracted). A new file in any of the three directories starts as a
  copy of its template, not a blank page. `TEMPLATE.md` itself is
  excluded from the index (it's not a dated entry) and from the
  file-count verification checks.
- **Decision-file skeleton** (`docs/decisions/TEMPLATE.md`): Title / Date
  / Context (what prompted it) / Decision (what was done) / Why
  (non-obvious reasoning — name alternatives considered only when a real
  fork existed, don't force an empty section) / Files touched /
  Verification / Related (links to the plan/review that led here, or a
  prior decision this amends). This is deliberately closer to Nygard's
  original 4-section ADR shape than to full MADR (which adds mandatory
  Decision Drivers / Considered Options / Pros-and-Cons sections) —
  MADR's own docs note its fuller template is a tradeoff (forces
  explicit trade-off analysis, but adds bureaucracy) suited to teams
  documenting weighty architectural calls; most entries here are
  Standard-tier changes where a short paired plan/review (when one
  exists) already carries that fuller analysis, so the decision file's
  job stays "what happened and where to look," not a second copy of a
  trade-off table. (Sources: [ADR Templates](https://adr.github.io/adr-templates/), [About MADR](https://adr.github.io/madr/).)

## `CLAUDE.md` instruction changes

**Budget**: since the whole point of this task is fighting documentation
bloat, the edited step 6 should land at roughly its current length, not
meaningfully longer — trim existing verbose passages (e.g. the current
"one continuous file" prose being inverted, lines 234-241, mostly gets
replaced rather than added to) to offset new rules, rather than
appending net-new bulk. A one-sentence wording fix (like the
delete-on-done clarification) should read as one sentence, not grow into
a new bullet with sub-cases.

**`~/.claude/CLAUDE.md` step 6 ("Documentation and backlog hygiene")**
must end up encoding all of these rules:
- Invert the "one continuous narrative file" model: default is one new
  `docs/decisions/YYYY-MM-DD-<slug>.md` file per Standard+ change, never
  appended to later — a later revisit writes a *new* file and cross-links
  back (`Related: amends <old file>`), matching how `docs/reviews/`
  files are already treated as an immutable historical record.
- Introduce the **index** as a fifth artifact role: one file, read in
  full at session start, containing only static project-overview facts
  plus one terse linked line per decision/plan/review file — never a
  paragraph of reasoning.
- **Session-start behavior**: read the index in full; do not read full
  decision/plan/review history unless a specific entry is relevant.
- **New search-before-you-start rule**: before starting design/debugging
  work on a topic, search the index (and open a linked file if relevant)
  for prior work on the same module/tool/failure mode — same family as
  the existing "check prior art" (step 1) and "check git blame/log"
  (step 9) habits, now extended to the project's own documentation.
- **Decision-file skeleton**, spelled out concretely (see above). When a
  plan/review already exists for the same change, the decision file is a
  short synthesis that links out, not a third retelling.
- **Index maintenance**: add the one-line entry in the same step a new
  decision/plan/review file is written — never batched for later.
- **`BACKLOG.md` done-item rule, tightened and made unambiguous**: when
  an item is done, **delete the line entirely** — no strikethrough, no
  "resolved" annotation left behind. The current wording ("remove from
  backlog") is exactly what's being reinterpreted as strikethrough-and-
  keep today; the new wording must foreclose that reading directly. If
  only part of a multi-part item is resolved, rewrite the line to
  describe only the remaining open part — no decorated hybrid.

**`~/.claude/CLAUDE.md` step 3 (SE principles)** — add a short paragraph:
a terse one-line pointer comment to a decision doc is fine; re-narrating
history/incidents inline in a comment is not — that content belongs in
the decision doc. Frame as an extension of the existing self-documenting-
code principle. Note explicitly this governs *future* comments only; it
does not itself authorize or schedule a pass over existing comments.

**Project `CLAUDE.md`**:
- Update "This project's documentation system" (lines 33-43): five
  artifacts now, `PROJECT_CONTEXT.md` → `PROJECT_INDEX.md`, add
  `docs/decisions/`.
- Line 9's pointer to `PROJECT_CONTEXT.md`'s "Development workflow"
  narrative → repoint to the specific decision file carrying that story,
  or drop if surrounding prose stands alone without it.
- Line 87 ("a `PROJECT_CONTEXT.md` changelog entry... addendum") →
  update to "a new `docs/decisions/` file," drop "addendum" language.
- **New section, "This project's design principles"**: migrate the 4
  bullets from the old "Design principles to carry forward" section
  verbatim (citations non-negotiable, evals before agent, narrow/
  checkable scope, document failure modes) — standing rules, not a
  point-in-time decision or a static fact, so they belong here.

## Migration approach (the ~65 sections)

1. **Build a disposition manifest first** (scratch work, not committed)
   — every one of the 62 headers (9 `##` + 53 `###`) gets one of four
   dispositions: (1) becomes its own `docs/decisions/` file — the
   default for the 53 `###` sections, **but not automatically for every
   one of them**: several sections are only 9-28 lines (e.g.
   `query_chunks.py`, `index_chunks.py`, `companies.py`, the
   `eval_harness.py --ids` filtering note) — a section that thin may not
   justify its own file. Use judgment per section: a short section is
   still fine as its own small file if it's a genuinely standalone
   decision (matches how short some `docs/plans/`/`docs/reviews/` files
   already are), but if two or more adjacent thin sections are really one
   continuous thread of work, group them into a single decision file
   instead of forcing artificial 1:1 splits — flag any such grouping
   explicitly in the manifest rather than deciding silently; (2) folds
   into a sibling section's decision file as a cross-link only, for
   genuine same-thread inline addenda that duplicate a section that
   already exists standalone elsewhere. **Note: no confirmed real example
   of this case was found during planning** — an independent review
   checked the specific case considered during design (a suspected
   2026-09-13 addendum nested inside the 2026-09-12 section) and found
   it's actually a separate sibling `###` section, not a nested addendum.
   Treat disposition (2) as available but rare; if the actual migration
   pass finds no genuine case of it, that's fine — don't force a section
   into this bucket to justify the category's existence; (3) folds into
   `PROJECT_INDEX.md`'s Project Overview or
   project `CLAUDE.md` (Goal/Stack/Companies-in-scope → Overview; 8-week
   plan → retire, fold one status line into Overview; Development-
   workflow's still-current operational facts → project `CLAUDE.md`;
   Design principles → project `CLAUDE.md`'s new section); (4) dissolves
   with no migration — "Code written so far" (empty parent heading) and
   the `<details>` historical-log block inside "Next steps" (verify each
   entry is a redundant pointer to content migrated elsewhere before
   deleting, don't assume).
2. **Dating**: use each section's own ISO date where present. For "Week
   N"-labeled sections with no date, cross-reference `git log` (85
   commits, 2026-08-13 to present) to find the real commit date rather
   than guessing — record provenance in the decision file (e.g. "dated
   via commit `<hash>`, no ISO date in the original heading"). Where
   several Week-labeled sections landed in one squashed commit, use that
   single real date for all and say so explicitly rather than inventing
   distinct dates.
3. **Extraction depth varies**: sections that already cite a paired
   `docs/plans/`/`docs/reviews/` file (roughly 2026-08-20 onward) get a
   short synthesis decision file that links out for detail. Sections
   with no paired plan/review (mostly pre-2026-08-20, plus some later
   Standard-tier changes that never got a saved plan) need faithful,
   substantial content in the decision file since it's the only place
   that information lives.
4. **Cross-check against `BACKLOG.md`'s existing "done" references
   first** — `BACKLOG.md` already names ~5 specific sections as
   resolved (lines 105-111) plus several inline references. Migrate
   those sections first, confirm faithful capture, only then resolve the
   corresponding backlog lines (this ordering is what makes "confirm
   before deleting" mechanical rather than best-effort).
5. **Produce files, then build index, then diff** — write all
   `docs/decisions/*.md` per the manifest, generate `PROJECT_INDEX.md`'s
   entry list mechanically from the manifest plus the 25 existing
   plan/review files, then run the verification checks below.

## `BACKLOG.md` fixes

- Rewrite the top framing to the new unambiguous delete-on-done rule.
- Resolve the strikethrough items found on audit (grep found 5, not the
  4 estimated at investigation time — confirm the true count directly
  when implementing): for each, confirm resolution is captured in a
  migrated decision file, then either delete the line entirely (fully
  resolved, or partially resolved but the open remainder is already
  duplicated elsewhere) or rewrite to a plain non-strikethrough bullet
  describing only a genuinely distinct still-open remainder.
- Delete the stale "DONE — see `PROJECT_CONTEXT.md`" prose block once
  its referenced sections are confirmed migrated; keep only the
  genuinely open bullets beneath it, re-pointed at their new files.
- Sweep remaining `PROJECT_CONTEXT.md` references elsewhere in the file
  and repoint each at its new `docs/decisions/*.md` location.

## Order of operations

1. Create `docs/decisions/` and all three `TEMPLATE.md` files
   (`docs/decisions/`, `docs/plans/`, `docs/reviews/` — the latter two
   extracted from their existing consistent structure across current
   files).
2. Update both `CLAUDE.md` files (defines the target shape first;
   mention the templates exist and should be copied for new files).
3. Build the disposition manifest; date Week-labeled sections via `git
   log`.
4. Cross-check manifest against `BACKLOG.md`'s existing done-references.
5. Write all `docs/decisions/*.md` files.
6. Fold Disposition-3 reference content into `PROJECT_INDEX.md`'s
   Project Overview and project `CLAUDE.md`.
7. `git mv PROJECT_CONTEXT.md PROJECT_INDEX.md`, gut to the Overview
   blurb, append the mechanically-generated index lines.
8. Fix `BACKLOG.md`.
9. Run verification (below).
10. Note for the user (outside repo scope, can't be edited by this
    task): their global auto-memory file
    `reference_project_context_doc.md` and its `MEMORY.md` index line
    should be updated to point at `PROJECT_INDEX.md`'s new role.

## Verification (documentation-only change, no test suite)

- **No-content-lost**: every one of the 62 original headers has a
  non-empty disposition in the manifest (header-level coverage). This
  alone doesn't catch a paragraph silently dropped *within* a retained
  section during rewrite, so add a **rough word-count conservation
  check** per migrated file: for sections with no paired plan/review
  (full faithful migration expected), the new decision file's word count
  should be roughly comparable to the original section's — a large
  unexplained drop is a signal to re-check, not proof of loss by itself.
  For sections with a paired plan/review (synthesis expected, genuinely
  shorter by design), skip this check. On top of the mechanical check,
  spot-check several longer/older sections by re-reading original vs.
  new decision file side-by-side to confirm no concrete fact (root
  cause, rejected alternative, verification number) silently disappeared.
- **Index integrity**: file count in `docs/decisions/` + `docs/plans/` +
  `docs/reviews/` equals the number of index entry lines; every link
  resolves to a real file; every file has exactly one index line.
- **`BACKLOG.md` hygiene**: `grep -n '\[x\]'`, `grep -n '~~'`, and
  `grep -n 'PROJECT_CONTEXT'` over `BACKLOG.md` all return nothing.
- **`CLAUDE.md` coherence**: read both files end-to-end after editing —
  no leftover reference to the old narrative-changelog role, new rules
  don't contradict untouched surrounding prose.
- **Repo-wide sweep**: `grep -rn "PROJECT_CONTEXT"` across the repo
  (`.md` and `.py`), excluding `docs/plans/`/`docs/reviews/` files
  (explicitly immutable historical record per existing convention) —
  any other hit gets re-pointed or justified.
- **Done bar**: all checks above pass; `git status` shows only the
  expected file set changed (`CLAUDE.md` ×2, `BACKLOG.md`,
  `PROJECT_CONTEXT.md`→`PROJECT_INDEX.md` via `git mv`, new
  `docs/decisions/*.md` files); nothing in `docs/plans/`/`docs/reviews/`
  touched.

### Critical files
- `PROJECT_CONTEXT.md` → `PROJECT_INDEX.md`
- `BACKLOG.md`
- `CLAUDE.md` (project)
- `~/.claude/CLAUDE.md` (global)
- `docs/decisions/TEMPLATE.md` (new — designed from the skeleton above,
  no existing files to sample)
- `docs/plans/TEMPLATE.md`, `docs/reviews/TEMPLATE.md` (new — extracted
  by sampling at least 3-4 files each across `docs/plans/`'s 12 files and
  `docs/reviews/`'s 13 files, spanning early/mid/late dates and
  different change types, not just the one pair already read during
  planning: `docs/plans/2026-09-13-table-grounding-region-scoped-matching.md`
  and its paired review)
