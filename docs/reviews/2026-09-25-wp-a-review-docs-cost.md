# Review: WP-A, review and documentation cost

Plan: `docs/plans/2026-09-25-wp-a-review-docs-cost.md`. WP-A is a markdown-only change to
skills, agents, CLAUDE.md files, templates, memories and BACKLOG, with no test suite involved.

It was reviewed under the **old** `independent-review-pass` rules, because the new ones only
take effect once WP-A lands. The change counts as non-code, which calls for a self-check plus
an independent rule-preservation audit, following the 2026-09-25 token-efficiency precedent.

## Round 1

**Passes:**
- A self-check: the YAML frontmatter of the 6 edited skills and agents, and `git status` in
  both repos.
- A rule-preservation audit by `general-purpose` (Opus). It compared HEAD against the working
  tree for every changed file and re-ran the contradiction grep, including over unchanged skills
  and rules.

**Findings:**

1. **High**: the in-flight prompt-audit roadmap requires per-WP plan, review and decision files.
   Later WPs read their eval baselines from those files, but the new ADR-gated rules would stop
   WP6–WP8 from writing them.
   - Where: `docs/plans/2026-09-24-prompt-audit-roadmap.md:25-34,632-638` and
     `docs/plans/2026-09-25-wp6-no-data-message.md`.
   - `[Fixed]`: SEC `CLAUDE.md` now carries an explicit exemption for prompt-audit WP5–WP8. The
     roadmap itself stays unedited.
2. **Med**: the global CLAUDE.md Trivial row said "`/code-review low` if code touched". That
   ignores diff re-classification, so a blast-radius diff could get too little review.
   - `[Fixed]`: the row now adds "(more if the diff re-classifies)".
3. **Low**: global CLAUDE.md is 13288 → 13971 bytes, against a no-net-growth aim.
   - `[Verified, no fix needed]`: recorded with its reason in the decision file.
4. **Low**: the plan paragraph says review files follow "Substantial or multi-session". The
   skills say Substantial only.
   - `[Verified, no fix needed]`: the skills match the roadmap; the plan paragraph was
     loose. The decision file uses the roadmap wording.
5. **Low**: making the commit body the record conflicts with "commit only when asked".
   - `[Fixed]`: the docs skill now says to propose the full message at task end.
6. **Low**: the docs skill rewrite dropped two rules: "grep the archive, never read it whole"
   and "no strikethrough or done-note".
   - `[Fixed]`: a short clause for each is back in the skill.
7. **Low**: the review skill now sends only *deferred* findings to BACKLOG, where the old text
   said *unresolved*.
   - `[Verified, no fix needed]`: the roadmap says "deferred findings still → BACKLOG", and a
     disputed finding gets a review file.
8. **Low**: combining re-classification with the tier table means a small diff (under ~30
   lines, no blast-radius path) gets no `security-reviewer`, even when it touches input
   handling.
   - `[Disputed]`: raised with the user. It follows from the settled decisions ("review depth
     by the actual diff" and "every Standard+ code diff"), so it wasn't changed unilaterally.
9. **Low (nits)**: in `arch-reviewer`, "left alone" had been dropped, and it said "report four
   things" above a list of three.
   - `[Fixed]`.

## Round 2

**Delta:** the round-1 fix lines only. There was no stash snapshot, so the auditor was given
the fixed lines and their findings.

**Passes:** the same audit, by a fresh `general-purpose` (Opus).

**Findings:** all five fixes resolve their findings, and none contradicts the surrounding
rules. Three nits remained, all `[Fixed]`, though nits don't reopen a round:
- "in touched files" restored in `arch-reviewer`;
- two lines reflowed in the docs skill;
- the prompt-audit exemption moved to its own bullet, so readers of the plans and reviews
  rules see it.

## Outcome

- **Status**: the review is closed. Round 2 was clean apart from nits.
- **Open with the user**: finding 8, whether a small re-classified-Trivial diff should still
  get `security-reviewer`.
- **Deferred to the first real Standard task**: the live check. That task's commit body names
  the passes it ran.
