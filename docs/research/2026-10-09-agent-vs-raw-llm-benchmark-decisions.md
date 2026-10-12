# Agent vs. raw LLM benchmark: design decisions (grill-me)

Research: `docs/research/2026-10-09-agent-vs-raw-llm-benchmark.md`.

How to use: write your choice on each `Answer:` line. "rec" accepts the recommendation; add any
notes underneath. Later rounds get appended below as earlier answers settle them.

Context from the research:
- FinanceBench's no-tools GPT-4-Turbo mostly *refused*: 9% correct, 3% wrong, 88% refused.
  Accuracy alone hides the difference between "safe but useless" and "unsafe".
- Vals never runs a model without tools. It compares models inside one fixed harness and avoids
  memorization by using post-2024 documents. "Agent vs. raw model" is FinanceBench's style of
  comparison, not Vals'.

## Round 1: root decisions

### Q1: Who is the result for?
- (a) A public write-up or portfolio piece ("our agent improves on raw Gemini by X")
- (b) An internal tool that tracks whether each change helps
- (c) Both

Recommended: **(a) first, designed so it can be re-run.** The project's design principles already
treat "here's what broke and how I found it" as the deliverable. The v1/v2 eval is already the
internal regression gate.

Answer: recommended

### Q2: Which headline comparison matters most?
- (a) Agent vs. the *same* model with no tools ("what our pipeline adds")
- (b) Agent vs. the same model with Google Search grounding ("better than what anyone gets off the shelf")
- (c) Agent with a cheap model vs. a *stronger* model without tools ("cheap model + our pipeline
  beats a better model")

Recommended: **(a) as the headline, always shown alongside (b).** (a) answers "are we making
results better" directly. On questions after the training cutoff, (a) is inflated by recency
alone, and (b) is the honest check on that. (c) is a nice extra, not the headline.

Answer: recommended

### Q3: Which questions?
- (a) v1's 48
- (b) v2's ~56 once written
- (c) Both, reported separately

Recommended: **(b) v2, reported by category.** v2's traps, refusal questions and
`forbidden_values` make the wrong-vs-refused split meaningful. v1 is already at 47/48, so on v1
the agent has no room to show improvement.

Answer: recommended is good but we would also like to see how v1 produces the results

### Q4: Budget, while the paid-tier decision is parked
- (a) Free tier only: a small ladder, spread over days
- (b) A few dollars allowed for this benchmark specifically (about $0.30–1.25 per full run per
  rung, plus repeated runs)
- (c) Decide later, but design for (a)

Recommended: **(c).** Every rung should fit the free quota, with no-tools runs (one call per
question) first. Paying is a later speed-up.

Answer: recommended

### Q5: Should other model families be compared, as Vals does across providers?
- (a) Gemini only (3.5 Flash-Lite, 3.8 Flash)
- (b) Also an OpenAI or Anthropic model, through new backends

Recommended: **(a) for now.** Each new family needs a new backend with tool-calling translation,
which is the multi-provider work we just decided against. This benchmark asks about our
pipeline, not about ranking providers.

Answer: recommended

## Coming in later rounds (depend on the answers above)
- Which rungs of the comparison ladder to run (no tools, search-grounded, whole filing in the
  prompt, exact passage given, agent minus one tool, stronger model)
- How refusals are scored (penalty score with p fixed in advance? correct-given-attempted?)
- How to split questions before and after the training cutoff when Google doesn't publish the
  cutoff (an empirical probe)
- Which judge grades the LLM-judged questions (another model family, or a jury, given
  self-preference bias)
- Number of repeated runs and the statistics reported (Wilson CI, McNemar, pass^k)
- Report format and where it's published

## Round 1: settled (2026-10-10)
- Q1: a public write-up first, designed so it can be re-run. The v1/v2 eval stays the
  internal gate.
- Q2: the headline is agent vs. the same model with no tools, always shown next to agent vs. the
  same model with Google Search grounding.
- Q3: v2 by category is primary. v1 is reported too, separately.
- Q4: design for the free tier; paying is a later speed-up.
- Q5: Gemini models only.

Fact found (not a decision): both question sets have gold passages. `eval/retrieval_gold.jsonl`
holds 247 verbatim anchors (accession + anchor text) for v1, and the phase 2 map requires one
for every v2 gold value. So an "exact passage given" baseline and retrieval recall@k need no
new authoring.

## Round 2

Labels used below:
- AG: our full agent
- B0: same model, no tools
- B1: a stronger Gemini (3.8 Flash), no tools
- B2: same model + Google Search grounding
- B3: whole filing in the prompt
- B4: the exact gold passage given
- A-x: the agent without tool x

### Q6: Which rungs, in what order?
- (a) Phase 1: AG, B0, B2, B1. Phase 2: B4, B3. Phase 3: tool ablations (A-x).
- (b) Only AG, B0 and B2 (the agreed headline pair), nothing else
- (c) Everything at once

Recommended: **(a).** B0 and B1 cost one call per question, B2 one or two calls, and together
they answer the headline. B4 is cheap thanks to the gold anchors, and the gap between B4 and AG
measures retrieval loss directly. B3 puts a whole 10-K (100K+ tokens) into each call, which may
hit the free tier's tokens-per-minute limit, so it goes after B4. The ablations are each a full
agent run; with about 56 questions they can only be descriptive (a 5–0 split of discordant
questions gives p = 0.0625), so they go last.

Answer: recommended order is good

### Q7: How are refusals scored?
v2 has questions where refusing is the *correct* answer, so the outcomes are: correct,
wrong (confident wrong figure), refused when an answer existed, and refused correctly.
- (a) Report the counts in each outcome and correct-given-attempted. No single combined score.
- (b) (a), plus one penalty score: +1 correct, 0 refused, −p wrong, with p fixed before any run
- (c) Plain accuracy only

Recommended: **(b) with p = 1**, and the same instruction in every condition's prompt:
"answer only if confident; a wrong figure costs as much as a right one earns". FinanceBench
shows plain accuracy hides "safe but useless" (88% refused) versus "unsafe". One penalty score
gives a reader a headline, and the outcome counts keep it honest. Fixing p in advance stops us
tuning the metric to flatter the agent.

Answer: recommended

### Q8: How do we split questions before and after the training cutoff?
Google doesn't publish 3.5 Flash-Lite's training cutoff, and the research says real cutoffs often
differ from published ones.
- (a) Conservative: count a question as "post" if its filing date is after the model's public
  release date, and leave the rest unsplit
- (b) Empirical probe: ask the no-tools model dated facts by month and find where its knowledge
  stops
- (c) Report no split; just add a caveat

Recommended: **(a), with (b) as a small sanity check.** (a) is defensible with no assumptions.
The probe costs about 20–30 no-tools calls and tells us whether "pre" really means "known". I'll
look up the release dates; you don't need to.

Answer: recommended

### Q9: Who grades the LLM-judged questions?
Every judge is Gemini (Q5). Research: LLM judges favour their own model's outputs.
- (a) Keep the current 3.5 Flash-Lite judge and disclose it
- (b) Judge with 3.8 Flash, a different model from every condition except B1, and disclose that
  it is the same family
- (c) (b), plus the headline uses only deterministically graded categories; judged categories
  are reported separately

Recommended: **(c).** The headline then never depends on a judge, and the judged results still
appear with the caveat attached.

Answer: recommended

### Q10: How many repeat runs?
Temperature 0 still varies between runs; a full v2 AG run is about 190 calls.
- (a) 3 runs of every condition, reporting the spread and pass^3 (correct in all 3 runs)
- (b) 3 runs of the cheap conditions (B0, B1, B4); AG 3 runs spread over 3 days; 1 run of
  everything else
- (c) 1 run each

Recommended: **(b).** It fits the free quota, and the headline numbers get a variance estimate.

Answer: for (a) what would be the estimated time to get all reports?

**Estimate (main session, 2026-10-10).** Assumptions:
- v1 + v2 = 104 questions.
- AG makes about 3.4 calls per question (measured), so about 354 calls per full run.
- Every other rung except the ablations makes about 1 call per question (104 calls).
- 3 tool ablations.
- 3.5 Flash-Lite's free quota is 500 requests a day, and our day-to-day dev work uses part of it.
- B1 and the 3.8 Flash judge draw on 3.8 Flash's own quota, which we haven't read yet.

| Plan | 3.5 Flash-Lite calls | Days at the full 500/day | Realistic, sharing quota with dev work |
|---|---|---|---|
| (a) 3× everything, with ablations | ~5,500 | ~11 | ~3 weeks |
| (a) 3× everything, without ablations | ~2,300 | ~5 | ~1–1.5 weeks |
| (b) as recommended, with ablations | ~2,950 | ~6 | ~1.5–2 weeks |
| (b) without ablations | ~1,900 | ~4 | ~1 week |

On the paid tier, all of (a) costs roughly $20 in total and finishes in about a day. About half
of that is B3, because each call there carries a whole filing.

B3 may also be limited by the free tier's tokens-per-minute cap (each call is 100K+ tokens), so
its runs could take hours even when requests remain. Unverified: the cap is only visible in AI
Studio.

### Q11: Where does the report live, and how is it produced?
- (a) A script builds a Markdown report from saved eval reports, committed under `docs/`, with a
  summary linked from the README
- (b) (a), plus a published HTML page with charts
- (c) A hand-written write-up

Recommended: **(a), with (b) later.** "Designed so it can be re-run" (Q1) means the report is
generated, not hand-edited. A visual page can come once the numbers are stable.

Answer: recommended

## Round 2: settled (2026-10-10). Confirmed shared understanding

1. A public, re-runnable write-up answering "does our agent make Gemini's financial answers
   better, and by how much?". The v1/v2 eval stays the internal gate.
2. The headline is AG vs. B0 (the same model with no tools), always shown next to AG vs. B2
   (Google Search grounding). Gemini models only.
3. v2 is reported by category, and v1 separately.
4. Phases: (AG, B0, B2, B1), then (B4, B3), then the tool ablations. Everything is designed to
   fit the free tier.
5. Scoring: outcome counts (correct / wrong / refused when an answer existed / refused
   correctly), correct-given-attempted, and one penalty score (+1 / 0 / −1) with p = 1 fixed in
   advance. Every condition's prompt carries the same "answer only if confident" instruction.
6. Post-cutoff means filed after the model's public release date, checked with a small dated-fact
   probe. 3.8 Flash judges the LLM-judged questions. The headline uses only the
   deterministically graded categories.
7. Repeats, option (b): B0, B1 and B4 run 3 times; AG runs 3 times over 3 days; everything else
   runs once. That is about 2,950 Flash-Lite calls including the ablations, roughly 1.5–2 weeks
   on the free tier.
8. Reporting: a script builds a Markdown report under `docs/` from saved eval reports, with a
   summary in the README. A visual page comes later.

Confirmed assumptions:
- All conditions use the same answer format and graders.
- The work starts after the v2 questions and the served-model/token-logging backlog item land.
- It becomes a roadmap phase before the monorepo and web UI work.

Next: `/wayfinder`, with this section as its "Decisions so far".

## Round 3: wayfinder charting (2026-10-12)

Context found in the eval harness that Rounds 1–2 didn't cover:
- A numeric question passes for the agent only if its value is also *citation-verified* against
  what it retrieved (`grade_numeric` with `all_results`). B0 and B1 retrieve nothing, so that
  check can't run on them.
- v2's company-attribution and trap checks read the agent's submitted claims and their sources.
  A raw model has neither.
- The harness records only pass or fail. The four-way outcome split from Q7 needs a refusal
  signal for every condition.

### Q12: Destination of the map
Done means a frozen design: every condition's prompt and answer format, how each outcome is
graded and classified, the statistics, the preregistration and the report generator are all
decided. The build work packages are then ordered in BACKLOG behind v2. Running the benchmark
and publishing it come after the map, as build packages.

Recommended: **as stated.** It matches the phase 2 map, which froze once decided and handed off
to build packages.

Answer: rec

### Q13: Grading parity
- (a) The headline grades every condition on the value alone, with the same tolerance. A second
  column, "correct and verifiably cited", is where only AG and B4 can score.
- (b) AG stays strict and the baselines are graded on the value alone. This makes AG's lead a
  conservative lower bound.
- (c) The baselines must cite something too.

Recommended: **(a).** One grader for every condition is what "same graders" meant. The cited
column turns "citations are non-negotiable" into a measured result rather than a handicap.

Answer: rec. yes we would like to present how well cited the numbers in answer are as well. 

### Q14: How the baselines answer
- (a) The baselines answer through Gemini structured output in the same claim shape (company,
  value, unit, period, plus an explicit `refused` flag), and attribution reads the company each
  claim names.
- (b) The baselines answer in prose, the attribution checks are skipped for them, and the report
  discloses that.
- (c) An LLM extracts claims from the prose.

Recommended: **(a).** It follows the "structured metadata over prose parsing" rule, and the
`refused` flag also settles Q15 for the baselines.

Answer: Is this for non agent supported benchmarks?

**Clarification (2026-10-12).** Yes: this covers only the conditions that run *without* our
agent loop, which are B0, B1, B2, B3 and B4. AG and the A-x ablations keep their existing submit
tool unchanged.

Why the non-agent conditions need a format at all:
- Our graders read structured claims, not just prose. The v2 checks "is each comparison value
  attributed to the right company?" and "did the answer state a trap value?" look at the
  claims the agent submits.
- A raw model has no submit tool. Without some structure, those checks can't run on it.
- Option (a) asks those conditions for the same claim shape through Gemini's JSON response
  schema: company, value, unit, period, plus `refused: true/false`. The same graders then run
  on every condition.

Answer (again): Is there any benifit of using a and c both? also if answers are not structured properly then a would fail to extract right? I guess its same for our agent as well. Give me your suggestion.

**Suggestion (2026-10-12).** Use (a) and drop (c), but keep a prose answer alongside the claims.
- **Malformed output is mostly not possible.** Gemini's response schema constrains decoding, so
  the reply is valid JSON in the requested shape. The agent works the same way: its submit tool
  is a schema-checked function call, and when it doesn't call submit at all, the citation gate
  refuses the answer.
- **The real risk is the prose and the claims disagreeing**, not failing to parse.
- **So each non-agent condition returns `answer` (prose) plus `claims` plus `refused`.** The value
  grade runs on the prose with the existing `grade_numeric`/`grade_comparison`, exactly as for AG.
  The claims feed only the attribution and trap checks, also as for AG. Every condition is then
  graded by identical code paths.
- **(c) isn't worth adding.** An extractor model sits between the answer and the grade, which is
  a judge in the headline in disguise (ruled out in Q9). Its only use would be rescuing
  malformed output, which the schema already prevents.
- **Exception: B2.** If Search plus a response schema doesn't work on Flash-Lite (open; needs a
  live test call), B2 gets a JSON instruction without constrained decoding and could actually
  fail to parse. Q15 handles that case.

