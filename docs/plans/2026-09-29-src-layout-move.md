# `src/` layout move (agent-improvement map, Decision 15)

## Context

This is prerequisite 4 of 6 in `docs/plans/2026-09-28-agent-improvement-map.md` (the NUMBER_PATTERN
fix, the replay tool and Ollama removal are done). Today all 23 modules sit flat at the repo root,
next to generated data dirs. The move puts the code in a `src/sec_agent/` package before the
`agent.py` split, so the split creates its new modules once, in their final place. It also
anchors the working-directory-relative data paths to the project root. That fixes the latent bug
BACKLOG line 54 describes (`xbrl_cache`/`trace_logs` resolved against the cwd) and lets
`analyze_gate_replay.require_repo_root` go.

Tier: Substantial. Critical core is touched throughout, so the blast-radius rules apply.

**User decisions (2026-09-29):**
- **Keep file basenames.** A pure move: `sec_agent/eval/eval_harness.py`,
  `sec_agent/agent/agent.py` and so on. Git sees renames, and history docs still match by name.
- **Critical core becomes directory globs, and widens.** Every file under `agent/`, `llm/`,
  `eval/`, `prompts/`, `sources/`, `retrieval/` and `verification/` becomes critical core. That adds
  `edgar_ingest`, `companies`, `period_labels`, `index_chunks` and `table_grounding` to the 90%
  bar, deeper plan review and the Opus arch review. Recorded in the map as a change to Decision 15.

## Decision / Design

### Target layout

```
src/sec_agent/
  __init__.py  config.py  tracing.py  mcp_server.py
  agent/         agent.py
  verification/  numeric_utils.py  table_grounding.py
  sources/       edgar_ingest.py  xbrl_facts.py  formulas.py  companies.py  companies.json  period_labels.py
  retrieval/     retrieval.py  chunk_documents.py  index_chunks.py
  llm/           llm_backends.py
  prompts/       (whole package, incl. model_input_snapshot.json)
  eval/          eval_harness.py
tools/  __init__.py  analyze_citation_gate.py  analyze_flakiness.py  analyze_gate_replay.py
        compare_prompt_versions.py  trace_query.py  discover_tags.py
scripts/check_docs_health.py        (unchanged: a git-hook helper, not an analysis CLI)
eval/eval_questions.jsonl, eval/eval_results/   (unchanged: committed evidence, and 156 history docs link to it)
var/  chroma_db/ chunks/ data/ xbrl_cache/ trace_logs/   (one gitignored dir; commit 2)
tests/ mirrored: tests/{agent,verification,sources,retrieval,llm,prompts,eval,tools}/test_*.py;
       test_config/test_tracing/test_mcp_server/test_check_docs_health at tests/; tests/manual stays.
```

- Each subpackage gets an empty `__init__.py`, with no re-exports: a re-export would make
  `patch("sec_agent.agent.X")` silently miss the real binding.
- Test subdirectories get **no** `__init__.py`. With pytest's default import mode, a regular
  package (`tools/`, `sec_agent`) then always wins over a namespace candidate such as `tests/tools`.
  The current basenames are all unique, so collisions can't happen.

**Install and invocation.** `pip install -e .` is **required**, not optional: the subprocess
tests and the manual scripts depend on it. It installs **both** `sec_agent` and `tools`:
`[tool.setuptools.packages.find] where = ["src", "."]`, `include = ["sec_agent*", "tools*"]`.
`requirements.txt` gains `-e .`, so the documented setup does it.
- Package CLIs run as `python -m sec_agent.agent.agent "…"` or `python -m sec_agent.eval.eval_harness`.
- Tools run as `python -m tools.trace_query …`, from any cwd.
- Tool-to-tool imports become `from tools import trace_query` (in `analyze_gate_replay` and
  `compare_prompt_versions`).
- pyright gets `extraPaths = ["src"]`. Two package roots make setuptools use its import-hook
  finder, which pyright can't follow.

## Files and steps

### Commit 1: the move (behaviour-identical, green on its own)

