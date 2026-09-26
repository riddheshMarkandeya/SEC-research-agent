# WP5: plain wording for the segment-rule emphasis (audit finding 4)

## Context
WP5 is **Step 5** of `docs/plans/2026-09-24-prompt-audit-roadmap.md` and fixes audit
finding 4 (`docs/reviews/2026-09-24-prompt-audit.md`, table row 4).

- **The problem:** SYSTEM_PROMPT's `get_financial_fact` bullet uses pressure language: "If a
  question asks about a specific segment or product line, do NOT call this tool at all, not
  even to try — go straight to `search_filings` instead."
- **Where it came from:** commit `6f3a8ee` (2026-08-20) added it. Three live tests on Ollama
  qwen showed no effect. It was kept "for more instruction-following models", which means
  Gemini.
- **The fix:** plain wording, screened on Gemini, plus a trace check on segment questions.
  The result also answers `6f3a8ee`'s open question: does the emphasis matter on Gemini?

**Tier:** Standard. It is one model-facing commit in `prompts/`, which is critical-core, so
the plan review gets escalated scrutiny.

**Sequencing (user decision, 2026-09-24):** plan now, and implement only after WP4 closes.
WP4 closes when its screen verdict is in (accepted, or its Decision rule has been applied)
and its reports and docs commits exist. The roadmap requires that each panel comparison
covers exactly one prompt change since the last accepted fingerprint.

## Repo state (2026-09-24, HEAD `d204b5b`)
- **WP4:** review closed. Its screen waits for the 07:00 UTC reset, and its candidate is
  agent fingerprint `d2131f5d5aae`. WP5's baseline B is whatever WP4 ends on:
  `d2131f5d5aae` if accepted, `4f36a2b026cf` if 4a is reverted.
- **Text location (verified):** `prompts/agent_system.py:36`, inside the
  `get_financial_fact` bullet.
  - The contract sentences just before it stay: "This tool ONLY returns a company's
    consolidated, company-wide total — it has NO way to get one segment's or one product
    line's figure (e.g. …)".
  - "there is no `segment` parameter", later in the same bullet, also stays.
- **Tests:** outside `docs/`, only `prompts/model_input_snapshot.json` (its `agent`
  section) pins the sentence, so the snapshot test is the red step.
  - The `judge` and `mcp` fingerprints don't hash `agent_system` (`prompts/__init__.py:46-51`).
  - `prompts/agent_tools.py:29` and `prompts/mcp.py:25` say "segment or product-line
    figures" in the search description, and they stay as they are.
- **Trace evidence (Gemini only, `trace_logs/traces.jsonl`):**
  - **The two panel segment questions:** 0 fact calls in 51 Gemini runs (NVDA 30, AAPL 21),
    including 0 in WP3's screen window (2026-09-25 01:40:57–01:51:00Z).
  - **`msft-three-segments-revenue-q3fy2026`:** 2 plain consolidated `revenue` calls in 22
    runs (2026-09-11 and 09-13), and none since. This is the only question that has shown
    the behaviour on Gemini.
  - **The one invented `segment: "Graphics"` call** (2026-09-09) was on Ollama and doesn't
    count.
- **PROJECT_INDEX Recent:** 48 lines today. WP4's docs step goes 48 → 52 → trim to 40.

## Change (changes vs. the roadmap)
- **Commit 5a** (model-facing), `prompts/agent_system.py:36`:
  - replace "If a question asks about a specific segment or product line, do NOT call this
    tool at all, not even to try — go straight to `search_filings` instead."
  - with "For a question about a specific segment or product line, use `search_filings`
    instead of this tool."
  - **Changed from the roadmap (plan review S4):** the roadmap's text stops at "instead".
    "Of this tool" gives "instead" an object once "do NOT call this tool" is gone. The
    decision file will record the change.
  - Nothing else in the bullet changes. The remaining all-caps words ("ONLY", "NO") are
    finding 8, which belongs to WP8.
- **Added (review S1):** a side run of `msft-three-segments-revenue-q3fy2026` ×3 before and
  after 5a. It feeds the trace check only, and gets no compare verdict. This is the only
  question that has shown the behaviour on Gemini.

## Steps
0. **On approval, now:** save this plan to `docs/plans/2026-09-24-wp5-segment-rule.md`, and
   the plan review to `docs/reviews/2026-09-24-wp5-segment-rule-plan-review.md`.
   - Both stay unstaged, and WP4's docs commit stages its own files by explicit path.
   - **Stop here** until WP4 closes.
1. **Start of implementation** (after WP4 closes):
   - `git status` shows only the two WP5 docs, which are docs and don't make the eval tree
     dirty;
   - read WP4's decision file for B's fingerprint and its three screen reports, and re-count
     the Recent lines.
   - **B side run:** at WP4's final HEAD, run
     `python eval_harness.py --ids msft-three-segments-revenue-q3fy2026` 3× as separate
     calls, about 20 requests. Its report timestamps mark the B side-run window.
2. **Commit 5a.**
   - Red: the snapshot test fails. The word diff shows only this sentence, and only in the
     `agent` section.
   - Regenerate with `UPDATE_SNAPSHOT=1`.
   - One-off check: `agent` moves, and `judge` and `mcp` don't.
3. **Manual checks:** ruff, pyright, and pytest with coverage.
4. **Implementation → review boundary:** give the `/compact` line.
5. **`independent-review-pass`** over the 5a range, all five passes, light effort. Commit
   any fixes.
