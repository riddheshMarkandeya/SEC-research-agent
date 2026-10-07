# Financial RAG benchmark landscape

Date: 2026-10-07
Ticket: R1 Benchmark landscape
Feeds: design of the ~50-question v2 eval suite and the choice of 5-7 new companies. We copy taxonomy and sector mix only.

Method note: figures below were read through fetch-and-summarise tools. FinQA and TAT-QA numbers were checked against text extracted from the ACL Anthology PDFs. FinanceBench, DocFinQA, SEC-QA, FinDER and Fin-RATE numbers come from arXiv HTML pages and were not re-checked against the PDFs.

## Findings

### Comparison table

| | FinanceBench | FinQA | TAT-QA | DocFinQA | SEC-QA | FinDER | Fin-RATE |
|---|---|---|---|---|---|---|---|
| Year | 2023 | 2021 | 2021 | 2024 | 2024 (FinNLP 2025) | 2025 | 2026 |
| Corpus | 40 US public companies, 360 docs, 2015-2023 | S&P 500 earnings reports 1999-2019 (via FinTabNet); 2,789 report pages | Real financial reports; 2,757 hybrid table+text contexts; companies and years not stated in what I read | 801 unique SEC filings (FinQA questions re-attached to full filings) | 18 S&P 500 companies, 2010-2023, 10 metrics | 490 S&P 500 companies, latest 10-K | 43 companies / 36 industries in corpus; questions touch 34 companies in 7 sectors; 2020-2025 |
| Filing types | 10-K 75% (270), 10-Q 27, 8-K 29, earnings 29, annual 5 | Earnings-report pages | Report pages | SEC filings (full) | 10-K, 10-Q, 8-K | 10-K | 10-K 72.9% of question sources, proxy 8.7%, 10-Q 7.8%, others |
| Questions | 10,231 total; 150 public | 8,281 (6,251 / 883 / 1,147) | 16,552 | 7,437 (5,735 / 780 / 922) | Generated on demand | 5,703 triplets | 7,500 (3 x 2,500) |
| Grading | Human experts: correct / incorrect / failed to answer | Execution accuracy and program accuracy | EM and F1 | Generated Python program; answer accepted if correct or close | Value within 1% of gold | RAGAS LLM judge (correctness, faithfulness, context recall) | 3 LLM judges: CORRECT / PARTIAL / INCORRECT / FAILURE, plus 5 Likert dimensions |
| Headline baseline | GPT-4-Turbo: 79% long context, 50% single vector store, 19% shared vector store | Model 65.05% vs experts 91.16%, crowd 50.68% | TAGOP 58.0 F1 vs human 90.8 | 42.6% (GPT-3.5, finetuned ColBERT retrieval) | Vanilla RAG about 30% vs best code-gen pipeline about 80% on multi-document questions | Correctness 31.89% (GPT-o1) with retrieved context vs 68.13% with perfect context | Closed models 38-44% accuracy |
| Licence | Paper: CC BY-NC-ND 4.0. HF card: CC-BY-NC-4.0 | MIT (GitHub) | CC BY 4.0 | CC BY-NC-SA 4.0 | Paper: CC BY-NC-SA 4.0 | CC BY 4.0 (paper); data release restricted when I read it | MIT (HF) |

### FinanceBench (Patronus AI, 2023) - the closest match to our agent

