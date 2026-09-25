# Review: read/diff/cache habits, status line, recurring retro

Plan: `docs/plans/2026-09-25-read-diff-cache-habits.md`. There's one code change,
`~/.claude/scripts/statusline.js` with its tests, covered by 11 `node:test` cases. The rest is
markdown and config (self-checked). This was the first real code review using the new reviewer
agents.

## Plan review (plan-reviewer agent, Opus)

1. **Med**: the retro item duplicated the Pilot item. `[Fixed]`: the first retro closes the
   Pilot, and the retro lives in the same backlog section.
2. **Med**: the trace-helper item duplicated `BACKLOG.md:261`. `[Fixed]`: the existing line was
   rewritten.
3. **Med**: the Recurring exception conflicts with the "delete when done" rule, and nothing
   surfaces the due date. `[Fixed]`: the exception is in the header, each run writes a decision
   file, and the due date is in a memory file.
4. **Med**: the "warm 38m" countdown goes stale while idle. `[Fixed]`: it shows an absolute
   time.
5. **Med**: `/effort` might rebuild the cache like `/model` does. `[Fixed]`: the docs say it
   keeps the cache on Opus 5.5 and Fable 5.1 and rebuilds it elsewhere; the rule says that.
6. **Low**: two reading rules were too broad (memory files; re-reading after compaction).
   `[Fixed]`.
7. **Low**: the hard-coded /300k denominator is wrong for `--autocompact` launches. `[Fixed]`:
   the count is shown plain.
8. **Low**: the Opus effort override is redundant. `[Verified, no fix needed]`: kept as a pin.

## Round 1 (statusline.js)

- **Pass 1, `/code-review` low**: at 999,600 tokens the line showed "1000k". `[Fixed]`: a test
  was written first, then the comparison moved after rounding.
- **Passes 2+3, `arch-reviewer` (Sonnet), about 28k tokens.** Nit: counts of 1M or more
  rendered as "1000k". `[Fixed]`: an M tier, test first. Comments passed Checklist A.
- **Pass 4, `security-reviewer` (Sonnet), about 25k tokens.** No issues; it reads trusted local
  stdin and has no shell, file or network I/O.
- **Pass 5, `/simplify`, 4 agents at about 52k tokens each.**
  - `[Fixed]`: `readFileSync(0)` instead of stream listeners; `toLocaleTimeString` for the
    clock; the unused catch binding dropped; the warm and cold `cachePart` branches merged.
  - `[Skipped]`: `Intl` compact notation changes the output format ("142K", "1M"), and the
    k/M-only scope is proportionate. Merging the two spawn tests wasn't worth it.

## Round 2

- **Pass 1**: none.
- **Pass 4**: no issues.
- **Passes 2+3.** Nit: a warm cache with no `expires_at` hides the segment. `[Verified, no fix
  needed]`: per the status line docs, `expires_at` is null only when the response had no cache
  tokens, and then `warm` is false.
- **Pass 5.** 3 of 4 agents found nothing. One said the "output tokens not counted" test can't
  falsify. `[Verified, no fix needed]`: false positive, since counting the fixture's 900 output
  tokens would render 143k and fail.
- **The round closed clean**, with no new findings and no `/simplify` edits, so the loop ends
  under the one-clean-round rule.

## Observations for the workflow retro

- **The reviewer agents followed the new contract.** Each returned `totals:` and `checked:` at
  about 25–32k tokens.
- **`/simplify` was the heaviest pass by far.** Its 4 agents used about 52k tokens each, about
  210k per round, on a 60-line script. Most of that looks like fixed per-agent overhead, since
  each agent loads CLAUDE.md, the skills list and so on.
- **Retro topic:** scale `/simplify` for small diffs, or run its angles in one agent.

## Outcome

- Shipped the status line (11 tests), the §6 rules, the review skill and agent updates, and the
  backlog items.
- The review closed clean in round 2.
- Open: the retro topic above, noted in the Recurring retro item.
