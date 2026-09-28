# Gemini model choice for the agent and judge (research note, 2026-09-28)

## Question

1. Which Gemini models can be used on the free tier today, what are their free-tier limits (RPM,
   RPD, TPM), and are quotas counted per model?
2. What do the docs say about how flash-lite differs from Flash or Pro for function calling,
   instruction following and thinking, and are there official benchmark numbers?
3. Could any Gemini API feature replace custom machinery here: document grounding and citations,
   `ANY` with allowed function names, parallel calls, or structured output combined with tools?
4. Is a model upgrade for the agent, the judge or both worth an A/B test? What would it cost in
   daily quota, and how can it be run without mixing quotas?

## Findings

Every claim in this section is sourced. Pages were fetched on 2026-09-28. Where a page's
last-updated date was shown, it is given. Some pages were read through a summarizing fetcher, so
the quotes below are close paraphrases unless a line says otherwise.

### F1. Rate limits: published structure, but no per-model free-tier numbers

- "Rate limits are applied per project, not per API key." RPD resets at midnight Pacific. Each
  dimension (RPM, TPM, RPD) is checked separately, and exceeding any one of them triggers a
  rate-limit error. Page last updated 2026-09-02.
  https://ai.google.dev/gemini-api/docs/rate-limits
- The page does not publish per-model numbers. It says limits "can be viewed in Google AI
  Studio". https://ai.google.dev/gemini-api/docs/rate-limits
- "Rate limits are more restricted for experimental and preview models."
  https://ai.google.dev/gemini-api/docs/rate-limits
- Tiers: Free needs an "active project or free trial". Tier 1 needs a linked billing account.
  Tier 2 needs $100 spent plus 3 days. Tier 3 needs $1,000 spent plus 30 days. The Batch API has
  its own separate limits. https://ai.google.dev/gemini-api/docs/rate-limits
- **Secondary sources only (not primary, and unverified):** a third-party tracker says 3.8, 3.7,
  3.6 and 3.5 Flash get about **20 free RPD**, while 3.5 Flash-Lite and 3.1 Flash-Lite get
  **500**. It also dates the removal of the per-model table from the docs to 2025-12-06, and says
  2.5 Flash dropped to about 5 RPM / 20 RPD after that.
  https://github.com/robhunter/agentdeals/issues/2017 and the search summary of
  https://www.scriptbyai.com/gemini-api-free-tier-limits/
  Google publishes no primary source for these numbers. The only authoritative checks are the AI
  Studio dashboard and the `quotaValue` field of a real `RESOURCE_EXHAUSTED` error (see R3).

### F2. Free-tier availability by model

The pricing page was last updated 2026-09-24:
https://ai.google.dev/gemini-api/docs/pricing

| Model | Free tier? | Paid price per 1M tokens (input / output) |
|---|---|---|
| gemini-3.8-flash | Free of charge | $0.75 / $3.75 until 2026-12-31, then $1.50 / $7.50 |
| gemini-3.7-flash, gemini-3.6-flash | Free of charge | same as 3.8 Flash |
| gemini-3.5-flash | Free of charge | $1.50 / $9.00 |
| **gemini-3.5-flash-lite** (current) | Free of charge | $0.30 / $2.50 |
| gemini-3.1-flash-lite | Free of charge | $0.25 / $1.50 |
| gemini-3.1-pro-preview | **Not available** | $2.00–4.00 / $12.00–18.00 |
| gemini-3-flash-preview | Free of charge | – |
| gemini-2.5-pro / flash / flash-lite | Free of charge (pricing page) | – |

- The models page (last updated 2026-09-24) lists all 3.x Flash and Flash-Lite models above as
  **Stable**, and 3.1 Pro only as a **Preview**. It says 2.5-series access is "limited to prior
  active users". https://ai.google.dev/gemini-api/docs/models
- Content sent on the free tier is used to improve Google's products. Paid-tier content is not.
  https://ai.google.dev/gemini-api/docs/pricing
- Release dates: 3.5-flash-lite went GA on 2026-07-21 as a "low-latency, highly cost-effective
  subagent". 3.6-flash went GA the same day, 3.7-flash on 2026-08-13 and 3.8-flash on 2026-09-02.
  https://ai.google.dev/gemini-api/docs/changelog

