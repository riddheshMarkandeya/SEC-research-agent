---
paths:
  - "edgar_ingest.py"
  - "xbrl_facts.py"
  - "index_chunks.py"
  - "retrieval.py"
  - "agent.py"
  - "llm_backends.py"
---

# This project's live-code TDD carve-out

The `tdd-live-code-carveout` skill's "live-only code" category means,
concretely, in this repo:

- **SEC EDGAR HTTP calls** (`edgar_ingest.py`, `xbrl_facts.py`)
- **Chroma + embedding indexing/retrieval** (`index_chunks.py`,
  `retrieval.py`)
- **LLM round-trips through either backend** (`agent.py`'s tool-calling
  loop, `llm_backends.py`)

For each of these, write the manual repro/verification script under
`tests/manual/verify_*.py` first, confirm it reproduces the bug or
exercises the new behavior, then implement, then re-run it — same
red-green spirit as unit TDD, different tool.

**Keep this list current the same way `BACKLOG.md` keeps itself
current** (see this project's own `CLAUDE.md`): add a file the moment a
change to it turns out to need a manual repro script first (a real
network call, DB/vector-store operation, or LLM round-trip that unit
tests alone can't safely cover) and it isn't already listed above, in
the same step, not as a deferred follow-up.
