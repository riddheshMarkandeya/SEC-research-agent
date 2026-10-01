# Map: agent improvement (merged)

Date: 2026-09-28. This is the single wayfinder map for this effort. It merges and supersedes, for
ticket state:
- `docs/plans/2026-09-28-gate-refusal-flakiness-map.md` (the "gate map"). Its Evidence summary
  and Decisions 1–12 hold the detail.
- `docs/plans/2026-09-28-structural-review.md` (the "review"). Its failure breakdown, C1–C6 and
  S1–S5 hold the detail.

Those two files keep their evidence and are no longer edited. This file carries decisions,
tickets and order from here on. Refer to the source items as "gate D9" or "review S3".

## Destination

The avoidable failures behind the eval's flaky questions are removed with structural changes,
not patches:
- gate refusals of correct answers;
- forced-turn filler claims;
- retrieval misses by period.

The citation guarantee stays intact, and the codebase is simpler afterwards (no Ollama, a split
`agent.py`, one submit loop). Done means every ticket is decided, the build work packages are
ordered in BACKLOG, and this map is frozen.

## Notes

- **Self-grilled**, at the user's request, with evidence for every decision. Anything that
  loosens the gate, revisits a recorded decision, or is a user-level product call is marked
  **needs user OK**.
- **Checks by reach (user-confirmed 2026-09-28):**

  | Change type | Final check |
  |---|---|
  | Code-only gate change | Offline replay plus a targeted live spot-check |
  | Prompt or schema change | One commit plus a panel 3× screen |
  | Every-question change | Panel 3× screen plus a full 48-question run |

- The judge stays on gemini-3.5-flash-lite during model tests.
- Critical-core rules (`.claude/rules/plan-review-blast-radius.md`) apply to every package that
  touches `agent.py`, `llm_backends.py`, `numeric_utils.py`, `retrieval.py`,
  `chunk_documents.py`, `eval_harness.py` or `prompts/`.
- Quota: 500 requests/day. The panel 3× is about 200; the full run is about 250.

## Decisions so far

Carried over, still needing the user's OK where marked:
- **Retry slot (gate D9, review S2 step 1):** the citation retry no longer needs spare tool
  budget. Needs user OK.
- **Placeholder claims verified as qualitative (gate D4, D11):** code-only. Needs user OK.
- **Verified-quote coverage (gate D3):** needs user OK.
- **Row-anchored verbatim table quotes plus header-parse fix (gate D12):** needs user OK.
- **Upheld: verbatim quotes as the grounding unit (review C1),** and coverage of every answer
  number (review C2).
- **Rejected:** covering any number in a cited source (gate D5), and auto-reattributing
  citations (gate D6).
- **Confirmed by the user:** the judge pin, the prompt-change protocol, and the final-check-by-
  reach table (review, "Confirmed with the user").

New in this merge:

