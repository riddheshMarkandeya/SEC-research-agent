# Review: strip the unprefixed citation header (`022e851`)

No repo plan (Standard design tier; session plan only). `_strip_citation_header` now also strips
the citation header echoed without its `[n] ` prefix. Suite before the diff: 963 passed. The
diff touches `agent.py` and `prompts/`, so it classified Substantial for review.

## Round 1

Passes: `/code-review` high, `arch-reviewer` (opus), `security-reviewer`, `/simplify` (reuse,
simplification, efficiency, altitude).

1. **Medium** (code-review): the docstring claimed a quote starting with another result's header
   is never stripped. That's false for the unprefixed form, which every chunk of the same filing
   shares. `[Fixed]`: reworded to say it's harmless because the rest of the quote must still
   ground against result [n]'s own text.
2. **Medium** (code-review): the `[{n}] ` prefix is hard-coded in `agent.py` apart from
   `CITATION_HEADER_TEMPLATE`. `[Verified, no fix needed]`: splitting the template would change
   the fingerprinted constants; the template comment states the constraint and the literal-header
   test fails if the prefix moves (the altitude pass reached the same conclusion).
3. **Low** (code-review, arch): the end-to-end test's comment narrated the incident. `[Fixed]`:
   trimmed to what the test pins.
4. **Nit** (arch): one test looped over its two cases. `[Fixed]`: parametrized.
5. **Process** (code-review): live spot-check not yet run; compare must use explicit mode.
   `[Verified, no fix needed]`: both were already planned steps (see Live verification).
6. **Low** (simplify, simplification): build the test headers with `_citation_header` instead of
   literals. `[Disputed]`: the expected value would then come from the code under test
   (tautological), and the literal is what catches a moved prefix (finding 2).
7. **Nit** (simplify, efficiency): compute the unprefixed candidate lazily.
   `[Verified, no fix needed]`: once per claim on a ~30-char string.

Security: no issues. Tried and disproved: another citation's or fabricated metadata in the
header (both candidates come from the claim's own metadata), a strip extending into the value
text (exact `startswith` only), a same-filing header from another index (the `[m] ` prefix blocks
it, and grounding runs against result [n] regardless), whitespace or case tricks (fail closed).
Reuse and altitude: no findings.

## Round 2

Delta: `git diff f0bd8b9` (round-1 snapshot). Passes: `/code-review` low. No findings.
Checks: ruff 0, pyright 0, 969 passed, agent fingerprint `7aec53939ce3`.

## Live verification

Three targeted runs on `022e851`: 6/6 passed (WP8: 0/2). None of the 6 submit spans echoed the
header, so the new path wasn't exercised live. Details in
`docs/decisions/2026-09-27-unprefixed-citation-header-strip.md`.

## Outcome

Shipped in `022e851`. Nothing deferred. Final suite 969 passed. Closed clean after 2 rounds.
