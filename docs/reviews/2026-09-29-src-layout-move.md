# Review: `src/` layout move (commits `138af8c`, `e5cef19`, `6f62735`)

Plan: `docs/plans/2026-09-29-src-layout-move.md`. The change moves the code into `src/sec_agent/`
and `tools/` (editable install) and anchors generated data under a root `var/`. Before this diff
the suite had 1043 tests. The diff touches critical core throughout, so it got the Substantial
passes.

## Round 1

Diff: `git diff -M 5f543a4..HEAD`. Passes: `/code-review` high, `arch-reviewer` (opus),
`security-reviewer`, `/simplify` (reuse, simplification, efficiency and altitude agents).

1. **High** (code-review): `xbrl_facts.fetch_concept`/`fetch_frame` and
   `discover_tags.fetch_company_facts` ran `CACHE_DIR.mkdir(exist_ok=True)`. The cache is now one
   level deeper (`var/xbrl_cache`), so a fresh clone without `var/` got a `FileNotFoundError`.
   `[Fixed]`: `parents=True` in all three places, and on `eval_harness`'s `RESULTS_DIR.mkdir`.
   The altitude agent suggested creating `VAR_DIR` when `config` is imported instead. Skipped:
   that makes every import touch the filesystem.
2. **Med** (code-review): provenance now records `chroma_dir: "var/chroma_db"` where pre-move
   reports have `"./chroma_db"`. `compare_prompt_versions` compares the whole config dict, so
   comparing a new report with a pre-move baseline prints one "config differs" warning.
   `[Verified, no fix needed]`: the setting really did change, and the warning appears once per
   pre-move baseline. Anyone comparing across the move should read it as the store path only.
3. **Med** (code-review): an old `.env` with `CHROMA_DIR=./chroma_db` now resolves to
   `<root>/chroma_db`, which is empty after the data move. `[Verified, no fix needed]`:
   `retrieval._get_chroma_collection` calls `get_collection`, which raises on a missing collection, so
   the failure is loud, not an empty result. The user's `.env` and `.env.example` are updated.
4. **Low** (code-review): `PROJECT_ROOT` is wrong under a non-editable `pip install .`.
   `[Verified, no fix needed]`: this was accepted in the plan's Risks, and the setup docs say `-e`.
5. **Low** (code-review): with `TRACE_LOG_PATH=""`, `analyze_gate_replay`'s default `--file` and
   `--out` resolve against the cwd. `[Verified, no fix needed]`: an empty setting disables the
   trace log, so there is nothing to replay unless `--file` is passed.
6. **Low** (code-review): the `RESULTS_DIR` comment still said "Anchored to this file".
   `[Fixed]`: the constant moved to `config` and the comment went with it.
7. **Low** (code-review): `test_env_overridable_defaults_live_under_var` passed the default literal
   into `env_path` instead of checking config's real defaults. `[Fixed]`: a `reload_config`
   fixture re-runs `config.py` with `.env` loading stubbed out and checks `CHROMA_DIR` and
   `TRACE_LOG_PATH`.
8. **Low** (code-review, arch): the eval question and results paths were built in three modules.
   `[Fixed]`: `config.QUESTIONS_PATH`/`RESULTS_DIR` are now the only definitions. `eval_harness`,
   `compare_prompt_versions`, `trace_query`, `analyze_gate_replay` and `verify_gate_replay`
   import them.
9. **Low** (code-review, arch): `eval_harness.REPO_ROOT = PROJECT_ROOT` was a leftover alias.
   `[Fixed]`: removed, and its callers and tests use `PROJECT_ROOT`.
10. **Nit** (arch, 16 items): comments and docstrings still cited old flat test paths
    (`tests/test_agent.py` and others), `python X.py` commands, and `trace_logs/` or `./chunks/`
    without `var/`. The `BACKLOG.md` item deletion also left a double blank line. `[Fixed]`.
11. **Q** (arch): the generic top-level `tools` package name can be shadowed by another
    distribution, or by `tests/tools` when the cwd is `tests/`. `[Deferred → BACKLOG]`:
    `tools/` was the approved plan, so the rename is a user decision. It is filed as
    `[misc, Low, Small]` to settle before the `agent.py` split.
12. **Low** (simplify, simplification): `PROVENANCE_PATHSPECS` retyped paths that already exist as
    constants. `[Fixed]`: derived from `SNAPSHOT_PATH.parent`, `COMPANIES_PATH` and
    `QUESTIONS_PATH`. A guard test asserts that each pathspec is repo-relative and exists.
13. **Low** (simplify, simplification and altitude): the config test's reload helper and its
    restore fixture were separate. The restore reload also ran before monkeypatch had undone the
    env and dotenv patches, so `config` could stay patched for later tests. `[Fixed]`: one
    fixture that calls `monkeypatch.undo()` before its restoring reload. A throwaway follow-on
    test confirmed the real values come back.
14. **Nit** (simplify, simplification): `CACHE_DIR = XBRL_CACHE_DIR` aliases in two modules.
    `[Verified, no fix needed]`: kept on purpose so existing `module.CACHE_DIR` monkeypatch targets
    keep working (plan, commit 2).
15. security-reviewer: no findings. It checked path handling (env-supplied paths are operator
    config, not a trust boundary), `.env` loading, the subprocess argv lists, package-data
    contents and `mcp_server` (import rewrites only). The efficiency and reuse agents found
    nothing to change.

## Round 2

Delta: `git diff HEAD` (snapshot `6f62735`). Passes: `/code-review` low, `arch-reviewer`
(sonnet; its first run died on a network error and was re-run), `security-reviewer`.

1. **Med** (code-review): the derived `PROVENANCE_PATHSPECS` called `relative_to(PROJECT_ROOT)` on
   `Path(__file__)`-based paths without resolving them. `PROJECT_ROOT` is resolved, so opening the
   checkout through a symlink, a junction or a `subst` drive made `import eval_harness` raise
   `ValueError`. `[Fixed]`: `.resolve()` per path. The `COMPANIES_PATH` import also moved off the
   comment that describes the `llm_backends` import.
2. **Nit** (arch): the `test_retrieval` docstring line next to an edited one pointed at the
   renamed `PROJECT_CONTEXT.md`. `[Fixed]`: the pointer was dropped.
3. security-reviewer: no findings.

## Round 3

Delta: the round-2 `PROVENANCE_PATHSPECS` fix. Passes: `/code-review` low, `security-reviewer`.
Both came back clean: the three pathspecs are unchanged, and nothing that feeds them is
controlled by input.

## Live verification

This was done before the review, since the review fixes change no live path's behaviour. The
gate replay was identical over 1211 runs after each code commit. The retrieval, MCP server and
gate-replay manual scripts passed. One live question was answered with a citation, and its trace
lines went to `var/trace_logs`. Details are in the plan's Testing section and the commit bodies.

## Outcome

The review fixes are committed on top of the three commits. One item is open in `BACKLOG.md`:
the `tools` package rename, `[misc, Low, Small]`, which is the user's call. The suite finished
at 1051 passed. The review closed clean after 3 rounds: 16 findings, 10 fixed, 5 verified with
no fix needed, and 1 deferred.
