# Review: WP2, prompt fingerprint, eval provenance and compare script (commits df9a2be..c4ee23c)

Plan: `docs/plans/2026-09-24-wp2-prompt-provenance.md`. WP2 adds:
- a committed model-input snapshot;
- per-consumer prompt fingerprints;
- eval-report provenance;
- `compare_prompt_versions.py`;
- a judge nonstandard-output flag;
- model-facing-text checks in the live MCP verification.

The suite had 793 tests before WP2 and 888 at review start. The review ran the five-pass
`independent-review-pass` over `eaa1b45..HEAD`: 5 rounds, with ruff and pyright clean and
the full suite passing before each. No round changed what a model receives: the snapshot
test passed unregenerated throughout, and the fingerprint stayed `cc984387c3e8`.

## Round 1

### Pass 1: correctness (`/code-review`, high)
- [Fixed] A single `--base` or `--candidate` could default the other side to the same
  fingerprint and print a clean "B vs B" comparison.
- [Fixed] Explicit mode dropped a named dirty or unverified file silently. With one side
  emptied it exited 0. It now names each exclusion and exits 2 on an empty side.
- [Fixed] The consistency warnings ignored `backend` and `judge_model`, so a change of
  grader went unwarned.
- [Fixed] An un-added `.py` module left the tree looking clean. `git status` now counts
  untracked files under every provenance pathspec, not just `prompts/`.
- [Fixed] The snapshot-check subprocess had no timeout. It is now 300s, and a timeout is
  recorded as `snapshot_verified: null`.
- [Fixed] The lenient judge parse searched the whole output. A reason line that mentioned
  the other word hid the "lenient parse disagrees" marker for `**PASS**`. It now reads the
  first line naming PASS or FAIL.
- [Fixed] One try block covered both git calls, so a failing `git status` discarded a good
  SHA.
- [Fixed] `RESULTS_DIR` was relative to the working directory. It is now anchored to the
  file in both `compare_prompt_versions.py` and `eval_harness.py`, so the two agree.
- [Verified, kept] "Fix the judge parse itself (strip markdown before `startswith`)." That
  would change pass/fail outcomes. The plan keeps finding 7 evidence-gated, so only the
  flag lands in WP2.
- [Verified, kept] "`agent` hashes the text twice (constants plus snapshot section)." This
  is deliberate: the constant hashes still catch an edit on a code path no snapshot
  scenario reaches.

### Passes 2–3: comments, design (fresh subagent)
- [Fixed] **The REGRESSED-TOTAL threshold was computed in floating point.**
  `ceil(0.14 × 50)` is 8, not 7, and N = 100, 150, 200, 300 and 350 were also off by one,
  all in the lenient direction. It is now integer arithmetic (`TOTAL_DROP_PERCENT = 14`),
  with a parametrized test.
- [Fixed] Fingerprint mode dropped excluded reports silently. They are now named, within
  the `--since` window.
- [Fixed] Undecodable git output (`UnicodeDecodeError`) escaped `_git_state`'s except.
- [Fixed] The `-k` selector tied production code to a test name. The check now targets the
  exact node ID, and an `ast` test guards the name.
- [Fixed] The hash-seed determinism test ran two subprocesses. It now runs one, compared
  with the in-process render, which saved about 10s of the suite.
- [Fixed] A wrong comment in `prompts/agent_tools.py`: MCP tool order *is* covered, by the
  snapshot's `mcp` section. Also a stale "Checks 1-4" line in `verify_mcp_server.py`.
- [Fixed] `live-eval-verification.md` gained the PowerShell form of `UPDATE_SNAPSHOT=1`.
- [Verified, kept] Keeping `render_model_inputs` under `tests/` is fine: `prompts/` reads
  only the JSON file and never imports test code. Copying `_git` from
  `scripts/check_docs_health.py` is also fine, because the hook script stays standalone.
- Confirmed clean:
  - every constant is classified, and model text outside `prompts/` is in the snapshot;
  - CRLF tolerance;
  - provenance can't spend quota;
  - `passed` is computed before the judge flag.

