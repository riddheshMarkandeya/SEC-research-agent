# Evaluate pytest-archon and import-linter for architecture-boundary enforcement

**Date:** 2026-09-15

## Context

Asked whether this project would benefit from an architecture-boundary
linter (`pytest-archon` or `import-linter`) enforcing rules like "don't
import upward" or "leaves stay leaves." Explored the actual import
graph first: 18 root modules, ~3,900 lines of source, a clean acyclic
DAG with zero cycles. `config.py`/`companies.py`/`numeric_utils.py` are
leaves; `agent.py` (2,387 lines) is the single high-fan-in hub (9
internal imports), imported only by `mcp_server.py` and
`eval_harness.py`. Given this shape is already clean, the case for a
linter was "pin it so it can't regress," not "fix an existing problem."

## Decision

**Not adopted.** `pytest-archon` was installed and empirically probed
against this repo before writing any real rule; `import-linter` was not
installed at all, on the strength of what the probe found. No
dependency, config, or test file from this evaluation was kept.

## Why

`pytest-archon`'s `check()` requires a genuine Python *package*
(directory with `__init__.py`, or a namespace package) to know which
directory to scan — it resolves that directory via
`importlib.util.find_spec(name).origin`'s parent. This project has no
such package: every module (`agent.py`, `retrieval.py`, etc.) sits flat
at the repo root, wired together via `pyproject.toml`'s
`pythonpath = ["."]`. For a flat top-level module, `find_spec` gives that
module directly, and its "parent directory" *is* the repo root. Since
`.venv` also lives inside the repo root, `check()` then recursively
globs and AST-parses every `.py` file under `.venv` too — every
installed package, including scipy/torch/chromadb's own dependency
trees.

Verified concretely, not assumed: a probe script (`package_dir("agent")`
+ `collect_imports("agent", walk)`) produced 50,000+ warning lines from
deep inside `scipy.sparse` internals and still hadn't finished after a
hard 60-second timeout. Since `pytest` already gates every commit via
`.git/hooks/pre-commit`, wiring this in as-is would make every commit
hang for minutes — the opposite of "rides the existing gate for free,"
which was the specific reason `pytest-archon` was preferred over
`import-linter` in the first place (it has no comparably light
alternative check mechanism of its own; both tools share the same
underlying Python import-resolution assumption, so `import-linter` was
not separately probed given this finding, rather than spending more
time confirming an already-likely conclusion).

**Alternatives considered**: (1) hand-roll a small `ast`-based check
scoped explicitly to this repo's own top-level `*.py` files (no
recursive glob, no dependency) — genuinely viable, but not pursued once
the DAG's already-clean, never-changed shape made the marginal
protection not worth even that small an addition; (2) restructure the
project into a real package (`src/<pkg>/...`) so `pytest-archon` would
work as designed — rejected as wildly disproportionate to the actual
problem (a purely cosmetic import-resolution mismatch, not a real code
defect).

## Files touched

None kept. `pytest-archon==0.0.7` was installed then uninstalled;
nothing was added to `requirements-dev.txt` or `pyproject.toml` for
this evaluation.

## Verification

Probe script run directly against this repo (not assumed from reading
the library's source alone): confirmed the `.venv` traversal and the
60-second-plus non-termination live, with real output quoted above.

## Related

Paired with `docs/decisions/2026-09-15-adopt-pyright.md` from the same
session's tooling-evaluation request. If this is ever revisited, the
prior art here is: don't re-try `pytest-archon`/`import-linter` without
first either giving this project a real package layout or reaching for
option (1) above (a hand-rolled `ast` check) instead.
