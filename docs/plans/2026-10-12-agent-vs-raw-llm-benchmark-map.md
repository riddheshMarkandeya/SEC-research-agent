# Map: agent vs. raw LLM benchmark (public write-up)

Date: 2026-10-12. The wayfinder map for the BACKLOG item "Agent vs. raw LLM benchmark". It was
charted from three grilling rounds with the user (Rounds 1–2 on 2026-10-10, Round 3 on
2026-10-12). Ticket state lives only in this file. Building waits for the phase 2 v2 questions
and the served-model/token-logging BACKLOG item.

## Destination

A frozen design for a public, re-runnable benchmark answering "does our agent make Gemini's
financial answers better, and by how much?". The design covers:
- each condition's prompt and answer format;
- how every outcome is graded and classified;
- the statistics;
- the preregistration;
- the report generator.

Done means every ticket below is decided, the build work packages are ordered in BACKLOG behind
v2, and this map is frozen. Running the benchmark and publishing it are build packages, not map
work.

## Notes

- **One decision ticket per session**; research and task tickets are exempt.
- **Quota.**
  - Free tier, per day: 3.5 Flash-Lite 15 RPM / 250K TPM / 500 RPD; 3.8 Flash 5 RPM / 20 RPD.
  - Search grounding is not on the free tier.
  - A full v1 or v2 AG run is about half a day's Flash-Lite quota. Never run v1 and v2 on the
    same quota day.
  - See `.claude/rules/live-eval-verification.md` and the research note's addendum.
- **Facts already established** (don't re-derive):
  - Both question sets have gold passages. `eval/retrieval_gold.jsonl` holds 247 verbatim
    anchors for v1, and the phase 2 map requires one per v2 gold value. B4 and retrieval
    recall@k need no new authoring.
  - The AG grader is stricter than any baseline can be. `grade_numeric` with `all_results`
    also requires the value to be citation-verified. v2 attribution and trap checks read the
    submitted claims (`eval_harness._attribution_failure`, `grading.claim_attributions`).
  - The project's default model is the moving alias `gemini-flash-lite-latest`
    (`config.py:65`). Today it maps to `gemini-3.5-flash-lite`, version
    `3.5-flash-lite-07-2026`.
  - The agent's tools: `search_filings`, `get_financial_fact`, `compare_financial_metric`,
    `calculate`, `submit_answer` (`prompts/agent_tools.py`).
  - AG measured on 2026-10-09: 3.4 calls per question, 7,884 input and 184 output tokens per
    call.
- **Condition labels.**
  - AG: the full agent.
  - B0: the same model, no tools.
  - B1: 3.8 Flash, no tools.
  - B2: the same model plus Search grounding.
  - B3: the whole filing in the prompt.
  - B4: the exact gold passage given.
  - A-x: the agent without tool x.
- **Skills**: `grill-me` for grilling tickets, `research` for research tickets.

## Decisions so far

Full questions, options and reasoning:
`docs/research/2026-10-09-agent-vs-raw-llm-benchmark-decisions.md` (Q1–Q22, plus each round's
"settled" section).

- **Audience** (Q1, user): a public write-up first, designed to be re-run. The v1/v2 eval stays
  the internal gate.
- **Headline pair** (Q2): AG vs. B0, always shown next to AG vs. B2. Gemini models only (Q5).
- **Question sets** (Q3): v2 by category is primary, and v1 is a separate panel. AG is near
  ceiling on v1 (47/48), so that panel mainly shows baseline levels (assumption D).
- **Phases** (Q6):
  1. AG, B0, B2, B1;
  2. B4, B3;
  3. the tool ablations, which are descriptive only at this n.
- **Scoring** (Q7, Q15):
  - Five outcomes: correct / wrong / wrongly declined / correctly declined / couldn't parse.
  - "No figure stated" means declined. Couldn't parse scores like a decline. API errors re-run
    and are never outcomes.
  - Also reported: correct-given-attempted, and a penalty score of +1 / 0 / −1 (p = 1, fixed in
    advance).
  - Every condition's prompt carries the same "answer only if confident" instruction.
- **Grading parity** (Q13):
  - The headline grades every condition on the value alone, with identical code.
  - A citation axis is recorded for each stated figure: verified / unverified / uncited.
  - AG's citation-gate withholds are counted inside its declined bucket.
- **Answer format** (Q14; schema part superseded by "B2 answer format" below):
  - AG and the ablations keep `submit_answer`.
  - ~~B0–B4 return prose, claims and `refused` through a response schema.~~ B0–B4 answer in
    prose plus a claim trailer instead.
  - Value grading reads the prose and attribution reads the claims, exactly as for AG.
  - No extractor model.
- **Cutoff split** (Q8): post-cutoff means filed after the model's public release (3.5
  Flash-Lite GA was 2026-07-21), checked with a 20–30-call dated-fact probe.