Answer (third): rec

### Q15: Classifying outcomes (correct / wrong / wrongly refused / correctly refused)
Recommended: **deterministic signals only.**
- For AG, the signal is a hard-gate refusal or a submitted refusal.
- For the baselines, it's the `refused` flag from Q14.
- B2, if it can't use a response schema alongside grounding, gets the same flag through a JSON
  instruction.

No judge decides what counts as a refusal.

Answer: explain

**Clarification (2026-10-12).** Round 2's scoring (Q7) puts every answer into one of four
buckets:

| Bucket | Example |
|---|---|
| correct | states the right figure |
| wrong | states a figure, and it's wrong or a trap value |
| wrongly refused | declines, but the question had an answer |
| correctly refused | declines, and v2 marks this as a refusal question where declining is right |

The harness only records pass or fail today, so something has to decide when an answer counts
as "declined". The recommendation is that a fixed rule decides it, never an LLM:
- **AG and ablations.** Declined means the citation gate withheld the answer, or the agent
  submitted no numeric claim (for example "the filing doesn't disclose this").
- **Non-agent conditions** (Q14). Declined means `refused: true`, or no claim.
- The same rule then works everywhere: **no figure stated = declined.** Figure stated → graded
  correct or wrong by the existing value grader.

The alternative is asking the 3.8 Flash judge "did this answer decline?" for each answer. It
costs quota and adds a judge into the headline, which Q9 ruled out.