- Corpus. 40 companies. 9 of 11 GICS sectors. Information Technology is 25% of questions; Materials is 1.8%. 360 documents, 2015-2023. No per-sector company list in the paper. [arXiv HTML](https://arxiv.org/html/2311.11944)
- Question types. Three, by origin. [arXiv HTML](https://arxiv.org/html/2311.11944)

  | Type | Count | Share | Example shapes (paraphrased) |
  |---|---|---|---|
  | Metrics-generated | 7,983 | 78% | "FY cost of goods sold in USD millions"; "D&A as a percent of revenue"; ratio from two statement lines. Built from 18 base metrics. |
  | Novel-generated | 1,323 | 13% | Company-specific things an analyst would want to know, written per filing. |
  | Domain-relevant | 925 | 9% | Standard questions asked of every company: dividend history, margin consistency across periods. The GitHub README labels them dg01-dg25. [GitHub](https://github.com/patronus-ai/financebench) |

- Reasoning labels on 8,908 questions: numerical reasoning 66%, information extraction 28%, logical reasoning 6%. The HF card says there are 9 `question_reasoning` categories. [HF card](https://huggingface.co/datasets/PatronusAI/financebench)
- Grading. Human experts labelled each answer correct, incorrect or failed-to-answer. The sample was 150 cases (50 per question type), run on 16 configurations, with 2,400 answers reviewed. Refusals count as failures but are tracked separately. [arXiv](https://arxiv.org/abs/2311.11944)
- Baselines. GPT-4-Turbo: 79% with long context, 50% with a single vector store, 19% with a shared vector store. The shared store refused 68% of questions. Llama2 mostly gave wrong answers (70%) rather than refusing. Abstract: GPT-4-Turbo with retrieval answered wrongly or refused on 81%. [arXiv HTML](https://arxiv.org/html/2311.11944)
- Hardest. The shared-vector-store setup (the multi-company retrieval problem) was hardest. The paper did not give per-sector or per-category accuracy in what I read.
- Contamination. No contamination discussion found. Filings run to 2023. [arXiv HTML](https://arxiv.org/html/2311.11944)
- Licence. Paper says CC BY-NC-ND 4.0; HF card says CC-BY-NC-4.0. The GitHub README names no licence. 150 open cases only; the rest is by request. [HF card](https://huggingface.co/datasets/PatronusAI/financebench)

### FinQA (2021)

- Corpus. S&P 500 earnings reports 1999-2019, taken from FinTabNet. Pages were filtered to at most one table, at most 20 rows. 8,281 questions on 2,789 report pages. Split 75/10/15 with no report overlap. [ACL PDF](https://aclanthology.org/2021.emnlp-main.300.pdf)
- Taxonomy is by program length, not topic. 59.10% of programs have 1 step, 32.71% have 2, 8.19% have 3 or more (max 5). Operation frequency: divide 45.29%, subtract 28.20%, add 14.98%, multiply 5.82%. [ACL PDF](https://aclanthology.org/2021.emnlp-main.300.pdf)
- Example shapes. Percent change between two years; ratio of two table cells; a multi-step chain that mixes table cells with a number in the text.
- Grading. Execution accuracy (numeric answer match) and program accuracy. The paper says execution accuracy overestimates correctness.
- Scores. Experts 91.16, non-expert crowd 50.68, system 65.05 (execution accuracy). The GitHub README reports 61.24 for the baseline. [GitHub](https://github.com/czyssrs/FinQA)
- Hardness. Accuracy drops as steps increase (paper section "Performances regarding program steps").
- Licence MIT. No contamination discussion. Annotators were 11 UpWork experts.

### TAT-QA (2021)

- 16,552 questions on 2,757 hybrid contexts (a table plus at least 2 surrounding paragraphs). [ACL PDF](https://aclanthology.org/2021.acl-long.254.pdf) The filing type and company count were not stated in the text I extracted.
- Taxonomy is by answer type and source (counts from the paper's Table 2): Span 7,139 (43.1%), Spans 2,072 (12.5%), Counting 377 (2.3%), Arithmetic 6,964 (42.1%). Sources: table 45.0%, text 23.6%, table+text 31.5%.
- Example shapes. A single value lookup ("revenue from X in year Y"); a set of items; which year had the lowest value; percent change or ratio from a table cell plus a text figure.
- Grading. EM and F1, with a scale (million/billion) component. TAGOP gets 58.0 F1; humans 90.8 F1.
- Hardest. Arithmetic: 42.5 EM overall. Error analysis: wrong evidence 55%, wrong calculation 9%, scale error 3%. [ACL PDF](https://aclanthology.org/2021.acl-long.254.pdf)
- Licence CC BY 4.0. [GitHub](https://github.com/NExTplusplus/TAT-QA)

### DocFinQA (2024)

- FinQA's questions re-attached to full SEC filings: 7,437 questions, 801 filings, average context 123k words (FinQA's was under 700). About 10% of FinQA questions were dropped for missing filings or parse failures. [arXiv HTML](https://arxiv.org/html/2401.06915)
- Grading. A generated Python program is accepted if its result is correct or approximately close; the authors admit false positives and negatives.
- Scores. Retrieval plus GPT-3.5: 42.6%. GPT-4 retrieval-free: 23% with System 2 Attention, versus 47.5% with retrieval. Fine-tuned ColBERT: HR@1 0.35, HR@3 0.55. Models struggle most on the longest documents.
- Licence CC BY-NC-SA 4.0. No dedicated contamination study (FinQA is 1999-2019 filings, so likely seen in training).

### SEC-QA (Kensho, 2024; FinNLP 2025)

- A generator framework rather than a fixed set. 18 S&P 500 companies, 2010-2023, 10-K/10-Q/8-K, 10 metrics. Designed to be refreshed on new filings so the model has not seen them. Five yearly variants differed by under 2 points (sigma < 2%). [arXiv HTML](https://arxiv.org/html/2406.14394)
- Taxonomy (complexity dimensions): parallel reference (same metric across entities or periods, e.g. 5-year revenue growth); multi-hop reference (resolve an entity from a constraint, then fetch its data); structural reference (use how the filing collection is organised); multi-output (several calculated values in one answer).
- Grading. Numeric answer accepted within a 1% margin to cover thousands/millions rounding.
- Scores. Vanilla RAG about 30% on multi-document questions; best code-generation pipeline about 80%. Single-value extraction 89.5%; compound or high-order metrics 33.3%. Document selection (metadata filtering) was the key factor.
- Licence CC BY-NC-SA 4.0 (paper). Contamination is handled by design (refresh).

### FinDER (2025)

- 5,703 query-evidence-answer triplets from real professional search queries, linked to 10-K evidence from 490 S&P 500 companies. [arXiv HTML](https://arxiv.org/html/2504.15800v2)
- Categories: Company Overview 18.95%, Financials 17.36%, Footnotes 16.71%, Governance 12.59%, Accounting / Legal / Risk / Shareholder Return about 8.6% each. Reasoning: qualitative 84.52%, quantitative 15.48%. Quantitative ops: compositional 49.83%, division 14.50%, multiplication 13.70%, subtraction 13.48%, addition 8.49%. Hops: 3-4 hops 43.45%, 5 or more 46.41%.
- Example shapes. An abbreviated query such as "recent CAGR in MS trading revenue"; a governance lookup; a footnote or accounting-policy lookup.
- Grading by RAGAS LLM judge. Best retriever (E5-mistral) reaches 25.95% context recall. Correctness 31.89% (GPT-o1) with retrieved context, 68.13% with perfect context.
- Hardest. Short, ambiguous, jargon-heavy queries hurt retrieval. Licence CC BY 4.0; when I read the page, release was limited to collaborators. No contamination analysis.

### Fin-RATE (2026)

- 7,500 questions in three tasks of 2,500: DR-QA (detail and reasoning in one document, about 1 chunk), EC-QA (compare firms, about 5.6 chunks), LT-QA (track one firm across years, about 3.0 chunks). Corpus: 15,311 chunks from 2,472 filings, 2020-2025, 43 companies in 36 industries (questions touch 34 companies in 7 sectors; Energy 8 and Basic Materials 7 companies). [arXiv HTML](https://arxiv.org/html/2602.07294v3), [HF card](https://huggingface.co/datasets/GGLabYale/Fin-RATE)
- Grading. Three LLM judges (GPT-5, DeepSeek-V3.2, Qwen3-235B) give CORRECT / PARTIAL / INCORRECT / FAILURE, plus five Likert dimensions and a 13-type error taxonomy.
- Scores. Closed models 38-44% accuracy, open models 3-27%. The finance-tuned model reached 1.27% on EC-QA. Hardest were entity misidentification and temporal misalignment in comparison and longitudinal tasks. Accuracy fell sharply when moving from gold context to retrieval.
- Licence MIT. No contamination analysis found. It covers 2020-2025 filings, so the nominal contamination risk is lower than FinanceBench's.

### Others seen but not read in depth

- FinanceRAG (ICAIF 2024 challenge) bundles FinanceBench, FinQA, FinQABench, FinDER, TAT-QA and ConvFinQA. It is a packaging of existing sets, not a new taxonomy. [arXiv 2411.16732](https://arxiv.org/pdf/2411.16732)
- FinRAGBench-V, FinMRAGBench and FinRetrieval appeared in search. They are multimodal or retrieval-only, so I did not read them. [FinRAGBench-V](https://arxiv.org/html/2505.17471)
- FinTextQA and Fin-Fact were not found in primary-source search results, so they are not covered.

## Inferences for our v2 design

These are my reasoning, not source claims.

Suggested category mix for about 50 questions (two axes, so each question gets one cell):

| Category (source of idea) | Share | Count | Shape |
|---|---|---|---|
| Single-value extraction, one filing (FinanceBench metrics-generated; SEC-QA single value; TAT-QA span) | 20% | 10 | A line item for a named fiscal year and period |
| Derived ratio or percent from 2-3 line items (FinQA 1-2 step programs; FinanceBench numerical reasoning) | 22% | 11 | Margin, growth rate, D&A as percent of revenue |
| Multi-step or compound metric (FinQA 3+ steps; SEC-QA compound, the hardest at 33%) | 10% | 5 | Free cash flow conversion, leverage, effective tax rate with a bridge |
| Cross-period within one company (Fin-RATE LT-QA; SEC-QA parallel reference) | 14% | 7 | Multi-year trend; 10-Q vs prior 10-K |
| Cross-company, including the look-alike pair (Fin-RATE EC-QA; SEC-QA multi-hop; FinanceBench shared-store setup) | 14% | 7 | Compare two firms; pick the higher of N |
| Text/footnote/policy lookup, qualitative but checkable (FinanceBench domain-relevant; FinDER footnotes/governance) | 10% | 5 | Debt maturities, segment definitions, auditor or risk factor |
| Refusal and trap cases (no equivalent benchmark; FinanceBench counts refusals as a failure class) | 10% | 5 | Metric not disclosed, wrong period, company not in corpus |

- All 50 stay numeric or exactly checkable. FinDER's 84.5% qualitative mix needs an LLM judge, which we would rather avoid given the citation-exactness goal.
- Grading: use SEC-QA's idea of a numeric tolerance (it uses 1%, so we would pick 1% for rounded-to-millions answers and exact for percentages we compute) plus a scale check (TAT-QA's scale error was 3% of its errors, but cheap to catch). Track refusals as their own outcome (FinanceBench; Fin-RATE FAILURE).
- Tag every question with a step count (FinQA) and an answer-source tag (table/text/both) so results can be sliced after only 50 questions.

Sector mix, for 10-12 total companies. FinanceBench is IT-heavy (25%) and misses 2 GICS sectors; Fin-RATE is Energy/Materials-heavy. Our current 5 are all technology, so the new 5-7 should avoid IT:
- Financials (a bank or insurer; very different statement shape) 1
- Health Care 1
- Energy or Materials 1
- Industrials 1
- Consumer Staples or Discretionary 1-2
- Utilities or Real Estate 0-1
- A same-sector look-alike pair (two firms with near-identical line items, e.g. two payment networks or two big-box retailers) counts within these slots or adds one.

A total of about 12 companies across 7-9 GICS sectors gives about 4-5 questions per company.

Caveat on the size of the effect: with 50 questions, a 10-point difference between two runs is within noise (a binomial 95% interval at p=0.7 is about +/-13 points), so per-category slices should be read as diagnostics, not scores.

## Open questions

- FinanceBench: per-sector company list and per-category accuracy were not in the text I read. Needs the PDF tables.
- FinanceBench licence conflict (paper CC BY-NC-ND vs HF card CC-BY-NC): irrelevant to us since we copy taxonomy only, but note it if we ever cite examples.
- TAT-QA: source companies, years and filing type not confirmed.
- FinDER: whether the data is now public. The page I read said collaborators only.
- Fin-RATE: 43 companies / 36 industries (corpus) vs 34 companies / 7 sectors (questions) not reconciled. Contamination analysis absent; the 2020-2025 range overlaps with model training for the early years.
- SEC-QA: the list of 10 metrics and 18 companies not enumerated.
- FinTextQA, Fin-Fact and FinQABench were not found or not read. Whether any has a taxonomy worth copying is unsettled.
- No benchmark reports a contamination measurement. We have no source-backed way to say how much the older ones are memorised.

## Sources

- FinanceBench paper: https://arxiv.org/abs/2311.11944 (HTML: https://arxiv.org/html/2311.11944)
- FinanceBench GitHub: https://github.com/patronus-ai/financebench
- FinanceBench HF card: https://huggingface.co/datasets/PatronusAI/financebench
- FinQA paper (EMNLP 2021): https://aclanthology.org/2021.emnlp-main.300.pdf ; arXiv https://arxiv.org/abs/2109.00122
- FinQA GitHub: https://github.com/czyssrs/FinQA
- TAT-QA paper (ACL 2021): https://aclanthology.org/2021.acl-long.254.pdf ; arXiv https://arxiv.org/abs/2105.07624
- TAT-QA GitHub: https://github.com/NExTplusplus/TAT-QA
- DocFinQA: https://arxiv.org/abs/2401.06915 (HTML: https://arxiv.org/html/2401.06915)
- SEC-QA: https://arxiv.org/abs/2406.14394 (HTML: https://arxiv.org/html/2406.14394); ACL Anthology https://aclanthology.org/2025.finnlp-2.15
- FinDER: https://arxiv.org/abs/2504.15800 (HTML: https://arxiv.org/html/2504.15800v2)
- Fin-RATE: https://arxiv.org/html/2602.07294v3 ; https://huggingface.co/datasets/GGLabYale/Fin-RATE ; https://github.com/jyd777/Fin-RATE
- FinanceRAG challenge: https://arxiv.org/pdf/2411.16732
- FinRAGBench-V: https://arxiv.org/html/2505.17471
