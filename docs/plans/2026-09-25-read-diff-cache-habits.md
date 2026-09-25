# Reading/diff/cache habits, status line, effort default, and a recurring workflow retro

## Context

A 2026-09-25 transcript analysis (23 sessions, 2026-08-25 → 09-25, about 18k tool calls, 49M
chars of tool output) found where reading and caching waste tokens. Every tool result is
re-sent on each later turn until compaction.

| Source | Size | Finding |
|---|---|---|
| Read | 29M chars (59%) | `agent.py` read 847× (5.8M); `test_agent.py` 248×. Auto-loaded files re-read anyway: project `CLAUDE.md` 63× in full, skills 48×. `BACKLOG.md` read in full 46×. |
| `git diff` / `git show` | 4.6M chars | Whole multi-file diffs, up to 29k chars each, docs included, repeated across rounds. |
| grep and `sed -n` | 3.9M chars | Often unbounded. |
| `trace_logs/traces.jsonl` (4.8MB) | 0.43M chars | Never read whole; 223 filtered queries. Log rotation would save no tokens. |
| Cache writes | about 11% of cost | 64% of cache writes came from 80 big rebuilds: 52 after resuming a session idle over 1h (about 370k each), 18 after a mid-session `/model` switch. |
| Output | about 8% of cost | Global `effortLevel` was `high`. |

## Decision / Design

User choices: suggestions 1 and 2; backlog items for 3 and 4; global effort medium; a status
line; a recurring retro.

1. **Global CLAUDE.md §6** gets three rule groups:
   - **Reading**: grep `-n` first, then ranged Read; no re-reads unless edited or compacted; never
     Read auto-loaded files except before editing; bound search output; long output goes to a
     file.
   - **Diffs**: `--stat` first, then per file; leave docs out of code-review diffs; give subagents
     the command, never the pasted diff.
   - **Cache**: `/compact` before a break of more than 1h; pick the model at session start;
     `/effort` keeps the cache only on Opus 5.5 and Fable 5.1 (per the prompt-caching docs).
2. **Review skill and agents**: the review skill passes diff commands; security leaves out `.md`
   files; arch-reviewer keeps docs, since it reviews them; both agents run `--stat` first and
   read surrounding code in ranges.
3. **Settings**:
   - `effortLevel: medium`;
   - `~/.claude/scripts/statusline.js` shows model, context tokens, "cache warm until HH:MM
     (Nk if cold)" and the 5h limit. The expiry is absolute because the status line doesn't
     refresh while idle;
   - Node `node:test` tests sit alongside it.
4. **Backlog**:
   - eval summary mode;
   - the existing trace-helper item, rewritten with new evidence;
   - `agent.py`/`test_agent.py` split (Substantial);
   - a **Recurring workflow retro**, due 2026-10-09 and every 2 weeks after, moved one week if
     fewer than 4 Standard+ tasks have run. Its first run closes the Pilot item, and each run
     writes a decision file. From the second run, a global `workflow-retro` skill takes a
     project as its parameter.
   - The Recurring exception is pinned in the BACKLOG header, and the due date lives in a memory
     file so it gets surfaced.

## Testing and verification

- Status line: `node --test` fixtures, the docs' sample JSON, and invalid or empty input.
- Both settings files parse as JSON.
- `git diff` self-check.
- The pre-commit docs-health check.
- The status line is code, so it gets the five-pass review at low effort.
