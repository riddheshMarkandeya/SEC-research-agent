# Negative-number support in `numeric_utils.NUMBER_PATTERN`

**Date:** 2026-09-11 (no paired plan — found during a codebase-wide
complexity review, not planned work; full 4-round review:
`docs/reviews/2026-09-11-negative-number-support.md`)

## Context

`NUMBER_PATTERN` dropped sign entirely — confirmed live,
`extract_numbers("Net loss of $(1,234) million")` returned `1234.0`,
positive. Reachable through this codebase's OWN generated citation text
(a negative XBRL fact rendered via plain `str()`), not just filing
prose. A sign-flipped claim was indistinguishable from a correct one
everywhere in this codebase, with zero test coverage.

## Decision

Extended `NUMBER_PATTERN` with named groups for an optional wrapping
`(`/`)` pair and a bare leading `-`, plus a bare-year guard so
`(2013)`-style citation-year boilerplate isn't misread as `-2013`.
Researched existing libraries first (`quantulum3`, `finparse`) and
rejected both — neither cleanly displaces the hand-rolled extractor
because the actual requirement (interoperate with `normalize()`'s
categories and span tracking) is narrower than what any general library
targets.

## Why

See the review doc for the full 4-round detail — round 2 found round 1's
own fix (a digit-count-alone guard against footnote markers like
"Registrant (1)") was itself a worse regression, silently flipping 554
real short table-cell negative values back to positive; the final guard
requires all three signals (short, not unit/percent-adjacent, AND
preceded by a letter) rather than digit-count alone. A same-day addendum
found two MORE gaps via live eval output, not either review pass: a
spaced `"-"` used as a subtraction operator in a rule-9 disclosure
sentence, and a Unicode minus sign (U+2212) that NFKC normalization
doesn't fold to ASCII.

## Files touched

`numeric_utils.py` only.

## Verification

14 new tests, full suite green throughout (584 → 601). A live full
41-question run hit the Gemini quota mid-run
(`20260912T234239Z.json`) — explicitly marked invalid per this project's
quota-awareness rule, not used for any comparison.

## Related

`docs/reviews/2026-09-11-negative-number-support.md`.
