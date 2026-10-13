# Backlog

Tracks open work: what's queued, what's in progress. This is **not** a
changelog. Completed work's rationale and verification live in its
record: the commit message body, or a `docs/decisions/YYYY-MM-DD-<slug>.md`
file when the change passes the ADR gate (and, for Substantial work, its
own paired design doc under `docs/plans/`), with files indexed from
`PROJECT_INDEX.md`. Link out to the relevant record instead of
re-explaining reasoning here; keep entries short.

**Keep this current as work happens, not just at session-end**: add a
line the moment a new open item is identified (a deferred idea, a
found-but-not-fixed bug, a follow-up) — don't wait for a wrap-up. Move
an item to "In progress" when you start it. **When an item is done,
delete its line entirely** — no strikethrough, no "resolved" annotation
left behind — and land its record in the same step (the commit body,
or a decision file plus its `PROJECT_INDEX.md` line if the ADR gate
passes). If only part of a
multi-part item is resolved, rewrite the line to describe only the
remaining open part, with no decorated hybrid of done-and-not-done. An
item should never just vanish from this file with no recorded trace
of what happened to it. **Exception: items tagged "Recurring"**. When a run
is done, rewrite the item's due date instead of deleting the line; each
run still leaves its own record.

This file replaces the project's former narrative changelog's old "Next
steps" section, which needed its own 380-line cleanup pass once already
(2026-08-19) from exactly this kind of bloat — don't let this file
suffer the same fate; prune it as items resolve.

**Where items go.** Origin sections (`### From …`) hold work someone can pick up. A latent item with nothing to do until a named condition is observed goes in the `## Watch list` at the end instead, as one line: the trigger plus a record link.

## How to read an item

Every bullet is tagged **[type, priority, effort]** — see the
`documentation-backlog-hygiene` skill's "Backlog tagging convention" for
the full definitions. Quick
reference:

- **Type**: `bug` · `refactor` · `feature` · `performance` ·
  `test-coverage` · `design` · `misc` — `(latent)` after `bug` means
  real but not currently triggered by any live code path.
- **Priority**: `Low` / `Med` / `High` — urgency, independent of type.
- **Effort**: `Trivial` / `Standard` / `Substantial` — this repo's own
  CLAUDE.md tiers; also signals how much process applies once picked
  up. `TBD` when the item hasn't been scoped enough to size yet.

## In progress

- [ ] **[misc, Med, Substantial]** **Agent-improvement map**: `docs/plans/2026-09-28-agent-improvement-map.md`. Packages 1, 2, 5, 3 and 4 are done. **Package 6 (thinking-level / temperature A/B) is deferred** (user, 2026-10-06): the panel is 39/39 and the full run 46/48 (48/48 on the expanded corpus, `20261007T072322Z`), so it can't show a gain. Trigger: the evals have headroom again (after the harder-eval-questions roadmap item, or alongside a model upgrade). Its base runs must come from `e8bd2a2` or later, or exclude `pltr-dividend-2019-refusal`. Temperature 0.1 has no recorded reason (Ollama era, `811cad0`); it stays a known open item until package 6 runs. No fallback backend after Ollama removal (user, 2026-09-28). Keep the model pin for its screens.

## Backlog

### Roadmap (user, 2026-10-06): data expansion → harder eval questions → monorepo → admin web UI → chat web UI

