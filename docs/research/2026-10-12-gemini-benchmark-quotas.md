Feeds ticket "Gemini quota and model facts" in [docs/plans/2026-10-12-agent-vs-raw-llm-benchmark-map.md](../plans/2026-10-12-agent-vs-raw-llm-benchmark-map.md).

# Gemini quotas, release dates and Search grounding for the agent vs. raw LLM benchmark (research, 2026-10-12)

Fetched 2026-10-12 with WebFetch (page to markdown, then summarized by a small model, so quotes are the summarizer's extraction, not verbatim page dumps). Only ai.google.dev pages were read successfully. The Vertex AI model pages returned navigation only (body truncated). The google-genai SDK source was not read.

## Findings

1. **Free-tier RPM/TPM/RPD for both models are not published in the docs.** The rate-limits page says limits vary by model and to "View your active rate limits in AI Studio." Only batch enqueued-token limits are listed for these models (Tiers 1-3, not free). So the TPM-throttles-100K-prompts question cannot be answered from docs.
2. **Free tier exists for both models.** Pricing lists input and output (incl. thinking) as "Free of charge" on the Free Tier for both.
3. **Grounding with Google Search is "Not available" on the Free Tier for both models.** Paid tier: 5,000 free search requests/month shared across all Gemini 3+ models, then $14 per 1,000 search requests (charged per search query the model runs). B2 therefore needs billing enabled.
4. **Release dates.** `gemini-3.5-flash-lite` GA 2026-07-21 (changelog entry "Gemini 3.6 Flash and Gemini 3.5 Flash-Lite generally available"); no preview entry found on the changelog. `gemini-3.8-flash` released 2026-09-02, listed "New Stable"; no preview entry. On 2026-10-08 `gemini-3.7-flash` was deprecated and routed to `gemini-3.8-flash`.
5. **Knowledge cutoff: not stated** on the models overview, either model page, or the model-versions page (no cutoff table anywhere on ai.google.dev). Vertex pages unread.
6. **Pinned IDs.** Both are listed as a single "Stable" ID with no preview or "-latest" variant: `gemini-3.5-flash-lite`, `gemini-3.8-flash`. Docs say stable models "usually don't change" and production apps should pin a stable model. Only "latest" aliases (e.g. `gemini-flash-latest`) are hot-swapped, with 2 weeks' email notice for breaking changes. The deprecations page gives no shutdown date for either model; stated shutdown dates are earliest-possible, with advance notice.
7. **`modelVersion`** is a field on GenerateContentResponse ("The model version used to generate the response"), as are `responseId` and `usageMetadata`.
8. **Search + JSON schema in one call:** the structured-output page says Gemini 3 series models can combine Structured Outputs with built-in tools including Google Search, labeled "Preview" and shown with `gemini-3.1-pro-preview`. Neither target model is named there.
9. **Grounding metadata (generateContent API reference):** `groundingMetadata` has `webSearchQueries`, `groundingChunks` (web/image/file/Maps), `groundingSupports` (`groundingChunkIndices`, `confidenceScores`, `segment` with partIndex/startIndex/endIndex/text), `searchEntryPoint`, `retrievalMetadata`. The Search docs page documents only the Interactions API shape: `google_search_call` (queries), `google_search_result` (`search_suggestions`), `url_citation` annotations with start/end index and URL.

## Sources say vs. inference

Sources say: items 1-9 above.

Inference (mine):
- With no published free-tier TPM, a 100K+ token B3 prompt may be throttled; Flash-Lite at 2,950 calls over ~10-14 days implies about 210-295 calls/day, so the RPD must be checked in AI Studio before fixing the schedule.
- B2 cannot run free. Either enable billing (cost is small: 5,000 free searches/month cover the benchmark if each call runs about 1-2 queries, but exceeding it costs $14/1,000), or drop B2 / run it on a paid project only. Billing-enabled projects also change data-use terms (billing page: paid usage not used to improve products), which is worth recording.
- Because aliases are absent for these models, the bare IDs are the pin. Log `modelVersion` and `responseId` per call, and for B2 log `webSearchQueries`, `groundingChunks` URIs and `groundingSupports` so reruns are comparable.
- The unstated knowledge cutoff means contamination of SEC filings cannot be bounded from docs; ask the models or treat as unknown.

## Open questions (not settled)

- Exact free-tier RPM, TPM, RPD for both models: visible only in AI Studio (https://aistudio.google.com/rate-limit). Check there before locking the run plan, including whether TPM blocks a 100K+ prompt.
- Official knowledge cutoff: Vertex AI pages (docs.cloud.google.com/vertex-ai/generative-ai/docs/models/gemini/3-5-flash-lite and 3-8-flash) were truncated to navigation; re-check manually.
- Whether `modelVersion` returns a dated/pinned string versus the bare ID for these models (needs one live call).
- Whether the Search + JSON-schema combination works on 3.5 Flash-Lite and 3.8 Flash in generateContent (needs one live call on a paid project).
- Preview release dates: none found in the changelog; the Flash-Lite GA entry title is combined with "3.6 Flash".
- google-genai SDK source not inspected for the `grounding_metadata` field names.

## Sources

- https://ai.google.dev/gemini-api/docs/rate-limits
- https://ai.google.dev/gemini-api/docs/models
- https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite
- https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash
- https://ai.google.dev/gemini-api/docs/models/gemini
- https://ai.google.dev/gemini-api/docs/changelog
- https://ai.google.dev/gemini-api/docs/deprecations
- https://ai.google.dev/gemini-api/docs/pricing
- https://ai.google.dev/gemini-api/docs/billing
- https://ai.google.dev/gemini-api/docs/google-search
- https://ai.google.dev/gemini-api/docs/structured-output
- https://ai.google.dev/api/generate-content

## Addendum: AI Studio rate-limit data (main session, 2026-10-12)

Source: a HAR capture of `aistudio.google.com/rate-limit` that the user saved on 2026-10-12. It
contains the `ListModelRateLimits`, `ListQuotaModels` and `ListModels` RPC responses. The tier
code mapping is inferred: tier 20 is free, because 3.5 Flash-Lite's 500 RPD there matches the
known free quota, and tier 30 is paid Tier 1.

**Limits (free tier / paid Tier 1):**

| Model (quota group) | Free RPM | Free TPM | Free RPD | Tier 1 RPM | Tier 1 TPM | Tier 1 RPD |
|---|---|---|---|---|---|---|
| gemini-3.5-flash-lite | 15 | 250,000 | 500 | 4,000 | 4,000,000 | 150,000 |
| gemini-3.8-flash | **5** | 250,000 | **20** | 1,000 | 2,000,000 | 10,000 |
| gemini-3.1-flash-lite (separate pool) | 15 | 250,000 | 500 | 4,000 | 4,000,000 | 150,000 |
| gemini-3.6-flash / 3.7-flash (each) | 5 | 250,000 | 20 | 1,000 | 2,000,000 | 10,000 |
| gemma-4-31b (`gemma-4-31b-it`) | 30 | 16,000 | 14,400 | 30 | 16,000 | 14,400 |
| gemma-4-26b (`gemma-4-26b-a4b-it`) | 30 | 16,000 | 14,400 | 30 | 16,000 | 14,400 |
| deep-research-pro-preview | 0 | 0 | 0 | 1 | 500,000 | 1,440 |

**Model IDs and versions (from `ListQuotaModels` and `ListModels`):**
- `gemini-3.5-flash-lite` reports version `3.5-flash-lite-07-2026`, with a 1,048,576-token input
  window and a launch timestamp of 2026-07-21. The moving alias `gemini-flash-lite-latest`
  currently maps to it. **The project default is that alias** (`config.py:65`,
  `.env.example:17`), so Q17's pinning means setting `GEMINI_MODEL_NAME=gemini-3.5-flash-lite`.
- The alias `gemini-flash-latest` currently maps to `gemini-3.8-flash`.
- `gemma-4-31b-it` reports version `001`. It is open-weight and dense, with a 262,144-token input
  window. Its methods are `generateContent` and `countTokens` only: no caching, no batch.
- Neither `ListModels` nor the docs carry a knowledge-cutoff field.

**Inference (mine):**
- **B3 fits the free tier.** At 250K TPM, a 100K+-token whole-filing prompt allows about 2
  calls a minute, so a 104-question B3 run takes roughly an hour, alone on the key.
- **3.8 Flash's 20 RPD breaks two Round 2 decisions.** B1 at 3 runs × 104 questions is 312
  calls, about 16 days of its free quota on its own, and the 3.8 Flash judge (Q9) draws from the
  same 20 a day. See Q21 in the decisions file.
- **Gemma 4 31B is the only free model with headroom** that isn't a sibling of the agent's model.
  Its 16K TPM fits judge prompts (a few thousand tokens each), not whole filings. Unverified:
  whether it accepts a system instruction and JSON output through the Gemini API; check with one
  live call.

## Addendum: live feasibility probes (main session, 2026-10-12)

**Setup.** All calls used the paid project's key at temperature 0, with google-genai 2.18.1. The
throwaway script lived in the session scratchpad and isn't kept.

**Spend.**
- 9 generation calls of under 500 tokens each, so under $0.01.
- 5 grounded calls, out of 5,000 free searches a month.
- 139 `countTokens` calls, which are free.

**Search grounding vs. JSON output**, on two NVIDIA revenue questions:
- FY2026, filed 2026-02-25, before 3.5 Flash-Lite's release.
- Q2 FY2027, filed 2026-08-26, after the release.

| Config (3.5 Flash-Lite) | Answer | `grounding_metadata` |
|---|---|---|
| no tools + response schema (B0) | declined (`refused: true`), both questions | n/a |
| Search + response schema | correct figure, valid schema JSON | **absent** |
| Search + JSON instruction, no schema | correct figure, inside a ```` ```json ```` fence, value as a string | **absent** |
| Search, plain prose | correct figure ($96,221M, matches the 10-Q's tables) | present: 2 chunks (nvidia.com, tradingview.com), supports with segment spans |

**What the probes show:**
- The search runs in every Search config. The post-release figure can't come from training,
  and the same model without tools declined it.
- Grounding metadata comes back **only when the output is plain prose**. Any JSON output,
  schema or instruction, drops it.
- The instruction-only JSON needed fence stripping and returned the value as a string.
- `usage_metadata` showed no `tool_use_prompt_token_count` in any config.

**`modelVersion`:**
- It returns the resolved model ID, not a dated version. A request for the alias
  `gemini-flash-lite-latest` came back as `gemini-3.5-flash-lite`.
- So a served-model check catches alias drift. It can't see a silent update behind the same
  stable ID; no finer version is exposed.
- 3.8 Flash spends thinking tokens even on a one-word reply (81 for "OK"). 3.5 Flash-Lite
  reported none.

**Filing sizes** (`countTokens`, text plus tables rendered as `a | b | c` rows, 139 filings):

| Form | n | min | median | max |
|---|---|---|---|---|
| 10-K | 29 | 64,893 | 112,805 | 488,748 |
| 10-Q | 110 | 23,681 | 79,855 | 377,683 |

- All 20 BAC and JPM filings exceed 250K tokens: 10-Qs run 277K–378K and 10-Ks 437K–489K.
  Every other filing is under it.
- Every filing fits the 1,048,576-token window.

**Inference (mine):**
- A single BAC or JPM whole-filing call exceeds the free tier's 250K TPM by itself, so it
  can't run on the free tier at any pace.
- Multi-company B3 prompts exceed 250K for most pairs: two median 10-Ks are already about 226K.
- B3 on the paid tier at about 100–150K average tokens per question and $0.30/M input is roughly
  $3–5 per 104-question run, more than the $5 credit allows for repeats.
