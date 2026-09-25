# Review: promote context-management trial (plan review)

Plan: `docs/plans/2026-09-25-promote-context-management.md`. This was the first run of the new
`plan-reviewer` agent (Opus, fresh context). It used about 29k tokens and followed the output
contract, ending in a `checked:` line and a verdict.

## Pass 1: plan review (plan-reviewer agent)

1. **Med**: the "compact at an earlier break when nearing the window" trigger isn't actionable,
   because Claude can't reliably see its own token count or run `/compact`. `[Fixed]`: the
   trigger is now observable. For plans with 4 or more implementation steps, offer the line once
   after a green test step around the midpoint. Compact instructions are the stated safety net.
2. **Med**: nothing verified that `# Compact instructions` in the user-level CLAUDE.md is
   honored. The docs only mention the project-root file. `[Fixed]`: a direct test ran before the
   project list was shrunk. A temporary PINEAPPLE line was added, and a headless session plus
   `/compact` ran in a throwaway directory. The summary began with "PINEAPPLE", so it's honored.
   The marker was removed.
3. **Med**: the generic list still had project-specific details (`docs/plans/...`, "eval").
   `[Fixed]`: the global list is now project-neutral (the repo plan copy "if the project keeps
   one"), and eval figures became a project-only addition.
4. **Low**: two Compact sections could read as rivals, and the "re-read rules" note appeared in
   three places. `[Fixed]`: the project section is worded "in addition to the global…", and the
   §6 copy of the note was dropped.
5. **Low**: this reverses two recorded choices without saying so. `[Fixed]`: the decision file
   names both and says what changed.
6. **Low**: setting `showClearContextOnPlanAccept` globally is harmless, since it only adds a
   prompt option. `[Verified, no fix needed]`.
7. **Low**: the plan's byte-size check was arbitrary. `[Fixed]`: dropped in favor of the
   rule-presence diff check.

## Outcome

All findings were folded in before approval. The verdict: sound once findings 1–3 were
addressed, which they were.
