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