Commit 1 carries only what the tree needs to stay green after the renames: imports, string
targets, `__file__` anchors, tooling config and the hook's include list. Prose docs and usage
docstrings go in commit 3. `git diff --cached -M --stat` must show every moved file as a rename.

1. **Baseline, on master before any edit**, saved to the scratchpad:
   - `python analyze_gate_replay.py --out <scratch>/replay-base.json`. Record its
     `new_cache_files`; any cache seeding happens here, so later runs are like-for-like.
   - `prompt_fingerprint()` output.
   - The `pytest -q` pass count.
2. **`git mv`** every file to its target path, add the `__init__.py` files and the `pyproject`
   packaging, and run `pip install -e .`. **No code edits yet.**
2a. **Error inventory (user suggestion).** Run `pyright .`, `ruff check .` and
   `pytest -q --co` (collection), then `pytest -q`, each to a scratch file. That gives the list of
   what the move breaks loudly. pyright covers `tools/` and `tests/manual` too, which pytest never
   runs. Steps 3–5 then fix it, and the loop repeats until all three are clean. Every item in the
   error inventory must map to an edit, and any grep-planned edit that never showed up as an error
   must be explained. The mechanical bulk (imports, 293 mock strings) still goes through the
   scripted map rather than one hand edit per error.
   - **Silent breakages that raise nothing.** These stay an explicit checklist, because the error
     loop can't find them:
     - `PROVENANCE_PATHSPECS` `"prompts"` / `companies.json`: a pathspec matching nothing means a
       report is never marked dirty;
     - `SNAPSHOT_TEST`;
     - the `"agent.py"` file-name literals;
     - cwd paths that still resolve from the repo root (`eval/eval_questions.jsonl` defaults);
     - usage docstrings.
3. **Import rewrite, scripted from one module→package map.** It keeps the local name, so no body
   edits are needed:
   - `import config` → `from sec_agent import config`
   - `import xbrl_facts` → `from sec_agent.sources import xbrl_facts`
   - `from agent import X` → `from sec_agent.agent.agent import X`
   - tests' `import agent` → `from sec_agent.agent import agent`
   - `prompts.*` → `sec_agent.prompts.*`
   - `tests/conftest.py:8` (`import tracing`)
   
   It covers top-level and indented imports, the latter in `test_agent`, `test_mcp_server`,
   `test_model_input_snapshot` and `test_discover_tags`.
4. **String references the import rewrite misses:**
   - **293 mock-target strings.** Rewrite them with the same map, anchored on `patch("` /
     `setattr("` / `patch.object`-free string forms. Explicitly skip `"<name>.py"` file-name
     literals: `test_compare_prompt_versions.py:23` and `test_eval_harness.py:713,748,890,893,907`
     name `agent.py` as a file and must stay. Afterwards, grep for any quote-anchored old module
     prefix still left.
   - **Dynamic imports.** `prompts/__init__.py:29`: `import_module(f"prompts.{name}")` →
     `import_module(f"{__name__}.{name}")`. `test_prompts.py` gets the full `sec_agent.prompts.` path
     (4 calls).
   - **Subprocess children** get `src` on their path explicitly rather than relying on the install:
     - `test_prompts.py:50` `-c "import json, prompts…"` → `from sec_agent import prompts`,
       with `REPO_ROOT/"src"` on the child's path;
     - `test_model_input_snapshot.py:493-499` → `[REPO_ROOT/"src", REPO_ROOT/"tests"/"prompts"]`;
     - `tests/manual/verify_mcp_server.py:201` → `[sys.executable, "-m", "sec_agent.mcp_server", …]`.
   - **Test file paths:**
     - `test_prompts.py:104` `REPO_ROOT/"prompts"/…` → the package directory;
     - `test_model_input_snapshot.py:29` `SNAPSHOT_PATH` → `prompts.SNAPSHOT_PATH`;
     - `REPO_ROOT` in both tests → `config.PROJECT_ROOT`.
