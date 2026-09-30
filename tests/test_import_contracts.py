"""The import-linter contracts in pyproject.toml ([tool.importlinter]): no
import cycles between sibling modules or subpackages, and nothing outside
sec_agent.tools imports it. Static imports only -- a dynamic import_module()
is invisible to them."""

import subprocess
import sys

import pytest

from sec_agent.config import PROJECT_ROOT

# lint_imports() puts the cwd on sys.path and reconfigures logging (which
# disables every existing logger), so it runs in a child process.
LINT = (
    "import sys\n"
    "from importlinter.cli import lint_imports\n"
    "sys.exit(lint_imports(config_filename=sys.argv[1], limit_to_contracts=(sys.argv[2],), no_cache=True))\n"
)


@pytest.mark.parametrize("contract", ["acyclic", "tools-leaf"])
def test_import_contract_is_kept(contract):
    result = subprocess.run(
        [sys.executable, "-c", LINT, str(PROJECT_ROOT / "pyproject.toml"), contract],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