Answer (again): Should we have categories for citation and couldn't parse the answer? They might not be the bucket that slots here but i'm not sure.

**Suggestion (2026-10-12).** Treat these as two different things.
- **Citation quality is a second axis, not a fifth bucket.** For every answer that states a
  figure, record one of: cited and verified, cited but not verified, or uncited. That's the Q13
  column, broken down. B0 and B1 come out 100% uncited by construction, which is itself a
  finding. For AG, also count "withheld by the citation gate" inside its declined bucket, so
  the report shows how often the gate turned a would-be answer into a refusal.
- **"Couldn't parse" is a fifth bucket**, shown in the counts, never hidden.
  - It scores like a decline: 0 in the penalty score, and not correct for accuracy.
  - It should be near zero given the schema (Q14). A pilot run before the preregistration
    checks that. If it's above a threshold fixed in the preregistration (e.g. >2% of a
    condition), that condition's prompt is fixed before the real runs, never after.
- **API errors (429, `RESOURCE_EXHAUSTED`) are not outcomes at all**: the question re-runs, as
  the quota rule already requires.

Answer (third): makes sense. go with rec.

### Q16: Which agent gets benchmarked
Work on v2 headroom will keep changing the agent.

Recommended: **freeze one tagged commit.** Every condition and every repeat runs from it, and a
later re-run benchmarks a new tag in full. Runs never mix commits.