- **Judge** (Q9, Q21): 3.8 Flash judges the LLM-judged questions. The headline uses only the
  deterministically graded categories.
- **Repeats** (Q10): B0, B1 and B4 run 3 times; AG runs 3 times over 3 days; everything else
  runs once. McNemar pairs each question's majority outcome over the 3 runs, with pass^3 and the
  spread shown next to it (assumption B).
- **Headline statistic** (Q19): AG vs. B0 on the deterministic v2 questions. The accuracy
  difference is tested with exact McNemar, and the penalty-score difference is shown next to it.
- **Reproducibility** (Q16–Q18):
  - One tagged agent commit for every run.
  - Pinned `gemini-3.5-flash-lite`, never the alias.
  - The served model is checked on every call, and a change invalidates that condition's runs.
  - A preregistration doc is committed before the first run, and the report cites its SHA. It
    fixes the conditions, p, the tolerance, the primary comparison, the tests and the
    couldn't-parse threshold.
  - A pilot run precedes the preregistration.
- **Quota split** (Q4, Q20, Q21):
  - Free tier: AG, B0, B3, B4 and the ablations.
  - A paid project: B2, B1 and the judge. That costs about a dollar or two; B2's searches stay
    inside the 5,000 free each month.
  - This is a narrow exception; the parked paid-tier decision stays open.
- **B2 logging** (assumption A): every call logs `webSearchQueries`, `groundingChunks` and
  `groundingSupports`. B2 is published as a dated snapshot, with its run dates stated.
- **B3 scope** (assumption C, partly reopened): single-filing questions take the whole filing,
  context first. The 250K-token rule for multi-company questions is reopened by the ticket "B3
  under the token cap": every BAC and JPM filing alone exceeds 250K.
- **Report** (Q11): a script builds a Markdown report under `docs/` from saved eval reports,
  with a summary in the README. A visual page comes later.

- **B2 answer format** (grilling, 2026-10-12; revisits Q14's schema because B2 can't use one):
  - **Every baseline (B0–B4) answers in prose, then a fixed trailer**: `CLAIMS:`, then one
    `CLAIM: ticker | value | unit | period` line per figure, or a single `REFUSED` line. One
    parser serves them all, so B0 and B2 differ only in Search. The pilot's couldn't-parse
    threshold guards the lost constrained decoding. AG and the ablations keep `submit_answer`.
  - **Companies are matched by ticker.** The prompt gives the corpus ticker list, and the parser
    also accepts `companies.json` names and aliases. An unmatched company is a logged
    attribution failure, not couldn't-parse.
  - **The trailer decides declined vs. stated.** `REFUSED` or no claim lines means declined. A
    missing or malformed trailer means couldn't parse. Values are graded from the prose.
    Prose/trailer disagreements are a counted diagnostic, not an outcome.
  - **B2's citation axis** labels each stated figure from the groundingSupports covering its prose
    sentence:
    - cited, primary: sec.gov or the company's own domain;
    - cited, third-party: other sites only;
    - uncited: no support covers it.

    Both "cited" labels count as unverified on the shared axis.
  - **Probe** (3 grounded calls, under $0.01): grounding metadata survived on all 3. Supports
    cover the prose only, never the trailer. All 3 trailers parsed. One claim said "Advanced
    Micro Devices" rather than AMD, which is why ticker matching is needed. Searches ran 1 for a
    single-company question and 4 for a two-company question.