- **Phase 2 build** (ordered 2026-10-08; decisions are in the phase 2 map (`docs/plans/2026-10-07-data-expansion-phase2-map.md`, frozen), under Decisions so far). Do the packages in order; 4 and 5 can run in parallel.
- [ ] **[bug, Low, Standard]** **Untickered BM25 still uses Okapi's clamped IDF.** The whole-corpus index (`_load_bm25_index`) keeps `BM25Okapi`: words in over half the corpus are lifted to `0.25 × average_idf` above rarer words, and a chunk matching only a word in exactly half the chunks scores 0 and is cut. Per-ticker indexes moved to `_LuceneIdfBM25` (2026-10-09), which fixed both there (replay 587 → 630, coverage 33 → 36). Left out because the replay holds no untickered query, so it can't be measured. Every v1 search carries a ticker today. Trigger: v2 questions or a probe with untickered searches. Then switch `:158` and measure. Critical core. `docs/decisions/2026-10-09-bm25-idf.md`
- [ ] **[bug, Low, Standard]** **The eval judge fails a cited answer for having "no citation markers".** In spot-check `20261009T185313Z`, `msft-segment-revenue-comparison-q3fy2026` gave the correct three figures, each marked `[10]`, with `citation_warnings: []`. That is nearly the same text as the PASS in `20261009T071942Z`, yet the judge said it had no citation markers. One case so far, so this is noise in v1 comparisons, not a pattern. Watch for a repeat. If it recurs, consider a deterministic citation-marker check in `grade_judged` (which already knows `has_citation`) in place of asking the judge. Critical core (`eval_harness.py`, `prompts/judge.py`).
- [ ] **[feature, Low, Standard]** **A `ticker` field on `submit_answer` claims, checked by the citation gate.** On top of 3a.1: the agent states which company each claim is about and the gate refuses a claim whose cited source has another ticker. Catches a label mix-up inside the agent (helps users, not only the grader), which source-ticker attribution alone can miss when the prose labels a correctly cited value with the wrong company. A tool-schema change, so a prompt change: v2 first, then the v1 gate, per `live-eval-verification.md`. Trigger: build 4's first v2 batch shows prose label swaps that 3a.1 passes.
- [ ] **[refactor, Low, Standard]** **3a.1's round-8 review leftovers in `eval/questions.py`**, to revisit with v2 run data: the outside-companies error reads "X is not one of" for several companies (list them as "are outside the question's companies (…)"); no test for an entry partly outside the question's companies, or for the label/companies message's company list; `_check_entry_companies` rebuilds `set(tickers)` per entry; `_row_identity` reports `ticker or tickers` instead of their union; a trap is charged to one company, so a trap on a cross-company derived value can't be written yet.
- [ ] **[misc, Med, Substantial]** **Phase 2 build 4: write the v2 questions** (about 56, 7 categories; mix and authoring process in the map). Batched by company or category across sessions; each batch passes the build 3b script before the user reviews it. Runs alongside build 5. Batches 1–2 are done (21 questions; `docs/plans/2026-10-13-phase2-build4-batch2.md`). Next is batch 3: N1–N10, numerical reasoning (allocation in `docs/plans/2026-10-12-phase2-build4-v2-questions.md`).
- [ ] **[misc, Med, Trivial]** **Re-run the v2 judge sanity script for R8's reworded criterion.** `PYTHONPATH=src python tests/manual/verify_v2_judge_templates.py`, about 155 judge calls, on a day with spare Gemini quota. Every verdict must come out as expected, including `v2-cat-backlog-2020`'s three good cases. Owed from the batches 1–2 review (`docs/reviews/2026-10-13-phase2-build4-batches1-2.md`).
- [ ] **[misc, Med, Trivial]** **Re-anchor the "latest" v2 questions at the next ingest.** Trigger: ingesting the Q3 2026 10-Qs for BAC, JNJ and XOM. Then `v2-bac-net-income-no-period`, `v2-jnj-cash-latest` and `v2-xom-net-income-last-quarter`, now pinned to Q2 2026, need a new figure, new `accepted` periods and new gold rows. After that, re-run `check_questions` on the v2 files. The checker can't catch this staleness, because the old Q2 anchor stays in the corpus.
- [ ] **[design, Med, Standard]** **Triage the 9 judge-template findings** from the misdirected review run over `18e9ec0` (`prompts/judge_criteria.py`, `compare_prompt_versions.py`). They are listed under "Out of range" in `docs/reviews/2026-10-13-phase2-build4-batches1-2.md`. Rewording a template means another judge sanity run, so batch it with R8's re-run where possible.
- [ ] **[refactor, Low, Trivial]** `check_questions --gold` still defaults to the v1 gold file, so checking the v2 questions without `--gold eval/retrieval_gold_v2.jsonl` errors every anchored part with "no gold rows". Derive the default from the questions path, as `_other_ids` does. Deferred from the phase 2 build 4 batches 1–2 code review (`docs/reviews/2026-10-13-phase2-build4-batches1-2.md`).
- [ ] **[misc, Med, Trivial]** **Live spot-check owed for the `[1, 6]` grader fix** (build 3a). After the branch merges, on a day with spare Gemini quota and not a v2 day: `python -m sec_agent.eval.eval_harness --backend gemini --ids crm-rpo-fy26,nvda-revenue-fy26-us-gaap,nvda-revenue-yoy-growth-q1fy27,msft-three-segments-revenue-q3fy2026` (the questions whose replayed answers cite with multi-index brackets). Offline, the replay showed 0 grade changes across 276 runs, 9 of them graded runs that use such brackets.
- [ ] **[bug, Med, Substantial]** **Phase 2 build 5: fact-tool fixes** (before the v2 baseline): fix `xbrl_facts`' four silent wrong answers on the new tickers (no-period path returns stale values and DEF 14A forms; TGT annual fiscal-year labels off by one; JNJ fiscal 2022 unreachable by label), add verified `Revenues` overrides (JPM, BAC, CAT, XOM) and TGT `CostOfGoodsAndServicesSold`, trace JNJ R&D 109M. Also for `period_labels`/`period_scope`: build 2 pinned TGT's `fiscal_year_end_month` to 2, which gives correct end-year labels with no code change, so only Target's start-year naming (its "fiscal 2024" is the year ending 2025-02-01) is left there. JNJ's fiscal 2026 ends 2027-01-03: once that 10-K is ingested, month 12 labels it FY2027 Q1, so the 52/53-week tolerance is needed for JNJ by about Feb 2027. Correct the stated invariants while there: `fiscal_year_label`'s docstring (every company names a year by the calendar year it ends in) and `_resolved_fiscal_year`'s, and `xbrl_facts`' "all five covered companies" default-tag comment (the default tags were never verified for the 7 new tickers). Keep v1 green; acceptance is a re-run of the tag check. `docs/research/2026-10-08-shortlist-xbrl-tag-check.md`
- [ ] **[misc, Med, Standard]** **Phase 2 build 6: v2 baseline.** `index_chunks --full` first (and the build-mode provenance item in the incremental indexing section), then one baseline, reported per category. If answerable questions pass above 80%, swap the easiest once. Then rank the headroom candidates: the per-company period-coverage note first, then a multi-ticket search or ticker subset on `compare_financial_metric`, then agent-improvement package 6.
- [ ] **[refactor, Med, Substantial]** Monorepo layout ahead of the web UIs. Details later, `/wayfinder` first.
- [ ] **[feature, Med, Substantial]** Admin web UI (ingest, rebuild, corpus status; phase 1 records the rebuild timings it needs). Details later, `/wayfinder` first.
- [ ] **[feature, Med, Substantial]** Chat web UI for the agent. Details later, `/wayfinder` first.

### From the 2026-10-09 free-tier LLM failover research

Research note: `docs/research/2026-10-09-free-tier-llm-failover.md`. Decided (user, 2026-10-09): no multi-provider router; the paid-tier question will be revisited, starting from that note's "Paid tier" and "Measured usage" sections, with `gemini-3.8-flash` as the first pilot candidate.

