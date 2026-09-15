# TDD adoption and pre-commit test gate

**Date:** 2026-08-14 (dated via commit `cfc3175`, "Add unit test suite and
pre-commit test gate" — the original `PROJECT_CONTEXT.md` "Development
workflow" section carried no ISO date of its own, only "started from Week
4 onward")

## Context

Weeks 2-4 had accumulated real, working code (ingestion, chunking,
indexing, retrieval) with no test suite at all. The project needed a
standing rule for when tests get written, not just an ad hoc decision
per module.

## Decision

Tests are written alongside new code going forward, not after, and
nothing gets committed with a failing test. Applied retroactively to
Weeks 2-4's pure/deterministic logic, then as a standing rule for
everything after. Enforced mechanically via a git pre-commit hook
(`githooks/pre-commit`, tracked in-repo since git itself doesn't
version-control hooks — a fresh clone needs `cp githooks/pre-commit
.git/hooks/pre-commit`), not left to convention alone.

## Why

Scope was deliberately narrow: only pure/deterministic functions get
unit tests (string/data transforms, grading logic, formatting) — no live
network calls, no embedding/rerank model loads, no live Ollama calls.
Code that inherently needs those (EDGAR HTTP calls, Chroma indexing,
`generate_answer()`, `grade_judged()`'s live LLM round-trip) is exercised
by manual verification runs instead of mocked into unit tests — mocking
an embedding model's output would test the mock, not the code. One
deliberate exception: `grade_judged()`'s response-parsing logic
(splitting `"PASS\n<reason>"` out of a reply) is pure and gets a unit
test with a mocked `requests.post`, since the parsing itself is worth
covering without a live server.

## Files touched

`githooks/pre-commit`, `pyproject.toml` (pytest config), initial
`tests/` suite covering Weeks 2-4's pure logic.

## Verification

Verified the hook actually blocks: committed a deliberately failing
test and confirmed the commit was rejected — the same "test the test"
principle later reused for the eval harness's own negative-control
checks.

## Related

This is the rule referenced throughout the rest of the project's
history whenever a change says "full TDD" or "full suite green at N" —
see any later decision file for a concrete application. Project
`CLAUDE.md`'s live-code TDD carve-out (SEC EDGAR HTTP, Chroma/embedding,
LLM round-trips) narrows this rule's live-only category concretely for
this repo.
