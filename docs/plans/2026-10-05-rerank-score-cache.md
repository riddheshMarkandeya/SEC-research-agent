# Persistent cross-encoder score cache for the replay tools

## Context

`analyze_gate_replay` and `retrieval_replay` are slowing development down.
- **Gate replay:** today's package-3 baseline took 3,600 s and its `--compare` took 3,395 s.
- **Retrieval replay:** a full run takes 33–70 min.
- **The docstrings are out of date:** they still say "about 18 minutes".

The rerank is the main cost:
- Each gate replay re-runs the cross-encoder for every one of the ~994 unique logged searches.
- `memoized()` (`analyze_gate_replay.py:436`) caches only within one process, so a gate-only change pays for every rerank twice: once for the baseline, once for the compare.
- Package 5's windowed MaxP tripled the cost per search: base-v0 took 1,432 s, v6 4,134 s.

We cache across runs rather than shrink the replayed history. The history is the regression corpus.

**Fix:** a persistent, content-addressed cache of cross-encoder scores, keyed by the **exact ordered list of (query, window) pairs in one `predict` call**. It applies only in the two replay tools, never in production retrieval.
- **Bit-exact by construction.** `CrossEncoder.predict` sorts its pairs by length and batches them, so a pair's float32 score can depend on which other pairs share the call. Keying on the whole call means a hit returns exactly what the same call would have computed.
- **It can't go stale when retrieval code changes.** A changed pool or windowing produces different pairs, which miss.
- **It still hits wherever replays repeat work.** A gate replay re-scores the same pools. A `--fused-floor` or rescue variant scores the same pool with the same windows.

**Expected result.** A warm gate replay or `--compare` should get much faster. The target ("minutes") gets checked against a profile first: the unexplained 3–5 min fixed cost of a `--qid` slice may set a floor, and that floor is out of scope here.

**User decisions (2026-10-05):**
- Option 2, this cache, only.
- Option 1 (an on-disk `hybrid_search` result cache with a retrieval fingerprint) becomes a `BACKLOG.md` item. Its trigger: a warm full gate replay still over ~10 min.
- Package 3's uncommitted work is left alone. This plan assumes the user finishes and commits it separately.

**Tier:** Substantial (small). It's a new devtools module. No critical-core file is edited. `retrieval._rerank_model` is swapped at runtime, the same way `install_live_search` already swaps `dispatch.hybrid_search`. `_get_rerank_model` returns any non-None singleton (`retrieval.py:99-103`), and `_token_counter` reads only `.tokenizer` (`:106-110`).

## Design

### New module `src/sec_agent/devtools/rerank_cache.py`

**Pure parts (unit-tested):**
- `cache_path(cache_dir, identity_parts) -> Path`. The file is `<cache_dir>/<sha256[:16] of identity>.sqlite`, where identity is `RERANK_MODEL_NAME`, `model.max_length`, `sentence_transformers.__version__` and `torch.__version__`. A model or library upgrade starts a fresh file.
- `open_store(path) -> ScoreStore | None`:
  - creates the directory;
  - opens SQLite with WAL;
  - creates the table `calls(key BLOB PRIMARY KEY, scores TEXT)`, where scores is a JSON list of floats (float32 → float64 → JSON round-trips exactly);
  - on `sqlite3.Error` or `OSError`, prints one `[rerank_cache] disabled: <reason>` line to stderr and returns None.
- `ScoreStore.get(key) -> list[float] | None` and `ScoreStore.put(key, scores)`. `put` is `INSERT OR IGNORE` and commits.
- `CachedReranker(model, store)`:
  - `predict(pairs, **kwargs)`:
    - If kwargs are given, bypass the cache (they would change the scores), calling `model.predict` straight through.
    - Otherwise compute key = sha256 of the JSON-encoded ordered pairs, then `store.get`.
      - Hit: return `np.asarray(scores)`.
      - Miss: `model.predict(pairs)`, then `store.put`, then return it.
    - Empty `pairs` never reaches it, because `_window_scores` guards (`retrieval.py:397`).
  - A `sqlite3.Error` raised from `get` or `put` mid-run (e.g. `SQLITE_BUSY`) prints one `[rerank_cache] disabled mid-run: <reason>` warning, drops the store, and serves this call and every later one uncached. A cache failure must never show up as a replay error. In gate replay it would otherwise land in `rebuild_results`' broad except (`analyze_gate_replay.py:222-226`) as a false difference, and in retrieval replay it would abort `run_all`.
  - `__getattr__` forwards everything else, `.tokenizer` included.
  - Counts `hits` and `misses` per call.
  - The model is assigned through `setattr(retrieval, "_rerank_model", ...)` if pyright objects to the type. That gets checked in step 3.
