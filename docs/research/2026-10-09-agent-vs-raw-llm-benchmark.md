# Agent vs. raw LLM: how to benchmark "how much does the agent add" (research, 2026-10-09)

Feeds the design discussion, and later a `/wayfinder` map, for a public, reportable benchmark in
the style of Vals Finance Agent: "Does our agent make financial answers better than the raw LLM,
and by how much?"
Companion note: [2026-10-07-financial-rag-benchmarks.md](2026-10-07-financial-rag-benchmarks.md)
covers taxonomy and datasets. This note covers **conditions, metrics and validity**.

Method note: every page was fetched on 2026-10-09 through a fetch-and-summarise tool, so quoted
figures are as the tool returned them and were not re-checked against PDFs. Where only an arXiv
abstract page was read, the note says so. Statistical figures marked "computed" were calculated
locally (Wilson and exact-binomial McNemar) and are not from a source.

## Key findings (sources say)

### 1. Vals Finance Agent benchmark (v1/v1.1 paper, v2 page)

- **v1 paper.** Bigeard, Krishnan, Wu, Nashold, "Finance Agent Benchmark", arXiv 2508.00828
  (dated 20 May 2025). [arXiv HTML](https://arxiv.org/html/2508.00828)
  - **Questions.** 537 questions in 9 categories: Quantitative Retrieval 102, Qualitative
    Retrieval 97, Numerical Reasoning 83, Beat or Miss 69, Financial Modeling 47, Adjustments 43,
    Trends 33, Market Analysis 34, Complex Retrieval 29.
  - **Authors.** Experts from banks, hedge funds and PE wrote them (seven domain experts, with 2–3
    years at bulge-bracket firms). A different expert peer-reviewed each question, then the
    authors did a final review.
  - **Recency.** The questions use documents published no earlier than 2024, which the authors
    say is "after most training cutoffs".
  - **Harness.** ReAct-style, with four tools:
    - Google web search via SerpAPI (up to 10 results);
    - EDGAR search via the SEC API (returns filing metadata, not full text);
    - `parse_html_page`, which saves the page to a key-value store;
    - `retrieve_information`, which sends stored text to the same LLM.
  - **Run settings.** 429 errors retry with exponential backoff (up to 8 attempts). Temperature
    0, no system prompt, 16,384-token limit.
  - **Grading.** A rubric-based LLM judge. GPT-4o extracted the rubrics, which were then reviewed
    by hand. Each expert answer is split into checks, plus a contradiction check, and simple
    numeric answers are compared directly.
  - **Metrics.** Class-balanced accuracy is the headline, and naive accuracy is also reported.
    They also report cost and latency per query: o3 scored 46.8% at $3.79 and 186.5 s. The expert
    baseline took 16.8 min and $25.66 per question.
  - **Contamination control.** The 337-question test set is private. Validation and test scores
    correlate at 0.98.
  - **No closed-book or no-tools condition, and no tool ablation.** Source (citation) accuracy is
    listed as future work. One finding: LLaMA 4 Maverick "hallucinated documents it never
    retrieved".
- **v1.1 page.** [vals.ai/benchmarks/finance_agent](https://www.vals.ai/benchmarks/finance_agent),
  updated 6/4/2026.
  - It reports accuracy, cost per test, duration per test, and tool calls with error counts.
  - "performance can be improved by allowing the model more tool calls and more tokens used".
  - It reports no no-tools comparison.
- **v2 page.** [vals.ai/benchmarks/fabv2](https://www.vals.ai/benchmarks/fabv2), updated
  10/7/2026.
  - **Questions.** 927 expert-reviewed questions in public, private-validation and held-out test
    splits. Nine categories: Earnings Analysis, General Qualitative, General Quantitative, Market
    Analysis, Disclosure Analysis, Adjustments, Comparables, Precedents, Financial Modeling.
  - **Two scoring modes.** Partial Credit and All-Pass. Under All-Pass no model reaches 51%; the
    top model under Partial Credit is at 65.4%.
  - **Per-model figures.** Cost per test and duration, e.g. $4.38 and 16m21s for the top model.
  - **The fetched text stopped before the Methodology section**, and the page contradicts itself
    on some category maxima.
  - **Harness and grading, unverified (search-engine summary of the vals.ai page only):**
    - fixed tools: `edgar_search`, `web_search`, `parse_html_page`, `retrieve_information`,
      `calculator`, `price_history`;
    - a **three-LLM judge jury**;
    - per-question checks, some flagged as **dealbreakers** (missing one gives zero credit);
    - Partial Credit is a severity-weighted average of the checks.

    [search result for vals.ai/benchmarks/fabv2](https://vals.ai/benchmarks/fabv2). A mirror
    says it reports the "Mean score across repeated runs".
    [benchlm.ai mirror](https://benchlm.ai/md/benchmarks/financeagentv2.md)
- **Takeaway (sources say):** Vals compares **models within one fixed harness**. It never
  compares a model with tools against the same model without them.

### 2. FinanceBench (Islam et al. 2023, arXiv 2311.11944)

Source: [arXiv HTML](https://arxiv.org/html/2311.11944).

- **Data.** 10,231 questions with answers and evidence strings. 16 configurations were evaluated
  on a 150-case sample, and 2,400 answers were reviewed by hand. The sample is 50 domain-relevant,
  50 novel-generated and 50 metrics-generated questions.
- **Grading.** One research-team member labelled each answer, with spot-checks. There are three
  labels:
  - **Correct.** Minor unit or rounding deviations are allowed.
  - **Incorrect.** Includes a right answer whose logic contradicts the gold evidence.
  - **Failed to answer.** The model explicitly says it lacks the information.

**Results per configuration (n = 150 each; Table 2):**

| Config | Correct | Incorrect | Failed to answer |
|---|---|---|---|
| GPT-4-Turbo closed book | 9% | 3% | 88% |
| GPT-4-Turbo shared vector store | 19% | 13% | 68% |
| Llama2 shared vector store | 19% | 70% | 11% |
| Llama2 single vector store | 41% | 54% | 5% |
| GPT-4-Turbo single vector store | 50% | 11% | 39% |
| Claude2 long context | 76% | 21% | 3% |
| GPT-4-Turbo long context | 79% | 17% | 4% |
| GPT-4-Turbo oracle (gold evidence pages) | 85% | 15% | 0% |

- **Order matters.** Putting the context first versus last changes the score sharply: GPT-4-Turbo
  long context 78% vs. 25%, Claude2 76% vs. 37%.
- **Hallucinations.** These are answers that are "superficially coherent" but wrong, and harder
  to catch than refusals. No hallucination count is given. Llama2 produced plausible-but-wrong
  answers more often than GPT-4-Turbo.
- **Long context has limits.** It helps, but the authors call it impractical for enterprises
  because of latency and documents that exceed the window.
- **The repo releases the 150-question sample.** Fields include evidence with page numbers,
  `question_type` and `doc_period`, plus the human-annotated completions per configuration.
  [github.com/patronus-ai/financebench](https://github.com/patronus-ai/financebench)
- **Takeaway (sources say):** this is the canonical **condition ladder**: closed-book → retrieval
  variants → long-context → oracle, reported as a **three-way outcome**. Note that the closed-book
  model mostly *refused* (88%) rather than hallucinated (3%).

### 3. Other benchmarks: what each ablates

The companion note has the full detail.

- **FinQA** (Chen et al. 2021). [arXiv HTML](https://arxiv.org/html/2109.00122)
  - **Ablates retrieval: retrieved vs. gold facts.** FinQANet (RoBERTa-large) gets 61.24 execution
    accuracy with retrieved facts vs. 70.00 with gold facts.
  - **Reports retriever recall separately:** 89.66% at top 3, 93.63% at top 5.
  - **Metrics:** execution accuracy plus program accuracy ("execution accuracy tends to
    overestimate"). Human experts score 91.16 and the crowd 50.68.
  - **Breaks results down by reasoning steps:** more than 2 steps drops to 22.78.
- **TAT-QA** (Zhu et al. 2021). [arXiv abs](https://arxiv.org/abs/2105.07624)
  - Hybrid table and text QA. TAGOP scores 58.0% F1 vs. 90.8% for human experts.
  - No retrieval or tool ablation (the abstract page only).
- **DocFinQA** (2024). [arXiv HTML](https://arxiv.org/html/2401.06915)
  - FinQA with the full document as context, averaging 123k words.
  - **Ablates retriever choice and oracle chunk vs. retrieval-free long context:**
    - GPT-3.5 with oracle chunk: ~67%;
    - GPT-3.5 with the best retriever: 42.6%;
    - on 100K+ token documents, GPT-4 with retrieval 47.5% vs. retrieval-free 23.0 / 20.0.
  - Reports retriever hit rate (HR@1 0.35, HR@3 0.55 for fine-tuned ColBERT).
  - No closed-book setting.
- **SEC-QA** (Lai et al., Kensho 2024). [arXiv abs](https://arxiv.org/abs/2406.14394)
  - Semi-automatically generated multi-document questions that can be **refreshed with documents
    newer than the models' training data**, explicitly to fight contamination.
  - Compares RAG methods with a program-of-thought system; RAG "systematically fail[s]"
    (abstract only).
- **FinanceQA** (2025). [arXiv abs](https://arxiv.org/abs/2501.18062)
  - Analyst-style tasks; models fail "approximately 60%", especially on tasks that need
    generated assumptions.
  - The abstract shows no tool/no-tool ablation.
- **BizBench** (2023). [arXiv abs](https://arxiv.org/abs/2311.06602)
  - Program synthesis for financial QA. It separates extraction from formula application, so it
    isolates *reasoning* skill from *reading* skill. No direct-answer ablation is shown on the
    abstract page.

### 4. Metrics with defining sources

- **Error bars and paired comparison.** Miller, "Adding Error Bars to Evals", arXiv 2411.00640.
  [HTML](https://arxiv.org/html/2411.00640v1)
  - Use CLT standard errors.
  - **Cluster** standard errors when questions come in related groups (up to ~3x larger).
  - **Compare models on per-question paired differences.**
    SE_paired = sqrt(SE_A² + SE_B² − 2·SE_A·SE_B·Corr).
  - Resample answers to reduce variance, and don't lower temperature to get there.
  - Do a power analysis.
  - The CLT assumes "a large number of questions", and the paper offers no small-n correction.
- **Wilson score interval** (Wilson 1927) and **exact McNemar** for paired binary outcomes
  (McNemar 1947; Dietterich 1998 recommends it for comparing two classifiers on one test set).
  These are standard references and **were not opened in this session**.
- **Three-way outcomes and abstention trade-off.** SimpleQA, Wei et al., arXiv 2411.04368.
  [HTML](https://arxiv.org/html/2411.04368)
  - Grades are correct / incorrect / not attempted.
  - "Correct given attempted" = correct ÷ (correct + incorrect). The F-score is the harmonic mean
    of overall correct and correct-given-attempted.
  - **F-score rewards guessing at >50% confidence**, so the paper proposes a penalty score:
    +1 correct, 0 abstain, −p wrong (p = 9 means 90% precision is needed to break even).
  - Calibration is measured by stated confidence, and by answer frequency over 100 samples.
- **Why to penalise wrong answers.** Kalai et al., "Why Language Models Hallucinate", arXiv
  2509.04664. [HTML](https://arxiv.org/html/2509.04664)
  - Binary grading makes "I don't know" a losing strategy, so models learn to guess.
  - It proposes stating confidence targets in the prompt: "Answer only if you are >t confident,
    since mistakes are penalized t/(1-t) points".
- **Selective prediction (risk–coverage).** Geifman & El-Yaniv 2017, arXiv 1705.08500.
  [abs](https://arxiv.org/abs/1705.08500) A selective classifier trades coverage for lower risk,
  e.g. guaranteed 2% top-5 ImageNet error at ~60% coverage.
- **Citation recall and precision.** ALCE, Gao et al., arXiv 2305.14627.
  [HTML](https://arxiv.org/html/2305.14627)
  - Per statement, citation recall = 1 iff at least one citation exists and the concatenated
    citations *entail* the statement.
  - Citation precision is per citation: a citation is "irrelevant" if it alone doesn't entail the
    statement and the rest still do without it.
  - Entailment is judged by the TRUE NLI model (T5-11B).
  - On ELI5 the best models "lack complete citation support 50% of the time" (abstract).
- **Retrieval recall.** FinQA (top-k recall) and DocFinQA (HR@k), above.
  - RAGAS (arXiv 2309.15217) is a *reference-free* suite: retrieval quality, faithfulness and
    generation quality. [abs](https://arxiv.org/abs/2309.15217) Only the abstract was read, so
    the metric formulas were not confirmed.
- **Run-to-run reliability.** τ-bench, arXiv 2406.12045. [abs](https://arxiv.org/abs/2406.12045)
  - It introduces **pass^k**, reliability over k trials.
  - gpt-4o has pass^8 < 25% in retail.
- **Cost, latency, tool calls.** Vals reports cost per test, duration per test and tool calls
  with errors (§1). Vals' v1 paper also reports a human-expert cost and time baseline.

### 5. Validity threats

- **Knowledge cutoff.**
  - Vals restricts questions to documents from 2024 on, "after most training cutoffs" (§1).
  - SEC-QA refreshes its documents to stay post-cutoff (§3).
  - **Effective cutoffs often differ from reported ones, and differ by topic.** Cheng et al.,
    "Dated Data", arXiv 2403.12958 [abs](https://arxiv.org/abs/2403.12958). So a reported cutoff
    date is not a clean split point.
  - **Google's model pages for Gemini 3.5 Flash-Lite don't state a knowledge cutoff.**
    [models](https://ai.google.dev/gemini-api/docs/models),
    [3.5 Flash-Lite](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite)
  - None of the benchmarks read here publishes a pre- vs. post-cutoff split. FreshQA comes
    closest: it shows that closed-book LLMs of every size struggle with fast-changing knowledge,
    and that search augmentation (FreshPrompt) helps.
    [arXiv abs 2310.03214](https://arxiv.org/abs/2310.03214)
- **Contamination.**
  - Vals keeps a private held-out test split, with validation–test correlation 0.98 (§1).
  - SEC-QA's motivation is that evaluation documents may already be in training corpora (§3).
- **LLM-judge bias.**
  - Self-preference: LLM evaluators score their own generations higher, and this correlates
    linearly with self-recognition. Panickssery et al., arXiv 2404.13076
    [abs](https://arxiv.org/abs/2404.13076)
  - MT-Bench names position, verbosity and self-enhancement biases. GPT-4 judges reach >80%
    agreement with humans, about human–human level. Zheng et al., arXiv 2306.05685
    [abs](https://arxiv.org/abs/2306.05685)
  - Vals v2 reportedly uses a three-judge jury (unverified, §1).
- **Refusal-capable baselines.**
  - FinanceBench's closed-book GPT-4-Turbo refused 88% and was wrong only 3% (§2). A plain
    accuracy figure hides that this baseline is *safe but useless*, while Llama2 with a shared
    store is *unsafe* (70% wrong).
  - SimpleQA and Kalai et al. argue for scoring that separates abstention from error and
    penalises errors (§4).

### 6. Web-search baseline availability

Grounding with Google Search: [docs](https://ai.google.dev/gemini-api/docs/google-search)

- It is supported on Gemini 3.5 Flash-Lite and 3.8 Flash, among others.
- Gemini 3 and newer models can combine it with custom function calling.
- Responses carry `url_citation` annotations (span → URL).
- Billing is per search query: 5,000 per month free, then $14 per 1,000.
- Gemini 3.5 Flash-Lite has a 1,048,576-token input window, so stuffing a whole 10-K into the
  prompt is feasible.

## Inference (mine, not from the sources)

### Baseline ladder: what each condition isolates

| # | Condition | Isolates | Notes |
|---|---|---|---|
| B0 | **Closed-book, same model** (3.5 Flash-Lite, no tools, same answer schema) | Headline "raw LLM" figure: what the model knows from training | Must be split pre/post cutoff, or it measures recency, not the agent. Expect mostly refusals on post-cutoff periods, as FinanceBench saw. |
| B1 | **Closed-book, stronger model** (e.g. 3.8 Flash or 3.1 Pro) | Whether the agent beats just buying a bigger model | Useful for the "cheap model + agent vs. expensive model" cost story. |
| B2 | **Same model + Google Search grounding** | Whether a *domain* pipeline beats generic web RAG | The fairest "off-the-shelf" competitor. Web pages may carry post-cutoff figures, so it removes the recency confound. |
| B3 | **Long-context: stuff the relevant filing(s)** | Whether retrieval and tools beat brute-force context | Isolates retrieval quality. Feasible given 1M tokens. Single-filing questions only; multi-company comparisons need several filings. Context-first ordering, per FinanceBench. |
| B4 | **Oracle passage** (gold evidence chunk + same model) | Upper bound on reasoning and answer formatting when retrieval is perfect | Agent ÷ oracle gap = retrieval loss; oracle − agent shows the headroom. Needs gold evidence per question. |
| A1..An | **Agent minus one tool** (−`get_financial_fact`, −`calculate`, −`compare_financial_metric`, −rerank/BM25) | Marginal value of each component | Small deltas; see the sample-size caveats. |
| AG | **Full agent** | — | — |

B0 and AG answer "how much does the agent add". B2 and B3 answer "is the agent better than the
obvious cheaper alternatives". B4 and A* explain *where* the gain comes from.

### Metrics (one row per condition)

- **Three-way outcome.** Correct / wrong / refused %, with a Wilson 95% CI on each.
  - Refusal and clarify questions in v2 invert this: for them, refusing counts as correct.
  - Keep them in a separate column so they don't inflate B0, which refuses everything.
- **Headline accuracy.** Over answerable questions, with a Wilson CI.
- **Precision.** Correct-given-attempted.
- **Penalty score.** +1 / 0 / −p, with p fixed in advance (e.g. p = 4, i.e. t = 0.8).
- **Risk–coverage.** Wrong-answer rate vs. coverage.
- **Forbidden-value hit rate.** The v2 traps.
- **Citation metrics.**
  - Citation precision and recall in ALCE style. Our claims are structured, so entailment can be a
    deterministic check that the value is present in the cited chunk or XBRL fact, rather than
    NLI.
  - Report "uncited numeric claim rate" too.
  - Applies to AG, A*, and B2 via `url_citation`. B0 has none, which is itself a finding.
- **Retrieval recall@k.** Only for conditions that retrieve, against gold evidence.
- **Cost and latency.** Tokens in/out, $ per question, median and p90 latency, tool calls per
  question, tool errors.
- **Stability.** Run ≥3 times per condition: mean ± SD of accuracy, and pass^3 (all three runs
  correct).

### Paired comparisons

- For AG vs. each baseline, on the same questions:
  - the discordant counts b and c (agent-only-correct, baseline-only-correct);
  - an exact McNemar p;
  - a paired bootstrap CI on the accuracy difference.
- Cluster by ticker or question template if several questions share one, per Miller.

### Report table shape

| Condition | n | Correct % [95% CI] | Wrong % | Refused % | Precision | Penalty score | Cit. precision / recall | Retrieval R@k | $/q | p50 latency | Δ vs AG (b/c, McNemar p) |
|---|---|---|---|---|---|---|---|---|---|---|---|

Split the table into at least two panels:

1. **pre-cutoff vs. post-cutoff fiscal periods**;
2. **by category** (numeric, comparison, multi-step, trap, refusal/clarify). Show category cells
   only with n and the CI, or mark them "n too small".

### Sample-size caveats (computed, n ≈ 50–100)

- **Wilson 95% intervals are wide.**

  | Result | 95% interval |
  |---|---|
  | 28/56 (50%) | 37–63% |
  | 50/56 (89%) | 79–95% |
  | 47/48 (v1's current score) | 89–99.6% |
  | 50/100 | 40–60% |

  So two systems ~10 pp apart overlap at n = 56.
- **Exact McNemar depends only on discordant pairs.**

  | Discordant split (b–c) | Exact p |
  |---|---|
  | 5–0 | 0.0625 |
  | 6–1 | 0.125 |
  | 10–3 | 0.092 |

- **What that means for each comparison.**
  - **AG vs. B0** on post-cutoff questions will be overwhelmingly significant: tens of discordant
    pairs.
  - **AG vs. B2/B3** may be borderline.
  - **Single-tool ablations will mostly not reach significance** at this n. Report them as
    descriptive, with their b/c counts, not as findings.
- **Repeated runs reduce run-to-run noise but don't add questions.** The CI on "this question
  set" shrinks; generalisation to new questions does not.
- **Preregister.** Fix the conditions, p, the tolerance and the primary comparison (AG vs. B0
  post-cutoff, AG vs. B2) before running, so the result doesn't depend on which comparison is
  chosen afterwards.

### Fairness rules for the baseline

- Give every condition the **same answer schema and refusal instruction**, including the
  explicit "refuse if not confident" target (Kalai et al.). Otherwise B0's refusals reflect the
  prompt, not knowledge.
- Grade numeric questions deterministically, by value within tolerance. For LLM-judged items,
  use a judge from a different family, or a 3-judge jury, to avoid self-preference with Gemini.
  Report judge–human agreement on a sample.
- Don't let B0 score on answers it got right only by *guessing* stale figures: the penalty score
  handles this.

## Open questions

1. **What is 3.5 Flash-Lite's effective cutoff?** The docs don't say. Should we probe it
   empirically, e.g. ask closed-book for known quarterly figures by period, and set the
   pre/post split from where accuracy collapses ("Dated Data")?
2. **Is B2 (Search grounding) reproducible enough to publish?** Web results drift. Do we log the
   `url_citation`s and freeze a run date?
3. **Do B3 and B4 need gold evidence annotations** (chunk or page per question) that v2 doesn't
   yet have? How much authoring cost does that add?
4. **Which judge for the LLM-judged items:** a non-Gemini judge (quota and cost) or a
   multi-judge jury?
5. **Is the free-tier Gemini quota enough** for 7 conditions × ~56 questions × 3 runs (≈1,200
   agent runs, multi-call each)? See
   [2026-10-09-free-tier-llm-failover.md](2026-10-09-free-tier-llm-failover.md).
6. **Is "public" credible without a private held-out split?** Vals keeps one. With ~56
   questions, a split leaves very small halves.
7. **Are refusal and clarify questions scored in the headline**, or reported separately? (This
   recommends separately.)
8. **Vals v2's exact harness and judge setup** were only seen via a search summary. Re-fetch the
   Methodology section if we cite it publicly.

## Verification against primary sources (added 2026-10-09, main session)

- FinanceBench Table 2 (arXiv html 2311.11944 v1, n=150 per configuration) matches the figures
  above. The paper itself has inconsistencies:
  - The closed-book row's counts (14 / 5 / 126) add up to 145, not 150, and 126/150 is 84%,
    not 88%. Cite the counts together with the caveat.
  - The body text gives 67% / 38% failed-to-answer for shared / single vector store, where
    Table 2 has 68% / 39%.
  - Long-context context-first is 78% in Section 5 and 79% in Table 2.
- Vals Finance Agent v1 (arXiv html 2508.00828) has no closed-book or no-tools configuration
  in its verbatim text. It handles memorization with post-2024 documents instead. It has four
  harness tools (GoogleSearch, EdgarSearch, ParseHTML, RetrieveInformation); no calculator was
  confirmed. Its 537 questions split 50 / 150 / 337 (public validation / private validation /
  private test).
- The Wilson intervals (28/56 → 0.373–0.627; 47/48 → 0.891–0.996) and the exact McNemar 5–0
  result (two-sided p = 0.0625) were recomputed and agree.