Answer: rec

### Q17: Pinning the model
The `gemini-3.5-flash-lite` alias could start serving a different model partway through a 1.5–2
week run.

Recommended: **pin explicit model versions** wherever Google offers them. The served-model
logging (a prerequisite backlog item) checks every call, and a model change invalidates the
affected condition's runs, which then re-run.

Answer: rec

### Q18: Preregistration
Recommended: **before the first run, commit a short preregistration doc** fixing the conditions,
p = 1, the tolerance, the primary comparison and the statistical tests. The report cites its
commit SHA. The research flagged choosing comparisons after the fact as the main credibility
risk without a held-out split.

Answer: rec

### Q19: The headline number (AG vs. B0, deterministically graded v2 questions)
- (a) The difference in penalty score
- (b) The difference in accuracy, with exact McNemar on the discordant questions
- (c) Both: (b) as the tested claim, (a) shown next to it

Recommended: **(c).** McNemar gives a real p-value on paired binary outcomes. The penalty score
is what separates "safe" from "useful" for a reader.

Answer: rec

### Not asked yet (facts to look up, or dependent on the answers above)
- 3.8 Flash free-tier quota, the tokens-per-minute caps and the model release dates (a
  background research ticket).
- Whether Search grounding works on the free tier, and how reproducible its logs are.
- The list of tools to ablate.
- How B3 handles questions spanning several companies.
- How 3 repeats get paired for McNemar.
- How the near-ceiling v1 results are presented.