5. **`__file__`-anchored paths, which break on the move.** Add `PROJECT_ROOT =
   Path(__file__).resolve().parents[2]` to `config.py`, and use it for:
   - `eval_harness.REPO_ROOT`, `RESULTS_DIR` and `QUESTIONS_PATH`;
   - `compare_prompt_versions.RESULTS_DIR`;
   - `analyze_gate_replay`'s `require_repo_root` root and its `--questions` default;
   - `trace_query`'s `--questions` default;
   - `test_analyze_gate_replay.py:567` (`require_repo_root(Path(replay.__file__).parent)` →
     `PROJECT_ROOT`).
   
   `companies.json` moves beside `companies.py`, so `COMPANIES_PATH` still holds. Also update
   `eval_harness.PROVENANCE_PATHSPECS` (`"prompts"` → `"src/sec_agent/prompts"`, `companies.json`
   → its new path) and `SNAPSHOT_TEST` (→ `tests/prompts/…`).
6. **`tests/manual`:**
   - Remove the 11 `sys.path.insert` hacks. The editable install covers `sec_agent` and `tools`.
   - `verify_gate_replay.py:23,26`: its imports → `from tools import …`; `:31` `QUESTIONS` →
     `PROJECT_ROOT`.
   - `verify_period_labels.py:82` `open("companies.json")` → `companies.COMPANIES_PATH`.
7. **Tooling:**
   - `pyproject.toml`:
     - `[build-system]` (setuptools) and a minimal `[project]` (`name = "sec-agent"`,
       `requires-python = ">=3.13"`; dependencies stay in `requirements.txt`);
     - the `packages.find` above; package-data `*.json`;
     - pytest `pythonpath = ["src", "."]`, kept as a fallback for in-process imports;
     - pyright `extraPaths`;
     - coverage `source = ["."]` kept, so `coverage.xml` paths stay repo-relative
       (`src/sec_agent/...`) and match diff-cover's `git diff` paths.
   - `requirements.txt`: add `-e .`.
   - `.claude/rules/*.md` frontmatter:
     - `plan-review-blast-radius.md` → the seven directory globs (`src/sec_agent/agent/**` …);
     - `live-code-tdd.md` and `live-eval-verification.md` → exact new paths for the same files
       (e.g. `tools/analyze_gate_replay.py`).
   - `githooks/pre-push` `--include`: the same seven globs, quoted (`'src/sec_agent/agent/**'`).
     diff-cover expands them with `glob(recursive=True)`.
