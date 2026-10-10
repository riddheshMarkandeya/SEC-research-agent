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