13. **Prerequisites come before any improvement package.** Improvement work lands mostly in
    `agent.py`. Doing it after a cleanup means smaller diffs, clearer seams and cheaper reads.
    The prerequisites, in order:
    1. **Fix the High-priority `NUMBER_PATTERN` cubic backtracking** (BACKLOG, `[bug, High]`).
       Answer text is untrusted and passes through it. The gate packages also edit
       `numeric_utils`, so it goes first.
    2. **Commit the replay tool (review S1).** It's the equivalence check for the two refactors
       that follow: the replay's verdicts must be identical before and after a pure refactor.
    3. **Remove the Ollama backend** (BACKLOG, user decision 2026-09-26: "before the `agent.py`
       split, which it shrinks"). It also removes the three backend-gating sets
       (`_CITATION_RETRY_BACKENDS`, `_FORCED_SUBMIT_BACKENDS`, `_FINAL_TURN_BACKENDS`), which
       simplifies review S2. Its open points (a) and (b) are tickets below.
    4. **Split `agent.py` (2,516 lines) and `tests/test_agent.py` (4,669 lines)** (BACKLOG,
       long-standing user goal). This is a pure move, verified by the model-input snapshot, the
       full suite and the replay.
       - **Done 2026-09-29** (`docs/plans/2026-09-29-agent-py-split.md`): seven new modules in
         `sec_agent/agent/` (`tool_args`, `tool_results`, `citations`, `fact_tools`,
         `calculate`, `dispatch`, `submission`); `agent.py` keeps only the loop.
    5. **Add a summary mode to `eval_harness.py`** (BACKLOG, Med). Every package below runs
       panels, and the full output has cost 2.4M characters of context across past sessions.
       Cheap, and it's outside the agent.
       - **Done 2026-09-30** (commit body): compact output by default (one line per question
         plus a per-type table), `--verbose` for the old output, `--summarize <report>` for a
         saved report, and no Hugging Face progress bars.

    Why not the split first, as the user suggested? The split is right to do early, and it comes
    before every improvement package. But Ollama removal shrinks what gets split, per the user's
    own recorded order. And without the replay tool, the split's only safety net would be unit
    tests plus quota-costing panels.

14. **No fallback backend after Ollama removal (user, 2026-09-28).** When the Gemini quota runs
    out, work stops until the reset. Other cloud backends are a separate effort, outside this map.
    The user also confirmed the order: prerequisites 1–5, then the improvement packages.
15. **Repo layout move to a `src/` package (user, 2026-09-28).** This is the user's own addition.
    It goes into Decision 13's prerequisites between Ollama removal and the `agent.py` split.
    - **What:** pure moves, in their own commit:
      - `src/sec_agent/`, with subpackages `agent/`, `verification/`, `sources/`, `retrieval/`,
        `llm/`, `prompts/` and `eval/`, plus `config`, `tracing` and `mcp_server`;
      - `tools/` for the analysis CLIs and the replay tool;
      - one gitignored `var/` for `chroma_db`, `chunks`, `data`, `xbrl_cache` and `trace_logs`;
      - `tests/` mirrored.
    - **Measured cost:**
      - 21 modules, 102 import lines, 226 string mock targets.
      - 10 working-directory-relative data paths, which the move anchors to the project root. That
        fixes a latent bug.
      - About 55 tooling path references: rules frontmatter, pre-push list, pyproject, CLAUDE.md,
        pre-commit.
      - 11 `tests/manual` `sys.path` hacks, replaced by an editable install.
      - The 156 history docs keep their old paths.
      - About one session.
    - **Unchanged:** the eval fingerprint (it hashes prompt values, not paths), the Chroma IDs
      (from filing metadata) and the logged traces.
    - **Why this slot:** after the edits that touch the same files, and before the split, so the
      split's new modules are created once, in their final place.
    - **Checks:** the full suite, the model-input snapshot, and identical verdicts from the
      replay tool.
    - The critical-core list becomes directory globs, mirrored in pre-push.
    - **Done 2026-09-29** (`docs/plans/2026-09-29-src-layout-move.md`). Changes from the above,
      user-decided: file basenames kept (`sec_agent/agent/agent.py`), and the directory globs
      deliberately widen the critical core to every module in `agent/`, `llm/`, `sources/`,
      `retrieval/`, `verification/`, `eval/` and `prompts/` (adds `table_grounding`,
      `edgar_ingest`, `companies`, `period_labels`, `index_chunks`). Committed eval data stays in
      `eval/`.

## Open tickets

### Ollama removal: prose fallback path
- Question: Does the prose-citation path (`collect_citation_warnings`) stay as Gemini's last
  resort (BACKLOG point b)? It was used in 8 of 478 runs.
- Type: grilling (self). Evidence: find what those 8 runs were and whether a forced submit would
  have covered them.
- Blocked by: none.
- Status: **resolved 2026-09-29: deleted** (user). Text after a forced submit is now refused. See
  `docs/decisions/2026-09-29-remove-ollama-and-prose-fallback.md`.

### `agent.py` module boundaries
- Question: Which modules, and where do the seams fall?
  - Candidates: tool dispatch, citation verification (`verify_claims` and helpers), the loop
    (`_run_agent_impl` and helpers), result formatting.
  - The module boundaries should match what the S2 loop refactor and the gate packages will
    touch.
- Type: grilling (self), then its own plan.
- Blocked by: none (Ollama removal done 2026-09-29).
- Status: **resolved 2026-09-29.** The loop stays in `agent.py`; the S2 retry state spans
  `agent.py` and `submission.py`; the gate packages land in `citations.py`. See
  `docs/plans/2026-09-29-agent-py-split.md`.

### Tool-message citations on refusal questions (from the gate map)
- Question: Should the refusal path need no numeric claims? It merges with review S3 (the
  not-available answer).
- Type: grilling (self), then a prompt/schema change under the protocol.
- Blocked by: retry slot shipped and re-measured.
- Status: open.

### Segment-table ranking (gate map) and period-scoped retrieval (review S5)
- Question: Which variant? Measure with an offline gold-rank harness before choosing:
  - a period-filtered extra list in rank fusion;
  - the glued-month chunker fix;
  - tables as their own chunks.
- Type: task (harness), then grilling.
- Blocked by: none. Independent of `agent.py`; can run in parallel.
- Status: open. **Frontier.**

### Judge-model setting
- Question: Add a separate judge-model setting (today the judge reads `GEMINI_MODEL_NAME`), as a
  prerequisite for any agent model swap. Critical core (`eval_harness.py`, `llm_backends.py`).
- Type: task.
- Blocked by: none. Needed only before a model-swap test.
- Status: open.

## Proposed build order

Prerequisites (Decisions 13 and 15): ~~NUMBER_PATTERN fix~~ → ~~replay tool~~ → ~~Ollama removal~~
→ ~~`src/` layout move~~ → ~~`agent.py` split~~ → ~~eval summary mode~~.

Then the improvement packages:
1. **Retry slot** (gate D9): code, then the panel and a full run.
2. **Gate rules** (gate D4/D11, D3, then D12 a and b): code-only, checked with the replay plus a
   spot-check.
3. **Uniform submit loop** (review S2 step 2): refactor, panel plus full run.
4. **Not-available answer** (review S3, with the tool-message ticket): prompt protocol.
5. **Period-scoped retrieval plus the glued-month fix** (review S5): offline harness, then panel
   plus full run.
6. **Thinking-level A/B, then temperature** (review S4): one variable at a time, on a quiet
   quota day.

After each package, re-mine the refusals with the replay tool before starting the next.

### Two tracks (2026-09-30)

The packages above are **track A**: they run on master and spend Gemini quota. The S5 ticket is
**track B**: offline work on branch `retrieval-harness` with no quota. Neither blocks the other.

**Rule of thumb:** when there's quota and a track A step is ready, do track A. When quota is
spent or you're waiting on a run, do track B.

Track A, next steps:
1. Package 1: the full 48-question run from master at `f6a75db` (from 07:00Z 2026-10-01), a
   refusal re-mine, then its docs commit.
2. Packages 2, 3 and 4, in order.
3. Package 5 builds the variant track B picks. It keeps its place after package 4, because its
   live check spends quota and the packages change one thing at a time. Moving it up is decided
   at track B's step 6, not before.

Track B (plan: `docs/plans/2026-09-30-retrieval-gold-rank-harness.md`):
1. V0/V1/V2 measured with the gold-rank harness, then the prototype stashed.
2. A cross-encoder rank diagnostic: splits the rerank misses into the model scoring gold low vs.
   the fusion step or table rescue dropping it.
3. `/research` on rerank, narrowed by step 2.
4. The research's candidates measured with `--compare` against V0.
5. The review pass, then a docs commit: the S5 ticket's figures, a rerank ticket on this map, the
   backlog items. Merge the branch after track A's step 1.
6. Grilling to pick the variant, which becomes package 5's spec.

V0 found that 478 of 572 retrieval misses happen at the rerank step, with gold already in the
candidate pool. So package 5's content will be renamed to match the variant track B picks,
instead of "period-scoped retrieval plus the glued-month fix".

## Not yet specified

- Whether `compare_financial_metric` leaves the agent's tool list. It has 0 calls in 478 runs,
  and BACKLOG has an item. It's model-visible, so it would ride on package 4's prompt commit.
- Model upgrade (3.8 Flash). It needs the judge-model setting and a verified free-tier cap.
- Reformatted table-row quotes, hand-computed numbers and cell-only quotes (gate map fog).
  Re-measure after packages 1–2.

## Out of scope

- Other cloud backends (a separate effort, per the user).
- Judge-criteria content failures with no gate or retrieval involvement.
- XBRL segment facts from full instance documents: exact but narrow, and a new tool.