### F3. Positioning, thinking defaults and benchmarks

- 3.5 Flash-Lite is "optimized for high-throughput, low-cost execution for subagent tasks and
  document parsing". It supports function calling, structured outputs, thinking, File Search,
  caching and Batch.
  https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite
- 3.8 Flash is "engineered for long-horizon software engineering, autonomous agents, and complex
  enterprise workflows". It supports thinking levels low, medium and high; "minimal is not
  supported". https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash
- Default thinking levels, from the thinking guide:
  - **3.5-flash-lite: Minimal**, which can be raised to low, medium or high.
  - 3.6-flash: Medium.
  - 3.7-flash and 3.8-flash: Medium. Minimal is not available on either.

  Thinking tokens are billed as output, and `max_output_tokens` caps thinking and output
  together. https://ai.google.dev/gemini-api/docs/thinking
  The Gemini 3 guide describes the levels this way: `minimal` is for "chat/high-throughput",
  `low` is "best for simple instruction-following", and `medium` is for "most tasks". That page
  says Flash and Pro default to `high`, which contradicts the thinking guide's Medium (see open
  question Q4). https://ai.google.dev/gemini-api/docs/gemini-3
- **Temperature:** "we strongly recommend keeping the temperature parameter at its default value
  of `1.0`… setting it below 1.0 may lead to unexpected behavior, such as looping or degraded
  performance, particularly in complex mathematical or reasoning tasks."
  https://ai.google.dev/gemini-api/docs/gemini-3
- 3.5 Flash-Lite benchmarks are published only against 3.1 Flash-Lite and third-party models,
  not against 3.x Flash:
  - SWE-Bench Pro: 54.2% (3.1 Flash-Lite: 38.3%)
  - Terminal-bench 2.1: 54.0% (31.0%)
  - OSWorld-Verified: 74.0% (54.3%)
  - GDM-MRCR v2 at 128k: 72.2% (60.1%)

  Sources: https://deepmind.google/models/gemini/flash-lite/ and
  https://deepmind.google/models/model-cards/gemini-3-5-flash-lite/
  The model card's stated limitations include hallucinations.
- 3.8 Flash benchmarks:
  - **Vals Finance Agent v2: 61.4%** (3.7 Flash: 59.0%)
  - HLE-Verified: 54.9%

  Source: https://deepmind.google/models/gemini/flash/
  No Flash-Lite score is published on the same benchmark.
- Launch post: 3.5 Flash-Lite is for "agentic search and document processing", and 3.6 Flash is
  "our workhorse model", "a step up in coding and knowledge work".
  https://blog.google/innovation-and-ai/models-and-research/gemini-models/gemini-3-6-flash-3-5-flash-lite-3-5-flash-cyber/
- Google publishes **no** first-party function-calling, instruction-following or tau-bench
  numbers comparing Flash-Lite with Flash. None of the pages fetched had any.

### F4. API features relevant to the custom machinery

- **Function-calling modes:**
  - AUTO: the default.
  - ANY: "constrained to always predict a function call".
  - NONE.
  - VALIDATED: "Model ensures function schema adherence".

  Allowed function names limit which declared functions the model may call.
  https://ai.google.dev/gemini-api/docs/function-calling and
  https://ai.google.dev/api/generate-content
  Both parallel calls (several independent calls in one turn) and compositional calls (chained
  across turns) are documented. The docs examples now use the Interactions API
  (`tool_choice`), not generateContent. https://ai.google.dev/gemini-api/docs/function-calling
- **Structured output combined with tools:** "Gemini 3 lets you combine Structured Outputs with
  built-in tools, including … File Search, and Function Calling." The page describes this as
  Gemini-3-only and in preview. Schemas guarantee format, not values: "always validate values in
  your application".
  https://ai.google.dev/gemini-api/docs/structured-output
