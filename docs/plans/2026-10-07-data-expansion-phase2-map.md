# Map: data expansion phase 2 and the v2 eval suite

Date: 2026-10-07. The wayfinder map for the roadmap's next two items (data expansion phase 2,
harder eval questions), which it merges. Charted in two grilling rounds with the user. Ticket
state lives only in this file.

## Destination

A frozen design for (a) the new company list and (b) the v2 eval suite: question types, size,
grading, how questions get written, and how v1 coexists with it. Done means every ticket below
is decided, the build work packages are ordered in BACKLOG, and this map is frozen.

## Notes

- **One decision ticket per session**; research tickets run in the background and are exempt.
- **Quota**: Gemini free tier, 500 requests/day, about 5 per question (a full 48-question v1 run
  costs about 250). v1 and a full v2 run don't fit in one day. See
  `.claude/rules/live-eval-verification.md`.
- **Benchmarks are a design reference, not a data source**: copy their taxonomy and sector mix,
  write fresh questions on our FY2024+ filings. Their public Q&A is a contamination risk, and
  their filings are stale.
- **Facts already established** (don't re-derive):
  - Skip-refetch exists: `edgar_ingest._already_ingested`.
  - Indexing re-embeds everything: `index_chunks.main` deletes the collection; 1,258 s for 7,572
    chunks.
  - Each 10-K carries 3 years of income statement, and the XBRL fact tools return every year SEC
    holds, not only ingested ones.
  - `prompts/agent_system.py` hard-codes "five companies", and the ticker list feeds the tool
    enum, so adding companies is a panel-screened prompt change.
- Skills: `grill-me` for grilling tickets, `research` for research tickets.

## Decisions so far

- **Destination** (user, 2026-10-07): as above. The UI is out of scope.
- **Skip-refetch → incremental indexing** (user): skip-refetch is already done (phase 1).
  Incremental indexing (embed only new chunk files, no collection delete) is the first build
  package. It waits on no ticket, so it's in BACKLOG now as its own item.
- **The old 48 become v1** (user): a frozen regression gate. A question moves into v2 only if it
  fits a v2 category.
- **Benchmark use** (user): taxonomy and sector mix only; no reused companies or questions.
- **v2's purpose** (user): headroom for agent work. The target baseline is about 60–75%, so real
  failures exist. Results are reported per category, alongside the benchmarks' categories.
- **Size** (user): v2 is about 50 questions, limited by quota and statistics (one question = 2
  percentage points; about 8+ per category before a change means anything). 10–12 companies in
  total, limited by sector coverage: one per structurally different sector, plus at least one
  same-sector pair as a look-alike distractor. Corpus size costs ingest and index time, not
  quota.

- **R1 Benchmark landscape** (research, 2026-10-07): FinanceBench is the closest match: 40
  companies across 9 of 11 GICS sectors (IT 25%), 360 docs (75% 10-K), with the hardest setting
  being a shared multi-company store (GPT-4-Turbo 19% vs 79% long-context). Other benchmarks fail
  most on compound metrics (SEC-QA 33% vs 90% on single values) and on entity or period mix-ups
  (Fin-RATE). Suggested v2 mix and sector advice are in the note's Inferences; FinanceBench, SEC-QA,
  FinDER and Fin-RATE figures come from HTML summaries, so check them before a decision rests on
  them. → `docs/research/2026-10-07-financial-rag-benchmarks.md`

- **R2 Sector-specific reporting** (research, 2026-10-07): the fact tools map one us-gaap tag per
  metric (`DEFAULT_METRIC_TAGS` plus per-ticker `METRIC_TAG_OVERRIDES`, `xbrl_facts.py:50-63`,
  checked). The default revenue tag is live for only 7 of 21 sampled tickers; gross profit and
  operating income are missing for banks, insurers, energy and most pharma. The annual fiscal-year
  rule uses the end-date year (`_resolved_fiscal_year`, checked), which mislabels companies that
  name a year by its start (HD, TGT, JNJ) but fits WMT and COST. Traps: XOM's facts moved to a new
  CIK with 10-K history under the old one, CAT net income is under `ProfitLoss`, and some tags
  look right but hold a different line. Sector headline metrics (FFO, NIM, combined ratio,
  comparable sales) aren't companyfacts tags, so they're text-only (unverified against filing
  text). → `docs/research/2026-10-07-sector-xbrl-reporting.md`

- **Build order before the first ingest** (user, 2026-10-07): (1) a pre-phase-2 hardening
  package of existing BACKLOG items: the `edgar_ingest` Unicode console crash, the `xbrl_facts`
  pass (SEC timeouts incl. `discover_tags`, canonical-date helper, unchecked `get_metric`
  indexing) and the `prompts/agent_tools.py` enum hoist; (2) incremental indexing. Neither blocks
  a ticket. Carry-overs for the v2 build, before its first baseline: the harness
  `CITATION_PATTERN` and the grader's `_CITATION_MARKER` both miss multi-source brackets like
  `[1, 6]`, which cross-company answers will use; and eval report provenance must hash the
  question file so v1 and v2 reports can't be pooled.

- **Company list** (user, 2026-10-08): 12 companies, the current 5 tech names plus 7 stress
  picks, one per sector, each triggering a distinct break verified by R2: JPM + BAC (bank
  look-alike pair, a retrieval distractor), TGT + WMT (retail pair, both Consumer Staples,
  late-Jan year-ends, opposite fiscal-year naming; chosen over HD as the truer look-alike), XOM
  (energy), JNJ (health care), CAT (industrials). Insurer, REIT and utilities are dropped,
  leaving 6 GICS sectors; acceptable because v2 reports per category. The tech names stay
  because v1 depends on them, and swapping frees no quota. Instead, v2 is **skewed away from
  tech** (about 5 questions on tech, mostly cross-company); this goes to the question-mix
  ticket. All CIKs are pinned by hand in `companies.json`. XOM is 34088: EDGAR checked
  2026-10-07, every 10-K/10-Q through the 2026-08-03 10-Q is under 34088, and the new CIK
  2115436 has only that one 10-Q.

## Open tickets

### Company list

- Question: Which sectors and tickers (10–12 in total), and which same-sector pair?
- Type: grilling
- Blocked by: R1 Benchmark landscape, R2 Sector-specific reporting
- Status: done (see Decisions so far)

### Filing depth

- Question: (a) Keep FY2024+, (b) 5 years of 10-Ks plus recent 10-Qs, or (c) 5 years of
  everything? Leaning (a) unless the v2 question types need old narrative text.
- Type: grilling
- Blocked by: R1 Benchmark landscape
- Status: open

### v2 question types and mix

- Question: Which categories (e.g. extraction, numerical reasoning, multi-year, cross-company,
  multi-hop, refusal), how many questions per category, and what difficulty target?
- Input: skew away from tech, about 5 tech questions (Company list decision).
- Type: grilling
- Blocked by: R1 Benchmark landscape, Company list (both done)
- Status: open

### How questions get written

- Question: By hand, or Claude-drafted with each gold value and citation checked against XBRL
  and the filing text, plus a user spot-check?
- Type: grilling
- Blocked by: v2 question types and mix
- Status: open

### Grading new question types

- Question: How are cross-company, multi-year, multi-hop and refusal answers graded, and does the
  current numeric grader stretch to them?
- Type: grilling
- Blocked by: v2 question types and mix
- Status: open

### XBRL tag check on the shortlist

- Question: For each shortlisted company, which concepts do our fact tools fail to find
  (`devtools/discover_tags`; SEC only, no Gemini quota)? The shortlist is the 7 new tickers
  (JPM, BAC, TGT, WMT, XOM, JNJ, CAT).
- Also check: companyfacts names BAC's CIK "BofA Finance LLC".
- Type: task
- Blocked by: Company list (done)
- Status: open

### Fact-tool adaptation policy

- Question: When a new company breaks the fact tools (missing tag, start-year fiscal naming, CIK
  change), do we fix the tools before the v2 baseline (tag fallbacks, fiscal-year naming per
  company), or ship as-is and let v2 measure the breakage as headroom?
- Type: grilling
- Blocked by: Company list (done)
- Status: open

## Not yet specified

- Period scoping matches on report date alone, so a date-scoped search with no ticker admits
  every company filing on the same quarter-end. More December-year-end companies multiply this;
  measure with `retrieval_replay` after ingest.
- Whether cross-company questions need agent or tool changes (e.g. a search across several
  tickers).
- How v1 and v2 share the quota day, and which suite gates which kind of change.

## Out of scope

- Monorepo, admin web UI, chat web UI: later roadmap items, each with its own `/wayfinder`.
- Agent improvements such as improvement-map package 6: they resume once v2 shows headroom.
- Reusing benchmark questions or companies verbatim: contamination and stale filings (decided
  above).