8. **Checks:**
   - `ruff check .` = 0; `pyright .` = 0;
   - the full suite, with the same pass count as the baseline;
   - `prompt_fingerprint()` identical, and the snapshot test green;
   - `python -m tools.analyze_gate_replay --compare <scratch>/replay-base.json` exits 0, with
     `new_cache_files` the same as the baseline (`compare_failed` ignores the cache, so check it by hand);
   - the `-M --stat` rename check.
   
   Commit (on the user's go).

### Commit 2: anchor data paths under `var/`

TDD for the one new piece of logic, in `tests/test_config.py`:
- a `project_path(value)` helper in `config.py`: a relative value resolves against `PROJECT_ROOT`,
  an absolute one is unchanged, and the empty string stays empty (an empty `TRACE_LOG_PATH`
  disables the log);
- the defaults land under `PROJECT_ROOT / "var"`.

1. `config.py`:
   - `load_dotenv(PROJECT_ROOT / ".env")`, explicit;
   - `VAR_DIR`, `DATA_DIR`, `CHUNKS_DIR`, `XBRL_CACHE_DIR`;
   - `CHROMA_DIR` and `TRACE_LOG_PATH` pass through `project_path`, with defaults `var/chroma_db` and
     `var/trace_logs/traces.jsonl`.
2. Replace the cwd-relative constants with `config` values. Each keeps its module-level name, so
   existing monkeypatches of `module.CONST` still work:
   - `chunk_documents.DATA_DIR`/`CHUNKS_DIR`;
   - `edgar_ingest.OUTPUT_DIR`;
   - `index_chunks.CHUNKS_DIR`, `retrieval.CHUNKS_DIR`;
   - `xbrl_facts.CACHE_DIR`, `discover_tags.CACHE_DIR`;
   - `verify_period_labels.py:57`'s `DATA_DIR`.
   
   This removes the three-way `CHUNKS_DIR` duplication.
3. Delete `analyze_gate_replay.require_repo_root`, its call, its tests, and its use in
   `verify_gate_replay.py:35`. Delete BACKLOG line 54.
4. `.gitignore`: replace the five data entries with `var/`. pyright `exclude` and coverage `omit`: `var`.
5. **Local data** (untracked, the user's machine): `mkdir var` and `mv chroma_db chunks data xbrl_cache
   trace_logs var/`. `.env`'s `CHROMA_DIR=./chroma_db` must become `var/chroma_db`, or the line is
   deleted. I'll show that edit to the user rather than make it silently: it's their personal file.
   `.env.example` changes to match.
6. **Checks:**
   - ruff and pyright = 0; the full suite;
   - the replay `--compare` against the baseline exits 0, **and** `new_cache_files` equals the
     baseline's. That proves `var/xbrl_cache` was found and nothing was refetched. A missing
     `var/chroma_db` shows as hash drift;
   - `python -m tools.analyze_gate_replay --compare …` run from `tests/`, which proves the cwd
     bug is gone. `tools` resolves via the install.
   
   Commit (on the user's go).

### Commit 3: docs and usage strings

- Usage docstrings in every moved CLI (`python agent.py …` → `python -m sec_agent.agent.agent …`),
  including `discover_tags:17`, `formulas:14`, `retrieval:22` and `xbrl_facts:15`.
- `eval_harness.py:678`'s printed `analyze_citation_gate` hint, with its test at
  `test_eval_harness.py:663`.
- `CLAUDE.md` path mentions; `PROJECT_INDEX.md` Project Overview (layout, and setup
  `pip install -e .`); `.env.example` comments; `live-eval-verification.md:84`.
- The plan and review files, the index lines, and the map/BACKLOG updates (below).

## Testing and verification

Per-commit checks are listed under each commit above.

### End-to-end verification (after commit 2, low quota)

- `python tests/manual/verify_retrieval.py` (local Chroma, no quota),
  `python tests/manual/verify_mcp_server.py` (subprocess launch via `-m`), and
  `python tests/manual/verify_gate_replay.py`.
- One live question: `python -m sec_agent.agent.agent "How many full-time employees does Apple
  have?"` (a few Gemini requests). It exercises config, `.env`, Chroma, the XBRL cache and the
  trace log landing in `var/trace_logs`.
- Run `diff-cover coverage.xml --compare-branch=origin/master` by hand, with both bars and the new
  globs, before the user pushes.

## Docs and records

- Step 1 after approval: copy this plan to `docs/plans/2026-09-29-src-layout-move.md` and add an
  index line.
- Review file `docs/reviews/2026-09-29-src-layout-move.md` (Substantial) and its index line.
- Map: mark the prerequisite done, and record the widened critical core as a change to Decision 15.
  Update the BACKLOG workstream line (next: `agent.py` split).
- No decision file: the move was decided in the map. The widening is recorded there and in the
  commit body.

## Risks

- **A mock string missed by the rewrite** fails loudly (`patch` imports its target), so the full
  suite catches it. A wrongly rewritten file-name literal is the silent case, hence the explicit
  skip list and a grep for `sec_agent[.a-z_]*\.py"` afterwards.
- **A small file whose edits push it below git's 50% similarity** shows as a delete plus an add, so
  diff-cover counts every line. The `-M --stat` check catches it before commit.
- **A non-editable `pip install .`** would put `PROJECT_ROOT` in site-packages. Not supported: the
  project runs from its checkout, and the setup docs say `-e`.

## Plan review

`plan-reviewer` (Opus), 1 round, 11 findings, all folded in:
1. High: `verify_gate_replay.py` would break (imports `tools`, `require_repo_root`, cwd `QUESTIONS`). **Fixed**: `tools` is now installed; steps 1.6 and 2.3.
2. High: a different-cwd replay couldn't import `tools`. **Fixed**: `packages.find` includes `tools`.
3. Med: `verify_period_labels.py` cwd paths (`companies.json`, `./data`). **Fixed**: steps 1.6 and 2.2.
4. Med: subprocess tests don't inherit pytest's `pythonpath`. **Fixed**: `src` passed explicitly (step 1.4). The install is stated as required.
5. Med: missed paths (`test_prompts.py:104`, `test_model_input_snapshot.py:29`, `test_analyze_gate_replay.py:567`, `conftest.py:8`). **Fixed**: steps 1.3–1.5.
6. Med: the quote-anchored rewrite would corrupt `"agent.py"` literals. **Fixed**: skip list plus a post-grep.
7. Med: replay `--compare` ignores `new_cache_files`. **Fixed**: checked by hand in both commits.
8. Low: the baseline replay may seed the cache. **Fixed**: baseline `new_cache_files` recorded.
9. Low: commit 1 wasn't a pure move. **Fixed**: docs and docstrings moved to commit 3, with the rationale stated.
10. Low: `discover_tags:17` etc. are docstrings, not lazy imports, and `xbrl_facts:15` was missing. **Fixed**: moved to commit 3. The pyright rationale is corrected (two roots mean the hook finder).
11. Low: keep coverage `source = ["."]`. **Fixed**.

User suggestion at approval: move first, let the errors surface, then fix. **Adopted** as step 2a.
The error inventory becomes the completeness check. The scripted map still does the bulk, and the
silent breakages keep their explicit checklist.

## Review log

Full findings and dispositions: `docs/reviews/2026-09-29-src-layout-move.md`.

- **Round 1** (diff `5f543a4..6f62735`): code-review high, arch (opus), security, simplify (4 agents). 14 findings: 8 fixed (headline: `var/xbrl_cache` mkdir lacked `parents=True`; eval paths now defined once in `config`; config test now checks the real defaults), 5 verified with no fix needed (including a one-time "config differs" warning against pre-move baselines, because `chroma_dir` changed), 1 deferred (`tools` package rename → BACKLOG, user's call). Security found nothing.
- **Round 2** (delta vs `6f62735`): code-review low, arch (sonnet), security. 2 fixed: derived provenance pathspecs now resolve before `relative_to`, which symlinked or `subst` checkouts need; one stale doc pointer.
- **Round 3** (the pathspec fix): code-review low, security. Clean, so the review is closed.

## Addendum (2026-09-29, during execution)

- **Baseline replay raced the move.** Step 1's master baseline was still running when step 2
  moved the files. Its modules were already imported, but `companies.json` is read lazily, so the
  37 `pltr-inventory-turnover-fy2025-refusal` runs errored in the baseline. Commit 1's compare
  then showed 1174 runs identical (264 refused then and now) and flagged those 37 as drift. They
  were re-baselined on master in a temporary `git worktree` (with `chunks/` and `xbrl_cache/`
  copied, and `CHROMA_DIR`/`TRACE_LOG_PATH` pointed at the main checkout): 37 runs identical
  (14 refused then and now). Lesson: finish a baseline before touching the tree.
- **Namespace shadowing from `tests/`.** With the cwd set to `tests/`, `import tools` resolves to
  the `tests/tools` directory as a namespace package: the cwd entry comes first, and setuptools'
  editable finder only runs after the path finder. pytest is unaffected (`pythonpath = ["src", "."]`
  puts the root's regular package on the path). Commit 2's other-cwd check ran from the
  scratchpad instead. Accepted as a known limitation: don't run tools from inside `tests/`.
- **Missed in commit 1, fixed in commit 2:** `tests/manual/verify_gate_replay.py`'s cwd-relative
  `QUESTIONS` (plan step 1.6). It now uses `eval_harness.QUESTIONS_PATH`.
- **Added in commit 2:** eval provenance records `chroma_dir` relative to the project root
  (`_root_relative`). Reports are committed, and `CHROMA_DIR` is now absolute, so without this
  every report would carry the machine-specific checkout path.
- **The rewrite over-reached on prose strings** (docstrings, an error message, a `match=`, a
  file name), and those were reverted. It also turned CRLF into LF, and CRLF was restored. The
  two docstrings describing patch targets kept the new, accurate prefix.