### Q20: B2 needs billing (revisits Round 1 Q4, given Q2)
New fact: Grounding with Google Search is **"Not available"** on the free tier for both 3.5
Flash-Lite and 3.8 Flash. The pricing page says so, and a second fetch on 2026-10-12 confirmed
it. Paid projects get 5,000 free search requests a month (shared across Gemini 3+), then $14 per
1,000. So "everything fits the free tier" (Q4) and "AG vs. B0 is always shown next to B2" (Q2)
can't both hold. Research: `docs/research/2026-10-12-gemini-benchmark-quotas.md`.

- (a) Use a paid project for B2 only. Every other condition stays on the free tier. About 104
  questions × 1 run uses ~100–200 searches, well inside the 5,000 free, so the cost is only
  Flash-Lite tokens, likely under $1. This is a narrow exception to the parked paid-tier
  decision, not a resolution of it.
- (b) Drop B2. The headline loses its honest check on the recency confound, and only the
  pre/post-cutoff split remains to address it.
- (c) Run B2 by hand in AI Studio. That isn't scriptable or re-runnable (Q1), and the grounding
  metadata wouldn't be logged.

Recommended: **(a).** B2 is the comparison that keeps the headline honest on post-cutoff
questions, and the cost is well under the "few dollars" option Q4 already weighed.

Answer: rec

### Q21: 3.8 Flash's free tier is 20 requests a day (revisits Q9 and Q10)
New fact, from the AI Studio rate-limit data the user captured on 2026-10-12: free 3.8 Flash is
**5 RPM and 20 RPD**. 3.5 Flash-Lite is 15 RPM, 250K TPM and 500 RPD. Details are in the
research note's addendum.
- B1 at 3 runs × 104 questions is 312 calls, about 16 days of free 3.8 Flash quota for B1 alone.
- The 3.8 Flash judge (Q9) shares the same 20 a day.

Good news in the same data: B3 fits the free tier (250K TPM is about 2 whole-filing calls a
minute, so roughly an hour per run).

- (a) Put B1 and the 3.8 Flash judge on the paid project Q20 already creates (Tier 1 allows
  10,000 RPD). Q9 and Q10 then stand unchanged. The cost is small: B1 is about one short call per
  question, and judge calls are short.
- (b) Stay free. Judge with **Gemma 4 31B** (free, 14,400 RPD, open weights, pinned version
  `001`, and a different model line from Gemini, though still from Google). Run B1 once
  instead of 3 times, at 104 calls over about 6 days.