### Pass 4: security (fresh subagent)
Nothing met the 80% bar. Checked:
- the subprocess argv, which is fixed and has no shell;
- that `UPDATE_SNAPSHOT` is stripped from the check's environment;
- that provenance `config` holds no API key, token or email;
- the snapshot file, grepped for secrets;
- that reports are loaded with `json.load` only.

### Pass 5: `/simplify` (4 agents)
- [Fixed] `default_pair` now fills the missing side relative to the given one, rather
  than refusing.
- [Fixed] One `select()` plus reporting helper serves both modes. `group_by_fingerprint`
  only groups.
- [Fixed] The integer threshold, and `dataclasses.replace` in a test instead of a file
  round-trip.

## Round 2
- [Fixed] (Pass 1) A failed `rev-parse` with a working `git status` recorded a clean tree
  with no SHA. This is fixed in round 2's pass 5: `is_excluded` now drops a report with no
  known SHA.
- [Fixed] (Pass 1) `--candidate <oldest>` printed a single-group table and exited 0. A
  named fingerprint with nothing to pair with now exits 2.
- [Fixed] (Passes 2–3) `--base` alone could pick an *older* candidate, running the
  comparison backwards. Defaults now run forward in time. The help text and a stale
  `ceil(0.14 x N)` comment were fixed, and the `*.py` pathspec's untracked-script
  tradeoff is now stated.
- [Fixed] (Passes 2–3) `select()`'s `r not in excluded` was quadratic dataclass equality.
  It is now one partition loop, and `_kept` is renamed `_select_and_report`.
- [Fixed] (Pass 5) The single-group case is handled before pairing, which leaves a single
  guard.
- Pass 4: clean.

## Rounds 3–5
- [Fixed] (Round 3, passes 2–3) `is_excluded` failed open on a missing `git_sha` key.
  After round 3's pass 5, any missing, empty or `"unknown"` SHA excludes. The module
  docstring (also the `--help` text) now lists this, and the pairing error names the
  empty side.
- [Fixed] (Round 4, pass 5) Eval-start warnings didn't cover every excluded state. For
  example, an unknown `git status` gave no warning, yet the report was later excluded.
  They now match. A shared predicate was declined: the compare CLI mustn't import the
  eval harness, and the warnings also cover a failed fingerprint.
- [Fixed] (Round 5) A docstring overclaimed "the same conditions". A drift-guard test now
  runs each provenance state through both `is_excluded` and `_provenance_warnings`.
- Passes 1 and 4 were clean in rounds 3–5.

## Live verification
- **`tests/manual/verify_mcp_server.py`:** every check passed on the committed tree, both
  the existing checks and the new model-facing-text checks. No Gemini quota used.
- **Model pin:** `gemini-flash-lite-latest` resolved to `gemini-3.5-flash-lite`
  (`resp.model_version`). The API accepts the concrete name, and it is now pinned in
  `.env`.
- **Spot-check:** `eval_harness.py --backend gemini --ids aapl-ai-risk` passed at SHA
  `2c3dbdd`. The report carries full provenance: clean tree, `snapshot_verified: true`,
  the pinned model, and agent fingerprint `cc984387c3e8`, unchanged from before the
  review. `compare_prompt_versions.py` lists it.
- **Panel baseline:** see the decision file.

## Outcome
- **Shipped:** WP2 as planned, plus 5 review-fix commits (`3d4ab61`..`2c3dbdd`).
- **Tests:** 917 at the end, up from 888 at review start. Diff coverage is 100% on WP2's
  own changes and 98% against `origin/master`.
- **Nothing filed to `BACKLOG.md`.** The two judgment calls kept (the judge parse
  unchanged, and no shared predicate) are recorded above.
- **Loop closed without a sixth round.** Each round's findings were smaller than the last.
  Round 5's passes 1–4 found only one docstring wording. Its pass 5 edits were a local
  variable binding and a new test, and weren't put through a sixth round.
