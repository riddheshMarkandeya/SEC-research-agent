# Placeholder values in optional claim fields

Date: 2026-09-28
Question: why `submit_answer` claims get placeholder `value`/`unit` fields, and which fix to use: (a) a schema
split or union, (b) a verifier-side downgrade, or (c) both.
Feeds: the fix for qualitative citations that the verifier refuses because they carry invented numbers.

## Question

Gemini (`gemini-3.5-flash-lite` through `google-genai` 2.18.1) often puts placeholder numbers into the optional
`value`/`unit` fields of qualitative claims. Examples: `value: 2025` for the quote "As of December 31,2025",
`value: 10` for "Condensed Consolidated Balance Sheets", and `unit: "raw"` with a null `value`. It does this even
though rule 9 says "OMIT value and unit together; never invent a placeholder number". The verifier then refuses the
answer. This note answers three questions:

1. Can Gemini function declarations express `anyOf`/`oneOf`, nullable types or discriminated unions? What limits
   are documented?
2. What do Google, Anthropic and OpenAI docs say about optional fields, and about models inventing values for them?
3. Is there published evidence that LLMs hallucinate values for optional or conditional tool-call fields?

## Findings (what the sources say)

### 1. Gemini schema support for unions and nullability

- **The two Gemini doc sets disagree about the function-declaration subset.**
  - The Gemini API function-calling guide only says: "Only a [subset of the OpenAPI schema] is supported. For
    `any` mode, the API may reject very large or deeply nested schemas." Its "Function declarations" section lists
    only `type`, `properties` and `required`. https://ai.google.dev/gemini-api/docs/function-calling
    ("Notes and limitations", "Function declarations")
  - Google Cloud's function-calling page (Gemini Enterprise Agent Platform, formerly Vertex) is explicit:
    "Function declarations are compatible with the OpenAPI schema. We support the following attributes: type,
    nullable, required, format, description, properties, items, enum, anyOf, $ref, and $defs. Remaining attributes
    are not supported." It also says "The maximum depth of nested schema is 32."
    https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/tools/function-calling ("Function
    schema examples")
  - `oneOf` is not on that list, and neither is `additionalProperties`.
- **The SDK has fields for `anyOf` and `nullable` in the `parameters` Schema.**
  - The installed `google-genai` 2.18.1 `types.Schema` includes `any_of` ("The instance must be valid against any
    (one or more) of the subschemas listed in `any_of`"), `nullable` ("Indicates if the value of this field can be
    null"), `additional_properties`, `ref`/`defs` and `property_ordering`.
    https://github.com/googleapis/python-genai/blob/main/google/genai/types.py (`class Schema`)
  - `FunctionDeclaration` also has `parameters_json_schema`, which is "mutually exclusive with `parameters`" and
    whose own example uses `additionalProperties: false`. Same file, `class FunctionDeclaration`.
  - The SDK's schema transformer rewrites `{"anyOf": [X, {"type": "null"}]}` as `X` plus `nullable: true`. It
    handles `any_of` but not `one_of` ("'any_of', # 'one_of', 'all_of', 'not' to come").
    https://github.com/googleapis/python-genai/blob/main/google/genai/_transformers.py and `types.py`
- **The JSON Schema path treats `oneOf` like `anyOf`.** The SDK docstring for `response_json_schema` lists the
  supported keywords as "`$id` `$defs` `$ref` `$anchor` `type` `format` `title` `description` `enum` `items`
  `prefixItems` `minItems` `maxItems` `minimum` `maximum` `anyOf` `oneOf` (interpreted the same as `anyOf`)
  `properties` `additionalProperties` `required`". https://github.com/googleapis/python-genai/blob/main/google/genai/types.py
  (`GenerateContentConfig.response_json_schema`)
  - That docstring covers response schemas. It says nothing about `parameters_json_schema` for function calls.
- **The structured-output guide documents nullable type arrays and `anyOf`.**
  - "To allow a property to be null, include `"null"` in the type array (e.g., `{"type": ["string", "null"]}`)."
  - It has a worked example "showcas[ing] `anyOf` for conditional schemas".
  - It lists `additionalProperties` under object keywords.
  - Limitations: "Not all JSON Schema features are supported" and "Very large or deeply nested schemas may be
    rejected."
  - https://ai.google.dev/gemini-api/docs/structured-output ("JSON schema support", "Limitations")
- **Google's 2025-11-05 announcement names the response-schema keywords.** It lists `anyOf`, `$ref`,
  `minimum`/`maximum`, `additionalProperties`, `type: 'null'` and `prefixItems` "across all actively supported
  Gemini models". It is about response schemas. https://blog.google/innovation-and-ai/technology/developers-tools/gemini-api-structured-outputs/
- **Neither Google doc set documents discriminated unions** (a `discriminator` or `const` tag). `const` is absent
  from every keyword list above.
- **Function calling and response schemas have been reported to diverge.** A 2025 forum thread reports different
  `nullable` semantics (an array form documented for function calling returned HTTP 400) and inconsistent `type`
  casing. Google staff acknowledged the report and gave no fix.
  https://discuss.ai.google.dev/t/schema-used-in-functioncalling-and-responseschema-diverges/69272
- **Nullability can decide whether a model invents a value (community report, not a primary spec).**
  - A proxy project found that stripping nullability from Gemini response schemas (`anyOf[..., null]` → plain
    type) meant "the model answers `"null"` or invents a value".
  - The report also says flattening is "appropriate for tool parameters" in their proxy.
  - https://github.com/diegosouzapw/OmniRoute/issues/12308
- **The mode names in the Gemini API guide differ from the SDK enum's.** The guide lists `validated`: "Model ensures
  function schema adherence." https://ai.google.dev/gemini-api/docs/function-calling ("Function calling modes")
  - The SDK enum describes `VALIDATED` only as "constrained to predict either function calls or natural language
    response", and `ANY` as "constrained to always predicting function calls". https://github.com/googleapis/python-genai/blob/main/google/genai/types.py
    (`FunctionCallingConfigMode`)
  - Neither source says whether argument values are grammar-constrained to the declared schema.

### 2. Vendor guidance on optional fields and invented values

- **OpenAI (strict structured outputs) makes every field required and expresses "optional" as nullable.**
  - "Although all fields must be required (and the model will return a value for each parameter), it is possible to
    emulate an optional parameter by using a union type with `null`." Its example uses
    `"type": ["string", "null"], "enum": [..., null]`.
  - "The model will always try to adhere to the provided schema, which can result in hallucinations if the input is
    completely unrelated to the schema. You could include language in your prompt to specify that you want to
    return empty parameters."
  - "Root objects must not be `anyOf`". Nested `anyOf` is supported.
  - "outputs will be produced in the same order as the ordering of keys in the schema."
  - https://developers.openai.com/api/docs/guides/structured-outputs ("All fields must be required", "Handling
    user-generated input", "Key ordering")
- **Anthropic documents value-guessing for missing parameters.**
  - "Claude Opus is much more likely to recognize that a parameter is missing and ask for it. Claude Sonnet might
    ask… But it might also infer a reasonable value." https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview
    ("When required parameters are missing")
  - It recommends `input_examples`, which "helps Claude understand when to include optional parameters". Its
    example includes one call that omits the optional `unit`.
    https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools ("Providing tool use examples")
  - Strict mode guarantees conformance to the schema, not correct values: "Without strict mode, Claude might return
    incompatible types … or omit required fields." https://platform.claude.com/docs/en/agents-and-tools/tool-use/strict-tool-use
- **Google's function-calling best practices cover descriptions, strong types and temperature.**
  - Use clear parameter descriptions, "Use strong typed parameters… add an enum field", and prompt instructions
    such as "Don't make assumptions".
  - "For the temperature parameter, use 0 or another low value … reduces hallucinations."
  - https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/tools/function-calling ("Best practices
    for function calling")
  - The Gemini 3 guide says the opposite about temperature: "For all Gemini 3 models, we strongly recommend keeping
    the temperature parameter at its default value of `1.0` … setting it below 1.0 may lead to unexpected behavior,
    such as looping or degraded performance." https://ai.google.dev/gemini-api/docs/gemini-3 ("Temperature")
  - Both Gemini guides add: "always validate values in your application" and "Implement robust error handling for
    schema-compliant but semantically incorrect outputs."
    https://ai.google.dev/gemini-api/docs/structured-output ("Best practices")
- **No vendor doc found recommends an enum `"none"` sentinel or separate arrays for optional values.** OpenAI's
  nullable-enum example (`enum: [..., null]`) is the closest documented pattern.

### 3. Published evidence of hallucinated argument values

- **HammerBench (arXiv 2412.16516), §5.2:** "user query with missing arguments can easily lead to parameter
  hallucinations. In these cases, LLMs tend to fill in missing arguments based on their internal model of the
  world."
  - §5.3: the hallucination rate "in the initial snapshot, where the context is incomplete, is significantly higher".
  - https://arxiv.org/html/2412.16516
- **ToolACE (arXiv 2409.00920), §3:** it treats this as a class of error to filter out, with a check that "Identifies
  whether the values of input parameters in function calls are fabricated—not mentioned in either the user query
  or the system prompt." https://arxiv.org/html/2409.00920v1
- **"Getting the Parameters Right" (Yu et al., arXiv 2608.03071, Aug 2026)** names "Conditional Dependencies" as a
  hard category: "Some parameters are required, or take constrained values, only when a sibling parameter takes a
  specific value".
  - Such rules "live in human-readable field descriptions, and the model must infer which shape the current
    situation calls for".
  - Across 7 frontier models, "only 2.1% of their failed calls violate the schema, while the others are schema-valid
    but value-wrong."
  - https://arxiv.org/html/2608.03071
- None of these papers measures placeholder filling for optional numeric fields specifically. The closest evidence
  is the missing-argument and conditional-field results above.

## Repo facts

- **The claim schema.** `prompts/agent_tools.py:190-257` (`SUBMIT_TOOL_SCHEMA`).
  - Claim items have optional `value` (number) and `unit` (enum `CLAIM_UNITS`, line 188).
  - `citation_index` and `quote` are required, and `additionalProperties` is false.
  - Property order is `value`, `unit`, `citation_index`, `quote`, so `value` is declared before the quote it must
    come from.
- **What Gemini receives.** `llm_backends.py:257-291` sends the schema through the OpenAPI-subset `parameters`
  field, not `parameters_json_schema`.
  - `_strip_additional_properties` removes `additionalProperties` recursively because the docstring says Gemini's
    Schema "doesn't support that keyword at all".
  - The installed SDK's `Schema` now has an `additional_properties` field, and the structured-output guide lists
    `additionalProperties`. The Cloud function-calling list above still omits it.
- **Temperature and forced calls.** `llm_backends.py:381` sets `temperature=0.1`. Lines 351-371 force
  `submit_answer` with `mode=ANY` + `allowed_function_names` on the forced turn.
- **The runtime validator can already check unions.** `agent.py:276-346` (`validate_tool_args`) uses
  `jsonschema.Draft202012Validator` on the unstripped schema, so it would enforce `anyOf`/`oneOf`/`const` without
  changes.
  - It already treats an explicit null on a declared property as absent (docstring, lines 318-330).
- **How the verifier routes a claim.** `agent.py:1461-1494` (`_verify_one_claim`):
  - value and unit both absent → `_verify_qualitative_claim` (the quote must be found in the source);
  - exactly one present → `malformed_claim`;
  - both present → `_verify_numeric_claim` (the value must be in the quote).
  - So `unit: "raw", value: null` is refused as malformed, and `value: 2025`/`value: 10` fail numeric grounding.
- **The coverage check.** `agent.py:1590-1700` (`verify_claims`) requires every number in `answer_text` to match a
  normalized claimed `(value, unit)` within `max(1%, 0.05)`.
  - It first strips `_NON_CLAIM_PATTERN` (dates, bare years, 10-K/10-Q, Note N…) and citation brackets.
  - A claimed value that matches no answer number covers nothing.
- **The prior decision rejected `oneOf`.** `docs/decisions/2026-09-15-qualitative-claims-schema.md` (commit
  `06ca03f`) made value/unit optional. Its reason for rejecting `oneOf`, and `dependentRequired` for the same
  reason, was that "this codebase uses no `oneOf`/`anyOf` in any tool schema today and Gemini's function-calling
  schema translation is already known to reject some standard JSON-Schema features … building on another
  unverified, more exotic schema feature was an avoidable risk."

## Inferences (mine, not the sources')

1. **The findings answer the 2026-09-15 `oneOf` rejection's premise.** Google Cloud's docs and the SDK now document
   `anyOf` and `nullable` for function declarations. `oneOf` is still undocumented on the `parameters` path, and it
   is only "interpreted the same as `anyOf`" on the JSON Schema path. Under global CLAUDE.md §4 that premise can be
   revisited, but only as an explicit fork. Also, the Gemini API guide (as distinct from the Cloud guide) still does
   not list `anyOf` for function declarations, and nothing says `gemini-3.5-flash-lite` honours it when decoding. A
   live 400 or accept check is still needed.
2. **A union or split cannot stop this failure on its own.**
   - The placeholders are schema-valid: 2025 and 10 are valid numbers, and "raw" is a valid enum value. That is
     exactly the "schema-valid but value-wrong" class (97.9% of failures) in Yu et al.
   - A union still leaves the model free to pick the numeric branch with a placeholder.
   - A two-array split (`numeric_claims` requiring value+unit, `support_citations` with no value slot) removes the
     slot for qualitative citations. The model can still misfile a support citation as numeric.
   - It would likely remove the `unit`-without-`value` shape, since each array's fields become all-required.
3. **The declaration order may encourage the placeholder.** Gemini preserves schema key order in output (Gemini
   2.5+ per Google's announcement; OpenAI documents the same for its models), and the order here is `value`,
   `unit`, `citation_index`, `quote`. The model may commit to a number before writing the quote, then match it to
   whatever digits are nearby (the year, "10" from a 10-Q-style heading). Moving `quote` first, or setting
   `property_ordering`, is a smaller model-visible change than a union. It is still a prompt change under the
   protocol. This is a hypothesis, not tested.
4. **Option (b) is logically safe for the coverage check if matching is normalized.**
   - The coverage pass only consumes claims that match an answer number, so downgrading a claim whose value matches
     none cannot uncover a number the answer asserts.
   - The downgraded claim still has to pass the qualitative quote-in-source check, so a fabricated quote is still
     caught.
   - Required conditions:
     - Match with the same `normalize()` plus tolerance and the same `_NON_CLAIM_PATTERN`/bracket strip as
       coverage. Raw string presence would wrongly downgrade `4475446000 raw` shown as "$4.48 billion".
     - Treat `value is None` with any `unit` as qualitative instead of malformed, which fixes the `unit: "raw",
       value: null` case.
   - Cost: a genuinely wrong claimed value that the answer never states is silently downgraded, not flagged. The
     answer does not assert that value, so nothing reaches the user; only a diagnostic signal is lost. Logging each
     downgrade (event name, claimed value, citation index) keeps that signal queryable.
5. **(b) is code-only, but it touches the high-blast-radius verifier.** It changes `_verify_one_claim`/
   `verify_claims`, which puts it under the `live-eval-verification.md` spot-check rule and the 90% critical-core
   coverage bar. It does not change model input, so it needs no snapshot regeneration and no panel. A targeted
   `--ids` re-run of the affected questions still applies.
6. **Lowering temperature is not a lever here.** Google's Gemini 3 guidance argues against the current 0.1, not for
   lowering it further. Changing temperature would be a separate model-visible change.

## Open questions

1. Does the Gemini API (not Vertex) accept `anyOf` inside `parameters` → `items` for `gemini-3.5-flash-lite`
   without a 400? Does it accept `parameters_json_schema` with `additionalProperties`/`oneOf`/`const`? A single
   offline-cheap live call would answer this; it costs 1 request of the 500/day quota.
2. Are `mode=ANY` function-call arguments grammar-constrained to the declared schema, or only validated
   afterwards? No Google source found says either way. If they are only validated, a union also gives no decoding
   guarantee.
3. How often does the placeholder shape occur in the panel reports? That rate decides whether a model-visible
   change is worth a panel run at all. It could be measured by grepping existing eval reports for
   `malformed_claim` and for numeric-claim failures whose value is a year or a small integer found in the quote.
4. Does moving `quote` ahead of `value` (inference 3) change the placeholder rate? This would need its own
   one-commit panel comparison.
5. Should a downgraded claim emit a non-refusing `CitationWarning`-like diagnostic, or only a log line? That is a
   design choice for the plan.

## Recommendation

**Do (b) now. Treat (a) as a separate, optional follow-up, not part of this fix.** That is (c) staged, with (b)
first.

- **Why (b) first:**
  - All three observed failures are schema-valid, so no schema shape Gemini documents can rule them out (inference
    2, Yu et al.).
  - (b) fixes all three shapes deterministically at the one place the refusal is decided.
  - It is code-only, needs no panel and costs almost no quota.
  - It keeps every guarantee the verifier gives the user (inference 4).
  - Implement it as: a claim is numeric only if its normalized `(value, unit)` matches some number extracted from
    `answer_text` under the coverage pass's own strip and tolerance. Otherwise, or if `value` is None, verify it as
    qualitative and log the downgrade.
- **Why (a) is not first:**
  - The 2026-09-15 decision rejected `oneOf` on an "unverified against Gemini" premise. The Cloud docs and SDK
    weaken that premise for `anyOf`, but the Gemini API docs don't confirm it, and nothing shows it reduces
    placeholders.
  - (a) is model-visible (one commit, a snapshot regeneration, the panel protocol) and needs open question 1
    answered first.
  - If the downgrade log shows (b) firing often, the cheaper model-visible experiment to try first is key reordering
    (`quote` before `value`). A two-array split comes after that, since it removes the unit-only shape without
    depending on `anyOf` support.