- [ ] **[bug, Med, Trivial]** **Pin the Gemini model id.** `GEMINI_MODEL_NAME` defaults to `gemini-flash-lite-latest`, an alias Google hot-swaps on every new release, with 2 weeks' notice only for breaking changes. A swap between two eval runs would look like a regression in our code. Live calls on 2026-10-09 resolved it to `gemini-3.5-flash-lite`; pin that exact id.
- [ ] **[feature, Med, Standard]** **Log the served model and token usage for each LLM call, and put both in eval reports.** `llm_backends.py` logs neither the response's `model_version` nor its `usage_metadata` (prompt, output, thinking and cached tokens), against the global rule that LLM calls log tokens. Reports record only the configured alias. Measured on 2026-10-09: 3.4 calls per question, 7,884 input and 184 output tokens per call, 53% implicit cache hits. Coordinate with the phase 2 v2-harness report provenance work. Also recheck the "a full run costs about 250" figure in `.claude/rules/live-eval-verification.md`: the measurement suggests about 165 agent calls plus judge calls.
- [ ] **[design, Med, Standard]** **Pilot `gemini-3.8-flash`, then decide which model is main and which is backup.** It is available on our free key with its own per-model quota (checked 2026-10-09), and it thinks by default. Steps:
  1. After the two items above, read 3.8 Flash's free daily quota in AI Studio.
  2. On a committed tree, run about 10 questions with `GEMINI_MODEL_NAME=gemini-3.8-flash`, then a full run if the result holds up.
  3. Make 3.8 main (with 3.5 Flash-Lite for exploratory `--ids` checks) only if it is clearly more accurate on our eval and its quota covers a full run (about 165 agent calls plus judge calls). Otherwise keep it as a backup for whole runs.

  Rules either way: switch models between runs only, never mid-run within an eval, and give each model its own baseline. Automatic 429 failover is acceptable only for non-eval agent use, after the served-model logging lands.
- [ ] **[feature, Med, Substantial]** **Agent vs. raw LLM benchmark (public write-up).** Decisions confirmed 2026-10-10 in `docs/research/2026-10-09-agent-vs-raw-llm-benchmark-decisions.md` (Round 2: settled); research in `docs/research/2026-10-09-agent-vs-raw-llm-benchmark.md`. Next step: `/wayfinder` map. Starts after the phase 2 v2 questions and the served-model/token-logging item above land. Roadmap slot: before the monorepo phase.

### From the 2026-10-06 data expansion phase 1 review