6. **Screen (Decision rule step 1):**
   - **Preconditions:** a clean tree at the final HEAD, and at least 250 of the Pacific
     day's quota left. Count the day's *actual* usage from traces (WP4's screen, its
     replicate and attribute runs, and the B side run), not an estimate. Otherwise wait for
     the next reset.
   - **Runs:** the panel 3× (the same 13 IDs as WP3/WP4, about 175–195 requests), then the
     MSFT side run 3× as separate `--ids` calls (about 20).
   - **Compare in explicit mode:**
     - `--base-files`: WP4's three accepted screen reports, or WP3's three if 4a was
       reverted, and in that case note the baseline's date in the decision file;
     - `--candidate-files`: the three new panel reports;
     - fingerprint mode isn't used, because it would pool WP4's replicate and attribute
       runs into B.
   - No REGRESSED and no REGRESSED-TOTAL: accept, with one exception:
   - **Segment override** (review S2/S3), on the two panel segment questions and the MSFT
     side question:
     - **Flagged:** any C run makes a `get_financial_fact` call with an invented argument
       (`segment` or any other extra key), or cites a consolidated fact value as a
       segment's figure in `claims`. A pass-rate compare can't see either, because the
       answer can still pass.
     - **Watch:** plain consolidated fact calls are counted, not flagged. Record them as
       watch if they appear where B has none.
     - **Replicate** a flagged question 3×. The flag recurs if at least 1 more such call
       shows up, so at least 2 across the 6 C runs.
     - **Attribute** (same day as the replicate): revert 5a and run that question 3×. If the
       flag recurred and the reverted runs show 0 such calls: **confirmed**. Keep the
       revert and file a BACKLOG item.
       - The main evidence is C's count against the historical Gemini base rate (0/51 on
         the panel segment questions). The revert runs are a same-day drift control.
     - A single flagged call that doesn't recur is recorded as watch.
7. **Trace check** (scratchpad script, no cost), B windows against C windows:
   - `.get` every key;
   - map run_id → question in a first pass;
   - count:
     - calls per tool;
     - on each segment question, fact calls split into "invented argument" and "plain
       consolidated", plus search calls;
     - fact calls anywhere in the panel with a `segment` argument;
     - whether any consolidated fact value ended up in `claims` on a segment question.
8. **Only if flagged:** replicate, then attribute, both in explicit mode. Budget about 25
   requests per question per step. The attribute runs happen on the same Pacific day as
   their replicate runs, and if quota doesn't allow that, both move to the next day.
9. **Docs:**
   - decision file `docs/decisions/<date>-wp5-segment-rule.md`:
     - fingerprints;
     - per-question k/3 against B;
     - the verdict and flags;
     - the trace counts, including the MSFT side run;
     - the request count;
     - the change from the roadmap ("of this tool");
     - the answer to `6f3a8ee`'s question;
   - code review file `docs/reviews/<date>-wp5-segment-rule.md`;
   - delete the WP5 BACKLOG line (`BACKLOG.md:53`);
   - 4 PROJECT_INDEX Recent lines. Trim to 40 only if the re-count goes over 50;
   - commit the reports, then the docs. No push.

**Authorisation on approval:**
- step 0 now;
- after WP4 closes:
  - commit 5a and any review-fix commits;
  - a revert only as the Decision rule or the segment override prescribes;
  - the reports commit and the docs commit;
  - Gemini requests: about 20 for the B side run, about 195–215 for the screen and C side
    run, plus about 25 per replicate or attribute step if flagged.

No push.

## Out of scope
- The all-caps emphasis elsewhere (finding 8, WP8).
- Duplicated guidance (finding 9).
- WP6.
- `msft-segment-revenue-comparison-q3fy2026`. It failed its last 8 runs, and WP8's full run
  covers it.

## Critical files
- `prompts/agent_system.py`
- `prompts/model_input_snapshot.json`
- **Reuse:**
  - `tests/test_model_input_snapshot.py`;
  - `prompts.prompt_fingerprint`;
  - `compare_prompt_versions.py` (explicit mode);
  - `eval_harness.py --ids`;
  - WP4's trace-check script pattern.

## Verification
- **Commit:** ruff, pyright and pytest clean, and the snapshot diff shows only the one
  sentence.
- **Screen:** the explicit-mode compare verdict, the segment override outcome and the trace
  counts (panel and MSFT side run), all recorded in the decision file.

## Plan review (1 independent round; source for the step-0 review file)
- **Must-fix, adopted:** M1, the history mixed backends. Gemini-only it is 0/51 on the panel
  segment questions and 2/22 plain consolidated calls on MSFT three-segments. The invented
  `segment` call was Ollama.
- **Should-fix, adopted:**
  - S1: the MSFT three-segments side run, B and C, trace-only.
  - S2: precise definitions of "recur" and "confirmed", with the attribute step framed as a
    drift control.
  - S3: flag only invented-argument calls or a consolidated value cited as a segment's
    figure; plain consolidated calls are watch.
  - S4: "instead of this tool".
- **Nits, adopted:**
  - the request estimate is now 175–195;
  - the quota check uses the day's actual usage;
  - a reverted-WP4 baseline gets its date recorded;
  - the index is re-counted rather than assumed to be 40;
  - attribute runs happen the same day as their replicate runs.
- **Confirmed:**
  - line 36, and that the contract sentences and "no `segment` parameter" stay;
  - only the snapshot pins the sentence;
  - `judge`/`mcp` don't hash `agent_system`;
  - the search descriptions at `agent_tools.py:29` and `mcp.py:25`;
  - the `--base-files`/`--candidate-files` flag names, and that dirty reports are
    excluded;
  - explicit mode is right;
  - reverting 4a restores `4f36a2b026cf`;
  - the BACKLOG line exists;
  - the unstaged step-0 docs are safe.
