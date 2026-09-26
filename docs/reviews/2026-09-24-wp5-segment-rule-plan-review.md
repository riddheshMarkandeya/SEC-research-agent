# Review: WP5 plan, segment-rule emphasis (one independent plan-review round)

Plan: `docs/plans/2026-09-24-wp5-segment-rule.md`. The plan replaces the pressure
language in SYSTEM_PROMPT's `get_financial_fact` bullet ("do NOT call this tool at all,
not even to try") with plain wording (audit finding 4). It screens the change under the
roadmap's Decision rule, with a trace check on segment questions. The plan was written
while WP4's screen was still waiting for the quota reset, and WP5's implementation is
held until WP4 closes. This review covers the plan only. HEAD was `d204b5b`.

## Pass 1: self-check of the roadmap's Step 5 against HEAD `d204b5b`
- [Verified] The sentence is at `prompts/agent_system.py:36`. Only the snapshot pins it.
- [Verified] In WP3's screen window, the two panel segment questions made 0
  `get_financial_fact` calls in 6 runs. That matches the roadmap's "today there are
  none".
- [Fixed in plan] The implementation waits until WP4 closes. WP5's baseline is whatever
  fingerprint WP4 ends on.

## Round 1: independent subagent (the whole plan, escalated for `prompts/`)

**Must-fix, adopted:**
- **M1, the history mixed backends.** The draft cited 4 fact calls in 122 segment-style
  runs, including an invented `segment: "Graphics"` call. Re-counted by backend:
  - 120 of those runs were Gemini, and they made only 2 fact calls, both plain
    consolidated `revenue` calls on `msft-three-segments-revenue-q3fy2026`;
  - the invented-argument call was on Ollama;
  - the two panel segment questions had 0 fact calls in 51 Gemini runs.

**Should-fix, adopted:**
- **S1, the panel can barely see the change.** Neither panel segment question has ever
  made a Gemini fact call. `msft-three-segments-revenue-q3fy2026` ×3 now runs before and
  after 5a as a trace-only side run, which gets no compare verdict.
- **S2, "recur" and "confirmed" were undefined.** At a base rate of about 1.7% per run,
  "the reverted runs make no fact calls" would confirm almost any recurrence. The plan now
  defines both:
  - recur means at least 2 flagged calls across 6 C runs;
  - confirmed means recurrence plus 0 in the reverted runs;
  - the attribute step is framed as a same-day drift control, with C's count against the
    historical base rate as the main evidence.
- **S3, "any fact call" was too broad.** A plain consolidated call is harmless. The flag is
  now an invented-argument call, or a consolidated value cited as a segment's figure.
  Plain consolidated calls are recorded as watch.
- **S4, the roadmap's text left "instead" without an object.** The replacement now ends
  "instead of this tool", and the decision file will note the change from the roadmap.

**Nits, adopted:**
- The request estimate is now 175–195, since the roadmap's PANEL section says about 195.
- The pre-screen quota check uses the day's actual usage from traces.
- A reverted-WP4 baseline gets its date recorded.
- The index count is re-counted at the start, not assumed to be 40.
- Attribute runs happen on the same Pacific day as their replicate runs.

**Confirmed:**
- line 36, and that the contract sentences and "no `segment` parameter" stay;
- the snapshot is the only pin outside `docs/`;
- the `judge` and `mcp` fingerprints don't hash `agent_system`
  (`prompts/__init__.py:46-51`);
- the search descriptions at `agent_tools.py:29` and `mcp.py:25`;
- the `compare_prompt_versions.py` flags `--base-files`/`--candidate-files`, and that
  dirty reports are excluded unless `--include-dirty` is passed;
- explicit mode is the right choice;
- reverting 4a restores `4f36a2b026cf`;
- the BACKLOG WP5 line exists;
- the unstaged step-0 docs are safe.

## Outcome

The must-fix, all four should-fixes and all five nits are folded into the plan before
approval. No user decision was needed, and nothing was deferred.