- [ ] **[bug (latent), Low, Trivial]** `edgar_ingest.get_filing_url` builds a `*_meta.json` path from an accession it doesn't check. `mcp_server.py:105` passes `accn` from raw XBRL companyfacts JSON. The path only feeds a read-only lookup for a citation URL. Fix: return None unless `_ACCESSION_PATTERN.fullmatch(accession)`, the check ingest already applies. This was the round 2 security residual in `docs/plans/2026-10-06-data-expansion-years.md`'s Review log, and it was left out because only the function's docstring is in that diff.
- [ ] **[bug (latent), Low, Trivial]** `index_chunks._scan_chunk_files` skips whitespace-only lines when counting chunks, but `load_chunks` decodes every line, so a chunk file with a blank line passes the identity count and then fails every build with a JSONDecodeError. `chunk_documents` never writes one today. Make both readers share the same rule (found in phase 2 build 2's code review).
- [ ] **[bug (latent), Low, Trivial]** `xbrl_facts.get_frame`/`_frame_entry` index frames-API entries (`entry["cik"]`, `["val"]`, `["end"]`, `["accn"]`) unchecked, so a malformed entry raises a raw `KeyError`. `get_metric` now drops such entries through `_entry_defect`/`_usable_entries`; frames entries have no `form`/`start`, so give them their own key check rather than reusing that one as-is. Same pass: `get_metric` passes an entry's raw `frame` to `get_frame`, which puts it into `fetch_frame`'s cache filename and URL unchecked; validate it against `^CY\d{4}(Q[1-4]I?)?$` (a path-traversal shape needs a tampered SEC response, so Low). Found while planning the pre-phase-2 hardening pass.
- [ ] **[bug (latent), Low, Small]** An SEC network failure on a cache-miss XBRL lookup (`requests` Timeout/ConnectionError, or a non-404 HTTPError from `fetch_concept`/`fetch_frame`) is not caught anywhere on the agent/MCP tool path, so it aborts the whole question instead of returning a tool error that sends the model to `search_filings`. The 30 s SEC timeout (2026-10-07) turned a hang into this exception; `eval_harness.run_eval` contains it per question. Fix at the dispatch boundary, with a log event. Deferred from the pre-phase-2 hardening review. Exposure grew in phase 2 build 2: `get_metric_all_companies`' instant-metric branch now makes 12 sequential `fetch_concept` calls, any one of which aborts the whole comparison on a cold cache.
- [ ] **[bug (latent), Low, Trivial]** `get_metric` still assumes a companyconcept payload's `units` is a dict and `units.USD` a list; a malformed whole payload raises instead of returning None. Individual malformed entries are already dropped by `_entry_defect`. Deferred from the pre-phase-2 hardening review.
- [ ] **[bug, Low, Standard]** **`analyze_citation_gate.classify_row` treats refusal and clarify rows as gate-attributable.** It excludes only `type == "judged"`; build 3a added the judge-graded `refusal` and `clarify` types, so a failed one with a citation is classed `false_negative_candidate` and inflates the gate's false-negative counts. Fix: exclude `type not in eval_harness.DETERMINISTIC_TYPES`. No v2 report exists yet, so nothing is miscounted today; trigger: the first v2 run. Found by build 3a's /simplify altitude pass (2026-10-09).
- [ ] **[refactor, Low, Standard]** **Two copies of the match-tolerance formula remain.** `calculate.py:67,76` and `table_grounding.py:340` still inline `max(0.01 * abs(norm), 0.05)` (and their comments describe it); build 3a moved citations.py and the grader to `numeric_utils.match_tolerance`. Same numbers today, so no behaviour change; the risk is a later tolerance change reaching the grader but not the agent's tools. Left out of 3a as outside its diff. Critical core (agent/, verification/).
- [ ] **[bug, Med, Standard]** **A bullet that starts with its number reads as negative.** `numeric_utils.extract_numbers` parses `- 20% for both ...` (a list item whose first token is the value) as -20%, taking the bullet marker for a minus sign; `rate was 20%` parses as 20. Since the 2026-09-12 negative-number change this can fail a correct grade (`grade_numeric` never finds +20) and can count a claim as unmatched in the citation checks. Found offline 2026-10-09 by build 3a's attribution sanity check on report `20260825T195207Z` (`aapl-msft-tax-rate-comparison`). Fix: treat a hyphen at line start (after indentation) followed by a space as a list marker, not a sign. `numeric_utils.py` is critical core: needs a live spot-check per `live-eval-verification.md`.
- [ ] **[improvement, Low, Standard]** On undated or repetitive queries, an older filing can outrank the current one. Offline replay on the expanded corpus found 3 lost hits of this kind:
  - `nvda-cost-of-revenue-fy2026`: the FY2024 and FY2025 10-Ks outrank;
  - `aapl-msft-employee-comparison`'s "employees OR staff" query: the FY2024 10-K risk factor outranks;
  - `aapl-cash-and-buyback-q3fy2026`: the FY2025 Q2 10-Q repurchase table outranks.
  It had no live effect (48/48), but it grows with every added year. Candidate: a recency prior for unscoped searches. Measure with `retrieval_replay --compare var/retrieval_replay/data-exp-new.json` first. The other 8 losses were 7 cases of rank churn within one filing and 1 scoping shift (`docs/decisions/2026-10-07-data-expansion-years.md`).

### From the 2026-10-06 package 4 rescope

- [ ] **[misc, Low, Standard]** Hash `eval/eval_questions.jsonl` (at least each question's criteria) into eval report provenance, and have `compare_prompt_versions` treat a change as a version boundary. Today `prompt_fingerprint()` covers `prompts/` only, so fingerprint mode pools grades from before and after a criteria change (`e8bd2a2`); see `docs/decisions/2026-10-06-close-package-4-not-available-answer.md`.

### From the 2026-10-05 rerank score cache plan

Plan: `docs/plans/2026-10-05-rerank-score-cache.md`. Review: `docs/reviews/2026-10-05-rerank-score-cache.md`.

- [ ] **[performance, Low, Standard]** An on-disk `hybrid_search` result cache for the replay tools, keyed by a fingerprint of the retrieval code and index, so a warm replay skips windowing, tokenizing and pool building too (about 0.7 s per search; the cross-encoder score cache in `devtools/rerank_cache.py` already skips `predict`). Trigger: a warm full gate replay over ~10 min. Measured 2026-10-05 with the score cache warm: gate replay 257 s (uncached 3,420 s), retrieval replay 169 s (uncached 2,403 s), so it isn't due. Startup (torch/transformers imports) measured about 22-30 s, too small for its own item.
- [ ] **[bug (latent), Low, Trivial]** The rerank score cache's file identity (`rerank_cache.install`) covers the sentence-transformers and torch versions but not `transformers`, so a `transformers` upgrade that shifts cross-encoder scores would still be served the old cached scores, and a replay `--compare` could hide a real difference. Until fixed, delete `var/rerank_cache/` after upgrading `transformers`. Fix: add `transformers.__version__` to the identity list. That starts a fresh cache file, so the next full replay is cold (about 42-55 min gate, then about 9 min retrieval). Trigger: do it with the next `transformers` upgrade, or earlier when a cold run is acceptable anyway.

### From the 2026-10-02 package 5 review

Plan: `docs/plans/2026-10-02-package-5-retrieval.md`. Review: `docs/reviews/2026-10-02-package-5-retrieval.md`.

- [ ] **[design, Low, Standard]** `rerank_windows.split_windows` carries a table header with no token budget, and its caption is the last non-blank line, which after one table is that table's `</TABLE>`. A long caption or wide header rows can push a window past 512 tokens with the query, so the cross-encoder truncates the row the window exists for. Both are faithful to the prototype the acceptance figures were measured on. A fix needs a cap (or the caption reset at `</TABLE>`) and a fresh `retrieval_replay` measurement, not a silent change.
- [ ] **[design, Low, Standard]** Period scoping matches on report dates alone. A search with no ticker scoped to a date also admits every other company's filing with the same report date (calendar quarter ends are shared), though only some companies' filings matched. Scoping by `(ticker, reportDate)` or accession number would be exact. Prototype semantics; measure with `retrieval_replay` before changing. Phase 2 build 2 gate: not triggered (2026-10-09). Every v1 search carries a ticker, so v1 can't show it. Offline exposure on the frozen query texts run untickered: 224 leaked filing slots across 56 queries, all on the fiscal-label path (MSFT's June-30 year end admits other companies' June-30 10-Qs). v2 measures it.
- [ ] **[refactor, Low, Standard]** `retrieval.search_details` returns an untyped 12-key dict that `retrieval_replay` reads by string key. A `TypedDict` would let pyright check the harness's reads.
- [ ] **[bug, Med, Standard]** The model cites a verbatim quote to the wrong source number, the quote being present in another source it retrieved, and the citation gate rightly refuses the answer. It caused both drops in the package 5 live eval (`eval/eval_results/20261003T030904Z.json`). `crm-ai-risk` cited [13] (`0001108524-26-000060_51`) for text in [15] (`_52`, the adjacent chunk), and the retry repeated it. `nvda-revenue-yoy-growth-q1fy27` cited [12] (the segment table) for the income-statement `Total revenue` row in [2], [14], [16] and [19]. Options: the gate's rejection message could name the retrieved source that does contain the quote, so the retry can fix the index, or the gate could re-attribute an exact unique match. Re-attribution changes what a citation guarantees and needs a design decision. Critical core (`citations.py`). Plan: `docs/plans/2026-10-02-package-5-retrieval.md` ("Testing and verification", step 14).
- [ ] **[refactor, Low, Trivial]** `retrieval_replay.question_parts` finds a comparison entry's company with `e["ticker"].split("-")[0]`, while the grader uses `grading.entry_companies` (the entry's `companies`, else an exact-ticker label, else the question's). Same result on every current question; a period-labelled entry ("FY2025") would get no gold rows. It also ignores an entry's `companies` list (`NII-gap` → "NII"), and `question["ticker"]` raises KeyError on a numeric question that has only `tickers`. Switch to `entry_companies`/`question_tickers` with the next `retrieval_replay` change. Found in build 3a.1's review, 2026-10-10.
- [ ] **[refactor, Low, Trivial]** `retrieval_replay.main` and `analyze_gate_replay.install_trace_capture` each swap the private `tracing._write_local_log` by hand. A small public context manager in `tracing` would cover both.

### From the 2026-09-24 prompt-audit roadmap

Design: `docs/plans/2026-09-24-prompt-audit-roadmap.md`. Findings: `docs/reviews/2026-09-24-prompt-audit.md`. The roadmap closed 2026-09-27 (WP8 bar met, 40/47). Summary: `docs/decisions/2026-09-27-prompt-audit-rollout.md`. Its follow-on work became the agent-improvement map (In progress). What's left here are its open items; trigger-only ones moved to the Watch list (2026-10-06). Anything that changes model-visible text still goes through the roadmap's panel-screen process, so batch the text items below into one screen where possible.

- [ ] **[misc, Low, Standard]** Tool-message text follow-ups (Step 7, plus two older items on the same messages):
  - reason-bearing rejections via `on_reject`, including a call rejected at the boundary (partial multi-year range, yoy + multi-year), which today reads as "no data … try search_filings";
  - `calculate`'s generic missing-argument message;
  - MCP search returning a silent `[]`;
  - a yoy no-data reply names the anchor period even when the prior year is the missing one (`formulas.py:353`; no live case, all 62 yoy calls found data);
  - the three "unknown ticker" paths disagree: `search_filings` names the bad ticker and lists valid ones, while `call_get_financial_fact`/`call_compare_financial_metric` fold it into their generic no-data messages. Upgrade the other two, or record why search differs (`docs/reviews/2026-09-10-fix-3-more-review-findings.md`).

  Each one changes model-visible text, so it needs a panel screen. `docs/decisions/2026-09-26-wp7-fiscal-year-strings.md`
- [ ] **[bug, Low, Standard]** A calculate result's expression pastes each operand's unit in as-is, so a `"raw"` operand (a plain ratio or count) reaches the model as e.g. "1.04 raw". The result value itself already omits "raw" via `tool_results.with_unit`. Found in the WP1 code review (`docs/reviews/2026-09-24-wp1-prompts-package.md`). It changes model-visible text: screen it with the tool-message batch above.
- [ ] **[refactor, Low, Standard]** Audit notes 8–10 (prompt style):
  - all-caps emphasis;
  - tool bullets in SYSTEM_PROMPT that duplicate the tool descriptions;
  - the size of rule 9;
  - sentences duplicated across the agent and MCP surfaces.
- [ ] **[design, Low, Standard]** The MCP `search_filings` schema is derived the wrong way round: `prompts.mcp.MCP_SEARCH_TOOL_SCHEMA` is the agent's schema with its agent-only text overridden, so agent-only wording in any other field reaches MCP clients silently. The `ticker` description already does ("…which company the question is about"), and three description sentences are written out on both surfaces. Fix: a neutral shared schema that the agent adds its note to. It changes model-visible text, so it needs a panel screen. Found in WP3's plan and code reviews (`docs/reviews/2026-09-24-wp3-group-a-wording.md`).

### From the 2026-09-22 eval-question-classification change

Full evidence/reasoning: `docs/plans/2026-09-22-eval-question-classification.md`'s
"Prior art" section.

- [ ] **[feature, Low, Substantial]** Adopting Meta-style same-commit
  burst reruns (rerun each eval question N times on one fixed code
  version before/after a change) would let a future version compute a
  true probabilistic flakiness score instead of `classify_history()`'s
  windowed streak/transitions proxy — holding code constant is what
  actually isolates "flaky" from "a real regression," which the current
  heuristic can only approximate from single-run-per-code-era history.
  Needs a new eval-harness feature (a same-version rerun mode), not just
  an analysis-script change — deliberately out of proportion to the
  2026-09-22 classification change itself.

### From the 2026-09-22 pytest-coverage adoption

Full evidence/reasoning: `docs/decisions/2026-09-22-adopt-pytest-coverage.md`,
`docs/decisions/2026-09-22-coverage-baseline-close-and-hard-gate.md`.

- [ ] **[test-coverage, Low, Standard]** Full-repo pytest coverage
  baseline mostly closed on 2026-09-22 (94% overall, up from 90%) — see
  `docs/decisions/2026-09-22-coverage-baseline-close-and-hard-gate.md`.
  `query_chunks.py` deleted (superseded), `index_chunks.py`/
  `eval_harness.py` fully closed. Still open: `retrieval/chunk_documents.py`'s
  `process_filing`/`main` (81% under branch mode, real file-I/O logic,
  testable but not live-only — deliberately not pragma-excluded) and
  `sec_agent/mcp_server.py`'s ASGI middleware/`build_app` (84% under branch mode
  — genuinely live wiring, but currently just uncovered, not
  pragma-excluded: `mcp_server.py` carries zero `# pragma: no cover`
  markers and isn't in `.claude/rules/live-code-tdd.md`'s list either —
  add both if this gap is closed via exclusion rather than new tests).
  Only the 90%/80% two-tier diff-coverage bar applies to new/changed
  lines going forward; these two remaining gaps close opportunistically,
  file by file, as those files are next touched for other reasons.

### From the 2026-09-17 orphaned-table-overlap chunking fix

Full evidence/reasoning: `docs/decisions/2026-09-17-fix-orphaned-table-overlap-chunking.md`
and its paired review file.

- [ ] **[design, Low, TBD]** `table_grounding.locate_value`'s
  1%-relative-tolerance was what let the original bug silently
  false-match a wrong-but-close cell (0.24% off) instead of failing
  cleanly with "value not found" — a contributing factor, not itself
  fixed by the chunking fix. Worth a future look at whether the
  tolerance should be tighter or paired with a stronger uniqueness
  check.
### From the 2026-09-15 broader ruff rule-category survey

Full evidence/reasoning: `docs/decisions/2026-09-15-expand-ruff-plr-rules.md`'s
Related section; raw findings not yet written up in their own decision
file pending which (if any) get adopted. Reproduce with
`ruff check --select B,SIM,UP,C4,RUF,ARG,RET,PERF,S,N,A,PTH,ERA,I .`

- [ ] **[design, Med, TBD]** Whether to select `S113`
  (request-without-timeout) and/or `B905` (zip-without-explicit-strict).
  Both surveyed with real hit counts, unlike a name-based guess:
  `S113` found 5 real production HTTP calls with no timeout at all;
  `edgar_ingest`'s now pass one, and the other three are their own bug
  item (2026-10-06 data expansion phase 1 review section), so selecting
  `S113` is now only about keeping new calls honest. `B905` found 2 real
  `zip()` calls in the retrieval path (now `retrieval.py:212,319`)
  that would silently truncate instead of erroring if Chroma ever
  returned mismatched-length document/metadata/distance lists. Rejected from the
  same survey, each for a specific reason rather than by category
  reputation: `S101`/`ARG001`/`ARG005`/`RUF059`/`B011` are 96-100%
  idiomatic test-file noise (asserts, mock-signature params, tuple
  unpacking) even where a handful of real hits exist; `ERA001` false-
  positives on this project's own comment-banner/decision-file-pointer
  conventions; `RET503` would push toward adding provably-unreachable
  dead code to satisfy the linter, contradicting the project's own
  error-handling philosophy; `RUF003` and a dozen other 1-4-hit codes
  weren't worth the selected-rule overhead at that volume.

### From the 2026-09-10 citation-gate-measurement-instrumentation plan

Full evidence/reasoning: `docs/plans/2026-09-10-citation-gate-measurement-instrumentation.md`.

- [ ] **[feature, Low, Standard]** Model-based veto before refusal (one entailment check before the hard gate withholds an answer) — deferred 2026-09-10 pending the structured-claims redesign's own measurement. Re-evaluated 2026-09-11 with the full 41-question baseline + 4-question stress set now analyzed: **0/45 gate fires post-redesign**, down from 6/45 (100% false positive) pre-redesign. Still no evidence a veto is needed — there's nothing left for it to overturn in this corpus. Revisit only if a wider/harder question set finds the gate firing again. **2026-09-26**: WP5's gate refusals on `nvda-revenue-two-quarter-comparison` were an uncovered-number false positive (the `1` in "a ÷ b − 1", `claims 1.0 (raw)`), not an entailment case. That goes to the narrow gate fix the WP5 close-out files, so there's still no evidence for a veto.
- [ ] **[refactor, Low, Trivial]** The `category, norm = normalize(...); tolerance = max(0.01*abs(norm), 0.05); any(c == category and abs(v - norm) <= tolerance for c, v in candidates)` pattern is now duplicated 6 times across `citations.py`/`calculate.py`/`table_grounding.py` (`_iter_citation_claims`, `value_is_citation_verified`, `_verify_one_claim`, `verify_claims`'s coverage check, `_ground_operand`/`call_calculate` for the `calculate` tool, 2026-09-11, and `table_grounding.locate_value`/`quote_is_grounded`, 2026-09-12) -- plus `eval_harness.grade_numeric`'s own copy, a natural 7th if a shared helper is ever extracted. Build 3a.1 (2026-10-10) extracted that helper for the eval side: `grading.value_matcher` serves `grade_numeric`, claim attribution and the question validator. Move it to `numeric_utils` and fold in the citations/calculate/table_grounding copies with the next change there that runs a live spot-check anyway. Pre-existing style tolerated 3 times already; the `calculate` tool's addition was a good opportunity to extract a shared `_matches_any(value, unit, candidates) -> bool` helper instead of continuing to copy it, and the table-grounding fix is a second one, deferred for the same reason. Found in the `calculate` tool's architecture review, 2026-09-11 (`docs/reviews/2026-09-11-calculate-tool-and-stress-questions.md`) -- not fixed there or in the 2026-09-12 fix, since it's a cosmetic DRY cleanup unrelated to either change's actual scope.

### From the 2026-09-06 full-codebase review

Full evidence/reasoning for each: `docs/reviews/2026-09-06-full-codebase-review.md`.
All numbered findings from this review are resolved — see
`docs/decisions/2026-09-06-full-codebase-review.md` (§1-§4, plus the
2026-09-07 addendum), `docs/decisions/2026-09-08-fix-3-medium-review-findings.md`
(§5/§7/§9), `docs/decisions/2026-09-09-fix-3-more-review-findings.md`
(§6/§8/§10), and `docs/decisions/2026-09-10-fix-3-more-review-findings.md`
(§11/§12/§13). The two genuinely open, lower-priority findings this
review also surfaced remain below.

- [ ] **[design, Low, Standard]** `tracing.py` has two overlapping "record an instantaneous fact" primitives (`record_unmet_metric_request` vs `log_event`) with no documented decision rule for which to use

### From the 2026-09-10 layered review of the §11/§12/§13 fixes

Full evidence: `docs/reviews/2026-09-10-fix-3-more-review-findings.md`.

- [ ] **[performance, Low, Standard]** `_never_tagged_hint()` (called from both `format_no_fact_message` and, as of §12, `format_no_comparison_message`) re-fetches `xbrl_facts.fetch_concept()` for the exact (ticker, tag) pair the caller's own lookup just fetched moments earlier — normally a free disk-cache hit, but `fetch_concept()` never caches a 404 response, so on the one case this hint actually exists for (a company that genuinely never tags a concept at all) it makes a real second live SEC network round-trip synchronously inside message formatting. Root cause is in `xbrl_facts.fetch_concept()`'s caching, not in either message formatter — a separate, larger-scope item than either function's own fix. (The section's other item, unknown-ticker message inconsistency, moved into the prompt-audit tool-message batch.)

### From the 2026-09-09 schema-driven arg-validation redesign

Full evidence/reasoning: `docs/plans/2026-09-09-schema-driven-arg-validation.md`, `docs/reviews/2026-09-09-schema-driven-arg-validation.md`. Surfaced while auditing the codebase for other schema-validation opportunities, or by that change's own two-pass review — real but lower-severity than what that change fixed, not addressed there.

- [ ] **[refactor, Low, Standard]** `dispatch_tool_call`'s `search_filings` branch re-derives ticker validity by hand (`isinstance`/`COMPANIES` membership) a second time, after `validate_tool_args` already checked the same thing internally via the schema, purely to decide which rejection message to show — a residual instance of the same "hand-rolled check duplicating the schema" pattern this redesign otherwise eliminated. Found in the redesign's own architecture-review pass; not fixed there because a clean fix means changing `validate_tool_args`'s return type across all 4 call sites for a 2-line message-selection convenience, out of proportion to that change.

## Watch list

Latent items with nothing to do until the named trigger is observed. When it is, move the item
back into an origin section as work. One line each: the trigger, plus the record that holds the
detail. The fuller write-ups from before the 2026-09-26 cleanup are in
`git show e45de8b:BACKLOG.md`.

**Citation verification**

- **[test-coverage, Low, Trivial]** Package 3's second citation retry hasn't run live yet: in the 2026-10-06 full run all 3 retried runs needed only `attempt: 1`. Trigger: a `citation_retry` event with `attempt: 2` in traces (check whether it rescued the run, then close this). `docs/reviews/2026-10-06-package-3-uniform-submit-loop.md`
- **[bug, Low, Standard]** `_CITATION_MARKER` doesn't match a multi-source bracket like `[1, 2, 3]`, so the eval grader's `value_is_citation_verified` treats a value cited that way as uncited (passes on a plain-text match). The agent's gate handles it via `_ANY_CITATION_BRACKET`. Trigger: a numeric eval question graded PASS on a wrongly multi-cited value. `docs/plans/2026-09-10-citation-gate-measurement-instrumentation.md`
- **[bug (latent), Low, Standard]** `_verify_one_claim` checks quote-to-value grounding, not whether the answer's own prose labels the cell's period correctly. A fix needs a `period` field on the claim schema. Trigger: a live false accept. `docs/plans/2026-09-12-structure-aware-table-quote-grounding.md`
- **[bug (latent), Low, Trivial]** `_quote_matches`'s flat anchor path can accept a wrong-period or digit-inflated quote for a prose-only value (table sources no longer use it). Trigger: a prose-path false accept. `docs/reviews/2026-09-13-table-grounding-region-scoped-matching.md`
- **[bug (latent), Low, Standard]** `table_grounding`'s fuzzy coverage could accept a similar-but-wrong segment label from a different table block. Trigger: a tracked filing with near-identical sibling labels. `docs/reviews/2026-09-13-table-grounding-region-scoped-matching.md`
- **[bug (latent), Low, Trivial]** A large `header_context` inflates `quote_is_grounded`'s coverage (25% → 88% in synthetic testing, never past the 90% threshold). Trigger: a fabricated quote crossing it. Package 2's D12a (2026-10-01) widens the header context of tables whose first row is a period header; the trigger is unchanged. `docs/reviews/2026-09-13-table-grounding-region-scoped-matching.md`
- **[bug (latent), Low, Trivial]** `_classify_row` treats a data row with a blank first cell as a header and drops it from `locate_value` (fails safe to `_quote_matches`). Trigger: a real filing with that shape. `docs/reviews/2026-09-13-table-grounding-region-scoped-matching.md`
- **[feature, Low, TBD]** `NUMBER_PATTERN` doesn't recognize `M`/`B`/`K`/`bn` abbreviations: `"$81.6B"` and `"$81.6bn"` parse as `(81.6, 'raw')`, so an answer using them fails coverage against a claim in billions. Rule 9 bans them; if ever added, recognize `MM`/`Bn`, not bare letters. Critical core: escalated plan review and a live spot-check. Trigger: an abbreviation in a live answer. `docs/decisions/2026-09-17-uncovered-number-gap-fixes.md`, `docs/research/2026-09-28-grounding-computed-numbers.md`
- **[test-coverage, Low, Standard]** Citation stress modes: the two-nearby-percentages question (`nvda-revenue-yoy-growth-q1fy27`) cited the risky sentence in only 1 of 3 runs, and a paraphrased quote near the 0.90 threshold is untested. Trigger: `analyze_flakiness.py` history showing the risky sentence exercised reliably (then close it), or a way to force a paraphrase. `docs/decisions/2026-09-23-restore-nvda-yoy-stress-question.md`

- **[feature, Low, Standard]** Gate rules D3 (a verified quote covers its own numbers) and D4/D11 (placeholder values become qualitative), deferred from improvement-map package 2: both loosen the gate and none of the 17 post-package-1 retries needed them. Includes the 2026-09-11 `nvda-gross-margin-fy26` case: a redundant second claim restating an already-verified value (71.1%) under another citation, whose quote doesn't contain it, refused the whole answer. The options there are a rule 9 line against redundant restatement claims, or tolerating a claim that duplicates a verified value. Trigger: a re-mine showing a placeholder, quote-number or redundant-restatement refusal. `docs/plans/2026-10-01-gate-rules-package-2.md`
- **[bug (latent), Low, Standard]** `locate_value(74550, "million")` on NVDA `0001045810-26-000052` chunk 34 also matches a percentage-table cell (`74.9` read as billions, within 1%), so a quote of that cell could ground a wrong value. Trigger: a live accept citing it. `docs/plans/2026-10-01-gate-rules-package-2.md`
- **[bug (latent), Low, Standard]** `quote_is_grounded` accepts a foreign group label that differs from the cell's own by a single letter: `| Segment A |` over Segment B's `Revenue | $34,681` grounds, while `Cloud`/`Gaming` and `Level 1:`/`Level 2:` are refused. The one-letter token is probably dropped as noise. Found in the package-2 review. Trigger: a live filing with letter-suffixed group labels. `docs/reviews/2026-10-01-gate-rules-package-2.md`

- **[bug, Low, Standard]** `pltr-inventory-turnover-fy2025-refusal`: the model files a fiscal year as a numeric claim ("[6] claims 2025 (raw)…") or a value with no unit, so a correct no-data refusal is withheld; `withheld_answer` is empty, so the eval's gate-FP flag misses it. Since the retry slot (2026-09-30) and uniform submit loop it passed 12/12 in October runs, so it's rescued, not fixed. Open questions: treat a year-shaped raw claim as non-claim; allow a refusal with no numeric claims. Critical core. Trigger: it fails again, or year-shaped claims show up in the harder eval questions. `docs/decisions/2026-09-30-citation-retry-own-slot.md`
- **[bug, Low, Standard]** `_NON_CLAIM_PATTERN`'s duration exemption covers only year/month/day; "12 weeks" or "2 quarters" still read as uncovered numbers. Each new word is whack-a-mole. Trigger: a live run withholds on one. `docs/decisions/2026-09-17-uncovered-number-gap-fixes.md`
- **[design, Low, Standard]** Rule 9's "computed as" example shows only a ratio and `calculate` renders percent_change as prose, so the model improvises its own percent-change formula; "× 100%" isn't covered as an identity (it would exempt a real "100%" claim). Fix: a percent_change example, or match `calculate`'s rendering (prompt change, panel run). Trigger: live runs withhold a percent derivation.
- **[bug, Low, Standard]** Percent-identity coverage in `verify_claims` keys on a `calculate` percent result only, so "current ÷ prior − 1" written after a `get_financial_fact(yoy_growth=True)` result would still withhold for the 1. Fix: also grant the identities for a yoy_growth result. Trigger: a run shows it.

**Refusals that need the failing quote captured** (check the `submit_answer` span's `checks` in `trace_logs/traces.jsonl` first; the trace query script item helps)

- **[bug (latent), Low, Standard]** `nvda-cost-of-revenue-fy2026`: a `quote_not_found` refusal via `search_filings` prose, then clean via XBRL on re-run. Trigger: a recurrence. `e45de8b:BACKLOG.md`
- **[bug (latent), Low, Standard]** `msft-segment-revenue-comparison-q3fy2026`: `quote_not_found` on the real segment values `35013`/`34681`/`13192` (2026-09-14 baseline). Not a gate false positive: the 2026-10-01 replay shows the cited source is the summary-of-results chunk, which lacks the segment table (the quote is verbatim in the MD&A table and grounds there). Trigger: a recurrence citing the right chunk. `e45de8b:BACKLOG.md`

**Agent loop and code structure**

- **[bug (latent), Low, Standard]** A submission from a mixed submit+search turn (answered with `MIXED_TURN_RESUBMIT_MESSAGE`) isn't cached the way a retried one is (`pre_retry_submit_args`). If the model then answers in text twice, the run is refused as `no_submission` instead of re-gating that submission against the larger result set. Trigger: a `no_submission` refusal whose trace shows an earlier mixed-turn submit. Code review of `docs/plans/2026-09-29-remove-ollama-and-prose-fallback.md`.
- **[bug (latent), Low, Standard]** The final-turn safety net could force a grounded but incomplete answer (fewer companies than asked). Trigger: a confidently wrong ranking from a forced submit. `docs/decisions/2026-09-16-final-turn-safety-net.md`
- **[refactor, Low, Trivial]** `dispatch_tool_call`'s tool branches are an if-chain. Trigger: a 5th or 6th tool (then use a dispatch table). `docs/reviews/2026-09-11-negative-number-support.md`
- **[refactor, Low, Standard]** `formulas.py` has 3 hand-written zero-denominator guards. Trigger: a 4th call site (then extract a shared `_safe_ratio()`). `docs/reviews/2026-09-08-fix-3-medium-review-findings.md`
- **[feature, Low, Substantial]** Per-call LLM generation tracing in Langfuse (tokens, prompt/completion text, cost and latency per call). Trigger: a real debugging need. `docs/decisions/2026-09-04-langfuse-tracing.md`

**Tooling and workflow**

- **[design, Med, Standard]** Audit finding 7: the judge verdict is parsed from a two-line format (`startswith("PASS")`), so `**PASS**` or a preamble would grade FAIL. Fix: structured output for the judge. It touches `grade_judged`, so it needs a panel screen. Trigger: `lenient parse disagrees` in any eval report (0 hits through WP8). `docs/reviews/2026-09-24-prompt-audit.md`
- **[design, Low, TBD]** Pyright strict mode (rejected 2026-09-15: ~94% of its errors were noise from dict-shaped data). Trigger: less untyped-dict data flow (`TypedDict`/`dataclass`), or a scoped-down strict preset. `docs/decisions/2026-09-15-adopt-pyright.md`
- **[design, Low, TBD]** A `PreToolUse`/`ExitPlanMode` hook backstop for the plan-review floor. Trigger: instruction-only enforcement caught missing a review. `docs/decisions/2026-09-17-mandatory-plan-review-floor.md`

**Retrieval**
- **[misc, Low, Standard]** Eval records can't tell a fresh index from an incrementally updated one. Incremental adds and deletes can shift HNSW top-k ties, and `corpus_provenance` reports only `index_matches_chunks`, so today the guard is the "run `index_chunks --full` before a baseline" convention. Fix: write the build mode (or the last full rebuild's time) into the `corpus_identity.json` sidecar and surface it in `corpus_provenance`. Trigger: a baseline comparison that shows unexplained retrieval drift, or before the v2 eval suite's first baseline. `docs/reviews/2026-10-07-incremental-indexing.md`
- **[refactor, Low, Standard]** Two readers of the chunk files: `retrieval._load_bm25_index` keeps its own glob, line parser and `_make_id`, mirroring `index_chunks.load_chunks`/`CHUNK_FILE_GLOB`/`make_id`. Today they agree (both reject a blank line), but either can drift, so the vector index may accept a file BM25 then fails on at query time, or the reverse. Fix: have `retrieval.py` call the `index_chunks` ones (no import cycle). It touches ranking-path code, so it needs a live-eval spot-check. `docs/reviews/2026-10-07-incremental-indexing.md`
- **[bug, Low, TBD]** ANN recall misses exist: in 2 of 30 logged queries, a chunk with an exact vector rank in the top 25 was left out by Chroma's HNSW search (`index_recall` class). This revisits `4c6850c`, which ruled HNSW tuning out because no failure had been an ANN-recall problem. That's no longer true, but the size is unmeasured. Trigger: the `index_recall` count in package 5's acceptance report is a material share of misses. `docs/reviews/2026-10-01-retrieval-harness.md`
- **[feature, Low, TBD]** V3 (glued-month de-glue in the chunker) and V4 (tables as their own chunks) weren't measured: dilution fell from 66 misses (V0) to 17 under strict period scoping, against 414 rerank misses in V6. Trigger: dilution grows after package 5 ships. `docs/plans/2026-09-30-retrieval-gold-rank-harness.md`
- **[misc, Low, Trivial]** `Alibaba-NLP/gte-multilingual-reranker-base` crashes under transformers 5.15 (its remote modeling code indexes RoPE with bad `position_ids`), so it was never timed. Trigger: a reranker model swap is reconsidered. `docs/research/2026-09-30-rerank-improvement.md`
