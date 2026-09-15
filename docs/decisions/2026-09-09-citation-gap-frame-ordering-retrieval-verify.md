# Uncited-claim detection, `get_frame()` ordering fix, `verify_retrieval.py`

**Date:** 2026-09-09/10

## Context

Picked up the next 3 highest-impact `BACKLOG.md` items. Full design:
`docs/plans/2026-09-09-citation-gap-frame-ordering-retrieval-verify.md`.
Review (five real rounds):
`docs/reviews/2026-09-09-citation-gap-frame-ordering-retrieval-verify.md`.

## Decision

New `_iter_uncited_claims()` detects numeric claims with NO citation
marker anywhere near them, closing a gap `_iter_citation_claims()`
couldn't see (motivated by a real observed case, `msft-cash-to-assets-fy2025`).
`xbrl_facts.py`'s `get_frame()` tag-merge tiebreak is now deterministic
(sorted, logged on genuine conflict, winner is the ticker's own
designated tag). New `tests/manual/verify_retrieval.py` — the one live
integration point that had no manual verification script.

## Why

This design went through five real review rounds, each finding a
genuinely different, non-obvious failure mode: a comma-joined second
claim sharing a sentence with a real citation slipping through entirely;
the fix for that being too restrictive and wrongly flagging genuinely-
grounded numbers sharing one trailing citation; a regex backtracking bug
and a cross-loop duplicate-warning bug. See the review doc for the full
five-round trace. Two deliberately-accepted, documented limitations
remain (a lowercase sentence start missed as a break; an out-of-range
citation marker's pre-existing tolerant behavior, left unchanged).

## Files touched

`agent.py` (`_iter_uncited_claims`, `_SENTENCE_BREAK`), `numeric_utils.py`
(`extract_numbers_with_spans`), `xbrl_facts.py` (`get_frame`),
`tests/manual/verify_retrieval.py` (new).

## Verification

Full suite 464/464. Live spot-check both backends across 6 questions:
Gemini 6/6 clean; Ollama 3/6, all three failures confirmed as
pre-existing, already-documented local-model flakiness. Live
`verify_mcp_server.py` and `verify_retrieval.py` runs both clean.

## Related

`docs/plans/2026-09-09-citation-gap-frame-ordering-retrieval-verify.md`,
`docs/reviews/2026-09-09-citation-gap-frame-ordering-retrieval-verify.md`.
