# Review: phase 2 build 3b, v2 authoring check script

Plan: `docs/plans/2026-10-12-phase2-build3b-authoring-check.md`. The change adds a schema
amendment (`eval/questions.py`) and `devtools/check_questions.py`, the authoring check a v2
question batch passes before the user reviews it. Substantial by design tier; about 1,650 lines
including tests. The plan's `## Review log` has each finding's full disposition. This file is
the summary.

## Round 1

Passes: `/code-review` high, `arch-reviewer` (sonnet), `security-reviewer`, `/simplify`
(reuse, simplification, efficiency and altitude angles).

1. **High** (code-review): a top-level `derivation` on a non-numeric question crashed the run
   with a `KeyError`. `[Fixed]` It is rejected at load.
2. **Med** (code-review, arch): a part name reused for another figure silently hid one figure
   from the anchor check. `[Fixed]` Reported as an error.
3. **Med** (code-review): a derivation of constants only needed no anchor. `[Fixed]` Error.
4. **Med** (code-review): the absence search missed hyphen, quote and Unicode variants, which
   would let a disclosed value pass as never disclosed. `[Fixed]` The text is folded to words.
5. **Med** (code-review): the rounding spread trusts the authored value's precision.
   `[Fixed]` by a checklist rule: write inputs as printed.
6. **Low** (code-review): a spread was checked across unit categories, and the "unneeded
   tolerance" warning ignored derivations that errored; trap-beside-answer ignored the trap's
   company; `accepted` wasn't graded for the ticker check. `[Fixed]` All four.
7. **Low** (code-review, arch, altitude): the spread's exact arithmetic copies the tool's.
   `[Fixed]` A test pins it to `_apply_calculate_operation`. A shared function in
   `calculate.py` (critical core) is out of scope.
8. **Nits** (arch): two comments and a plan addendum `[Fixed]`. Private-name imports and
   `assert` narrowing `[Verified, no fix needed]`.
9. Security: no findings. Path building from a ticker was examined: tickers come from local
   chunk metadata.
10. `/simplify`: six cleanups applied, including indexing XBRL facts by accession once per
    ticker. Refactors into critical-core modules were skipped (listed in the plan).

## Round 2

Delta: `git diff 1e4a0f6`. Passes: `/code-review` low, `arch-reviewer` (sonnet),
`security-reviewer`.

1. **Low** (code-review): `trap.get("ticker", single_ticker(question))` evaluates its default
   eagerly. `[Verified, no fix needed]` `single_ticker` returns None, never raises; a test
   covers a multi-company trap.
2. **Nit** (arch): run-on docstring. `[Fixed]`
3. **Low** (arch): a punctuation-only absence term matches everything. `[Verified, no fix
   needed]` It fails loudly.
4. Security: no findings.

Closed: no new finding needing an executable change.

## Live verification

No Gemini quota is spent: the tool runs offline, except for the cached companyfacts reads.
- **v1 smoke run.** Exit 1 with 27 errors, all on the 9 derived v1 questions that predate
  `derivation`. Every v1 anchor matches a chunk.
- **Two-question fixture.** Exit 1 with exactly the two expected errors.
