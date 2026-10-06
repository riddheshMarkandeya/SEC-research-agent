# Review: persistent cross-encoder score cache for the replay tools

Plan: `docs/plans/2026-10-05-rerank-score-cache.md`. A new devtools module, `rerank_cache.py`, caches whole `CrossEncoder.predict` calls in SQLite under `var/rerank_cache/` for `analyze_gate_replay` and `retrieval_replay` only, with a `--no-rerank-cache` flag and stats in each report header. The suite had 1252 tests before this diff (1279 after). The diff classified as Substantial (about 700 lines, Substantial design tier, no high-risk path).

## Round 1

Snapshot `145b616`. Passes: `/code-review` high, `arch-reviewer` (sonnet), `security-reviewer`, `/simplify` (reuse, simplification, efficiency, altitude).

1. **High** (code-review): the cache identity left out `activation_fn`, dtype, device and the Hugging Face revision, so changing any of them behind the same model name would reuse stale scores and hide the change `--compare` exists to measure. `[Fixed]`: all four are in the identity now, along with `max_seq_length`. Only a local model path whose weights change stays undetected (documented).
2. **Medium** (code-review, arch): a corrupt row raised an uncaught `ValueError`, and a wrong-length row was served unchecked, despite the module's "a cache failure never fails a replay" promise. `[Fixed]`: `ScoreStore.get(key, count)` raises `ValueError` and `predict` disables the cache mid-run. Tested with real corrupt rows.
3. **Low** (code-review, arch): hits returned float64, misses float32. `[Fixed]`: hits return float32, which is exact. Tested.
4. **Low** (code-review, arch): a failure to open the store looked the same in the header as `--no-rerank-cache`. `[Fixed]`: it reports `disabled: "at open"`. Tested, and fired live once.
5. **Low** (code-review): `install` idempotence across two `main` calls in one process. `[Verified, no fix needed]`: no caller runs `main` twice, and the tests stub `install`.
6. **Low** (code-review): `install` loads the model eagerly. `[Verified, no fix needed]`: sentence_transformers is already imported with `retrieval`, so the cost is about 2.4 s of model load.
7. **Low** (code-review): the private `_rerank_model` swap can be bypassed silently. `[Verified, no fix needed]`: listed in the plan's Risks and visible as 0 hits; a guard test for the names was added (from `/simplify`).
8. **Low** (code-review): unbounded growth. `[Verified, no fix needed]`: 1.9 MB after three full runs of each tool; deleting the directory is safe.
9. **Low** (code-review): the connection is never closed, which could leave WAL files. `[Verified, no fix needed]`: none were left after 7 full runs.
10. **Nit** (arch): `call_key` unannotated, BACKLOG item under the wrong heading, Review log empty. `[Fixed]`.
11. **/simplify**: length check moved into `ScoreStore.get`, spy classes in the manual script merged, guard test added. `[Fixed]`. Skipped as marginal: shared CLI wiring for two callers, deriving `path` from the store, the per-tool wiring tests.
12. security-reviewer: no findings. Checked SQL parameterization, deserialization (JSON, not pickle), path construction (a hex digest), and log content.

## Round 2

Delta: `git diff 145b616`. Passes: `/code-review` low, `arch-reviewer` (sonnet), `security-reviewer`.

1. **Medium** (code-review low): `torch.device` and `torch.dtype` in the identity would make `json.dumps` raise. `[Verified, no fix needed]`: `cache_path` stringifies every part first, and live runs through `install` succeeded.
2. **Low** (arch): `BACKLOG.md` cited this file before it existed. `[Fixed]`: this file.
3. **Nit** (arch): `CachedReranker` takes both `store` and `path`. `[Verified, no fix needed]`: the storeless case needs the path.
4. security-reviewer: no findings.

## Live verification

- `tests/manual/verify_rerank_cache.py`, before and after the fixes: 3 real calls (72, 72, 71 pairs), cold vs plain `predict` 0.0, warm vs cold 0.0 with 0 model calls. Diagnostic split-vs-one-call 1.9e-6 to 2.4e-6, which confirms the call-level key was needed.
- Full acceptance on the round 1 code (plan step 7): gate cold and warm `--compare` against an uncached reference both exit 0 (1,480 runs, 471 refused then and now); warm 257 s vs 3,420 s uncached, 834 hits / 0 misses. Retrieval cold and warm match the uncached reference exactly (556/981 hit@5, 37/40); warm 169 s vs 2,403 s.
- After the round 1 fixes (new identity, so a fresh file): a `--qid nvda-revenue-fy26` gate slice cold (0 hits, 6 misses), then warm `--compare` exit 0 (6 hits, 0 misses). The open-failure path fired live: one stderr line, `disabled at open`, scoring carried on.

## Outcome

Shipped the cache with both CLIs wired, 24 unit tests plus CLI tests, and the manual repro. Open in `BACKLOG.md`: an on-disk `hybrid_search` result cache **[performance, Low, Standard]**, dormant because the measured warm gate replay (257 s) is under its ~10 min trigger. Final suite: 1279 passed. The review closed clean after 2 rounds: 10 fixed (counting the /simplify edits as one), 8 verified with no fix needed, 0 deferred, 0 disputed.