- `stats(reranker) -> dict | None` returns `{"path", "hits", "misses", "disabled"}`.

**Live part, `install(enabled) -> CachedReranker | None`** (`# pragma: no cover`):
- Returns None when disabled.
- Idempotent: if `retrieval._rerank_model` is already a `CachedReranker`, it returns that one. `tests/manual/verify_gate_replay.py:43` already calls `install_live_search()`.
- Otherwise it loads `retrieval._get_rerank_model()`, builds `cache_path(config.VAR_DIR / "rerank_cache", ...)`, and calls `open_store`. If that gives None, the run goes ahead uncached. Otherwise it wraps the model and assigns it.
- The docstring says that a changed model behind the same name (a new HF revision, or a local path whose weights change) isn't detected. In that case, delete `var/rerank_cache/` or pass `--no-rerank-cache`.

### The two CLIs

- Both get a `--no-rerank-cache` flag.
- Each `main` calls `rerank_cache.install(not args.no_rerank_cache)` just before its replay loop: in gate replay before `_replay_all`, in retrieval replay before `run_all`. `install_live_search()` and `_live_retriever` keep their signatures, so their existing stubs still work.
- Each puts `rerank_cache: stats(reranker)` into the report header, and adds `rerank cache: N hits, M misses` to the printed summary.
- Existing `main` tests stub `rerank_cache.install` (a `cli` fixture or `monkeypatch`), so no test opens the real `var/` cache.

**Logging (§2).** Replays deliberately send trace events nowhere: they'd otherwise land in the trace log being read. So the channels are stderr plus the JSON report header. They answer three questions:
1. Was the cache on, and which file did it use?
2. How many calls did it save?
3. Was it turned off, and why: at open, or mid-run?

### Doc updates (same change)

- **Both docstrings' timing paragraphs:** measured cold vs warm figures, and the note that a run that changes pools or windowing scores those queries fresh.
- **`.claude/rules/live-code-tdd.md`:** add `rerank_cache.py`. `install` loads the real cross-encoder.
- **`BACKLOG.md`:** the option-1 item, tagged `[performance, Low, Standard]`, with the measured warm runtime and the ~10 min trigger.
- A separate `[performance]` item for the fixed startup cost if the profile shows a large one. Not fixed here.
- Save this plan as `docs/plans/2026-10-0X-rerank-score-cache.md`, with a `PROJECT_INDEX.md` Recent line.

## Steps

0. **Precondition:** package 3 is committed by the user. Run `git status`, and branch `replay-rerank-cache` from `master`. Copy this plan to `docs/plans/`.
1. **Profile first** (read-only on code). cProfile a gate-replay `--qid` slice, plus one retrieval-replay `--qid` slice, sending the output to the scratchpad. Record the split between startup (models, BM25, Chroma), `predict`, and everything else. That sets the realistic warm target and the expectations in the BACKLOG item.
2. **Manual repro** (`tdd-live-code-carveout`): `tests/manual/verify_rerank_cache.py`, using real pairs from a few logged queries and a temp db. It reports:
   - cold `CachedReranker` vs plain `predict` on the same call: max abs diff, expected 0.0;
   - warm vs cold: max abs diff 0.0, with 0 model calls when warm;
   - the same pairs scored as two separate calls vs one: max abs diff. This one is diagnostic. It records whether pair-level keying would have been safe, as a note for later.

   Expect it to fail first (no module), then pass.
3. **TDD `tests/devtools/test_rerank_cache.py`**, with a fake model that counts calls and scores deterministically:
   - a miss is predicted and stored, and a repeated call is a hit with no model call;
   - a different pair order or contents misses;
   - kwargs bypass the cache;
   - a second `ScoreStore` on the same file sees the hit (persistence);
   - `cache_path` changes with each identity part;
   - `open_store` on an unopenable path (e.g. under a path that is a file) returns None and prints the warning;
   - a store whose `get` or `put` raises `sqlite3.Error`: the call returns the model's scores, one warning is printed, later calls go uncached, and `stats` shows `disabled`;
   - `.tokenizer` forwarding;
   - hit and miss counts.

   Run pyright on the new module here.