- **File Search:** a managed store that chunks, embeds and indexes documents, with configurable
  `max_tokens_per_chunk` and `max_overlap_tokens`.
  - It returns `file_citation` annotations naming the source document, with page numbers "when
    available".
  - Free-tier storage is 1 GB. Indexing is billed at embedding prices, and storage and
    query-time embeddings are free.
  - It cannot be combined with Google Search or URL Context.

  https://ai.google.dev/gemini-api/docs/file-search
  The fetched text gave its supported models as the 3.x Flash models and 3.1 Pro Preview, but
  the Flash-Lite model page lists File Search as supported (see open question Q5). The changelog
  entry of 2026-05-05 added `page_numbers` and `media_id` to grounding metadata.
  https://ai.google.dev/gemini-api/docs/changelog
- **Thought signatures:** in generateContent, signatures are "metadata that can be attached to
  any part, such as living inside `functionCall` parts". The Interactions API manages them
  automatically in stateful mode. https://ai.google.dev/gemini-api/docs/thinking#signatures

## Repo facts

- R1. The model is pinned in `.env` line 18 to `GEMINI_MODEL_NAME=gemini-3.5-flash-lite`,
  pinned 2026-09-24 (WP2). The default in `config.py:39` and `.env.example:24` is
  `gemini-flash-lite-latest`.
- R2. **The judge shares the agent's model.** `llm_backends.complete()` (line 455) uses
  `GEMINI_MODEL_NAME`. `--judge-backend` picks the backend, not the model. There is no separate
  judge-model setting, so changing `GEMINI_MODEL_NAME` changes both the agent and the judge.
- R3. Quota is counted per project **and per model**. This is confirmed by real errors in
  `eval/eval_results/20260912T003832Z.json`: `quotaId
  GenerateRequestsPerDayPerProjectPerModel-FreeTier`, `quotaDimensions {model:
  gemini-3.5-flash-lite}`, `quotaValue '500'`. See also
  `docs/reviews/2026-09-17-fix-orphaned-table-overlap-chunking.md:102`.
- R4. Sampling settings:
  - The agent calls with `temperature=0.1` (`llm_backends.py:381`).
  - The judge calls with `temperature=0.0` (`complete()`).
  - No `thinking_config` is set anywhere, so the agent runs at flash-lite's default **Minimal**
    thinking.
- R5. Forced tool choice already uses `FunctionCallingConfigMode.ANY` with
  `allowed_function_names=[force_tool]` (`llm_backends.py:367-373`).
- R6. The SDK is pinned at `google-genai==2.18.1`, called through `client.chats`
  (generateContent). `MAX_TOOL_ITERATIONS = 6` (`agent.py:59`).
- R7. The flakiness map
  (`docs/plans/2026-09-28-gate-refusal-flakiness-map.md:35`) puts a 3× panel at about 200
  requests against the 500/day cap.

## Inferences

These are not stated in any source.

- I1. **A non-lite Flash is usable on the free tier, but it cannot run the panel.** If the
  secondary figure of about 20 RPD is right, one 3× panel of about 200 requests would take
  roughly 8–10 days of quota for the agent alone. The per-question round-trip count (up to about
  9) also means a single question could be cut off mid-run by a low RPM. That is plausibly about
  5 RPM, but it is unverified.
- I2. **The cheapest lever is untested and costs no extra daily requests: thinking level and
  temperature on the same model.**
  - The agent runs 3.5-flash-lite at Minimal thinking, the level Google positions for "chat /
    high-throughput".
  - It also runs at temperature 0.1, against Google's explicit Gemini 3 warning about going
    below 1.0.
  - Raising `thinking_level` to `low`/`medium` uses the same 500-RPD bucket. It costs tokens
    (TPM and latency), not requests.
  - Behavioural failures like placeholder numbers, wrong citation indexes and skipped calculate
    calls plausibly benefit from more reasoning.
  - This is a prompt-change-protocol item: it changes model input and config, and so the
    fingerprint.
- I3. **The judge must be decoupled before any agent-model A/B.**
  - Because of R2, pointing `GEMINI_MODEL_NAME` at 3.8-flash would also change the grader. Any
    PASS/FAIL difference would then mix agent quality with grader drift, which confounds the
    comparison. It would also spend the scarce Flash quota on judge calls.
  - A separate judge-model setting that stays pinned to `gemini-3.5-flash-lite` keeps grading
    constant and keeps judge calls in the flash-lite bucket.
  - Per R3, each model has its own bucket, so this also stops the two arms' quotas from mixing.
  - This touches `llm_backends.complete()` and the judge path, which are high-blast-radius.
