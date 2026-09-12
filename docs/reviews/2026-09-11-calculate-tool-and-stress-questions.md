# Review: the `calculate` tool and new citation-gate stress questions

Plan: `docs/plans/2026-09-11-calculate-tool-and-stress-questions.md`.
Two-pass review per CLAUDE.md step 7, run after implementation, live
verification of both motivating questions, and the new eval questions
were all complete and the full suite was green (584 tests at the time
both passes ran).

## Pass 1 — correctness and CLAUDE.md compliance (`/code-review`, medium effort)

1. **[Fixed] `_calculation_as_result` could produce citation text a
   `calculate` result could never itself be cited against.** Computed
   values were rendered via Python's default `str()`, which switches to
   scientific notation ("1e+18") outside roughly 1e16..1e-4 — but
   `NUMBER_PATTERN` (`numeric_utils.py`) has no exponent support at all.
   `multiply` of two billion-scale operands reaches this range easily
   (1e9 × 1e9 = 1e18). Confirmed live: a `calculate` call producing
   `1e18` rendered as `"...= 1e+18 (computed value...)"`, and a
   `submit_answer` claim citing that exact text was refused by
   `_verify_one_claim` with `value_not_in_quote` — a correct, tool-
   computed value (the very guarantee this tool exists to provide) would
   have been refused as ungrounded. **Fix**: added
   `_format_computed_number()`, a fixed-point formatter (`.6f`, trailing
   zeros/dot stripped) used everywhere a computed number is rendered into
   citable text — both operand values in the expression string and the
   result value itself. Added
   `test_calculation_as_result_text_avoids_scientific_notation_for_large_values`,
   which reproduces the exact `multiply`-of-two-billions scenario and
   proves end-to-end (not just format-checks the string) that a claim
   citing the result now passes `_verify_one_claim` — confirmed red
   before the fix, green after.

## Pass 2 — architecture, design, performance, refactoring (fresh subagent, no memory of the implementation session)

Verdict: **clean bill of health**. The new `calculate` branch in
`_dispatch_tool_call` matches the existing 6-step dispatch shape used by
every other tool exactly (trace span → boundary call → not-found returns
a formatted message with zero `all_results` mutation → build+append a
result → `span.update()` → return the formatted block) — no divergence.
The schema's explicit `unit_a`/`unit_b` fields and the category-match gate
(`normalize()`'s percent-vs-scale category, required to match between
both operands) are consistent with decisions the codebase already made
for `submit_answer` claims, not a new restriction invented for this tool.
`_ground_operand` correctly reuses `_number_candidates()` — the same
primitive `_verify_one_claim` already trusts — rather than reinventing
extraction. `mcp_server.py` genuinely excludes the new schema, matching
the stated reasoning (citation indices are only meaningful within one
`_run_agent_impl` run). No performance concerns (arithmetic and a text
scan over small per-call inputs, no O(n²) risk against `all_results`).

Three minor findings, none blocking:

1. **[Deferred to BACKLOG, not fixed]** The
   `normalize(...); tolerance = max(0.01*abs(norm), 0.05); any(...)`
   pattern is now duplicated 5 times across `agent.py` (it existed 3
   times before this change; `_ground_operand`/`call_calculate` add a
   4th and 5th use). Extracting a shared `_matches_any(value, unit,
   candidates) -> bool` helper would be a reasonable cleanup, but it's
   cosmetic and unrelated to this change's actual scope — filed to
   `BACKLOG.md` as a `[refactor, Low, Trivial]` item rather than expanding
   this diff to touch 3 other call sites for a non-functional change.
2. **[Not fixed, judged not worth it]** `_ground_operand` computes
   `normalize()` once for its own grounding check, and `call_calculate`
   calls it again immediately after for the actual arithmetic — a cheap,
   O(1) redundant call per operand, not a real performance concern.
   Could return `(category, norm)` from `_ground_operand` on success to
   avoid the second call, but the current two-call version reads more
   clearly (grounding and arithmetic stay visibly separate steps) and the
   cost is negligible.
3. **[Not fixed, judged not a defect]** The category-match gate can't
   distinguish "dollars" from "share count" — both are `normalize()`'s
   coarse `"scale"` category — so a nonsensical `multiply` of two
   unrelated scale quantities would still be schema-legal. This is an
   existing limitation of the whole `normalize()` model (two categories,
   `percent` and `scale`), not something `calculate` introduces or could
   reasonably fix without a larger unit-typing redesign well outside this
   change's scope.

## Review-loop status

Two rounds completed (the two required passes); the first pass's finding
is fixed and covered by a new regression test testing the actual failure
end-to-end, not just the surface symptom. The second pass's three minor
findings are either filed to `BACKLOG.md` (the DRY duplication) or judged
not worth acting on (documented above, not silently dropped). No further
review round is planned before landing.