4. **CLI wiring:**
   - `--no-rerank-cache` reaches `install` as `enabled=False`;
   - the header carries what the stubbed `install`/`stats` return;
   - the existing `main` tests still pass with `install` stubbed.
5. **Docs and rule updates** listed above.
6. **Checks:** `ruff check .`, `pyright .`, then `pytest --cov=. --cov-report=term-missing -q` written to a scratch file. Changed lines must meet the 80% bar; the pragma'd lines are excluded.
7. **Live acceptance against uncached references.** Runs go in the background, and runtimes are recorded.
   - **Gate full:**
     1. Get an uncached reference on this exact code. Reuse a `--no-rerank-cache`-equivalent baseline only if the code it ran is identical; otherwise run `--no-rerank-cache --out ref.json` once (about 1 h).
     2. Cold cached run: `--compare ref.json`. Must exit 0.
     3. Warm cached run: `--compare ref.json`. Must exit 0, show about 0 misses, and its runtime is recorded.

     Exit 0 proves the formatted top-k (order, headers, text: `content_sha256`, `tool_results.py:24-37`) and every verdict match. It doesn't compare raw scores; step 2 covers those.
   - **Retrieval:** `--compare var/retrieval_replay/pkg5-f3-r2.json` (an uncached run; or the newest base matching master's retrieval code), cold then warm. No lost hits either time, and the warm `runtime_s` is recorded. Then a warm `--fused-floor 0` run must reproduce the recorded F=0 figures (599, 34/40) with about 0 misses.
   - Write the BACKLOG item(s) with the measured numbers.
8. Compact checkpoint line, then `independent-review-pass` by the actual diff. Commit only on the user's request.

## Risks

- **Pools that change partly miss in full.** A scoping or windowing change re-scores every affected query fresh, so it costs a cold run, which is still correct. Pair-level reuse was dropped for bit-exactness (plan review, finding 1). Step 2 records whether it would have been safe, in case it's worth revisiting.
- **A changed model behind the same name isn't detected.** This is documented, with two remedies: delete the directory, or pass `--no-rerank-cache`.
- **Disk:** one row per unique call, about 10³–10⁴ rows, a few MB. `var/` is gitignored, and deleting the directory is always safe.
- **A private attribute swap:** if retrieval renames `_rerank_model`, the replay runs uncached and the header's 0 hits make it visible.
- **The warm target may be floored by the fixed startup cost.** Step 1 measures it, and a BACKLOG item records it.

## Verification summary

- **Unit tests:** step 3, plus the CLI tests in step 4.
- **Raw-score equality on real data:** step 2.
- **End-to-end faithfulness and speed:** step 7. It compares against **uncached** references and records cold vs warm runtimes for both tools.

## Plan review

Reviewer: plan-reviewer (opus), one round. Every finding is folded in.

1. **[High, folded]** A pair-level key isn't bit-exact: `predict` sorts by length and batches, so a pair's score can depend on its batch-mates. Step 6's cold-vs-warm test couldn't catch this, because both runs used the cache. Fix: a call-level key (exact by construction), and acceptance against uncached references (step 7).
2. **[High, folded]** A SQLite error mid-run would become a false replay difference, or abort retrieval replay. Fix: catch it inside `predict`, warn once and go uncached, with a unit test.
3. **[Med, folded]** The wiring didn't match the code: `install_live_search` is called from `_replay_all`, and the existing stubs take fixed arities. Fix: install from each `main`, keep the signatures, and stub `rerank_cache.install` in tests.
4. **[Med, folded]** Two behaviours had no test seam. Fix: pure `cache_path` and warn-and-disable `open_store`, both unit-tested, and the directory gets created.
5. **[Med, folded]** "Almost all the time is rerank" was unproven, and the fixed startup cost is unexplained. Fix: profile first (step 1), and the warm target is now hedged.
6. **[Low, folded]** `predict` kwargs weren't in the key. Fix: kwargs bypass the cache.
7. **[Low, folded]** A second install would double-wrap. Fix: `install` is idempotent.
8. **[Low, folded]** A changed model behind the same name isn't detected. Fix: documented, with its remedies.
9. **[Low, folded]** The pyright result of assigning `_rerank_model` was unchecked. Fix: checked in step 3, with `setattr` as the fallback.

## Results (2026-10-05, branch `replay-rerank-cache` off `63114b9`)

**Step 1, profile (cProfile, `--qid nvda-revenue-fy26`):**
- Gate replay: 81 s total (85 s wall) for 27 runs and 6 searches. `predict` 45 s (55%), imports about 22 s, `_get_rerank_model` 2.4 s, `split_windows` 3.1 s (about 0.5 s per search), pool building about 1.1 s.
- Retrieval replay: 69 s total, `predict` 34 s, imports about 22 s.
- The 3-5 min fixed cost of a slice was not reproduced: startup is about 22-30 s. No startup BACKLOG item.

**Step 2, manual repro (`tests/manual/verify_rerank_cache.py`):** 3 real calls (72, 72, 71 pairs). Cold vs plain `predict` 0.0, warm vs cold 0.0 with 0 model calls, stats 3 hits / 3 misses: OK. Diagnostic, the same pairs as two calls vs one: 1.9e-6, 2.4e-6, 1.9e-6, so a pair-level key would not have been bit-exact (finding 1 confirmed).

**Step 6, checks:** `ruff check .` clean, `pyright .` 0 errors, 1274 passed, total coverage 97%; `rerank_cache.py` 100%, `analyze_gate_replay.py` 100%, `retrieval_replay.py` 98% (its missing lines are pre-existing).

**Step 7, live acceptance.** Neither existing reference ran this code (`pkg5-f3-r2.json` and `pkg5-f0.json` are at `9143665`, before package 5's retrieval changes), so both tools got fresh uncached references. One shared cache file, `var/rerank_cache/c061bdb2c9c28f3a.sqlite`, 1.9 MB after all runs.

| Run | Exit | Wall | Cache |
|---|---|---|---|
| gate, `--no-rerank-cache` (reference) | 0 | 3,420 s | off |
| gate cold, `--compare` ref | 0 | 3,278 s | 0 hits, 834 misses |
| gate warm, `--compare` ref | 0 | 257 s | 834 hits, 0 misses |
| retrieval, `--no-rerank-cache` (reference) | 0 | 2,403 s (`runtime_s` 2,390) | off |
| retrieval cold, `--compare` ref | 0 | 566 s | 454 hits, 97 misses |
| retrieval warm, `--compare` ref | 0 | 169 s (`runtime_s` 159.1) | 551 hits, 0 misses |
| retrieval warm `--fused-floor 0`, `--compare` ref | 1 (expected) | 170 s | 551 hits, 0 misses |

- Gate: 1,480 runs replayed, 0 errored, 109 drifted; refused 471 then and now; 0 recovered, 0 newly refused, 0 check changes, 0 tool-result drift, identically cold and warm.
- Retrieval (reference, cold, warm): 981 parts, hit@5 556 (56.7%), reach 960 (97.9%), 37/40 covered; deltas none.
- The retrieval "cold" run was already 82% warm: the gate runs had scored most of the same calls, so the two tools share the cache usefully.
- F=0 warm: hit@5 655 (66.8%, +99 vs F=3), 34/40 covered (lost `aapl-employees-fy25-indirect`, `nvda-inventory-turnover-fy2026`, `nvda-revenue-two-quarter-comparison`). The recorded 599 hits came from `9143665` on 901 parts, so they can't reproduce; the 34/40 coverage does.
- Speedup warm vs uncached: gate 13x (57 min to 4.3 min), retrieval 14x (40 min to 2.8 min). The warm gate replay is under the ~10 min option-1 trigger, so that BACKLOG item stays dormant.

## Review log

Diff re-classified at review time: Substantial (about 700 lines with tests and docs; Substantial design tier). No high-risk path: `src/sec_agent/retrieval/` is untouched. Round 1 snapshot: `git stash create` → `145b616`.

**Round 1.** Passes: `/code-review high`, `arch-reviewer` (sonnet), `security-reviewer`, `/simplify` (4 angles).
- security: no findings.
- [Fixed] (code-review) The cache identity covered only the model name, max_length and library versions, so a change to `activation_fn`, dtype, device or the Hugging Face revision behind the same name would reuse stale scores and hide exactly the change `--compare` exists to measure. The identity now adds the revision (`config._commit_hash`), `max_seq_length` (`max_length` is deprecated), `repr(activation_fn)`, device and dtype. This also closes the plan's "same-name model change" risk for Hugging Face models; only a local path whose weights change stays undetected. The new identity starts a new file (`3c188f875f7dab21.sqlite`), so the step 7 file `c061bdb2c9c28f3a.sqlite` is now unused.
- [Fixed] (code-review, arch) A corrupt row (bad JSON) raised an uncaught `ValueError`, and a wrong-length row was served unchecked. `ScoreStore.get(key, count)` now raises `ValueError` for both, and `predict` disables the cache mid-run as for a `sqlite3.Error`. Test: corrupt and wrong-length rows written into a real file.
- [Fixed] (code-review, arch) A hit returned float64 while a miss returned float32. Hits now return float32 (float32 → float64 → float32 is exact). Test: hit dtype.
- [Fixed] (code-review, arch) A store that failed to open left the header `null` / "off", the same as `--no-rerank-cache`. `install` now installs `CachedReranker(model, None, path)` with `disabled: "at open"`, which runs uncached. Test: storeless reranker. Fired live once against a file blocking `VAR_DIR`: one `[rerank_cache] disabled: [WinError 183] …` line, summary `…, disabled at open`, and scoring carries on.
- [Fixed] (arch, nit) `call_key` annotated; BACKLOG item moved under its own heading; this log filled in.
- [Fixed] (/simplify) The length check moved into `ScoreStore.get`, which removes a raise-then-catch in `predict`; the manual script's two spy classes merged into one; a guard test that `retrieval._rerank_model` and `_get_rerank_model` still exist (a rename would otherwise turn the cache off silently).
- [Verified, no fix needed] (code-review) `install` idempotence keeps an earlier reranker and its counts when `main` runs twice in one process. Nothing does that: both tools are CLIs, and their tests stub `install`.
- [Verified, no fix needed] (code-review) `install` loads the model before the replay, even for a slice with no searches. `retrieval` imports sentence_transformers at module load anyway, so the extra cost is the model load (about 2.4 s, profiled).
- [Verified, no fix needed] (code-review) The private `_rerank_model` swap could be bypassed silently by a retrieval refactor. Already in Risks; the header's 0 hits shows it, and the new guard test catches a rename.
- [Verified, no fix needed] (code-review) The store only grows. 1.9 MB after 3 full runs of both tools; deleting the directory is documented as safe.
- [Verified, no fix needed] (code-review) The store's connection is never closed, which could leave `-wal`/`-shm` files. None were left after the 7 acceptance runs: Python closes and checkpoints the connection at exit.
- Skipped (/simplify, marginal): shared CLI wiring for two callers (altitude said not to build it for two), deriving `path` from the store, the duplicated per-tool wiring tests.
- After the fixes: `ruff check .` clean, `pyright .` 0 errors, 1279 passed, `rerank_cache.py` 100%; `verify_rerank_cache.py` OK (0.0 diffs, 0 warm model calls); a `--qid nvda-revenue-fy26` gate slice cold (0 hits, 6 misses) then warm `--compare` exit 0 (6 hits, 0 misses).


**Round 2** (delta `git diff 145b616`). Passes: `/code-review low`, `arch-reviewer` (sonnet), `security-reviewer`.
- security: no findings.
- [Verified, no fix needed] (code-review) `torch.device`/`dtype` in the identity would break `json.dumps`. `cache_path` stringifies every part first, and live runs through `install` succeeded.
- [Fixed] (arch) BACKLOG cited a review file that didn't exist yet: `docs/reviews/2026-10-05-rerank-score-cache.md` written and indexed (Recent trimmed to 40, the oldest 11 moved to the archive).
- [Verified, no fix needed] (arch, nit) `CachedReranker` takes both `store` and `path`: the storeless case needs the path.
- No executable finding, so the review is done: 2 rounds, 10 fixed, 8 verified with no fix needed, 0 deferred.
