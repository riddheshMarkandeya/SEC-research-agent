# Grounding computed numbers and formula constants

Date: 2026-09-28
Question: how do citation- or grounding-gated LLM systems treat numbers that appear in the model's own inline
arithmetic (derived values, and formula constants such as the 1 in "a/b − 1" or the 100 in "× 100")?
Feeds: the choice among options (a)–(e) for `verify_claims`' coverage check.

## Findings (what the sources say)

1. **Program-based numeric QA runs the computation and keeps it out of the narrated text.**
   - PoT has the LM "express the reasoning process as a program", and an external computer runs the program
     to get the answer. The paper evaluates on FinQA, ConvFinQA and TAT-QA and reports about 12% average gain over
     CoT. https://arxiv.org/abs/2211.12588
   - PAL: LLMs "often make logical and arithmetic mistakes in the solution part". PAL "offloads the solution
     step to a runtime such as a Python interpreter". https://arxiv.org/abs/2211.10435
   - Toolformer puts the call inline in the text, "[Calculator(723 / 252)] 2.87". The expression the reader sees
     is the executed call, not a re-derivation. https://arxiv.org/abs/2302.04761
2. **FinQA whitelists formula constants as explicit program tokens tied to the program.**
   - The generator's closed constant vocabulary is `CONST_1 … CONST_10, CONST_100, CONST_1000 … CONST_1000000000,
     CONST_M1`. https://github.com/czyssrs/FinQA/blob/main/code/generator/constant_list.txt
   - The operations are `add subtract multiply divide exp greater table_*`.
     https://github.com/czyssrs/FinQA/blob/main/code/generator/operation_list.txt
   - Every other program token must be a number found in the input. Otherwise `assert cur_num_idx != -1` fails.
     https://github.com/czyssrs/FinQA/blob/main/code/generator/finqa_utils.py (`prog_token_to_indices`,
     lines 40-61)
   - Result: grounded numbers come from the evidence. Constants are a small fixed set that is valid only inside
     a program. This is structurally the same as option (b).
3. **Human-written gold derivations use both formula shapes, and the constant 1 appears as a literal.**
   - TAT-QA dev set `derivation` fields include `"126 / 67 - 1"`, `"22,224 / 30,890 - 1"`,
     `"(1,609,000 - 1,164,000)/1,164,000"` and `"100 - 82"`. In these samples the percent derivations leave
     out "× 100".
     https://raw.githubusercontent.com/NExTplusplus/TAT-QA/master/dataset_raw/tatqa_dataset_dev.json ;
     paper https://arxiv.org/abs/2105.07624
   - So "a/b − 1" is a natural, common way people write a derivation, not a model quirk.
4. **Attribution frameworks have no carve-out for arithmetic or constants.**
   - AIS lists "numerical reasoning" among its hard cases: such cases "may be difficult to assess for AIS
     because they need extra reasoning". It still applies the "according to P" test to them. It has no
     exemption for derived values or constants. https://arxiv.org/html/2112.12870v2 (§3.1, Table 1)
   - FActScore breaks text into atomic facts and scores each one against a knowledge source. It has no special
     treatment for computed values. https://arxiv.org/abs/2305.14251
   - RARR finds attribution after the fact and post-edits unsupported content. It is also about facts, not
     arithmetic. https://arxiv.org/abs/2210.08726
   - Numeric fact-checking benchmarks (QuanTemp) treat numerical claims as a hard, separate verification class:
     the best macro-F1 is 58.32. https://arxiv.org/abs/2403.17169
5. **Vendor grounding APIs cite spans, not computations.**
   - Anthropic Citations: `cited_text` is extracted by the API, so citations "are guaranteed to contain valid
     pointers to the provided documents". Citations are incompatible with structured outputs, and using both
     returns a 400. https://platform.claude.com/docs/en/build-with-claude/citations
   - Tool results can be made citable as `search_result` blocks.
     https://platform.claude.com/docs/en/build-with-claude/search-results
   - Neither page says how to cite a value the model computed.
   - Google Check Grounding treats "a sentence" as a single claim and scores whether the facts entail it. Claims
     that aren't facts (e.g. "Here is what I found.") get `groundingCheckRequired: false`. The page does not say
     how numbers or arithmetic are handled.
     https://docs.cloud.google.com/generative-ai-app-builder/docs/check-grounding
   - Structured outputs and strict tool use guarantee schema compliance ("Guaranteed field types and required
     fields"), not that the values are correct.
     https://platform.claude.com/docs/en/build-with-claude/structured-outputs
6. **Do models copy verbatim? The evidence is mixed and indirect.**
   - More copying from context correlates with fewer unfaithful hallucinations on RAGTruth.
     https://arxiv.org/abs/2510.00508
   - Frontier models "fail to perform … exactly copying an input string" that sits well inside their context.
     https://arxiv.org/abs/2607.16072
   - No source found measures whether models copy a *tool-rendered arithmetic expression* verbatim into their
     final prose.

## Repo facts relevant to the options

- **The model's derivation shape comes from the prompt, not from the tool.**
  - Rule 9 and the `calculate` description both give the example "computed as $34,550 million ÷ $195,201 million
    = 17.7%" (prompts/agent_system.py:53, prompts/agent_tools.py:286). That is a percent_of shape with no × 100.
  - No prompt shows a percent_change example.
  - The tool renders percent_change as prose, "percentage change from {b} to {a}" (prompts/agent_messages.py:40),
    and prose has no operators to copy.
  - Inference: when the model is asked to "show the computation inline" for a percent change, it improvises a
    formula, and "a ÷ b − 1" is the natural improvisation (see finding 3).
- **The constant's sign depends on what precedes it.** (Corrected after checking; the first draft said it always
  parses as −1.)
  - After a number, the spaced minus is subtraction: `extract_numbers("44,062,000,000 - 1 = 85.2%")` gives
    `(1.0, 'raw')`, as in the live answer. The "−1" in the first draft came from "$44.1B", where "B" isn't a
    unit, so the minus followed a letter.
  - After ")", as in "(a ÷ b) − 1", it reads as a sign: `(-1.0, 'raw')`. `_covered`'s comparison is
    sign-sensitive, so option (b) needs 1, −1 and 100. "× 100 − 100" gives +100.
- **Category separation limits how far (b) can leak.**
  - A bare "100 stores" or "1 segment" normalizes to `('scale', 100.0)` or `('scale', 1.0)`.
  - "1%" is `percent`, and "$1 billion" is `('scale', 1e9)`.
  - So identity candidates at scale 1 and 100 only cover bare unitless numbers. (Pre-decision analysis: with the
    1% tolerance that would be [0.95, 1.05] or [99, 101]; the implementation matches exactly.)
- **Side finding: the "B" suffix isn't parsed.**
  - `extract_numbers("$81.6B")` returns `(81.6, 'raw')`, and so does "$81.6bn". "$81.6 billion" returns
    `(81.6, 'billion')`. This holds at HEAD `ffffee8`.
  - It doesn't affect this bug: "$81.6B ÷ $44.1B" was the research question's paraphrase. The live answers wrote
    full figures ("$81,615,000,000 ÷ $44,062,000,000 - 1"), and only the 1 was flagged. It's filed as its own
    backlog item.
- The first implementation's `_strip_formula_constants` regex, since removed, was the shape-guessing approach
  under review.

## Inferences (mine, not from sources)

- Every system found either:
  - executes the computation and renders it in code (PoT, PAL, Toolformer, FinQA programs), or
  - leaves arithmetic to a human or NLI judge (AIS, FActScore, Check Grounding).
- None uses a regex over free prose to decide which numbers in a model-written formula are constants. That
  matches the four review rounds: the shape space is open-ended, and TAT-QA's annotators alone use at least two
  shapes.
- FinQA's design is the closest match to (b):
  - constants are a closed, tiny vocabulary;
  - they are valid only in the presence of an executed program;
  - they don't depend on the text's shape.
- Option (a) only covers the one shape it renders. The model can still write the other shape (finding 3), and
  the rule 9 example, not the tool text, is what currently shapes the prose.
- Option (d) in its strong form (code renders the derivation from the `calculate` record, and the model only
  references it) is the PoT/Toolformer pattern. It removes the problem rather than filtering it. A weak form (a
  model-written `derivation` field the gate skips) just moves the free text, and a skipped field can hide an
  invented operand.

## Open questions

- How many eval questions are percent_change or percent_of? This sets the cost of (e). Not checked.
- Would the model reliably copy a rendered "(a − b) ÷ b × 100"? No primary evidence was found either way (see
  finding 6). Only a panel run can tell.
- Do other shapes appear live, such as "÷ 2" for averages or "× 1,000" unit shifts? If they do, (b)'s constant
  set may need to grow the way FinQA's did. It should stay closed and tied to the operation.
- Does the "B"/"bn" suffix gap cause live refusals anywhere? It didn't in the three NVDA runs (full figures
  written there). Filed as a backlog item.
- The Citations and structured-outputs incompatibility is Anthropic-specific. The project runs on Gemini and
  Ollama, so it doesn't constrain (d) here. Noted only as prior art.

## Recommendation (ranked)

Risk key: **F** = the risk that a fabricated number gets through; **W** = the risk that a correct answer is
withheld.

1. **(b) alone, scoped: first choice.** Only on a turn with a successful `percent_change`/`percent_of`
   calculation, add the identities {1, −1, 100, −100} to `calculated_candidates`, in the scale category only.
   (As implemented: {1, −1, 100, −100} for percent_change and {100} for percent_of, matched exactly rather than with
   the 1% tolerance. That drops the [0.95, 1.05] and [99, 101] leak, and the operation is read from
   `calculate`'s own rendered text, not from new metadata, so the agent fingerprint stays unchanged.)
   Delete the regex strip.
   - F: low and bounded. The only thing that can slip through is a bare unitless number within 1% of 1 or 100,
     and only on turns where a percent calculation actually ran. This is FinQA's closed-constant design.
   - W: low. It covers every formula shape the model might write ("a/b − 1", "× 100", "100 × (a − b)/b"),
     because it doesn't read the shape at all.
   - Cost: code-only, so no panel run is required. The live spot-check rule still applies to `verify_claims`.
2. **(b) + a prompt-only alignment of the rule 9 example (a variant of (a)/(c)): only if percent derivations
   still misbehave after (b).** Change the example so it matches the tool's own rendering (e.g. "an 85.2%
   increase, calculated from $44,062 million to $81,615 million"), or add a percent_change example.
   - F: unchanged from (b).
   - W: slightly lower.
   - Cost: a prompt change, so one commit plus a panel run. Its main value is readability and consistency, not
     the gate.
3. **(d) strong form: long-term target, as a separate work package.**
   - `submit_answer` claims reference a `calculate` result id, and code renders the derivation text from that
     executed record (PoT/Toolformer).
   - F: lowest, because no model-written arithmetic reaches the gate.
   - W: lowest once adopted, but high during the transition, because the model will still write inline math into
     `answer_text` until the prompts change.
   - Cost: the highest. It changes the schema and the prompt, touches the blast-radius core (agent.py, prompts/),
     and needs panel runs.
   - Reject the weak form (a model-written derivation field that the gate skips): it has the highest F of all.
4. **(a): rendered expression with the constants.**
   - F: low, since the constants are tied to the executed calculation.
   - W: medium. It only covers the rendered shape, and the rule 9 example competes with it.
   - Cost: a prompt-visible change (a commit plus a panel run) and a larger snapshot diff. It gains little over
     (b) for the gate.
5. **(c): tell the model not to re-derive inline.**
   - F: low.
   - W: medium, because instruction-following is imperfect and any inline math the model still writes is
     withheld.
   - It reverses rule 9's current "show the computation inline" instruction, which exists so a calculated value
     isn't presented as if the filing stated it. It is also a prompt change with a panel run.
6. **(e): accept the false positive.**
   - F: none added.
   - W: high. Three live runs have already withheld correct answers, and every percent_change question is at
     risk.
   - Acceptable only as a stopgap while (b) lands.
7. **Status quo, the shape regex: drop it.**
   - F and W were both non-zero across four review rounds.
   - No prior art found filters formula constants by the shape of free text.

The costs of (a) and (c) are higher than code-only options because of this project's prompt-change protocol:
one commit per change plus a panel eval run (`.claude/rules/live-eval-verification.md`, "Prompt changes").
(b) avoids that protocol entirely.
