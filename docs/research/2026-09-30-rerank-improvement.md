# Rerank improvement — candidate variants for the gold-rank harness

Context: offline harness, 901 query/gold-part pairs. hit@5 = 36.5%; gold reaches the fused pool
89.6% of the time. 478/901 misses happen at rerank: 462 from cross-encoder ordering, 16 from the
max-of-RRF combination rule. Current reranker `cross-encoder/ms-marco-MiniLM-L-6-v2`, 512-token
max (query+doc). ~86% of gold chunks exceed 512 tokens; ~90% of gold chunks (hit and miss alike)
are financial tables. For 158/462 model misses the gold anchor row is past the 512-token cutoff
(vs. 14/329 for hits). Median CE rank of missed gold ≈ 19.5 of ~50.

## 1. Long-context open-weight rerankers

| Model | Params | Max seq len | Licence | sentence-transformers `CrossEncoder` load | CPU latency/throughput published | BEIR/long-doc scores found |
|---|---|---|---|---|---|---|
| `cross-encoder/ms-marco-MiniLM-L-6-v2` (current) | ~22M (6-layer MiniLM) | 512 | Apache 2.0 | yes, no extra args | 1800 docs/sec on V100 GPU (no CPU figure given) [sbert ce-msmarco](https://www.sbert.net/docs/pretrained-models/ce-msmarco.html) | MS MARCO dev MRR@10 39.01, TREC-DL19 nDCG@10 74.30 [sbert](https://www.sbert.net/docs/pretrained-models/ce-msmarco.html) |
| `cross-encoder/ms-marco-MiniLM-L-12-v2` | ~33M (12-layer) | 512 | Apache 2.0 | yes, no extra args | 960 docs/sec on V100 GPU [sbert](https://www.sbert.net/docs/pretrained-models/ce-msmarco.html) | MRR@10 39.02, nDCG@10 74.31 — essentially tied with L-6 [sbert](https://www.sbert.net/docs/pretrained-models/ce-msmarco.html) |
| `cross-encoder/ms-marco-TinyBERT-L6` / `-L2-v2` | smaller still | 512 | Apache 2.0 | yes | 680–9000 docs/sec on V100 depending on depth [sbert](https://www.sbert.net/docs/pretrained-models/ce-msmarco.html) | MRR@10 30–36, nDCG@10 67–70 — worse than L-6, not useful here |
| `BAAI/bge-reranker-base` | 0.3B (XLM-RoBERTa-base) | 512 | MIT | yes, directly | not found | T2Reranking MAP 67.28 (Chinese); no English BEIR figure found on card [HF bge-reranker-base](https://huggingface.co/BAAI/bge-reranker-base) |
| `BAAI/bge-reranker-large` | ~0.56B | 512 | MIT | yes | not found | not directly sourced this session |
| `BAAI/bge-reranker-v2-m3` | 0.6B (bge-m3/XLM-RoBERTa) | model supports up to 8192 (inherited from bge-m3), but maintainers say it was **fine-tuned at max_length=1024** and recommend not exceeding that [HF discussion #9](https://huggingface.co/BAAI/bge-reranker-v2-m3/discussions/9) | Apache 2.0 | **not directly** — model card's own usage sample uses `FlagEmbedding.FlagReranker`, not sentence-transformers `CrossEncoder` (sentence-transformers tag is present but FlagEmbedding is the documented path) [HF bge-reranker-v2-m3](https://huggingface.co/BAAI/bge-reranker-v2-m3) | not found; maintainers warn runtime grows with input length (noted roughly linear-ish with length doubling) [discussion #9](https://huggingface.co/BAAI/bge-reranker-v2-m3/discussions/9) | MIRACL/BEIR gains reported reranking top-100 from bge-m3/bge-en-v1.5/e5-mistral, exact numbers not extracted this session [HF card](https://huggingface.co/BAAI/bge-reranker-v2-m3) |
| `jinaai/jina-reranker-v2-base-multilingual` | 0.3B (278M) | model card says "up to 1024" with an internal **sliding-window chunker** (default overlap 80) for longer inputs — not a native 2k–8k context model | **CC-BY-NC-4.0** — non-commercial; commercial use requires Jina's paid API/marketplace [HF jina-reranker-v2](https://huggingface.co/jinaai/jina-reranker-v2-base-multilingual) | yes, but requires `trust_remote_code=True` | GPU-only figures ("3–6x speedup with flash attention"); no CPU numbers | BEIR nDCG@10 53.17, MKQA nDCG@10 54.83, MLDR (long-doc, multilingual) recall@10 68.95 [HF card](https://huggingface.co/BAAI/bge-reranker-v2-m3) — fails the "free/open-weight, commercial-compatible" constraint as licensed |
| `jinaai/jina-reranker-v3` | 0.6B, listwise (last-but-not-late interaction) | long-context, listwise design (full spec not confirmed this session) | **CC BY-NC-4.0** — non-commercial, same restriction as v2 [arXiv 2509.25085](https://arxiv.org/html/2509.25085v3), confirmed non-commercial across multiple HF pages | not confirmed this session | not found | not sourced this session — licence alone rules it out |
| `mixedbread-ai/mxbai-rerank-base-v2` | 0.5B | long-context (model family touts up to 8k, "32k-compatible" per large-v2) | Apache 2.0 | yes: `sentence_transformers.CrossEncoder("mixedbread-ai/mxbai-rerank-base-v2")` works directly; a dedicated `mxbai_rerank` package is also offered | 0.67s latency reported, but **on A100 GPU**, not CPU [superlinked mxbai-rerank-base-v2](https://superlinked.com/models/mixedbread-ai-mxbai-rerank-base-v2) | BEIR avg 55.57 (English) [superlinked](https://superlinked.com/models/mixedbread-ai-mxbai-rerank-base-v2) |
| `mixedbread-ai/mxbai-rerank-large-v2` | ~1.5B, RL-enhanced | up to 8k tokens (32k-compatible per vendor blog) | Apache 2.0 [mixedbread blog](https://www.mixedbread.com/blog/mxbai-rerank-v2) | yes via CrossEncoder | not found for CPU | vendor claims SOTA across 100+ languages; no primary BEIR table extracted this session |
| `Alibaba-NLP/gte-reranker-modernbert-base` | 149M | 8192 (ModernBERT + RoPE + Flash Attention architecture) | Apache 2.0 | yes, **no special flags** — loads with plain `sentence_transformers.CrossEncoder(...)` [HF Alibaba-NLP/gte-reranker-modernbert-base](https://huggingface.co/Alibaba-NLP/gte-reranker-modernbert-base) | no CPU number on the card; card notes GPU deployment recommended, CPU deployable via Text Embeddings Inference Docker image | BEIR avg 56.73 (15 datasets); **LoCo (long-document) avg 90.68**, best on SummScreenRetrieval (94.06) and QsmsumRetrieval (70.86) [HF card](https://huggingface.co/Alibaba-NLP/gte-reranker-modernbert-base) |
| `Alibaba-NLP/gte-multilingual-reranker-base` | not confirmed this session | not confirmed | not confirmed | not confirmed | not confirmed | not sourced — flagged as open question |

Inference: of the models checked, `gte-reranker-modernbert-base` is the strongest fit on paper —
149M params (similar order to the current 22–33M MiniLM, so CPU cost should scale sub-linearly
better than a 0.5–1.5B model), native 8192-token context (no window/trust_remote_code hack), a
permissive Apache-2.0 licence, drop-in `CrossEncoder` loading, and a published long-document
benchmark (LoCo) that is directly the failure mode measured here (long passages, financial-style
tables resemble LoCo's long structured documents more than BEIR's short passages). This is
inference, not a sourced claim — no one has published LoCo-style numbers on SEC tables
specifically.

`bge-reranker-v2-m3` is the next most plausible candidate in spec, but its "native" 8192 is
undermined by the maintainers' own warning that it was fine-tuned at 1024 and that longer inputs
cost more compute — and sentence-transformers compatibility is unconfirmed (FlagEmbedding is the
documented path), which is a real code-change cost against this project's `CrossEncoder`-based
pipeline.

`mxbai-rerank` models are Apache-2.0 and long-context but all published latency is GPU-only; no
CPU figure was found in any primary source this session, so CPU cost on this project's hardware
is unknown and would need to be measured, not assumed.

Jina v2/v3 fail the "free/open-weight" constraint as read here: CC-BY-NC-4.0 blocks anything but
research/eval use, and this is a research agent being asked to run searches for a user, which is
plausibly commercial-adjacent use depending on how strict the licence terms are read — flagged
rather than asserted, since "non-commercial" boundary-drawing for personal-project use wasn't
something I could resolve from the licence text alone.

## 2. Long-passage scoring techniques for a short-context cross-encoder

Source: Dai & Callan, "Deeper Text Understanding for IR with Contextual Neural Language
Modeling," SIGIR 2019 ([arXiv:1905.09217](https://arxiv.org/abs/1905.09217)).

- **Passage construction**: a 150-word sliding window over the document, stride 75 words (50%
  overlap); document title prepended to each passage when available.
- **FirstP**: document score = score of the first passage only.
- **MaxP**: document score = max score over all passages (this is the "take the max" idea the
  harness's own combination rule echoes, but applied within one model's scoring rather than
  across fusion methods).
- **SumP**: document score = sum of all passage scores.
- **Reported gains (nDCG@20, vs. a Coor-Ascent learning-to-rank baseline)**:
  - Robust04 title queries: baseline 0.427 → FirstP 0.444 → **MaxP 0.469** → SumP 0.467.
  - Robust04 description queries: baseline 0.441 → FirstP 0.491 → **MaxP 0.529** → SumP 0.524.
  - ClueWeb09-B title queries: baseline 0.295 → FirstP 0.286 (no gain) → MaxP 0.293 (no gain) →
    SumP 0.289.
  - ClueWeb09-B description queries: baseline 0.251 → FirstP 0.272 → MaxP 0.262 → SumP 0.261.
  - MaxP is consistently the best or tied-best of the three on Robust04; the gain is much smaller
    or absent on ClueWeb09-B, a noisier web collection. [arXiv:1905.09217 via ar5iv](https://ar5iv.labs.arxiv.org/html/1905.09217)

Source: Li, Yates, MacAvaney, He & Sun, "PARADE: Passage Representation Aggregation for
Document Reranking," arXiv 2020 ([arXiv:2008.09093](https://arxiv.org/abs/2008.09093)).

- PARADE aggregates passage **representations** (via a CNN or a shallow Transformer over
  per-passage CLS vectors) rather than aggregating passage **scores** (FirstP/MaxP/SumP). The
  claimed reason representation aggregation wins: it lets passages interact (a weak individual
  passage can still contribute signal in context of others), where score aggregation discards
  everything except the single max (or sum) number.
- Reported numbers (MAP / nDCG@20, description queries):
  - Robust04: ELECTRA-MaxP 0.3464 / 0.5540 → PARADE-Max(CNN) 0.3992 / 0.6022 → PARADE-Transformer
    0.4084 / 0.6127.
  - GOV2: ELECTRA-MaxP 0.2857 / 0.5319 → PARADE-Max 0.3160 / 0.5732 → PARADE-Transformer 0.3269 /
    0.6069. [arXiv:2008.09093 via ar5iv](https://ar5iv.labs.arxiv.org/html/2008.09093)
  - So PARADE-Transformer adds roughly +0.06 MAP / +0.06–0.07 nDCG@20 over plain MaxP with the
    same base encoder — a real but second-order gain over MaxP itself, and MaxP is already a
    large step over FirstP/no-aggregation (per Dai & Callan above).
- PARADE requires training an aggregation head end-to-end; it is not a drop-in inference-time
  trick like MaxP/windowing, so it is a bigger engineering lift than the project's harness-driven
  "try variants" scope implies — noted as inference, not found disputed or confirmed by the paper
  itself (the paper's own focus is the aggregation head, not CPU cost of using it as a plug-in).

**Table-specific windowing** (header-repeated row groups): I could not find a paper that
isolates this exact technique (splitting a financial table into row-group windows with column
headers repeated in each window, then MaxP-ing a short-context cross-encoder over the windows) as
a named, evaluated method. It is a direct application of the FirstP/MaxP sliding-window idea
(Dai & Callan) to table rows instead of prose sentences, and is consistent with what table
serialization research says about preserving row/column structure under linearization (see §3) —
but no source found quantifies it. **Open question, not settled by sources.**

## 3. Evidence on retrieving/reranking tabular financial text

- **ICAIF 2024 FinanceRAG challenge** results (from search, not directly fetched to primary
  leaderboard page): 1st place "Finance RAG with Hybrid Search and Reranking" (Jing Wang,
  Accrete); 2nd place "Multi-Reranker" (David Lee) ablated query expansion, corpus refinement, and
  **multiple reranker models** together; 3rd place used a mixture-of-experts retrieval approach.
  [AI4F challenge page](https://ai4f.org/2024-challenge), [arXiv:2411.16732 abstract](https://arxiv.org/abs/2411.16732).
  I could not extract the Multi-Reranker paper's actual reranker model names or serialization
  choice — the PDF fetch returned only binary/garbled text both times it was tried. **Open
  question.**
- **"From BM25 to Corrective RAG: Benchmarking Retrieval Strategies for Text-and-Table
  Documents"** ([arXiv:2604.01733](https://arxiv.org/html/2604.01733v1)) is the most directly
  relevant primary source found: financial documents with markdown-formatted tables from real SEC
  filings and annual reports, retrieved whole-document (no chunking, ~920 tokens average) and
  reranked with **Cohere Rerank v4.0 Pro** (a paid, closed-weight API — not usable under this
  project's free/open-weight constraint, but informative on reranking's effect size). Reported
  Recall@5 / MRR@3: BM25 0.644/0.411, dense (text-embedding-3-large) 0.587/0.351, Hybrid RRF
  0.695/0.433, **Hybrid + Cohere Rerank 0.816/0.605** — reranking added +12.1pp Recall@5 and
  +39.7% relative MRR@3 over unreranked hybrid fusion. This is evidence that reranking in
  general is worth a large share of the pipeline's accuracy on this exact document type
  (SEC-filing tables), even though the specific reranker tested isn't a candidate here.
- **FinRank** ([arXiv:2608.07400](https://arxiv.org/abs/2608.07400)) evaluates retrieval,
  reranking and hard-negative discrimination on financial QA as separate tasks and reports that
  reranking the top-20 improved nDCG@10 across all seven of its tasks, "confirming the
  effectiveness of Cross-Encoders over BERT-based retrievers" — but I could not extract the
  paper's actual reranker model list or numeric table; the PDF fetch failed to decode both times
  tried. **Open question** (which cross-encoders, what passage-length handling).
- **Table serialization**: a 2026 preprint, "Improving Robustness of Tabular Retrieval via
  Representational Stability" ([arXiv:2604.24040](https://arxiv.org/html/2604.24040)), states
  that semantically-equivalent serializations (CSV, TSV, HTML, markdown, DDL) "can produce
  substantially different embeddings and retrieval results," and that naive linearization "can
  obscure relational structure, introduce spurious dependencies, and ignore feature-specific
  inductive biases." It proposes averaging embeddings across several serializations as a fix
  rather than picking one winning format — i.e., the literature found here does not declare a
  single winning serialization (markdown vs. linearized-row vs. column:value); it instead treats
  serialization choice as a known source of instability. No FinQA/TAT-QA-specific serialization
  ablation was found and fetched successfully this session. **Open question**: which
  serialization wins specifically for financial 10-K/10-Q tables was not resolved by a source I
  could verify.

## 4. The max-of-reciprocal-ranks combination rule

- RRF itself (k=60, summing/combining `1/(k+rank)` across result lists) is the standard,
  well-documented technique — used as-is in OpenSearch, Elasticsearch, Azure AI Search, MongoDB
  Atlas, Weaviate [OpenSearch RRF blog](https://opensearch.org/blog/introducing-reciprocal-rank-fusion-hybrid-search/).
  That much is settled and matches this project's fusion step.
- For combining a **fused rank** with a **reranker rank/score** specifically (this project's
  actual question — using `max(1/(60+fused_rank), 1/(60+ce_rank))` as a rank-preserving floor),
  search surfaced two competing, both-cited patterns rather than one standard:
  1. **Full override**: "a common approach is to use a cross-encoder as a final reranker on top
     of RRF... fusing with RRF on ~50 candidates, then resorting the top 50 by the cross-encoder's
     score" — i.e., trust the reranker completely and discard the fused rank once the pool is
     fixed.
  2. **Weighted blend**: `s(d) = α·s_retr(d) + (1-α)·s_ce(d)` — blend retrieval and reranker
     scores rather than fully trusting either. (Both patterns found via secondary sources in this
     session — [bigdataboutique RRF explainer](https://bigdataboutique.com/blog/reciprocal-rank-fusion-how-it-works-and-when-to-use-it),
     [bge-model.com docs](https://bge-model.com/bge/bge_reranker_v2.html) — neither is a paper
     with an ablation isolating "floor" vs. "full override" vs. "blend"; this is the weakest-
     sourced part of the brief.)
  3. I found **no primary source** that specifically evaluates a `max()`-as-floor combination
     rule (keep whichever of fused-rank-score or CE-rank-score is higher) against either full
     override or linear blending. The 16/478 misses attributable to this rule in the measured
     facts are a small share next to the 462 CE-ordering misses, so this is a secondary lever
     regardless of what the literature says. **Open question**: no source directly supports or
     rejects the floor rule as currently implemented; the two patterns above are what exists
     nearby in the literature, not a verdict on this project's specific formula.

## Candidate variants

| Variant | What changes | Expected effect on measured miss classes | Est. latency per ~50-candidate search on CPU | Evidence |
|---|---|---|---|---|
| **Long-context reranker swap** (`Alibaba-NLP/gte-reranker-modernbert-base`) | Swap the CE model only; drop-in `CrossEncoder` load, Apache-2.0, no code restructuring beyond a config change and raising `max_length` | Directly targets the 158/462 misses where gold is past token 512 (ModernBERT native 8192) and plausibly helps ordering generally on long table passages given its LoCo long-doc score (90.68); does not touch the 16 combination-rule misses | Unknown exactly — 149M params is close to the current model's order of magnitude per-token, but input length rises ~5-8x (2800 chars ≈ 700+ tokens vs. 512 cap today), so per-candidate cost rises; no CPU figure published, needs a direct timing run before committing | [HF model card](https://huggingface.co/Alibaba-NLP/gte-reranker-modernbert-base) (arch, licence, LoCo score); CPU latency not found — measure, don't assume |
| **Windowed MaxP with table header carried, on current model** | Keep `ms-marco-MiniLM-L-6-v2`; split long chunks into ~400-token windows with the table's header/column row repeated in each window, score every window, take per-candidate max score | Directly targets long-table misses (the same 158/462 class) without a new model; MaxP's Robust04 gain (+0.04 nDCG@20 over FirstP) is the closest sourced analog, though no source evaluates this exact header-repeat-for-tables variant | Each long chunk becomes 2-4 windows scored independently with the same cheap model — roughly 2-4x today's reranker cost for the long chunks only (not all 50 candidates), likely well inside the 2-3x tolerance since reranking is one stage of the total latency, not the whole budget | Dai & Callan MaxP numbers ([arXiv:1905.09217](https://arxiv.org/abs/1905.09217)); table-header-carry specifics are inference extrapolated from general serialization-sensitivity findings ([arXiv:2604.24040](https://arxiv.org/html/2604.24040)), not a sourced ablation |
| **Larger short-context model with MaxP** (`cross-encoder/ms-marco-MiniLM-L-12-v2`, windowed) | Swap to L-12 (double the layers, same 512 cap) combined with the same windowing as above | L-12's own MS MARCO numbers are statistically tied with L-6 (nDCG@10 74.31 vs 74.30, MRR@10 39.02 vs 39.01) on short passages, so swapping the base model alone is expected to add little; value would come entirely from the windowing, not the bigger model | ~2x current model's cost per scoring call (960 vs 1800 docs/sec on the vendor's GPU benchmark — a relative, not absolute, CPU figure) times however many windows are added | [sbert ce-msmarco table](https://www.sbert.net/docs/pretrained-models/ce-msmarco.html) — numbers are near-identical, weakening the case for this swap specifically; windowing is the real lever, this row isolates "does the bigger base model matter" and the sourced answer is "not much" |
| **Drop the fused-rank floor; trust the reranker fully** | Change the combination rule to always use CE rank when the candidate was scored by the CE (drop the `max()` with the fused term) | Targets only the 16/478 combination-rule misses; cannot help the 462 CE-ordering misses, so this alone leaves ~97% of rerank misses unaddressed | No latency change — pure scoring-formula edit | No primary source directly validates or rejects this; "trust the reranker once it's run" is a described pattern in secondary hybrid-search write-ups ([bigdataboutique](https://bigdataboutique.com/blog/reciprocal-rank-fusion-how-it-works-and-when-to-use-it)), not an ablation; given it only touches 16 known misses, low expected payoff regardless of which rule wins in the literature |
| **Long-context reranker swap** (`BAAI/bge-reranker-v2-m3`) | Swap model; requires either confirming sentence-transformers `CrossEncoder` compatibility or adding a `FlagEmbedding`-based code path (bigger integration change than the ModernBERT swap) | Same target class as the ModernBERT swap (long-table misses), but the model's own maintainers warn it was tuned at 1024 tokens, not the full 8192 — so expected gain on >1024-token tables is uncertain | 0.6B params — meaningfully larger than the current 22M-param model; maintainers note runtime grows with input length; no CPU figure found | [HF discussion #9](https://huggingface.co/BAAI/bge-reranker-v2-m3/discussions/9) (tuning length caveat); CrossEncoder-vs-FlagEmbedding path unconfirmed, a real integration-risk factor |

Ranked by expected gain vs. cost: (1) windowed MaxP with header-carry on the current model — no
new model, no licence risk, directly targets the dominant 158-case long-table miss class, cost
scoped only to long candidates; (2) ModernBERT long-context swap — best spec match and a real
long-document benchmark score, but unmeasured CPU latency is a real risk to the 2-3x budget;
(3) dropping the fused-rank floor — trivial to try, but caps out at 16 of 478 misses so it's a
low-stakes, low-reward change to bundle in alongside either of the above rather than a priority on
its own. The bge-reranker-v2-m3 and L-12 swaps rank lowest: the first carries real integration
risk against a self-acknowledged tuning-length caveat, the second's own vendor numbers show it
barely beats the current model on short passages.

## Open questions

- No CPU latency/throughput figure was found in any primary source for `gte-reranker-modernbert-base`,
  any `mxbai-rerank` model, or `bge-reranker-v2-m3` — every GPU-only figure found (A100, V100) is
  not a valid stand-in for this project's CPU-only laptop constraint; a direct local timing run is
  needed before ranking these by latency with confidence.
- Whether `BAAI/bge-reranker-v2-m3` loads correctly through sentence-transformers' `CrossEncoder`
  (the project's current integration point) or requires a `FlagEmbedding`-based code path was not
  settled — the model card's own usage example uses `FlagEmbedding`, which is signal but not
  confirmation either way.
- No source was found that isolates "table windowed-by-row-group with header repeated" as a named,
  separately-evaluated technique; its expected gain here is extrapolated from the general
  short-passage MaxP literature (Dai & Callan) and general table-serialization-sensitivity
  findings, not measured directly for this technique.
- The FinanceRAG "Multi-Reranker" paper (arXiv:2411.16732) and the FinRank paper
  (arXiv:2608.07400) both likely contain the specific reranker-model comparisons and serialization
  choices this brief's Q1/Q3 are asking about, but both PDF fetches returned undecodable/binary
  content this session rather than extractable text — worth a retry via a different fetch path
  (e.g. the HTML/ar5iv mirror, as worked for the Dai & Callan and PARADE papers) before trusting
  this brief's current coverage of those two as final.
- No source was found that directly evaluates the `max(1/(60+fused_rank), 1/(60+ce_rank))`
  combination rule itself (as opposed to RRF fusion in general, or reranker-score blending in
  general) — whether a rank-floor, a full override, or an α-weighted blend is best for this
  specific pipeline shape is unresolved by the literature surfaced here.
- `Alibaba-NLP/gte-multilingual-reranker-base` and `BAAI/bge-reranker-large` were named in the
  decision's candidate list but not fetched from a primary source this session (param
  count/context length/licence unconfirmed) — flagged rather than guessed at.

## Verified locally (2026-09-30, after the note above)

A timing run on this laptop's CPU (scratch script, not committed): three real fused pools of 38,
45 and 48 candidates, `CrossEncoder.predict(batch_size=16)`, after a warm-up call.
- `cross-encoder/ms-marco-MiniLM-L-6-v2` at 512 tokens takes 2.69, 3.36 and 3.72 s.
- `Alibaba-NLP/gte-reranker-modernbert-base` loads directly through `CrossEncoder`, and its config
  confirms `max_position_embeddings` 8192. It takes 38.6, 43.2 and 39.5 s at `max_length=1024`,
  and 42.9, 44.9 and 43.9 s at 2048.

That is about 12x today's latency, past the 30 s ceiling. The ModernBERT swap drops out at full
pool size. Only a much smaller rerank pool could bring it back. Windowed MaxP on the current
model is the candidate to measure first.

### Second timing run (2026-10-01)
Same method, with the scratch script `timing2.py`. The full fused pools (38, 40 and 48 chunks)
produce 82, 85 and 103 MaxP windows, so windowing roughly doubles the pairs a model scores.

| Model | Size | Seconds per pool at 512 tokens | At 1024 tokens |
|---|---|---|---|
| `ms-marco-MiniLM-L-6-v2` | 23M | 4.59 mean over 3 pools; 2.75 on the MSFT pool alone | - |
| `BAAI/bge-reranker-base` | 278M | 22.87 | - |
| `BAAI/bge-reranker-base`, its own `onnx/model.onnx` | 278M | 22.91 (no gain from ONNX) | - |
| `gte-reranker-modernbert-base`, `onnx/model_int8.onnx` | 149M | 17.40 (MSFT pool) | 30.61 |
| `BAAI/bge-reranker-v2-m3` | 568M | 53.75 (MSFT pool) | 96.45 |
| `Alibaba-NLP/gte-multilingual-reranker-base` | 306M | crashed: its remote modeling code indexes RoPE with garbage `position_ids` under transformers 5.15 | - |

`bge-reranker-v2-m3` loads through `CrossEncoder` without trouble.

Every stronger model is at least 5-6x today's latency before windowing, and about 10x or more
with it. None fits the 2-3x budget on this CPU, so step 3 (a stronger model plus windowing) is
closed for the full pool. One open option remains: a smaller second-stage pool (for example the
top 10 after L-6), which isn't measured.

## The two papers that failed to fetch (read 2026-09-30 from copies the user supplied)

**Multi-Reranker, 2nd place in the ACM-ICAIF '24 FinanceRAG challenge**
([arXiv:2411.16732](https://arxiv.org/abs/2411.16732), section 3.2, Table 2).
What the paper says:
- It skips embedding retrieval entirely. jina-reranker-v2-base-multilingual takes a first cut to
  the top 200, then a second reranker chosen per dataset picks the top 10. Each dataset's
  reranker was picked against the organizers' labels:
  - bge-reranker-v2-m3 for FinDER, TAT-QA and ConvFinQA;
  - gte-multilingual-reranker-base for FinQA;
  - jina-v2 for FinQABench, FinanceBench and MultiHiertt.
- Public-leaderboard nDCG@10 is 0.63996.
- For MultiHiertt, whose corpora have very large token counts with the key facts in tables,
  "table extraction" (indexing only the tables) was the best corpus variant in their ablation.
  Combining the original query with extracted keywords was the best query variant.
- GPT-4o summaries of the corpus hurt numeric questions.
- It gives no truncation or windowing details, and no CPU latency. Section 4 names compute cost
  as the main limitation.

Inference: no single reranker won across financial datasets, and the choice was made against
labels, which is what our harness does. The table-only corpus result supports separate table
chunks (V4) or table-focused windows.

**FinRank, an SEC-filing retrieval benchmark** ([arXiv:2608.07400](https://arxiv.org/abs/2608.07400),
sections 6.1, 7.1 and 7.2, Tables 4 and 5). What the paper says:
- It uses **our exact reranker**, `ms-marco-MiniLM-L-6-v2`, under a uniform 512-token truncation,
  on 1185 records.
- Reranking each record's candidate set of gold plus hand-picked confusable hard negatives
  (Table 5, MRR / nDCG@5):

  | Ranker | MRR | nDCG@5 |
  |---|---|---|
  | ms-marco cross-encoder | 79.8 | 76.6 |
  | BM25 | 78.2 | 75.4 |
  | TF-IDF | 80.4 | 77.9 |
  | bge-large-en-v1.5 | 79.1 | 76.5 |
  | e5-mistral-7b-instruct | 83.6 | 80.5 |

- On the global pool, a cross-encoder rerank of mpnet's top 20 lifts MRR from 22.2 to 26.9.
- Restricting BM25 to the record's own filing, by (ticker, year, doc_type), removes 92.9% of the
  hard negatives. It lifts BM25 Recall@10 from 32.1 to 55.0 and MRR from 23.8 to 41.9.

Inference, for us:
- On SEC filings at 512 tokens, our cross-encoder barely beats BM25 or TF-IDF at telling
  confusable passages apart. That matches our 462 model-caused misses. The model, not only the
  truncation, is weak here, so windowing may recover part of the misses but not all.
- The metadata-filter result is independent support for V2 (strict period filtering).
- Neither paper evaluates windowed or MaxP reranking, or a fused-rank floor. Those questions stay
  open.