- **Gemini quota and model facts** (research, 2026-10-12):
  - Search grounding is not on the free tier, so B2 needs billing.
  - 3.8 Flash's free tier is 20 RPD.
  - B3 fits Flash-Lite's 250K TPM, at about 2 whole-filing calls a minute.
  - Both models have stable IDs and responses carry `modelVersion`. No official knowledge
    cutoff is published.
  - Search plus a JSON schema is documented only as a Preview, on another model.

  → `docs/research/2026-10-12-gemini-benchmark-quotas.md` (with an AI Studio rate-limit
  addendum)
- **Feasibility probes** (task, 2026-10-12; under $0.01, 5 of the 5,000 free searches):
  - **Search runs in every config, but `grounding_metadata` is returned only for plain-prose
    output.** Schema JSON and instruction JSON both drop it. Instruction JSON also came back
    fenced, with the value as a string. B0 declined both test questions.
  - **`modelVersion` returns the resolved model ID** (the alias came back as
    `gemini-3.5-flash-lite`). The served-model check catches alias drift, not a silent update
    behind a stable ID.
  - **Filing sizes:** median 10-K 113K tokens, median 10-Q 80K. **All 20 BAC/JPM filings exceed
    250K** (up to 489K), and every filing fits the 1M window. 3.8 Flash spends thinking tokens
    even on one-word replies.

  → `docs/research/2026-10-12-gemini-benchmark-quotas.md` ("live feasibility probes")
- **Background research** (2026-10-09): the condition ladder, metrics, statistics and validity
  threats → `docs/research/2026-10-09-agent-vs-raw-llm-benchmark.md`

## Open tickets

### B3 under the token cap
- Question: All 20 BAC/JPM filings exceed the free tier's 250K TPM in a single call, and most
  multi-company prompts would too. How does B3 handle them?
  - Option: run B3 on the paid tier (4M TPM). Roughly $3–5 per 104-question run, above the
    current $5 credit once repeats are counted.
  - Option: free tier, with bank filings and over-cap prompts marked n/a for B3 and the n
    reported. That drops the same-sector pair that v2's look-alike traps rely on.
  - Option: paid for over-cap prompts only, free for the rest.
- Type: grilling.
- Blocked by: none. The exact n per option is only known once v2 lands.
- Status: open

### Ablation list
- Question: Which A-x conditions run in phase 3? Candidates: −`search_filings`,
  −`get_financial_fact`, −`calculate`, −`compare_financial_metric`, −rerank.
  - Each is a full agent run.
  - Results are descriptive (a 5–0 discordant split gives p = 0.0625).
  - Quota sets how many fit.
- Type: grilling.
- Blocked by: v2 landing and the agent tag being chosen. These are external, in BACKLOG
  "Phase 2 build"; the tool set may change during v2 headroom work.
- Status: open

## Not yet specified

- **The headline question subset.** Which v2 categories are deterministically graded, and how
  many questions each holds, is known only once v2 is written. If the deterministic subset is
  small, the headline's power changes. Becomes a task ticket (inventory v2) when v2 lands.

## Out of scope

- **Google Deep Research comparison**: reconsider once this benchmark's results are in (user,
  Q22).
- **Gemma 4 (or any open-weight model) as a condition**: a future benchmark, not this one (user,
  Q22; Q5 limits this one to Gemini).
- **Non-Gemini model families**: Q5. Each needs a new tool-calling backend.
- **A visual HTML report page**: Q11, later, once the numbers are stable.
- **A private held-out question split**: n ≈ 56 is too small to halve. Preregistration covers
  the after-the-fact-choice risk instead.

Not out of scope but not a decision either: use the Batch API for any paid single-call
Flash-Lite runs (B0/B3/B4-style; the agent loop is multi-turn). That's a build detail for the run
package (user, Q22).
