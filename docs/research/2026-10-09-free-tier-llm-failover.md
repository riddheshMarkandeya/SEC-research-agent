# Free-tier LLM failover options for the eval loop (research, 2026-10-09)

Feeds the decision between options A–D (multi-provider free keys, aggregator/gateway, more Gemini
quota, or status quo plus one pinned secondary backend). The main concern is eval stability.
All pages were fetched on 2026-10-09. Each source is marked with the date it shows, or "undated".

## Key findings (sources say)

1. **Gemini quotas are per project and per model. The free-tier numbers are not in the public docs.**
   "Rate limits are applied per project, not per API key." "Limits vary depending on the specific
   model being used." RPD "reset at midnight Pacific time". Per-model free-tier figures are shown
   only in AI Studio (login required).
   [rate-limits, updated 2026-09-02](https://ai.google.dev/gemini-api/docs/rate-limits)
2. **The `-latest` alias we use is hot-swapped.** "This alias will get hot-swapped with every new
   release of a specific model variation". Breaking changes come with 2 weeks' email notice.
   [models, updated 2026-10-06](https://ai.google.dev/gemini-api/docs/models). The docs don't say
   which model `gemini-flash-lite-latest` resolves to. The newest Flash-Lite listed is
   `gemini-3.5-flash-lite` (stable). Also listed stable: `gemini-3.1-flash-lite`, and Flash
   3.5/3.6/3.7/3.8 (same page).
3. **Gemini paid pricing.** 3.5 Flash-Lite costs $0.30/M input and $2.50/M output (thinking
   included). Batch costs $0.15/$1.25. "Batch pricing has no free tier". Free-tier content is used
   to improve Google's products; paid-tier content is not.
   [pricing, updated 2026-10-09](https://ai.google.dev/gemini-api/docs/pricing). 3.5 Flash-Lite
   has a 1,048,576-token input limit and supports function calling and the Batch API.
   [model page, updated 2026-07-30](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite)
4. **Multiple Gemini projects to dodge quota.** The Gemini API terms have no explicit clause on
   this. [terms, updated 2026-04-28](https://ai.google.dev/gemini-api/terms). The Google APIs ToS,
   which apply to all Google APIs, say: "You agree to, and will not attempt to circumvent, such
   limitations documented with each API. If you would like to use any API beyond these limits,
   you must obtain Google's express consent".
   [Google APIs ToS §2(d), modified 2021-11-09](https://developers.google.com/terms)
5. **Groq.** The tool_choice API supports `none`, `auto`, `required` and a named function ("forces
   the model to call that tool"). It also exposes `seed`, documented as "best effort", and
   `system_fingerprint`. [API reference, undated](https://console.groq.com/docs/api-reference).
   The rate-limit table on the page is labelled "base limits for the Developer plan". It lists
   gpt-oss-120b and qwen3.8-27b at 30 RPM, 1K RPD, 8K TPM and 200K TPD. The Free-plan tab didn't
   render in the fetch. Limits are "at the organization level".
   [rate-limits, undated](https://console.groq.com/docs/rate-limits). The deprecation page says
   **llama-3.3-70b-versatile shut down on 2026-08-16, for free and developer tiers**
   [deprecations, undated](https://console.groq.com/docs/deprecations), but the models page still
   lists it as production. [models, undated](https://console.groq.com/docs/models). The AUP bars
   use "beyond published parameters, rate limits, or use limitations, including by registering
   multiple accounts or orchestrating usage between multiple organizations".
   [AUP, effective 2025-10-15](https://console.groq.com/docs/legal/ai-policy)
6. **OpenRouter `:free`.**
   - **Limits:** 20 RPM. 50 requests/day with fewer than 10 credits purchased, and 1,000/day once
     10 credits (about $10) have ever been bought. A negative balance gives 402s even on free
     models. [limits, undated](https://openrouter.ai/docs/api-reference/limits)
   - **Free models:** the live model list has 15 `:free` ids. None is Llama 3.3 70B, Qwen,
     DeepSeek, Mistral or gpt-oss. They are mostly Nemotron 3/3.5, Gemma 4 26B/31B, Poolside,
     Liquid and others. 13 of the 15 advertise `tools` and 11 advertise `tool_choice`.
     [models API, live](https://openrouter.ai/api/v1/models)
   - **`openrouter/free`** "selects free models at random". That is unsuitable for evals. (Same
     source.)
   - **Multiple accounts:** prohibited if the purpose is "bypassing or circumventing use limits".
     [terms §7, updated 2026-08-31](https://openrouter.ai/terms)
7. **OpenRouter provenance and routing.**
   - **Fallback:** the `models` array falls back on "any error … including … rate-limiting". The
     response's `model` field "shows the model that was ultimately used".
     [model fallbacks, undated](https://openrouter.ai/docs/guides/routing/model-fallbacks)
   - **Provider routing:** by default it will "load balance requests across providers,
     prioritizing price", so the provider behind a single model id can vary between calls.
     `provider.order`, `only`, `allow_fallbacks:false`, `require_parameters` and `quantizations`
     pin it down. [provider selection, undated](https://openrouter.ai/docs/guides/routing/provider-selection)
   - **Provider name:** the completion response has no `provider` field.
     [API overview, undated](https://openrouter.ai/docs/api-reference/overview). It is available
     afterwards from `GET /generation`, which returns `provider_name`, `model`, `router` and
     `provider_responses` (per-attempt).
     [get generation, undated](https://openrouter.ai/docs/api-reference/get-a-generation)
8. **LiteLLM Router.**
   - **Cooldowns:** a 429 causes "immediate cooldown". The defaults are `allowed_fails`=3 and
     `cooldown_time`=5 s.
   - **Retries:** "For RateLimitError we implement exponential backoffs". There are ordered
     deployment priorities (`order=1,2,…`), then fallbacks keyed by model-group name.
   - **Provenance:** the serving deployment is in `response._hidden_params["model_id"]`, or the
     `x-litellm-model-id` header on the proxy.
   - [routing, undated](https://docs.litellm.ai/docs/routing)
9. **LiteLLM `tool_choice` mapping** (source at commit `de6a071`, 2026-10-09):
   - **Gemini:** `required` → `mode="ANY"`, and a named function → `ANY` +
     `allowed_function_names=[name]`. Other values raise unless `drop_params`.
     [gemini transformation](https://github.com/BerriAI/litellm/blob/de6a0717b7e2fa1ba5b6565d8a9e3ec2223719bc/litellm/llms/vertex_ai/gemini/vertex_and_google_ai_studio_gemini.py#L370-L383)
   - **Mistral:** `required` → `"any"`, but a dict (named function) is **silently not mapped**
     (`if param == "tool_choice" and isinstance(value, str)`). Mistral's own API offers only
     `auto`/`any`/`none`.
     [mistral transformation](https://github.com/BerriAI/litellm/blob/de6a0717b7e2fa1ba5b6565d8a9e3ec2223719bc/litellm/llms/mistral/chat/transformation.py#L136-L195),
     [Mistral function calling, undated](https://docs.mistral.ai/capabilities/function_calling/)
   - **Groq:** passed through OpenAI-style.
     [groq transformation](https://github.com/BerriAI/litellm/blob/de6a0717b7e2fa1ba5b6565d8a9e3ec2223719bc/litellm/llms/groq/chat/transformation.py)
10. **Several listed providers are gone or are not a durable free tier.**
    - **GitHub Models** "has been fully retired" (2026-07-30).
      [GitHub docs](https://docs.github.com/en/github-models/use-github-models/prototyping-with-ai-models)
    - **Cerebras** is now a Free *Trial*: "$5 in free credits after adding a verified payment
      method", expiring in 30 days. It offers gpt-oss-120b and qwen-3.8-27b at 5 RPM and 1M TPD.
      [Cerebras rate limits, undated](https://inference-docs.cerebras.ai/support/rate-limits)
    - **SambaNova free tier** (no payment method) is **20 RPM, 20 RPD**, 200K TPD for
      DeepSeek-V3.1, Llama-3.3-70B and gpt-oss-120b.
      [SambaNova rate limits, undated](https://docs.sambanova.ai/docs/en/models/rate-limits)
11. **Cloudflare Workers AI and NVIDIA NIM.**
    - **Cloudflare** gives 10,000 Neurons/day free, resetting at 00:00 UTC.
      Llama-3.3-70B-fp8-fast costs 26,668 Neurons per M input tokens and 204,805 per M output
      tokens. gpt-oss-120b costs 31,818 / 68,182.
      [Workers AI pricing, updated 2026-10-09](https://developers.cloudflare.com/workers-ai/platform/pricing/).
      The function-calling docs don't mention `tool_choice`.
      [function calling, updated 2026-04-21](https://developers.cloudflare.com/workers-ai/features/function-calling/)
    - **NVIDIA NIM** is free for Developer Program members "for prototyping, research,
      development and testing purposes only".
      [NIM FAQ, updated 2026-08-06](https://docs.api.nvidia.com/nim/docs/product). No official
      RPM or credit figure was found. The ~40 RPM / 1,000 credits numbers are forum reports only.
      [forum](https://forums.developer.nvidia.com/t/request-for-nvidia-build-api-rate-limit-increase-40-rpm-200-rpm/377433)
12. **Mistral.**
    - **Free mode:** limits are shown only on the in-console Limits page. Limits are per org and
      per model, in RPS, TPM and tokens/month.
      [usage limits, undated](https://docs.mistral.ai/admin/billing-usage/usage-limits),
      [help, undated](https://help.mistral.ai/en/articles/698531-why-am-i-hitting-api-rate-limits-and-how-do-i-increase-them)
    - **Training:** "we may use your data (input and output) to train" unless opted out.
      [help, undated](https://help.mistral.ai/en/articles/347617-do-you-use-my-user-data-to-train-your-artificial-intelligence-models)
13. **"OmniRouter" is probably OmniRoute.** It is an MIT-licensed, self-hosted (or hosted via
    "Cheaper Inference") OpenAI-compatible gateway that picks "the next healthy target" when one is
    out of quota. It advertises "90+ free tiers", 19 routing strategies, OAuth/subscription
    providers and "35 web-cookie providers" (ChatGPT Web, Claude Web, Gemini Web).
    [omniroute.online, snapshot 2026-10-09](https://omniroute.online/),
    [repo](https://github.com/diegosouzapw/OmniRoute). The awesome list names "OmniRoute", not
    "OmniRouter".
    [awesome-free-models, last checked 2026-10-01](https://github.com/12britz/awesome-free-models)
14. **Eval tooling records the model per run, and Inspect also records it per sample/call.**
    - **Inspect AI:** `EvalSpec.model` ("Model used for eval"), `model_args`,
      `model_generate_config` and `revision`. `EvalSample.model_usage: dict[str, ModelUsage]` is
      keyed by model name, plus `role_usage`. `ModelEvent.model` and `.role` are recorded per call.
      [log reference, undated](https://inspect.aisi.org.uk/reference/inspect_ai.log.html),
      [source @f95ab3d](https://github.com/UKGovernmentBEIS/inspect_ai/blob/f95ab3d4e9c7692e2ce6830e78b7ef184ba8e6f1/src/inspect_ai/log/_log.py#L323-L327)
    - **lm-eval-harness:** writes `model`, `model_args`, `model_source`, `git_hash` and env info
      into results.
      [evaluator.py @d6de816](https://github.com/EleutherAI/lm-evaluation-harness/blob/d6de81643928d653435c431bae19945d41d32520/lm_eval/evaluator.py#L354-L421)
    - **HELM:** benchmarks all models "under standardized conditions" on "the same core scenarios
      and metrics". [HELM paper, arXiv 2211.09110](https://arxiv.org/abs/2211.09110)
    - None of the pages read explicitly says "don't mix models within a run". Their data models
      assume one model per run, with per-sample usage keyed by model.
15. **Temperature 0 is not deterministic on shared servers.** 1,000 temperature-0 completions from
    Qwen3-235B produced "80 unique completions". The cause is non-batch-invariant kernels under
    varying server load.
    [Thinking Machines, 2025-09-10](https://thinkingmachines.ai/blog/defeating-nondeterminism-in-llm-inference/).
    Groq's `seed` is "best effort", and `system_fingerprint` exists to detect backend changes.
    [Groq API ref](https://console.groq.com/docs/api-reference)

## Provider comparison (sources say; "?" = not found on an official page)

| Provider | Free limits (official) | Strong tool-capable models on free tier | Forced tool choice | Context | Free-tier data use | Multi-account ToS | Page date |
|---|---|---|---|---|---|---|---|
| Google Gemini | per project, per model; numbers only in AI Studio (our observed ~500 RPD) | 3.5 Flash-Lite, 3.x Flash | yes: `any` mode (+ allowed tools) [fc docs](https://ai.google.dev/gemini-api/docs/function-calling) | 1M (3.5 FL) | used to improve products; human review possible | Google APIs ToS: don't circumvent limits | 2026-09-02 / 2026-10-09 |
| Groq | Developer-labelled table: 30 RPM, 1K RPD, 8K TPM, 200K TPD (gpt-oss-120b, qwen3.8-27b); Free tab ? | gpt-oss-120b; qwen3.8-27b (preview); llama-3.3-70b (conflicting: shut down 2026-08-16 vs listed) | yes: `required` + named fn | 131K | ? (`/docs/your-data` not read) | AUP bans multiple accounts/orgs | undated; AUP 2025-10-15 |
| Mistral | per org/model; numbers only in console | Large 3, Medium 3.5, Small 3.2 | `any` only (no named fn) | ? | trains unless opted out | ? | undated |
| OpenRouter `:free` | 20 RPM; 50 RPD (<10 credits) / 1,000 RPD (≥10 credits bought) | Nemotron 3 Ultra/Super, Gemma 4 31B (no Llama/Qwen/DeepSeek free ids today) | named fn yes; `required` not documented | 262K–1M | per provider; OR doesn't store unless opted in | ToS bans multi-accounts to bypass limits | ToS 2026-08-31; limits undated |
| Cerebras | trial only: $5, needs card, 30 days; 5 RPM, 1M TPD | gpt-oss-120b, qwen-3.8-27b | ? | ? | ? | ? | undated |
| SambaNova | 20 RPM / **20 RPD** / 200K TPD (no card) | DeepSeek-V3.1, Llama-3.3-70B, gpt-oss-120b | ? | ? | ? | ? | undated |
| Cloudflare Workers AI | 10K Neurons/day | Llama-3.3-70B, gpt-oss-120b, Qwen3.8-27B | not documented | ? | ? | ? | 2026-10-09 |
| NVIDIA NIM | official: free for Dev Program, prototyping only; numbers forum-only (~40 RPM) | many | ? | ? | ? | ? | 2026-08-06 |
| GitHub Models | **retired 2026-07-30** | — | — | — | — | — | 2026 |

## Inference (not stated by sources)

- **Our call volume vs. small free tiers.** The table and arithmetic below assume a guessed call
  size of about 6K input and 400 output tokens; measure it from `usage_metadata` before relying on
  this. A 250-call run is about 1.5M input tokens.
  - **SambaNova** (20 RPD) can't run even one full eval, and neither can OpenRouter without
    credits (50 RPD).
  - **Groq's** 200K TPD (Developer-labelled) would cover only about 30 calls. Its free tier is
    probably lower.
  - **Cloudflare:** 10K Neurons/day at ~250 Neurons/call gives about 40 calls/day.
  - **OpenRouter with $10 of credits ever bought** (1,000 RPD) is the only aggregator path that
    fits a full run on one model per day, at 20 RPM.
- **Paid Gemini is cheap at our volume.** Under the same guessed call size, 3.5 Flash-Lite costs
  about $0.90 input + $0.50 output, roughly **$1.40/day for 500 calls**, or about $0.70 per
  250-call eval run. Batch halves that, but Batch is asynchronous and our agent loop is multi-turn,
  so each turn would be a separate batch round. Batch fits the judge step better than the agent
  loop. Paid tier also stops content being used for training, and Tier 1 raises limits once
  billing is linked.
- **Rotating Gemini models** (Flash-Lite ↔ Flash, 3.1 FL ↔ 3.5 FL) probably gives separate
  per-model quotas, because the docs say limits vary by model. But that is model mixing, the same
  stability problem as option A. Several projects to multiply quota conflicts with Google APIs ToS
  §2(d) in spirit.
- **The `gemini-flash-lite-latest` alias is itself an eval-stability risk, regardless of failover.**
  A hot-swap silently changes the model between runs, and `GEMINI_MODEL_NAME` records only the
  alias. Pinning `gemini-3.5-flash-lite` and recording the resolved model would address it.
- **Per-call provenance** is available everywhere it matters:
  - Gemini: `model_version` in the response. This should be verified.
  - OpenRouter: `model` in the response, plus `provider_name` via `/generation`.
  - LiteLLM: `_hidden_params["model_id"]`.
  - Groq: `system_fingerprint`.
  Inspect's shape, with run-level `model` plus per-sample usage keyed by model, is a reasonable
  template for our report.
- **Forced tool calls aren't portable.** Gemini ANY with allowed names, Groq `required` or a named
  function, Mistral `any` only, and OpenRouter's named function differ semantically. A LiteLLM
  layer silently drops a named-function `tool_choice` for Mistral. Our forced-tool path would need
  per-provider tests.
- **OmniRoute** can drain subscription quota through web cookies. That likely breaches those
  services' terms, and its randomised "auto" routing is the opposite of what an eval needs.

## Open questions

1. What are the actual Gemini free-tier RPM/RPD for 3.5 Flash-Lite, 3.1 Flash-Lite and 3.x Flash?
   Check in AI Studio.
2. Which model does `gemini-flash-lite-latest` resolve to today? Check `model_version` in a
   response.
3. What are Groq's Free-plan numbers? The tab didn't render; check the console limits page or the
   `x-ratelimit-*` headers. Is llama-3.3-70b-versatile live or shut down?
4. What is Groq's free-tier data retention/training policy (`/docs/your-data`, not read)? The same
   question applies to Cerebras and NVIDIA.
5. What are the numbers on Mistral's in-console Free-mode Limits page? Can an API-only free org
   reach the training opt-out toggle?
6. What does one agent question actually use in tokens (input/output)? This is needed for the
   cost, TPD and Neuron estimates above.
7. How deterministic is our own pipeline on Gemini at temperature 0? Rerun the same `--ids` twice
   and diff, to size the noise floor before comparing models.
8. Does Gemini's `function_calling_config` `ANY` + allowed names behave the same as Groq's named
   `tool_choice` for our tool schemas, e.g. on JSON-schema features like enums?

## Implications for options A–D (inference)

- **A. Multi-provider free keys + own router.** Pro: no spend, and each provider is independent.
  Cons:
  - Mixes models within a run by design.
  - Most real free tiers are tiny (SambaNova 20 RPD, Cloudflare ~40 calls, Groq ~200K TPD).
    Cerebras and GitHub Models are no longer free tiers.
  - Forced tool calls differ per provider.
  - There is a lot of router code to own and test.
  - Several keys at one provider is banned (Groq AUP, OpenRouter ToS).
- **B. Aggregator.** OpenRouter with $10 of credits bought once gets 1,000 RPD on `:free` with one
  key, and the response reports the model. The strong free models (Nemotron 3 Ultra/Super,
  Gemma 4 31B) differ from Gemini, though.
  - Provider load-balancing must be pinned (`provider.order`, `allow_fallbacks:false`).
  - The `models` fallback would mix models mid-run. Only use it as a hard-stop, not a fallback.
  - LiteLLM is a good library if we go multi-provider. Its cooldowns and provenance work, but
    watch the Mistral named-tool drop.
  - OmniRoute is not recommended (ToS-risky cookie routes; random routing).
- **C. More Gemini quota.** Paid Flash-Lite at about $1–2/day (under the token guess) removes the
  quota problem with the *same model*. That is the best fit for eval stability, and it also
  stops training on our data. Multiple free projects is the ToS-grey route. Model rotation is
  model mixing. Batch API suits the judge, not the multi-turn agent.
- **D. Status quo + discipline + one pinned secondary for whole runs.** This keeps runs
  single-model and comparable. It needs a per-model baseline and run-level model provenance,
  which `_model_name_for` already half-provides. Pin the Gemini alias regardless. Candidate
  secondaries for whole-run use: OpenRouter Nemotron/Gemma `:free` with credits, or Groq
  gpt-oss-120b if its free TPD fits after measurement. Either needs its own baseline, since
  scores aren't comparable to Gemini's.

## Paid tier: price-to-intelligence (added 2026-10-09)

Scope: which paid model gives the best tool-calling and numeric/financial accuracy per dollar for
our agent loop. All pages were read on 2026-10-09. "Page date" means the date the page itself
shows, if any.

### Key findings (sources say)

- **Gemini paid prices per 1M tokens, input / output** ([Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing)):
  - `gemini-3.5-flash-lite`: $0.30 / $2.50, cached $0.03.
  - `gemini-3.1-flash-lite`: $0.25 / $1.50, cached $0.025.
  - `gemini-3.8-flash` (also 3.7 and 3.6): $0.75 / $3.75, cached $0.075.
  - 3.8 Flash rises to $1.50 / $7.50 on 2027-01-01.
  - `gemini-3.5-flash`: $1.50 / $9.00. The older 3.5 Flash costs *more* than 3.8 Flash.
  - Batch halves every price. Output prices include thinking tokens.
- **OpenAI** ([OpenAI pricing](https://developers.openai.com/api/docs/pricing)) lists small models
  under "luna" names as well as mini/nano. Prices per 1M tokens, input / output:
  - `gpt-6-luna`: $0.10 / $0.50. Released 2026-09-22, per
    [AA](https://artificialanalysis.ai/models/gpt-6-luna). Its default effort is `medium`
    ([reasoning guide](https://developers.openai.com/api/docs/guides/reasoning)).
  - `gpt-5.6-luna`: $0.20 / $1.20.
  - `gpt-5.4-mini`: $0.75 / $4.50.
  - `gpt-5.4-nano`: $0.20 / $1.25.
  - Cached input is 0.1×, and Batch or Flex is 0.5×.
  - Reasoning tokens "are billed as output tokens" ([reasoning guide](https://developers.openai.com/api/docs/guides/reasoning)).
- **Anthropic's `claude-haiku-5-5`**, released 2026-10-07: $0.10 / $0.50 per 1M for prompts up to
  100K tokens, and $0.50 / $2.50 above that. Cache reads cost $0.01, and Batch is 50% off. That is
  about 90% cheaper than Haiku 4.5 at $1 / $5
  ([Claude pricing](https://platform.claude.com/docs/en/about-claude/pricing),
  [Haiku 5.5 page](https://anthropic.com/claude-haiku-5-5)). Its effort levels run low to max, with
  `medium` the default. It supports adaptive thinking only. The usage field
  `output_tokens_details.thinking_tokens` reports "how many of the billed output tokens were
  internal reasoning"
  ([extended thinking](https://platform.claude.com/docs/en/build-with-claude/extended-thinking)).
- **DeepSeek, first-party, per 1M tokens** ([DeepSeek pricing](https://api-docs.deepseek.com/quick_start/pricing)):
  - `deepseek-flash` (V4.1-Flash): $0.30 input on a cache miss, $1.20 output, at peak times.
    Off-peak is half that: $0.15 / $0.60.
  - `deepseek-v4-pro`: $1.32 / $3.96 at peak, $0.66 / $1.98 off-peak.
  - Peak hours are 01:00–04:00 and 06:00–10:00 UTC on weekdays. Cache hits cost $0.003–$0.044.
- **Qwen, first-party** ([Model Studio pricing](https://www.alibabacloud.com/help/en/model-studio/model-pricing),
  Singapore region): `qwen3.8-flash` costs $0.15 / $0.47, `qwen3.8-27b` $0.50 / $3.00, and
  `qwen3.7-plus` $0.40 / $1.60. Mistral's own pricing page lists only Large, at $0.50 / $1.50,
  with Batch 50% off ([Mistral pricing](https://mistral.ai/pricing)). OpenRouter's live
  [models JSON](https://openrouter.ai/api/v1/models) lists these other prices:
  - `mistralai/mistral-small-2603` (Small 4): $0.15 / $0.60.
  - `mistral-medium-3-5`: $1.50 / $7.50.
  - `gpt-oss-120b`: $0.037 / $0.17.
  - `llama-4-maverick`: $0.19 / $0.65.
  The OpenRouter Gemini, OpenAI and Haiku prices match first-party.
- **Vals Finance Agent v2** is the closest public proxy to our task. It has 927 expert-reviewed
  questions on public-company filings, and the page is dated 2026-10-07
  ([Vals FAB v2](https://www.vals.ai/benchmarks/fabv2)). Accuracy and cost per test:
  - Gemini 3.8 Flash: 61.44%, $2.00 (rank 2 of 76).
  - Gemini 3.7 Flash: 59.04%, $1.48.
  - GPT-5.6 Luna: 55.04%, $0.28.
  - Mistral Large 4: 54.68%, $1.20.
  - Haiku 5.5: 54.14%, $1.64.
  - DeepSeek V4.1 Flash: 53.48%, $0.21.
  - Qwen 3.8 Max: 50.59%, $1.24.
  - GPT-6 Luna: 49.87%, $0.12.
  - Qwen 3.8 27B: 48.55%, $0.75.
  - **Gemini 3.5 Flash-Lite (our current model): 47.44%, $0.39.**
  - GPT-5.4 mini: 45.36%, $1.20.
  - GPT-5.4 nano: 38.22%, $0.16.
  - Mistral Medium 3.5: 32.10%, $1.91.
  - Gemini 3.1 Flash-Lite Preview: 29.99%, $0.14.
  - gpt-oss and Llama are not listed. The page doesn't say which effort level each model ran at.
- **Google's own 3.8 Flash page** cites the same Finance Agent v2 figure, 61.4%
  ([Gemini Flash](https://deepmind.google/models/gemini/flash/)). The 3.5 Flash-Lite model page has
  no tool-use or finance row. On long context it leads its peers on GDM-MRCR v2 (8-needle) at 128K:
  - 3.5 Flash-Lite: 72.2%.
  - 3.1 Flash-Lite: 60.1%.
  - GPT-5.4 mini: 42.7%.
  - Haiku 4.5: 35.3%.
  At 1M pointwise, 3.5 Flash-Lite scores 21.3% and 3.1 Flash-Lite 12.3%. The page is undated
  ([Gemini Flash-Lite](https://deepmind.google/models/gemini/flash-lite/)).
- **Artificial Analysis Intelligence Index.** AA is a secondary aggregator, not a benchmark owner,
  and its pages are undated. Index score and cost per index task
  ([AA leaderboard](https://artificialanalysis.ai/leaderboards/models)):
  - Haiku 5.5 (max): 43, $0.21.
  - Gemini 3.8 Flash (high): 41, $1.24.
  - Qwen3.8-Flash-Next: 40, $0.37.
  - DeepSeek V4.1 Flash (max): 39, $0.27.
  - GPT-6 Luna (max): 38, $0.07.
  - Gemini 3.5 Flash-Lite: 22, $0.19.
  - Mistral Medium 3.5: 14, $0.50.
  - gpt-oss-120b (high): 12, $0.11.
  - Mistral Small 4: 11, $0.02.
  The model pages show that verbosity and latency differ widely between models:
  - Haiku 5.5 (max) used 440M output tokens on the index, with a 306 s time to first token
    ([AA Haiku 5.5](https://artificialanalysis.ai/models/claude-haiku-5-5)).
  - GPT-6 Luna (max) used 140M, with 104 s
    ([AA GPT-6 Luna](https://artificialanalysis.ai/models/gpt-6-luna)).
  - 3.5 Flash-Lite used 59M, with 8.7 s
    ([AA 3.5 FL](https://artificialanalysis.ai/models/gemini-3-5-flash-lite)).
  AA's tau2 and AA-LCR pages didn't expose per-model figures for our candidates in text.
- **The tool-calling leaderboards don't cover current candidates.** BFCL V4 is dated 2026-04-12. Its
  newest small models are Haiku 4.5, GPT-5-mini/nano and Gemini 2.5 Flash/Flash-Lite, and none of
  the 2026 candidates appear
  ([BFCL](https://gorilla.cs.berkeley.edu/leaderboard.html), data from `data_overall.csv`). Two
  older data points show that Flash-Lite-class models were weak at multi-turn tool use:
  - Gemini 2.5 Flash-Lite (FC): 36.87% overall, 13.5% multi-turn.
  - Haiku 4.5 (FC): 68.70% overall, 53.62% multi-turn.
  [τ-bench's site](https://taubench.com/) shows only the top 3 per benchmark. None of our
  candidates are among them except Qwen 3.8 Max, which leads τ³-Banking at 55.2%. The vendor
  pages for Haiku 5.5 and 3.5 Flash-Lite publish no τ²-bench row.
- **Forced named tool call support on each first-party API:**
  - **Gemini:** yes. Use mode `any` with `allowed_tools`. Thinking isn't listed as a restriction
    ([function calling](https://ai.google.dev/gemini-api/docs/function-calling)).
  - **OpenAI:** yes. `tool_choice: {"type":"function","name":…}`
    ([function calling](https://developers.openai.com/api/docs/guides/function-calling)).
    Chat Completions doesn't support function calling on GPT-6 Astra or 6.1 Sol; the docs say
    nothing restricting Luna.
  - **Anthropic, Haiku 5.5:** yes. `tool_choice` `tool` or `any` is accepted, but "a forced call
    skips thinking" ([define tools](https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools)).
    Opus 5.5, Sonnet 5.5 and Fable 5.1 reject forced tool use with a 400.
  - **DeepSeek:** a named function and `required` exist but "are not supported in thinking mode"
    and return a 400 ([chat API](https://api-docs.deepseek.com/api/create-chat-completion)).
  - **Qwen:** named function yes. `required` is not supported in thinking mode
    ([Qwen function calling](https://www.alibabacloud.com/help/en/model-studio/qwen-function-calling)).
  - **Mistral:** `any`, `auto` and `none` only. There is no named function
    ([Mistral function calling](https://docs.mistral.ai/capabilities/function_calling/)).

### Cost per eval run

`cost = calls × (in_tokens × in_price + out_tokens × out_price) / 1e6`

The prices are per 1M tokens.
- `out_tokens` must include thinking or reasoning tokens. Every provider below bills them as
  output.
- With caching, split the input term: `(cached_in × cache_price + uncached_in × in_price)`.
- Batch halves both prices on Gemini, OpenAI, Anthropic and Mistral. For the multi-turn agent loop
  it only fits the judge step (see Inference above).
- Per-token price alone misranks reasoning models, because `out_tokens` varies several-fold by
  model and effort (see AA verbosity above). Measure `out_tokens` for each candidate.

| Model (API id) | in $/M | out $/M | thinking billed as output? | forced named tool call? | key scores (date) |
|---|---|---|---|---|---|
| `gemini-3.5-flash-lite` (current) | 0.30 | 2.50 | yes | yes (`any` + allowed) | Finance Agent v2 47.44%, $0.39/test (10-07); AA 22; MRCR 128K 72.2% |
| `gemini-3.1-flash-lite` | 0.25 | 1.50 | yes | yes | Finance Agent v2 29.99% (preview) (10-07); MRCR 128K 60.1% |
| `gemini-3.8-flash` | 0.75 (1.50 from 2027) | 3.75 (7.50 from 2027) | yes | yes | Finance Agent v2 61.44%, $2.00/test (10-07); AA 41 (high) |
| `gpt-6-luna` | 0.10 | 0.50 | yes | yes | Finance Agent v2 49.87%, $0.12 (10-07); AA 38 (max) |
| `gpt-5.6-luna` | 0.20 | 1.20 | yes | yes | Finance Agent v2 55.04%, $0.28 (10-07) |
| `gpt-5.4-mini` / `-nano` | 0.75 / 0.20 | 4.50 / 1.25 | yes | yes | Finance Agent v2 45.36% / 38.22% (10-07) |
| `claude-haiku-5-5` (≤100K prompt) | 0.10 | 0.50 | yes | yes, skips thinking | Finance Agent v2 54.14%, $1.64 (10-07); AA 43 (max) |
| `deepseek-flash` (V4.1) | 0.30 peak / 0.15 off-peak | 1.20 / 0.60 | ? (reasoning_tokens reported, billing unstated) | not in thinking mode | Finance Agent v2 53.48%, $0.21 (10-07); AA 39 (max) |
| `qwen3.8-flash` | 0.15 | 0.47 | n/a (single price) | yes (named) | AA 40 (Flash-Next, possibly a different id) |
| `mistral-small-2603` (Small 4, via OR) | 0.15 | 0.60 | ? | `any` only | AA 11 |
| Mistral Large 4 (first-party) | 0.50 | 1.50 | ? | `any` only | Finance Agent v2 54.68%, $1.20 (10-07) |
| `gpt-oss-120b` (OR only) | 0.037 | 0.17 | ? | via OR, per provider | AA 12 (high) |
| `llama-4-maverick` (OR only) | 0.19 | 0.65 | n/a | via OR | BFCL 37.29% (old, 2026-04-12 page) |

### Inference (not stated by sources)

- **Benchmarks are a weak proxy for our task.** Our task is narrow: a 48-question exact-figure and
  citation eval through our own retrieval tools. Finance Agent v2 is the closest public analogue,
  but its harness, tools and grading differ, and its effort settings aren't stated. A targeted run
  of our own eval decides this, on the same ~10 question ids for each candidate, after the
  noise-floor rerun in Open question 7 above.
- **Within Gemini, 3.8 Flash is the accuracy step-up.** It scores +14 points over 3.5 Flash-Lite on
  Finance Agent v2, at 2.5× input and 1.5× output price, falling to ~5× / 3× in 2027. It needs
  only a model-id change: same SDK, tool declarations and `any` forced-call path. 3.1 Flash-Lite is
  cheaper but clearly weaker, so it isn't worth piloting.
- **Outside Gemini, GPT-5.6 Luna and DeepSeek V4.1 Flash look best per dollar on the finance
  proxy.** Each scores ~53–55% at ~$0.2–0.3 per test, versus 3.5 Flash-Lite's 47% at $0.39. GPT-6
  Luna is the cheapest per token, but it scored lower than 5.6 Luna on Finance Agent v2.
  - DeepSeek's forced-call path breaks in thinking mode. Our forced-tool step would have to run
    non-thinking, so the measured score may not carry over.
  - DeepSeek's peak and off-peak pricing makes run cost depend on the time of day.
- **Haiku 5.5 is cheap per token but verbose and slow at high effort.** On Finance Agent v2 it costs
  $1.64 per test against GPT-5.6 Luna's $0.28 at a similar score. Its 306 s time to first token at
  max effort would hurt a multi-call loop, so it would need a low or medium effort setting and its
  own measurement.
- **Switching cost.**
  - Gemini → Gemini: change the pinned id and re-baseline.
  - Any other family needs:
    - a new client (OpenAI SDK, Anthropic SDK or an OpenAI-compatible API), plus tool-schema
      translation;
    - per-provider forced-call semantics (see the table);
    - a new provenance field and a full re-baseline of the 48 questions;
    - probably prompt tuning.
  - The earlier "Forced tool calls aren't portable" point applies directly.
- **Rough cost scale**, for orientation only. It uses the earlier section's guessed 6K input and
  400 output tokens per call, and thinking is not included:
  - 3.5 Flash-Lite: ~$0.0028/call.
  - 3.8 Flash: ~$0.006/call.
  - GPT-5.6 Luna: ~$0.0017/call.
  - Haiku 5.5 and GPT-6 Luna: ~$0.0008/call.
  Even 250 calls on 3.8 Flash is about $1.5 per run, so price matters less than accuracy and
  switching cost at our volume. Replace with measured tokens.

**Shortlist to pilot (inference, ranked):**
1. **`gemini-3.8-flash`**: highest finance-proxy score and zero switching cost. Note the 2027 price
   rise.
2. **`gpt-5.6-luna`**: strongest score per dollar on Finance Agent v2, with clean named-function
   forcing. Costs a new client.
3. **`deepseek-flash` (V4.1)**: similar score at lower cost. Pilot only if our forced-call step works
   in non-thinking mode.

### Open questions

1. Real `in_tokens` and `out_tokens` per call (including thinking) on each candidate. The main
   session is measuring these on 3.5 Flash-Lite.
2. Which effort or thinking level did Vals use for each Finance Agent v2 entry, and which level
   would we run?
3. Does GPT-6 Luna or 5.6 Luna support function calling on Chat Completions, or only on
   Responses? The docs restrict only Astra and 6.1 Sol.
4. Does DeepSeek bill reasoning tokens at the output rate? The pricing page doesn't say.
5. Can Qwen's named `tool_choice` be used in thinking mode? Only `required` is documented as
   unsupported.
6. Are there current tau2-bench or BFCL scores for 2026 small models? Neither leaderboard showed
   them. Check sierra-research's full table or the vendor system cards.
7. What are Mistral's first-party Small 4 and Medium 3.5 prices? Its pricing page lists only Large.
8. Does 3.8 Flash's 2027 price ($1.50 / $7.50) change the ranking once real tokens are known?

## Measured usage and cost per run (added 2026-10-09, main session)

**Measured.** 5 eval questions were run live through the real agent on 2026-10-09: `crm-rpo-fy26`,
`aapl-msft-employee-comparison`, `pltr-government-contract-risk`, `nvda-asset-turnover-fy2026`
and `five-company-gross-margin-ranking-fy2025`. A throwaway wrapper recorded each call's
`usage_metadata`; the repo code was unchanged. That gave 17 calls.

- `model_version` was `gemini-3.5-flash-lite` on every call, so this is what
  `gemini-flash-lite-latest` resolves to on 2026-10-09.
- 3.4 LLM calls per question. The trace log (`var/trace_logs/traces.jsonl`, 506 Gemini runs
  since 2026-10-01) gives 3.37 tool calls per run, which agrees.
- Input: 7,884 tokens per call on average. The first call is 5,735; later calls reach 13,880 as
  the chat history grows.
- Output: 184 tokens per call on average, 1,177 at most (a long judged answer). No thinking tokens
  were reported.
- 53% of input tokens came back as implicit cache hits (`cached_content_token_count`).
- A full run is about 48 × 3.4 ≈ 163 agent calls plus the judged-question calls. That is below
  the "about 250" in `live-eval-verification.md`; recheck that figure.

**Cost per full 48-question run (inference).** Judge calls are excluded. The calculation assumes
cache hits are billed at the context-caching rate: 3.5 Flash-Lite $0.03, 3.8 Flash $0.075, and
the OpenAI cached rate at 0.1× input. The caching page doesn't say explicitly that implicit hits
are billed at those rates. It also assumes each model produces the same tokens we measured; a
model that thinks will produce more output.

| Model | $/call | $/run (163 calls) |
|---|---|---|
| gemini-3.5-flash-lite | 0.0017 | ~0.28 |
| gemini-3.8-flash (to 2026-12-31) | 0.0038 | ~0.62 |
| gemini-3.8-flash (from 2027-01-01) | 0.0076 | ~1.23 |
| gpt-5.6-luna (plus any reasoning tokens) | 0.0010 | ~0.17 |

Every candidate costs under about $1.25 per full run. At this volume, cost does not decide the
choice: accuracy on our own eval and switching cost do.

**Checks against primary sources (2026-10-09):**
- The Vals Finance Agent v2 figures quoted above match `vals.ai/benchmarks/fabv2` ("Updated
  10/7/2026").
- Vals lists 3.8 Flash at $1.5 / $7.5, which is the 2027 list price, so its $2.00 per test
  overstates today's cost.
- The page's own prose disagrees with its table about who ranks first: Gemini 4 Argon is 65.40% in
  the table.
- The 3.8 Flash $0.75 / $3.75 rate, rising to $1.50 / $7.50 on 2027-01-01, matches
  `ai.google.dev/gemini-api/docs/pricing`.
