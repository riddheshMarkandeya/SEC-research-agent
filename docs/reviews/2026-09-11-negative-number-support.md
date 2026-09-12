# Review: negative-number support in `numeric_utils.NUMBER_PATTERN`

Plan: implicit — see `PROJECT_CONTEXT.md`'s 2026-09-11 "Negative-number
support" section for the full context, prior-art research, and design.
Full TDD throughout; full suite green at every step.

## Pass 1 — correctness and CLAUDE.md compliance (`/code-review`, medium effort)

1. **[Fixed] A naive "any `(NUM)` is negative" rule misreads common
   footnote/reference markers as negative.** Confirmed live:
   `extract_numbers("Total debt securities (1) $ 433")` returned
   `[(-1.0, "raw"), (433.0, "raw")]`; `grep`-confirmed this exact shape
   ("Mark whether the Registrant (1) has filed... and (2) has been...")
   appears on literally every 10-K's cover page in this project's corpus.
   Because this feeds `_number_candidates()`'s candidate pool in
   `agent.py`, a spurious `-1`/`-2` could falsely "verify" an unrelated
   small-negative-value claim never actually stated in that source.
   **First fix**: suppress the sign flip for a parenthesized number that
   is short (<=2 digits), comma-less, decimal-less, and not immediately
   followed by a unit word or `%`. Added regression tests for both the
   prose-enumeration and glued-to-table-label shapes, plus a test
   confirming a genuine single-digit negative percent (`"(4)%"`, also
   found live in the corpus) still flips correctly.
2. **[Accepted, documented, not fixed]** A real dollar charge stated as
   an exact, comma-less 4-digit 19xx/20xx figure (e.g. "Impairment charge
   (2010)" meaning -$2010) would be read as positive by the bare-year
   guard. Genuinely ambiguous with no disambiguating signal even to a
   human reading the isolated text, and no real occurrence of this shape
   was found in the corpus (unlike every other carve-out here, which
   is grep-confirmed real) — documented as an accepted residual rather
   than chased further, per this project's practice of fixing what's
   evidenced.

## Pass 2 — architecture, design, performance, refactoring (fresh subagent, no memory of the implementation session)

**Verdict: found a real, more serious bug in pass 1's own fix.** The
subagent constructed and ran counterexamples rather than just eyeballing
the diff, and found that pass 1's digit-count-alone guard broke on this
project's own pipe-delimited table format: a genuine short negative table
value (unit stated once in the table's caption, not per-cell — the exact
mechanism `_number_candidates`'s `unit_source` already exists to handle)
was indistinguishable from a footnote marker by digit count alone.
Verified the scale of the regression directly against the full corpus
before accepting the finding: **554 occurrences** across all 5 companies
of a short comma-less negative value as its own table cell (e.g.
`"Cumulative translation, net of tax | 449 | (73) | (86) | (87) |"`) were
being silently flipped back to positive by pass 1's own fix — a
regression clearly worse than the false positive it closed.

Root cause, found by comparing both real shapes side by side: a footnote
marker is always glued to a preceding WORD (`"Registrant (1)"`, just a
space between); a real table-cell value always starts fresh — right
after a `"|"` delimiter, a newline, another number, or a currency symbol,
never directly after a letter. **Fix**: the reference-number guard now
requires all three — short/comma-less/decimal-less, not immediately
followed by a unit/percent, AND the nearest non-whitespace character
before the `"("` is alphabetic. Verified this separates every real
occurrence of both shapes with a live full-corpus scan (0/554 still
wrongly positive), not just a re-run of the existing test set.

Two minor findings, both addressed:
1. **[Fixed]** Test coverage restated the carve-outs' own logic rather
   than stress-testing the corpus shape that actually broke it (the
   554-occurrence table-cell case). Added two tests reproducing the real
   failing shapes directly.
2. **[Fixed]** The sign-determination logic (base rule + two carve-outs)
   was packed into one dense inline conditional. Extracted `_is_negative()`
   as a single, clearly-named function housing the base rule and both
   carve-outs together.

No other issues found: architecture/style fit matches the file's existing
grounded-in-real-corpus commenting convention; `normalize()`'s
percent/scale split is untouched; no real performance concern (one
compiled module-level regex, same asymptotic behavior, negligible extra
branching per match); the `sign` lookbehind's ISO-date/hyphen-range
handling and the bare-year vs. reference-number carve-outs are each
internally sound, independently traced/re-run with no interaction bug
between them.

## Round 3 — found live, by the first real eval run after landing (2026-09-12)

Not from either review pass — from actually running the full 41-question
`eval_harness.py --backend gemini` baseline once the Gemini daily quota
reset, per the pending `BACKLOG.md` item. `aapl-msft-employee-comparison`
(previously a clean pass) newly hard-gate-refused: `"claims -166000.0
(raw) but no claim in your submit_answer call covers it"`. The model's
own answer disclosed its computation exactly as system-prompt rule 9
asks ("...57,000 more full-time employees than Apple (computed as
223,000 - 166,000 = 57,000)"), using a literal, SPACED `"-"` as the
subtraction operator — not a sign. `(?<!\d)`'s guard against a hyphen
glued to a *preceding* digit (added in the original design, see the
ISO-date/hyphenated-range reasoning above) didn't cover this: the
character immediately before this hyphen is a space, not a digit, so the
guard passed and `166,000` was misread as `-166000.0`.

Root cause: a regex-only fixed-width lookbehind can't skip variable
whitespace to check what's on the OTHER side of that space. Fixed at the
Python level (same technique already used for the reference-number
carve-out's "preceded by a letter" check): `_preceded_by_number()` looks
backward past whitespace and confirms the nearest real character isn't a
digit — a genuine negation is preceded by a word, punctuation, an opening
paren, or nothing; a subtraction's minuend is a number. Verified against
the exact live failure (`extract_numbers` on the real withheld answer
text, before and after) and end-to-end by re-running the exact eval
question live post-fix (`aapl-msft-employee-comparison` now passes
cleanly, 0 citation warnings). The other newly-gated question from the
same eval run, `nvda-gross-margin-fy26`, failed on `quote_not_found` —
unrelated to this fix (`_quote_matches` never calls into
`numeric_utils.py`) and matches this exact question's pre-existing,
already-documented non-deterministic flakiness in `BACKLOG.md`; not
touched here.

## Review-loop status

Three rounds, each catching something the previous one couldn't: round 1
(`/code-review`) found the footnote-marker false positive; round 2 (a
fresh architecture subagent) found round 1's own fix was a worse
regression at scale (554 real occurrences); round 3 (the first live full
eval run) found a shape neither static review exercised — a model
choosing "-" as its own notation for subtraction inside a disclosure
sentence, something only a live model-generated answer could surface.
Each was a distinct, newly-found issue with a clean, verified fix, not
the same issue recurring — per CLAUDE.md's cap, that's the loop working
as designed, not a signal to stop and escalate. Full suite green
throughout (584 -> 600 tests, +16 new). No further round planned before
landing; the next real signal will be the full 41-question baseline
re-run with this fix included.
