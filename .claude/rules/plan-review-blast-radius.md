---
paths:
  - "agent.py"
  - "llm_backends.py"
  - "xbrl_facts.py"
  - "formulas.py"
  - "retrieval.py"
  - "numeric_utils.py"
  - "eval_harness.py"
  - "chunk_documents.py"
---

# This project's high-blast-radius core

Per `design-before-building`'s review floor (unconditional since
2026-09-17 — every plan produced in plan mode gets one
independent-subagent review pass, regardless of tier), a change
touching one of the functions/areas below earns *escalated* scrutiny
from that reviewing subagent — deeper review within the floor every
plan already gets, not a gate on whether review happens at all. It
still doesn't pull in the rest of the Substantial-tier process (no
forced spec/prior-art write-up, no TDD/documentation-depth
escalation) unless the task is independently tiered Substantial.
Every entry here is grounded in a real incident from this project's
own history, not a speculative "this file feels important" argument:

- **`agent.py`** — the tool-calling loop (`_run_agent_impl`) and its
  dispatch/backend-call sites (`_dispatch_tool_call`,
  `_partition_submit_call`). Incident: the 2026-09-16 `MAX_TOOL_ITERATIONS`
  fix, where a wire-protocol-shape mistake here would have produced a
  live Gemini 400 on the exact questions the fix targeted.
- **`llm_backends.py`** — the backend send functions (`_gemini_send`,
  `_gemini_send_followup`, `_ollama_send`, `_ollama_send_followup`).
  Same incident — this is exactly where `send_followup` vs.
  `send_tool_results` had to be gotten right.
- **`xbrl_facts.py`** — `_pick_entry`, `get_metric`,
  `_pick_entry_by_end_date`, `_resolved_fiscal_year`. Incident: the
  2026-09-16 CRM fiscal-year-lookup fix.
- **`formulas.py`** — `get_yoy_growth`, `_compute_ratio_metric`,
  `_compute_ratio_metric_all_companies`. Incident: the same CRM fix's
  second-order `get_yoy_growth`-chaining regression risk, found only by
  tracing how these functions consume `get_metric()`'s return value.
- **`retrieval.py`** — ranking/rerank logic (same functions
  `.claude/rules/live-eval-verification.md` already names for its own,
  related purpose).
- **`numeric_utils.py`** — the number-parsing/normalization functions.
  Incident: the 2026-09-12 negative-number fix, where 14 passing unit
  tests still shipped two live-only bugs (a spaced-hyphen subtraction
  expression, a Unicode minus sign) no unit test had anticipated — the
  clearest existing evidence in this project that diff size doesn't
  predict risk here.
- **`eval_harness.py`** — `grade_judged`/`JUDGE_SYSTEM_PROMPT`. A
  different flavor of blast radius than the other entries: this code
  doesn't affect the agent's answers, it decides what counts as
  PASS/FAIL across the whole eval suite, so a wrong change here corrupts
  every before/after comparison the project relies on without ever
  showing up as an agent regression. Incident: the 2026-09-17 judge
  hypothetical-date fix, where the judge failed correctly-cited, cleanly
  grounded answers (`citation_warnings: []`) as "fabricated hypothetical
  data" purely from its own training-cutoff blind spot.
- **`chunk_documents.py`** — `chunk_blocks()`. Corpus-wide code that
  every live citation-grounding check reads from, so a subtle bug here
  can silently corrupt table data across the whole indexed corpus
  without ever looking like a bug in the code that surfaces the
  failure. Incident: the 2026-09-17 orphaned-table-overlap fix, where a
  raw-character-slice overlap carry-over could land mid-table, hiding a
  real row from `table_grounding.py`'s paired-tag regex and causing a
  correct answer to be citation-gate-refused — root-caused only by
  tracing the bug back through retrieval and table-grounding to the
  chunker, not by anything visible in the citation-verification code
  itself.

**Keep this list current the same way `BACKLOG.md` keeps itself
current** (see this project's own `CLAUDE.md`): add an entry the moment
a plan or code review surfaces a real issue in a function not already
listed here, in the same step, not as a deferred follow-up.

## Coverage bar

A separate policy from the escalated plan-review scrutiny above —
mechanically a numeric coverage floor, not incident-grounded review
depth — that happens to reuse this same 8-file list rather than
maintaining a second, identical one. Per
`docs/decisions/2026-09-22-adopt-pytest-coverage.md`: new/changed lines
in any file listed above must clear **90%** diff coverage (vs. 80%
elsewhere) before a change touching it is called done, excluding
live-only lines already marked `# pragma: no cover` per
`.claude/rules/live-code-tdd.md`. If this file's own `paths:` list
changes for plan-review reasons, the coverage bar's file set changes
with it automatically — no second list to keep in sync.