- I4. **Upgrading the judge is a separate question with a real cost.** A different judge model
  changes the meaning of every historical PASS/FAIL. Swapping it only makes sense if a judge
  error rate has been measured. Nothing in this research shows the judge is the bottleneck.
- I5. **A paid Tier-1 run is the realistic way to A/B 3.8-flash.** One panel is about 160 agent
  requests. At a guessed 10–20k input tokens per request that is about 1.6–3.2M input tokens,
  about $1.2–2.4 at $0.75/M, plus output and thinking tokens. That is likely under $5 per panel.
  The token counts are guessed, not measured; the logged token counts (LLM calls log tokens)
  would give the real figure. A bonus: paid-tier content is not used for training.
- I6. **Most of the API features don't retire the custom machinery.**
  - `ANY` + allowed names is already in use (R5).
  - VALIDATED only enforces the schema. Placeholder values and wrong citation indexes are
    schema-valid, so it can't catch them.
  - Structured output + tools also guarantees shape, not values, which the docs say themselves.
  - File Search citations are at document and page level, not verbatim-span-level. They would
    replace Chroma retrieval, not the quote-to-number grounding checks the project relies on, and
    they don't cover XBRL tool output.
  - None of these is a substitute for citation verification.
  - Parallel function calls could cut round trips, and so RPD, if the agent issues independent
    searches. That is worth a check against logs, not a redesign.

## Open questions

- Q1. What are the real free-tier RPM, RPD and TPM figures for gemini-3.8-flash (and 3.6/3.7)
  on this project? Check the AI Studio rate-limit dashboard, or read `quotaValue` from a single
  deliberate 429. No primary doc publishes them.
- Q2. How many of the ~200 panel requests are agent calls and how many are judge calls? Count
  them from the logged events of one panel run.
- Q3. Does `thinking_level` `low`/`medium` on 3.5-flash-lite change the four failure modes? How
  much do latency and TPM grow per question?
- Q4. Is the default thinking level on 3.x Flash Medium (thinking guide) or High (Gemini 3
  guide)? Pass it explicitly in any A/B so the arms don't depend on either default.
- Q5. Does File Search support 3.5-flash-lite? The model page and the File Search page disagree.
  This only matters if File Search is ever considered.
- Q6. Does the temperature warning apply to flash-lite in tool-calling loops? Is the 0.1 value
  historically justified? Check its commit or decision history before changing it (§4 of the
  global CLAUDE.md, revisiting prior decisions).

## Recommendation

1. **First A/B, which needs no model change:** 3.5-flash-lite at `thinking_level=low` (and
   possibly `medium`) against the current Minimal. Keep everything else fixed and run it on the
   13-question panel. It costs about 200 requests from the same 500-RPD bucket, so run it on a
   day with no other full run. Only then consider temperature 1.0 as its own arm, one variable at
   a time. The docs put this lever squarely on the recurring failure type (instruction-following
   and reasoning) and it adds no quota. **Worth doing.**
2. **Agent upgrade to gemini-3.8-flash: worth an A/B, but not on the free tier.**
   - At the secondary figure of about 20 RPD, one 3× panel (about 160 agent requests) would take
     over a week.
   - Options:
     - Confirm the real free cap first (Q1).
     - Run one panel pass (13 questions, about 55 requests) over about 3 days as a smoke signal.
     - Or enable Tier-1 billing for a single panel, likely under $5 by I5's rough estimate.
   - Also pass the thinking level explicitly.
3. **Judge: keep it on gemini-3.5-flash-lite.** Don't upgrade it in the same experiment.
4. **Prerequisite for any agent-model A/B:** add a separate judge-model setting defaulting to
   the pinned flash-lite, so the judge stays fixed while `GEMINI_MODEL_NAME` varies. Each arm then
   draws only on its own per-model bucket (R3): the agent on the arm's model, the judge on
   flash-lite. The judge's usage (about 40 requests per panel, if Q2 confirms) then counts against
   flash-lite's 500. This change touches `llm_backends.complete()` and `eval_harness`'s judge
   path, both high-blast-radius, and needs its own Standard-tier plan.
5. **Don't adopt File Search, VALIDATED or structured output as fixes for the current
   failures.** None of them checks values (I6).