- (c) (a), plus Gemma 4 31B as a second free judge, forming a 2-judge jury. Disagreements are
  flagged in the report. This addresses the self-preference risk the research raised.

Recommended: **(a).** The paid project exists anyway for B2, so this keeps the Round 2 design
intact for likely a dollar or two. (c) is a cheap upgrade if you want the jury; it only affects
the judged categories, which aren't in the headline.

Answer: rec

### Q22: Optional extras the AI Studio model list makes possible
Nothing here is recommended for this map. Mark any you want considered; the rest go to "Out of
scope" with this reason.
- **Google Deep Research** (`deep-research-pro-preview`, paid only): "our narrow agent vs.
  Google's general research agent" would be a striking public comparison. It's expensive per
  query and limited to 1 RPM, and it isn't a Gemini-model-in-our-harness condition.
- **Gemma 4 31B with our agent loop**: does our pipeline lift an open-weight model as much? It
  needs function calling through the Gemini API (unverified) and stretches Q5's "Gemini only".
- **Batch API** on Flash-Lite (paid): about half price for any paid re-runs. This is a build
  detail, not a design decision.

Answer: We can consider Google Deep Research based on the results we get from the benchmark. Gemma 4 can be a similar next models to try for future benchmarks. Batch API should be considered for when we are trying to benchmark flash-lite runs.

## Round 3: settled (2026-10-12). Confirm line by line

1. **Map destination**: a frozen design (conditions, answer format, grading, outcome classes,
   statistics, preregistration, report generator), with build work packages ordered in BACKLOG
   behind v2. Running and publishing are build packages.
2. **Grading**: every condition is graded on the value alone, by the same code (headline). A
   citation axis is recorded per stated figure (verified / unverified / uncited) and reported
   next to the headline. AG's citation-gate withholds are counted inside its declined bucket.
3. **Answer format**: AG and the ablations keep the submit tool. The non-agent conditions
   (B0–B4) return `answer` (prose) + `claims` + `refused` through a response schema. Value
   grading reads the prose and attribution reads the claims, exactly as for AG. No extractor
   model.
4. **Outcomes**: correct / wrong / wrongly declined / correctly declined / couldn't parse.
   - "No figure stated" means declined.
   - Couldn't parse scores like a decline. A pilot run checks it stays under a preregistered
     threshold.
   - API errors re-run and are never outcomes.
5. **Reproducibility**:
   - One tagged agent commit for every run.
   - Pinned model IDs: `gemini-3.5-flash-lite`, not the `gemini-flash-lite-latest` default.
   - Served-model checks; a model change invalidates that condition's runs.
   - A preregistration doc committed before the first run, its SHA cited in the report.
6. **Headline**: AG vs. B0 on the deterministically graded v2 questions. The accuracy difference
   is tested with exact McNemar, and the penalty-score difference is shown next to it.
7. **Quota**:
   - Free tier: AG, B0, B3, B4 and the ablations.
   - A paid project: B2 (Search grounding isn't on the free tier), B1 and the 3.8 Flash judge
     (free 3.8 Flash is 20 RPD).
   - Round 2's repeats and judge stand unchanged.
8. **Later, not this map**:
   - A Google Deep Research comparison, considered once results are in.
   - Gemma 4 for a future benchmark.
   - The Batch API for any paid single-call Flash-Lite runs. The agent loop is multi-turn, so
     batch fits B0/B3/B4-style conditions only.

Assumptions I'd otherwise ask about (my predicted answers; correct any that are wrong):
- **A. B2 logging**: every call logs its grounding metadata (`webSearchQueries`,
  `groundingChunks`, `groundingSupports`), and the report states the run dates. B2 is
  published as a dated snapshot, not as reproducible.
- **B. Repeats in the statistics**: the McNemar test pairs per-question *majority* outcomes
  (correct in ≥2 of 3 runs). pass^3 and the run-to-run spread are reported next to it.
- **C. B3 with several companies**: concatenate the relevant filings when they fit under 250K
  tokens (the free TPM); otherwise mark the question "n/a for B3" and report the n.
- **D. v1**: the same report table as a separate panel, with a note that AG is near ceiling
  (47/48), so v1 mainly shows baseline levels.
- **E. Ablation list**: decided once v2 lands and the agent tag is chosen. Candidates:
  −`search_filings`, −`get_financial_fact`, −`calculate`, −`compare_financial_metric`, −rerank.

Confirmation: LGTM
