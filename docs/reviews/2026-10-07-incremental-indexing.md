# Review: incremental indexing for `index_chunks`

No paired repo plan, since this was Standard by design tier. `index_chunks` now embeds only new or changed chunk files. It keeps a per-file sha256 manifest and an embedding recipe in the `corpus_identity.json` sidecar. A pure `plan_index_update` decides between a full rebuild and add/replace/delete, and a live `build_index` adds a `--full` flag. The suite had 1,384 tests before review. The diff was about 590 changed lines, so the review ran Substantial-depth passes.

## Round 1

Passes: `/code-review` high, `arch-reviewer` (sonnet), `security-reviewer`, `/simplify` (reuse, simplification, efficiency, altitude).

1. **High** (code-review): the sidecar was cleared and rows deleted before the changed files were read or encoded, so any load or model failure turned a one-file update into a ~20 min full rebuild. `[Fixed]` Read and encode now come before any mutation. The manual script was red on the pre-fix snapshot and green after.
2. **Medium** (code-review): delete-by-accession isn't scoped to a ticker. `[Verified, no fix needed]` Ids are `{accession}_{chunk_index}`, so the id scheme already requires globally unique accessions, and a duplicate would also collide in `add`. The real corpus has 61 distinct filenames. The post-build count check catches a violation, and the next run rebuilds fully.
3. **Medium** (code-review): the sidecar doesn't record whether the index came from a full or an incremental build, so HNSW tie drift after incremental runs is invisible in eval records. `[Deferred → BACKLOG]` Surfacing it means changing `corpus_provenance` and the eval record shape. Until then the rule is to run `--full` before a baseline.
4. **Low** (code-review): each file is read twice, once to hash and once to parse. `[Verified, no fix needed]` The chunker and indexer run one after the other in a single-user CLI, and the extra I/O is negligible next to embedding.
5. **Medium** (code-review): the recipe omits the torch and transformers versions and the HF model revision. `[Disputed]` Neither package is pinned, so every unrelated upgrade would force a ~20 min rebuild over float-level drift. The rule of running `--full` before a baseline already covers eval comparability, and `INDEX_RECIPE_VERSION` covers deliberate encode changes.
6. **Medium** (code-review): when every chunk file was removed, the run skipped the deletes. `[Fixed]` The empty-corpus early return now applies only to a full rebuild, which deliberately refuses to wipe the index on an empty chunks directory.
7. **Low** (code-review): a blank line crashed the load after mutation. `[Fixed]` Superseded by round 6: a blank line raises before any mutation.
8. **Low** (code-review, arch): edited comments pointed at decision-file paths. `[Fixed]`
9. **Low** (code-review): `load_all_chunks` was dead in production. `[Fixed]` Deleted, and its tests repointed.
10. **Low** (code-review): stale `clear_identity_sidecar` docstring, and a double collection count. `[Fixed]`
11. Arch nits (`build_index` length, the narrowing asserts, the import style): `[Verified, no fix needed]` ruff passes, and a tail helper would trip PLR0913.
12. `/simplify`: no edits. Each finding was either a plan or plan-review choice (the backward-compatible sidecar fields, `build_manifest`, `IndexResult`, the triggers list), outside this diff (`retrieval.py` duplication, see round 4), or negligible.

Security: no findings.

## Rounds 2–7

Deltas were reviewed against stash snapshots `623d324` → `510dc8c` → `976e20c` → `352b663` → `40f39ed` → `035161d`. Rounds 2–6 ran `/code-review` high and `security-reviewer`; round 7 ran `/code-review` low and `security-reviewer`. Security had no findings in any round.

- **Validation before mutation** (rounds 2–3): ids are built by a pure, unit-tested `chunk_ids` and checked for uniqueness before the sidecar is cleared. The guarantee is bounded on purpose. A malformed file, a missing or repeated id, or a model failure raises with the previous build intact. A failure inside Chroma after that point still leaves no sidecar, so the next run rebuilds fully. Three rounds kept raising pre-mutation checks, so the comment states the bound rather than chasing each Chroma rejection. `_recreate_collection` re-checks existence right before deleting.
- **Loader vs. count** (rounds 2–6, a single root cause): the loader and `_scan_chunk_files`' count split lines differently. Successive rounds patched symptoms: a blank-line skip that diverged from `retrieval.py`'s BM25 reader, Unicode whitespace, and decode-error positions. Round 6 fixed the root. `load_chunks` now uses the same `bytes.splitlines()` as the count and decodes per line. The counts agree by construction, every parse or decode error carries `in <path> line <n>`, and blank lines raise as the BM25 reader does. On the real corpus: 61 files, 7,572 records, which equals the identity count, with 7,572 unique ids.
- **Visibility** (rounds 4–5): `index_build_aborted` is logged with the mode, error, notes and identity. The real line was read.
- **Deferred** (round 4): `retrieval.py` keeps its own chunk reader and `_make_id`. `[Deferred → BACKLOG]` It's ranking-path code that needs a live-eval spot-check.
- Smaller fixes: the ticker-label sort, the manual script's patch restore and exact exception types, and per-case note checks.

## Live verification

- `tests/manual/verify_incremental_index.py` runs 7 steps with 47 checks against a real Chroma store and the real model: full build, no-op, replace/add/remove, recipe change, corrupt sidecar, five bad-file cases, and all files removed. The pre-fix snapshots failed steps 6 and 7, and the duplicate-id case failed with its guard disabled.
- Real corpus, first run: a full rebuild in 1,091.5 s (7,572 chunks, corpus `d703a4290869`). Later runs: "Index up to date". `verify_retrieval.py` returned sane hits.

## Outcome

Shipped as above. Still open in `BACKLOG.md`:
- `[misc, Low, Standard]` record the build mode for eval records;
- `[refactor, Low, Standard]` have `retrieval.py` share the chunk reader.

Final suite: 1,389 passed, `index_chunks.py` at 100%. The review closed clean in round 7.
