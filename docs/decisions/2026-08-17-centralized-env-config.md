# Centralized environment configuration (`config.py`)

**Date:** 2026-08-17 (commit `32b59a5`, "Centralize env config; fix XBRL
period matching to trust data over computed labels" — a squashed commit
covering both this decision and
`docs/decisions/2026-08-17-xbrl-period-matching-end-date-fix.md`; the two
are unrelated changes that happened to land together)

## Context

Several infra values were independently hardcoded as module-level
constants in 3+ files each, with the drift already visible in diverging
names: `CHROMA_DIR` separately defined in `index_chunks.py`,
`retrieval.py`, and `query_chunks.py` (all three must agree or one
silently queries an empty/unrelated store); the embedding model name
under two different variable names (`MODEL_NAME` vs `EMBED_MODEL_NAME`);
the SEC `User-Agent` header built once in `edgar_ingest.py` and hardcoded
a second time in `xbrl_facts.py`; the Ollama URL/model name already
centralized once, but oddly owned by `answer.py` (an answer-generation
script being the source of truth for two other modules' config).

## Decision

New `config.py` loads `.env` via `python-dotenv` and exposes typed
constants (`SEC_USER_AGENT`, `OLLAMA_URL`, `OLLAMA_MODEL_NAME`,
`CHROMA_DIR`, `EMBED_MODEL_NAME`, `RERANK_MODEL_NAME`), each with a
fallback equal to what was previously hardcoded. `.env.example` is
committed as the template; `.env` itself is gitignored. All 8 consuming
modules (`edgar_ingest.py`, `xbrl_facts.py`, `index_chunks.py`,
`query_chunks.py`, `retrieval.py`, `answer.py`, `agent.py`,
`eval_harness.py`) now import from `config.py`. The Ollama chat model
constant was renamed `OLLAMA_MODEL_NAME` everywhere (previously
ambiguous `MODEL_NAME`, colliding in name — though not meaning — with
the embedding model constant of the same name elsewhere).

## Why

Same duplication-drift risk `companies.py` had just been built to fix
for ticker/company data, applied here to infra config — a config value
silently diverging across files is strictly worse than a crash, since
nothing signals the disagreement.

## Files touched

`config.py` (new), `.env.example` (new), and all 8 consuming modules
listed above.

## Verification

`python -c "import <module>"` for all 8 consuming modules, plus the full
137-test suite, both clean after the change.

## Related

Squashed alongside
`docs/decisions/2026-08-17-xbrl-period-matching-end-date-fix.md` in the
same commit.
